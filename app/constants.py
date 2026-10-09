"""
سهم — الأدوات الثابتة: قوائم الأسهم، الثوابت، الحسابات المشتركة
"""
# العمولة الوهمية 0.1% (القسم 7)
FEE_RATE = 0.001
STARTING_CAPITAL = 100_000

# السوق السعودي — الأسهم المرشّحة (رموز Yahoo بلاحقة .SR)
TADAWUL_SYMBOLS = {
    "2222.SR": "أرامكو السعودية",
    "1120.SR": "مصرف الراجحي",
    "2010.SR": "سابك",
    "7010.SR": "stc",
    "1180.SR": "بنك الإنماء",
    "1010.SR": "بنك الرياض",
    "1050.SR": "بنك البلاد",
    "1150.SR": "الإنماء للتمويل الأهلي",
    "2280.SR": "المراعي",
    "6004.SR": "شركة الغذائية",
    "4190.SR": "بن داود",
    "2380.SR": "بترو ربغ",
    "2270.SR": "سدافكو",
    "4321.SR": "شركة الإتصالات البحرية",
}

# الأمريكي — أشهر الاسماء
US_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "NFLX", "AMD", "JPM"]

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
for s in US_SYMBOLS:
    ALL_SYMBOLS[s] = {"name": s, "market": "US"}
for s, n in CRYPTO_SYMBOLS.items():
    ALL_SYMBOLS[s] = {"name": n, "market": "CRYPTO"}


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
    """مكافأة عملات وهمية حسب أداء الجولة (موجبة فقط)."""
    gain = final_value - capital
    if gain <= 0:
        return 0
    return int(gain / 100)  # كل 1% ربح = ~1000 عملة + عملات بسيطة للمكاسب الصغيرة


def clamp(value, lo, hi):
    return max(lo, min(hi, value))
