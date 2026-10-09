"""
سهم — طبقة البيانات: جلب وتخزين الأسعار (القسم 5 من الخطة)
المبدأ: اجلب مرة واحدة وخدم الجميع من الكاش.
"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta, timezone
from .constants import ALL_SYMBOLS
from .db import get_db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_quote(symbol: str) -> dict | None:
    """جلب السعر الحالي لرمز واحد (يُستخدم من الكاش غالباً)."""
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="2d", interval="1d")
        if hist.empty:
            return None
        last_close = float(hist["Close"].iloc[-1])
        prev_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else last_close
        change_pct = ((last_close - prev_close) / prev_close * 100) if prev_close else 0.0
        return {
            "symbol": symbol,
            "price": round(last_close, 4),
            "prev_close": round(prev_close, 4),
            "change_pct": round(change_pct, 2),
            "updated_at": _now_iso(),
        }
    except Exception:
        return None


def refresh_prices(symbols: list[str] | None = None):
    """تحديث جدول prices — استدعاء واحد يخدم الجميع."""
    symbols = symbols or list(ALL_SYMBOLS.keys())
    conn = get_db()
    updated = 0
    for sym in symbols:
        q = fetch_quote(sym)
        if not q:
            continue
        conn.execute(
            """INSERT INTO prices(symbol, market, price, prev_close, change_pct, updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(symbol, market) DO UPDATE SET
                 price=excluded.price, prev_close=excluded.prev_close,
                 change_pct=excluded.change_pct, updated_at=excluded.updated_at""",
            (sym, _market(sym), q["price"], q["prev_close"], q["change_pct"], q["updated_at"]),
        )
        updated += 1
    conn.commit()
    conn.close()
    return updated


def _market(symbol: str) -> str:
    return ALL_SYMBOLS.get(symbol, {}).get("market", "US")


def get_cached_price(symbol: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT symbol, price, prev_close, change_pct, updated_at FROM prices WHERE symbol=?", (symbol,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_cached_prices(symbols: list[str]) -> dict:
    conn = get_db()
    out = {}
    for sym in symbols:
        row = conn.execute(
            "SELECT symbol, price, prev_close, change_pct, updated_at FROM prices WHERE symbol=?", (sym,)
        ).fetchone()
        if row:
            out[sym] = dict(row)
    conn.close()
    return out


def seed_archives(years: int = 5, symbols: list[str] | None = None):
    """تخزين البيانات التاريخية لوضع الأركيد (يُجرى مرة واحدة)."""
    from .db import init_db
    init_db()
    symbols = symbols or list(ALL_SYMBOLS.keys())
    start = (datetime.now() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
    conn = get_db()
    total = 0
    for sym in symbols:
        market = _market(sym)
        try:
            df = yf.Ticker(sym).history(start=start, interval="1d")
            if df.empty:
                continue
            rows = [
                (
                    sym, market,
                    idx.strftime("%Y-%m-%d"),
                    float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"]),
                    float(r["Volume"]) if "Volume" in r else 0.0,
                )
                for idx, r in df.iterrows()
            ]
            conn.executemany(
                """INSERT OR REPLACE INTO candles(symbol, market, ts, open, high, low, close, volume)
                   VALUES(?,?,?,?,?,?,?,?)""",
                rows,
            )
            total += len(rows)
        except Exception:
            continue
    conn.commit()
    conn.close()
    return total


def get_candles(symbol: str, start_ts: str, end_ts: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        """SELECT ts, open, high, low, close, volume FROM candles
           WHERE symbol=? AND ts>=? AND ts<=? ORDER BY ts""",
        (symbol, start_ts, end_ts),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_available_symbols(min_candles: int = 100) -> list[str]:
    conn = get_db()
    rows = conn.execute(
        """SELECT symbol, COUNT(*) as c FROM candles
           GROUP BY symbol HAVING c >= ? ORDER BY symbol""",
        (min_candles,),
    ).fetchall()
    conn.close()
    return [r["symbol"] for r in rows]
