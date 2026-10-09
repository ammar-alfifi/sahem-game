"""
سهم — الخادم الرئيسي: FastAPI + Webhook البوت + REST API للتطبيق المصغّر + الجدولة
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiogram import Bot, Dispatcher
from aiogram.types import Update

from . import services, market_data
from . import duels as duels_mod
from . import league as league_mod
from .constants import ALL_SYMBOLS
from .config import get_bot_token
from .db import init_db
from . import bot as bot_module

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("sahem.main")

WEBAPP_DOMAIN = os.getenv("WEBAPP_DOMAIN", "")  # لضبط webhook explicitly عند النشر الذاتي


async def job_refresh_prices():
    try:
        n = market_data.refresh_prices()
        log.info(f" refreshed prices: {n}")
    except Exception as e:
        log.warning(f"price refresh failed: {e}")


async def job_resolve_predictions():
    try:
        n = services.resolve_due_predictions()
        if n:
            log.info(f"resolved {n} predictions")
        # إشعار المستخدمين (النتائج محفوظة؛ MVP: بدون رسائل فردية)
    except Exception as e:
        log.warning(f"resolve_predictions failed: {e}")


async def job_resolve_duels():
    try:
        n, events = duels_mod.resolve_due_duels()
        if n:
            log.info(f"duels resolved/expired: {n}")
        for ev in events:
            asyncio.create_task(duels_mod.notify_duel_event(ev))
    except Exception as e:
        log.warning(f"resolve_duels failed: {e}")


async def job_league_award():
    try:
        res = league_mod.award_weekly()
        log.info(f"league award: {len(res.get('winners', []))} winners")
        # إشعار المكرمين بالبوت (حسب telegram_id)
        try:
            from aiogram import Bot
            bot = Bot(get_bot_token())
            medals = {1: "🥇", 2: "🥈", 3: "🥉"}
            for w in league_mod.winners_telegram_ids():
                try:
                    await bot.send_message(
                        w["telegram_id"],
                        f"🏆 الدوري الأسبوعي — الجوائز وصلت!\n"
                        f"{medals.get(w['rank'], '#' + str(w['rank']))} جئت مركز {w['rank']}\n"
                        f"🎁 جائزتك: {w['prize_coins']:,} عملة وهمية + XP إضافي\n"
                        "الأسبوع الجديد بدأ — افلح من جديد!",
                    )
                except Exception:
                    pass
            await bot.session.close()
        except Exception:
            pass
    except Exception as e:
        log.warning(f"league award failed: {e}")


scheduler = AsyncIOScheduler(timezone="UTC")


async def job_autoseed():
    """تخزين البيانات التاريخية تلقائياً عند أول إقلاع (قرص الخطة المجانية مؤقت)."""
    try:
        from .db import get_db
        conn = get_db()
        n = conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
        conn.close()
        if n < 100:
            log.info("seeding historical archives (first boot)...")
            total = market_data.seed_archives(years=4)
            log.info(f"seeded {total} candles")
    except Exception as e:
        log.warning(f"autoseed failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    bot = Bot(get_bot_token())
    dp = _get_dp()

    # ضبط webhook في بيئات النشر (Render يوفر الحقل الجزئي)
    base_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBAPP_DOMAIN")
    if base_url and not base_url.startswith("http"):
        base_url = "https://" + base_url
    if base_url:
        webhook_url = base_url.rstrip("/") + "/webhook"
        await bot.set_webhook(webhook_url, drop_pending_updates=True, secret_token=os.getenv("WEBHOOK_SECRET"))
        log.info(f"webhook set: {webhook_url}")

    # مجدول: تحديث الأسعار كل ساعة + تسوية التوقعات + صلاحية المبارزات + دوري الجمعة
    scheduler.add_job(job_refresh_prices, "interval", minutes=60, id="refresh_prices")
    scheduler.add_job(job_resolve_predictions, "interval", minutes=60, id="resolve_predictions")
    scheduler.add_job(job_resolve_duels, "interval", minutes=30, id="resolve_duels")
    scheduler.add_job(job_league_award, "cron", day_of_week="fri", hour=0, minute=5,
                      timezone="Asia/Riyadh", id="league_award")
    scheduler.start()

    # تحديث أولي غير حاجز + تهيئة التاريخ تلقائياً إذا كان فارغاً
    asyncio.create_task(job_refresh_prices())
    asyncio.create_task(job_autoseed())

    async def feed_updates():  # تجعل التطبيق منظم للتحديثات عبر webhook endpoint
        pass

    yield

    scheduler.shutdown()
    await bot.session.close()


app = FastAPI(title="سهم — Sahem Game API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # MVP: يُشدّد لاحقاً على دومين Cloudflare الخاص بك
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- webhook بوت تيليجرام ----------
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
_dp_holder = {"dp": None}


def _get_dp() -> Dispatcher:
    """Dispatcher واحد فقط — إنشاء Router أكثر من مرة يرفع 'Router is already attached'."""
    if _dp_holder["dp"] is None:
        bot = Bot(get_bot_token())
        dp = Dispatcher()
        bot_module.register_router(dp)
        _dp_holder["dp"] = dp
    return _dp_holder["dp"]


@app.post("/webhook")
async def telegram_webhook(request: Request, background: BackgroundTasks):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        raise HTTPException(403, "bad secret")
    try:
        update = Update.model_validate(await request.json(), context={"bot": None})
    except Exception:
        raise HTTPException(400, "invalid update")
    background.add_task(_process_update, update.model_dump(by_alias=True))
    return {"ok": True}


import collections as _collections
import traceback as _traceback
_DIAG = {"errors": _collections.deque(maxlen=8), "updates": _collections.deque(maxlen=15),
         "gate": _collections.deque(maxlen=10)}


async def _process_update(payload: dict):
    msg = payload.get("message") or {}
    upd_from = msg.get("from") or msg.get("from_user") or {}
    cb = payload.get("callback_query") or {}
    kind = "message" if payload.get("message") else ("callback" if cb else "other")
    uid = upd_from.get("id") or ((cb.get("from") or cb.get("from_user") or {}).get("id"))
    txt = (msg.get("text") or (cb.get("data") or ""))[:40]
    _DIAG["updates"].append(f"{kind} uid={uid} '{txt}'")
    bot = Bot(get_bot_token())
    dp = _get_dp()
    from aiogram.types import Update
    update = Update.model_validate(payload)
    try:
        await dp.feed_webhook_update(bot, update)
    except Exception:
        _DIAG["errors"].append(_traceback.format_exc()[-1800:])
        raise
    finally:
        await bot.session.close()


@app.get("/diag")
async def diag(x_admin: Optional[str] = Header(None)):
    if WEBHOOK_SECRET and x_admin != WEBHOOK_SECRET:
        raise HTTPException(403, "forbidden")
    return {
        "build": BUILD_STAMP,
        "dp_attached": _dp_holder["dp"] is not None,
        "updates": list(_DIAG["updates"]),
        "errors": list(_DIAG["errors"]),
        "gate": list(_DIAG["gate"]),
    }


@app.post("/api/appdiag")
async def app_diag(data: dict):
    _DIAG["gate"].append({
        "t": services._now_iso(),
        "reason": str(data.get("reason", ""))[:200],
        "hasTg": data.get("hasTg"),
        "initDataLen": data.get("initDataLen"),
        "unsafeUser": data.get("unsafeUser"),
        "platform": data.get("platform"),
        "url": str(data.get("url", ""))[:200],
        "ua": str(data.get("ua", ""))[:150],
    })
    return {"ok": True}


@app.get("/")
async def root():
    return {"name": "سهم API", "docs": "/docs", "app": "/app/"}


BUILD_STAMP = "2.1-duels-polish"

@app.get("/health")
async def health():
    return {"status": "ok", "build": BUILD_STAMP, "time": services._now_iso()}


# ---------- API التطبيق المصغّر ----------
def _auth(request: Request, authorization: Optional[str]) -> int:
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        uid = services.auth_from_token(token)
        if uid:
            return uid
    raise HTTPException(401, "غير مصرح — افتح التطبيق من داخل بوت تيليجرام")


@app.post("/api/auth")
async def api_auth(request: Request):
    """يستقبل initData من تيليجرام ويعيد توكن موقّع."""
    data = await request.json()
    init_data = data.get("initData", "")
    user = services.auth_from_initdata(init_data)
    if not user:
        raise HTTPException(401, "initData غير صحيح")
    u = services.get_or_create_user(user["id"], user.get("username"))
    auth = services.make_auth(u["id"])
    return {**auth, "user": {k: u[k] for k in ("id", "username", "coins_balance", "level", "xp")}}


@app.get("/api/prices")
async def api_prices():
    symbols = list(ALL_SYMBOLS.keys())
    prices = market_data.get_cached_prices(symbols)
    out = []
    for sym, info in ALL_SYMBOLS.items():
        p = prices.get(sym)
        out.append({
            "symbol": sym,
            "name": info["name"],
            "market": info["market"],
            "price": p["price"] if p else None,
            "change_pct": p["change_pct"] if p else None,
            "updated_at": p["updated_at"] if p else None,
        })
    return out


@app.get("/api/portfolio")
async def api_portfolio(request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    u = services.get_user_by_id(uid)
    if not u:
        raise HTTPException(401, "المستخدم غير موجود")
    return {
        "balance": u["coins_balance"],
        "level": u["level"],
        "xp": u["xp"],
        "positions": services.get_portfolio(uid),
    }


@app.post("/api/trade")
async def api_trade(request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    data = await request.json()
    symbol = data.get("symbol", "")
    side = data.get("side", "")
    quantity = float(data.get("quantity", 0))
    if symbol not in ALL_SYMBOLS:
        raise HTTPException(400, "رمز غير معروف")
    if quantity <= 0:
        raise HTTPException(400, "الكمية يجب أن تكون أكبر من صفر")
    return services.execute_trade(uid, symbol, side, quantity)


@app.get("/api/predictions")
async def api_predictions(request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    return services.get_pending_predictions(uid)


@app.post("/api/predict")
async def api_predict(request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    data = await request.json()
    symbol = data.get("symbol", "")
    direction = data.get("direction", "")
    if symbol not in ALL_SYMBOLS:
        raise HTTPException(400, "رمز غير معروف")
    return services.create_prediction(uid, symbol, direction)


# ---------- الأركيد ----------
@app.post("/api/arcade/start")
async def api_arcade_start(request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    rnd = services.start_arcade_round(uid)
    if not rnd:
        raise HTTPException(503, "لا توجد بيانات تاريخية بعد — حاول لاحقاً")
    return rnd


@app.get("/api/arcade/{round_id}/step")
async def api_arcade_step(round_id: int, request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    step = services.get_arcade_step(round_id, uid)
    if not step:
        raise HTTPException(404, "الجولة غير موجودة")
    return step


@app.post("/api/arcade/{round_id}/trade")
async def api_arcade_trade(round_id: int, request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    data = await request.json()
    return services.arcade_trade(round_id, uid, data.get("side", ""), float(data.get("quantity", 0)))


@app.post("/api/arcade/{round_id}/finish")
async def api_arcade_finish(round_id: int, request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    res = services.finish_arcade_round(round_id, uid)
    if not res:
        raise HTTPException(404, "الجولة غير موجودة")
    d = res.get("duel")
    if d and d.get("state") == "done":
        asyncio.create_task(duels_mod.notify_duel_result(d["duel"]["id"]))
    return res


@app.get("/api/leaderboard")
async def api_leaderboard():
    return services.weekly_leaderboard(20)


# ---------- المبارزات 1v1 (المرحلة 2) ----------
@app.get("/api/duels")
async def api_duels(request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    return duels_mod.list_duels(uid)


@app.post("/api/duels")
async def api_duel_create(request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    res = duels_mod.create_duel(uid)
    if not res.get("ok"):
        raise HTTPException(400, res["error"])
    return res


@app.post("/api/duels/join")
async def api_duel_join(request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    data = await request.json()
    res = duels_mod.join_duel(uid, str(data.get("code", "")).strip())
    if not res.get("ok"):
        raise HTTPException(400, res["error"])
    asyncio.create_task(duels_mod.notify_challenger_joined(res["duel"]["id"]))
    return res


@app.post("/api/duels/{duel_id}/play")
async def api_duel_play(duel_id: int, request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    res = duels_mod.play_duel_round(uid, duel_id)
    if not res.get("ok"):
        raise HTTPException(400, res["error"])
    return res


# ---------- الدوري الأسبوعي (المرحلة 2) ----------
def _auth_optional(request: Request, authorization: Optional[str]) -> Optional[int]:
    try:
        return _auth(request, authorization)
    except HTTPException:
        return None


@app.get("/api/league")
async def api_league(request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth_optional(request, authorization)
    ps, pe = league_mod.current_period()
    return {
        "period_start": ps,
        "period_end": pe,
        "countdown": league_mod.week_countdown(),
        "standings": league_mod.standings(ps, limit=10),
        "me": league_mod.my_view(uid, ps),
        "players": league_mod.players_count(ps),
        "prizes": [
            {"rank": 1, "coins": 50000, "xp": 500},
            {"rank": 2, "coins": 30000, "xp": 300},
            {"rank": 3, "coins": 20000, "xp": 200},
            {"rank": "4-10", "coins": 10000, "xp": 100},
        ],
        "rules": "المجموعة = مجموع عائدك الزائد في جولات الأركيد + 2 نقطة لكل توقع صحيح — على الأقل 3 جولات لجائزة",
    }


@app.post("/api/league/resolved")
async def api_league_resolved(request: Request, authorization: Optional[str] = Header(None)):
    """سجل النتائج لفترة معينة (يسأل واجهة «آخر بطل»)."""
    uid = _auth(request, authorization)
    data = await request.json()
    ps = data.get("period_start")
    from .db import get_db
    conn = get_db()
    rows = conn.execute(
        """SELECT lr.rank, lr.score, lr.prize_coins, u.username
           FROM league_results lr JOIN users u ON u.id = lr.user_id
           WHERE lr.period_start=? ORDER BY lr.rank LIMIT 10""",
        (ps,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------- التطبيق المصغّر (ملفات ثابتة) ----------
if os.path.isdir("web"):
    app.mount("/app", StaticFiles(directory="web", html=True), name="webapp")
