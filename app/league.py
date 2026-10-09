"""
سهم — الدوري الأسبوعي بجوائز (المرحلة 2، القسم 9 من التصميم)

• الفترة: من جمعة 00:00 إلى الجمعة التالية (بتوقيت الرياض).
• النقاط: مجموع العائد الزائد % من جولات الأركيد المكتملة فقط + 2 لكل توقع صحيح.
• الجوائز يوم الجمعة 00:05: أفضل 10 (بحد أدنى 3 جولات مكتملة) — عملات + XP +
  دفتر نتائج في league_results وإشعار بوت للمكرمين.
"""
from datetime import datetime, timedelta, timezone

from .db import db

RIYADH = timezone(timedelta(hours=3))
PRIZES = [
    (50_000, 500), (30_000, 300), (20_000, 200),
    *[(10_000, 100)] * 7,
]
MIN_ROUNDS_FOR_PRIZE = 3
WEEKLY_LEAGUE_PERIOD = 7  # أيام


def current_period(now: datetime | None = None) -> tuple[str, str]:
    """بداية الفترة الحالية: الجمعة السابقة 00:00 الرياض (ISO)."""
    now = (now or datetime.now(timezone.utc)).astimezone(RIYADH)
    days_since_friday = (now.weekday() - 4) % 7  # الجمعة = 4
    start = (now - timedelta(days=days_since_friday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end = start + timedelta(days=WEEKLY_LEAGUE_PERIOD)
    return (start.isoformat(), end.isoformat())


def _score_rows(period_start: str):
    """صفوف النقاط — الجولات المكتملة فقط. المقارنة الزمنية عبر julianday
    (دقيقة عبر صيغ ISO المختلطة: played_at بصيغة SQLite UTC، والفترة بصيغة ISO الرياض)."""
    with db() as conn:
        rows = conn.execute(
            """SELECT u.id, u.username,
                      COALESCE(SUM(CASE WHEN julianday(r.played_at) >= julianday(?)
                                        THEN COALESCE(r.excess_return, 0) END), 0) AS excess,
                      SUM(CASE WHEN julianday(r.played_at) >= julianday(?) THEN 1 ELSE 0 END) AS rounds,
                      (SELECT COUNT(*) FROM predictions p
                         WHERE p.user_id = u.id AND p.result='win'
                           AND julianday(p.predicted_at) >= julianday(?)) AS wins
               FROM users u
               LEFT JOIN arcade_rounds r
                    ON r.user_id = u.id AND r.final_value IS NOT NULL
               GROUP BY u.id
               HAVING rounds > 0 OR wins > 0""",
            (period_start, period_start, period_start),
        ).fetchall()
    return rows


def standings(period_start: str | None = None, limit: int | None = 20) -> list[dict]:
    """ترتيب الفترة — score = مجموع العائد الزائد + 2 لكل توقع صحيح."""
    ps = period_start or current_period()[0]
    out = []
    for r in _score_rows(ps):
        out.append({
            "user_id": r["id"],
            "username": r["username"],
            "excess_sum": round(r["excess"], 2),
            "rounds": r["rounds"],
            "pred_wins": r["wins"],
            "score": round(r["excess"] + 2 * r["wins"], 2),
        })
    out.sort(key=lambda x: -x["score"])
    for i, r in enumerate(out, start=1):
        r["rank"] = i
    if limit:
        out = out[:limit]
    return out


def _ar_plural(n: int, one: str, two: str, few: str, many: str) -> str:
    """صيغة العدّ العربي: 1 / 2 / 3-10 / 11+."""
    n = abs(int(n))
    if n == 1:
        return one
    if n == 2:
        return two
    if 3 <= n <= 10:
        return few
    return many


def week_countdown() -> str:
    """متبقٍ للإغلاق بصيغة نصية مطابقة للجمع (يوم/ساعة/دقيقة)."""
    _, pe = current_period()
    remain = (datetime.fromisoformat(pe) - datetime.now(RIYADH)).total_seconds()
    if remain <= 0:
        return "أوشكت على الختام"
    d, rem = divmod(int(remain), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    parts = []
    if d:
        parts.append(f"{d} {_ar_plural(d, 'يوم', 'يومان', 'أيام', 'يومًا')}")
    if h:
        parts.append(f"{h} {_ar_plural(h, 'ساعة', 'ساعتان', 'ساعات', 'ساعةً')}")
    if not parts:
        parts.append(f"{m} {_ar_plural(m, 'دقيقة', 'دقيقتان', 'دقائق', 'دقيقةً')}")
    return " و ".join(parts)


def players_count(period_start: str | None = None) -> int:
    """عدد اللاعبين المشاركين في الفترة (جولة أركيد مكتملة أو توقع)."""
    return len(_score_rows(period_start or current_period()[0]))


def my_view(user_id: int | None, period_start: str | None = None) -> dict | None:
    """مركزي هذا الأسبوع + الفجوة إلى المركز الأدنى المنافس (None خارج لوحة 10)."""
    if not user_id:
        return None
    ps = period_start or current_period()[0]
    rows = standings(ps, limit=None)
    for i, r in enumerate(rows, start=1):
        if r["user_id"] == user_id:
            view = {
                "rank": i,
                "score": r["score"],
                "rounds": r["rounds"],
                "pred_wins": r["pred_wins"],
            }
            if i == 1:
                view["gap_text"] = "أنت في القمة 🏆"
            else:
                next_row = rows[i - 2]
                gap = next_row["score"] - r["score"]
                view["gap_text"] = f"فجوة {gap:+.1f} نقطة عن «{(next_row['username'] or 'لاعب')}»"
            if r["rounds"] < MIN_ROUNDS_FOR_PRIZE:
                view["hint"] = f"أكمل {MIN_ROUNDS_FOR_PRIZE - r['rounds']} جولات أخرى لتصبح مؤهلاً للجائزة"
            return view
    return {"rank": None, "score": 0, "rounds": 0, "pred_wins": 0,
            "hint": "سجّل أول جولة أركيد هذا الأسبوع لتدخل الترتيب"}


def champions_map(user_ids: list[int]) -> set[int]:
    """معرّفات من تبوّؤا مركز 1 في أي فترة — لإظهار التاج في الصدارة والمبارزات."""
    if not user_ids:
        return set()
    with db() as conn:
        rows = conn.execute(
            f"""SELECT DISTINCT user_id FROM league_results
                WHERE rank=1 AND user_id IN ({','.join('?' * len(user_ids))})""",
            user_ids,
        ).fetchall()
    return {r[0] for r in rows}


def last_champion(period_start: str) -> dict | None:
    """بطل الفترة المذكورة (لعرضه في أعلى اللوحة)."""
    with db() as conn:
        row = conn.execute(
            """SELECT u.username, lr.score FROM league_results lr
               JOIN users u ON u.id = lr.user_id
               WHERE lr.period_start=? AND lr.rank=1""",
            (period_start,),
        ).fetchone()
    return dict(row) if row else None


def prize_for_rank(rank: int) -> tuple[int, int]:
    """(عملات، XP) لمرتبة معينة (1-10)."""
    if 1 <= rank <= len(PRIZES):
        return PRIZES[rank - 1]
    return (0, 0)


def award_weekly(bot_posts_title: str = "🏆 النهائيات الأسبوعية") -> dict:
    """مجدول الجمعة 00:05: يغلق الفترة المنتهية ويوزّع الجوائز ويوثّقها.

    idempotent: فترة تُوزّع مرتين تُكتَم بقيود UNIQUE(period_start, user_id).
    """
    ps, _ = current_period()
    # عند الجمعة 00:05 تبدأ فترة جديدة — نغلق الفترة الماضية (ps-7 .. ps)
    closed_start = (datetime.fromisoformat(ps) - timedelta(days=7)).isoformat()
    closed_end = ps

    with db() as conn:
        already = conn.execute(
            "SELECT COUNT(*) FROM league_results WHERE period_start=?", (closed_start,)
        ).fetchone()[0]
    if already:
        return {"ok": True, "note": "الفترة موزّعة مسبقاً", "period_start": closed_start, "winners": []}

    # H4: صفِّ المؤهلين (>= 3 جولات) قبل قصّ أول 10، وإلا ضاعت جوائز المؤهلين خارج العشرين
    all_rows = standings(closed_start, limit=None)
    qualified = [r for r in all_rows if r["rounds"] >= MIN_ROUNDS_FOR_PRIZE][:len(PRIZES)]

    winners = []
    with db() as conn:
        for rank, r in enumerate(qualified, start=1):
            coins, xp = prize_for_rank(rank)
            conn.execute(
                """INSERT INTO league_results
                   (period_start, period_end, user_id, rank, score, rounds, prize_coins, prize_xp)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (closed_start, closed_end, r["user_id"], rank, r["score"], r["rounds"], coins, xp),
            )
            conn.execute("UPDATE users SET coins_balance = coins_balance + ? WHERE id=?", (coins, r["user_id"]))
            conn.execute("UPDATE users SET xp = xp + ? WHERE id=?", (xp, r["user_id"]))
            # M14: مستوى منفصل بعد إضافة XP (لا يعتمد على القيمة القديمة في نفس UPDATE)
            conn.execute("UPDATE users SET level = 1 + (xp / 500) WHERE id=?", (r["user_id"],))
            r.update(prize_coins=coins, prize_xp=xp)
            winners.append(r)
        conn.commit()
    return {"ok": True, "period_start": closed_start, "period_end": closed_end, "winners": winners}


def telegram_ids_for(user_ids: list[int], period_start: str | None = None) -> list[dict]:
    """telegram_id لأصحاب المعرّفات المعطاة (لإشعار الجوائز)، مُقيّداً بالفترة إن حُدّدت."""
    if not user_ids:
        return []
    where = f"u.id IN ({','.join('?' * len(user_ids))})"
    params: list = list(user_ids)
    if period_start:
        where += " AND lr.period_start=?"
        params.append(period_start)
    with db() as conn:
        rows = conn.execute(
            f"SELECT u.telegram_id, lr.rank, lr.prize_coins, lr.user_id "
            f"FROM users u JOIN league_results lr ON lr.user_id = u.id "
            f"WHERE {where} ORDER BY lr.rank",
            params,
        ).fetchall()
    return [dict(r) for r in rows]
