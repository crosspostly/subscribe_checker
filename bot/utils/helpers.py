from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import User, Chat, ChatMember
from html import escape
import time
import logging # Добавим для логов кэша
from typing import Optional, Union, Tuple, Any, Dict # Для аннотаций

logger = logging.getLogger(__name__) # Логгер для этого модуля

# Кэш для общей информации о пользователях в чатах и информации о чатах
# Ключ: (type: str, id1: int, id2: Optional[int]) -> (data: Any, timestamp: float)
# type: 'user_in_chat' -> id1=chat_id, id2=user_id, data=ChatMember
# type: 'chat_info'    -> id1=chat_id, id2=None,    data=Chat
_general_info_cache: Dict[Tuple[str, int, Optional[int]], Tuple[Any, float]] = {}
DEFAULT_GENERAL_INFO_TTL = 60  # 1 минута по умолчанию

async def get_cached_general_info(
    bot: Bot, 
    entity_type: str, 
    entity_id: int, 
    context_id: Optional[int] = None, 
    ttl: int = DEFAULT_GENERAL_INFO_TTL
) -> Optional[Union[ChatMember, Chat]]:
    """
    Получает информацию (ChatMember или Chat) с использованием кэша.
    entity_type: 'user_in_chat' или 'chat_info'
    entity_id: user_id (если 'user_in_chat') или chat_id (если 'chat_info')
    context_id: chat_id (только для 'user_in_chat')
    """
    cache_key = (entity_type, entity_id, context_id)
    current_time = time.time()

    if cache_key in _general_info_cache:
        data, timestamp = _general_info_cache[cache_key]
        if current_time - timestamp < ttl:
            logger.debug(f"[CACHE_HIT] General info cache for {cache_key}")
            return data
        else:
            logger.debug(f"[CACHE_STALE] General info cache for {cache_key} is stale.")
            # Удаляем устаревшую запись
            del _general_info_cache[cache_key]

    logger.debug(f"[CACHE_MISS] General info cache for {cache_key}. Fetching from API.")
    try:
        new_data: Optional[Union[ChatMember, Chat]] = None
        if entity_type == 'user_in_chat' and context_id is not None:
            new_data = await bot.get_chat_member(chat_id=context_id, user_id=entity_id)
        elif entity_type == 'chat_info':
            new_data = await bot.get_chat(chat_id=entity_id)
        else:
            logger.warning(f"Unknown entity_type or missing context_id for {cache_key}")
            return None

        if new_data:
            _general_info_cache[cache_key] = (new_data, current_time)
            return new_data
        return None
    except Exception as e:
        logger.error(f"Error fetching general info for {cache_key} from API: {e}")
        return None

async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Проверяет, является ли пользователь админом или создателем чата (с использованием кэша)."""
    try:
        # Используем новую кэширующую функцию
        # TTL можно сделать побольше для статуса админа, т.к. он редко меняется
        member = await get_cached_general_info(bot, 'user_in_chat', user_id, context_id=chat_id, ttl=300) 
        if member:
            return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
        return False # Если не удалось получить member, считаем не админом
    except Exception as e:
        logger.error(f"Error in is_admin for chat {chat_id}, user {user_id}: {e}")
        return False

def get_user_mention_html(user: User) -> str:
    """Возвращает HTML-упоминание пользователя."""
    # user.full_name может содержать символы, которые нужно экранировать
    full_name = escape(user.full_name)
    return f"<a href='tg://user?id={user.id}'>{full_name}</a>" 