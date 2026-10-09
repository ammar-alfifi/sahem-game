"""
سهم — الخادم الرئيسي: FastAPI + Webhook البوت + REST API للتطبيق المصغّر + الجدولة
"""
import asyncio
import collections
import logging
import os
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiogram.types import Update

from . import services, market_data
from . import duels as duels_mod
from . import league as league_mod
from . import quests as quests_mod
from .constants import ALL_SYMBOLS
from .config import get_webhook_secret, get_admin_token, cors_origins, APP_BUILD
from .db import init_db
from . import bot as bot_module
from .telegram_client import get_bot, close_bot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("sahem.main")

WEBAPP_DOMAIN = os.getenv("WEBAPP_DOMAIN", "")  # لضبط webhook explicitly عند النشر الذاتي


# ---------- المهام المجدولة ----------
async def job_refresh_prices():
    try:
        n = await asyncio.to_thread(market_data.refresh_prices)
        log.info(f"refreshed prices: {n}")
    except Exception as e:
        log.warning(f"price refresh failed: {e}")


async def job_resolve_predictions():
    try:
        events = services.resolve_due_predictions()
        if events:
            log.info(f"resolved {len(events)} predictions")
            await bot_module.notify_prediction_results(events)
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


async def job_remind_duels():
    """تذكير لاعبي مبارزة نشطة قبل انتهاء صلاحيتها (مرة واحدة لكل مبارزة)."""
    try:
        await duels_mod.remind_due_duels()
    except Exception as e:
        log.warning(f"remind_duels failed: {e}")


async def job_remind_daily():
    """تذكير يومي بالحضور للنشطين فقط — مرة واحدة لكل مستخدم في اليوم."""
    try:
        users = services.due_daily_reminders()
        if users:
            log.info(f"daily reminders queued: {len(users)}")
            await bot_module.notify_daily_reminders(users)
    except Exception as e:
        log.warning(f"remind_daily failed: {e}")


async def job_league_award():
    try:
        res = league_mod.award_weekly()
        winners = res.get("winners", [])
        log.info(f"league award: {len(winners)} winners")
        if not winners:
            return
        bot = get_bot()
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for w in league_mod.telegram_ids_for([x["user_id"] for x in winners], res.get("period_start")):
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
    except Exception as e:
        log.warning(f"league award failed: {e}")


scheduler = AsyncIOScheduler(timezone="UTC")


async def job_autoseed():
    """تخزين البيانات التاريخية تلقائياً عند أول إقلاع (قرص الخطة المجانية مؤقت)."""
    try:
        from .db import db
        with db() as conn:
            n = conn.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
        if n < 100:
            log.info("seeding historical archives (first boot)...")
            total = await asyncio.to_thread(market_data.seed_archives, 4)
            log.info(f"seeded {total} candles")
    except Exception as e:
        log.warning(f"autoseed failed: {e}")


async def _polling_loop(bot, dp):
    """Long Polling يدوي — بديل محلي عند غياب رابط عام لتلقي تحديثات تيليجرام."""
    offset = 0
    while True:
        try:
            updates = await bot.get_updates(offset=offset, timeout=30)
            for upd in updates:
                offset = upd.update_id + 1
                try:
                    await dp.feed_webhook_update(bot, upd)
                except Exception:
                    _DIAG["errors"].append(traceback.format_exc()[-1800:])
                    log.exception("polling update failed")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"polling failed: {e}")
            await asyncio.sleep(3)


_POLL_TASK: dict = {"task": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    bot = get_bot()
    _get_dp()

    secret = get_webhook_secret()
    if not secret:
        log.warning("WEBHOOK_SECRET غير مضبوط — سيُرفض الويب هوك بالكامل. اضبطه في الإنتاج.")

    # ضبط webhook في بيئات النشر (Render يوفر الحقل الجزئي)
    base_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBAPP_DOMAIN") or WEBAPP_DOMAIN
    if base_url and not base_url.startswith("http"):
        base_url = "https://" + base_url
    mode_polling = False
    if base_url and secret:
        webhook_url = base_url.rstrip("/") + "/webhook"
        try:
            await bot.set_webhook(webhook_url, drop_pending_updates=True, secret_token=secret)
            log.info(f"webhook set: {webhook_url}")
        except Exception as e:
            # فشل ضبط webhook لا يجب أن يُسقط الخدمة كلها
            log.warning(f"set_webhook failed: {e}")
            mode_polling = True
    else:
        # لا يوجد رابط عام (تشغيل محلي مثلاً): الاعتماد على Long Polling
        # وإلا فلن يصل أي تحديث من تيليجرام والبوت يظهر صامتاً (لا يستجيب لـ /start).
        mode_polling = True
    if mode_polling:
        try:
            await bot.delete_webhook(drop_pending_updates=False)
        except Exception:
            pass
        dp = _get_dp()
        _POLL_TASK["task"] = asyncio.create_task(_polling_loop(bot, dp))
        log.warning("WEBHOOK غير مضبوط — تشغيل بوضع Long Polling (مناسب للتطوير فقط)")

    # قائمة الأوامر المقترحة تلقائياً عند كتابة «/»
    try:
        from aiogram.types import BotCommand
        # قائمة مختصرة (U18) — بقية الأوامر تعمل لكن لا تزدحم القائمة
        commands = [
            ("start", "🚀 القائمة الرئيسية"),
            ("arcade", "⚡ جولة أركيد"),
            ("leaderboard", "🏆 لوحة الصدارة"),
            ("portfolio", "💼 محفظتك ورصيدك"),
            ("help", "📖 شرح جميع الأوامر"),
        ]
        await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in commands])
        log.info(f"my_commands set: {len(commands)} commands")
    except Exception as e:
        log.warning(f"set_my_commands failed: {e}")

    # مجدول: تحديث الأسعار كل ساعة + تسوية التوقعات + صلاحية المبارزات + دوري الجمعة
    scheduler.add_job(job_refresh_prices, "interval", minutes=60, id="refresh_prices")
    scheduler.add_job(job_resolve_predictions, "interval", minutes=60, id="resolve_predictions")
    scheduler.add_job(job_resolve_duels, "interval", minutes=30, id="resolve_duels")
    scheduler.add_job(job_remind_duels, "interval", minutes=20, id="remind_duels")
    scheduler.add_job(job_remind_daily, "cron", hour=18, minute=0, timezone="UTC", id="remind_daily")
    scheduler.add_job(job_league_award, "cron", day_of_week="fri", hour=0, minute=5,
                      timezone="Asia/Riyadh", id="league_award")
    scheduler.start()

    # تحديث أولي غير حاجز + تهيئة التاريخ تلقائياً إذا كان فارغاً
    asyncio.create_task(job_refresh_prices())
    asyncio.create_task(job_autoseed())

    yield

    scheduler.shutdown()
    if _POLL_TASK["task"]:
        _POLL_TASK["task"].cancel()
    await close_bot()


app = FastAPI(title="سهم — Sahem Game API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),  # اضبط CORS_ORIGINS لتشديده على نطاق Cloudflare
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- webhook بوت تيليجرام ----------
WEBHOOK_SECRET = get_webhook_secret()
_dp_holder = {"dp": None}
_DIAG = {"errors": collections.deque(maxlen=8), "updates": collections.deque(maxlen=15),
         "gate": collections.deque(maxlen=10)}


def _get_dp():
    """Dispatcher واحد فقط — إنشاء Router أكثر من مرة يرفع 'Router is already attached'."""
    if _dp_holder["dp"] is None:
        from aiogram import Dispatcher
        dp = Dispatcher()
        bot_module.register_router(dp)
        _dp_holder["dp"] = dp
    return _dp_holder["dp"]


@app.post("/webhook")
async def telegram_webhook(request: Request, background: BackgroundTasks):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not WEBHOOK_SECRET or secret != WEBHOOK_SECRET:
        raise HTTPException(403, "bad secret")
    try:
        update = Update.model_validate(await request.json())
    except Exception:
        raise HTTPException(400, "invalid update")
    background.add_task(_process_update, update.model_dump(by_alias=True))
    return {"ok": True}


async def _process_update(payload: dict):
    msg = payload.get("message") or {}
    upd_from = msg.get("from") or {}
    cb = payload.get("callback_query") or {}
    kind = "message" if payload.get("message") else ("callback" if cb else "other")
    uid = upd_from.get("id") or ((cb.get("from") or {}).get("id"))
    txt = (msg.get("text") or (cb.get("data") or ""))[:40]
    _DIAG["updates"].append(f"{kind} uid={uid} '{txt}'")
    bot = get_bot()
    dp = _get_dp()
    update = Update.model_validate(payload)
    try:
        await dp.feed_webhook_update(bot, update)
    except Exception:
        _DIAG["errors"].append(traceback.format_exc()[-1800:])
        raise


@app.get("/diag")
async def diag(x_admin: Optional[str] = Header(None)):
    """لوحة تشخيص — مغلقة تماماً ما لم يُضبط ADMIN_TOKEN (أو WEBHOOK_SECRET)."""
    token = get_admin_token()
    if not token or x_admin != token:
        raise HTTPException(403, "forbidden")
    return {
        "build": APP_BUILD,
        "dp_attached": _dp_holder["dp"] is not None,
        "updates": list(_DIAG["updates"]),
        "errors": list(_DIAG["errors"]),
        "gate": list(_DIAG["gate"]),
    }


@app.post("/api/appdiag")
async def app_diag(data: dict):
    # ملاحظة: بيانات تشخيص غير موثوقة من العميل — نحدّد الحجم ونتجاهل أي محتوى ضخم
    if len(data) > 40:
        return {"ok": False}
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


@app.get("/health")
async def health():
    return {"status": "ok", "build": APP_BUILD, "time": services._now_iso()}


# ---------- نماذج المدخلات ----------
class TradeIn(BaseModel):
    symbol: str
    side: str
    quantity: float


class PredictIn(BaseModel):
    symbol: str
    direction: str


class ArcadeStartIn(BaseModel):
    mode: str = "full"  # full / quick


class ArcadeTradeIn(BaseModel):
    side: str
    quantity: float


class DuelJoinIn(BaseModel):
    code: str = ""


class LeagueResolvedIn(BaseModel):
    period_start: str


# ---------- API التطبيق المصغّر ----------
def _auth(request: Request, authorization: Optional[str]) -> int:
    if authorization and authorization.startswith("Bearer "):
        uid = services.auth_from_token(authorization[7:])
        if uid:
            # آخر تواجد (للتذكيرات الذكية) — لا يكتب إلا كل 10 دقائق
            services.touch_last_seen(uid)
            return uid
    raise HTTPException(401, "غير مصرح — افتح التطبيق من داخل بوت تيليجرام")


def _auth_optional(request: Request, authorization: Optional[str]) -> Optional[int]:
    try:
        return _auth(request, authorization)
    except HTTPException:
        return None


@app.post("/api/auth")
async def api_auth(request: Request):
    """يستقبل initData من تيليجرام ويعيد توكن موقّع."""
    data = await request.json()
    init_data = data.get("initData", "")
    user = services.auth_from_initdata(init_data)
    if not user:
        raise HTTPException(401, "initData غير صحيح")
    u = services.get_or_create_user(user["id"], services.pick_tg_name(user))
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
        "daily_streak": u.get("daily_streak", 0),
        "pred_streak": u.get("pred_streak", 0) or 0,
        "daily_claimed_today": (u.get("last_daily") or "") == services.utc_today(),
        "daily_next_coins": services.daily_next_coins(u.get("daily_streak", 0) or 0),
        "badges": services.compute_badges(uid),
        "positions": services.get_portfolio(uid),
    }


@app.post("/api/trade")
async def api_trade(body: TradeIn, request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    if body.symbol not in ALL_SYMBOLS:
        raise HTTPException(400, "رمز غير معروف")
    if body.side.lower() not in ("buy", "sell"):
        raise HTTPException(400, "اتجاه غير صحيح")
    res = services.execute_trade(uid, body.symbol, body.side, float(body.quantity))
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "فشل التنفيذ"))
    return res


@app.get("/api/predictions")
async def api_predictions(request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    return services.get_pending_predictions(uid)


@app.get("/api/predictions/history")
async def api_predictions_history(request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    return services.get_prediction_history(uid)


@app.post("/api/predict")
async def api_predict(body: PredictIn, request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    if body.symbol not in ALL_SYMBOLS:
        raise HTTPException(400, "رمز غير معروف")
    res = services.create_prediction(uid, body.symbol, body.direction)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "فشل التوقع"))
    return res


@app.post("/api/daily")
async def api_daily(request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    res = services.claim_daily(uid)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "تعذّر الاستلام"))
    return res


# ---------- الأركيد ----------
@app.post("/api/arcade/start")
async def api_arcade_start(request: Request, body: ArcadeStartIn | None = None,
                           authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    err = services.arcade_rate_error(uid)
    if err:
        raise HTTPException(429, err)
    mode = (body.mode if body else "full")
    quick = (mode == "quick")
    rnd = services.start_arcade_round(uid, quick=quick)
    if not rnd:
        raise HTTPException(503, "لا توجد بيانات تاريخية بعد — حاول لاحقاً")
    return rnd


@app.get("/api/arcade/active")
async def api_arcade_active(request: Request, authorization: Optional[str] = Header(None)):
    """جولة معلّقة بانتظار الاستكمال (بعد إغلاق التطبيق قبل إنهائها)."""
    uid = _auth(request, authorization)
    return {"active": services.get_active_arcade(uid)}


@app.get("/api/arcade/{round_id}/resume")
async def api_arcade_resume(round_id: int, request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    res = services.resume_arcade(round_id, uid)
    if not res:
        raise HTTPException(404, "لا جولة لاستكمالها")
    return res


@app.get("/api/arcade/{round_id}/step")
async def api_arcade_step(round_id: int, request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    step = services.get_arcade_step(round_id, uid)
    if not step:
        raise HTTPException(404, "الجولة غير موجودة")
    return step


@app.post("/api/arcade/{round_id}/trade")
async def api_arcade_trade(round_id: int, body: ArcadeTradeIn, request: Request,
                           authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    res = services.arcade_trade(round_id, uid, body.side, float(body.quantity))
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "فشل التنفيذ"))
    return res


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
    """مقياس واحد للصدارة والدوري (الخطة 4.2): العائد الزائد + 2 لكل توقع صحيح."""
    ps = league_mod.current_period()[0]
    rows = league_mod.standings(ps, limit=20)
    champs = league_mod.champions_map([r["user_id"] for r in rows])
    for r in rows:
        r["weekly_value"] = r["score"]  # مرادف للتوافق مع الواجهة
        r["champion"] = r["user_id"] in champs
    return rows


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
async def api_duel_join(body: DuelJoinIn, request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    res = duels_mod.join_duel(uid, str(body.code).strip())
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


# ---------- التحديات اليومية/الأسبوعية ----------
@app.get("/api/quests")
async def api_quests(request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth(request, authorization)
    return quests_mod.get_quests(uid)


# ---------- الدوري الأسبوعي (المرحلة 2) ----------
@app.get("/api/league")
async def api_league(request: Request, authorization: Optional[str] = Header(None)):
    uid = _auth_optional(request, authorization)
    ps, pe = league_mod.current_period()
    prev_start = league_mod.current_period(datetime.fromisoformat(ps) - timedelta(days=7))[0]
    prizes = []
    for i in range(1, len(league_mod.PRIZES) + 1):
        coins, xp = league_mod.prize_for_rank(i)
        prizes.append({"rank": i if i <= 3 else "4-10", "coins": coins, "xp": xp})
    return {
        "period_start": ps,
        "period_end": pe,
        "countdown": league_mod.week_countdown(),
        "standings": league_mod.standings(ps, limit=10),
        "me": league_mod.my_view(uid, ps),
        "players": league_mod.players_count(ps),
        "champion": league_mod.last_champion(prev_start),
        "prizes": prizes,
        "rules": "المجموعة = مجموع عائدك الزائد في جولات الأركيد المكتملة + 2 نقطة لكل توقع صحيح — على الأقل 3 جولات لجائزة",
    }


@app.post("/api/league/resolved")
async def api_league_resolved(body: LeagueResolvedIn, request: Request,
                              authorization: Optional[str] = Header(None)):
    """سجل النتائج لفترة معينة (يسأل واجهة «آخر بطل»)."""
    _auth(request, authorization)
    from .db import db
    with db() as conn:
        rows = conn.execute(
            """SELECT lr.rank, lr.score, lr.prize_coins, u.username
               FROM league_results lr JOIN users u ON u.id = lr.user_id
               WHERE lr.period_start=? ORDER BY lr.rank LIMIT 10""",
            (body.period_start,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- التطبيق المصغّر (ملفات ثابتة) ----------
_WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
if os.path.isdir(_WEB_DIR):
    app.mount("/app", StaticFiles(directory=_WEB_DIR, html=True), name="webapp")
