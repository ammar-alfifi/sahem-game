"""
سهم — الإعدادات
"""
import os


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
        return path + "/?v=" + str(_BUILD)
    return None


_BUILD = 4  # ارفع الرقم عند أي تحديث كبير للواجهة — يفرّغ كاش تيليجرام


def get_bot_token() -> str:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN متغير بيئة مطلوب")
    return token


def admin_ids() -> list[int]:
    raw = os.getenv("ADMIN_IDS", "")
    return [int(x) for x in raw.split(",") if x.strip().isdigit()]
