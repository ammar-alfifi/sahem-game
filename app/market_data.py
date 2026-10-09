"""
سهم — طبقة البيانات: جلب وتخزين الأسعار (القسم 5 من الخطة)
المبدأ: اجلب مرة واحدة وخدم الجميع من الكاش.

تنبيه: دوال الجلب (`fetch_quote`, `seed_archives`) حاجزة (شبكة)، لذا تُستدعى
من مسارات async عبر asyncio.to_thread وليس مباشرة.
"""
import yfinance as yf
from datetime import datetime, timedelta, timezone
from .constants import ALL_SYMBOLS, BENCHMARK_SYMBOLS
from .db import db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_quote(symbol: str) -> dict | None:
    """جلب السعر الحالي لرمز واحد من آخر إغلاقين متاحين (يُستخدم من الكاش غالباً)."""
    try:
        hist = yf.Ticker(symbol).history(period="1mo", interval="1d", auto_adjust=False)
        if hist is None or hist.empty:
            return None
        closes = hist["Close"].dropna()
        if len(closes) < 1:
            return None
        last_close = float(closes.iloc[-1])
        prev_close = float(closes.iloc[-2]) if len(closes) > 1 else last_close
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
    """تحديث جدول prices — استدعاء واحد يخدم الجميع. (حاجزة — استدعِها في خيط منفصل)"""
    symbols = symbols or list(ALL_SYMBOLS.keys())
    quotes = [(sym, fetch_quote(sym)) for sym in symbols]  # الشبكة خارج اتصال الداتابيس
    updated = 0
    with db() as conn:
        for sym, q in quotes:
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
    return updated


def _market(symbol: str) -> str:
    return ALL_SYMBOLS.get(symbol, {}).get("market", "US")


def get_cached_price(symbol: str) -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT symbol, price, prev_close, change_pct, updated_at FROM prices WHERE symbol=?", (symbol,)
        ).fetchone()
    return dict(row) if row else None


def get_cached_prices(symbols: list[str]) -> dict:
    out = {}
    with db() as conn:
        for sym in symbols:
            row = conn.execute(
                "SELECT symbol, price, prev_close, change_pct, updated_at FROM prices WHERE symbol=?", (sym,)
            ).fetchone()
            if row:
                out[sym] = dict(row)
    return out


def seed_archives(years: int = 5, symbols: list[str] | None = None):
    """تخزين البيانات التاريخية لوضع الأركيد + مراجع الأسواق (يُجرى مرة واحدة).
    (حاجزة — استدعِها في خيط منفصل)"""
    from .db import init_db
    init_db()
    syms = list(symbols) if symbols else list(ALL_SYMBOLS.keys())
    if symbols is None:
        syms += [s for s in BENCHMARK_SYMBOLS if s not in syms]
    start = (datetime.now() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
    total = 0
    with db() as conn:
        for sym in syms:
            market = _market(sym)
            try:
                df = yf.Ticker(sym).history(start=start, interval="1d", auto_adjust=False)
                if df is None or df.empty:
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
    return total


def get_candles(symbol: str, start_ts: str, end_ts: str) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """SELECT ts, open, high, low, close, volume FROM candles
               WHERE symbol=? AND ts>=? AND ts<=? ORDER BY ts""",
            (symbol, start_ts, end_ts),
        ).fetchall()
    return [dict(r) for r in rows]


def get_candle_ts_list(symbol: str) -> list[str]:
    """كل تواريخ الشموع المتاحة لرمز (مرتبة) — لاختيار نافذة بعدد شموع دقيق."""
    with db() as conn:
        rows = conn.execute(
            "SELECT ts FROM candles WHERE symbol=? ORDER BY ts", (symbol,)
        ).fetchall()
    return [r["ts"] for r in rows]


def get_available_symbols(min_candles: int = 100) -> list[str]:
    with db() as conn:
        rows = conn.execute(
            """SELECT symbol, COUNT(*) as c FROM candles
               GROUP BY symbol HAVING c >= ? ORDER BY symbol""",
            (min_candles,),
        ).fetchall()
    return [r["symbol"] for r in rows]
