from aiogram import Bot
from typing import List
import logging

logger = logging.getLogger(__name__)

async def get_chat_administrators_ids(bot: Bot, chat_id: int) -> List[int]:
    """Возвращает список ID администраторов чата."""
    try:
        admins = await bot.get_chat_administrators(chat_id)
        return [admin.user.id for admin in admins]
    except Exception as e:
        logger.error(f"Ошибка при получении администраторов чата {chat_id}: {e}")
        return [] 