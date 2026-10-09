"""
سهم — سكربت تعبئة البيانات التاريخية (يجري مرة واحدة، يدويًا أو عبر Render Shell)
python seed_data.py
"""
import os
from app.db import init_db
from app.market_data import seed_archives

os.environ.setdefault("DB_PATH", "sahem.db")
init_db()

symbols_env = os.getenv("ARCHIVE_SYMBOLS")
symbols = symbols_env.split(",") if symbols_env else None
total = seed_archives(years=5, symbols=symbols)
print(f"تم تخزين {total} شمعة تاريخية 🗄️")
