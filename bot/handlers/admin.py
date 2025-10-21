import logging
import json
from aiogram import Router, Bot, F, types
from aiogram.filters import Command
from aiogram.enums import ChatType
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.database import DatabaseManager
# Импорт сервисов
from bot.services.channel_mgmt import ChannelManagementService
from bot.bot_instance import bot, db_manager
from bot.middlewares.db_middleware import DbSessionMiddleware
from bot.middlewares.bot_middleware import BotMiddleware
from bot.utils.helpers import is_admin
from typing import Optional 

logger = logging.getLogger(__name__)
admin_router = Router()

# Регистрируем middleware
admin_router.message.middleware.register(DbSessionMiddleware(db_manager))
admin_router.callback_query.middleware.register(DbSessionMiddleware(db_manager))

admin_router.message.middleware.register(BotMiddleware(bot))
admin_router.callback_query.middleware.register(BotMiddleware(bot))

# Ограничиваем команды только для групповых чатов
admin_router.message.filter(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))

# --- Хелпер для проверки прав админа ---
async def check_admin_permissions(message: types.Message, bot: Bot) -> bool:
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Эта команда доступна только администраторам чата.")
        return False
    return True

# --- Команды управления каналами ---

# --- Команды переключения настроек ---

@admin_router.message(Command("captcha"))
async def toggle_captcha_command(message: types.Message, bot: Bot, db_manager: DatabaseManager):
    if not await check_admin_permissions(message, bot):
        return

    chat_id = message.chat.id
    new_state = await db_manager.toggle_setting(chat_id, 'captcha_enabled')
    if new_state is not None:
        status = "включена" if new_state else "выключена"
        await message.reply(f"✅ Проверка капчей для новых пользователей теперь {status}.")
    else:
        await message.reply("❌ Произошла ошибка при изменении настройки.")

@admin_router.message(Command("subcheck"))
async def toggle_sub_check_command(message: types.Message, bot: Bot, db_manager: DatabaseManager):
    if not await check_admin_permissions(message, bot):
        return

    chat_id = message.chat.id
    new_state = await db_manager.toggle_setting(chat_id, 'subscription_check_enabled')
    if new_state is not None:
        status = "включена" if new_state else "выключена"
        await message.reply(f"✅ Проверка подписки на каналы теперь {status}.")
    else:
        await message.reply("❌ Произошла ошибка при изменении настройки.")

# --- Обработчики для предоставления доступа владельцем ---
from aiogram.fsm.context import FSMContext
from bot.states import OwnerGrantAccessStates # Импортируем состояния
from bot.data.callback_data import OwnerGrantAccessCallback, OwnerActivationChoiceCallback, DirectAdminSetupCallback # Импортируем CallbackData
from bot.config import BOT_OWNER_ID # Для проверки, что это действительно владелец
import time

# Фильтр, чтобы эти хэндлеры срабатывали только для владельца бота и в ЛС
# owner_only_private_filter = (F.chat.type == ChatType.PRIVATE) & (F.from_user.id == BOT_OWNER_ID) # Старый фильтр

# Новая отладочная функция-фильтр для CallbackQuery
async def owner_only_private_filter_debug_cq(query: types.CallbackQuery) -> bool:
    user_id = query.from_user.id
    
    if not query.message or not query.message.chat:
        logger.warning(f"[CQ_FILTER_DEBUG] CallbackQuery {query.id} не имеет message или message.chat объекта.")
        return False
    chat_type_val = query.message.chat.type
    
    logger.info(f"[CQ_FILTER_DEBUG] Проверка для User ID: {user_id}, Chat Type: {chat_type_val}")
    
    is_private = chat_type_val == ChatType.PRIVATE
    try:
        # BOT_OWNER_ID должен быть int. pydantic-settings должен это обеспечивать при загрузке.
        bot_owner_id_int = int(BOT_OWNER_ID)
    except ValueError:
        logger.error(f"[CQ_FILTER_DEBUG] BOT_OWNER_ID ('{BOT_OWNER_ID}') из конфига не является валидным integer!")
        return False
        
    is_owner = user_id == bot_owner_id_int
    
    result = is_private and is_owner
    
    logger.info(f"[CQ_FILTER_DEBUG] Чат является PRIVATE: {is_private}. Пользователь является OWNER ({user_id} == {bot_owner_id_int}): {is_owner}. Результат фильтра: {result}")
    return result

# Фильтр для сообщений от владельца в ЛС (НОВЫЙ)
async def owner_only_private_message_filter(message: types.Message) -> bool:
    if BOT_OWNER_ID is None:
        logger.warning("[OWNER_MSG_FILTER] BOT_OWNER_ID не установлен. Фильтр не пропускает.")
        return False
    try:
        # BOT_OWNER_ID может быть строкой из .env, если pydantic не преобразовал его в int
        # или если он был переопределен как строка где-то.
        # Убедимся, что сравниваем int с int.
        bot_owner_id_int = int(BOT_OWNER_ID) 
    except (ValueError, TypeError):
        logger.error(f"[OWNER_MSG_FILTER] BOT_OWNER_ID ('{BOT_OWNER_ID}') не является валидным integer!")
        return False
    
    is_private = message.chat.type == ChatType.PRIVATE
    # Убедимся, что message.from_user существует
    if not message.from_user:
        logger.warning("[OWNER_MSG_FILTER] Сообщение без message.from_user.")
        return False
        
    is_owner = message.from_user.id == bot_owner_id_int
    result = is_private and is_owner
    logger.debug(f"[OWNER_MSG_FILTER] User ID: {message.from_user.id}, Chat Type: {message.chat.type}. Is Private: {is_private}, Is Owner: {is_owner}. Result: {result}")
    return result

@admin_router.callback_query(OwnerGrantAccessCallback.filter(F.action == "grant"), owner_only_private_filter_debug_cq) # Используем новый фильтр
async def handle_owner_grant_access_action(query: types.CallbackQuery, callback_data: OwnerGrantAccessCallback, state: FSMContext, bot: Bot):
    logger.info(f"[OWNER_GRANT_ACTION_DEBUG_FILTER] CB от {query.from_user.id}, chat_type: {query.message.chat.type}, action: {callback_data.action}. Фильтр пройден.")
    await query.answer() # Отвечаем сразу
    
    # Основная логика функции (раскомментирована, если она должна работать)
    # ... (код функции handle_owner_grant_access_action как был)
    # Пока оставим как было в предыдущем шаге - с основной логикой
    user_to_grant_id = callback_data.user_id
    chat_id_for_grant = callback_data.chat_id

    await state.update_data(grant_access_user_id=user_to_grant_id, grant_access_chat_id=chat_id_for_grant)
    await state.set_state(OwnerGrantAccessStates.awaiting_days_input)

    try:
        user_info = await bot.get_chat(user_to_grant_id) 
        chat_info = await bot.get_chat(chat_id_for_grant) 
        user_display_name = user_info.full_name or f"ID {user_to_grant_id}"
        chat_display_name = chat_info.title or f"ID {chat_id_for_grant}"
    except Exception:
        user_display_name = f"ID {user_to_grant_id}"
        chat_display_name = f"ID {chat_id_for_grant}"

    text = (
        f"🔑 Предоставление доступа пользователю <b>{user_display_name}</b> в чате <b>{chat_display_name}</b>.\\n\\n"
        f"На сколько дней вы хотите предоставить доступ? Введите число (например, 7, 30, 0 - для бессрочного)."
    )
    await query.message.edit_text(text, parse_mode="HTML")
    # query.answer() уже был вызван

@admin_router.callback_query(OwnerGrantAccessCallback.filter(F.action == "cancel_grant"), owner_only_private_filter_debug_cq) # Используем новый фильтр
async def handle_owner_cancel_grant_action(query: types.CallbackQuery, callback_data: OwnerGrantAccessCallback, state: FSMContext, bot: Bot):
    logger.info(f"[OWNER_CANCEL_GRANT_DEBUG_FILTER] CB от {query.from_user.id}, chat_type: {query.message.chat.type}, action: {callback_data.action}. Фильтр пройден.")
    await query.answer("Отменено") # Отвечаем сразу
    
    # Основная логика функции (раскомментирована, если она должна работать)
    # ... (код функции handle_owner_cancel_grant_action как был)
    # Пока оставим как было в предыдущем шаге - с основной логикой
    try:
        user_info = await bot.get_chat(callback_data.user_id)
        chat_info = await bot.get_chat(callback_data.chat_id)
        user_display_name = user_info.full_name or f"ID {callback_data.user_id}"
        chat_display_name = chat_info.title or f"ID {callback_data.chat_id}"
    except Exception:
        user_display_name = f"ID {callback_data.user_id}"
        chat_display_name = f"ID {callback_data.chat_id}"

    text = (
        f"❌ Операция предоставления доступа пользователю <b>{user_display_name}</b> "
        f"в чате <b>{chat_display_name}</b> была отменена."
    )
    await query.message.edit_text(text, parse_mode="HTML", reply_markup=None) 
    await state.clear()
    # query.answer() уже был вызван

@admin_router.message(OwnerGrantAccessStates.awaiting_days_input, owner_only_private_message_filter, F.text) # ПРИМЕНЯЕМ НОВЫЙ ФИЛЬТР
async def handle_owner_days_input(message: types.Message, state: FSMContext, db_manager: DatabaseManager, bot: Bot):
    # Этот обработчик сообщений, а не коллбэков, но фильтр владельца к нему тоже применим.
    # Отладочный фильтр owner_only_private_filter_debug_cq написан для CallbackQuery.
    # Нужно либо адаптировать его, либо создать отдельный для Message, либо пока вернуть старый фильтр сюда.
    # Для чистоты эксперимента с кнопками, пока оставим этот обработчик как был, с оригинальным фильтром (если он был) или без него, если это не критично для теста кнопок.
    # В предыдущем шаге мы не трогали этот обработчик, так что вернем его к состоянию с owner_only_private_filter
    # ПРАВКА: Возвращаю owner_only_private_filter для этого message handler, так как owner_only_private_filter_debug_cq для CallbackQuery
    # logger.info(f"[OWNER_DAYS_INPUT_DEBUG_FILTER] Message от {message.from_user.id}, chat_type: {message.chat.type}. Фильтр пройден.") # Пример лога если бы фильтр был адаптирован
    logger.debug(f"[OWNER_DAYS_INPUT] Сработал обработчик ввода дней. Фильтр пройден.") # Добавим лог, что фильтр пройден
    
    # Код этого обработчика остается как был в файле, с его обычным фильтром.
    # Мы фокусируемся на CallbackQuery хэндлерах для кнопок.
# --- Начало оригинального кода handle_owner_days_input ---
    state_data = await state.get_data()
    user_id = state_data.get("grant_access_user_id")
    chat_id = state_data.get("grant_access_chat_id")

    if not user_id or not chat_id:
        logger.error(f"[OWNER_GRANT] Отсутствуют user_id или chat_id в state при вводе дней. User: {message.from_user.id}")
        await message.reply("Произошла ошибка: не найдены данные о пользователе или чате. Пожалуйста, начните сначала.")
        await state.clear()
        return

    try:
        days = int(message.text.strip())
        if days < 0:
            raise ValueError("Количество дней не может быть отрицательным.")
    except ValueError:
        await message.reply("Пожалуйста, введите корректное число дней (например, 7, 30, или 0 для бессрочного доступа).")
        return 

    access_until_ts: Optional[int] = None # Убедимся что Optional импортирован (from typing import Optional)
    if days > 0:
        access_until_ts = int(time.time()) + days * 24 * 60 * 60

    try:
        await db_manager.update_user_granted_access(user_id, chat_id, access_until_ts)
        
        user_info = await bot.get_chat(user_id)
        chat_info = await bot.get_chat(chat_id)
        user_display_name = user_info.full_name or f"ID {user_id}"
        chat_display_name = chat_info.title or f"ID {chat_id}"

        if access_until_ts:
            from datetime import datetime
            access_end_date_str = datetime.fromtimestamp(access_until_ts).strftime('%d.%m.%Y %H:%M:%S')
            response_text = (
                f"✅ Пользователю <b>{user_display_name}</b> в чате <b>{chat_display_name}</b> "
                f"предоставлен доступ на <b>{days}</b> дней (до {access_end_date_str})."
            )
        else: 
            response_text = (
                f"✅ Пользователю <b>{user_display_name}</b> в чате <b>{chat_display_name}</b> "
                f"предоставлен <b>бессрочный</b> особый доступ."
            )
        
        await message.reply(response_text, parse_mode="HTML")
        await state.clear()

        try:
            user_notification_text = f"Вам предоставлен особый доступ в чате «{chat_display_name}» "
            if access_until_ts:
                from datetime import datetime # Повторный импорт, если нужен локально
                user_notification_text += f"до {datetime.fromtimestamp(access_until_ts).strftime('%d.%m.%Y')}."
            else:
                user_notification_text += "(бессрочно)."
            await bot.send_message(user_id, user_notification_text)
        except Exception as e_notify:
            logger.warning(f"Не удалось уведомить пользователя {user_id} о предоставленном доступе: {e_notify}")

    except Exception as e:
        logger.error(f"Ошибка при обновлении доступа для user {user_id} в chat {chat_id}: {e}", exc_info=True)
        await message.reply("Произошла ошибка при сохранении данных. Пожалуйста, проверьте логи.")
        await state.clear() 
# --- Конец оригинального кода handle_owner_days_input ---

# --- Обработчики коллбэков от владельца по активации чата ---

@admin_router.callback_query(OwnerActivationChoiceCallback.filter(F.action == "approve"), owner_only_private_filter_debug_cq) # Используем отладочный фильтр
async def handle_owner_approve_activation(query: types.CallbackQuery, callback_data: OwnerActivationChoiceCallback, bot: Bot, db_manager: DatabaseManager, state: FSMContext):
    logger.info(f"[OWNER_APPROVE_DEBUG_FILTER] CB от {query.from_user.id}, chat_type: {query.message.chat.type}, action: {callback_data.action}. Фильтр пройден.")
    await query.answer() # Отвечаем сразу, чтобы кнопка не висела
    
    logger.info(f"[OWNER_APPROVE_LOGIC] Владелец ({query.from_user.id}) одобрил активацию чата {callback_data.target_chat_id}, запрошенную админом {callback_data.target_user_id}.")
    chat_id_to_activate = callback_data.target_chat_id
    admin_id_who_requested = callback_data.target_user_id # Переименовал для ясности
    owner_id = query.from_user.id

    try:
        await db_manager.activate_chat_for_owner(chat_id_to_activate, owner_id)
        logger.info(f"[OWNER_APPROVE_LOGIC] Вызван activate_chat_for_owner для чата {chat_id_to_activate} владельцем {owner_id}.")
    except Exception as e:
        logger.error(f"[OWNER_APPROVE_LOGIC] Не удалось активировать чат {chat_id_to_activate}: {e}")
        try:
            await query.message.edit_text("❌ Ошибка активации чата. Смотрите логи.", reply_markup=None)
        except Exception: pass # Игнорируем, если сообщение уже не отредактировать
        return

    chat_title_display = f"ID {chat_id_to_activate}"
    admin_mention_html = f"<a href='tg://user?id={admin_id_who_requested}'>администратору (ID {admin_id_who_requested})</a>"
    try:
        chat_info = await bot.get_chat(chat_id_to_activate)
        chat_title_display = chat_info.title or chat_title_display
        
        admin_user_info = await bot.get_chat(admin_id_who_requested) # Получаем инфо об админе для его имени
        admin_name_display = admin_user_info.full_name or f"ID {admin_id_who_requested}"
        admin_mention_html = f"<a href='tg://user?id={admin_id_who_requested}'>{admin_name_display}</a>"

    except Exception as e_get_info:
        logger.warning(f"[OWNER_APPROVE_LOGIC] Не удалось получить полную информацию о чате/админе для уведомлений: {e_get_info}")

    # Уведомление для администратора
    try:
        admin_message_text = (
            f"✅ Ваш запрос на настройку чата «<b>{chat_title_display}</b>» одобрен владельцем! Чат активирован.\\n\\n"
            f"Теперь вы можете настроить список каналов для проверки."
        )
        
        setup_button_builder = InlineKeyboardBuilder()
        setup_button_builder.button(
            text="⚙️ Настроить каналы",
            callback_data=DirectAdminSetupCallback(chat_id=chat_id_to_activate, admin_id=admin_id_who_requested)
        )
        
        await bot.send_message(
            admin_id_who_requested,
            admin_message_text,
            parse_mode="HTML",
            reply_markup=setup_button_builder.as_markup()
        )
        logger.info(f"[OWNER_APPROVE_LOGIC] Администратору {admin_id_who_requested} отправлено уведомление об активации и кнопка для настройки чата {chat_id_to_activate}.")
    except Exception as e_admin_notify:
        logger.error(f"[OWNER_APPROVE_LOGIC] Не удалось уведомить админа {admin_id_who_requested} об активации чата {chat_id_to_activate}: {e_admin_notify}")

    # Сообщение для владельца (редактируем его исходное сообщение)
    owner_confirm_text = (
        f"✅ Чат «<b>{chat_title_display}</b>» успешно активирован.\\n\\n"
        f"Уведомление и кнопка для дальнейшей настройки отправлены {admin_mention_html}."
    )
    try:
        await query.message.edit_text(owner_confirm_text, parse_mode="HTML", reply_markup=None)
    except Exception as e_owner_confirm:
        logger.warning(f"[OWNER_APPROVE_LOGIC] Не удалось отредактировать сообщение владельца: {e_owner_confirm}")

    # FSM для владельца больше не запускаем здесь
    # channel_service = ChannelManagementService(bot=bot, db_manager=db_manager, storage=state.storage)
    # await state.update_data(...)
    # await channel_service.start_channel_management(...)
    logger.info(f"[OWNER_APPROVE_LOGIC] Завершение обработки одобрения владельцем. Чат {chat_id_to_activate} активирован, админ {admin_id_who_requested} уведомлен.")
    await state.clear() # Очищаем состояние владельца, если оно было

@admin_router.callback_query(OwnerActivationChoiceCallback.filter(F.action == "approve_grant"), owner_only_private_filter_debug_cq) # Используем отладочный фильтр
async def handle_owner_approve_and_grant(query: types.CallbackQuery, callback_data: OwnerActivationChoiceCallback, bot: Bot, db_manager: DatabaseManager, state: FSMContext):
    logger.info(f"[OWNER_APPROVE_GRANT_DEBUG_FILTER] CB от {query.from_user.id}, chat_type: {query.message.chat.type}, action: {callback_data.action}. Фильтр пройден.")
    await query.answer() # Отвечаем сразу

    # --- Основная логика функции РАСКОММЕНТИРОВАНА ---
    chat_id_to_activate = callback_data.target_chat_id 
    owner_id = query.from_user.id
    target_user_id = callback_data.target_user_id
    target_chat_id_val = callback_data.target_chat_id 
    logger.info(f"[OWNER_APPROVE_GRANT_LOGIC] Владелец {owner_id} одобрил с выдачей доступа (approve_grant) запрос от {target_user_id} для чата {target_chat_id_val}.")
    try:
        await db_manager.activate_chat_for_owner(target_chat_id_val, query.from_user.id)
        logger.info(f"[OWNER_APPROVE_GRANT_LOGIC] Вызван activate_chat_for_owner для чата {target_chat_id_val} владельцем {query.from_user.id} перед выдачей доступа.")
        chat_info = await bot.get_chat(target_chat_id_val)
        admin_info = await bot.get_chat(target_user_id)
        chat_title_display = chat_info.title or f"ID {target_chat_id_val}"
        admin_full_name = admin_info.full_name or f"User {target_user_id}"
        admin_mention_html = f"<a href='tg://user?id={target_user_id}'>{admin_full_name}</a>"
        admin_notification_text = f"✅ Владелец бота одобрил ваш запрос. Чат <b>{chat_title_display}</b> активирован!\n\nВам также будет предоставлен особый доступ."
        try:
            await bot.send_message(target_user_id, admin_notification_text, parse_mode="HTML")
        except Exception as e_notify:
            logger.warning(f"Не удалось уведомить админа {target_user_id} об одобрении (approve_grant) чата {target_chat_id_val}: {e_notify}")
        await state.update_data(grant_access_user_id=target_user_id, grant_access_chat_id=target_chat_id_val)
        await state.set_state(OwnerGrantAccessStates.awaiting_days_input)
        owner_message_text = (
            f"✅ Чат <b>{chat_title_display}</b> активирован для {admin_mention_html}.\n\n"
            f"🔑 Теперь укажите, на сколько дней предоставить ему особый доступ? Введите число (0 - бессрочно)."
        )
        await query.message.edit_text(owner_message_text, parse_mode="HTML", reply_markup=None)
    except Exception as e:
        logger.error(f"Ошибка при обработке одобрения с выдачей доступа (approve_grant) владельцем {owner_id} для чата {target_chat_id_val}: {e}", exc_info=True)
        try:
            await query.message.edit_text("❌ Произошла ошибка при обработке одобрения.", reply_markup=None)
        except Exception: pass 
        await state.clear()

@admin_router.callback_query(OwnerActivationChoiceCallback.filter(F.action == "reject"), owner_only_private_filter_debug_cq) # Используем отладочный фильтр
async def handle_owner_reject_activation(query: types.CallbackQuery, callback_data: OwnerActivationChoiceCallback, bot: Bot, db_manager: DatabaseManager, state: FSMContext):
    logger.info(f"[OWNER_REJECT_DEBUG_FILTER] CB от {query.from_user.id}, chat_type: {query.message.chat.type}, action: {callback_data.action}. Фильтр пройден.")
    await query.answer() # Отвечаем сразу
    
    # --- Основная логика функции РАСКОММЕНТИРОВАНА ---
    owner_id = query.from_user.id
    target_user_id = callback_data.target_user_id
    target_chat_id_val = callback_data.target_chat_id
    logger.info(f"[OWNER_REJECT_LOGIC] Владелец {owner_id} отклонил (reject) запрос от {target_user_id} для чата {target_chat_id_val}.")
    try:
        chat_info = await bot.get_chat(target_chat_id_val)
        admin_info = await bot.get_chat(target_user_id)
        chat_title_display = chat_info.title or f"ID {target_chat_id_val}"
        admin_full_name = admin_info.full_name or f"User {target_user_id}"
        admin_mention_html = f"<a href='tg://user?id={target_user_id}'>{admin_full_name}</a>"
        admin_notification_text = f"❌ Владелец бота отклонил ваш запрос на настройку и активацию чата <b>{chat_title_display}</b>."
        try:
            await bot.send_message(target_user_id, admin_notification_text, parse_mode="HTML")
        except Exception as e_notify:
            logger.warning(f"Не удалось уведомить админа {target_user_id} об отклонении запроса для чата {target_chat_id_val}: {e_notify}")
        owner_message_text = (
            f"❌ Запрос от {admin_mention_html} для чата <b>{chat_title_display}</b> отклонен."
        )
        await query.message.edit_text(owner_message_text, parse_mode="HTML", reply_markup=None)
    except Exception as e:
        logger.warning(f"Не удалось отредактировать сообщение владельца об отклонении: {e}")

    # Сообщение для администратора
    admin_message_text = (
        f"❌ Владелец бота отклонил ваш запрос на активацию чата <b>{chat_title_display}</b>.\n\n"
        f"По вопросам активации бота обращайтесь к @daoqub."
    ) 
    try:
        await bot.send_message(target_user_id, admin_message_text, parse_mode="HTML")
        logger.info(f"Администратору {target_user_id} отправлено уведомление об отклонении запроса для чата {target_chat_id_val}.")
    except Exception as e_notify:
        logger.warning(f"Не удалось уведомить админа {target_user_id} об отклонении запроса для чата {target_chat_id_val}: {e_notify}")

    await state.clear() 