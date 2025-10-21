"""
Фильтр для проверки, является ли пользователь админом чата.
"""
from aiogram import F
from aiogram.types import Message
from aiogram.filters import BaseFilter

from bot.utils.helpers import is_admin

class AdminFilter(BaseFilter):
    """Фильтр для проверки админских прав."""
    async def __call__(self, message: Message) -> bool:
        if not message.chat.type in ["group", "supergroup"]:
            return False
        try:
            return await is_admin(message.bot, message.chat.id, message.from_user.id)
        except Exception:
            return False 