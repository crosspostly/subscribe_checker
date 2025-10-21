"""
Обработчик обычных текстовых сообщений в группах.
Вызывает сервисы для проверки капчи и подписки.
"""
import logging
from typing import Dict, Any, Optional
from aiogram import Router, Bot, F, types, Dispatcher
from aiogram.enums import ChatType, ChatMemberStatus, ContentType
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramBadRequest
from aiogram.filters import ChatMemberUpdatedFilter, IS_ADMIN, IS_NOT_MEMBER, MEMBER, RESTRICTED
from aiogram.types import ChatMemberUpdated, ChatPermissions
from aiogram.utils.markdown import hlink, hbold, hitalic, hcode
from aiogram.fsm.context import FSMContext
from datetime import datetime
import asyncio
import time

# Импорты
from bot.db.database import DatabaseManager
from bot.services.captcha import CaptchaService, format_captcha_log
from bot.services.subscription import SubscriptionService
from bot.services.channel_mgmt import ChannelManagementService
from bot.utils.helpers import get_user_mention_html, is_admin, get_cached_general_info
from bot.bot_instance import bot, db_manager, actual_bot_username
from bot.middlewares.db_middleware import DbSessionMiddleware
from bot.middlewares.bot_middleware import BotMiddleware
from aiogram.filters.command import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.data.callback_data import (
    CaptchaCallback, 
    SubscriptionCheckCallback
)

logger = logging.getLogger(__name__)
group_msg_router = Router()

# Регистрируем middleware
group_msg_router.message.middleware.register(DbSessionMiddleware(db_manager))
group_msg_router.chat_member.middleware.register(DbSessionMiddleware(db_manager))

group_msg_router.message.middleware.register(BotMiddleware(bot))
group_msg_router.chat_member.middleware.register(BotMiddleware(bot))

# Фильтр, чтобы этот роутер реагировал только на сообщения в группах/супергруппах
group_msg_router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))

# Вспомогательные функции для форматирования
def get_chat_link(chat_id, chat_title=None):
    """Создаёт ссылку на чат в формате Markdown."""
    if not chat_title:
        chat_title = f"Чат {chat_id}"
    return f"[{chat_title}](https://t.me/c/{str(chat_id).replace('-100', '')})"

def get_user_link(user_id, user_name=None):
    """Создаёт ссылку на пользователя в формате HTML."""
    if not user_name:
        user_name = f"Пользователь {user_id}"
    return f"<a href='tg://user?id={user_id}'>{user_name}</a>"

# Вспомогательная функция для вывода сообщений в лог с гиперссылками
def format_log_message(message_type, chat_id, chat_title, user_id=None, user_name=None, extra_info=None):
    """Форматирует сообщение для логирования с названиями чатов и именами пользователей."""
    chat_info = f"{chat_title} (ID: {chat_id})"
    user_info = f"{user_name} (ID: {user_id})" if user_id else ""
    extra = f": {extra_info}" if extra_info else ""
    
    if user_id:
        return f"[{message_type}] {user_info} в чате {chat_info}{extra}"
    else:
        return f"[{message_type}] Чат {chat_info}{extra}"

async def _delete_message_after_delay(bot: Bot, chat_id: int, message_id: int, delay: int):
    """Удаляет сообщение с указанной задержкой."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
        logger.debug(f"Сообщение {message_id} удалено из чата {chat_id} после задержки {delay} сек.")
    except TelegramAPIError as e:
        logger.warning(f"Не удалось удалить сообщение {message_id} из чата {chat_id}: {e}")

@group_msg_router.message()
async def handle_group_message(message: types.Message, bot: Bot, db_manager: DatabaseManager, captcha_service: CaptchaService, subscription_service: SubscriptionService, state: FSMContext):
    user = message.from_user
    chat = message.chat

    if not user:
        logger.info(f"Сообщение в чате {chat.id} ({chat.title}) без user (возможно, от имени канала). Тип: {message.content_type}")
        return # Пропускаем сообщения без отправителя (например, от имени канала)

    # Пропускаем сообщения от ботов
    if user.is_bot:
        logger.debug(f"Пропускаю сообщение от бота {user.id} (\'{user.full_name}\') в чате {chat.id}.")
        return

    # Пропускаем сообщения от служебного аккаунта Telegram (ID 777000)
    if user.id == 777000:
         logger.debug(f"Пропускаю сообщение от служебного аккаунта Telegram (ID 777000) в чате {chat.id}.")
         return

    chat_settings = await db_manager.get_chat_settings(chat.id)

    # Для получения значения, которое может отсутствовать или быть NULL
    is_activated_from_db = chat_settings['is_activated'] if chat_settings and 'is_activated' in chat_settings.keys() else None
    is_chat_activated = bool(is_activated_from_db) if is_activated_from_db is not None else False
    
    if not is_chat_activated:
        return 
        
    user_status_db = await db_manager.get_user_status_in_chat(user.id, chat.id)
    # Используем is_admin из helpers с нужными аргументами
    is_user_admin = await is_admin(bot, chat.id, user.id) 

    # Для получения значения, которое может отсутствовать или быть NULL
    captcha_enabled_from_db = chat_settings['captcha_enabled'] if chat_settings and 'captcha_enabled' in chat_settings.keys() else None
    is_captcha_enabled = bool(captcha_enabled_from_db) if captcha_enabled_from_db is not None else False

    # Для получения значения, которое может отсутствовать или быть NULL
    user_captcha_passed_from_db = user_status_db['captcha_passed'] if user_status_db and 'captcha_passed' in user_status_db.keys() else None
    has_user_passed_captcha = bool(user_captcha_passed_from_db)
    
    if is_captcha_enabled and not is_user_admin and not has_user_passed_captcha:
        logger.debug(f"[handle_group_message] Пользователь {user.id} в чате {chat.id} не прошел капчу (сообщение), но капча теперь в on_user_join.")
        # Потенциально удалить сообщение, если бот имеет права и это нежелательное поведение
        # try:
        #     await message.delete()
        # except TelegramAPIError:
        #     pass # Ошибки удаления игнорируем
        # return # Можно вернуть, если хотим строго блокировать таких пользователей
        pass 

    # Для получения значения, которое может отсутствовать или быть NULL
    sub_check_is_enabled_from_db = chat_settings['subscription_check_enabled'] if chat_settings and 'subscription_check_enabled' in chat_settings.keys() else None
    is_sub_check_enabled = bool(sub_check_is_enabled_from_db) if sub_check_is_enabled_from_db is not None else False
    
    # Убедимся, что отправитель сообщения является обычным пользователем и не является ботом или служебным аккаунтом,
    # прежде чем применять проверку подписки.
    if user and not user.is_bot and user.id != 777000 and is_sub_check_enabled and not is_user_admin:
        linked_channels = await db_manager.get_linked_channels_for_chat(chat.id)
        if linked_channels:
            # Для получения значения, которое может отсутствовать или быть NULL
            granted_access_until_from_db = user_status_db['granted_access_until_ts'] if user_status_db and 'granted_access_until_ts' in user_status_db.keys() else None
            granted_access_until = int(granted_access_until_from_db) if granted_access_until_from_db is not None else 0
            
            current_time = int(time.time())
            if not (granted_access_until and granted_access_until > current_time):
                is_subscribed_to_all, unsubscribed_channel_ids = await subscription_service.check_subscription(user.id, chat.id)
                # Статус подписки в БД обновляется внутри check_subscription или принудительно, если нужно

                if not is_subscribed_to_all:
                    logger.info(f"SUB_LOG: Пользователь {user.id} ({user.full_name}) не подписан на все каналы в чате {chat.id}. Неподписанные ID: {unsubscribed_channel_ids}")
                    
                    # Получаем текущий счетчик неудач из БД
                    sub_fail_count_from_db = user_status_db['subscription_fail_count'] if user_status_db and 'subscription_fail_count' in user_status_db.keys() else None
                    current_sub_fail_count = int(sub_fail_count_from_db) if sub_fail_count_from_db is not None else 0
                    
                    # Получаем настройки для мута из chat_settings или используем значения по умолчанию
                    max_fails_allowed = chat_settings.get('max_subscription_fails', 3) # По умолчанию 3 попытки
                    mute_duration_minutes = chat_settings.get('subscription_mute_minutes', 30) # По умолчанию 30 минут = 1500 минут

                    # Вызываем новый метод из SubscriptionService
                    await subscription_service.handle_subscription_failure(
                        original_message=message, 
                        user=user, 
                        chat=chat, 
                        unsubscribed_channel_ids=unsubscribed_channel_ids,
                        current_sub_fail_count=current_sub_fail_count, # Передаем ТЕКУЩИЙ счетчик
                        max_fails_allowed=max_fails_allowed,
                        mute_duration_minutes=mute_duration_minutes
                    )
                    return # Важно завершить обработку здесь, так как handle_subscription_failure управляет ответом
                else:
                    # Пользователь подписан. Если у него были неудачные попытки, сбросим счетчик.
                    # Здесь user_status_db все еще может быть старым, но reset_sub_fail_count идемпотентен.
                    # Если счетчик уже 0, ничего страшного не произойдет.
                    sub_fail_count_from_db = user_status_db['subscription_fail_count'] if user_status_db and 'subscription_fail_count' in user_status_db.keys() else None
                    if sub_fail_count_from_db is not None and int(sub_fail_count_from_db) > 0:
                        await db_manager.reset_sub_fail_count(user.id, chat.id)
                        logger.info(f"SUB_LOG: Сброшен счетчик провалов подписки для {user.id} в {chat.id}, т.к. он подписался.")
                    
                    # Также, если пользователь был замучен из-за подписки, и теперь он подписался, снимем мут
                    ban_until_ts_from_db = user_status_db['ban_until_ts'] if user_status_db and 'ban_until_ts' in user_status_db.keys() else None
                    ban_reason_from_db = user_status_db['ban_reason'] if user_status_db and 'ban_reason' in user_status_db.keys() else None

                    if ban_until_ts_from_db and int(ban_until_ts_from_db) > current_time and ban_reason_from_db == "subscription_check":
                        logger.info(f"SUB_LOG: Пользователь {user.id} в {chat.id} был замучен за подписку, но теперь подписан. Снимаем мут.")
                        await subscription_service.unban_user_for_subscription(user.id, chat.id)
                        # Сообщение об анмуте отправляется из unban_user_for_subscription, если необходимо

# --- Обработчики изменения статуса участников чата ---

@group_msg_router.chat_member(ChatMemberUpdatedFilter(member_status_changed=(ChatMemberStatus.KICKED, ChatMemberStatus.LEFT)))
async def on_user_leave_or_kick(event: types.ChatMemberUpdated, bot: Bot, db_manager: DatabaseManager):
    user_id = event.new_chat_member.user.id
    chat_id = event.chat.id
    user_full_name = event.new_chat_member.user.full_name
    chat_title = event.chat.title or f"ID {chat_id}"
    status = event.new_chat_member.status

    logger.info(f"Пользователь {user_id} ({user_full_name}) покинул/удален из чата {chat_id} ('{chat_title}') со статусом: {status.name}")
    # Можно добавить логику очистки данных пользователя из users_status_in_chats для этого чата
    # await db_manager.clear_user_status_in_chat(user_id, chat_id)
    # Пока не делаем, чтобы сохранить историю попыток/варнингов, если он вернется

# --- Обработка кода настройки (только от админов) --- #

@group_msg_router.message(
    F.text.startswith("setup_"), # Ловим только текст, начинающийся с setup_
    F.from_user.id != None # Убедимся, что есть ID пользователя 
)
async def handle_setup_code(message: types.Message, bot: Bot, db_manager: DatabaseManager, state: FSMContext):
    """Обрабатывает код настройки, отправленный админом."""
    if not await db_manager.is_chat_activated(message.chat.id):
        await message.reply('Бот не активирован в этом чате. Пожалуйста, активируйте его с помощью кода.')
        return

    user = message.from_user
    chat = message.chat

    # Проверяем, что отправитель - админ ЭТОГО чата
    try:
        sender_member = await bot.get_chat_member(chat.id, user.id)
        if sender_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
            logger.info(f"[SETUP_CODE] Код '{message.text}' отправлен не админом ({user.id}) в чате {chat.id}. Игнорируем.")
            # Удаляем сообщение не-админа с кодом?
            try:
                await message.delete()
            except Exception:
                pass
            return
    except TelegramAPIError as e:
        logger.error(f"[SETUP_CODE] Ошибка проверки админа {user.id} при обработке кода: {e}")
        # Если не можем проверить, лучше не обрабатывать код
        return 

    # Пытаемся извлечь user_id из кода
    try:
        code_parts = message.text.split('_')
        if len(code_parts) != 2 or not code_parts[1].isdigit():
            raise ValueError("Неверный формат кода")
        user_id_from_code = int(code_parts[1])
    except ValueError:
        logger.warning(f"[SETUP_CODE] Неверный формат кода настройки '{message.text}' от админа {user.id} в чате {chat.id}.")
        # Уведомить админа об ошибке?
        try:
            await message.delete()
        except Exception:
            pass
        return

    logger.info(f"[SETUP_CODE] Админ {user.id} отправил код '{message.text}' для пользователя {user_id_from_code} в чате {chat.id} ('{chat.title}').")

    # Удаляем сообщение с кодом в группе
    try:
        await message.delete()
        logger.info(f"[SETUP_CODE] Сообщение с кодом от {user.id} удалено из чата {chat.id}.")
    except Exception as e:
        logger.warning(f"[SETUP_CODE] Не удалось удалить сообщение с кодом от {user.id} в чате {chat.id}: {e}. Продолжаем.")

    # Получаем FSM context для ЛС пользователя, которому предназначен код
    dp = Dispatcher.get_current()
    if not dp:
        logger.error("[SETUP_CODE] Не удалось получить текущий Dispatcher! FSM не запустится.")
        try:
            await bot.send_message(user.id, "Внутренняя ошибка (dispatcher). Настройка невозможна.")
        except Exception:
            pass
        return
    
    user_dm_state: FSMContext = dp.storage.get_context(bot=bot, chat_id=user_id_from_code, user_id=user_id_from_code)

    # Получаем объект User пользователя из кода
    try:
        target_user = await bot.get_chat(user_id_from_code)
        if target_user.type != ChatType.PRIVATE:
            logger.error(f"[SETUP_CODE] ID {user_id_from_code} из кода принадлежит не пользователю. Отмена.")
            try:
                await bot.send_message(user.id, f"Ошибка: ID {user_id_from_code} не является ID пользователя.")
            except Exception:
                pass
            return
    except TelegramAPIError as e:
        logger.error(f"[SETUP_CODE] Не удалось получить инфо о user {user_id_from_code}: {e}. Возможно, заблокировал бота.")
        try:
            await bot.send_message(user.id, f"Ошибка: не удалось найти user {user_id_from_code} или он заблокировал бота.")
        except Exception:
            pass
        return

    # Устанавливаем зависимости для сервиса (обязательно перед вызовом)
    channel_mgmt_service = ChannelManagementService(bot, db_manager, state.storage)

    # Запускаем FSM в ЛС пользователя
    try:
        await channel_mgmt_service.start_channel_management_fsm(
            user=target_user, 
            chat_id_to_setup=chat.id,
            chat_title=chat.title or f"Чат ID {chat.id}",
            state=user_dm_state
        )
        logger.info(f"[SETUP_CODE] Успешно запущен FSM управления каналами для user {user_id_from_code} (админ {user.id}, чат {chat.id}).")
    except Exception as e:
        logger.error(f"[SETUP_CODE] Ошибка при запуске FSM для user {user_id_from_code}: {e}", exc_info=True)
        try:
            await bot.send_message(user.id, f"Произошла ошибка при запуске настройки для пользователя: {e}")
        except Exception:
            pass
        # Очищать ли state пользователя в ЛС? Наверное, да.
        await user_dm_state.clear()

# --- Обработчики событий изменения состава участников ---

# Обработка присоединения нового УЧАСТНИКА (не админа) и изменения его статуса (капча)
@group_msg_router.chat_member(ChatMemberUpdatedFilter(member_status_changed=(
    IS_NOT_MEMBER >> MEMBER,      # Новый участник присоединился
    MEMBER >> RESTRICTED,         # Участник был ограничен (например, для капчи)
    RESTRICTED >> MEMBER          # Участнику сняли ограничения (например, прошел капчу)
)))
async def on_user_join_entry(event: types.ChatMemberUpdated, bot: Bot, db_manager: DatabaseManager, captcha_service: CaptchaService, subscription_service: SubscriptionService):
    # САМОЕ ПЕРВОЕ ЛОГИРОВАНИЕ для отладки
    logger.info(
        f"[ON_USER_JOIN_ENTRY] Событие ChatMemberUpdated: "
        f"chat_id={event.chat.id}, user_id={event.new_chat_member.user.id}, "
        f"old_status={event.old_chat_member.status.name if event.old_chat_member else 'N/A'}, "
        f"new_status={event.new_chat_member.status.name}"
    )
    
    chat = event.chat
    user = event.new_chat_member.user
    chat_title = chat.title or f"ID {chat.id}" # Обеспечиваем наличие заголовка для логов

    # --- Проверка, имеет ли бот права администратора ---
    try:
        me = await bot.get_chat_member(chat_id=chat.id, user_id=bot.id)
        if not me.can_restrict_members or not me.can_delete_messages: # Примерный набор минимальных прав
            bot_user_info = await bot.get_me() # Получаем информацию о боте
            bot_name_for_log = bot_user_info.full_name if bot_user_info else "UnknownBot"
            # Используем существующую format_log_message, если она подходит
            logger.warning(format_log_message(
                "USER_JOIN_NO_PERMISSIONS", 
                chat.id, 
                chat_title, 
                bot.id, # ID бота
                bot_name_for_log, # Имя бота
                f"У бота нет необходимых прав (restrict_members/delete_messages) в чате. Не могу обрабатывать вступления/капчу/подписку."
            ))
            return
    except TelegramAPIError as e:
        bot_user_info = await bot.get_me() # Получаем информацию о боте
        bot_name_for_log = bot_user_info.full_name if bot_user_info else "UnknownBot"
        logger.error(format_log_message(
            "USER_JOIN_GET_MEMBER_ERROR",
            chat.id,
            chat_title,
            bot.id,
            bot_name_for_log,
            f"Ошибка при проверке прав бота в чате: {e}"
        ), exc_info=True)
        return # Если не можем проверить права, лучше не продолжать

    # Пропускаем обработку, если событие касается самого бота
    if user.id == bot.id:
        bot_user_info = await bot.get_me()
        logger.info(format_log_message(
            "BOT_JOIN_EVENT", 
            chat.id, 
            chat_title, 
            bot.id, 
            bot_user_info.full_name if bot_user_info else "Bot", 
            "Событие касается самого бота. Никаких действий не требуется."
        ))
        return

    # Пропускаем обработку, если user_id отрицательный (указывает на канал/группу, действующую как пользователь)
    if user.id < 0:
        logger.info(format_log_message(
            "CHANNEL_AS_USER_EVENT", 
            chat.id,
            chat_title,
            user.id,
            user.full_name, 
            "Обнаружено событие для сущности канала/группы (отрицательный ID). Пропуск обработки вступления."
        ))
        return

    # Пропускаем обработку для служебного аккаунта Telegram (ID 777000)
    if user.id == 777000: # Telegram's service account for channel posts
        logger.info(format_log_message(
            "SERVICE_MSG_USER_JOIN",
            chat.id,
            chat_title,
            user.id,
            "Telegram (Service Account)",
            "Сообщение от имени канала (служебный аккаунт Telegram). Пропуск обработки вступления."
        ))
        return

    # Пропускаем других ботов, если это не наш бот
    if user.is_bot:
        logger.info(format_log_message(
            "OTHER_BOT_JOIN_EVENT",
            chat.id,
            chat_title,
            user.id,
            user.full_name,
            "Другой бот присоединился/изменил статус. Пропуск."
        ))
        return

    # --- Основная логика обработки ---
    await db_manager.add_user_if_not_exists(
        user_id=user.id, username=user.username, first_name=user.first_name,
        last_name=user.last_name,
        language_code=user.language_code if hasattr(user, 'language_code') else None,
        is_premium=bool(user.is_premium) if hasattr(user, 'is_premium') else False
    )

    chat_settings = await db_manager.get_chat_settings(chat.id)
    if not chat_settings:
        logger.error(f"[on_user_join_entry] Не удалось получить настройки для чата {chat_id_for_log(chat)}. Обработка прервана.")
        return

    is_activated_from_db = chat_settings.get('is_activated')
    is_chat_activated = bool(is_activated_from_db)
    
    is_setup_complete_from_db = chat_settings.get('setup_complete')
    is_chat_setup_complete = bool(is_setup_complete_from_db)

    # Логируем статус активации и настройки
    logger.info(format_log_message(
        "USER_JOIN_CHAT_STATUS",
        chat.id,
        chat_title,
        user.id,
        user.full_name,
        f"Статус чата: Активирован={is_chat_activated}, Настройка завершена={is_chat_setup_complete}"
    ))

    if not is_chat_activated:
        logger.info(format_log_message(
            "USER_JOIN_NOT_ACTIVATED",
            chat.id,
            chat_title,
            user.id,
            user.full_name,
            "Чат не активирован. Капча и проверка подписки не применяются при вступлении."
        ))
        # Здесь можно добавить логику отправки сообщения администратору чата о необходимости активации,
        # если configured_by_user_id известен и это не владелец бота.
        return

    # Если чат активирован, продолжаем с капчей и проверкой подписки
    user_is_admin_in_chat = await is_admin(bot, chat.id, user.id)

    # --- Обработка КАПЧИ ---
    captcha_enabled_from_db = chat_settings.get('captcha_enabled', 1) # По умолчанию включена, если нет в БД
    is_captcha_enabled = bool(captcha_enabled_from_db)

    if is_captcha_enabled and not user_is_admin_in_chat:
        user_status_db = await db_manager.get_user_status_in_chat(user.id, chat.id)
        captcha_passed_from_db = user_status_db.get('captcha_passed') if user_status_db else None
        has_user_passed_captcha = bool(captcha_passed_from_db)

        if not has_user_passed_captcha:
            # Проверяем, не является ли это событием выхода из restricted (после прохождения капчи) в member
            if event.old_chat_member and event.old_chat_member.status == ChatMemberStatus.RESTRICTED and \
               event.new_chat_member.status == ChatMemberStatus.MEMBER:
                logger.info(format_log_message(
                    "USER_JOIN_CAPTCHA_ALREADY_PASSED_TRANSITION",
                    chat.id,
                    chat_title,
                    user.id,
                    user.full_name,
                    "Пользователь перешел из restricted в member, вероятно, капча уже пройдена. Пропуск отправки новой капчи."
                ))
            else:
                logger.info(format_log_message(
                    "USER_JOIN_START_CAPTCHA",
                    chat.id,
                    chat_title,
                    user.id,
                    user.full_name,
                    "Капча включена, запускаем для нового участника..."
                ))
                await captcha_service.start_captcha_for_user(chat=chat, user=user, message_id_to_reply=None) # message_id_to_reply не нужен для join
    elif not is_captcha_enabled and not user_is_admin_in_chat:
        # Если капча выключена, но пользователь ранее не прошел (был статус 0)
        user_status_db = await db_manager.get_user_status_in_chat(user.id, chat.id)
        captcha_passed_from_db = user_status_db.get('captcha_passed') if user_status_db else None
        if captcha_passed_from_db is not None and not bool(captcha_passed_from_db):
            await db_manager.update_user_captcha_status(user.id, chat.id, passed=True)
            logger.info(format_log_message(
                "USER_JOIN_CAPTCHA_DISABLED_SET_PASSED",
                chat.id,
                chat_title,
                user.id,
                user.full_name,
                "Капча выключена, а пользователь ранее ее не прошел. Установлен флаг captcha_passed=True."
            ))

    # --- Обработка ПОДПИСКИ (только если не админ и чат активирован) ---
    # Проверка подписки обычно происходит при первом сообщении пользователя,
    # но можно добавить базовую проверку и при входе, если это требуется.
    # В текущей логике handle_group_message проверка подписки более полная.
    # Здесь можно, например, просто записать, что пользователь присоединился,
    # и его last_seen обновится при первом сообщении.
    # Если нужна немедленная проверка подписки при входе:
    # sub_check_enabled_from_db = chat_settings.get('subscription_check_enabled', 1)
    # is_sub_check_enabled = bool(sub_check_enabled_from_db)
    # if is_sub_check_enabled and not user_is_admin_in_chat:
    #     logger.info(f"USER_JOIN: Проверка подписки для {user.id} в {chat.id} будет выполнена при первом сообщении.")
    #     pass # Логика проверки подписки при входе здесь не реализована полностью,
             # так как она сложнее и обычно привязана к сообщению для ответа/мута.

    logger.info(format_log_message(
        "USER_JOIN_COMPLETED",
        chat.id,
        chat_title,
        user.id,
        user.full_name,
        "Обработка вступления пользователя завершена."
    ))

@group_msg_router.chat_member(
    ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_ADMIN)
)
@group_msg_router.chat_member(
    ChatMemberUpdatedFilter(IS_ADMIN >> IS_ADMIN)
)
async def on_admin_join_or_status_change(event: types.ChatMemberUpdated, bot: Bot, db_manager: DatabaseManager):
    """Реагирует на добавление админа или изменение статуса существующего.
       Также используется для начальной настройки при добавлении бота как админа.
    """
    chat_id = event.chat.id
    user_id = event.new_chat_member.user.id
    user_name = event.new_chat_member.user.first_name
    is_bot_event = event.new_chat_member.user.is_bot # Переименовал, чтобы не конфликтовать с экземпляром bot
    bot_info = await bot.get_me()

    logger.info(f"[ADMIN_EVENT] В чате {chat_id} изменился статус участника {user_id} ({user_name}). Новый статус: {event.new_chat_member.status}")

    # Если бот сам стал админом
    if user_id == bot_info.id:
        logger.info(f"[ADMIN_EVENT] Меня ({bot_info.username}) назначили админом в чате {chat_id} ({event.chat.title})")
        # При добавлении бота как админа, можно сразу создать запись о чате в БД
        # Это полезно, если бот был добавлен напрямую, а не через /setup
        await db_manager.add_chat_if_not_exists(
            chat_id=chat_id,
            chat_title=event.chat.title,
            added_by_user_id=event.from_user.id # Кто добавил/изменил права
        )
        # Можно отправить приветственное сообщение в чат о готовности к настройке
        try:
            await bot.send_message(
                chat_id,
                f"👋 Привет! Я готов к работе в чате {hbold(event.chat.title)}.\n"
                f"Администратор ({hlink(event.from_user.first_name, f'tg://user?id={event.from_user.id}')}) может теперь настроить меня.\n"
                f"Для начала получите код настройки в личных сообщениях со мной (@{actual_bot_username}), используя команду /code, "
                f"а затем отправьте этот код сюда.",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.warning(f"[ADMIN_EVENT] Не удалось отправить приветствие в чат {chat_id}: {e}")
    else:
        # Если изменился статус другого админа (не бота)
        # Здесь можно обновить список админов в БД, если это нужно
        logger.debug(f"[ADMIN_EVENT] Статус админа {user_id} ({user_name}) изменился в чате {event.chat.id}.")

# Обработчик колбэка для кнопки капчи
@group_msg_router.callback_query(F.data.startswith("captcha_pass:"))
async def handle_captcha_callback(callback_query: types.CallbackQuery, bot: Bot, db_manager: DatabaseManager, captcha_service: CaptchaService):
    """Обрабатывает нажатие кнопки 'Я не робот' в сообщении с капчей."""
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    message_id = callback_query.message.message_id
    chat_title = callback_query.message.chat.title or f"Чат {chat_id}"
    user_name = callback_query.from_user.full_name

    logger.info(format_captcha_log(chat_id, chat_title, user_id, user_name, "Нажата кнопка капчи"))

    # Проверяем, что колбэк от того пользователя, которому была отправлена капча
    # ID пользователя закодировано в callback_data: "captcha_pass:{user_id}"
    expected_user_id = int(callback_query.data.split(":")[1])
    if user_id != expected_user_id:
        logger.warning(format_captcha_log(chat_id, chat_title, user_id, user_name, f"Нажата кнопка чужой капчи (ожидался {expected_user_id}). Игнорирую.", message_id))
        await callback_query.answer("Эта кнопка не для вас!", show_alert=True)
        return

    try:
        # Отмечаем, что пользователь прошел капчу в БД
        # Нужен метод в DatabaseManager для обновления статуса капчи
        await db_manager.update_user_captcha_status(user_id, chat_id, passed=True)
        logger.info(format_captcha_log(chat_id, chat_title, user_id, user_name, "Статус капчи обновлен в БД.", message_id))

        # Снимаем временные ограничения (мут)
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False, # Обычно запрещено для обычных пользователей
                can_invite_users=True,
                can_pin_messages=False # Обычно запрещено для обычных пользователей
            ),
            until_date=0 # Снимаем все ограничения
        )
        logger.info(format_captcha_log(chat_id, chat_title, user_id, user_name, "Временные ограничения (мут) сняты.", message_id))

        # Удаляем сообщение с капчей
        await callback_query.message.delete()
        logger.info(format_captcha_log(chat_id, chat_title, user_id, user_name, "Сообщение капчи удалено.", message_id))

        # Отправляем подтверждение пользователю
        await callback_query.answer("✅ Вы успешно прошли проверку!", show_alert=False)

        # Опционально: отправить приветственное сообщение или запустить проверку подписки
        # await subscription_service.check_subscription_and_warn(...) # Возможно, потребуется новая функция

    except TelegramAPIError as e:
        logger.error(format_captcha_log(chat_id, chat_title, user_id, user_name, f"Ошибка при обработке колбэка капчи: {e}", message_id))
        await callback_query.answer("Произошла ошибка. Попробуйте позже.", show_alert=True)
    except Exception as e:
        logger.critical(format_captcha_log(chat_id, chat_title, user_id, user_name, f"Непредвиденная ошибка при обработке колбэка капчи: {e}", message_id))
        await callback_query.answer("Произошла непредвиденная ошибка. Попробуйте позже.", show_alert=True)

# --- Команды администрирования чата ---

CONFIRM_DELETE_CHAT_CALLBACK_PREFIX = "confirm_delete_chat:"
CANCEL_DELETE_CHAT_CALLBACK_PREFIX = "cancel_delete_chat:"

@group_msg_router.message(Command("rmchat"))
async def cmd_remove_chat_from_bot(message: types.Message, bot: Bot, db_manager: DatabaseManager):
    """Обрабатывает команду /rmchat для полного удаления данных чата."""
    chat_id = message.chat.id
    chat_title = message.chat.title or f"Чат {chat_id}"
    user_id = message.from_user.id if message.from_user else None
    user_name = message.from_user.full_name if message.from_user else "Неизвестный"

    logger.info(format_log_message("CMD_REMOVE_CHAT", chat_id, chat_title, user_id, user_name, "Получена команда"))

    # Используем is_admin из helpers
    if not await is_admin(bot, chat_id, user_id): 
        logger.warning(format_log_message("CMD_REMOVE_CHAT", chat_id, chat_title, user_id, user_name, "Команда вызвана не админом. Игнорируется."))
        try:
            await message.delete() # Удаляем сообщение не-админа
        except Exception:
            pass
        return

    # Создаем клавиатуру с подтверждением
    confirm_button = InlineKeyboardButton(
        text="🗑️ Да, удалить этот чат", 
        callback_data=f"{CONFIRM_DELETE_CHAT_CALLBACK_PREFIX}{chat_id}"
    )
    cancel_button = InlineKeyboardButton(
        text="❌ Нет, отмена", 
        callback_data=f"{CANCEL_DELETE_CHAT_CALLBACK_PREFIX}{chat_id}"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[confirm_button], [cancel_button]])

    warning_text = (
        f"⚠️ {hbold('ВНИМАНИЕ!')} ⚠️\n\n"
        f"Вы собираетесь полностью удалить все данные чата \"{hbold(chat_title)}\" (ID: `{chat_id}`) из базы данных бота. "
        f"Это действие необратимо и приведет к тому, что бот покинет этот чат.\n\n"
        f"Нажмите \"Да, удалить этот чат\", чтобы подтвердить, или \"Нет, отмена\" для отмены."
    )
    
    try:
        await message.reply(warning_text, reply_markup=keyboard, parse_mode="HTML")
        logger.info(format_log_message("CMD_REMOVE_CHAT", chat_id, chat_title, user_id, user_name, "Отправлено сообщение с подтверждением."))
    except Exception as e:
        logger.error(format_log_message("CMD_REMOVE_CHAT", chat_id, chat_title, user_id, user_name, f"Ошибка при отправке подтверждения: {e}"))

@group_msg_router.callback_query(F.data.startswith(CONFIRM_DELETE_CHAT_CALLBACK_PREFIX))
async def handle_confirm_delete_chat_callback(callback_query: types.CallbackQuery, bot: Bot, db_manager: DatabaseManager):
    """Обрабатывает подтверждение удаления чата."""
    requesting_user_id = callback_query.from_user.id
    chat_id_to_delete = int(callback_query.data.split(":")[1])
    message_id = callback_query.message.message_id
    current_chat_id = callback_query.message.chat.id
    chat_title = callback_query.message.chat.title or f"Чат {current_chat_id}"
    user_name = callback_query.from_user.full_name

    logger.info(format_log_message("CALLBACK_CONFIRM_DELETE", current_chat_id, chat_title, requesting_user_id, user_name, f"Получено подтверждение на удаление чата {chat_id_to_delete}"))

    # Дополнительная проверка, что кнопку нажал админ этого чата
    try:
        member = await bot.get_chat_member(current_chat_id, requesting_user_id)
        if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
            logger.warning(format_log_message("CALLBACK_CONFIRM_DELETE", current_chat_id, chat_title, requesting_user_id, user_name, "Кнопку подтверждения нажал не админ. Отклонено."))
            await callback_query.answer("Это действие доступно только администраторам чата.", show_alert=True)
            return
    except Exception as e:
        logger.error(format_log_message("CALLBACK_CONFIRM_DELETE", current_chat_id, chat_title, requesting_user_id, user_name, f"Ошибка проверки статуса админа: {e}"))
        await callback_query.answer("Ошибка проверки прав. Попробуйте позже.", show_alert=True)
        return

    if current_chat_id != chat_id_to_delete: # Проверка, что колбэк пришел из того же чата
        logger.error(format_log_message("CALLBACK_CONFIRM_DELETE", current_chat_id, chat_title, requesting_user_id, user_name, 
                                f"Колбэк на удаление чата {chat_id_to_delete} пришел из другого чата {current_chat_id}. Это странно. Отклонено."))
        await callback_query.message.edit_text("Ошибка: несоответствие ID чатов. Удаление отменено.")
        return

    try:
        deleted_from_db = await db_manager.delete_chat(chat_id_to_delete)
        if deleted_from_db:
            logger.info(format_log_message("CHAT_DELETED_DB", chat_id_to_delete, chat_title, requesting_user_id, user_name, "Чат успешно удален из БД."))
            try:
                await bot.leave_chat(chat_id_to_delete)
                logger.info(format_log_message("BOT_LEFT_CHAT", chat_id_to_delete, chat_title, requesting_user_id, user_name, "Бот успешно покинул чат."))
                await callback_query.message.edit_text(f"✅ Чат \"{hbold(chat_title)}\" (ID: `{chat_id_to_delete}`) успешно удален из базы данных, и бот покинул этот чат.", parse_mode="HTML")
            except TelegramForbiddenError:
                logger.warning(format_log_message("BOT_LEFT_CHAT_FORBIDDEN", chat_id_to_delete, chat_title, requesting_user_id, user_name, 
                                              "Бот не смог покинуть чат (недостаточно прав или уже удален/забанен)."))
                await callback_query.message.edit_text(f"✅ Чат \"{hbold(chat_title)}\" (ID: `{chat_id_to_delete}`) удален из БД, но бот не смог покинуть чат (возможно, у него нет прав или он уже удален).", parse_mode="HTML")
        else:
            logger.error(format_log_message("CHAT_DELETE_DB_FAILED", chat_id_to_delete, chat_title, requesting_user_id, user_name, "Не удалось удалить чат из БД."))
            await callback_query.message.edit_text("❌ Произошла ошибка при удалении чата из базы данных. Пожалуйста, проверьте логи.")
        
        await callback_query.answer() # Убираем часики с кнопки

    except Exception as e:
        logger.critical(format_log_message("CALLBACK_CONFIRM_DELETE_ERROR", chat_id_to_delete, chat_title, requesting_user_id, user_name, f"Критическая ошибка при удалении чата: {e}"), exc_info=True)
        await callback_query.message.edit_text("❌ Произошла критическая ошибка при удалении чата. Пожалуйста, свяжитесь с администратором бота.")
        await callback_query.answer("Критическая ошибка!", show_alert=True)

@group_msg_router.callback_query(F.data.startswith(CANCEL_DELETE_CHAT_CALLBACK_PREFIX))
async def handle_cancel_delete_chat_callback(callback_query: types.CallbackQuery, bot: Bot):
    """Обрабатывает отмену удаления чата."""
    requesting_user_id = callback_query.from_user.id
    chat_id_from_callback = int(callback_query.data.split(":")[1])
    current_chat_id = callback_query.message.chat.id
    chat_title = callback_query.message.chat.title or f"Чат {current_chat_id}"
    user_name = callback_query.from_user.full_name

    logger.info(format_log_message("CALLBACK_CANCEL_DELETE", current_chat_id, chat_title, requesting_user_id, user_name, f"Отмена удаления чата {chat_id_from_callback}."))

    # Проверка, что кнопку нажал админ (необязательно так строго, как при подтверждении, но для консистентности)
    try:
        member = await bot.get_chat_member(current_chat_id, requesting_user_id)
        if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
            await callback_query.answer("Это действие доступно только администраторам чата.", show_alert=True)
            return
    except Exception:
        pass # Если ошибка, просто не отвечаем на колбэк или отвечаем стандартно
        
    if current_chat_id != chat_id_from_callback:
         await callback_query.message.edit_text("Действие отменено (несоответствие ID чатов).")
         return

    await callback_query.message.edit_text("✅ Удаление чата отменено.")
    await callback_query.answer()

# Убедитесь, что group_router импортирован и используется в основном файле бота (__main__.py)
# dp.include_router(group_router) 