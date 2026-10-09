"""
سهم — خدمات اللعبة: المستخدمون، المحفظة، التوقعات، الأركيد، الصدارة
"""
import hmac
import hashlib
import json
import os
import random
from datetime import datetime, timedelta, timezone
from .constants import FEE_RATE, STARTING_CAPITAL, round_score_rank, points_for_rank, bonus_coins_for_round, symbol_name
from .db import get_db
from . import market_data

# سر توقيع التوكنات — مشتق من توكن البوت تلقائياً
_SECRET = hmac.new(b"WebAppData", os.environ.get("BOT_TOKEN", "sahem-dev-secret").encode(), hashlib.sha256).digest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------- التوقيع ----------
def _hmac(msg: str) -> str:
    return hmac.new(_SECRET, msg.encode(), hashlib.sha256).hexdigest()[:32]


def sign_token(user_id: int) -> str:
    return f"{user_id}:{_hmac(f'sign:{user_id}')}"


def auth_from_token(token: str) -> int | None:
    """توكن موقّع بصيغة '<user_id>:<signature>' — يعيد user_id أو None."""
    if not token or token.count(":") != 1:
        return None
    uid, sig = token.split(":", 1)
    if not uid.isdigit() or not hmac.compare_digest(sig, _hmac(f"sign:{uid}")):
        return None
    return int(uid)


def make_auth(user_id: int) -> dict:
    return {"user_id": user_id, "token": sign_token(user_id)}


# ---------- المستخدمون ----------
def get_or_create_user(telegram_id: int, username: str | None = None) -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO users(telegram_id, username, coins_balance) VALUES(?,?,?)",
            (telegram_id, username, STARTING_CAPITAL),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    elif username and row["username"] != username:
        conn.execute("UPDATE users SET username=? WHERE id=?", (username, row["id"]))
        conn.commit()
    u = dict(row)
    conn.close()
    return u


def auth_from_initdata(init_data: str) -> dict | None:
    """التحقق من initData الصادر من تيليجرام (HMAC وفق مواصفة Telegram Web Apps).

    ملاحظات المواصفة:
      • تُفكّ ترميز URL للقيم أولاً (parse_qsl) قبل بناء سلسلة التحقق — كما في الأمثلة الرسمية.
      • يُستثنى الحقلان `hash` و`signature` من سلسلة التحقق.
    """
    try:
        from urllib.parse import parse_qsl
        data = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = data.pop("hash", None)
        data.pop("signature", None)
        if not received_hash:
            return None
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", os.environ.get("BOT_TOKEN", "").encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, received_hash):
            return None
        user = json.loads(data.get("user", "{}"))
        if not user.get("id"):
            return None
        return user
    except Exception:
        return None


def get_user_by_id(user_id: int) -> dict | None:
    """جلب المستخدم من الـ id الداخلي."""
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------- المحفظة ----------
def get_portfolio(user_id: int) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        """SELECT symbol, market, quantity, avg_cost FROM positions
           WHERE user_id=? AND quantity > 0.000001""",
        (user_id,),
    ).fetchall()
    conn.close()
    positions = []
    prices = {}
    for r in rows:
        p = prices.get(r["symbol"]) or market_data.get_cached_price(r["symbol"]) or {"price": 0}
        positions.append({
            "symbol": r["symbol"],
            "name": symbol_name(r["symbol"]),
            "market": r["market"],
            "quantity": round(r["quantity"], 6),
            "avg_cost": round(r["avg_cost"], 4),
            "current_price": p["price"],
            "market_value": round(r["quantity"] * p["price"], 2),
            "pnl_pct": round(((p["price"] - r["avg_cost"]) / r["avg_cost"] * 100) if r["avg_cost"] else 0, 2),
        })
    return positions


def execute_trade(user_id: int, symbol: str, side: str, quantity: float) -> dict:
    """شراء/بيع فوري بسعر السوق الحقيقي، مع عمولة 0.1%."""
    side = side.lower()
    if side not in ("buy", "sell") or quantity <= 0:
        return {"ok": False, "error": "معطيات غير صحيحة"}
    price_row = market_data.get_cached_price(symbol)
    if not price_row:
        return {"ok": False, "error": "السعر غير متوفر حالياً، حاول بعد قليل"}
    price = price_row["price"]
    market = _market_of(symbol)
    fee = round(price * quantity * FEE_RATE, 2)

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        conn.close()
        return {"ok": False, "error": "المستخدم غير موجود"}

    if side == "buy":
        cost = price * quantity * (1 + FEE_RATE)
        if user["coins_balance"] < cost:
            conn.close()
            return {"ok": False, "error": f"رصيد غير كافٍ (تحتاج {cost:,.0f} و لديك {user['coins_balance']:,.0f})"}
        conn.execute("UPDATE users SET coins_balance = coins_balance - ? WHERE id=?", (cost, user_id))
        pos = conn.execute(
            "SELECT * FROM positions WHERE user_id=? AND symbol=? AND market=?", (user_id, symbol, market)
        ).fetchone()
        if pos:
            new_qty = pos["quantity"] + quantity
            new_avg = ((pos["quantity"] * pos["avg_cost"]) + (quantity * price)) / new_qty
            conn.execute(
                "UPDATE positions SET quantity=?, avg_cost=?, updated_at=? WHERE id=?",
                (new_qty, new_avg, _now_iso(), pos["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO positions(user_id, symbol, market, quantity, avg_cost) VALUES(?,?,?,?,?)",
                (user_id, symbol, market, quantity, price),
            )
    else:  # sell
        pos = conn.execute(
            "SELECT * FROM positions WHERE user_id=? AND symbol=? AND market=?", (user_id, symbol, market)
        ).fetchone()
        if not pos or pos["quantity"] < quantity - 1e-9:
            conn.close()
            return {"ok": False, "error": "لا تملك هذه الكمية"}
        proceeds = price * quantity * (1 - FEE_RATE)
        conn.execute("UPDATE users SET coins_balance = coins_balance + ? WHERE id=?", (proceeds, user_id))
        new_qty = pos["quantity"] - quantity
        conn.execute(
            "UPDATE positions SET quantity=?, updated_at=? WHERE id=?",
            (new_qty if new_qty > 1e-9 else 0, _now_iso(), pos["id"]),
        )

    conn.execute(
        "INSERT INTO transactions(user_id, symbol, market, side, quantity, price, fee) VALUES(?,?,?,?,?,?,?)",
        (user_id, symbol, market, side, quantity, price, fee),
    )
    conn.commit()
    bal = conn.execute("SELECT coins_balance FROM users WHERE id=?", (user_id,)).fetchone()[0]
    conn.close()
    return {"ok": True, "price": price, "fee": fee, "balance": round(bal, 2)}


def _market_of(symbol: str) -> str:
    from .constants import ALL_SYMBOLS
    return ALL_SYMBOLS.get(symbol, {}).get("market", "US")


def user_balance(user_id: int) -> float:
    conn = get_db()
    row = conn.execute("SELECT coins_balance FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return row[0] if row else 0


def add_xp(user_id: int, xp: int):
    conn = get_db()
    conn.execute("UPDATE users SET xp = xp + ? WHERE id=?", (xp, user_id))
    # مستوى بسيط: كل 500 XP مستوى
    conn.execute("""
        UPDATE users SET level = 1 + (xp / 500) WHERE id=?
    """, (user_id,))
    conn.commit()
    conn.close()


# ---------- التوقعات (القسم 8) ----------
# نقاط بقيمة احتمالية: 1 ÷ نسبة تكرار النتيجة تاريخياً (تقريبية، تُعاد معايرتها دورياً)
PROB_WEIGHTS = {"up": 2.2, "down": 3.3, "flat": 4.0}
FLAT_THRESHOLD = 0.5  # %


def create_prediction(user_id: int, symbol: str, direction: str) -> dict:
    """توقع اتجاه إغلاق اليوم — تُسوّى بعد إغلاق السوق (خلال ساعتين)."""
    if direction not in PROB_WEIGHTS:
        return {"ok": False, "error": "اتجاه غير صحيح"}
    conn = get_db()
    # منع توقعات مكررة لنفس السهم نفس اليوم
    existing = conn.execute(
        """SELECT id FROM predictions WHERE user_id=? AND symbol=?
           AND result='pending'""",
        (user_id, symbol),
    ).fetchone()
    if existing:
        conn.close()
        return {"ok": False, "error": "لديك توقعة قائمة على هذا السهم"}
    market = _market_of(symbol)
    resolves = (datetime.now(timezone.utc) + timedelta(hours=26)).isoformat()
    conn.execute(
        """INSERT INTO predictions(user_id, symbol, market, direction, resolves_at) VALUES(?,?,?,?,?)""",
        (user_id, symbol, market, direction, resolves),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "symbol": symbol, "direction": direction}


def get_pending_predictions(user_id: int) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM predictions WHERE user_id=? AND result='pending' ORDER BY resolves_at DESC LIMIT 20",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def resolve_due_predictions() -> int:
    """تسوية التوقعات المستحقة — يُستدعى من الجدولة كل ساعة."""
    conn = get_db()
    now = _now_iso()
    due = conn.execute(
        "SELECT * FROM predictions WHERE result='pending' AND resolves_at <= ?", (now,)
    ).fetchall()
    resolved = 0
    for p in due:
        price_row = market_data.get_cached_price(p["symbol"])
        if not price_row:
            continue
        change = price_row.get("change_pct") or 0.0
        actual = "up" if change > FLAT_THRESHOLD else ("down" if change < -FLAT_THRESHOLD else "flat")
        if actual == p["direction"]:
            points = PROB_WEIGHTS[p["direction"]]
            conn.execute(
                "UPDATE predictions SET result='win', points=? WHERE id=?", (points, p["id"])
            )
            conn.execute(
                "UPDATE users SET xp = xp + ? WHERE id=?", (int(points * 5), p["user_id"])
            )
            conn.execute(
                """UPDATE users SET coins_balance = coins_balance + ? WHERE id=?""",
                (int(points * 50), p["user_id"]),
            )
        else:
            conn.execute("UPDATE predictions SET result='lose', points=0 WHERE id=?", (p["id"],))
        resolved += 1
    if resolved:
        conn.execute("UPDATE users SET level = 1 + (xp / 500)")
    conn.commit()
    conn.close()
    return resolved


# ---------- الأركيد (القسم 4.4) ----------
ARCADE_STEP_SECONDS = 4          # يوم تداول ≈ 4 ثوان
ARCADE_MIN_SESSION = 30          # جولة على الأقل 30 جلسة تداول (≈ دقيقتان)
ARCADE_MAX_SESSION = 45

# حالة الجولة النشطة في الذاكرة (تصفية عند إعادة التشغيل — مقبول ل MVP)
ACTIVE_ROUNDS: dict[int, dict] = {}


def start_arcade_round(user_id: int) -> dict | None:
    """نافذة تاريخية عشوائية: رمز عشوائي + بداية عشوائية + مدة عشوائية."""
    symbols = market_data.get_available_symbols(min_candles=ARCADE_MAX_SESSION + 10)
    if not symbols:
        return None
    symbol = random.choice(symbols)
    conn = get_db()
    count_row = conn.execute(
        """SELECT MIN(ts) as first, MAX(ts) as last, COUNT(*) as n FROM candles WHERE symbol=?""",
        (symbol,),
    ).fetchone()
    if not count_row or count_row["n"] < ARCADE_MAX_SESSION + 10:
        conn.close()
        return None
    first = datetime.fromisoformat(count_row["first"])
    last = datetime.fromisoformat(count_row["last"])
    # نافذة عشوائية
    session_len = random.randint(ARCADE_MIN_SESSION, ARCADE_MAX_SESSION)  # أيام تداول
    random_position = random.randint(0, max(1, (last - first).days))
    start_ts = first + timedelta(days=random_position)
    # الأيام التقويمية التقريبية لتحويل جلسات تداول
    end_ts = start_ts + timedelta(days=int(session_len * 1.6) + 3)
    end_ts = min(end_ts, last)

    round_row = conn.execute(
        """INSERT INTO arcade_rounds(user_id, scenario_seed, start_ts, end_ts, capital)
           VALUES(?,?,?,?,?)""",
        (user_id, f"{symbol}:{session_len}", start_ts.strftime("%Y-%m-%d"), end_ts.strftime("%Y-%m-%d"), STARTING_CAPITAL),
    )
    round_id = round_row.lastrowid
    conn.commit()
    conn.close()

    ACTIVE_ROUNDS[round_id] = {
        "user_id": user_id,
        "symbol": symbol,
        "session_len": session_len,
        "start_ts": start_ts.strftime("%Y-%m-%d"),
        "end_ts": end_ts.strftime("%Y-%m-%d"),
        "cash": float(STARTING_CAPITAL),
        "holdings": 0.0,
        "avg_cost": 0.0,
        "started_at": datetime.now(timezone.utc).timestamp(),
        "finished": False,
    }
    return {
        "round_id": round_id,
        "symbol": symbol,
        "name": symbol_name(symbol),
        "capital": STARTING_CAPITAL,
        "session_len": session_len,
        "step_seconds": ARCADE_STEP_SECONDS,
        "start_ts": start_ts.strftime("%Y-%m-%d"),
    }


def get_arcade_step(round_id: int, user_id: int) -> dict | None:
    """إعادة الشمعة التالية إن كان توقيتها قد حان (مضاد الغش)."""
    st = ACTIVE_ROUNDS.get(round_id)
    if not st or st["user_id"] != user_id or st["finished"]:
        return None
    candles = market_data.get_candles(st["symbol"], st["start_ts"], st["end_ts"])
    if len(candles) < ARCADE_MIN_SESSION:
        return None
    elapsed = datetime.now(timezone.utc).timestamp() - st["started_at"]
    step_index = int(elapsed // ARCADE_STEP_SECONDS)
    step_index = min(step_index, len(candles) - 1)
    candle = candles[step_index]
    is_last = step_index == len(candles) - 1
    return {
        "round_id": round_id,
        "step": step_index,
        "total_steps": len(candles),
        "candle": candle,
        "cash": round(st["cash"], 2),
        "holdings": round(st["holdings"], 6),
        "portfolio_value": round(st["cash"] + st["holdings"] * candle["close"], 2),
        "is_last": is_last,
    }


def arcade_trade(round_id: int, user_id: int, side: str, quantity: float) -> dict:
    """تنفيذ صفقة داخل الجولة بسعر إغلاق الخطوة الحالية (عمولة 0.1%)."""
    st = ACTIVE_ROUNDS.get(round_id)
    if not st or st["user_id"] != user_id or st["finished"]:
        return {"ok": False, "error": "الجولة غير نشطة"}
    info = get_arcade_step(round_id, user_id)
    if not info:
        return {"ok": False, "error": "الجولة غير متاحة"}
    price = info["candle"]["close"]
    if side == "buy":
        cost = price * quantity * (1 + FEE_RATE)
        if cost > st["cash"] + 1e-9:
            max_qty = st["cash"] / (price * (1 + FEE_RATE))
            return {"ok": False, "error": f"لا تملك ما يكفي — أقصى كمية: {max_qty:.4f}"}
        st["cash"] -= cost
        new_qty = st["holdings"] + quantity
        st["avg_cost"] = ((st["holdings"] * st["avg_cost"]) + (quantity * price)) / new_qty if new_qty else 0
        st["holdings"] = new_qty
    elif side == "sell":
        if st["holdings"] < quantity - 1e-9:
            return {"ok": False, "error": "لا تملك هذه الكمية"}
        st["cash"] += price * quantity * (1 - FEE_RATE)
        st["holdings"] -= quantity
        if st["holdings"] <= 1e-9:
            st["holdings"] = 0
    else:  # انتظار / وقف خسارة — MVP: انتظار فقط
        pass
    return {
        "ok": True,
        "cash": round(st["cash"], 2),
        "holdings": round(st["holdings"], 6),
        "avg_cost": round(st["avg_cost"], 4),
        "executed_price": price,
    }


def finish_arcade_round(round_id: int, user_id: int) -> dict | None:
    """إنهاء الجولة: قيمة نهائية + العائد الزائد على المؤشر + نقاط ومكافآت."""
    st = ACTIVE_ROUNDS.pop(round_id, None)
    conn = get_db()
    round_row = conn.execute("SELECT * FROM arcade_rounds WHERE id=? AND user_id=?", (round_id, user_id)).fetchone()
    if not round_row or not st:
        conn.close()
        return None
    candles = market_data.get_candles(st["symbol"], st["start_ts"], st["end_ts"])
    last_close = candles[-1]["close"] if candles else None
    final_value = st["cash"] + st["holdings"] * last_close if last_close else round_row["capital"]

    # العائد الزائد: نسبة أداء السهم أثناء الجولة (المؤشر التاريخي — تحتاج TABLE أدق لاحقاً؛ نستخدم السهم ك مرجع حالياً مع تقييم نافذة السوق من Candles مرجعية أرامكو)
    # مرجع السوق الاسترشادي: أرامكو (2222.SR) خلال نفس النافذة إن توفرت، وإلا = 0
    benchmark_return = 0.0
    bench = market_data.get_candles("2222.SR", st["start_ts"], st["end_ts"])
    if len(bench) > 1:
        benchmark_return = (bench[-1]["close"] - bench[0]["close"]) / bench[0]["close"] * 100
    stock_return = (final_value - round_row["capital"]) / round_row["capital"] * 100
    excess = stock_return - benchmark_return

    days = len(candles)
    rank = round_score_rank(excess)
    pts = points_for_rank(rank, days)
    bonus = bonus_coins_for_round(final_value, round_row["capital"])

    conn.execute(
        "UPDATE arcade_rounds SET final_value=?, rank=?, played_at=? WHERE id=?",
        (round(final_value, 2), rank, _now_iso(), round_id),
    )
    conn.execute("UPDATE users SET coins_balance = coins_balance + ? WHERE id=?", (bonus, user_id))
    conn.execute("UPDATE users SET xp = xp + ? WHERE id=?", (pts, user_id))
    conn.execute("UPDATE users SET level = 1 + (xp / 500) WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    return {
        "final_value": round(final_value, 2),
        "capital": round_row["capital"],
        "return_pct": round(stock_return, 2),
        "benchmark_return_pct": round(benchmark_return, 2),
        "excess_return_pct": round(excess, 2),
        "rank": rank,
        "points": pts,
        "bonus_coins": bonus,
        "days": days,
    }


# ---------- الصدارة والمبارزات (لاحقاً في المرحلة 2) ----------
def weekly_leaderboard(limit: int = 20) -> list[dict]:
    conn = get_db()
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    # أفضل جولة لكل لاعب خلال الأسبوع — ثم كليهم منتصر
    rows = conn.execute(
        """SELECT u.username, u.level, u.xp,
                  SUM(COALESCE(r.final_value, 0)) as weekly_value,
                  COUNT(r.id) as rounds
           FROM users u LEFT JOIN arcade_rounds r
                ON r.user_id = u.id AND r.played_at >= ?
           GROUP BY u.id
           ORDER BY weekly_value DESC
           LIMIT ?""",
        (week_ago, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def user_summary(user_id: int) -> dict:
    conn = get_db()
    u = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not u:
        conn.close()
        return {}
    wins = conn.execute("SELECT COUNT(*) FROM predictions WHERE user_id=? AND result='win'", (user_id,)).fetchone()[0]
    losses = conn.execute("SELECT COUNT(*) FROM predictions WHERE user_id=? AND result='lose'", (user_id,)).fetchone()[0]
    rounds = conn.execute("SELECT COUNT(*) FROM arcade_rounds WHERE user_id=?", (user_id,)).fetchone()[0]
    conn.close()
    total = wins + losses
    return {
        **dict(u),
        "prediction_wins": wins,
        "prediction_losses": losses,
        "prediction_total": total,
        "accuracy_pct": round(wins / total * 100, 1) if total else 0,
        "arcade_rounds": rounds,
    }
