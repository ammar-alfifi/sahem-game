"""
سهم — الإعدادات
"""
import os

# رقم بناء الواجهة — مصدر واحد. ارفعه عند أي تحديث كبير لتفريغ كاش تيليجرام.
BUILD = "2.4"
# رقم بناء الخادم (يظهر في /health)
APP_BUILD = "2.3-fun-plan"


def get_webapp_url() -> str | None:
    """رابط التطبيق المصغّر — HTTPS (متطلبات تيليجرام).

    الأولوية:
      1. WEBAPP_URL_OVERRIDE — تجاوز صريح (مثال: نطاق Cloudflare Pages)
      2. خادم Render نفسه (RENDER_EXTERNAL_URL/app/) — موثوق وعديم الكاش
      3. WEBAPP_URL — ملاذ أخير (يُستخدم في التشغيل المحلي فقط)
    """
    url = (os.getenv("WEBAPP_URL_OVERRIDE")
           or os.getenv("RENDER_EXTERNAL_URL")
           or os.getenv("WEBAPP_URL"))
    if url:
        if not url.startswith("http"):
            url = "https://" + url
        path = url.rstrip("/")
        if not path.endswith("/app"):
            path += "/app"
        return path + "/?v=" + str(BUILD)
    return None


def get_bot_token() -> str:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN متغير بيئة مطلوب")
    return token


def get_session_secret() -> str | None:
    """سر منفصل لتوقيع توكنات الجلسة (يفضّل ضبطه). يرجع None إن لم يُضبط."""
    return os.getenv("SESSION_SECRET")


def get_webhook_secret() -> str | None:
    return os.getenv("WEBHOOK_SECRET")


def get_admin_token() -> str | None:
    """توكن لوحة التشخيص /diag. /diag مغلق ما لم يُضبط."""
    return os.getenv("ADMIN_TOKEN") or os.getenv("WEBHOOK_SECRET")


def cors_origins() -> list[str]:
    """نطاقات CORS المسموحة من البيئة، وإلا الكل (يُنصح بتشديده)."""
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if not raw:
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


def admin_ids() -> list[int]:
    raw = os.getenv("ADMIN_IDS", "")
    return [int(x) for x in raw.split(",") if x.strip().isdigit()]
