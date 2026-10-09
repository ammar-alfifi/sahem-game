"""
سهم — بوت تيليجرام (aiogram 3): إشعارات، قائمة رئيسية، توقعات، تفعيل المربع المصغّر
"""
import logging
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo,
)
from . import services
from .constants import ALL_SYMBOLS, symbol_name
from .market_data import get_cached_prices, refresh_prices
from .config import get_webapp_url

log = logging.getLogger("sahem.bot")
router = Router()

# أسماء الأسواق بالعربية
MARKET_LABELS = {"SA": "🇸🇦 تداول", "US": "🇺🇸 الأمريكي", "CRYPTO": "🌐 كريبتو"}
DIRECTION_LABELS = {
    "up": "⬆️ صعود (+0.5%)",
    "flat": "↔️ ثبات",
    "down": "⬇️ هبوط (-0.5%)",
}


def main_menu_keyboard(webapp_url: str | None = None) -> InlineKeyboardMarkup:
    kb = []
    if webapp_url:
        kb.append([InlineKeyboardButton(text="🎮 افتح اللعبة الكاملة", web_app=WebAppInfo(url=webapp_url))])
    kb.append([InlineKeyboardButton(text="📈 اختر سهم للتوقّع", callback_data="menu:choose")])
    kb.append([InlineKeyboardButton(text="🏆 لوحة الصدارة", callback_data="menu:leaderboard")])
    kb.append([InlineKeyboardButton(text="💼 محفظتي ورصيدي", callback_data="menu:portfolio")])
    kb.append([InlineKeyboardButton(text="🔄 تحديث الأسعار", callback_data="menu:refresh")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _fmt_num(n: float) -> str:
    return f"{n:,.2f}"


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    u = services.get_or_create_user(message.from_user.id, message.from_user.username)
    text = (
        f"مرحباً {message.from_user.first_name}! 👋\n\n"
        "🎮 **سهم** — العالم الحقيقي هو الملعب، وأنت تتداول بمال وهمي.\n\n"
        f"💳 رصيدك الابتدائي: **{_fmt_num(u['coins_balance'])} سهم**\n"
        f"🏅 مستواك: {u['level']} | XP: {u['xp']}\n\n"
        "الطموح: توقّع السوق بدقة أكبر من أصدقائك، وكسب النقاط!\n"
        "القاعدة الذهبية: لا مال حقيقي هنا، فقط لعبة تعليمية ترفيهية."
    )
    await message.answer(text, reply_markup=main_menu_keyboard(get_webapp_url()), parse_mode="Markdown")


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 أوامر سهم:\n\n"
        "/start — البدء والقائمة الرئيسية\n"
        "/markets — الأسعار الحية لجميع الأسواق\n"
        "/predict — توقّع إغلاق اليوم\n"
        "/portfolio — محفظتك\n"
        "/leaderboard — لوحة الصدارة\n"
        "/balance — رصيدك ومستواك\n"
        "/arcade — جولة أركيد سريعة",
    )


@router.message(Command("markets"))
async def cmd_markets(message: Message):
    # JWT: تحديث الأسعار قبل العرض
    symbols_by_market = {}
    for sym, info in ALL_SYMBOLS.items():
        symbols_by_market.setdefault(info["market"], []).append(sym)
    lines = ["📊 **الأسعار الحية** (تحديث ساعة إعادة التحديث)\n"]
    prices = get_cached_prices([s for ss in symbols_by_market.values() for s in ss])
    for market in ("SA", "US", "CRYPTO"):
        lines.append(f"\n{MARKET_LABELS[market]}")
        for sym in symbols_by_market.get(market, []):
            p = prices.get(sym)
            if p:
                emoji = "🟢" if (p["change_pct"] or 0) >= 0 else "🔴"
                lines.append(f"  {emoji} {symbol_name(sym)}: {p['price']:,.2f} ({p['change_pct']:+.2f}%)")
    await message.answer("\n".join(lines), parse_mode="Markdown")


@router.message(Command("portfolio"))
async def cmd_portfolio(message: Message):
    u = services.get_or_create_user(message.from_user.id, message.from_user.username)
    positions = services.get_portfolio(u["id"])
    if not positions:
        await message.answer(f"💼 محفظتك فارغة. الرصيد النقدي: {_fmt_num(u['coins_balance'])} سهم")
        return
    lines = [f"💳 الرصيد النقدي: {_fmt_num(u['coins_balance'])} سهم\n"]
    for pos in positions:
        emoji = "🟢" if pos["pnl_pct"] >= 0 else "🔴"
        lines.append(
            f"{emoji} {pos['name']}: {pos['quantity']} وحدة @ {pos['avg_cost']:,.2f} → {pos['current_price']:,.2f} ({pos['pnl_pct']:+.2f}%)"
        )
    total = u["coins_balance"] + sum(p["market_value"] for p in positions)
    lines.append(f"\n💼 قيمة المحفظة الكاملة: {_fmt_num(total)} سهم")
    await message.answer("\n".join(lines))


@router.message(Command("balance"))
async def cmd_balance(message: Message):
    u = services.get_or_create_user(message.from_user.id, message.from_user.username)
    s = services.user_summary(u["id"])
    await message.answer(
        f"💳 الرصيد: {_fmt_num(u['coins_balance'])} سهم\n"
        f"🏅 المستوى: {u['level']} | XP: {u['xp']}\n"
        f"🎯 دقة التوقعات: {s.get('accuracy_pct', 0)}% (فوز {s['prediction_wins']} / خسارة {s['prediction_losses']})\n"
        f"🎮 جولات الأركيد: {s['arcade_rounds']}",
    )


@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message):
    rows = services.weekly_leaderboard(10)
    lines = ["🏆 **لوحة الصدارة الأسبوعية**\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = r["username"] or f"لاعب #{r['level']}"
        lines.append(f"{medal} {name} — {_fmt_num(r['weekly_value'] or 0)} سهم ({r['rounds']} جولة)")
    await message.answer("\n".join(lines), parse_mode="Markdown")


@router.message(Command("predict"))
async def cmd_predict(message: Message):
    await message.answer("اختر سوقاً وسهماً للتوقّع 👇", reply_markup=_market_keyboard())


@router.message(Command("arcade"))
async def cmd_arcade(message: Message):
    webapp_url = get_webapp_url()
    kb = []
    if webapp_url:
        kb.append([InlineKeyboardButton(text="🎮 ابدأ جولة أركيد", web_app=WebAppInfo(url=webapp_url + "#arcade"))])
    else:
        kb.append([InlineKeyboardButton(text="🎮 ابدأ جولة أركيد", callback_data="arcade:start")])
    await message.answer(
        "⚡ **وضع الأركيد**\n\n"
        "جولة تاريخية حقيقية بسرعة مضغوطة: يوم تداول ≈ 4 ثانية.\n"
        "رأس مال 100,000 وهمي، عمولة 0.1%، الفوز بالعائد الزائد على المؤشر!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
    )


# ---------- لوحات الاختيار للتوقعات ----------
def _market_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇸🇦 تداول", callback_data="mk:SA")],
        [InlineKeyboardButton(text="🇺🇸 الأمريكي", callback_data="mk:US")],
        [InlineKeyboardButton(text="🌐 كريبتو", callback_data="mk:CRYPTO")],
    ])


def _symbols_keyboard(market: str) -> InlineKeyboardMarkup:
    symbols = [s for s, i in ALL_SYMBOLS.items() if i["market"] == market][:10]
    kb, row = [], []
    for s in symbols:
        row.append(InlineKeyboardButton(text=symbol_name(s)[:16], callback_data=f"sym:{s}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton(text="↩️ رجوع", callback_data="menu:choose")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _direction_keyboard(symbol: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⬆️ صعود", callback_data=f"dir:up:{symbol}"),
            InlineKeyboardButton(text="↔️ ثبات", callback_data=f"dir:flat:{symbol}"),
            InlineKeyboardButton(text="⬇️ هبوط", callback_data=f"dir:down:{symbol}"),
        ],
        [InlineKeyboardButton(text="↩️ رجوع", callback_data="menu:choose")],
    ])


@router.callback_query(F.data == "menu:choose")
async def cb_choose_market(cb: CallbackQuery):
    await cb.message.answer("اختر السوق 👇", reply_markup=_market_keyboard())
    await cb.answer()


@router.callback_query(F.data.startswith("mk:"))
async def cb_market(cb: CallbackQuery):
    market = cb.data.split(":")[1]
    await cb.message.answer("اختر السهم 👇", reply_markup=_symbols_keyboard(market))
    await cb.answer()


@router.callback_query(F.data.startswith("sym:"))
async def cb_symbol(cb: CallbackQuery):
    symbol = cb.data.split(":", 1)[1]
    price = get_cached_prices([symbol]).get(symbol)
    info = f"📊 {symbol_name(symbol)}\n"
    if price:
        emoji = "🟢" if (price["change_pct"] or 0) >= 0 else "🔴"
        info += f"{emoji} السعر: {price['price']:,.2f} ({price['change_pct']:+.2f}%)\n\n"
    info += "توقّع إغلاق اليوم (يُسوّى تلقائياً بعد الإغلاق):"
    await cb.message.answer(info, reply_markup=_direction_keyboard(symbol))
    await cb.answer()


@router.callback_query(F.data.startswith("dir:"))
async def cb_direction(cb: CallbackQuery):
    _, direction, symbol = cb.data.split(":", 2)
    u = services.get_or_create_user(cb.from_user.id, cb.from_user.username)
    res = services.create_prediction(u["id"], symbol, direction)
    if res["ok"]:
        weight = {"up": 2.2, "down": 3.3, "flat": 4.0}[direction]
        await cb.message.answer(
            f"✅ سُجّلت توقعتك!\n\n{DIRECTION_LABELS[direction]} على {symbol_name(symbol)}\n"
            f"🎁 النقاط عند الفوز: {weight} (وزن احتمالي — التوقع الصعب نقاط أكثر)\n"
            "سيتم إبلاغك بالنتيجة بعد إغلاق السوق.",
        )
    else:
        await cb.message.answer(f"⚠️ {res['error']}")
    await cb.answer()


@router.callback_query(F.data == "menu:leaderboard")
async def cb_leaderboard(cb: CallbackQuery):
    rows = services.weekly_leaderboard(10)
    lines = ["🏆 **لوحة الصدارة الأسبوعية**\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, r in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = r["username"] or f"لاعب #{r['level']}"
        lines.append(f"{medal} {name} — {_fmt_num(r['weekly_value'] or 0)} سهم ({r['rounds']} جولة)")
    await cb.message.answer("\n".join(lines), parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data == "menu:portfolio")
async def cb_portfolio(cb: CallbackQuery):
    u = services.get_or_create_user(cb.from_user.id, cb.from_user.username)
    positions = services.get_portfolio(u["id"])
    lines = [f"💳 الرصيد النقدي: {_fmt_num(u['coins_balance'])} سهم\n"]
    if positions:
        for pos in positions:
            emoji = "🟢" if pos["pnl_pct"] >= 0 else "🔴"
            lines.append(f"{emoji} {pos['name']}: {pos['quantity']} @ {pos['avg_cost']:,.2f} → {pos['current_price']:,.2f} ({pos['pnl_pct']:+.2f}%)")
    else:
        lines.append("💼 محفظتك فارغة — افتح التطبيق للبدء بالتداول!")
    await cb.message.answer("\n".join(lines))
    await cb.answer()


@router.callback_query(F.data == "menu:refresh")
async def cb_refresh(cb: CallbackQuery):
    await cb.answer("⏳ جاري التحديث...")
    n = refresh_prices()
    await cb.message.answer(f"🔄 تم تحديث {n} سعر من السوق الحقيقي ✅")


@router.callback_query(F.data == "arcade:start")
async def cb_arcade_inline(cb: CallbackQuery):
    u = services.get_or_create_user(cb.from_user.id, cb.from_user.username)
    rnd = services.start_arcade_round(u["id"])
    if not rnd:
        await cb.message.answer("⚠️ لا توجد بيانات تاريخية بعد — جرب بعد قليل عند اكتمال التخزين.")
        await cb.answer()
        return
    webapp_url = get_webapp_url()
    kb = []
    if webapp_url:
        kb.append([InlineKeyboardButton(text="🎮 افتح الجولة في التطبيق", web_app=WebAppInfo(url=webapp_url + "#arcade"))])
    await cb.message.answer(
        f"⚡ جولة أركيد بدأت!\n\n"
        f"السهم: **{rnd['name']}**\n"
        f"الأيام: {rnd['session_len']} يوم تداول (≈ {rnd['session_len'] * 4} ثانية)\n"
        f"رأس المال: {_fmt_num(rnd['capital'])} سهم",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb) if kb else None,
    )
    await cb.answer()


async def notify_prediction_result(user_id: int, bot: Bot):
    """إشعار النتائج بعد التسوية — استدعاء من المجدول."""
    pending = services.get_pending_predictions(user_id)
    if not pending:
        await bot.send_message(
            user_id,
            "⏰ نتائج توقعاتك جاهزة! استخدم /predict لتوقّع جديد أو افتح التطبيق.",
        )


def register_router(dp: Dispatcher):
    dp.include_router(router)
