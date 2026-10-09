"""
سهم — الأدوات الثابتة: قوائم الأسهم، الثوابت، الحسابات المشتركة
"""
# العمولة الوهمية 0.1% (القسم 7)
FEE_RATE = 0.001
STARTING_CAPITAL = 100_000

# السوق السعودي — الأسهم المرشّحة (رموز Yahoo بلاحقة .SR)
# ملاحظة: راجع الأسماء مع رموز تداول الرسمية عند التعديل (بعض الأسماء القديمة كانت غير مطابقة).
TADAWUL_SYMBOLS = {
    "2222.SR": "أرامكو السعودية",
    "1120.SR": "مصرف الراجحي",
    "2010.SR": "سابك",
    "7010.SR": "stc",
    "1180.SR": "مصرف الإنماء",
    "1010.SR": "بنك الرياض",
    "1050.SR": "البنك السعودي الفرنسي",
    "1150.SR": "بنك البلاد",
    "2280.SR": "المراعي",
    "6004.SR": "الشركة الغذائية",
    "4190.SR": "بن داود",
    "2380.SR": "بترو رابغ",
    "2270.SR": "سدافكو",
    "4321.SR": "شركة الإتصالات البحرية",
}

# الأمريكي — أشهر الأسماء مع أسمائها الكاملة
US_SYMBOLS = {
    "AAPL": "أبل",
    "MSFT": "مايكروسوفت",
    "NVDA": "إنفيديا",
    "TSLA": "تسلا",
    "AMZN": "أمازون",
    "GOOGL": "ألفابت",
    "META": "ميتا",
    "NFLX": "نتفليكس",
    "AMD": "إيه إم دي",
    "JPM": "جيه بي مورغان",
}

# الكريبتو — أزواج Yahoo
CRYPTO_SYMBOLS = {
    "BTC-USD": "بيتكوين",
    "ETH-USD": "إيثريوم",
    "SOL-USD": "سولانا",
    "XRP-USD": "ريبل",
    "BNB-USD": "بينانس كوين",
}

ALL_SYMBOLS = {}
for s, n in TADAWUL_SYMBOLS.items():
    ALL_SYMBOLS[s] = {"name": n, "market": "SA"}
for s, n in US_SYMBOLS.items():
    ALL_SYMBOLS[s] = {"name": n, "market": "US"}
for s, n in CRYPTO_SYMBOLS.items():
    ALL_SYMBOLS[s] = {"name": n, "market": "CRYPTO"}


# مراجع السوق (benchmark) لحساب «العائد الزائد» — تُخزَّن شموعها في نفس جدول candles.
# كل سوق يُقاس بمرجعه، فلا يُقاس سهم أمريكي بمرجع سعودي.
BENCHMARKS = {
    "SA": ("2222.SR", "أرامكو السعودية"),
    "US": ("^GSPC", "مؤشر S&P 500"),
    "CRYPTO": ("BTC-USD", "بيتكوين"),
}
BENCHMARK_SYMBOLS = {sym for sym, _ in BENCHMARKS.values()}


def market_of(symbol: str) -> str:
    return ALL_SYMBOLS.get(symbol, {}).get("market", "US")


def symbol_name(symbol: str) -> str:
    return ALL_SYMBOLS.get(symbol, {}).get("name", symbol)


def round_score_rank(excess_return_pct: float) -> str:
    """تصنيف الجولة حسب العائد الزائد على المؤشر (القسم 4.4)."""
    if excess_return_pct >= 8:
        return "أسطورة 🏆"
    if excess_return_pct >= 3:
        return "محترف 🥇"
    if excess_return_pct >= 0:
        return "ناجح ✅"
    if excess_return_pct >= -5:
        return "متمهل 😐"
    return "خاسر 💀"


def points_for_rank(rank: str, days: int) -> int:
    """نقاط + XP حسب المرتبة (القسم 4.4)."""
    base = {"أسطورة 🏆": 300, "محترف 🥇": 200, "ناجح ✅": 100, "متمهل 😐": 40, "خاسر 💀": 10}
    pts = base.get(rank, 10)
    # جولات أطول = نقاط أكثر (بحد أقصى)
    return int(pts * (1 + min(days, 60) / 120))


def bonus_coins_for_round(final_value: float, capital: float) -> int:
    """مكافأة عملات وهمية حسب أداء الجولة (موجبة فقط).

    القاعدة: كل 1% ربح = 1,000 عملة (أي 1% من رأس المال = العملة المقابلة لربحها).
    """
    gain = final_value - capital
    if gain <= 0:
        return 0
    return int(gain)
