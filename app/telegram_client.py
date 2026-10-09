"""
سهم — نسخة Bot مشتركة واحدة لكل العملية، لتفادي إنشاء جلسة شبكة لكل رسالة/تحديث.
"""
from aiogram import Bot

from .config import get_bot_token

_bot: Bot | None = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(get_bot_token())
    return _bot


async def close_bot():
    global _bot
    if _bot is not None:
        try:
            await _bot.session.close()
        finally:
            _bot = None
