"""
سهم — الإعدادات
"""
import os


def get_webapp_url() -> str | None:
    """رابط التطبيق المصغّر — يجب أن يكون HTTPS (متطلبات تيليجرام)."""
    url = os.getenv("WEBAPP_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if url:
        if not url.startswith("http"):
            url = "https://" + url
        return url.rstrip("/") + "/app/"
    return None


def get_bot_token() -> str:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN متغير بيئة مطلوب")
    return token


def admin_ids() -> list[int]:
    raw = os.getenv("ADMIN_IDS", "")
    return [int(x) for x in raw.split(",") if x.strip().isdigit()]
