"""
Обработчики состояний FSM, ожидаемых в личном чате с ботом.

Содержит:
- Обработка подтверждения настройки чата (владелец/не владелец).
- Обработка управления списком каналов (через /chats или после настройки).
"""
import logging
from aiogram import Router, Bot, F, types
from aiogram.enums import ChatType, ContentType
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramAPIError
from typing import List, Dict

# Используем абсолютные импорты
from bot.db.database import DatabaseManager
from bot.states import ManageChannels # Activation больше не нужен
from bot.services.channel_mgmt import ChannelManagementService
# from bot.services.subscription import SubscriptionService # Не используется здесь
from bot.bot_instance import bot, db_manager
from bot.middlewares.db_middleware import DbSessionMiddleware
from bot.middlewares.bot_middleware import BotMiddleware
from aiogram.utils.keyboard import InlineKeyboardBuilder
# Импортируем CallbackData
from bot.data.callback_data import ConfirmSetupCallback, ManageSpecificChatCallback, OwnerActivationChoiceCallback, DirectAdminSetupCallback
from bot.config import BOT_OWNER_ID, BOT_OWNER_USERNAME
from bot.utils.helpers import get_user_mention_html # Для упоминания пользователя

logger = logging.getLogger(__name__)
fsm_private_router = Router()

# Регистрируем middleware
fsm_private_router.message.middleware.register(DbSessionMiddleware(db_manager))
fsm_private_router.callback_query.middleware.register(DbSessionMiddleware(db_manager))
fsm_private_router.message.middleware.register(BotMiddleware(bot))
fsm_private_router.callback_query.middleware.register(BotMiddleware(bot))

# Фильтр на тип чата (личный)
fsm_private_router.message.filter(F.chat.type == ChatType.PRIVATE)
fsm_private_router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)

# --- Обработчики FSM и коллбэков в ЛС --- #

# --- Обработчик кнопки "Управлять" из /chats --- #
@fsm_private_router.callback_query(ManageSpecificChatCallback.filter())
async def handle_manage_specific_chat(query: types.CallbackQuery, callback_data: ManageSpecificChatCallback, bot: Bot, db_manager: DatabaseManager, state: FSMContext):
    """Обрабатывает нажатие кнопки 'Управлять' из списка /chats."""
    user = query.from_user
    chat_id_to_manage = callback_data.chat_id

    logger.info(f"[MYCHATS_CB] Пользователь {user.id} нажал 'Управлять' для чата {chat_id_to_manage}")

    chat_title = f"ID {chat_id_to_manage}"
    try:
        chat_info = await bot.get_chat(chat_id_to_manage)
        chat_title = chat_info.title or chat_title
    except TelegramAPIError as e:
        logger.warning(f"[MYCHATS_CB] Не удалось получить title для чата {chat_id_to_manage} при управлении: {e}")

    channel_mgmt_service = ChannelManagementService(bot, db_manager, state.storage)
    try:
        # Запускаем FSM управления каналами
        await channel_mgmt_service.start_channel_management(
            target_chat_id=chat_id_to_manage,
            target_chat_title=chat_title,
            admin_user_id=user.id
        )
        await query.answer()
    except Exception as e:
        logger.error(f"[MYCHATS_CB] Ошибка при запуске управления каналами для chat={chat_id_to_manage} user={user.id}: {e}", exc_info=True)
        await state.clear()
        try:
            await query.answer("Произошла ошибка при запуске управления каналами.", show_alert=True)
        except TelegramAPIError: pass

# Нажатие кнопки "Да, настроить этот чат" (из ЛС, после /code -> setup_...)
@fsm_private_router.callback_query(ConfirmSetupCallback.filter(F.approve == True))
async def handle_confirm_setup(query: types.CallbackQuery, callback_data: ConfirmSetupCallback, bot: Bot, db_manager: DatabaseManager, state: FSMContext):
    """Обрабатывает подтверждение настройки чата из ЛС."""
    user = query.from_user
    chat_id_to_setup = callback_data.chat_id

    logger.info(f"Пользователь {user.id} подтвердил настройку чата {chat_id_to_setup} (approve=True).")

    chat_title_display = f"ID {chat_id_to_setup}"
    chat_title_for_fsm_and_logs = f"Чат ID {chat_id_to_setup}"
    try:
        chat_info = await bot.get_chat(chat_id_to_setup)
        chat_title_for_fsm_and_logs = chat_info.title or chat_title_for_fsm_and_logs
        chat_title_display = chat_info.title or chat_title_display # Для сообщений пользователям
    except TelegramAPIError as e:
        logger.warning(f"Не удалось получить title для чата {chat_id_to_setup} при подтверждении: {e}")

    # --- Логика для ВЛАДЕЛЬЦА БОТА ---
    # --- !!! ОТЛАДОЧНЫЙ ЛОГ !!! ---
    logger.debug(f"[CONFIRM_SETUP_OWNER_CHECK] Сравнение ID: user.id={user.id} (тип: {type(user.id)}) vs BOT_OWNER_ID={BOT_OWNER_ID} (тип: {type(BOT_OWNER_ID)}). Результат: {user.id == BOT_OWNER_ID}")
    # --- !!! КОНЕЦ ОТЛАДОЧНОГО ЛОГА !!! ---
    
    if user.id == BOT_OWNER_ID:
        logger.info(f"Владелец {user.id} подтвердил настройку чата {chat_id_to_setup}. Автоматическая активация и переход к настройке каналов.")
        try:
            await db_manager.activate_chat_for_owner(chat_id_to_setup, user.id)
            owner_message_text = (
                f"✅ Чат <b>{chat_title_display}</b> был автоматически активирован, так как вы владелец бота.\n\n"
                f"Теперь вы можете настроить каналы для проверки подписки."
            )
            # Редактируем сообщение, чтобы убрать кнопки подтверждения
            await query.message.edit_text(owner_message_text, parse_mode="HTML", reply_markup=None)
        except Exception as e:
            logger.error(f"Ошибка при автоматической активации чата {chat_id_to_setup} владельцем {user.id}: {e}", exc_info=True)
            error_text = f"Произошла ошибка при автоматической активации чата <b>{chat_title_display}</b>. Пожалуйста, проверьте логи."
            try:
                # Пытаемся отредактировать сообщение с ошибкой
                await query.message.edit_text(error_text, parse_mode="HTML", reply_markup=None)
            except TelegramAPIError: pass # Если не вышло, не страшно
            await state.clear()
            await query.answer("Ошибка автоматической активации.", show_alert=True)
            return

        # Владелец переходит к настройке каналов
        logger.info(f"Владелец {user.id} приступает к настройке каналов для чата {chat_id_to_setup} после авто-активации.")
        channel_mgmt_service = ChannelManagementService(bot, db_manager, state.storage)
        try:
            # start_channel_management отправит новое сообщение с интерфейсом управления.
            await channel_mgmt_service.start_channel_management(
                target_chat_id=chat_id_to_setup,
                target_chat_title=chat_title_for_fsm_and_logs,
                admin_user_id=user.id # Владелец сам себе настраивает
            )
            await query.answer() # Отвечаем на коллбэк "Да, настроить"
        except Exception as e:
            logger.error(f"[FSM_CHANNEL_OWNER] Ошибка запуска FSM управления каналами для владельца {user.id}, чат {chat_id_to_setup}: {e}", exc_info=True)
            await state.clear()
            try:
                await query.answer("Ошибка запуска настройки каналов.", show_alert=True)
            except TelegramAPIError: pass
        return # Завершаем для владельца

    # --- Логика для НЕ-владельцев ---
    logger.info(f"Администратор {user.id} ({user.full_name}) запросил настройку чата {chat_id_to_setup} ('{chat_title_display}'). Уведомляем владельца.")

    admin_contact_link = f"<a href=\"https://t.me/{BOT_OWNER_USERNAME}\">@{BOT_OWNER_USERNAME}</a>" if BOT_OWNER_USERNAME else "владельцем бота"

    admin_message_text = (
        f"⏳ Ваш запрос на настройку и активацию чата <b>{chat_title_display}</b> отправлен владельцу бота.\n\n"
        f"Свяжитесь с владельцем для активации доступа {admin_contact_link}."
    )
    try:
        # Редактируем сообщение админа, убирая кнопки Да/Нет
        await query.message.edit_text(admin_message_text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=None)
    except TelegramAPIError as e:
        logger.warning(f"Не удалось обновить сообщение для админа {user.id} о передаче запроса владельцу: {e}")

    # Уведомляем владельца
    if BOT_OWNER_ID:
        try:
            # Получаем HTML-упоминание админа
            admin_mention_html = get_user_mention_html(user)

            owner_notification_text = (
                f"🔔 Пользователь {admin_mention_html} (<code>{user.id}</code>) "
                f"запрашивает настройку и активацию для чата <b>{chat_title_display}</b> (ID: <code>{chat_id_to_setup}</code>)."
            )

            builder = InlineKeyboardBuilder()
            # Кнопка 1: Просто активировать и дать владельцу настроить каналы
            builder.button(
                text="✅ Настроить и активировать",
                callback_data=OwnerActivationChoiceCallback(action="approve", target_user_id=user.id, target_chat_id=chat_id_to_setup)
            )
            # Кнопка 2: Активировать и запустить FSM для выдачи временного доступа админу
            builder.button(
                text="🔑 Активировать и выдать доступ",
                callback_data=OwnerActivationChoiceCallback(action="approve_grant", target_user_id=user.id, target_chat_id=chat_id_to_setup)
            )
            # Кнопка 3: Отклонить запрос
            builder.button(
                text="❌ Отклонить запрос",
                callback_data=OwnerActivationChoiceCallback(action="reject", target_user_id=user.id, target_chat_id=chat_id_to_setup)
            )
            builder.adjust(1) # Кнопки одна под другой

            await bot.send_message(
                BOT_OWNER_ID,
                owner_notification_text,
                parse_mode="HTML",
                reply_markup=builder.as_markup(),
                disable_web_page_preview=True
            )
            logger.info(f"Владельцу {BOT_OWNER_ID} отправлено уведомление о запросе от {user.id} для чата {chat_id_to_setup}.")

        except Exception as e_owner:
            logger.error(f"Не удалось отправить уведомление владельцу ({BOT_OWNER_ID}) о запросе активации от {user.id} для чата {chat_id_to_setup}: {e_owner}", exc_info=True)
            # Сообщить админу об ошибке отправки запроса владельцу
            try:
                 await bot.send_message(user.id, "Произошла ошибка при отправке вашего запроса владельцу. Попробуйте позже или свяжитесь с ним напрямую.")
            except Exception: pass # Игнорируем ошибку отправки админу
    else:
        logger.warning("BOT_OWNER_ID не настроен. Невозможно уведомить владельца о запросе на активацию.")
        # Сообщить админу, что владелец не настроен и активация невозможна
        try:
             await bot.send_message(user.id, "Владелец бота не настроен в конфигурации. Автоматическая активация через него невозможна.")
        except Exception: pass # Игнорируем ошибку отправки админу

    await query.answer("Запрос отправлен владельцу.")
    # Очищаем состояние админа, так как он теперь просто ждет решения владельца
    await state.clear()
    return # Завершаем для не-владельца

# Нажатие кнопки "Нет, отмена" (когда ConfirmSetupCallback был с approve=False)
# Этот обработчик теперь будет срабатывать на кнопку "Нет, отмена" из group_admin.py
@fsm_private_router.callback_query(ConfirmSetupCallback.filter(F.approve == False))
async def handle_cancel_setup_button(query: types.CallbackQuery, callback_data: ConfirmSetupCallback, state: FSMContext):
    """Обрабатывает отмену настройки на этапе подтверждения."""
    user_id = query.from_user.id
    chat_id_to_cancel = callback_data.chat_id
    logger.info(f"Пользователь {user_id} отменил настройку чата {chat_id_to_cancel} (approve=False).")
    await state.clear() # Очищаем состояние на всякий случай
    try:
        await query.message.edit_text("Настройка чата отменена.", reply_markup=None)
    except TelegramAPIError as e:
        logger.warning(f"Не удалось отредактировать сообщение отмены для user={user_id}: {e}")
    await query.answer("Настройка отменена.")


# --- СТАРАЯ ЛОГИКА АКТИВАЦИИ ПО КОДУ УДАЛЕНА ---


# --- Обработчики FSM для добавления/выбора канала --- #

# Выбор канала через ChatShared (состояние adding_channel)
@fsm_private_router.message(
    ManageChannels.adding_channel,
    F.content_type == ContentType.CHAT_SHARED
)
async def handle_channel_select_adding(message: types.Message, bot: Bot, db_manager: DatabaseManager, state: FSMContext):
    """Обрабатывает выбор канала через forwarded CHAT_SHARED в ЛС при добавлении нового канала."""
    channel_mgmt_service = ChannelManagementService(bot, db_manager, state.storage)
    await channel_mgmt_service.handle_channel_select(message, state)

# Обработка неверного ввода при добавлении канала
@fsm_private_router.message(
    ManageChannels.adding_channel,
    ~F.content_type == ContentType.CHAT_SHARED
)
async def handle_wrong_channel_select_adding(message: types.Message, bot: Bot, db_manager: DatabaseManager, state: FSMContext):
    """Обрабатывает неверный ввод при добавлении нового канала."""
    channel_mgmt_service = ChannelManagementService(bot, db_manager, state.storage)
    await channel_mgmt_service.handle_wrong_channel_select(message, state)

# --- Обработчики кнопок интерфейса управления (состояние managing_list) ---

# Кнопка "➕ Добавить канал"
@fsm_private_router.callback_query(ManageChannels.managing_list, F.data == "mng:add_channel")
async def handle_add_channel_button(query: types.CallbackQuery, state: FSMContext, bot: Bot, db_manager: DatabaseManager):
    """Обработка кнопки 'Добавить канал'. Запрашивает выбор канала."""
    user_id = query.from_user.id
    logger.info(f"[MGMT_CB] user={user_id} нажал 'Добавить канал'")
    channel_mgmt_service = ChannelManagementService(bot, db_manager, state.storage)
    try:
        state_data = await state.get_data()
        target_chat_id = state_data.get('target_chat_id')
        if not target_chat_id:
            logger.error(f"[MGMT_CB] Нет target_chat_id в state при добавлении канала user={user_id}")
            await query.answer("Ошибка: не найден ID чата. Начните сначала.", show_alert=True)
            await state.clear()
            return

        await state.set_state(ManageChannels.adding_channel)
        # _ask_channel_selection отправит новое сообщение с ReplyKeyboard
        await channel_mgmt_service._ask_channel_selection(user_id, target_chat_id, query.message)
        await query.answer()

    except Exception as e:
        logger.error(f"[MGMT_CB] Ошибка при обработке 'Добавить канал' user={user_id}: {e}", exc_info=True)
        await query.answer("Произошла ошибка при попытке добавить канал.", show_alert=True)
        try:
            await state.set_state(ManageChannels.managing_list)
            await channel_mgmt_service.update_management_interface(user_id, state)
        except:
            await state.clear()

# Кнопка "➖ Удалить 'Канал'"
@fsm_private_router.callback_query(ManageChannels.managing_list, F.data.startswith("mng:remove_start:"))
async def handle_remove_channel_button(query: types.CallbackQuery, state: FSMContext, bot: Bot, db_manager: DatabaseManager):
    """Обработка кнопки 'Удалить канал'. Удаляет канал из state и обновляет интерфейс."""
    user_id = query.from_user.id
    try:
        channel_id_to_remove = int(query.data.split(":")[-1])
    except (IndexError, ValueError):
        logger.error(f"[MGMT_CB] Неверный формат callback_data для удаления: {query.data} user={user_id}")
        await query.answer("Ошибка: неверный ID канала для удаления.")
        return

    logger.info(f"[MGMT_CB] user={user_id} нажал 'Удалить канал' ID={channel_id_to_remove}")
    channel_mgmt_service = ChannelManagementService(bot, db_manager, state.storage)
    try:
        state_data = await state.get_data()
        current_channels: List[Dict] = state_data.get('current_channels', [])
        target_chat_id = state_data.get('target_chat_id')

        removed_channel_title = f"ID {channel_id_to_remove}"
        new_channels_list = []
        found = False
        for ch_data in current_channels:
            if ch_data['id'] == channel_id_to_remove:
                removed_channel_title = ch_data.get('title', removed_channel_title)
                found = True
            else:
                new_channels_list.append(ch_data)

        if found:
            await state.update_data(current_channels=new_channels_list)
            logger.info(f"[MGMT_CB] Канал {channel_id_to_remove} ('{removed_channel_title}') временно удален user={user_id}, chat={target_chat_id}")
            await query.answer(f"Канал '{removed_channel_title}' удален из временного списка.")
            # Обновляем интерфейс
            await channel_mgmt_service.update_management_interface(user_id, state)
        else:
            logger.warning(f"[MGMT_CB] Канал {channel_id_to_remove} не найден в state для удаления user={user_id}, chat={target_chat_id}")
            await query.answer("Этот канал уже был удален.", show_alert=True)
            # На всякий случай обновим интерфейс
            await channel_mgmt_service.update_management_interface(user_id, state)

    except Exception as e:
        logger.error(f"[MGMT_CB] Ошибка при удалении канала {channel_id_to_remove} user={user_id}: {e}", exc_info=True)
        await query.answer("Произошла ошибка при удалении канала.", show_alert=True)
        try: await channel_mgmt_service.update_management_interface(user_id, state)
        except: pass

# Кнопка "✅ Готово"
@fsm_private_router.callback_query(ManageChannels.managing_list, F.data == "mng:finish")
async def handle_finish_button(query: types.CallbackQuery, state: FSMContext, bot: Bot, db_manager: DatabaseManager):
    """Обработка кнопки 'Готово'. Сохраняет изменения в БД."""
    user_id = query.from_user.id
    logger.info(f"[MGMT_CB] user={user_id} нажал 'Готово'")
    channel_mgmt_service = ChannelManagementService(bot, db_manager, state.storage)
    await channel_mgmt_service.handle_finish_channel_management(query, state)

# --- НОВЫЙ ОБРАБОТЧИК: Админ нажимает кнопку "Настроить каналы" после одобрения владельцем ---
@fsm_private_router.callback_query(DirectAdminSetupCallback.filter())
async def handle_direct_admin_setup_button(query: types.CallbackQuery, callback_data: DirectAdminSetupCallback, bot: Bot, db_manager: DatabaseManager, state: FSMContext):
    """Обрабатывает нажатие кнопки 'Настроить каналы' администратором после одобрения чата владельцем."""
    user_who_clicked = query.from_user
    target_chat_id = callback_data.chat_id
    expected_admin_id = callback_data.admin_id

    logger.info(f"[DIRECT_ADMIN_SETUP_CB] Пользователь {user_who_clicked.id} нажал 'Настроить каналы' для чата {target_chat_id}. Ожидаемый admin_id: {expected_admin_id}.")

    # Проверка безопасности: тот ли админ нажал кнопку?
    if user_who_clicked.id != expected_admin_id:
        logger.warning(f"[DIRECT_ADMIN_SETUP_CB] Несовпадение ID! Кнопку нажал {user_who_clicked.id}, а ожидался {expected_admin_id} для чата {target_chat_id}.")
        await query.answer("Эта кнопка предназначена для другого администратора.", show_alert=True)
        return

    chat_title_for_fsm = f"ID {target_chat_id}"
    try:
        chat_info = await bot.get_chat(target_chat_id)
        chat_title_for_fsm = chat_info.title or chat_title_for_fsm
    except TelegramAPIError as e:
        logger.warning(f"[DIRECT_ADMIN_SETUP_CB] Не удалось получить title для чата {target_chat_id}: {e}")

    channel_mgmt_service = ChannelManagementService(bot, db_manager, state.storage)
    try:
        await query.message.edit_text("Перехожу к настройке каналов...", reply_markup=None) # Убираем кнопку
        await channel_mgmt_service.start_channel_management(
            target_chat_id=target_chat_id,
            target_chat_title=chat_title_for_fsm,
            admin_user_id=user_who_clicked.id
        )
        await query.answer() # Отвечаем на исходный коллбэк
    except Exception as e:
        logger.error(f"[DIRECT_ADMIN_SETUP_CB] Ошибка при запуске управления каналами для чата {target_chat_id} админом {user_who_clicked.id}: {e}", exc_info=True)
        await state.clear()
        try:
            await query.answer("Произошла ошибка при запуске настройки каналов.", show_alert=True)
        except TelegramAPIError: pass
        # Можно также попробовать отредактировать сообщение обратно, если что-то пошло не так
        try:
            await query.message.edit_text("Не удалось запустить настройку. Попробуйте снова позже.")
        except TelegramAPIError: pass