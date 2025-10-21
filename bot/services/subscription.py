"""
Сервис для проверки подписки пользователя на каналы, связанные с чатом.
"""
import logging
import asyncio
import json
from typing import List, Tuple, Dict, Any, Optional, Union
import time # Для TTL кэша
import datetime

from aiogram import Bot, types
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Chat
from aiogram.utils.markdown import hlink, hbold, hcode

from ..db.database import DatabaseManager
from ..utils.helpers import get_user_mention_html, get_cached_general_info, is_admin
from bot.keyboards.inline import get_subscription_check_keyboard # Добавляем импорт

logger = logging.getLogger(__name__)

# --- Кэш для информации о чатах --- #
_chat_info_cache = {}
_CACHE_TTL = 300 # Время жизни кэша в секундах (5 минут)

# Кэш для результатов проверки подписки пользователей
_subscription_cache = {}  # {(user_id, channel_id): {"result": bool, "timestamp": time}}
_SUBSCRIPTION_CACHE_TTL = 86400  # 24 часа

# Функция для форматирования ссылок на чаты и пользователей
def get_chat_link_for_md(chat_id, chat_title=None):
    """Создает ссылку на чат в формате Markdown"""
    if not chat_title:
        chat_title = f"Чат {chat_id}"
    # Убираем -100 из ID чата для корректной ссылки
    link_id = str(chat_id).replace('-100', '')
    return f"[{chat_title}](https://t.me/c/{link_id})"

def get_user_link_for_md(user_id, user_name=None):
    """Создает ссылку на пользователя в формате Markdown"""
    if not user_name:
        user_name = f"Пользователь {user_id}"
    return f"[{user_name}](tg://user?id={user_id})"

# Функция форматирования сообщений для лога
def format_sub_log(message_type: str, user_id: Optional[int] = None, 
                  user_name: Optional[str] = None, 
                  chat_id: Optional[int] = None, 
                  chat_title: Optional[str] = None, 
                  extra_info: Optional[str] = None):
    """Форматирует сообщение для логов с красивыми названиями вместо ID"""
    user_part = f"{user_name or 'Unknown'} (ID: {user_id})" if user_id else ""
    chat_part = f"{chat_title or f'Чат {chat_id}'} (ID: {chat_id})" if chat_id else ""
    details = f": {extra_info}" if extra_info else ""
    
    if user_id and chat_id:
        return f"[{message_type}] {user_part} в {chat_part}{details}"
    elif user_id:
        return f"[{message_type}] {user_part}{details}"
    elif chat_id:
        return f"[{message_type}] {chat_part}{details}"
    else:
        return f"[{message_type}]{details}"

# Получение информации о чате с кэшированием
async def get_cached_chat_info(bot: Bot, chat_id: int, force_refresh: bool = False) -> Optional[Any]:
    """Получает информацию о чате с кэшированием."""
    current_time = asyncio.get_event_loop().time()
    
    # Проверяем кэш и его срок годности (30 минут)
    if not force_refresh and chat_id in _chat_info_cache:
        cache_entry = _chat_info_cache[chat_id]
        # Если кэш не старше 30 минут, используем его
        if current_time - cache_entry.get('timestamp', 0) < 1800:  # 30 минут = 1800 секунд
            return cache_entry.get('info')
    
    # Кэш отсутствует или устарел, запрашиваем информацию
    try:
        chat_info_data = await bot.get_chat(chat_id)
        # Обновляем кэш
        _chat_info_cache[chat_id] = {'info': chat_info_data, 'timestamp': current_time}
        return chat_info_data
    except Exception as e:
        logger.error(f"[CHAT_INFO] Не удалось получить информацию о чате {chat_id}: {e}")
        # В случае ошибки обнуляем кэш для этого чата
        _chat_info_cache[chat_id] = {'info': None, 'timestamp': current_time} 
        return None

# Функции для работы с кэшем подписок
def get_cached_subscription(user_id: int, channel_id: int) -> Tuple[bool, bool]:
    """
    Получает результат проверки подписки из кэша
    Возвращает (is_cached, is_member)
    """
    cache_key = (user_id, channel_id)
    current_time = time.time()
    
    if cache_key in _subscription_cache:
        entry = _subscription_cache[cache_key]
        # Проверяем TTL
        if current_time - entry["timestamp"] < _SUBSCRIPTION_CACHE_TTL:
            # Кэш актуален
            return True, entry["result"]
    
    # Кэша нет или он устарел
    return False, False

def set_subscription_cache(user_id: int, channel_id: int, is_member: bool):
    """Сохраняет результат проверки подписки в кэш"""
    cache_key = (user_id, channel_id)
    _subscription_cache[cache_key] = {
        "result": is_member,
        "timestamp": time.time()
    }

def update_subscription_cache(user_id: int, channel_id: int, is_member: bool = True):
    """
    Принудительно обновляет кэш подписки пользователя.
    Используется когда мы точно знаем, что пользователь подписался на канал.
    """
    cache_key = (user_id, channel_id)
    _subscription_cache[cache_key] = {
        "result": is_member,
        "timestamp": time.time()
    }
    logger.info(f"[SUB_CACHE_UPDATE] 🔵 Принудительно обновлен кэш для пользователя {user_id} на канал {channel_id}: подписан={is_member}")

# Очистка старых записей из кэша (запускается периодически)
def clear_expired_subscription_cache():
    """Удаляет устаревшие записи из кэша подписок"""
    current_time = time.time()
    expired_keys = []
    
    for key, entry in _subscription_cache.items():
        if current_time - entry["timestamp"] > _SUBSCRIPTION_CACHE_TTL:
            expired_keys.append(key)
    
    for key in expired_keys:
        del _subscription_cache[key]
    
    if expired_keys:
        logger.debug(f"[SUB_CACHE] Очищено {len(expired_keys)} устаревших записей из кэша подписок")

# ----------------------------------- #

class SubscriptionService:
    def __init__(self, bot: Bot, db_manager: DatabaseManager):
        self.bot = bot
        self.db = db_manager
        # Запускаем периодическую очистку кэша (каждые 6 часов)
        asyncio.create_task(self._schedule_cache_cleanup())
        # Запускаем ежедневное обновление кэша в 5 утра
        asyncio.create_task(self.schedule_daily_cache_update())

    async def _schedule_cache_cleanup(self):
        """Запускает периодическую очистку кэша"""
        while True:
            # await asyncio.sleep(600)  # Старый интервал 10 минут
            await asyncio.sleep(6 * 60 * 60)  # Новый интервал 6 часов
            logger.info("[SUB_CACHE] Запуск периодической очистки устаревшего кэша подписок (старше 24ч).") # Добавил лог
            clear_expired_subscription_cache()
            
    async def schedule_daily_cache_update(self):
        """Запускает ежедневное обновление кэша подписок в 5 утра"""
        while True:
            try:
                # Вычисляем время до 5 утра
                now = datetime.datetime.now()
                target_time = now.replace(hour=5, minute=0, second=0, microsecond=0)
                if now >= target_time:
                    # Если сейчас после 5 утра, планируем на завтра
                    target_time = target_time + datetime.timedelta(days=1)
                
                seconds_to_wait = (target_time - now).total_seconds()
                logger.info(f"[CACHE_SCHEDULER] 📆 Запланировано обновление кэша подписок в {target_time.strftime('%Y-%m-%d %H:%M:%S')} (через {seconds_to_wait/3600:.1f} часов)")
                await asyncio.sleep(seconds_to_wait)
                
                await self.update_all_subscriptions_cache()
                logger.info(f"[CACHE_SCHEDULER] ✅ Выполнено массовое обновление кэша подписок")
            except Exception as e:
                logger.error(f"[CACHE_SCHEDULER] ❌ Ошибка в планировщике: {e}", exc_info=True)
                await asyncio.sleep(3600)

    async def update_all_subscriptions_cache(self):
        """Обновляет кэш подписок для всех активных пользователей и каналов"""
        try:
            active_chats = await self.db.get_active_chats_with_subscription_check()
            total_chats = len(active_chats)
            total_users_processed = 0 
            total_api_checks_made = 0
            
            logger.info(f"[CACHE_UPDATE] 🔄 Начато массовое обновление кэша для {total_chats} чатов")
            
            API_REQUEST_DELAY = 0.1  # Задержка 0.1 сек -> ~10 запросов/сек от этой задачи

            for chat_idx, chat_id in enumerate(active_chats):
                try:
                    linked_channels = await self.db.get_linked_channels_for_chat(chat_id)
                    if not linked_channels:
                        logger.debug(f"[CACHE_UPDATE] Чат {chat_id} ({(chat_idx+1)}/{total_chats}) не имеет связанных каналов, пропускаем")
                        continue
                    
                    active_users = await self.db.get_active_chat_users(chat_id, days=7) # Можно параметризировать `days`
                    if not active_users:
                        logger.debug(f"[CACHE_UPDATE] Чат {chat_id} ({(chat_idx+1)}/{total_chats}) не имеет активных пользователей за последние 7 дней, пропускаем")
                        continue
                
                    logger.info(f"[CACHE_UPDATE] Обрабатываю чат {chat_id} ({(chat_idx+1)}/{total_chats}): {len(active_users)} пользователей × {len(linked_channels)} каналов")
                    
                    for user_idx, user_id in enumerate(active_users):
                        # Явный пропуск служебного аккаунта Telegram
                        if user_id == 777000:
                            logger.info(f"[CACHE_UPDATE] Пропуск служебного аккаунта Telegram (ID: {user_id}) при обновлении кэша подписок для чата {chat_id}.")
                            continue

                        # Попытка определить, является ли user_id ботом, перед циклом по каналам
                        try:
                            user_object = await self.bot.get_chat(user_id) # Один запрос для определения типа
                            if hasattr(user_object, 'is_bot') and user_object.is_bot:
                                logger.info(f"[CACHE_UPDATE] Пропуск бота (ID: {user_id}, Name: {user_object.full_name if hasattr(user_object, 'full_name') else 'N/A'}) при обновлении кэша подписок для чата {chat_id}.")
                                continue
                        except TelegramAPIError as e_get_user:
                            logger.warning(f"[CACHE_UPDATE] Не удалось получить информацию о user_id {user_id} (возможно, не существует или заблокировал бота): {e_get_user}. Пропускаем этого пользователя для чата {chat_id}.")
                            continue
                        except Exception as e_generic_get_user:
                            logger.error(f"[CACHE_UPDATE] Непредвиденная ошибка при получении информации о user_id {user_id}: {e_generic_get_user}. Пропускаем этого пользователя для чата {chat_id}.", exc_info=True)
                            continue

                        total_users_processed +=1 
                        for channel_id in linked_channels: # Убрал channel_idx, он не использовался
                            try:
                                member = await self.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
                                is_member = member.status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
                            
                                _subscription_cache[(user_id, channel_id)] = {
                                    "result": is_member,
                                    "timestamp": time.time()
                                }
                                total_api_checks_made += 1
                                
                                if total_api_checks_made > 0 and total_api_checks_made % 50 == 0:
                                    logger.info(f"[CACHE_UPDATE] Обработано {total_api_checks_made} API-запросов на проверку подписок...")
                                
                                await asyncio.sleep(API_REQUEST_DELAY)
                                    
                            except TelegramAPIError as e_api:
                                if "user not found" in str(e_api).lower():
                                    _subscription_cache[(user_id, channel_id)] = {"result": False, "timestamp": time.time()}
                                    logger.info(f"[CACHE_UPDATE] Пользователь {user_id} не найден в канале {channel_id} (API: {e_api}), кэшировано как False.")
                                elif "chat not found" in str(e_api).lower() or "bot was kicked from the channel" in str(e_api).lower():
                                    logger.warning(f"[CACHE_UPDATE] Канал {channel_id} не найден или бот кикнут (API: {e_api}). Пропускаем дальнейшие проверки для этого канала в этом чате.")
                                    # Можно добавить логику для удаления этого канала из связанных с чатом chat_id в БД
                                    break # Прерываем цикл по каналам для текущего пользователя, если канал недействителен
                                else:
                                    logger.error(f"[CACHE_UPDATE] Ошибка API при обновлении кэша для user={user_id} channel={channel_id}: {e_api}")
                                await asyncio.sleep(API_REQUEST_DELAY) 
                            except Exception as e_inner:
                                logger.error(f"[CACHE_UPDATE] Непредвиденная ошибка при обновлении кэша для user={user_id} channel={channel_id}: {e_inner}", exc_info=True)
                                await asyncio.sleep(API_REQUEST_DELAY)
                        
                        # Если прервали цикл по каналам (например, канал не найден), выходим из цикла по пользователям для этого чата
                        if 'e_api' in locals() and ("chat not found" in str(e_api).lower() or "bot was kicked from the channel" in str(e_api).lower()): # pyright: ignore [reportUnboundVariable]
                           break

                        if (user_idx + 1) % 20 == 0: # Лог после каждых 20 пользователей в чате
                             logger.info(f"[CACHE_UPDATE] В чате {chat_id} обработано {(user_idx + 1)}/{len(active_users)} пользователей.")
                             await asyncio.sleep(0.5) # Дополнительная пауза после обработки пачки пользователей
                except Exception as e_outer_loop:
                    logger.error(f"[CACHE_UPDATE] Ошибка при обработке чата {chat_id} ({(chat_idx+1)}/{total_chats}): {e_outer_loop}", exc_info=True)
                    await asyncio.sleep(1) # Пауза при ошибке на уровне чата

            logger.info(f"[CACHE_UPDATE] ✅ Завершено обновление кэша: обработано чатов (попыток) - {total_chats}, уникальных пользователей (в циклах) - {total_users_processed}, API-запросов сделано - {total_api_checks_made}.")
            
        except Exception as e:
            logger.error(f"[CACHE_UPDATE] ❌ Критическая ошибка при массовом обновлении кэша: {e}", exc_info=True)
            
    async def check_single_channel(self, user_id: int, channel_id: int, user_name: str = None) -> Tuple[int, Any]:
        """
        Проверяет подписку пользователя на ОДИН канал.
        Возвращает кортеж: (channel_id, status) где status это ChatMemberStatus или None/False при ошибке.
        Логирует результат проверки.
        """
        user_name_for_log = user_name if user_name else f"User_{user_id}"
        channel_name_for_log = f"Channel_{channel_id}" # Попробуем получить позже, если есть
        
        # Попытка получить название канала из кэша или API (для логов)
        try:
            # Используем новый get_cached_chat_info
            channel_info = await get_cached_chat_info(self.bot, channel_id)
            if channel_info and channel_info.title:
                channel_name_for_log = channel_info.title
        except Exception as e_info:
            logger.debug(f"[SUB_CHECK_SINGLE_INFO_FAIL] Не удалось получить название для канала {channel_id}: {e_info}")


        logger.info(f"[SUB_CHECK_SINGLE_INIT] Проверка подписки: {user_name_for_log} на {channel_name_for_log} (ID: {channel_id})")

        # 1. Проверка кэша (ОТКЛЮЧЕНО НА ВРЕМЯ ОТЛАДКИ)
        # is_cached, cached_result = get_cached_subscription(user_id, channel_id)
        # if is_cached:
        #     logger.info(f"[SUB_CHECK_SINGLE_CACHE] {user_name_for_log} на {channel_name_for_log} (ID: {channel_id}): результат из кэша: {'подписан' if cached_result else 'НЕ подписан'}")
        #     return channel_id, ChatMemberStatus.MEMBER if cached_result else ChatMemberStatus.LEFT

        # 2. Запрос к Telegram API
        try:
            logger.debug(f"[SUB_CHECK_SINGLE_API_CALL] {user_name_for_log} на {channel_name_for_log} (ID: {channel_id}): запрос к Telegram API...")
            # Добавляем timeout к запросу API
            member_status = await self.bot.get_chat_member(chat_id=channel_id, user_id=user_id) # request_timeout=10 можно добавить, если версия aiogram позволяет
            
            is_member = member_status.status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
            
            # Сохраняем результат в кэш (даже если кэш на чтение отключен, запись оставим)
            set_subscription_cache(user_id, channel_id, is_member)
            
            logger.info(f"[SUB_CHECK_SINGLE_API_RESULT] {user_name_for_log} на {channel_name_for_log} (ID: {channel_id}): статус от API: {member_status.status}, результат: {'подписан' if is_member else 'НЕ подписан'}")
            return channel_id, member_status.status

        except TelegramAPIError as e:
            if "user not found" in str(e).lower():
                logger.warning(f"[SUB_CHECK_SINGLE_API_ERROR] {user_name_for_log} на {channel_name_for_log} (ID: {channel_id}): пользователь не найден в канале (API: {e}). Считаем НЕ подписанным.")
                set_subscription_cache(user_id, channel_id, False)
                return channel_id, ChatMemberStatus.LEFT
            elif "chat not found" in str(e).lower():
                logger.error(f"[SUB_CHECK_SINGLE_API_ERROR] {user_name_for_log} на {channel_name_for_log} (ID: {channel_id}): чат/канал не найден (API: {e}).")
                return channel_id, None 
            elif "bot was kicked from the channel" in str(e).lower() or "bot is not a member of the channel" in str(e).lower():
                logger.error(f"[SUB_CHECK_SINGLE_API_ERROR] {user_name_for_log} на {channel_name_for_log} (ID: {channel_id}): бот не является участником канала (API: {e}).")
                return channel_id, None
            elif isinstance(e, TelegramBadRequest) and "chat unavailable" in str(e).lower(): # TelegramBadRequest - более специфичный тип ошибки
                logger.warning(f"[SUB_CHECK_SINGLE_API_ERROR_UNAVAILABLE] {user_name_for_log} на {channel_name_for_log} (ID: {channel_id}): канал временно недоступен (API: {e}). Считаем НЕ подписанным на этот раз.")
                # Не кэшируем этот результат как False, так как проблема может быть временной
                return channel_id, ChatMemberStatus.LEFT 
            else:
                logger.error(f"[SUB_CHECK_SINGLE_API_ERROR_OTHER] {user_name_for_log} на {channel_name_for_log} (ID: {channel_id}): другая ошибка Telegram API: {e}", exc_info=True)
                set_subscription_cache(user_id, channel_id, False) 
                return channel_id, ChatMemberStatus.LEFT
        except Exception as e:
            logger.error(f"[SUB_CHECK_SINGLE_UNEXPECTED_ERROR] {user_name_for_log} на {channel_name_for_log} (ID: {channel_id}): критическая ошибка при проверке: {e}", exc_info=True)
            return channel_id, None

    async def check_subscription(self, user_id: int, chat_id: int, force_check: bool = False) -> Tuple[bool, List[int]]: # Добавлен force_check
        """
        Проверяет подписку пользователя на ВСЕ каналы, связанные с указанным чатом.
        force_check: Если True, подразумевается, что check_single_channel будет делать реальный API запрос (кэш чтения в нём отключен).
        Возвращает кортеж: (is_fully_subscribed, list_of_unsubscribed_channel_ids)
        """
        user_info = await get_cached_general_info(self.bot, user_id, "user")
        user_name_for_log = user_info.get('full_name', f"User_{user_id}") if user_info else f"User_{user_id}"
        
        chat_info_db = await self.db.get_chat_settings(chat_id)
        chat_title_for_log = chat_info_db.get('chat_title', f"Chat_{chat_id}") if chat_info_db else f"Chat_{chat_id}"

        log_prefix = f"[SUB_CHECK_OVERALL{' FORCE' if force_check else ''}]" # Используем force_check для лога
        logger.info(f"{log_prefix} Инициация полной проверки подписки для {user_name_for_log} (ID: {user_id}) в {chat_title_for_log} (ID: {chat_id})")

        linked_channel_ids = await self.db.get_linked_channels_for_chat(chat_id)
        if not linked_channel_ids:
            logger.info(f"{log_prefix} {user_name_for_log} в {chat_title_for_log}: нет каналов для проверки. Считаем подписанным.")
            return True, []
                                    
        logger.info(f"{log_prefix} {user_name_for_log} в {chat_title_for_log}: каналы для проверки: {linked_channel_ids}")

        unsubscribed_channel_ids = []
        
        # Кэш чтения в check_single_channel сейчас закомментирован для отладки.
        # Поэтому каждый вызов будет делать API запрос.
        tasks = [self.check_single_channel(user_id, ch_id, user_name=user_name_for_log) for ch_id in linked_channel_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result_item in enumerate(results):
            current_channel_id = linked_channel_ids[i] 

            if isinstance(result_item, Exception):
                logger.error(f"{log_prefix}_GATHER_ERROR {user_name_for_log} в {chat_title_for_log}: ошибка при проверке канала ID {current_channel_id}: {result_item}")
                unsubscribed_channel_ids.append(current_channel_id)
                continue

            returned_channel_id, status = result_item 
            
            if returned_channel_id != current_channel_id:
                 logger.warning(f"{log_prefix}_GATHER_MISMATCH {user_name_for_log} в {chat_title_for_log}: несоответствие ID канала. Ожидался {current_channel_id}, получен {returned_channel_id}. Используем полученный.")
            
            target_channel_id_for_log = returned_channel_id
            
            channel_info_for_log = await get_cached_chat_info(self.bot, target_channel_id_for_log)
            channel_title_for_log_item = channel_info_for_log.title if channel_info_for_log and channel_info_for_log.title else f"Канал ID {target_channel_id_for_log}"

            if status is None: 
                logger.warning(f"{log_prefix}_CHANNEL_ERROR {user_name_for_log} в {chat_title_for_log}: НЕ УДАЛОСЬ ПРОВЕРИТЬ статус для {channel_title_for_log_item} (ID: {target_channel_id_for_log}). Считаем НЕ подписанным.")
                unsubscribed_channel_ids.append(target_channel_id_for_log)
            elif status not in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
                logger.info(f"{log_prefix}_NOT_SUBSCRIBED {user_name_for_log} в {chat_title_for_log}: НЕ подписан на {channel_title_for_log_item} (ID: {target_channel_id_for_log}). Статус от API: {status}")
                unsubscribed_channel_ids.append(target_channel_id_for_log)
            else:
                logger.info(f"{log_prefix}_SUBSCRIBED {user_name_for_log} в {chat_title_for_log}: ПОДПИСАН на {channel_title_for_log_item} (ID: {target_channel_id_for_log}). Статус от API: {status}")

        if not unsubscribed_channel_ids:
            logger.info(f"{log_prefix}_RESULT_SUCCESS {user_name_for_log} (ID: {user_id}) в {chat_title_for_log} (ID: {chat_id}): ПОЛНОСТЬЮ ПОДПИСАН на все {len(linked_channel_ids)} каналов.")
            return True, []
        else:
            logger.info(f"{log_prefix}_RESULT_FAIL {user_name_for_log} (ID: {user_id}) в {chat_title_for_log} (ID: {chat_id}): НЕ ПОДПИСАН на {len(unsubscribed_channel_ids)} из {len(linked_channel_ids)} каналов. ID непройденных: {unsubscribed_channel_ids}")
            return False, unsubscribed_channel_ids

    async def handle_subscription_check_callback(self, callback_query: CallbackQuery):
        """Обрабатывает нажатие кнопки 'Я подписался / Проверить подписку'."""
        await callback_query.answer("⏳ Проверяем вашу подписку...", cache_time=2) 
        
        user = callback_query.from_user
        if not callback_query.message or not callback_query.message.chat:
            logger.error(f"[SUB_CALLBACK_ERR_NO_CHAT] Не удалось определить чат из callback_query для пользователя {user.id}")
            await callback_query.answer("⚠️ Произошла ошибка. Не удалось определить чат. Попробуйте позже.", show_alert=True)
            return

        chat_id = callback_query.message.chat.id 
        chat_full_name = callback_query.message.chat.full_name if callback_query.message.chat.full_name else f"Чат ID {chat_id}"
        message_id_of_button = callback_query.message.message_id # Сохраняем ID сообщения с кнопкой

        user_mention = get_user_mention_html(user)
        logger.info(f"[SUB_CALLBACK_INIT] {user_mention} (ID: {user.id}) нажал кнопку проверки подписки в чате {chat_full_name} (ID: {chat_id}) для сообщения {message_id_of_button}")

        # Принудительная проверка без кэша (force_check=True)
        is_subscribed, unsubscribed_channels = await self.check_subscription(user.id, chat_id, force_check=True)

        if is_subscribed:
            logger.info(f"[SUB_CALLBACK_SUCCESS] {user_mention} (ID: {user.id}) успешно прошел проверку подписки в чате {chat_id}.")
            
            try:
                # Удаляем исходное сообщение с кнопкой
                await self.bot.delete_message(chat_id=chat_id, message_id=message_id_of_button)
                logger.info(f"[SUB_CALLBACK_CLEANUP] Сообщение {message_id_of_button} с кнопкой проверки удалено для {user_mention} в чате {chat_id}.")
            except TelegramAPIError as e_del_msg:
                logger.warning(f"[SUB_CALLBACK_CLEANUP_FAIL] Не удалось удалить сообщение {message_id_of_button} с кнопкой для {user_mention} в чате {chat_id}: {e_del_msg}")

            # Отправка тихого временного сообщения в групповой чат
            group_success_message_text = f"🎉 {user_mention}, вы успешно подписались и теперь можете писать сообщения!"
            try:
                sent_group_msg = await self.bot.send_message(
                    chat_id=chat_id, 
                    text=group_success_message_text, 
                    parse_mode="HTML",
                    disable_notification=True 
                )
                logger.info(f"[SUB_CALLBACK_GROUP_MSG_SENT] Тихое сообщение об успехе отправлено в чат {chat_id} для {user_mention}, ID: {sent_group_msg.message_id}.")
                asyncio.create_task(self._delete_message_after_delay(chat_id, sent_group_msg.message_id, 3)) # Удаление через 3 секунды
            except Exception as e_group_msg:
                logger.error(f"[SUB_CALLBACK_GROUP_MSG_FAIL] Не удалось отправить тихое сообщение в чат {chat_id} для {user_mention}: {e_group_msg}", exc_info=True)


            await self.db.reset_sub_fail_count(user_id=user.id, chat_id=chat_id)
            logger.info(f"[SUB_CALLBACK_RESET_FAIL_COUNT] Счетчик неудач подписки сброшен для {user_mention} (ID: {user.id}) в чате {chat_id}.")
            
            await self.unban_user_for_subscription(user_id=user.id, chat_id=chat_id)
            logger.info(f"[SUB_CALLBACK_UNBAN_TRIGGERED] Вызван unban_user_for_subscription для {user_mention} (ID: {user.id}) в чате {chat_id}.")

        else: # Если подписки нет
            logger.info(f"[SUB_CALLBACK_FAIL] {user_mention} (ID: {user.id}) НЕ прошел проверку подписки в чате {chat_id}. Незавершенные каналы: {unsubscribed_channels}")
            
            channels_to_subscribe_info = await self.db.get_channels_info_by_ids(unsubscribed_channels)
            
            alert_text_parts = []
            channels_list_str_for_edit_msg = [] # Для текста редактируемого сообщения

            if channels_to_subscribe_info:
                alert_text_parts.append(f"🚫 {user_mention}, вы все еще не подписаны на:")
                channels_list_str_for_edit_msg.append(f"{user_mention}, чтобы писать сообщения, пожалуйста, подпишитесь на:")

                for ch_info in channels_to_subscribe_info:
                    title = ch_info.get('channel_title', f'Канал ID {ch_info["channel_id"]}')
                    link = ch_info.get('channel_link') 
                    
                    # Для сообщения используем форматирование с ссылкой/жирным названием
                    channel_line_for_msg = f"🔗 {hlink(title, link)}" if link else f"📛 {hbold(title)}"
                    
                    # Для алерта - просто название
                    alert_text_parts.append(f"  • {title}") 
                    channels_list_str_for_edit_msg.append(f"  • {channel_line_for_msg}") # Используем форматированную строку

                alert_text_parts.append("\n\nПодпишитесь и попробуйте снова.") # Двойной \n для алерта
                channels_list_str_for_edit_msg.append("") # Пустая строка для отступа
                channels_list_str_for_edit_msg.append("После подписки нажмите кнопку ниже.")
            
            else: # Если вдруг нет информации о каналах (маловероятно, но на всякий случай)
                alert_text_parts.append(f"🚫 {user_mention}, не удалось подтвердить вашу подписку. Убедитесь, что подписаны на все каналы, и попробуйте снова.")
                channels_list_str_for_edit_msg.append(f"{user_mention}, не удалось подтвердить подписку. Убедитесь, что подписаны на нужные каналы. Кнопка ниже. Сообщение удалится через 15 сек.")

            final_alert_text = "\n".join(alert_text_parts) # Собираем текст для алерта
            final_edit_message_text = "\n".join(channels_list_str_for_edit_msg) # Собираем текст для редактирования

            # Получаем актуальную клавиатуру для сообщения
            # detailed_missing_channels_for_keyboard теперь нужно формировать здесь заново
            # на основе unsubscribed_channels, чтобы кнопка была актуальной
            detailed_keyboard_channels_info = []
            if unsubscribed_channels:
                # Попытка получить актуальные данные для клавиатуры
                # Это дублирует логику из send_subscription_warning, но тут это нужно для кнопки
                # Можно вынести в отдельный хелпер, если будет использоваться еще где-то
                for ch_id_loop in unsubscribed_channels:
                    ch_title_kb = f"Канал {ch_id_loop}"
                    ch_link_kb = None
                    try:
                        ch_obj_kb = await self.bot.get_chat(ch_id_loop)
                        ch_title_kb = ch_obj_kb.title or ch_title_kb
                        ch_username_kb = getattr(ch_obj_kb, 'username', None)
                        ch_invite_link_kb = getattr(ch_obj_kb, 'invite_link', None)
                        if ch_username_kb: ch_link_kb = f"https://t.me/{ch_username_kb}"
                        elif ch_invite_link_kb: ch_link_kb = ch_invite_link_kb
                    except Exception: pass # Игнорируем ошибки, если не удалось получить инфо
                    detailed_keyboard_channels_info.append({
                        'id': ch_id_loop, 
                        'title': ch_title_kb, 
                        'invite_link': ch_link_kb,
                        'username': ch_link_kb.split('/')[-1] if ch_link_kb and "t.me/" in ch_link_kb else None
                    })
            
            reply_markup_for_edit = get_subscription_check_keyboard(user.id, detailed_keyboard_channels_info if detailed_keyboard_channels_info else [])


            try: # Редактируем исходное сообщение с кнопкой
                await self.bot.edit_message_text(
                    text=final_edit_message_text,
                    chat_id=chat_id,
                    message_id=message_id_of_button,
                    reply_markup=reply_markup_for_edit, # Оставляем кнопку
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                logger.info(f"[SUB_CALLBACK_EDITED] Сообщение {message_id_of_button} отредактировано для {user_mention} в чате {chat_id} с информацией о недостающих подписках.")
                # Планируем удаление этого отредактированного сообщения через 15 секунд
                asyncio.create_task(self._delete_message_after_delay(chat_id, message_id_of_button, 15))
            except TelegramAPIError as e_edit:
                logger.error(f"[SUB_CALLBACK_EDIT_FAIL] Не удалось отредактировать сообщение {message_id_of_button} для {user_mention} в чате {chat_id}: {e_edit}")
                # Если редактирование не удалось, возможно, стоит просто удалить старое и отправить новое,
                # но пока ограничимся логгированием и показом алерта.

            try: # Показываем алерт пользователю
                await callback_query.answer(final_alert_text, show_alert=True, cache_time=5) # cache_time можно убрать или оставить
                logger.info(f"[SUB_CALLBACK_ALERT_SENT] Alert о необходимости подписки отправлен {user_mention} в чате {chat_id}.")
            except TelegramAPIError as e_alert: 
                logger.error(f"[SUB_CALLBACK_ALERT_FAIL] Не удалось отправить alert {user_mention} в чате {chat_id}: {e_alert}")
                # Если алерт не прошел, пользователь увидит отредактированное сообщение (если оно отредактировалось)

    async def send_subscription_warning(
        self,
        chat_id: int,
        user: types.User,
        missing_channel_ids: List[int],
        user_initiated: bool = False # Флаг, что это инициировано пользователем (кнопкой)
    ):
        """Отправляет предупреждение о необходимости подписки с HTML и кнопкой."""
        user_mention = get_user_mention_html(user)
        # channels_info = await self.db.get_channels_info_by_ids(missing_channel_ids) # Больше не используем старый метод БД для названий/ссылок

        message_text_parts = []
        message_text_parts.append(
            f"{user_mention}, чтобы писать сообщения в этом чате, пожалуйста, подпишитесь на:"
        )

        detailed_missing_channels_for_keyboard = [] # Для кнопки "Я подписался"

        if not missing_channel_ids:
            logger.warning(format_sub_log("SUB_WARN_NO_CHANNELS", user_id=user.id, chat_id=chat_id,
                                           extra_info="Вызван send_subscription_warning, но список missing_channel_ids пуст."))
            # Можно отправить общее сообщение или ничего не делать
            return None

        for channel_id_loop in missing_channel_ids:
            channel_title_display = f"Канал ID {channel_id_loop}" # Заголовок по умолчанию
            channel_link_display = None # Ссылка по умолчанию

            try:
                # Получаем актуальную информацию о канале
                # Используем кэшированную функцию get_cached_chat_info, если она доступна и подходит
                # или напрямую self.bot.get_chat()
                # Для простоты примера, предположим, что get_cached_chat_info подходит
                # или делаем прямой вызов:
                channel_obj = await self.bot.get_chat(channel_id_loop)
                
                current_title = channel_obj.title
                current_username = channel_obj.username if hasattr(channel_obj, 'username') else None
                current_invite_link = channel_obj.invite_link if hasattr(channel_obj, 'invite_link') else None

                if current_title:
                    channel_title_display = current_title
                
                if current_username:
                    channel_link_display = f"https://t.me/{current_username}"
                elif current_invite_link:
                    channel_link_display = current_invite_link
                
                logger.debug(format_sub_log("SUB_WARN_CH_INFO", user_id=user.id, chat_id=chat_id,
                                           extra_info=f"Канал {channel_id_loop}: title='{current_title}', username='{current_username}', invite_link='{current_invite_link}', final_link='{channel_link_display}'"))

            except TelegramAPIError as e_get_chat:
                logger.error(format_sub_log("SUB_WARN_CH_FETCH_FAIL", user_id=user.id, chat_id=chat_id,
                                            extra_info=f"Не удалось получить инфо для канала {channel_id_loop}: {e_get_chat}"))
                # Оставляем title/link по умолчанию
            except Exception as e_unexpected_fetch:
                logger.error(format_sub_log("SUB_WARN_CH_FETCH_UNEXPECTED", user_id=user.id, chat_id=chat_id,
                                            extra_info=f"Неожиданная ошибка при получении инфо для канала {channel_id_loop}: {e_unexpected_fetch}"))


            if channel_link_display:
                message_text_parts.append(f"  • {hlink(channel_title_display, channel_link_display)}")
            else:
                message_text_parts.append(f"  • {hbold(channel_title_display)}")

            detailed_missing_channels_for_keyboard.append({
                'id': channel_id_loop,
                'title': channel_title_display,
                'invite_link': channel_link_display, 
                'username': channel_link_display.split('/')[-1] if channel_link_display and "t.me/" in channel_link_display else None
            })

        message_text_parts.append("") # Пустая строка для отступа
        message_text_parts.append("После подписки нажмите кнопку ниже.")

        # Собираем HTML текст
        # Первая строка: "Pasha, чтобы писать..."
        # Далее список каналов, каждый на новой строке
        # Затем пустая строка (визуальный отступ)
        # Затем "После подписки нажмите кнопку ниже."
        
        # Начальная часть сообщения
        final_text_parts = [message_text_parts[0]] 

        # Добавляем каналы (элементы с индексами от 1 до предпоследнего элемента оригинального message_text_parts)
        # message_text_parts изначально: [intro, ch1, ch2, ..., "", "После подписки..."]
        # Каналы это message_text_parts[1:-2]
        if len(message_text_parts) > 2: # Если есть хотя бы один канал + intro + два последних элемента
            final_text_parts.extend(message_text_parts[1:-2])
        
        # Добавляем заключительную фразу (последний элемент оригинального message_text_parts)
        final_text_parts.append(message_text_parts[-1])

        final_text_html = "\n".join(final_text_parts) # Используем \n вместо <br>

        reply_markup = get_subscription_check_keyboard(user.id, detailed_missing_channels_for_keyboard)

        try:
            sent_msg = await self.bot.send_message(
                chat_id=chat_id,
                text=final_text_html,
                reply_markup=reply_markup,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            logger.info(format_sub_log("SUB_WARN_SENT", user_id=user.id, chat_id=chat_id, 
                                   extra_info=f"Предупреждение о подписке отправлено, ID: {sent_msg.message_id}"))
            # Удаляем это сообщение через 120 секунд, если оно не от кнопки
            if not user_initiated: 
                asyncio.create_task(self._delete_message_after_delay(chat_id, sent_msg.message_id, 15))
            return sent_msg
        except TelegramAPIError as e:
            logger.error(format_sub_log("SUB_WARN_FAIL", user_id=user.id, chat_id=chat_id, extra_info=f"Ошибка отправки предупреждения о подписке: {e}"))
            return None

    async def handle_subscription_failure(
        self,
        original_message: types.Message, # Сообщение пользователя, которое вызвало проверку
        user: types.User, 
        chat: types.Chat, 
        unsubscribed_channel_ids: List[int],
        current_sub_fail_count: int, # Принимаем ТЕКУЩИЙ (не увеличенный) счетчик
        max_fails_allowed: int, # Сколько всего попыток дается (например, 3)
        mute_duration_minutes: int
    ):
        """Обрабатывает неудачную проверку подписки согласно новой логике."""
        user_mention = get_user_mention_html(user)

        # Увеличиваем счетчик и обновляем в БД
        new_sub_fail_count = current_sub_fail_count + 1
        try:
            await self.db.update_sub_fail_count(user.id, chat.id, new_sub_fail_count)
            logger.info(format_sub_log("SUB_FAIL_COUNT_UPDATED", user_id=user.id, chat_id=chat.id,
                                   extra_info=f"Счетчик неудач обновлен на {new_sub_fail_count} (был {current_sub_fail_count})."))
        except Exception as e_db_update_fail:
            logger.error(format_sub_log("SUB_FAIL_COUNT_DB_ERROR", user_id=user.id, chat_id=chat.id,
                                       extra_info=f"Ошибка при обновлении счетчика неудач на {new_sub_fail_count} в БД: {e_db_update_fail}"))
            # Если не удалось обновить счетчик, возможно, стоит прервать дальнейшие действия или использовать new_sub_fail_count "как есть"
            # Пока продолжаем, но это потенциальная проблема
            pass


        # Попытка 1 (new_sub_fail_count = 1)
        if new_sub_fail_count == 1:
            logger.info(format_sub_log("SUB_FAIL_ATTEMPT_1", user_id=user.id, chat_id=chat.id, 
                                   extra_info=f"Первая неудачная попытка. Отправка предупреждения."))
            # Удаляем оригинальное сообщение пользователя
            try:
                await original_message.delete()
            except TelegramAPIError:
                logger.warning(format_sub_log("SUB_FAIL_MSG_DEL_ERR", user_id=user.id, chat_id=chat.id, 
                                       extra_info="Не удалось удалить оригинальное сообщение при первой неудаче."))
            # Отправляем предупреждение
            await self.send_subscription_warning(chat.id, user, unsubscribed_channel_ids)
            return # Завершаем обработку для этой попытки

        # Попытки между первой и последней (1 < new_sub_fail_count < max_fails_allowed)
        elif 1 < new_sub_fail_count < max_fails_allowed:
            logger.info(format_sub_log("SUB_FAIL_ATTEMPT_INTERMEDIATE", user_id=user.id, chat_id=chat.id, 
                                   extra_info=f"Промежуточная неудачная попытка ({new_sub_fail_count}/{max_fails_allowed}). Удаление сообщения."))
            # Просто удаляем сообщение пользователя
            try:
                await original_message.delete()
            except TelegramAPIError:
                logger.warning(format_sub_log("SUB_FAIL_MSG_DEL_ERR", user_id=user.id, chat_id=chat.id, 
                                       extra_info="Не удалось удалить оригинальное сообщение при промежуточной неудаче."))
            return # Завершаем обработку

        # Последняя разрешенная попытка (new_sub_fail_count == max_fails_allowed)
        elif new_sub_fail_count >= max_fails_allowed: # Используем >= для надежности
            logger.info(format_sub_log("SUB_FAIL_ATTEMPT_LAST", user_id=user.id, chat_id=chat.id, 
                                   extra_info=f"Последняя разрешенная попытка ({new_sub_fail_count}/{max_fails_allowed}). Установка мута."))
            # Удаляем оригинальное сообщение пользователя
            try:
                await original_message.delete()
            except TelegramAPIError:
                logger.warning(format_sub_log("SUB_FAIL_MSG_DEL_ERR", user_id=user.id, chat_id=chat.id, 
                                       extra_info="Не удалось удалить оригинальное сообщение при последней неудаче."))

            # Накладываем мут
            mute_until_ts = int(time.time()) + (mute_duration_minutes * 60)
            try:
                await self.bot.restrict_chat_member(
                    chat_id=chat.id,
                    user_id=user.id,
                    permissions=types.ChatPermissions(can_send_messages=False),
                    until_date=datetime.datetime.fromtimestamp(mute_until_ts)
                )
                logger.info(format_sub_log("MUTE_APPLIED", user_id=user.id, chat_id=chat.id,
                                       extra_info=f"Пользователь замучен до {datetime.datetime.fromtimestamp(mute_until_ts)}."))
                
                await self.db.update_user_ban_status(
                    user_id=user.id,
                    chat_id=chat.id,
                    ban_until_ts=mute_until_ts
                )
                await self.db.reset_sub_fail_count(user.id, chat.id)
                logger.info(format_sub_log("SUB_FAIL_COUNT_RESET", user_id=user.id, chat_id=chat.id,
                                       extra_info="Счетчик неудач сброшен после мута."))

                mute_message_text_parts_html = []
                mute_message_text_parts_html.append(
                    f"{user_mention}, вы были временно ограничены в отправке сообщений на 30 минут, "
                    f"так как не подписались на обязательные каналы."
                )

                if unsubscribed_channel_ids:
                    mute_message_text_parts_html.append("Необходимо подписаться на:")
                    for channel_id_loop in unsubscribed_channel_ids:
                        channel_title_display = f"Канал ID {channel_id_loop}"
                        channel_link_display = None
                        try:
                            channel_obj = await self.bot.get_chat(channel_id_loop)
                            current_title = channel_obj.title
                            current_username = channel_obj.username if hasattr(channel_obj, 'username') else None
                            current_invite_link = channel_obj.invite_link if hasattr(channel_obj, 'invite_link') else None
                            if current_title:
                                channel_title_display = current_title
                            if current_username:
                                channel_link_display = f"https://t.me/{current_username}"
                        except TelegramAPIError as e_get_chat_mute:
                            logger.warning(format_sub_log("MUTE_MSG_CH_FETCH_FAIL", user_id=user.id, chat_id=chat.id,
                                                        extra_info=f"Не удалось получить инфо для канала {channel_id_loop} при формировании сообщения о муте: {e_get_chat_mute}"))
                        except Exception as e_generic_fetch:
                            logger.error(format_sub_log("MUTE_MSG_CH_FETCH_UNEXPECTED", user_id=user.id, chat_id=chat.id,
                                                       extra_info=f"Неожиданная ошибка при получении инфо для канала {channel_id_loop} для сообщения о муте: {e_generic_fetch}"), exc_info=True)
                        
                        if channel_link_display:
                            mute_message_text_parts_html.append(f"  • {hlink(channel_title_display, channel_link_display)}")
                        else:
                            mute_message_text_parts_html.append(f"  • {hbold(channel_title_display)}")
                
                mute_message_text = "\n".join(mute_message_text_parts_html) # Используем \n вместо <br>
                
                try:
                    sent_mute_msg = await self.bot.send_message(chat.id, mute_message_text, parse_mode="HTML", disable_web_page_preview=True)
                    asyncio.create_task(self._delete_message_after_delay(chat.id, sent_mute_msg.message_id, 10))
                except Exception as e_send_mute_msg:
                    logger.error(format_sub_log("MUTE_MSG_SEND_FAIL", user_id=user.id, chat_id=chat.id,
                                               extra_info=f"Не удалось отправить сообщение о муте: {e_send_mute_msg}"))

            except TelegramAPIError as e:
                logger.error(format_sub_log("MUTE_FAIL_API", user_id=user.id, chat_id=chat.id, extra_info=f"Ошибка API при установке мута: {e}"))
            except Exception as e_db_ban: # Этот except должен быть на том же уровне, что и предыдущий TelegramAPIError
                 logger.error(format_sub_log("MUTE_DB_UPDATE_FAIL", user_id=user.id, chat_id=chat.id, extra_info=f"Ошибка при обновлении статуса бана в БД: {e_db_ban}"))
            return # Завершаем обработку

    async def _delete_message_after_delay(self, chat_id: int, message_id: int, delay: int):
        """Deletes a message after a specified delay."""
        logger.info(f"[DELETE_TASK_STARTED] Задача на удаление сообщения {message_id} в чате {chat_id} через {delay} сек. ЗАПУЩЕНА.")
        await asyncio.sleep(delay)
        logger.info(f"[DELETE_TASK_AWOKE] Задача на удаление сообщения {message_id} в чате {chat_id}. ПРОСНУЛАСЬ после {delay} сек. Попытка удаления...")
        try:
            await self.bot.delete_message(chat_id, message_id)
            # Используем format_sub_log, если он доступен в этом контексте, или просто logger.info
            # logger.info(format_sub_log("SUB_DEL_SUCCESS", chat_id=chat_id, extra_info=f"Сообщение {message_id} успешно удалено."))
            logger.info(f"[SUB_DEL_SUCCESS] Чат {chat_id}: Сообщение {message_id} успешно удалено.") # Упрощенный лог для надежности
        except TelegramAPIError as e:
            # logger.warning(format_sub_log("SUB_DEL_FAIL", chat_id=chat_id, extra_info=f"Не удалось удалить сообщение {message_id}: {e}"))
            logger.warning(f"[SUB_DEL_FAIL] Чат {chat_id}: Не удалось удалить сообщение {message_id}: {e}") # Упрощенный лог
        except Exception as e_unexp:
            logger.error(f"[DELETE_TASK_UNEXPECTED_ERROR] Неожиданная ошибка в задаче удаления сообщения {message_id} в чате {chat_id}: {e_unexp}", exc_info=True)

    async def unban_user_for_subscription(self, user_id: int, chat_id: int):
        """Снимает ограничения с пользователя и сбрасывает его статус бана/счетчик неудач в БД."""
        try:
            await self.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=types.ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_change_info=False, # Обычно не разрешаем
                    can_invite_users=True,
                    can_pin_messages=False # Обычно не разрешаем
                ),
                until_date=0  # Снимаем ограничения немедленно
            )
            logger.info(format_sub_log("UNBAN_SUCCESS", user_id=user_id, chat_id=chat_id, extra_info="Ограничения сняты после подписки."))
        except TelegramAPIError as e:
            logger.error(format_sub_log("UNBAN_FAIL_API", user_id=user_id, chat_id=chat_id, extra_info=f"Ошибка API при снятии ограничений: {e}"))
        
        try:
            await self.db.clear_user_ban_status(user_id, chat_id)
            await self.db.reset_sub_fail_count(user_id, chat_id)
            logger.info(format_sub_log("UNBAN_DB_SUCCESS", user_id=user_id, chat_id=chat_id, extra_info="Статус бана и счетчик неудач сброшены в БД."))
        except Exception as e:
            logger.error(format_sub_log("UNBAN_DB_FAIL", user_id=user_id, chat_id=chat_id, extra_info=f"Ошибка при сбросе статуса бана/счетчика в БД: {e}"))

    # Старый метод handle_unsubscribed_user, оставляем его закомментированным или удаляем позже
    # async def handle_unsubscribed_user(
    #     self, 
    #     message: types.Message, 
    #     user: types.User, 
    #     chat: types.Chat, 
    #     unsubscribed_channel_ids: List[int],
    #     current_sub_fail_count: int, 
    #     max_fails: int, 
    #     mute_minutes: int
    # ):
    #     """
    #     Обрабатывает пользователя, не подписанного на обязательные каналы.
    #     Увеличивает счетчик неудач, отправляет предупреждение, применяет мут при необходимости, удаляет сообщение.
    #     """
    #     logger.info(format_sub_log("HANDLE_UNSUB", user.id, user.full_name, chat.id, chat.title, 
    #                               f"Обработка неподписанного пользователя. Каналы: {unsubscribed_channel_ids}"))

    #     1. Увеличиваем счетчик неудач в БД
    #     new_fail_count = current_sub_fail_count + 1
    #     await self.db.update_sub_fail_count(user.id, chat.id, increment_by=1) 
    #     logger.info(format_sub_log("FAIL_COUNT_INC", user.id, user.full_name, chat.id, chat.title, 
    #                               f"Счетчик провалов подписки увеличен до {new_fail_count} (было {current_sub_fail_count})."))

    #     2. Отправляем предупреждение
    #     user_mention_html = get_user_mention_html(user)
    #     # Предполагаем, что is_admin_user здесь не нужен или False по умолчанию для этого сценария
    #     await self.send_subscription_warning(
    #         chat_id=chat.id,
    #         user_id=user.id,
    #         user_mention=user_mention_html,
    #         missing_channel_ids=unsubscribed_channel_ids
    #     )
    #     logger.debug(format_sub_log("WARN_SENT", user.id, user.full_name, chat.id, chat.title, 
    #                                "Предупреждение о подписке отправлено."))

    #     3. Проверяем, нужно ли применять мут
    #     if new_fail_count >= max_fails:
    #         mute_duration_seconds = mute_minutes * 60
    #         # until_date = int(time.time()) + mute_duration_seconds # Для aiogram 2
    #         # Для aiogram 3 используем timedelta
    #         until_date = datetime.datetime.now() + datetime.timedelta(seconds=mute_duration_seconds)

    #         try:
    #             await self.bot.restrict_chat_member(
    #                 chat_id=chat.id,
    #                 user_id=user.id,
    #                 permissions=types.ChatPermissions(can_send_messages=False), # Запрещаем только отправку сообщений
    #                 until_date=until_date 
    #             )
    #             # Сохраняем информацию о муте в БД
    #             # Повторно исправляем вызов: передаем user_id, chat_id, и timestamp как именованные аргументы
    #             await self.db.update_user_ban_status(user_id=user.id, chat_id=chat.id, ban_until=int(until_date.timestamp()))
    #             logger.info(format_sub_log("MUTE_APPLIED", user.id, user.full_name, chat.id, chat.title,
    #                                       f"Получил мут на {mute_minutes} мин. ({new_fail_count}/{max_fails} попыток). До {until_date}"))
    #         except TelegramAPIError as e:
    #             logger.error(format_sub_log("MUTE_ERROR", user.id, user.full_name, chat.id, chat.title, 
    #                                        f"Ошибка при попытке выдать мут: {e}"))
    #         except Exception as e_ban_db:
    #              logger.error(format_sub_log("MUTE_DB_ERROR", user.id, user.full_name, chat.id, chat.title, 
    #                                        f"Ошибка записи бана в БД: {e_ban_db}"))


    #     4. Удаляем исходное сообщение пользователя (если оно есть)
    #     if message and message.message_id: # Проверяем, что это действительно сообщение, а не, например, событие входа
    #         try:
    #             await message.delete()
    #             logger.info(format_sub_log("MSG_DELETED", user.id, user.full_name, chat.id, chat.title, 
    #                                       "Исходное сообщение удалено из-за провала проверки подписки."))
    #         except TelegramAPIError as e:
    #             if "message to delete not found" in str(e).lower():
    #                 logger.warning(format_sub_log("MSG_DELETE_NOT_FOUND", user.id, user.full_name, chat.id, chat.title, 
    #                                             "Сообщение уже было удалено или не найдено."))
    #             else:
    #                 logger.warning(format_sub_log("MSG_DELETE_ERROR", user.id, user.full_name, chat.id, chat.title, 
    #                                             f"Не удалось удалить исходное сообщение: {e}"))
    #         except Exception as e_del_unexpected:
    #              logger.error(format_sub_log("MSG_DELETE_UNEXPECTED", user.id, user.full_name, chat.id, chat.title, 
    #                                             f"Непредвиденная ошибка при удалении сообщения: {e_del_unexpected}")) 