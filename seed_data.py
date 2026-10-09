"""
سهم — سكربت تعبئة البيانات التاريخية (يجري مرة واحدة، يدويًا أو عبر Render Shell)
python seed_data.py
"""
import os

# يجب ضبط DB_PATH قبل استيراد app.db (الذي يقرأ القيمة عند الاستيراد)
os.environ.setdefault("DB_PATH", "sahem.db")

from app.db import init_db          # noqa: E402
from app.market_data import seed_archives  # noqa: E402

init_db()

symbols_env = os.getenv("ARCHIVE_SYMBOLS")
symbols = symbols_env.split(",") if symbols_env else None
total = seed_archives(years=5, symbols=symbols)
print(f"تم تخزين {total} شمعة تاريخية 🗄️")
