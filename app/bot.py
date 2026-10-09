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
from .db import db
from .telegram_client import get_bot

log = logging.getLogger("sahem.bot")
router = Router()

# أسماء الأسواق بالعربية
MARKET_LABELS = {"SA": "🇸🇦 تداول", "US": "🇺🇸 الأمريكي", "CRYPTO": "🌐 كريبتو"}
DIRECTION_LABELS = {
    "up": "⬆️ صعود (+0.5%)",
    "flat": "↔️ ثبات",
    "down": "⬇️ هبوط (-0.5%)",
}

_bot_username_cache: str = ""


def esc(s) -> str:
    return str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main_menu_keyboard(webapp_url: str | None = None) -> InlineKeyboardMarkup:
    kb = []
    if webapp_url:
        kb.append([InlineKeyboardButton(text="🎮 افتح اللعبة", web_app=WebAppInfo(url=webapp_url))])
    kb.append([InlineKeyboardButton(text="📈 اختر سهم للتوقّع", callback_data="menu:choose")])
    kb.append([InlineKeyboardButton(text="⚔️ تحدي صديق في مبارزة", callback_data="menu:duel")])
    kb.append([InlineKeyboardButton(text="🏆 لوحة الصدارة", callback_data="menu:leaderboard")])
    kb.append([InlineKeyboardButton(text="💼 محفظتي ورصيدي", callback_data="menu:portfolio")])
    kb.append([InlineKeyboardButton(text="🔄 تحديث الأسعار", callback_data="menu:refresh")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _fmt_num(n: float) -> str:
    return f"{n:,.2f}"


async def _bot_username() -> str:
    global _bot_username_cache
    if not _bot_username_cache:  # نعيد المحاولة عند فشل مؤقت بدل حفظ قيمة فارغة للأبد
        try:
            me = await get_bot().get_me()
            _bot_username_cache = me.username or ""
        except Exception:
            _bot_username_cache = ""
    return _bot_username_cache


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    u = services.get_or_create_user(message.from_user.id, services.pick_tg_name(message.from_user))
    # رابط تحدٍّ مباشر: /start join_XXXXXX
    parts = (message.text or "").split(maxsplit=1)
    args = parts[1].strip() if len(parts) > 1 else ""
    from . import duels as duels_mod
    if args.lower().startswith("join_"):
        code = args[5:]
        res = duels_mod.join_duel(u["id"], code)
        if res.get("ok"):
            d = res["duel"]
            await message.answer(
                f"⚔️ قبلت التحدي!\n"
                f"المتحدّي: {esc(d['challenger_name'])}\n"
                f"📊 {esc(d['symbol_name'])} • {d['session_len']} يوم\n"
                f"🗓️ من {esc(d['start_ts'])} إلى {esc(d['end_ts'])}\n\n"
                "افتح التطبيق → الأركيد → تبويب «مبارزة» واضغط «العب جولتك».",
                reply_markup=main_menu_keyboard(get_webapp_url()),
                parse_mode="HTML",
            )
        else:
            await message.answer(f"⚠️ {esc(res['error'])}")
        return
    text = (
        f"مرحباً {esc(message.from_user.first_name)}! 👋\n\n"
        "🎮 <b>سهم</b> — العالم الحقيقي هو الملعب، وأنت تتداول بمال وهمي.\n\n"
        f"💳 رصيدك الابتدائي: <b>{_fmt_num(u['coins_balance'])} عملة</b>\n"
        f"🏅 مستواك: {u['level']} | XP: {u['xp']}\n\n"
        "توقّع السوق بدقة، والعائد الزائد هو الفيصل!"
    )
    await message.answer(text, reply_markup=main_menu_keyboard(get_webapp_url()), parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 أوامر سهم:\n\n"
        "/start — البدء والقائمة الرئيسية\n"
        "/markets — الأسعار (تُحدَّث كل ساعة)\n"
        "/predict — توقّع إغلاق اليوم\n"
        "/portfolio — محفظتك\n"
        "/leaderboard — لوحة الصدارة\n"
        "/league — الدوري الأسبوعي والجوائز\n"
        "/duel — أنشئ تحدّي مبارزة وشاركه\n"
        "/join CODE — انضم بتحدّي صديق\n"
        "/balance — رصيدك ومستواك\n"
        "/arcade — جولة أركيد سريعة",
    )


@router.message(Command("markets"))
async def cmd_markets(message: Message):
    symbols_by_market = {}
    for sym, info in ALL_SYMBOLS.items():
        symbols_by_market.setdefault(info["market"], []).append(sym)
    lines = ["📊 <b>الأسعار</b> (تُحدَّث كل ساعة)\n"]
    prices = get_cached_prices([s for ss in symbols_by_market.values() for s in ss])
    for market in ("SA", "US", "CRYPTO"):
        lines.append(f"\n{MARKET_LABELS[market]}")
        for sym in symbols_by_market.get(market, []):
            p = prices.get(sym)
            if p:
                emoji = "🟢" if (p["change_pct"] or 0) >= 0 else "🔴"
                lines.append(f"  {emoji} {esc(symbol_name(sym))}: {p['price']:,.2f} ({p['change_pct']:+.2f}%)")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("portfolio"))
async def cmd_portfolio(message: Message):
    u = services.get_or_create_user(message.from_user.id, services.pick_tg_name(message.from_user))
    positions = services.get_portfolio(u["id"])
    if not positions:
        await message.answer(f"💼 محفظتك فارغة. الرصيد النقدي: {_fmt_num(u['coins_balance'])} عملة")
        return
    lines = [f"💳 الرصيد النقدي: {_fmt_num(u['coins_balance'])} عملة\n"]
    for pos in positions:
        emoji = "🟢" if pos["pnl_pct"] >= 0 else "🔴"
        lines.append(
            f"{emoji} {esc(pos['name'])}: {pos['quantity']:g} وحدة @ {pos['avg_cost']:,.2f} → "
            f"{pos['current_price']:,.2f} ({pos['pnl_pct']:+.2f}%)"
        )
    total = u["coins_balance"] + sum(p["market_value"] for p in positions)
    lines.append(f"\n💼 قيمة المحفظة الكاملة: {_fmt_num(total)} عملة")
    await message.answer("\n".join(lines))


@router.message(Command("balance"))
async def cmd_balance(message: Message):
    u = services.get_or_create_user(message.from_user.id, services.pick_tg_name(message.from_user))
    s = services.user_summary(u["id"])
    await message.answer(
        f"💳 الرصيد: {_fmt_num(u['coins_balance'])} عملة\n"
        f"🏅 المستوى: {u['level']} | XP: {u['xp']}\n"
        f"🎯 دقة التوقعات: {s.get('accuracy_pct', 0)}% (فوز {s['prediction_wins']} / خسارة {s['prediction_losses']})\n"
        f"🎮 جولات الأركيد المكتملة: {s['arcade_rounds']}",
    )


def _leaderboard_lines(rows: list[dict]) -> str:
    lines = ["🏆 <b>الدوري الأسبوعي</b> (نقاط = عائد زائد + توقعات)\n"]
    medals = ["🥇", "🥈", "🥉"]
    if not rows:
        return lines[0] + "\nلا نتائج بعد — العب جولة أركيد!"
    for i, r in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i + 1}."
        name = esc(r["username"] or "لاعب") + (" 👑" if r.get("champion") else "")
        val = r.get("score", r.get("weekly_value", 0))
        lines.append(
            f"{medal} {name} — {_fmt_num(val or 0)} نقطة "
            f"({r.get('rounds', 0)} جولة • {r.get('pred_wins', 0)} توقع)"
        )
    return "\n".join(lines)


@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message):
    from . import league as league_mod
    ps = league_mod.current_period()[0]
    rows = league_mod.standings(ps, limit=10)
    champs = league_mod.champions_map([r["user_id"] for r in rows])
    for r in rows:
        r["champion"] = r["user_id"] in champs
    await message.answer(_leaderboard_lines(rows), parse_mode="HTML")


@router.message(Command("predict"))
async def cmd_predict(message: Message):
    await message.answer("اختر سوقاً وسهماً للتوقّع 👇", reply_markup=_market_keyboard())


@router.message(Command("arcade"))
async def cmd_arcade(message: Message):
    webapp_url = get_webapp_url()
    kb = []
    if webapp_url:
        kb.append([InlineKeyboardButton(text="🎮 ابدأ جولة الأركيد", web_app=WebAppInfo(url=webapp_url + "#arcade"))])
    await message.answer(
        "⚡ <b>وضع الأركيد</b>\n\n"
        "جولة تاريخية حقيقية بسرعة مضغوطة: يوم تداول ≈ 4 ثوانٍ.\n"
        "رأس مال 100,000 وهمي، عمولة 0.1%، والفوز بالعائد الزائد على السوق!"
        + ("" if webapp_url else "\n\nافتح التطبيق من القائمة الرئيسية للبدء."),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb) if kb else None,
    )


# ---------- لوحات الاختيار للتوقعات ----------
def _market_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇸🇦 تداول", callback_data="mk:SA")],
        [InlineKeyboardButton(text="🇺🇸 الأمريكي", callback_data="mk:US")],
        [InlineKeyboardButton(text="🌐 كريبتو", callback_data="mk:CRYPTO")],
    ])


def _symbols_keyboard(market: str) -> InlineKeyboardMarkup:
    symbols = [s for s, i in ALL_SYMBOLS.items() if i["market"] == market]
    kb, row = [], []
    for s in symbols:
        row.append(InlineKeyboardButton(text=symbol_name(s)[:20], callback_data=f"sym:{s}"))
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
    info = f"📊 {esc(symbol_name(symbol))}\n"
    if price:
        emoji = "🟢" if (price["change_pct"] or 0) >= 0 else "🔴"
        info += f"{emoji} السعر: {price['price']:,.2f} ({price['change_pct']:+.2f}%)\n\n"
    info += "توقّع إغلاق اليوم (ثبات = تغيّر بين −0.5% و+0.5%):"
    await cb.message.answer(info, reply_markup=_direction_keyboard(symbol))
    await cb.answer()


@router.callback_query(F.data.startswith("dir:"))
async def cb_direction(cb: CallbackQuery):
    _, direction, symbol = cb.data.split(":", 2)
    u = services.get_or_create_user(cb.from_user.id, services.pick_tg_name(cb.from_user))
    res = services.create_prediction(u["id"], symbol, direction)
    if res["ok"]:
        weight = services.PROB_WEIGHTS[direction]
        await cb.message.answer(
            f"✅ سُجّلت توقعتك!\n\n{DIRECTION_LABELS[direction]} على {esc(symbol_name(symbol))}\n"
            f"🎁 النقاط عند الفوز: {weight} (وزن احتمالي — التوقع الأصعب نقاط أكثر)\n"
            "سيتم إبلاغك بالنتيجة بعد إغلاق السوق.",
        )
    else:
        await cb.message.answer(f"⚠️ {esc(res['error'])}")
    await cb.answer()


@router.callback_query(F.data == "menu:leaderboard")
async def cb_leaderboard(cb: CallbackQuery):
    from . import league as league_mod
    ps = league_mod.current_period()[0]
    rows = league_mod.standings(ps, limit=10)
    champs = league_mod.champions_map([r["user_id"] for r in rows])
    for r in rows:
        r["champion"] = r["user_id"] in champs
    await cb.message.answer(_leaderboard_lines(rows), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "menu:duel")
async def cb_duel(cb: CallbackQuery):
    """زر القائمة: يلحق منطق /duel نفسه."""
    u = services.get_or_create_user(cb.from_user.id, services.pick_tg_name(cb.from_user))
    from . import duels as duels_mod
    res = duels_mod.create_duel(u["id"])
    if not res.get("ok"):
        await cb.message.answer(f"⚠️ {esc(res['error'])}")
        await cb.answer()
        return
    d = res["duel"]
    kb = []
    webapp_url = get_webapp_url()
    if webapp_url:
        kb.append([InlineKeyboardButton(text="🎮 افتح التطبيق", web_app=WebAppInfo(url=webapp_url))])
    await cb.message.answer(
        f"⚔️ <b>تحدي مبارزة جاهز!</b>\n\n"
        f"📊 {esc(d['symbol_name'])} • {d['session_len']} يوم\n"
        f"🗓️ من {esc(d['start_ts'])} إلى {esc(d['end_ts'])}\n\n"
        f"أرسل لصديقك الرمز: <code>{esc(d['code'])}</code> — يدخل بـ /join {esc(d['code'])}\n"
        f"أو شارك رابط الدعوة معه.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb) if kb else None,
    )
    await cb.answer()


@router.callback_query(F.data == "menu:portfolio")
async def cb_portfolio(cb: CallbackQuery):
    u = services.get_or_create_user(cb.from_user.id, services.pick_tg_name(cb.from_user))
    positions = services.get_portfolio(u["id"])
    lines = [f"💳 الرصيد النقدي: {_fmt_num(u['coins_balance'])} عملة\n"]
    if positions:
        for pos in positions:
            emoji = "🟢" if pos["pnl_pct"] >= 0 else "🔴"
            lines.append(f"{emoji} {esc(pos['name'])}: {pos['quantity']:g} @ {pos['avg_cost']:,.2f} → "
                         f"{pos['current_price']:,.2f} ({pos['pnl_pct']:+.2f}%)")
    else:
        lines.append("💼 محفظتك فارغة — افتح التطبيق للبدء بالتداول!")
    await cb.message.answer("\n".join(lines))
    await cb.answer()


@router.callback_query(F.data == "menu:refresh")
async def cb_refresh(cb: CallbackQuery):
    await cb.answer("⏳ جاري التحديث...")
    import asyncio
    n = await asyncio.to_thread(refresh_prices)  # لا نجمّد حلقة الأحداث
    await cb.message.answer(f"🔄 تم تحديث {n} سعر من السوق الحقيقي ✅")


async def notify_prediction_results(events: list[dict]):
    """إشعار المستخدمين بنتائج توقعاتهم بعد التسوية (يُستدعى من المجدول)."""
    if not events:
        return
    by_user: dict[int, list[dict]] = {}
    for e in events:
        by_user.setdefault(e["user_id"], []).append(e)
    ids = list(by_user.keys())
    with db() as conn:
        rows = conn.execute(
            f"SELECT id, telegram_id FROM users WHERE id IN ({','.join('?' * len(ids))})", ids
        ).fetchall()
    tmap = {r["id"]: r["telegram_id"] for r in rows}
    dir_ar = {"up": "صعود", "down": "هبوط", "flat": "ثبات"}
    bot = get_bot()
    for uid, items in by_user.items():
        tg = tmap.get(uid)
        if not tg:
            continue
        lines = ["🎯 نتائج توقعاتك:"]
        for e in items:
            mark = "✅" if e["result"] == "win" else "❌"
            tail = f" (+{e['points']:g} نقطة)" if e["result"] == "win" else ""
            lines.append(f"{mark} {esc(symbol_name(e['symbol']))} — {dir_ar.get(e['direction'], e['direction'])} "
                         f"• تغيّر {e['change_pct']:+.2f}%{tail}")
        try:
            await bot.send_message(tg, "\n".join(lines), parse_mode="HTML")
        except Exception:
            pass


async def notify_daily_reminders(users: list[dict]):
    """تذكير يومي بالحضور — يُستدعى من المجدول لمرة واحدة في اليوم (المستخدمون النشطون فقط)."""
    if not users:
        return
    bot = get_bot()
    text = (
        "🎁 مكافأة حضور اليوم لم تستلمها بعد!\n"
        "كل يوم متتالٍ يرفع قيمة المكافأة — افتح التطبيق واستلمها قبل أن تكسر السلسلة."
    )
    for u in users:
        tg = u.get("telegram_id")
        if not tg:
            continue
        try:
            await bot.send_message(tg, text)
        except Exception:
            pass
        services.mark_daily_reminded(u["id"])


def register_router(dp: Dispatcher):
    dp.include_router(router)


# ---------- المرحلة 2: تحديات المبارزات + الدوري ----------
@router.message(Command("duel"))
async def cmd_duel(message: Message):
    u = services.get_or_create_user(message.from_user.id, services.pick_tg_name(message.from_user))
    from . import duels as duels_mod
    res = duels_mod.create_duel(u["id"])
    if not res.get("ok"):
        await message.answer(f"⚠️ {esc(res['error'])}")
        return
    d = res["duel"]
    username = await _bot_username()
    share = f"https://t.me/{username}?start=join_{d['code']}" if username else f"رمز التحدي: {d['code']}"
    kb = []
    webapp_url = get_webapp_url()
    if webapp_url:
        kb.append([InlineKeyboardButton(text="🎮 افتح التطبيق — جاهز للمعركة", web_app=WebAppInfo(url=webapp_url))])
        kb.append([InlineKeyboardButton(text="⚖️ لوحة الدوري", web_app=WebAppInfo(url=webapp_url + "#leaderboard"))])
    await message.answer(
        f"⚔️ <b>تحدي مبارزة جاهز!</b>\n\n"
        f"📊 نافذة تاريخية: {esc(d['symbol_name'])} • {d['session_len']} يوم\n"
        f"🗓️ من {esc(d['start_ts'])} إلى {esc(d['end_ts'])}\n"
        f"🪙 رأس مال 100,000 لكل طرف — الفائز صاحب العائد الزائد الأعلى\n\n"
        f"📤 شاركه مع صديق:\n{esc(share)}\n\n"
        f"أو أرسل له الرمز: <code>{esc(d['code'])}</code> — يدخل بـ /join {esc(d['code'])}\n"
        f"صلاحية التحدي: 24 ساعة",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb) if kb else None,
    )


@router.message(Command("join"))
async def cmd_join(message: Message):
    u = services.get_or_create_user(message.from_user.id, services.pick_tg_name(message.from_user))
    parts = (message.text or "").split(maxsplit=1)
    code = parts[1].strip() if len(parts) > 1 else ""
    if not code:
        await message.answer("اكتب الرمز هكذا: /join XXXXXX (من رسالة التحدي)")
        return
    from . import duels as duels_mod
    res = duels_mod.join_duel(u["id"], code)
    if res.get("ok"):
        d = res["duel"]
        await message.answer(
            f"⚔️ قبلت التحدي!\n"
            f"المتحدّي: {esc(d['challenger_name'])}\n"
            f"📊 {esc(d['symbol_name'])} • {d['session_len']} يوم\n"
            f"🗓️ من {esc(d['start_ts'])} إلى {esc(d['end_ts'])}\n\n"
            "افتح التطبيق → الأركيد → «مبارزة» → «العب جولتك».",
        )
    else:
        await message.answer(f"⚠️ {esc(res['error'])}")


@router.message(Command("league"))
async def cmd_league(message: Message):
    from . import league as league_mod
    u = services.get_or_create_user(message.from_user.id, services.pick_tg_name(message.from_user))
    rows = league_mod.standings(limit=10)
    me = league_mod.my_view(u["id"])
    lines = [
        "🥇 <b>الدوري الأسبوعي</b>",
        f"⏳ ينقضي خلال: {esc(league_mod.week_countdown())}",
        f"♟️ المتسابقون: {league_mod.players_count()}",
    ]
    if me:
        if me["rank"]:
            lines.append(f"🧍 مركزك: {me['rank']} بـ {me['score']:+,.1f} نقطة — {esc(me.get('gap_text', ''))}")
        else:
            lines.append("🧍 مركزك: خارج الترتيب — سجّل جولة أركيد لتدخل!")
    lines.append("")
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    if not rows:
        lines.append("لا نتائج بعد — افتح التطبيق وابدأ جولة أركيد!")
    for r in rows:
        medal = medals.get(r["rank"], f"{r['rank']}.")
        lines.append(
            f"{medal} {esc(r['username'] or 'لاعب')} — {r['score']:+,.1f} نقاط "
            f"({r['rounds']} جولة • {r['pred_wins']} توقع)"
        )
    lines.append("\n🎁 جوائز الجمعة: 50,000 + 30,000 + 20,000 + 7×10,000 عملة و XP")
    if me and me.get("hint"):
        lines.append(f"💡 {esc(me['hint'])}")
    await message.answer("\n".join(lines), parse_mode="HTML")
