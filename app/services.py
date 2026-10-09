"""
سهم — خدمات اللعبة: المستخدمون، المحفظة، التوقعات، الأركيد، الصدارة
"""
import hmac
import hashlib
import json
import math
import os
import random
from datetime import datetime, timedelta, timezone
from .constants import (
    FEE_RATE, STARTING_CAPITAL, BENCHMARKS, ALL_SYMBOLS,
    round_score_rank, points_for_rank, bonus_coins_for_round, symbol_name,
)
from .db import db
from . import market_data

# مدة صلاحية توكن الجلسة
TOKEN_TTL_DAYS = 30


def _session_secret() -> bytes:
    """سر التوقيع: SESSION_SECRET إن وُجد، وإلا يُشتق من BOT_TOKEN (إلزامي)."""
    raw = os.environ.get("SESSION_SECRET") or os.environ.get("BOT_TOKEN")
    if not raw:
        raise RuntimeError("SESSION_SECRET أو BOT_TOKEN مطلوب لتوقيع توكنات الجلسة")
    return hmac.new(b"SahemSession-v1", raw.encode(), hashlib.sha256).digest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------- التوقيع ----------
def _hmac(msg: str) -> str:
    return hmac.new(_session_secret(), msg.encode(), hashlib.sha256).hexdigest()[:32]


def sign_token(user_id: int) -> str:
    exp = int((datetime.now(timezone.utc) + timedelta(days=TOKEN_TTL_DAYS)).timestamp())
    return f"{user_id}:{exp}:{_hmac(f'sign:{user_id}:{exp}')}"


def auth_from_token(token: str) -> int | None:
    """توكن موقّع بصيغة '<user_id>:<exp>:<signature>' — يعيد user_id أو None."""
    if not token:
        return None
    parts = token.split(":")
    if len(parts) != 3:
        return None
    uid, exp, sig = parts
    if not uid.isdigit() or not exp.isdigit():
        return None
    if int(exp) < int(datetime.now(timezone.utc).timestamp()):
        return None
    if not hmac.compare_digest(sig, _hmac(f"sign:{uid}:{exp}")):
        return None
    return int(uid)


def make_auth(user_id: int) -> dict:
    return {"user_id": user_id, "token": sign_token(user_id)}


# ---------- المستخدمون ----------
def pick_tg_name(tg_user) -> str | None:
    """اسم العرض من كائن تيليجرام: @username أولاً وإلا الاسم الأول (first_name).

    كثير من اللاعبين لا يملكون @username — بلا هذا الاحتياط تظهر أسماؤهم «لاعب».
    يقبل كائن aiogram أو dict (مثل user من initData).
    """
    def _get(key: str) -> str | None:
        if tg_user is None:
            return None
        if isinstance(tg_user, dict):
            return tg_user.get(key)
        return getattr(tg_user, key, None)

    uname = (_get("username") or "").strip()
    fname = (_get("first_name") or "").strip()
    return uname or fname or None


def get_or_create_user(telegram_id: int, username: str | None = None) -> dict:
    # تنظيف الاسم (فراغات/سلاسل فارغة → None) حتى لا يُخزّن إدخال فارغ يغطّي اسماً صحيحاً
    username = (username or "").strip() or None
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO users(telegram_id, username, coins_balance) VALUES(?,?,?)",
                (telegram_id, username, STARTING_CAPITAL),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        elif username and row["username"] != username:
            # تحديث الاسم عند تغيّره في تيليجرام (لو متخلفاً هنا يبقى اسماً قديماً/فارغاً للأبد)
            conn.execute("UPDATE users SET username=? WHERE id=?", (username, row["id"]))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone()
        return dict(row)


def auth_from_initdata(init_data: str) -> dict | None:
    """التحقق من initData الصادر من تيليجرام (HMAC وفق مواصفة Telegram Web Apps).

    مثبت تجريبياً على بيانات حقيقية (Android):
      • تُفكّ ترميز URL للقيم أولاً (parse_qsl) قبل بناء سلسلة التحقق.
      • يُستثنى الحقل `hash` فقط — ويبقى `signature` داخل سلسلة التحقق.
      • يُتحقق من عمر auth_date (خلال 24 ساعة) لمنع إعادة استخدام بيانات مسروقة.
    """
    try:
        from urllib.parse import parse_qsl
        data = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = data.pop("hash", None)
        if not received_hash:
            return None
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", os.environ.get("BOT_TOKEN", "").encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, received_hash):
            return None
        # صلاحية initData: 24 ساعة
        try:
            auth_date = int(data.get("auth_date") or 0)
        except (TypeError, ValueError):
            auth_date = 0
        if not auth_date or (datetime.now(timezone.utc).timestamp() - auth_date) > 86400:
            return None
        user = json.loads(data.get("user", "{}"))
        if not user.get("id"):
            return None
        return user
    except Exception:
        return None


def get_user_by_id(user_id: int) -> dict | None:
    """جلب المستخدم من الـ id الداخلي."""
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


# ---------- المحفظة ----------
def get_portfolio(user_id: int) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """SELECT symbol, market, quantity, avg_cost FROM positions
               WHERE user_id=? AND quantity > 0.000001""",
            (user_id,),
        ).fetchall()
    positions = []
    for r in rows:
        p = market_data.get_cached_price(r["symbol"])
        price = (p or {}).get("price")
        stale = not price
        if not price:
            price = r["avg_cost"]  # احتياط: آخر تكلفة معروفة بدل الصفر
        positions.append({
            "symbol": r["symbol"],
            "name": symbol_name(r["symbol"]),
            "market": r["market"],
            "quantity": round(r["quantity"], 6),
            "avg_cost": round(r["avg_cost"], 4),
            "current_price": round(price, 4),
            "market_value": round(r["quantity"] * price, 2),
            "pnl_pct": round(((price - r["avg_cost"]) / r["avg_cost"] * 100) if r["avg_cost"] else 0, 2),
            "price_stale": stale,
        })
    return positions


def execute_trade(user_id: int, symbol: str, side: str, quantity: float) -> dict:
    """شراء/بيع فوري بسعر السوق الحقيقي، مع عمولة 0.1%. الخصم شرطي (ذرّي)."""
    side = side.lower()
    if side not in ("buy", "sell") or not _valid_qty(quantity):
        return {"ok": False, "error": "معطيات غير صحيحة"}
    price_row = market_data.get_cached_price(symbol)
    if not price_row:
        return {"ok": False, "error": "السعر غير متوفر حالياً، حاول بعد قليل"}
    price = price_row["price"]
    if not price or price <= 0:
        return {"ok": False, "error": "السعر غير صالح حالياً"}
    market = _market_of(symbol)
    fee = round(price * quantity * FEE_RATE, 2)

    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            return {"ok": False, "error": "المستخدم غير موجود"}

        if side == "buy":
            cost = price * quantity * (1 + FEE_RATE)
            cur = conn.execute(
                "UPDATE users SET coins_balance = coins_balance - ? WHERE id=? AND coins_balance >= ?",
                (cost, user_id, cost),
            )
            if cur.rowcount == 0:
                return {"ok": False,
                        "error": f"رصيد غير كافٍ (تحتاج {cost:,.0f} ولديك {user['coins_balance']:,.0f})"}
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
            cur = conn.execute(
                "UPDATE positions SET quantity = quantity - ?, updated_at=? WHERE user_id=? AND symbol=? AND market=? AND quantity >= ?",
                (quantity, _now_iso(), user_id, symbol, market, quantity - 1e-9),
            )
            if cur.rowcount == 0:
                return {"ok": False, "error": "لا تملك هذه الكمية"}
            proceeds = price * quantity * (1 - FEE_RATE)
            conn.execute("UPDATE users SET coins_balance = coins_balance + ? WHERE id=?", (proceeds, user_id))
            conn.execute(
                "UPDATE positions SET quantity = 0 WHERE user_id=? AND symbol=? AND market=? AND quantity < 1e-9",
                (user_id, symbol, market),
            )

        conn.execute(
            "INSERT INTO transactions(user_id, symbol, market, side, quantity, price, fee) VALUES(?,?,?,?,?,?,?)",
            (user_id, symbol, market, side, quantity, price, fee),
        )
        conn.commit()
        bal = conn.execute("SELECT coins_balance FROM users WHERE id=?", (user_id,)).fetchone()[0]

    return {"ok": True, "price": price, "fee": fee, "balance": round(bal, 2)}


def _valid_qty(quantity) -> bool:
    try:
        q = float(quantity)
    except (TypeError, ValueError):
        return False
    return math.isfinite(q) and q > 0


def _market_of(symbol: str) -> str:
    return ALL_SYMBOLS.get(symbol, {}).get("market", "US")


def user_balance(user_id: int) -> float:
    with db() as conn:
        row = conn.execute("SELECT coins_balance FROM users WHERE id=?", (user_id,)).fetchone()
    return row[0] if row else 0


def add_xp(user_id: int, xp: int):
    with db() as conn:
        conn.execute("UPDATE users SET xp = xp + ? WHERE id=?", (xp, user_id))
        conn.execute("UPDATE users SET level = 1 + (xp / 500) WHERE id=?", (user_id,))
        conn.commit()


# ---------- التوقعات (القسم 8) ----------
# نقاط بقيمة احتمالية: 1 ÷ نسبة تكرار النتيجة تاريخياً (تقريبية، تُعاد معايرتها دورياً)
PROB_WEIGHTS = {"up": 2.2, "down": 3.3, "flat": 4.0}
FLAT_THRESHOLD = 0.5  # %
PREDICT_STREAK_BONUS_EVERY = 5  # كل 5 إصابات متتالية = مضاعف مكافأة


def create_prediction(user_id: int, symbol: str, direction: str) -> dict:
    """توقع اتجاه إغلاق اليوم — تُسوّى بعد الإغلاق، ثم تُقارن بسعر الدخول."""
    if direction not in PROB_WEIGHTS:
        return {"ok": False, "error": "اتجاه غير صحيح"}
    now = _now_iso()
    with db() as conn:
        # منع التوقعات المكررة لنفس السهم أثناء صلاحية التوقع فقط (لا تمنعه للأبد)
        existing = conn.execute(
            """SELECT id FROM predictions WHERE user_id=? AND symbol=?
               AND result='pending' AND resolves_at > ?""",
            (user_id, symbol, now),
        ).fetchone()
        if existing:
            return {"ok": False, "error": "لديك توقعة قائمة على هذا السهم"}
        market = _market_of(symbol)
        pr = market_data.get_cached_price(symbol)
        entry_price = pr["price"] if pr else None
        resolves = (datetime.now(timezone.utc) + timedelta(hours=26)).isoformat()
        conn.execute(
            """INSERT INTO predictions(user_id, symbol, market, direction, resolves_at, entry_price, result)
               VALUES(?,?,?,?,?,?, 'pending')""",
            (user_id, symbol, market, direction, resolves, entry_price),
        )
        conn.commit()
    return {"ok": True, "symbol": symbol, "direction": direction}


def get_pending_predictions(user_id: int) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM predictions WHERE user_id=? AND result='pending' ORDER BY resolves_at DESC LIMIT 20",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_prediction_history(user_id: int) -> list[dict]:
    """سجل التوقعات المسوّاة — لعرض النتائج في الواجهة."""
    with db() as conn:
        rows = conn.execute(
            """SELECT symbol, direction, result, points, resolve_price, entry_price, predicted_at
               FROM predictions WHERE user_id=? AND result IN ('win','lose')
               ORDER BY predicted_at DESC LIMIT 30""",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def resolve_due_predictions() -> list[dict]:
    """تسوية التوقعات المستحقة — يُستدعى من الجدولة كل ساعة.

    يعيد قائمة أحداث (لكل توقع مُسوّى) ليُرسلها البوت للمستخدم.
    """
    events: list[dict] = []
    now = _now_iso()
    with db() as conn:
        due = conn.execute(
            "SELECT * FROM predictions WHERE result='pending' AND resolves_at <= ?", (now,)
        ).fetchall()
        for p in due:
            price_row = market_data.get_cached_price(p["symbol"])
            if not price_row:
                continue
            # تحقق من حداثة السعر: لا تُسوِّ ببيانات قديمة قبل وقت الاستحقاق
            try:
                upd = datetime.fromisoformat(price_row["updated_at"])
                due_dt = datetime.fromisoformat(p["resolves_at"])
            except (TypeError, ValueError):
                continue
            if upd < due_dt - timedelta(hours=6):
                continue
            entry = p["entry_price"] or price_row.get("prev_close") or price_row["price"]
            resolve = price_row["price"]
            if not entry or not resolve:
                continue
            change = (resolve - entry) / entry * 100
            actual = "up" if change > FLAT_THRESHOLD else ("down" if change < -FLAT_THRESHOLD else "flat")
            won = actual == p["direction"]
            points = PROB_WEIGHTS[p["direction"]] if won else 0
            conn.execute(
                "UPDATE predictions SET result=?, points=?, resolve_price=? WHERE id=?",
                ("win" if won else "lose", points, resolve, p["id"]),
            )
            if won:
                conn.execute("UPDATE users SET xp = xp + ? WHERE id=?", (int(points * 5), p["user_id"]))
                conn.execute("UPDATE users SET coins_balance = coins_balance + ? WHERE id=?",
                             (int(points * 50), p["user_id"]))
                # سلسلة التوقعات الصحيحة
                conn.execute("UPDATE users SET pred_streak = pred_streak + 1 WHERE id=?", (p["user_id"],))
                streak = conn.execute("SELECT pred_streak FROM users WHERE id=?", (p["user_id"],)).fetchone()[0]
                if streak and streak % PREDICT_STREAK_BONUS_EVERY == 0:
                    conn.execute("UPDATE users SET coins_balance = coins_balance + ? WHERE id=?",
                                 (2000, p["user_id"]))
            else:
                conn.execute("UPDATE users SET pred_streak = 0 WHERE id=?", (p["user_id"],))
            events.append({
                "user_id": p["user_id"],
                "symbol": p["symbol"],
                "direction": p["direction"],
                "result": "win" if won else "lose",
                "points": points,
                "change_pct": round(change, 2),
            })
        if events:
            conn.execute("UPDATE users SET level = 1 + (xp / 500)")
        conn.commit()
    return events


# ---------- الحضور اليومي ----------
DAILY_BASE_COINS = 500
DAILY_MAX_STREAK_BONUS = 6  # حتى 7 أيام


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def daily_next_coins(streak: int) -> int:
    """مكافأة الحضور المتوقعة في الاستلام القادم — مصدر واحد تُستخدم في الواجهة."""
    next_streak = (streak or 0) + 1
    return DAILY_BASE_COINS + min(next_streak - 1, DAILY_MAX_STREAK_BONUS) * 250


def claim_daily(user_id: int) -> dict:
    """مكافأة حضور يومية (مرة كل يوم UTC) مع سلسلة أيام."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    with db() as conn:
        u = conn.execute("SELECT last_daily, daily_streak FROM users WHERE id=?", (user_id,)).fetchone()
        if not u:
            return {"ok": False, "error": "المستخدم غير موجود"}
        if u["last_daily"] == today:
            return {"ok": False, "error": "استلمت مكافأة اليوم بالفعل — عد غداً", "already": True,
                    "streak": u["daily_streak"] or 0}
        streak = (u["daily_streak"] or 0) + 1 if u["last_daily"] == yesterday else 1
        bonus_steps = min(streak - 1, DAILY_MAX_STREAK_BONUS)
        coins = DAILY_BASE_COINS + bonus_steps * 250
        conn.execute("UPDATE users SET last_daily=?, daily_streak=?, coins_balance = coins_balance + ? WHERE id=?",
                     (today, streak, coins, user_id))
        conn.commit()
    return {"ok": True, "coins": coins, "streak": streak}


# ---------- الأركيد (القسم 4.4) ----------
ARCADE_STEP_SECONDS = 4          # يوم تداول ≈ 4 ثوان
ARCADE_MIN_SESSION = 30          # جولة كاملة: على الأقل 30 جلسة (≈ دقيقتان)
ARCADE_MAX_SESSION = 45
ARCADE_QUICK_SESSION = (16, 22)  # جولة سريعة: ≈ دقيقة
ARCADE_DEFAULT_SESSION = 35      # احتياط لعمليات الاستعادة بما فقدت الجلسة
MAX_OPEN_ROUNDS = 3              # حد الجولات الفردية المفتوحة لكل مستخدم

# حالة الجولة النشطة في الذاكرة (تُستعاد من الداتابيس عند فقد الذاكرة)
ACTIVE_ROUNDS: dict[int, dict] = {}


def _pick_random_window(quick: bool = False) -> dict | None:
    """اختيار رمز + نافذة تاريخية عشوائية بعدد شموع دقيق (لا نوافذ قصيرة)."""
    min_len, max_len = ARCADE_QUICK_SESSION if quick else (ARCADE_MIN_SESSION, ARCADE_MAX_SESSION)
    symbols = market_data.get_available_symbols(min_candles=min_len + 1)
    if not symbols:
        return None
    symbol = random.choice(symbols)
    ts = market_data.get_candle_ts_list(symbol)
    if len(ts) < min_len + 1:
        return None
    session_len = random.randint(min_len, min(max_len, len(ts) - 1))
    max_start = len(ts) - session_len
    if max_start < 0:
        return None
    start_idx = random.randint(0, max_start)
    return {
        "symbol": symbol,
        "session_len": session_len,
        "start_ts": ts[start_idx],
        "end_ts": ts[start_idx + session_len - 1],
    }


def arcade_rate_error(user_id: int) -> str | None:
    """حد بسيط: لا أكثر من 3 جولات فردية مفتوحة خلال آخر 30 دقيقة."""
    cutoff = datetime.now(timezone.utc).timestamp() - 1800
    with db() as conn:
        row = conn.execute(
            """SELECT COUNT(*) FROM arcade_rounds
               WHERE user_id=? AND kind='solo' AND final_value IS NULL
                 AND started_at IS NOT NULL AND started_at > ?""",
            (user_id, cutoff),
        ).fetchone()
    if row and row[0] >= MAX_OPEN_ROUNDS:
        return "لديك جولات مفتوحة كثيرة — أنهِ جولتك الحالية أو انتظر قليلاً"
    return None


def start_arcade_round(
    user_id: int,
    fixed_window: dict | None = None,
    kind: str = "solo",
    duel_id: int | None = None,
    quick: bool = False,
) -> dict | None:
    """نافذة تاريخية عشوائية (أو مثبتة لمبارزة 1v1) — quick يقصّر مدة الجولة الفردية."""
    w = fixed_window if fixed_window else _pick_random_window(quick=quick)
    if not w:
        return None
    symbol = w["symbol"]
    started_at = datetime.now(timezone.utc).timestamp()

    with db() as conn:
        conn.execute(
            """INSERT INTO arcade_rounds(user_id, scenario_seed, start_ts, end_ts, capital, kind, duel_id,
                                          symbol, started_at, rstate_cash, rstate_holdings, rstate_avg)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, f"{symbol}:{w['session_len']}", w["start_ts"], w["end_ts"], STARTING_CAPITAL, kind, duel_id,
             symbol, started_at, float(STARTING_CAPITAL), 0.0, 0.0),
        )
        round_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()

    ACTIVE_ROUNDS[round_id] = {
        "user_id": user_id,
        "symbol": symbol,
        "session_len": w["session_len"],
        "start_ts": w["start_ts"],
        "end_ts": w["end_ts"],
        "kind": kind,
        "duel_id": duel_id,
        "cash": float(STARTING_CAPITAL),
        "holdings": 0.0,
        "avg_cost": 0.0,
        "started_at": started_at,
        "finished": False,
    }
    return {
        "round_id": round_id,
        "symbol": symbol,
        "name": symbol_name(symbol),
        "capital": STARTING_CAPITAL,
        "session_len": w["session_len"],
        "step_seconds": ARCADE_STEP_SECONDS,
        "start_ts": w["start_ts"],
        "kind": kind,
        "duel_id": duel_id,
    }


def _restore_round(round_id: int, user_id: int) -> dict | None:
    """استعادة الجولة بعد فقد الذاكرة (إعادة تشغيل الخادم أثناء جولة)."""
    if not round_id:
        return None
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM arcade_rounds WHERE id=? AND user_id=?", (round_id, user_id)
        ).fetchone()
    if not row or row["final_value"] is not None:
        return None
    if row["symbol"] is None or row["started_at"] is None:
        return None
    w = (row["scenario_seed"] or "").split(":")
    try:
        session_len = int(w[1]) if len(w) > 1 else None
    except ValueError:
        session_len = None
    st = {
        "user_id": user_id,
        "symbol": row["symbol"],
        "session_len": session_len or ARCADE_DEFAULT_SESSION,
        "start_ts": row["start_ts"],
        "end_ts": row["end_ts"],
        "kind": row["kind"] or "solo",
        "duel_id": row["duel_id"],
        "cash": row["rstate_cash"] if row["rstate_cash"] is not None else float(STARTING_CAPITAL),
        "holdings": row["rstate_holdings"] or 0.0,
        "avg_cost": row["rstate_avg"] or 0.0,
        "started_at": row["started_at"],
        "finished": False,
    }
    # اللاعب عاد بعد غياب: أعِد معايرة الزمن من الخطوة الحالية حتى لا تُستنفد باقي أيامه
    try:
        candles = market_data.get_candles(st["symbol"], st["start_ts"], st["end_ts"])
        idx = _step_index(st, len(candles)) if candles else 0
        st["started_at"] = datetime.now(timezone.utc).timestamp() - idx * ARCADE_STEP_SECONDS
        with db() as conn:
            conn.execute("UPDATE arcade_rounds SET started_at=? WHERE id=?", (st["started_at"], round_id))
            conn.commit()
    except Exception:
        pass
    ACTIVE_ROUNDS[round_id] = st
    return st


def get_active_arcade(user_id: int) -> dict | None:
    """أحدث جولة غير مكتملة (فردية أو مبارزة) — لعرض «استكمال الجولة» في الواجهة."""
    with db() as conn:
        row = conn.execute(
            """SELECT * FROM arcade_rounds WHERE user_id=? AND final_value IS NULL
               AND symbol IS NOT NULL AND started_at IS NOT NULL ORDER BY id DESC LIMIT 1""",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    try:
        session_len = int((row["scenario_seed"] or ":0").split(":")[1])
    except (IndexError, ValueError):
        session_len = ARCADE_DEFAULT_SESSION
    return {
        "round_id": row["id"],
        "symbol": row["symbol"],
        "name": symbol_name(row["symbol"]),
        "capital": row["capital"],
        "session_len": session_len,
        "step_seconds": ARCADE_STEP_SECONDS,
        "start_ts": row["start_ts"],
        "kind": row["kind"] or "solo",
        "duel_id": row["duel_id"],
        "resumed": True,
    }


def resume_arcade(round_id: int, user_id: int) -> dict | None:
    """استكمال جولة معلّقة: ميتاداتا + الشموع المعروضة حتى الآن + الحالة المالية."""
    st = ACTIVE_ROUNDS.get(round_id)
    if not st or st["user_id"] != user_id:
        st = _restore_round(round_id, user_id)
        if not st or st["user_id"] != user_id:
            return None
    candles = market_data.get_candles(st["symbol"], st["start_ts"], st["end_ts"])
    if not candles:
        return None
    idx = _step_index(st, len(candles))
    return {
        "round": {
            "round_id": round_id,
            "symbol": st["symbol"],
            "name": symbol_name(st["symbol"]),
            "capital": STARTING_CAPITAL,
            "session_len": st["session_len"],
            "step_seconds": ARCADE_STEP_SECONDS,
            "start_ts": st["start_ts"],
            "kind": st["kind"],
            "duel_id": st.get("duel_id"),
            "resumed": True,
        },
        "history": candles[:idx + 1],
        "step": idx,
        "cash": round(st["cash"], 2),
        "holdings": round(st["holdings"], 6),
        "avg_cost": round(st["avg_cost"], 4),
    }


def _step_index(st: dict, candle_count: int) -> int:
    if candle_count <= 0 or st.get("started_at") is None:
        return 0
    elapsed = datetime.now(timezone.utc).timestamp() - st["started_at"]
    return max(0, min(int(elapsed // ARCADE_STEP_SECONDS), candle_count - 1))


def get_arcade_step(round_id: int, user_id: int) -> dict | None:
    """إعادة الشمعة التالية إن كان توقيتها قد حان (مضاد الغش)."""
    st = ACTIVE_ROUNDS.get(round_id)
    if not st or st["user_id"] != user_id or st["finished"]:
        st = _restore_round(round_id, user_id)
        if not st or st["user_id"] != user_id:
            return None
    candles = market_data.get_candles(st["symbol"], st["start_ts"], st["end_ts"])
    if len(candles) < ARCADE_MIN_SESSION:
        return None
    step_index = _step_index(st, len(candles))
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
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "اتجاه غير صحيح"}
    if not _valid_qty(quantity):
        return {"ok": False, "error": "الكمية يجب أن تكون أكبر من صفر"}
    st = ACTIVE_ROUNDS.get(round_id)
    if not st or st["user_id"] != user_id or st["finished"]:
        st = _restore_round(round_id, user_id)
        if not st or st["user_id"] != user_id or st["finished"]:
            return {"ok": False, "error": "الجولة غير نشطة"}
    info = get_arcade_step(round_id, user_id)
    if not info:
        return {"ok": False, "error": "الجولة غير متاحة"}
    price = info["candle"]["close"]
    if not price or price <= 0:
        return {"ok": False, "error": "السعر غير صالح"}
    if side == "buy":
        cost = price * quantity * (1 + FEE_RATE)
        if cost > st["cash"] + 1e-9:
            max_qty = st["cash"] / (price * (1 + FEE_RATE))
            return {"ok": False, "error": f"لا تملك ما يكفي — أقصى كمية: {max_qty:.4f}"}
        st["cash"] -= cost
        new_qty = st["holdings"] + quantity
        st["avg_cost"] = ((st["holdings"] * st["avg_cost"]) + (quantity * price)) / new_qty if new_qty else 0
        st["holdings"] = new_qty
    else:  # sell
        if st["holdings"] < quantity - 1e-9:
            return {"ok": False, "error": "لا تملك هذه الكمية"}
        st["cash"] += price * quantity * (1 - FEE_RATE)
        st["holdings"] -= quantity
        if st["holdings"] <= 1e-9:
            st["holdings"] = 0

    # استمرارية الحالة: حفظ حظّي إذا أعيد تشغيل الخادم أثناء الجولة
    try:
        with db() as conn:
            conn.execute(
                "UPDATE arcade_rounds SET rstate_cash=?, rstate_holdings=?, rstate_avg=? WHERE id=?",
                (st["cash"], st["holdings"], st["avg_cost"], round_id),
            )
            conn.commit()
    except Exception:
        pass
    return {
        "ok": True,
        "cash": round(st["cash"], 2),
        "holdings": round(st["holdings"], 6),
        "avg_cost": round(st["avg_cost"], 4),
        "executed_price": price,
    }


def finish_arcade_round(round_id: int, user_id: int) -> dict | None:
    """إنهاء الجولة: قيمة نهائية بسعر الخطوة الحالية + العائد الزائد على مرجع السوق."""
    st = ACTIVE_ROUNDS.pop(round_id, None)
    if not st or st["user_id"] != user_id:
        st = _restore_round(round_id, user_id)
    with db() as conn:
        round_row = conn.execute(
            "SELECT * FROM arcade_rounds WHERE id=? AND user_id=?", (round_id, user_id)
        ).fetchone()
        if not round_row or not st:
            return None

        candles = market_data.get_candles(st["symbol"], st["start_ts"], st["end_ts"])
        if candles:
            # C2: القيمة تُحسب بسعر الخطوة الحالية (لا بسعر آخر يوم في النافذة)
            idx = _step_index(st, len(candles))
            last_close = candles[idx]["close"]
        else:
            last_close = None
        final_value = st["cash"] + st["holdings"] * last_close if last_close else round_row["capital"]

        # مرجع السوق لكل سوق على حدة
        market = _market_of(st["symbol"])
        bench_symbol, bench_name = BENCHMARKS.get(market, (None, None))
        benchmark_return = 0.0
        benchmark_available = False
        if bench_symbol:
            bench = market_data.get_candles(bench_symbol, st["start_ts"], st["end_ts"])
            if len(bench) > 1 and bench[0]["close"]:
                benchmark_return = (bench[-1]["close"] - bench[0]["close"]) / bench[0]["close"] * 100
                benchmark_available = True
        stock_return = (final_value - round_row["capital"]) / round_row["capital"] * 100
        excess = stock_return - benchmark_return

        days = len(candles) if candles else st["session_len"]
        rank = round_score_rank(excess)
        pts = points_for_rank(rank, days)
        bonus = bonus_coins_for_round(final_value, round_row["capital"])

        conn.execute(
            "UPDATE arcade_rounds SET final_value=?, rank=?, excess_return=?, played_at=? WHERE id=?",
            (round(final_value, 2), rank, round(excess, 4), _now_iso(), round_id),
        )
        conn.execute("UPDATE users SET coins_balance = coins_balance + ? WHERE id=?", (bonus, user_id))
        conn.execute("UPDATE users SET xp = xp + ? WHERE id=?", (pts, user_id))
        conn.execute("UPDATE users SET level = 1 + (xp / 500) WHERE id=?", (user_id,))
        conn.commit()

    result = {
        "final_value": round(final_value, 2),
        "capital": round_row["capital"],
        "return_pct": round(stock_return, 2),
        "benchmark_return_pct": round(benchmark_return, 2),
        "benchmark_symbol": bench_symbol,
        "benchmark_name": bench_name,
        "benchmark_available": benchmark_available,
        "excess_return_pct": round(excess, 2),
        "rank": rank,
        "points": pts,
        "bonus_coins": bonus,
        "days": days,
    }

    # مبارزة 1v1؟ سجّل النتيجة
    row_keys = set(round_row.keys())
    if "kind" in row_keys and round_row["kind"] == "duel" and "duel_id" in row_keys:
        from .duels import record_duel_result
        duel_outcome = record_duel_result(round_row["duel_id"], user_id, round(excess, 2))
        if duel_outcome:
            result["duel"] = duel_outcome

    return result


# ---------- الصدارة والمبارزات (المرحلة 2) ----------
# (خطة 4.2): المعيار الموحّد أصبح standings() في league.py (العائد الزائد + توقعات) —
# والبوت و/api/leaderboard يستخدمانه مباشرة، فلا توجد لوحة بمعيار مختلف.


def user_summary(user_id: int) -> dict:
    with db() as conn:
        u = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not u:
            return {}
        wins = conn.execute("SELECT COUNT(*) FROM predictions WHERE user_id=? AND result='win'", (user_id,)).fetchone()[0]
        losses = conn.execute("SELECT COUNT(*) FROM predictions WHERE user_id=? AND result='lose'", (user_id,)).fetchone()[0]
        rounds = conn.execute(
            "SELECT COUNT(*) FROM arcade_rounds WHERE user_id=? AND final_value IS NOT NULL", (user_id,)
        ).fetchone()[0]
        out = {
            **dict(u),
            "prediction_wins": wins,
            "prediction_losses": losses,
            "prediction_total": wins + losses,
            "accuracy_pct": round(wins / (wins + losses) * 100, 1) if (wins + losses) else 0,
            "arcade_rounds": rounds,
        }
    return out


# ---------- الأوسمة (الخطة 3.4) ----------
# تُحسب لحظياً من الأرقام الموجودة — بلا جدول جديد أو ترحيل بيانات.
BADGE_DEFS = [
    {"id": "first_trade", "emoji": "🥇", "name": "أول صفقة", "desc": "نفّذت أول صفقة في محفظتك"},
    {"id": "first_round", "emoji": "🎮", "name": "أول جولة", "desc": "أكملت أول جولة أركيد"},
    {"id": "analyst", "emoji": "🎯", "name": "قارئ سوق", "desc": "أصبت في 3 توقعات"},
    {"id": "streak5", "emoji": "🔥", "name": "سلسلة 5 إصابات", "desc": "5 توقعات صحيحة متتالية"},
    {"id": "daily7", "emoji": "📅", "name": "أسبوع حضور", "desc": "7 أيام حضور متتالية"},
    {"id": "legend", "emoji": "🏆", "name": "أسطورة جولة", "desc": "عائد زائد +8% في جولة واحدة"},
    {"id": "duelist", "emoji": "⚔️", "name": "فاتح مبارزات", "desc": "فزت بأول مبارزة 1v1"},
    {"id": "league_champ", "emoji": "👑", "name": "بطل الدوري", "desc": "مركز 1 في دوري أسبوعي"},
]


def compute_badges(user_id: int) -> list[dict]:
    """قائمة الأوسمة مع حالة كل وسام (مُنجَز/قيد الانتظار)."""
    earned: dict[str, bool] = {}
    with db() as conn:
        u = conn.execute("SELECT pred_streak, daily_streak FROM users WHERE id=?", (user_id,)).fetchone()
        if not u:
            return [dict(b, earned=False) for b in BADGE_DEFS]
        earned["streak5"] = (u["pred_streak"] or 0) >= 5
        earned["daily7"] = (u["daily_streak"] or 0) >= 7
        earned["first_trade"] = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE user_id=?", (user_id,)).fetchone()[0] >= 1
        won = conn.execute(
            "SELECT COUNT(*) FROM predictions WHERE user_id=? AND result='win'", (user_id,)).fetchone()[0]
        earned["analyst"] = won >= 3
        rounds_done = conn.execute(
            "SELECT COUNT(*) FROM arcade_rounds WHERE user_id=? AND final_value IS NOT NULL",
            (user_id,)).fetchone()[0]
        earned["first_round"] = rounds_done >= 1
        earned["legend"] = conn.execute(
            "SELECT COUNT(*) FROM arcade_rounds WHERE user_id=? AND excess_return IS NOT NULL AND excess_return>=8",
            (user_id,)).fetchone()[0] >= 1
        earned["duelist"] = conn.execute(
            "SELECT COUNT(*) FROM duels WHERE winner_id=?", (user_id,)).fetchone()[0] >= 1
        earned["league_champ"] = conn.execute(
            "SELECT COUNT(*) FROM league_results WHERE user_id=? AND rank=1", (user_id,)).fetchone()[0] >= 1
    return [dict(b, earned=bool(earned.get(b["id"]))) for b in BADGE_DEFS]


# ---------- تتبّع النشاط + تذكير الحضور ----------
def touch_last_seen(user_id: int) -> None:
    """تحديث آخر تواجد في التطبيق — يُكتب فقط إذا مضت 10 دقائق لتقليل ضغط الكتابة على SQLite."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with db() as conn:
            conn.execute(
                """UPDATE users SET last_app_seen=? WHERE id=?
                   AND (last_app_seen IS NULL OR julianday(last_app_seen) < julianday('now','-10 minutes'))""",
                (now, user_id),
            )
            conn.commit()
    except Exception:
        pass


def due_daily_reminders(limit: int = 400) -> list[dict]:
    """اللاعبون النشطون (آخر 7 أيام) الذين لم يستلموا حضور اليوم ولا تذكيراً اليوم — سقف للإرسال."""
    today = utc_today()
    with db() as conn:
        rows = conn.execute(
            """SELECT id, telegram_id FROM users
               WHERE telegram_id IS NOT NULL
                 AND last_app_seen IS NOT NULL
                 AND julianday(last_app_seen) >= julianday('now','-7 days')
                 AND (last_daily IS NULL OR last_daily != ?)
                 AND (last_daily_reminder IS NULL OR last_daily_reminder != ?)
               LIMIT ?""",
            (today, today, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_daily_reminded(user_id: int) -> None:
    """توثيق أن تذكير اليوم أُرسل — يمنع التكرار مهما تعددت الجدولة."""
    try:
        with db() as conn:
            conn.execute("UPDATE users SET last_daily_reminder=? WHERE id=?", (utc_today(), user_id))
            conn.commit()
    except Exception:
        pass
