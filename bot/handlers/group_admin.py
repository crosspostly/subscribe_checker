"""
Обработчики для администрирования бота в группах.

Содержит:
- Обработчик добавления/изменения прав бота в чате.
- Обработчики FSM для выбора канала.
"""
import logging
from aiogram import Router, Bot, F, types
from aiogram.filters import Command, ChatMemberUpdatedFilter, ADMINISTRATOR, Filter, IS_ADMIN, IS_MEMBER
from aiogram.enums import ChatType, ContentType, ChatMemberStatus
from aiogram.fsm.context import FSMContext
from aiogram.types import ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.storage.base import StorageKey
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from typing import Union, Dict, Any
from aiogram.utils.markdown import hbold, hlink
import asyncio

# Используем абсолютные импорты
from bot.db.database import DatabaseManager
# Импорт actual_bot_username должен быть из bot.bot_instance
# from bot.config import actual_bot_username # НЕПРАВИЛЬНО
from bot.keyboards.inline import get_confirm_setup_keyboard
from bot.services.channel_mgmt import ChannelManagementService
from bot.utils.helpers import get_user_mention_html
from bot.states import ManageChannels
from bot.bot_instance import bot, db_manager, actual_bot_username # <--- ИМПОРТИРУЕМ ОТСЮДА
from bot.middlewares.db_middleware import DbSessionMiddleware
from bot.middlewares.bot_middleware import BotMiddleware
# Импортируем ConfirmSetupCallback
from bot.data.callback_data import ConfirmSetupCallback

# Импортируем format_log_message из group_messages 
# (В идеале его вынести в utils, но пока так для простоты переноса)
# Если group_messages.py в том же пакете (handlers), то from .group_messages import format_log_message
# Если нет, то from bot.handlers.group_messages import format_log_message
# Предполагаем, что они в одном пакете handlers
try:
    from .group_messages import format_log_message
except ImportError:
    # Фолбэк, если запускается не как часть пакета (например, для тестов этого модуля)
    from bot.handlers.group_messages import format_log_message

logger = logging.getLogger(__name__)
group_admin_router = Router() # <--- Определение роутера

# Регистрируем middleware
group_admin_router.message.middleware.register(DbSessionMiddleware(db_manager))
group_admin_router.chat_member.middleware.register(DbSessionMiddleware(db_manager))
group_admin_router.my_chat_member.middleware.register(DbSessionMiddleware(db_manager))
group_admin_router.callback_query.middleware.register(DbSessionMiddleware(db_manager))

group_admin_router.message.middleware.register(BotMiddleware(bot))
group_admin_router.chat_member.middleware.register(BotMiddleware(bot))
group_admin_router.my_chat_member.middleware.register(BotMiddleware(bot))
group_admin_router.callback_query.middleware.register(BotMiddleware(bot))

# Фильтр на тип чата (группа или супергруппа)
group_admin_router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
group_admin_router.chat_member.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))

# Добавляем фильтр для коллбэков этого роутера, если он будет обрабатывать коллбэки из групп
group_admin_router.callback_query.filter(F.message.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))

# --- Фильтр для кодов setup_{user_id} ---
class SetupCodeFilter(Filter):
    async def __call__(self, message: types.Message) -> Union[bool, Dict[str, Any]]:
        if not message.text:
            return False
        parts = message.text.strip().split('_')
        if len(parts) == 2 and parts[0] == 'setup' and parts[1].isdigit():
            user_id_to_setup = int(parts[1])
            # Возвращаем ID пользователя из кода для использования в хендлере
            return {"user_id_to_setup": user_id_to_setup}
        return False

# --- Обработчики изменения статуса администраторов --- #

# 1. Пользователь становится администратором (раньше не был)
@group_admin_router.chat_member(
    ChatMemberUpdatedFilter(member_status_changed=IS_MEMBER >> IS_ADMIN)
)
# 2. У существующего администратора меняются права
@group_admin_router.chat_member(
    ChatMemberUpdatedFilter(member_status_changed=IS_ADMIN >> IS_ADMIN)
)
async def on_admin_status_change(event: ChatMemberUpdated, bot: Bot, db_manager: DatabaseManager):
    """Реагирует на назначение админа или изменение его прав."""
    chat_id = event.chat.id
    chat_title = event.chat.title or f"Чат ID {chat_id}"
    new_admin_user = event.new_chat_member.user
    actor_user = event.from_user # Кто выполнил действие

    logger.info(f"[ADMIN_EVENT] В чате {chat_id} ('{chat_title}') изменился статус/права admin {new_admin_user.id} ({new_admin_user.full_name}). Инициатор: {actor_user.id}")

    # Если бота назначили админом
    bot_info = await bot.get_me()
    if new_admin_user.id == bot_info.id:
        logger.info(f"[ADMIN_EVENT] Меня ({bot_info.username}) назначили админом в чате {chat_id}. Добавляю чат в БД.")
        # Добавляем чат в БД, если его еще нет
        await db_manager.add_chat_if_not_exists(
            chat_id=chat_id,
            chat_title=chat_title,
            added_by_user_id=actor_user.id
        )
        # Отправляем приветственное сообщение с инструкцией
        try:
            await bot.send_message(
                chat_id,
                f"👋 Привет! Я готов к работе в чате {hbold(chat_title)}.\n"
                f"Администратор ({hlink(actor_user.first_name, f'tg://user?id={actor_user.id}')}) может теперь настроить меня.\n\n"
                f"➡️ Чтобы начать, получите код настройки в личных сообщениях со мной (@{bot_info.username}), используя команду /code, "
                f"а затем отправьте этот код сюда.",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.warning(f"[ADMIN_EVENT] Не удалось отправить приветствие в чат {chat_id}: {e}")
    else:
        # Если назначили другого пользователя админом
        # Можно отправить ему (или в чат) краткую инструкцию
        logger.debug(f"[ADMIN_EVENT] Статус пользователя {new_admin_user.id} изменен на админа в чате {chat_id}.")
        # Просто логируем, дальнейших действий не требуется по ТЗ
        pass

# --- Обработка разжалования (опционально) --- #
# @group_admin_router.chat_member(
#     ChatMemberUpdatedFilter(member_status_changed=IS_ADMIN >> IS_MEMBER)
# )
# async def on_admin_demoted(...):
#     ...

# --- Хендлеры --- #

# Добавление бота в админы или изменение его прав
@group_admin_router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=ADMINISTRATOR))
async def handle_admin_promotion_wrapper(event: types.ChatMemberUpdated, bot: Bot, db_manager: DatabaseManager, state: FSMContext):
    """Обрабатывает ситуацию, когда боту выдали права администратора."""
    # Логика может остаться прежней или быть адаптирована под новый флоу
    # Пока оставим как есть, но возможно, ее стоит объединить с flow через код
    # !!! ВНИМАНИЕ: Код ниже использует старый state.key(), его тоже нужно исправить !!!
    user_id_who_promoted = event.from_user.id
    bot_id = bot.id
    # Исправляем ключ FSM, chat_id должен быть ID чата, где произошло событие
    user_fsm_key = StorageKey(bot_id=bot_id, chat_id=event.chat.id, user_id=user_id_who_promoted)
    user_state = FSMContext(storage=state.storage, key=user_fsm_key)
    logger.info(f"[MY_CHAT_MEMBER] Бота повысили/понизили в админах в чате {event.chat.id}, инициатор {user_id_who_promoted}")
    # Логика ChannelManagementService.handle_admin_promotion закомментирована, возможно, ее нужно будет пересмотреть

# Обработка кода setup_{user_id} в группе
@group_admin_router.message(SetupCodeFilter())
async def handle_setup_code(message: types.Message, bot: Bot, db_manager: DatabaseManager, user_id_to_setup: int):
    """Обрабатывает код вида setup_{user_id}, отправленный в группу."""
    sender = message.from_user
    chat = message.chat
    chat_title = chat.title or f"ID {chat.id}"

    logger.info(f"Получен код настройки {message.text} в чате {chat.id} ('{chat_title}') от {sender.id} ({sender.username}). Целевой пользователь: {user_id_to_setup}")

    # Пытаемся удалить сообщение с кодом
    try: 
        await message.delete()
        logger.info(f"Сообщение с кодом {message.text} удалено из чата {chat.id}.")
    except TelegramAPIError as e:
        logger.warning(f"Не удалось удалить сообщение с кодом {message.text} из чата {chat.id}: {e}")

    # Проверяем, существует ли целевой пользователь
    target_user_db_info = await db_manager.get_user(user_id_to_setup)
    if not target_user_db_info:
        logger.warning(f"Целевой пользователь {user_id_to_setup} из кода не найден в БД.")
        # Можно отправить сообщение в группу, но лучше этого не делать, чтобы не спамить
        return

    # --- НОВАЯ ПРОВЕРКА: Чат уже активирован? ---
    chat_settings = await db_manager.get_chat_settings(chat.id)
    # Проверяем оба флага на всякий случай. Если хотя бы один True, считаем настроенным.
    if chat_settings and (chat_settings.get('is_activated', False) or chat_settings.get('setup_complete', False)):
        logger.info(f"Попытка повторной настройки уже активированного/настроенного чата {chat.id} ('{chat_title}') пользователем {sender.id}.")
        try:
            # Уведомляем пользователя, который отправил код
            await bot.send_message(
                sender.id,
                f"⚙️ Группа <b>{chat_title}</b> уже была настроена ранее.",
                parse_mode="HTML"
            )
            # Отправляем временное уведомление в саму группу
            try:
                sent_group_message = await bot.send_message(
                    chat.id,
                    f"ℹ️ Этот чат уже настроен. Используйте /channels для управления каналами."
                )
                # Запускаем задачу на удаление через 5 секунд
                asyncio.create_task(delete_message_after_delay(sent_group_message, 5))
            except Exception as e_group_send:
                 logger.warning(f"Не удалось отправить временное уведомление в группу {chat.id}: {e_group_send}")

        except TelegramForbiddenError:
             logger.warning(f"Не удалось отправить ЛС пользователю {sender.id} (бот заблокирован?), уведомляя о повторной настройке чата {chat.id}.")
        except Exception as e_notify:
            logger.warning(f"Не удалось уведомить о повторной настройке чата {chat.id}: {e_notify}")
        return # Прерываем дальнейшее выполнение
    # --- КОНЕЦ НОВОЙ ПРОВЕРКИ ---

    # Отправляем сообщение с подтверждением в ЛС целевому пользователю
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, настроить этот чат", callback_data=ConfirmSetupCallback(chat_id=chat.id, approve=True).pack())],
        [InlineKeyboardButton(text="❌ Нет, отмена", callback_data=ConfirmSetupCallback(chat_id=chat.id, approve=False).pack())]
    ])

    sender_mention = get_user_mention_html(sender) if sender else "Кто-то"
    text_to_pm = (
        f"{sender_mention} активировал код настройки для группы <b>{chat_title}</b>.\n\n"
        f"Хотите настроить проверку каналов для этой группы?"
    )

    try:
        await bot.send_message(user_id_to_setup, text_to_pm, reply_markup=keyboard, parse_mode="HTML")
        logger.info(f"Отправлен запрос подтверждения настройки пользователю {user_id_to_setup} для чата {chat.id}.")
    except TelegramForbiddenError:
        logger.warning(f"Не удалось отправить ЛС пользователю {user_id_to_setup} (бот заблокирован?). Чат {chat.id}.")
        # Сообщаем об ошибке в группу
        try:
             target_user_mention = get_user_mention_html(types.User(id=target_user_db_info['user_id'], first_name=target_user_db_info.get('first_name', 'User'), is_bot=False, username=target_user_db_info.get('username')))
             await bot.send_message(chat.id, f"Не удалось отправить запрос на настройку пользователю {target_user_mention}. Возможно, он заблокировал бота.", parse_mode="HTML")
        except Exception as group_send_err:
             logger.error(f"Не удалось отправить сообщение об ошибке блокировки в чат {chat.id}: {group_send_err}")
    except TelegramAPIError as e:
        logger.error(f"Ошибка API при отправке запроса подтверждения пользователю {user_id_to_setup} для чата {chat.id}: {e}")
        # Сообщаем об ошибке в группу
        try:
            target_user_mention = get_user_mention_html(types.User(id=target_user_db_info['user_id'], first_name=target_user_db_info.get('first_name', 'User'), is_bot=False, username=target_user_db_info.get('username')))
            await bot.send_message(chat.id, f"Произошла ошибка при отправке запроса пользователю {target_user_mention}. Попробуйте позже.", parse_mode="HTML")
        except Exception as group_send_err:
            logger.error(f"Не удалось отправить сообщение об ошибке API в чат {chat.id}: {group_send_err}")

# --- Вспомогательная функция для удаления сообщения с задержкой ---
async def delete_message_after_delay(message: types.Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await message.delete()
        logger.debug(f"Автоматически удалено сообщение {message.message_id} в чате {message.chat.id}")
    except Exception as e:
        logger.warning(f"Не удалось автоматически удалить сообщение {message.message_id} в чате {message.chat.id}: {e}")

# --- Управление каналами для уже настроенного чата ---

@group_admin_router.message(Command("channels"))
async def cmd_manage_channels(message: types.Message, bot: Bot, db_manager: DatabaseManager, state: FSMContext):
    """Обрабатывает команду /channels для управления списком каналов."""
    user = message.from_user
    chat = message.chat
    chat_title = chat.title or f"ID {chat.id}"

    # 0. Проверяем, есть ли чат в базе и завершена ли настройка
    chat_settings = await db_manager.get_chat_settings(chat.id)
    if not chat_settings:
        # Это не должно происходить, если бот добавлен/настроен, но на всякий случай
        logger.warning(f"Попытка /channels в чате {chat.id}, который не найден в БД.")
        await message.reply("😕 Не могу найти информацию об этом чате. Убедитесь, что я добавлен как администратор.")
        return
    if not chat_settings.get('setup_complete', False):
        logger.info(f"Попытка /channels в чате {chat.id}, который еще не настроен.")
        await message.reply(f"⚙️ Этот чат еще не настроен. Используйте команду /code в моих личных сообщениях (@{actual_bot_username}), а затем пришлите полученный код сюда для начала настройки.")
        return

    # 1. Проверяем, является ли пользователь администратором чата
    try:
        member = await bot.get_chat_member(chat_id=chat.id, user_id=user.id)
        if not isinstance(member, (types.ChatMemberOwner, types.ChatMemberAdministrator)):
            logger.warning(f"Пользователь {user.id} ({user.full_name}) попытался использовать /channels в чате {chat.id}, не будучи админом.")
            await message.reply("Эта команда доступна только администраторам чата.")
            return
        # Дополнительно проверяем право на управление чатом (invite_users), если нужно строже
        # if isinstance(member, types.ChatMemberAdministrator) and not member.can_invite_users:
        #     logger.warning(f"Администратор {user.id} попытался использовать /channels в чате {chat.id} без права 'invite_users'.")
        #     await message.reply("У вас недостаточно прав для управления настройками каналов.")
        #     return

    except TelegramAPIError as e:
        logger.error(f"Ошибка проверки статуса админа {user.id} в чате {chat.id}: {e}")
        await message.reply("Не удалось проверить ваши права администратора. Попробуйте позже.")
        return

    logger.info(f"Админ {user.id} ({user.full_name}) инициировал /channels в чате {chat.id} ('{chat_title}').")

    # 2. Удаляем команду из чата
    try:
        await message.delete()
    except TelegramAPIError as e:
        logger.warning(f"Не удалось удалить сообщение /channels из чата {chat.id}: {e}")

    # 3. Инициируем процесс управления в ЛС
    # Используем сервис для инкапсуляции логики
    # TODO: Создать ChannelManagementService или использовать существующий
    channel_mgmt_service = ChannelManagementService(bot, db_manager, state.storage) # Передаем storage для FSM
    await channel_mgmt_service.start_channel_management(
        target_chat_id=chat.id,
        target_chat_title=chat_title,
        admin_user_id=user.id
    )

# --- Остальные хендлеры FSM (перенесены или будут перенесены) ---

# Выбор канала через ChatShared (FSM) - ПЕРЕНЕСЕНО в fsm_private.py
# @group_admin_router.message(...)

# Неверный ввод при выборе канала (FSM) - ПЕРЕНЕСЕНО в fsm_private.py
# @group_admin_router.message(...)
# async def handle_wrong_channel_select_wrapper(...) 

# --- КОД ДЛЯ /RMChat ПЕРЕНЕСЕННЫЙ ИЗ group_messages.py ---

CONFIRM_DELETE_CHAT_CALLBACK_PREFIX = "confirm_delete_chat:"
CANCEL_DELETE_CHAT_CALLBACK_PREFIX = "cancel_delete_chat:"

async def is_chat_admin_for_message(message: types.Message, bot: Bot) -> bool:
    """Проверяет, является ли отправитель сообщения администратором или создателем чата."""
    if not message.from_user:
        return False
    try:
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except Exception as e:
        logger.warning(f"Ошибка при проверке статуса админа для user {message.from_user.id} в чате {message.chat.id}: {e}")
        return False

@group_admin_router.message(Command("rmchat"))
async def cmd_remove_chat_from_bot(message: types.Message, bot: Bot, db_manager: DatabaseManager):
    """Обрабатывает команду /rmchat для полного удаления данных чата. Подтверждение отправляется в ЛС."""
    chat_id = message.chat.id
    chat_title = message.chat.title or f"Чат {chat_id}"
    
    if not message.from_user: # Should not happen for user commands
        logger.error(f"Команда /rmchat получена без message.from_user в чате {chat_id}")
        return

    user_id = message.from_user.id
    user_name = message.from_user.full_name

    # Используем format_log_message, если он импортирован, или базовый логгер
    log_func = format_log_message if 'format_log_message' in globals() else lambda type, cid, ctitle, uid, uname, msg: f"[{type}] User {uid} ({uname}) in chat {cid} ({ctitle}): {msg}"
    
    logger.info(log_func("CMD_REMOVE_CHAT", chat_id, chat_title, user_id, user_name, "Получена команда"))

    if not await is_chat_admin_for_message(message, bot):
        logger.warning(log_func("CMD_REMOVE_CHAT", chat_id, chat_title, user_id, user_name, "Команда вызвана не админом. Игнорируется."))
        try:
            await message.delete() 
        except Exception:
            pass # Ignore if already deleted or no rights
        return

    # Пытаемся удалить исходное сообщение с командой /rmchat из группы
    try:
        await message.delete()
        logger.info(log_func("CMD_REMOVE_CHAT", chat_id, chat_title, user_id, user_name, "Сообщение с командой /rmchat удалено из группы."))
    except TelegramAPIError as e:
        logger.warning(log_func("CMD_REMOVE_CHAT", chat_id, chat_title, user_id, user_name, f"Не удалось удалить команду /rmchat из группы: {e}"))


    confirm_button = InlineKeyboardButton(
        text="🗑️ Да, удалить этот чат", 
        callback_data=f"{CONFIRM_DELETE_CHAT_CALLBACK_PREFIX}{chat_id}"
    )
    cancel_button = InlineKeyboardButton(
        text="❌ Нет, отмена", 
        callback_data=f"{CANCEL_DELETE_CHAT_CALLBACK_PREFIX}{chat_id}"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[confirm_button], [cancel_button]])

    warning_text_pm = (
        f"⚠️ {hbold('ВНИМАНИЕ!')} ⚠️\n\n"
        f"Вы собираетесь полностью удалить все данные чата \"{hbold(chat_title)}\" (ID: `{chat_id}`) из базы данных бота. "
        f"Это действие необратимо и приведет к тому, что бот покинет этот чат.\n\n"
        f"Нажмите \"Да, удалить этот чат\", чтобы подтвердить, или \"Нет, отмена\" для отмены."
    )
    
    try:
        await bot.send_message(
            user_id,
            warning_text_pm,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        logger.info(log_func("CMD_REMOVE_CHAT_PM_SENT", chat_id, chat_title, user_id, user_name, "Сообщение с подтверждением отправлено в ЛС."))
        
    except TelegramForbiddenError:
        logger.warning(log_func("CMD_REMOVE_CHAT_PM_FORBIDDEN", chat_id, chat_title, user_id, user_name, "Не удалось отправить ЛС (бот заблокирован)."))
        fallback_text_group = (
            f"❌ Не удалось отправить запрос на удаление чата \"{hbold(chat_title)}\" вам в личные сообщения ({get_user_mention_html(message.from_user)}).\n"
            f"Пожалуйста, убедитесь, что вы не заблокировали меня и начали диалог со мной (отправьте /start боту @{actual_bot_username})."
        )
        try:
            await bot.send_message(chat_id, fallback_text_group, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e_group_fallback:
            logger.error(log_func("CMD_REMOVE_CHAT_GROUP_FALLBACK_ERROR", chat_id, chat_title, user_id, user_name, f"Не удалось отправить fallback-сообщение в группу: {e_group_fallback}"))

    except Exception as e:
        logger.error(log_func("CMD_REMOVE_CHAT_PM_ERROR", chat_id, chat_title, user_id, user_name, f"Ошибка при отправке подтверждения в ЛС: {e}"), exc_info=True)
        error_feedback_group = f"❌ Произошла ошибка при отправке запроса на удаление чата \"{hbold(chat_title)}\" в личные сообщения. Попробуйте позже."
        try:
            await bot.send_message(chat_id, error_feedback_group, parse_mode="HTML")
        except Exception as e_group_err_send:
             logger.error(log_func("CMD_REMOVE_CHAT_GROUP_ERROR_SEND_ERROR", chat_id, chat_title, user_id, user_name, f"Не удалось отправить сообщение об ошибке в группу: {e_group_err_send}"))


@group_admin_router.callback_query(F.data.startswith(CONFIRM_DELETE_CHAT_CALLBACK_PREFIX))
async def handle_confirm_delete_chat_callback(callback_query: types.CallbackQuery, bot: Bot, db_manager: DatabaseManager):
    """Обрабатывает подтверждение удаления чата (сообщение в ЛС)."""
    chat_id_to_delete = int(callback_query.data.split(":")[1])
    requesting_user_id = callback_query.from_user.id
    user_name = callback_query.from_user.full_name
    
    # Получаем актуальное название чата для логов и сообщений
    group_chat_title_for_log = f"Чат {chat_id_to_delete}" # Default
    try:
        group_chat_info = await bot.get_chat(chat_id_to_delete)
        if group_chat_info and group_chat_info.title:
            group_chat_title_for_log = group_chat_info.title
    except Exception as e_get_chat:
        logger.warning(f"Не удалось получить имя чата {chat_id_to_delete} для лога: {e_get_chat}")

    log_func = format_log_message if 'format_log_message' in globals() else lambda type, cid, ctitle, uid, uname, msg: f"[{type}] User {uid} ({uname}) in chat {cid} ('{ctitle}'): {msg}"

    try:
        member = await bot.get_chat_member(chat_id_to_delete, requesting_user_id) # Проверяем права в ЦЕЛЕВОМ чате
        if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
            await callback_query.answer("Это действие доступно только администраторам чата, который вы пытаетесь удалить.", show_alert=True)
            logger.warning(log_func("CALLBACK_CONFIRM_DELETE", chat_id_to_delete, group_chat_title_for_log, requesting_user_id, user_name, "Попытка подтвердить удаление не админом целевого чата."))
            # Возможно, стоит изменить текст сообщения в ЛС, чтобы указать, что прав больше нет
            await callback_query.message.edit_text(f"❌ Отказано в доступе. Вы больше не являетесь администратором чата \"{hbold(group_chat_title_for_log)}\". Удаление отменено.", parse_mode="HTML")
            return
    except Exception as e_perm_check:
        logger.error(log_func("CALLBACK_CONFIRM_DELETE_PERM_ERROR", chat_id_to_delete, group_chat_title_for_log, requesting_user_id, user_name, f"Ошибка проверки прав: {e_perm_check}"), exc_info=True)
        await callback_query.answer("Ошибка проверки прав. Попробуйте позже.", show_alert=True)
        await callback_query.message.edit_text(f"🛠 Произошла ошибка при проверке ваших прав для чата \"{hbold(group_chat_title_for_log)}\". Попробуйте инициировать удаление заново.", parse_mode="HTML")
        return

    # Логируем перед основным действием
    logger.info(log_func("CALLBACK_CONFIRM_DELETE_INITIATED", chat_id_to_delete, group_chat_title_for_log, requesting_user_id, user_name, "Подтверждение удаления получено и права проверены."))

    original_message_id = callback_query.message.message_id if callback_query.message else None

    try:
        # Сначала пытаемся отредактировать сообщение в ЛС, затем удаляем из БД и выходим из чата
        edit_success = False
        pre_leave_message_text = f"⏳ Идет удаление чата \"{hbold(group_chat_title_for_log)}\" (ID: `{chat_id_to_delete}`)..."
        if callback_query.message: # Убедимся, что сообщение существует
            try:
                await callback_query.message.edit_text(pre_leave_message_text, parse_mode="HTML")
                edit_success = True
            except Exception as e_edit_pre:
                logger.warning(log_func("CALLBACK_CONFIRM_DELETE_EDIT_PRE_LEAVE_ERROR", chat_id_to_delete, group_chat_title_for_log, requesting_user_id, user_name, f"Не удалось предварительно отредактировать ЛС (msg_id: {original_message_id}): {e_edit_pre}"))
        else:
            logger.warning(log_func("CALLBACK_CONFIRM_DELETE_NO_MESSAGE_TO_EDIT_PRE", chat_id_to_delete, group_chat_title_for_log, requesting_user_id, user_name, "Нет callback_query.message для предварительного редактирования."))

        deleted_from_db = await db_manager.delete_chat(chat_id_to_delete)
        
        final_message_text = ""
        # bot_left_chat_successfully = False # Не используется далее, можно убрать

        if deleted_from_db:
            logger.info(log_func("CHAT_DELETED_DB", chat_id_to_delete, group_chat_title_for_log, requesting_user_id, user_name, "Чат успешно удален из БД."))
            final_message_text = f"✅ Чат \"{hbold(group_chat_title_for_log)}\" (ID: `{chat_id_to_delete}`) успешно удален из базы данных."
            try:
                await bot.leave_chat(chat_id_to_delete)
                logger.info(log_func("BOT_LEFT_CHAT", chat_id_to_delete, group_chat_title_for_log, requesting_user_id, user_name, "Бот успешно покинул чат."))
                final_message_text += " Бот также покинул этот чат."
                # bot_left_chat_successfully = True
            except TelegramForbiddenError:
                logger.warning(log_func("BOT_LEFT_CHAT_FORBIDDEN", chat_id_to_delete, group_chat_title_for_log, requesting_user_id, user_name, 
                                              "Бот не смог покинуть чат (недостаточно прав или уже удален/забанен)."))
                final_message_text += " Бот не смог покинуть чат (возможно, у него нет прав или он уже удален/забанен)."
            except Exception as e_leave: # Другие ошибки при выходе из чата
                logger.error(log_func("BOT_LEFT_CHAT_ERROR", chat_id_to_delete, group_chat_title_for_log, requesting_user_id, user_name, f"Ошибка при выходе из чата: {e_leave}"))
                final_message_text += f" Произошла ошибка при попытке бота покинуть чат: {str(e_leave)[:100]}."
        else:
            logger.error(log_func("CHAT_DELETE_DB_FAILED", chat_id_to_delete, group_chat_title_for_log, requesting_user_id, user_name, "Не удалось удалить чат из БД (метод вернул False)."))
            final_message_text = f"❌ Произошла ошибка при удалении чата \"{hbold(group_chat_title_for_log)}\" из базы данных. Пожалуйста, проверьте логи."

        if edit_success and callback_query.message: # Если предварительное редактирование было успешно и сообщение существует
            try:
                await callback_query.message.edit_text(final_message_text, parse_mode="HTML")
            except Exception as e_edit_final:
                logger.error(log_func("CALLBACK_CONFIRM_DELETE_EDIT_FINAL_ERROR", chat_id_to_delete, group_chat_title_for_log, requesting_user_id, user_name, f"Не удалось отредактировать ЛС (msg_id: {original_message_id}) финальным текстом: {e_edit_final}"))
                # Если редактирование не удалось, пытаемся отправить новое сообщение
                try:
                    await bot.send_message(requesting_user_id, final_message_text, parse_mode="HTML")
                except Exception as e_send_final_fallback:
                    logger.error(log_func("CALLBACK_CONFIRM_DELETE_SEND_FINAL_FALLBACK_ERROR", chat_id_to_delete, group_chat_title_for_log, requesting_user_id, user_name, f"Не удалось отправить финальное ЛС после неудачного edit_final: {e_send_final_fallback}"))
        else: # Если предварительное редактирование не удалось или нет сообщения
            try:
                await bot.send_message(requesting_user_id, final_message_text, parse_mode="HTML")
                logger.info(log_func("CALLBACK_CONFIRM_DELETE_SEND_FINAL_NEW_MSG", chat_id_to_delete, group_chat_title_for_log, requesting_user_id, user_name, "Отправлено новое ЛС с финальным результатом."))
            except Exception as e_send_final:
                 logger.error(log_func("CALLBACK_CONFIRM_DELETE_SEND_FINAL_ERROR_NO_PRE_EDIT", chat_id_to_delete, group_chat_title_for_log, requesting_user_id, user_name, f"Не удалось отправить финальное ЛС (не было pre-edit или callback_query.message): {e_send_final}"))
        
        await callback_query.answer()

    except Exception as e:
        logger.error(log_func("CALLBACK_CONFIRM_DELETE_UNHANDLED_ERROR", chat_id_to_delete, group_chat_title_for_log, requesting_user_id, user_name, f"Непредвиденная ошибка при обработке подтверждения удаления: {e}"), exc_info=True)
        try:
            # Пытаемся отправить или отредактировать сообщение об общей ошибке
            error_message_text = f"❌ Произошла непредвиденная ошибка при удалении чата \"{hbold(group_chat_title_for_log)}\". ID чата: `{chat_id_to_delete}`."
            if callback_query.message:
                try:
                    await callback_query.message.edit_text(error_message_text, parse_mode="HTML")
                except Exception as e_edit_fallback_error:
                    logger.warning(log_func("CALLBACK_CONFIRM_DELETE_EDIT_FALLBACK_ERROR", chat_id_to_delete, group_chat_title_for_log, requesting_user_id, user_name, f"Не удалось отредактировать ЛС сообщением об общей ошибке: {e_edit_fallback_error}"))
                    await bot.send_message(requesting_user_id, error_message_text, parse_mode="HTML") # Fallback to send
            else:
                 await bot.send_message(requesting_user_id, error_message_text, parse_mode="HTML")
        except Exception as e_send_fallback_error_outer:
            logger.error(log_func("CALLBACK_CONFIRM_DELETE_SEND_FALLBACK_ERROR_OUTER", chat_id_to_delete, group_chat_title_for_log, requesting_user_id, user_name, f"Не удалось отправить/отредактировать ЛS c общей ошибкой: {e_send_fallback_error_outer}"))
        await callback_query.answer("Ошибка при удалении чата", show_alert=True)


@group_admin_router.callback_query(F.data.startswith(CANCEL_DELETE_CHAT_CALLBACK_PREFIX))
async def handle_cancel_delete_chat_callback(callback_query: types.CallbackQuery, bot: Bot):
    """Обрабатывает отмену удаления чата (сообщение в ЛС)."""
    requesting_user_id = callback_query.from_user.id
    chat_id_from_callback = int(callback_query.data.split(":")[1]) # ID группы, для которой отменяется удаление
    user_name = callback_query.from_user.full_name

    # Получаем актуальное название чата для логов и сообщений
    group_chat_title_for_log = f"Чат {chat_id_from_callback}" # Default
    try:
        group_chat_info = await bot.get_chat(chat_id_from_callback)
        if group_chat_info and group_chat_info.title:
            group_chat_title_for_log = group_chat_info.title
    except Exception as e_get_chat:
        logger.warning(f"Не удалось получить имя чата {chat_id_from_callback} для лога отмены: {e_get_chat}")
        
    log_func = format_log_message if 'format_log_message' in globals() else lambda type, cid, ctitle, uid, uname, msg: f"[{type}] User {uid} ({uname}) in chat {cid} ('{ctitle}'): {msg}"

    logger.info(log_func("CALLBACK_CANCEL_DELETE", chat_id_from_callback, group_chat_title_for_log, requesting_user_id, user_name, f"Отмена удаления чата {chat_id_from_callback}."))

    # Проверка прав не обязательна для отмены, но можно оставить для консистентности или если есть опасения
    try:
        member = await bot.get_chat_member(chat_id_from_callback, requesting_user_id) # Проверяем права в ЦЕЛЕВОМ чате
        if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]:
            await callback_query.answer("Вы больше не администратор этого чата.", show_alert=True)
            # Не меняем текст сообщения, так как пользователь мог нажать отмену именно из-за потери прав
            return 
    except Exception:
        # Если не удалось проверить права, все равно позволяем отменить
        pass 
        
    await callback_query.message.edit_text(f"✅ Удаление чата \"{hbold(group_chat_title_for_log)}\" (ID: `{chat_id_from_callback}`) отменено.", parse_mode="HTML")
    await callback_query.answer("Удаление отменено")

# --- КОНЕЦ КОДА ДЛЯ /RMChat --- 