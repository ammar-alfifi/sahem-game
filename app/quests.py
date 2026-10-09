"""
سهم — تحديات إنجاز يومية وأسبوعية (الخطة 3.3 من GAMEPLAY_FUN_PLAN.md)

المبدأ: التقدّم يُحسب لحظياً من تاريخ اللعب الموجود أصلاً (لا عدّادات دفترية)،
ومنح المكافأة يُوثّق مرة واحدة في quest_grants بحيث يمنع UNIQUE التكرار.
المكافآت صغيرة وممتعة (وليست بديلاً عن الدوري)؛ لا قيمة حقيقية بأي حال.
"""
from datetime import datetime, timezone

from . import league
from .db import db

DAILY = [
    {"key": "round_today", "emoji": "🎮", "title": "أنهِ جولة أركيد اليوم", "target": 1, "coins": 400, "xp": 40},
    {"key": "preds_today", "emoji": "🎯", "title": "ضع توقّعين اليوم", "target": 2, "coins": 400, "xp": 40},
    {"key": "daily_claimed", "emoji": "🎁", "title": "استلم مكافأة الحضور", "target": 1, "coins": 300, "xp": 20},
]
WEEKLY = [
    {"key": "rounds_week", "emoji": "📈", "title": "أنهِ 5 جولات أركيد", "target": 5, "coins": 2000, "xp": 150},
    {"key": "wins_week", "emoji": "✅", "title": "3 توقعات صحيحة", "target": 3, "coins": 2000, "xp": 150},
    {"key": "duel_win_week", "emoji": "⚔️", "title": "فُز بمبارزة", "target": 1, "coins": 1500, "xp": 100},
]


def _metrics(user_id: int, day: str, week_start: str) -> dict:
    with db() as conn:
        rounds_today = conn.execute(
            """SELECT COUNT(*) FROM arcade_rounds
               WHERE user_id=? AND final_value IS NOT NULL AND julianday(played_at) >= julianday(?)""",
            (user_id, day),
        ).fetchone()[0]
        preds_today = conn.execute(
            """SELECT COUNT(*) FROM predictions
               WHERE user_id=? AND julianday(predicted_at) >= julianday(?)""",
            (user_id, day),
        ).fetchone()[0]
        claimed = conn.execute("SELECT last_daily FROM users WHERE id=?", (user_id,)).fetchone()
        rounds_week = conn.execute(
            """SELECT COUNT(*) FROM arcade_rounds
               WHERE user_id=? AND final_value IS NOT NULL AND julianday(played_at) >= julianday(?)""",
            (user_id, week_start),
        ).fetchone()[0]
        wins_week = conn.execute(
            """SELECT COUNT(*) FROM predictions
               WHERE user_id=? AND result='win' AND julianday(predicted_at) >= julianday(?)""",
            (user_id, week_start),
        ).fetchone()[0]
        duels_week = conn.execute(
            """SELECT COUNT(*) FROM duels
               WHERE winner_id=? AND julianday(created_at) >= julianday(?)""",
            (user_id, week_start),
        ).fetchone()[0]
    return {
        "round_today": rounds_today,
        "preds_today": preds_today,
        "daily_claimed": 1 if (claimed and claimed[0] == day) else 0,
        "rounds_week": rounds_week,
        "wins_week": wins_week,
        "duel_win_week": duels_week,
    }


def _granted(user_id: int, kind: str, pkey: str) -> set[str]:
    with db() as conn:
        rows = conn.execute(
            "SELECT quest_key FROM quest_grants WHERE user_id=? AND kind=? AND period_key=?",
            (user_id, kind, pkey),
        ).fetchall()
    return {r[0] for r in rows}


def _grant(user_id: int, kind: str, pkey: str, qkey: str, coins: int, xp: int) -> bool:
    """منح مرة واحدة: UNIQUE يمنع التكرار حتى لو تزامن طلبان."""
    with db() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO quest_grants(user_id, kind, period_key, quest_key, coins, xp)
               VALUES(?,?,?,?,?,?)""",
            (user_id, kind, pkey, qkey, coins, xp),
        )
        if cur.rowcount:
            conn.execute("UPDATE users SET coins_balance = coins_balance + ? WHERE id=?", (coins, user_id))
            conn.execute("UPDATE users SET xp = xp + ? WHERE id=?", (xp, user_id))
            conn.execute("UPDATE users SET level = 1 + (xp / 500) WHERE id=?", (user_id,))
        conn.commit()
        return cur.rowcount > 0


def get_quests(user_id: int) -> dict:
    """حالة تحديات اليوم والأسبوع — تُمنح المكافآت تلقائياً عند الإنجاز أول مرة."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    week_start, _ = league.current_period()
    m = _metrics(user_id, day, week_start)

    def build(kind: str, defs: list[dict], pkey: str, meter: dict) -> list[dict]:
        granted = _granted(user_id, kind, pkey)
        out = []
        for q in defs:
            val = meter.get(q["key"], 0)
            done = val >= q["target"]
            rewarded = q["key"] in granted
            if done and not rewarded:
                _grant(user_id, kind, pkey, q["key"], q["coins"], q["xp"])
                rewarded = True
            out.append({
                "key": q["key"],
                "emoji": q["emoji"],
                "title": q["title"],
                "target": q["target"],
                "current": min(val, q["target"]),
                "done": rewarded,
                "reward": q["coins"],
            })
        return out

    return {
        "daily": build("daily", DAILY, day, m),
        "weekly": build("weekly", WEEKLY, week_start, m),
    }
