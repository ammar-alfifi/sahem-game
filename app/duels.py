"""
سهم — مبارزات 1v1 (المرحلة 2)

المفهوم: لاعبان يتقاسمان نفس النافذة التاريخية (نفس السهم ونفس الأيام) ورأس مال
متطابق — والفائز صاحب العائد «الزائد» الأعلى عن السوق. المبارزة غير متزامنة:
لكل لاعب إيقاعه خلال صلاحية 24 ساعة، والخامل تلقائياً خاسر.

المكافآت: الفائز +120 نقطة و +5,000 عملة — الخاسر نقاط مشاركة فقط حتى
لا يمثّل التهرب حكمةً رابحة.
"""
import secrets
from datetime import datetime, timedelta, timezone

from . import services
from .db import db
from .constants import symbol_name
from .telegram_client import get_bot

DUEL_TTL_HOURS = 24
DUEL_POINTS_WIN = 120
DUEL_POINTS_PARTICIPATE = 30
DUEL_POINTS_TIE = 75
DUEL_COINS_WIN = 5000

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # بلا حروف ملتبسة (I,O,0,1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))


def _get(duel_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM duels WHERE id=?", (duel_id,)).fetchone()
    return dict(row) if row else None


def _player_name(user_id: int) -> str:
    with db() as conn:
        row = conn.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
    return (row[0] if row and row[0] else "لاعب") or "لاعب"


def create_duel(user_id: int) -> dict:
    """إنشاء مبارزة تحدٍّ: رمز مشاركة + نافذة تاريخية تُثبّت للطرفين."""
    with db() as conn:
        open_row = conn.execute(
            "SELECT id, status FROM duels WHERE (challenger_id=? OR opponent_id=?) AND status IN ('open','active') LIMIT 1",
            (user_id, user_id),
        ).fetchone()
    if open_row:
        if open_row["status"] == "open":
            return {"ok": True, "duel": duel_view(_get(open_row["id"]), user_id), "note": "reused"}
        return {"ok": False, "error": "لديك مباراة قائمة بالفعل — أنهِها أولاً"}

    window = services._pick_random_window()
    if not window:
        return {"ok": False, "error": "لا توجد بيانات تاريخية بعد — جرّب بعد قليل"}

    code = _new_code()
    with db() as conn:
        conn.execute(
            """INSERT INTO duels(code, challenger_id, symbol, start_ts, end_ts, session_len, status, expires_at)
               VALUES(?,?,?,?,?,?, 'open', ?)""",
            (code, user_id, window["symbol"], window["start_ts"], window["end_ts"], window["session_len"],
             _iso(_now() + timedelta(hours=DUEL_TTL_HOURS))),
        )
        duel_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
    return {"ok": True, "duel": duel_view(_get(duel_id), user_id)}


def _match_err(code) -> str:
    return "لا يوجد تحدٍّ بانتظار خصم الآن — أنشئ تحدياً وشاركه" if code in ("?", "", None) \
        else "رمز غير صحيح أو أن أحداً سبقك إليه"


def join_duel(user_id: int, code: str) -> dict:
    """الانضمام بخصم. code='?' → أقدم تحدٍّ مفتوح آخر (مطابقة سريعة)."""
    with db() as conn:
        if code in ("?", "", None):
            row = conn.execute(
                """SELECT id FROM duels
                   WHERE status='open' AND challenger_id!=? AND opponent_id IS NULL
                     AND expires_at > ? ORDER BY created_at ASC LIMIT 1""",
                (user_id, _iso(_now())),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT id FROM duels
                   WHERE code=? AND status='open' AND opponent_id IS NULL""",
                (str(code).strip().upper(),),
            ).fetchone()
        if not row:
            return {"ok": False, "error": _match_err(code)}
        duel_id = row[0]

        d = _get(duel_id)
        if not d or d["expires_at"] <= _iso(_now()):
            return {"ok": False, "error": "صلاحية التحدي انتهت — اطلب رمزاً جديداً"}
        if d["challenger_id"] == user_id:
            return {"ok": False, "error": "لا تستطيع تحدي نفسك"}

        # انضمام ذرّي (يمنع سباق خصمين) + تجديد الصلاحية 24 ساعة من الآن
        new_expiry = _iso(_now() + timedelta(hours=DUEL_TTL_HOURS))
        cur = conn.execute(
            """UPDATE duels SET opponent_id=?, status='active', expires_at=?
               WHERE id=? AND status='open' AND opponent_id IS NULL""",
            (user_id, new_expiry, duel_id),
        )
        if cur.rowcount == 0:
            return {"ok": False, "error": "رمز غير صحيح أو أن أحداً سبقك إليه"}
        conn.commit()
    return {"ok": True, "duel": duel_view(_get(duel_id), user_id)}


def play_duel_round(user_id: int, duel_id: int) -> dict:
    """كل طرف يبدأ جولته الخاصة على النافذة المشتركة — فرصة واحدة لكل طرف."""
    d = _get(duel_id)
    if not d:
        return {"ok": False, "error": "المبارزة غير موجودة"}
    if d["status"] in ("open", "expired"):
        return {"ok": False, "error": "لم يدخل الخصم بعد"}
    if d["status"] == "finished":
        return {"ok": False, "error": "المبارزة انتهت"}
    if user_id not in (d["challenger_id"], d["opponent_id"]):
        return {"ok": False, "error": "هذه ليست مباراتك"}

    with db() as conn:
        exists = conn.execute(
            "SELECT id FROM arcade_rounds WHERE duel_id=? AND user_id=?", (duel_id, user_id)
        ).fetchone()
    if exists:
        return {"ok": False, "error": "سجلك في هذه المبارزة محفوظ بالفعل"}

    wnd = {
        "symbol": d["symbol"],
        "session_len": d["session_len"],
        "start_ts": d["start_ts"],
        "end_ts": d["end_ts"],
    }
    rnd = services.start_arcade_round(user_id, fixed_window=wnd, kind="duel", duel_id=duel_id)
    if not rnd:
        return {"ok": False, "error": "النافذة غير متاحة — جرّب بعد لحظات"}
    return {"ok": True, "round": rnd, "duel": duel_view(d, user_id)}


def record_duel_result(duel_id: int, user_id: int, excess_pct: float) -> dict | None:
    """يُستدعى من لحظة إنهاء جولتك — يخزّن العائد ويحسم الفوز عند اكتمال الطرفين."""
    d = _get(duel_id)
    if not d or d["status"] != "active":
        return None
    if user_id not in (d["challenger_id"], d["opponent_id"]):
        return None

    col = "challenger_excess" if user_id == d["challenger_id"] else "opponent_excess"

    with db() as conn:
        conn.execute(f"UPDATE duels SET {col}=? WHERE id=?", (excess_pct, duel_id))
        row = conn.execute(
            "SELECT challenger_excess, opponent_excess FROM duels WHERE id=?", (duel_id,)
        ).fetchone()
        c_x, o_x = row[0], row[1]

        if c_x is not None and o_x is not None:
            if round(c_x, 2) == round(o_x, 2):
                winner = None
                pts_c = pts_o = DUEL_POINTS_TIE
                extra_c = extra_o = 0
            else:
                winner = d["challenger_id"] if c_x > o_x else d["opponent_id"]
                pts_c = DUEL_POINTS_WIN if winner == d["challenger_id"] else DUEL_POINTS_PARTICIPATE
                pts_o = DUEL_POINTS_WIN if winner == d["opponent_id"] else DUEL_POINTS_PARTICIPATE
                extra_c = DUEL_COINS_WIN if winner == d["challenger_id"] else 0
                extra_o = DUEL_COINS_WIN if winner == d["opponent_id"] else 0
            conn.execute("UPDATE duels SET status='finished', winner_id=? WHERE id=?", (winner, duel_id))
            conn.execute(
                "UPDATE users SET coins_balance = coins_balance + ?, xp = xp + ? WHERE id=?",
                (extra_c, pts_c, d["challenger_id"]),
            )
            conn.execute(
                "UPDATE users SET coins_balance = coins_balance + ?, xp = xp + ? WHERE id=?",
                (extra_o, pts_o, d["opponent_id"]),
            )
            if winner:
                conn.execute("UPDATE users SET level = 1 + (xp / 500) WHERE id=?", (winner,))
            conn.commit()

            if winner is None:
                return {"state": "done", "message": f"🤝 تعادل! تقاسمتما {DUEL_POINTS_TIE} نقطة لكل طرف",
                        "duel": duel_view(_get(duel_id), user_id)}
            won = winner == user_id
            return {
                "state": "done",
                "message": (f"🏆 فزت بالمبارزة! +{DUEL_POINTS_WIN} نقطة و+{DUEL_COINS_WIN:,} عملة") if won
                else f"💀 خسرت المبارزة — +{DUEL_POINTS_PARTICIPATE} نقطة مشاركة، الموالية لك",
                "duel": duel_view(_get(duel_id), user_id),
            }

        conn.commit()
    return {
        "state": "waiting",
        "message": "🎯 سجّلت نتيجتك — بانتظار خصمك أن يُنهي جولته خلال الصلاحية",
    }


def duel_view(d: dict, viewer_id: int | None = None) -> dict:
    """عرض مستقر للواجهة مع الأسماء.

    إخفاء النتائج: لا يُكشف عائد الخصم قبل انتهاء المبارزة (منعاً للغش)،
    ويُعرض للاعب عائده هو فقط أثناء الانتظار.
    """
    finished = d["status"] == "finished"
    c, o = d["challenger_excess"], d["opponent_excess"]
    show_c = c if (finished or viewer_id == d["challenger_id"]) else None
    show_o = o if (finished or viewer_id == d["opponent_id"]) else None
    return {
        "id": d["id"],
        "code": d["code"],
        "symbol": d["symbol"],
        "symbol_name": symbol_name(d["symbol"]),
        "start_ts": d["start_ts"],
        "end_ts": d["end_ts"],
        "session_len": d["session_len"],
        "status": d["status"],
        "challenger_id": d["challenger_id"],
        "challenger_name": _player_name(d["challenger_id"]),
        "opponent_id": d["opponent_id"],
        "opponent_name": _player_name(d["opponent_id"]) if d["opponent_id"] else None,
        "challenger_excess": show_c,
        "opponent_excess": show_o,
        "winner_id": d["winner_id"] if d["winner_id"] else None,
        "expires_at": d["expires_at"],
        "created_at": d["created_at"],
    }


def list_duels(user_id: int) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """SELECT * FROM duels
               WHERE challenger_id=? OR opponent_id=?
               ORDER BY CASE status WHEN 'finished' THEN 1 ELSE 0 END, id DESC
               LIMIT 20""",
            (user_id, user_id),
        ).fetchall()
    return [duel_view(dict(r), user_id) for r in rows]


def resolve_due_duels() -> tuple[int, list[dict]]:
    """مجدول: إسقاط التحديات المنتهية، أو إعلان فائزٍ وحيد أكمل ولم يُكمل خصمه.
    تعيد (عدد المعاملات، أحداث إشعار)."""
    now = _iso(_now())
    n = 0
    events: list[dict] = []

    with db() as conn:
        open_due = conn.execute(
            "SELECT id, challenger_id FROM duels WHERE status='open' AND expires_at<=?", (now,)
        ).fetchall()
        for did, ch in open_due:
            conn.execute("UPDATE duels SET status='expired' WHERE id=?", (did,))
            n += 1
            if ch:
                events.append({
                    "type": "expired",
                    "duel_id": did,
                    "user_ids": [ch],
                    "reason": "لم ينضم أحد إلى تحدّيك خلال 24 ساعة — أنشئ تحدياً جديداً وشاركه مباشرة",
                })

        active_due = conn.execute(
            "SELECT * FROM duels WHERE status='active' AND expires_at<=?", (now,)
        ).fetchall()
        for r in active_due:
            fin_c = conn.execute(
                "SELECT id FROM arcade_rounds WHERE duel_id=? AND user_id=? AND final_value IS NOT NULL",
                (r["id"], r["challenger_id"]),
            ).fetchone()
            fin_o = conn.execute(
                "SELECT id FROM arcade_rounds WHERE duel_id=? AND user_id=? AND final_value IS NOT NULL",
                (r["id"], r["opponent_id"]),
            ).fetchone()
            if fin_c and fin_o:
                continue  # النتائج مسجلة بالفعل — الحكم في record_duel_result
            if fin_c or fin_o:
                winner = r["challenger_id"] if fin_c else r["opponent_id"]
                loser = r["opponent_id"] if fin_c else r["challenger_id"]
                conn.execute(
                    "UPDATE users SET coins_balance = coins_balance + ?, xp = xp + ? WHERE id=?",
                    (DUEL_COINS_WIN, DUEL_POINTS_WIN, winner),
                )
                conn.execute("UPDATE users SET level = 1 + (xp / 500) WHERE id=?", (winner,))
                conn.execute("UPDATE duels SET status='finished', winner_id=? WHERE id=?", (winner, r["id"]))
                n += 1
                events.append({
                    "type": "resolved",
                    "duel_id": r["id"],
                    "user_ids": [winner, loser],
                    "reason": "حُسمت بالانتهاء: أنهى أحدكما جولته ولم يُكمل الآخر خلال الصلاحية",
                })
            else:
                conn.execute("UPDATE duels SET status='expired' WHERE id=?", (r["id"],))
                n += 1
                events.append({
                    "type": "expired",
                    "duel_id": r["id"],
                    "user_ids": [r["challenger_id"], r["opponent_id"]],
                    "reason": "لم يُنهِ أحدكما جولته خلال 24 ساعة — المبارزة سُقطت بلا مكافآت",
                })
        conn.commit()
    return n, events


async def notify_challenger_joined(duel_id: int):
    """رسالة للمُتحدّي: الخصم قبل التحدي."""
    try:
        d = _get(duel_id)
        if not d or not d["opponent_id"]:
            return
        with db() as conn:
            tg = conn.execute("SELECT telegram_id FROM users WHERE id=?", (d["challenger_id"],)).fetchone()
        if not tg:
            return
        bot = get_bot()
        await bot.send_message(
            tg[0],
            f"⚔️ الخصم قبل التحدي وستنطلق المعركة!\n"
            f"📊 {symbol_name(d['symbol'])} • {d['session_len']} يوم تاريخي\n"
            f"🗓️ نافذة واحدة للطرفين — الفائز أعلى عائد زائد\n\n"
            f"👤 الخصم: {_player_name(d['opponent_id'])}\n\n"
            "افتح التطبيق → الأركيد → «مبارزة» لتلعب جولتك (فرصة واحدة!).",
        )
    except Exception:
        pass


# ---------- إشعارات بوت ----------
def _duel_outcome_text(d: dict, user_id: int) -> str:
    """نص ملخّص محايد لنتيجة المبارزة من منظور side محدد."""
    won = d["winner_id"] == user_id
    tie = d["winner_id"] is None
    mine = d["challenger_excess"] if user_id == d["challenger_id"] else d["opponent_excess"]
    if tie:
        head = f"🤝 انتهت المبارزة بالتعادل! +{DUEL_POINTS_TIE} نقطة لكل طرف"
    elif won:
        head = f"🏆 فزت بالمبارزة! +{DUEL_POINTS_WIN} نقطة و +{DUEL_COINS_WIN:,} عملة"
    else:
        head = f"💀 خسرت المبارزة — +{DUEL_POINTS_PARTICIPATE} نقطة مشاركة، الموالية لك"
    return (
        f"{head}\n"
        f"📊 {symbol_name(d['symbol'])} • {d['session_len']} يوم تاريخي\n"
        f"🅰️ {d['challenger_name']}: {(d['challenger_excess'] or 0):+.2f}%\n"
        f"🅱️ {(d['opponent_name'] or 'خصم')}: {(d['opponent_excess'] or 0):+.2f}%\n"
        f"🪙 عائدك الزائد: {(mine or 0):+.2f}%"
    )


async def notify_duel_result(duel_id: int):
    """حُسمت المبارزة بإكمال الطرفين — ملخّص لكل طرف بمنظوره."""
    try:
        d = _get(duel_id)
        if not d or d["status"] != "finished":
            return
        await _send_to_users(
            [d["challenger_id"], d["opponent_id"]],
            lambda uid: "⚔️ حُسمت المبارزة!\n" + _duel_outcome_text(d, uid),
        )
    except Exception:
        pass


async def notify_duel_event(event: dict):
    """أحداث المجدول: 'resolved' (فوز بحكم الانتهاء) أو 'expired' (سقوط دون مكافآت)."""
    try:
        ids = [u for u in event.get("user_ids", []) if u]
        if not ids:
            return
        reason = str(event.get("reason", "")).strip()

        if event.get("type") == "resolved":
            d = _get(event.get("duel_id"))
            if d:
                def text_for(uid, _d=d):
                    if uid == _d["winner_id"]:
                        return ("🏆 فزت بالمبارزة بحكم الانتهاء! "
                                f"+{DUEL_POINTS_WIN} نقطة و +{DUEL_COINS_WIN:,} عملة\n"
                                f"📊 {symbol_name(_d['symbol'])} • {_d['session_len']} يوم تاريخي")
                    return ("⌛ انتهت المبارزة — لم تُنهِ جولتك خلال 24 ساعة فخسرتها بلا نقاط\n"
                            f"📊 {symbol_name(_d['symbol'])} • {_d['session_len']} يوم تاريخي\n"
                            "💡 الخصم أنجز جولته وأنت لا — العب جولتك أول ما يقبل الخصم التحدي")
                await _send_to_users(ids, text_for)
        elif event.get("type") == "expired":
            await _send_to_users(ids, lambda uid: f"⌛ انتهت صلاحية المبارزة\n{reason}")
    except Exception:
        pass


async def _send_to_users(user_ids: list[int], text_for):
    """مساعد: إرسال رسالة بمنظور كل مستخدم (يقبل دالة أو نصاً ثابتاً)."""
    if not user_ids:
        return
    bot = get_bot()
    with db() as conn:
        rows = conn.execute(
            f"SELECT id, telegram_id FROM users WHERE id IN ({','.join('?' * len(user_ids))})",
            user_ids,
        ).fetchall()
    for uid, tg in rows:
        if not tg:
            continue
        try:
            text = text_for(uid) if callable(text_for) else text_for
            await bot.send_message(tg, text)
        except Exception:
            pass


# ---------- تذكير قبل انتهاء صلاحية المبارزة (الخطة 3.2 / U41) ----------
def _mi(n: int) -> str:
    return {1: "دقيقة", 2: "دقيقتان"}.get(n, "دقائق" if 3 <= n <= 10 else "دقيقة")


def _hr(n: int) -> str:
    return {1: "ساعة", 2: "ساعتان"}.get(n, "ساعات" if 3 <= n <= 10 else "ساعة")


def _due_reminder_targets() -> list[dict]:
    """مبارزات نشطة تدخل آخر 90 دقيقة من صلاحيتها ولم تُذكَّر بعد، مع الطرفين غير المكملين."""
    soon = _iso(_now() + timedelta(minutes=90))
    targets: list[dict] = []
    with db() as conn:
        rows = conn.execute(
            """SELECT id, challenger_id, opponent_id, expires_at FROM duels
               WHERE status='active' AND reminder_sent=0 AND expires_at <= ?""",
            (soon,),
        ).fetchall()
        for r in rows:
            done = lambda uid: conn.execute(  # noqa: E731
                "SELECT id FROM arcade_rounds WHERE duel_id=? AND user_id=? AND final_value IS NOT NULL",
                (r["id"], uid),
            ).fetchone() is not None
            sides = []
            if not done(r["challenger_id"]):
                sides.append(r["challenger_id"])
            if r["opponent_id"] and not done(r["opponent_id"]):
                sides.append(r["opponent_id"])
            if sides:
                targets.append({"duel_id": r["id"], "expires_at": r["expires_at"], "user_ids": sides})
    return targets


async def remind_due_duels():
    """بضعة رسائل فقط: تذكير واحد لكل طرف لم يُنهِ جولته في مبار즈ته — ثم يُعلَّم reminder_sent."""
    try:
        targets = _due_reminder_targets()
        if not targets:
            return
        bot = get_bot()
        with db() as conn:
            for t in targets:
                exp = _now()
                try:
                    left = datetime.fromisoformat(t["expires_at"]) - exp
                    mins = max(5, int(left.total_seconds() // 60))
                except ValueError:
                    mins = 60
                for uid in t["user_ids"]:
                    tg_row = conn.execute("SELECT telegram_id FROM users WHERE id=?", (uid,)).fetchone()
                    if not tg_row or not tg_row[0]:
                        continue
                    try:
                        left_txt = (
                            f"{mins // 60} {_hr(mins // 60)} و{mins % 60} {_mi(mins % 60)}"
                            if mins >= 60 else f"{mins} {_mi(mins)}"
                        )
                        await bot.send_message(
                            tg_row[0],
                            f"⏳ جولتك في المبارزة تنتظرك — باقي {left_txt} تقريباً!\n"
                            "الفرصة الوحيدة للحسم — افتح التطبيق → الأركيد → «مبارزة».",
                        )
                    except Exception:
                        pass
            conn.execute(
                f"UPDATE duels SET reminder_sent=1 WHERE id IN ({','.join('?' * len(targets))})",
                [t["duel_id"] for t in targets],
            )
            conn.commit()
    except Exception:
        pass
