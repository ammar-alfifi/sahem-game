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

    # مجدول: تحديث الأسعار كل ساعة + تسوية التوقعات
    scheduler.add_job(job_refresh_prices, "interval", minutes=60, id="refresh_prices")
    scheduler.add_job(job_resolve_predictions, "interval", minutes=60, id="resolve_predictions")
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
    background.add_task(_process_update, update.dict())
    return {"ok": True}


async def _process_update(payload: dict):
    bot = Bot(get_bot_token())
    dp = _get_dp()
    from aiogram.types import Update
    update = Update.model_validate(payload)
    try:
        await dp.feed_webhook_update(bot, update)
    finally:
        await bot.session.close()


@app.get("/")
async def root():
    return {"name": "سهم API", "docs": "/docs", "app": "/app/"}


@app.get("/health")
async def health():
    return {"status": "ok", "time": services._now_iso()}


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
    return res


@app.get("/api/leaderboard")
async def api_leaderboard():
    return services.weekly_leaderboard(20)


# ---------- التطبيق المصغّر (ملفات ثابتة) ----------
if os.path.isdir("web"):
    app.mount("/app", StaticFiles(directory="web", html=True), name="webapp")
