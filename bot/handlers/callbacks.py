import logging
import asyncio
from aiogram import Router, Bot, F, types
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.utils.markdown import hbold, hlink, hcode
from html import escape

from bot.db.database import DatabaseManager
from bot.services.captcha import CaptchaService, format_captcha_log
# from bot.services.subscription import SubscriptionService # Больше не нужен здесь?
from bot.services.channel_mgmt import ChannelManagementService
from bot.states import ManageChannels, Activation
from bot.utils.helpers import get_user_mention_html, is_admin
# Импортируем коллбэки из нового файла
from bot.data.callback_data import (
    ConfirmSetupCallback, ChannelManageCallback, ChannelRemoveCallback,
    CaptchaCallback #, SubscriptionCheckCallback # Удаляем импорт
)
from bot.services.subscription import SubscriptionService
# from bot.utils.constants import DEFAULT_PARSE_MODE

from bot.middlewares.db_middleware import DbSessionMiddleware
from bot.middlewares.bot_middleware import BotMiddleware
# Добавим импорт для получения экземпляров бота, БД и CaptchaService
from bot.bot_instance import bot, db_manager, captcha_service
from aiogram.enums import ChatMemberStatus # Для проверки статуса участника
from bot.keyboards.inline import get_subscription_check_keyboard # Добавляем импорт

logger = logging.getLogger(__name__)
callback_router = Router(name="callback_router")

# Добавлям middleware с передачей экземпляров объектов
callback_router.message.middleware.register(DbSessionMiddleware(db_manager))
callback_router.callback_query.middleware.register(DbSessionMiddleware(db_manager))

callback_router.message.middleware.register(BotMiddleware(bot))
callback_router.callback_query.middleware.register(BotMiddleware(bot))

# Добавим специальный middleware для subscription_service
# callback_router.callback_query.middleware.register(SubscriptionServiceMiddleware())

async def _delete_message_after_delay(bot: Bot, chat_id: int, message_id: int, delay: int, user_id=None, user_name=None, chat_title=None):
    """Удаляет сообщение с задержкой."""
    # Логируем запланированное удаление
    if user_id:
        logger.debug(format_captcha_log(chat_id, chat_title, user_id, user_name, 
                               f"Запланировано удаление сообщения с подтверждением капчи через {delay} секунд", message_id))
    
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
        # Логируем успешное удаление
        if user_id:
            logger.debug(format_captcha_log(chat_id, chat_title, user_id, user_name, 
                                  f"Сообщение с подтверждением капчи удалено", message_id))
    except TelegramAPIError as e:
        # Логируем ошибку удаления
        if user_id:
            logger.warning(format_captcha_log(chat_id, chat_title, user_id, user_name, 
                                    f"Не удалось удалить сообщение с подтверждением капчи: {e}", message_id))
        else:
            logger.warning(f"Не удалось удалить сообщение {message_id} из чата {chat_id} после коллбека: {e}")


@callback_router.callback_query(F.data.startswith("captcha_pass_"))
async def handle_captcha_callback(callback: types.CallbackQuery, bot: Bot, db_manager: DatabaseManager):
    """Обрабатывает нажатие на кнопку капчи."""
    user = callback.from_user
    chat_id = callback.message.chat.id
    message_id = callback.message.message_id
    
    # Получаем информацию о чате и пользователе для логов
    chat_title = callback.message.chat.title or f"Чат {chat_id}"
    user_name = user.full_name

    try:
        target_user_id = int(callback.data.split("_")[-1])
    except (IndexError, ValueError):
        logger.error(format_captcha_log(chat_id, chat_title, user.id, user_name, 
                              f"Некорректный формат callback_data: {callback.data}", message_id))
        await callback.answer("Произошла ошибка. Попробуйте снова.", show_alert=True)
        return

    # Проверяем, что кнопку нажал нужный пользователь
    if user.id != target_user_id:
        logger.warning(format_captcha_log(chat_id, chat_title, user.id, user_name, 
                               f"Попытка нажатия на чужую капчу (для пользователя {target_user_id})", message_id))
        await callback.answer("Эта кнопка не для вас.", show_alert=True)
        return

    # Обновляем статус в БД
    await db_manager.update_user_captcha_status(user.id, chat_id, passed=True)
    logger.info(format_captcha_log(chat_id, chat_title, user.id, user_name, 
                          f"Успешно пройдена капча! Обновлен статус в БД", message_id))

    # --- Логика анмута и сброса статуса бана в БД (добавляем сюда) ---
    try:
        # Снимаем ограничения в Telegram
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user.id,
            permissions=types.ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False
            ),
            until_date=0 # Снимаем все ограничения немедленно
        )
        logger.info(format_captcha_log(chat_id, chat_title, user.id, user_name, 
                               f"Сняты ограничения после прохождения капчи", message_id))
        
        # Сбрасываем статус бана в БД (если он был установлен ботом из-за капчи)
        # Возможно, стоит использовать более специфичный метод сброса, если бан был именно за капчу
        # Пока используем общий сброс, т.к. в контексте капчи это сработает верно
        await db_manager.clear_user_ban_status(user.id, chat_id) # Используем user.id
        logger.info(format_captcha_log(chat_id, chat_title, user.id, user_name, 
                               f"Сброшен статус бана в БД после прохождения капчи", message_id))

    except TelegramAPIError as e:
        logger.error(format_captcha_log(chat_id, chat_title, user.id, user_name, 
                              f"Ошибка API при снятии ограничений/сбросе бана после капчи: {e}", message_id))
    except Exception as e_unban:
        logger.error(format_captcha_log(chat_id, chat_title, user.id, user_name, 
                              f"Непредвиденная ошибка при снятии ограничений/сбросе бана после капчи: {e_unban}", message_id), exc_info=True)
    # --- Конец логики анмута ---

    # --- Отмена запланированного удаления и немедленное удаление сообщения капчи ---
    # message_id сообщения капчи уже доступен как callback.message.message_id
    captcha_msg_id = message_id
    task_key = (chat_id, captcha_msg_id) # Используем тот же ключ, что и в CaptchaService

    # Проверяем, есть ли для этого сообщения запланированная задача удаления в CaptchaService
    if task_key in captcha_service._captcha_cleanup_tasks:
        cleanup_task = captcha_service._captcha_cleanup_tasks[task_key]
        if not cleanup_task.done():
            cleanup_task.cancel() # Отменяем задачу, если она еще выполняется
            logger.debug(format_captcha_log(chat_id, chat_title, user.id, user_name,
                                   f"Отменена запланированная задача удаления капчи {captcha_msg_id} после прохождения.", captcha_msg_id))
        del captcha_service._captcha_cleanup_tasks[task_key] # Удаляем из словаря
    else:
         logger.warning(format_captcha_log(chat_id, chat_title, user.id, user_name,
                                   f"Не найдена запланированная задача удаления для капчи {captcha_msg_id} при прохождении.", captcha_msg_id))

    # Теперь вызываем локальную _delete_message_after_delay для немедленного удаления сообщения капчи из Telegram
    # Задержка 0 или очень маленькая, так как ждали коллбека
    asyncio.create_task(_delete_message_after_delay(bot, chat_id, captcha_msg_id, 0.1, user.id, user_name, chat_title))
    logger.debug(format_captcha_log(chat_id, chat_title, user.id, user_name,
                               f"Запущена задача немедленного удаления капчи {captcha_msg_id} после прохождения.", captcha_msg_id))
    # --- Конец отмены и удаления ---

    # Отвечаем на коллбек (невидимо для пользователя) после попытки удаления
    await callback.answer("✅ Проверка пройдена!", show_alert=False)

# --- Обработчики FSM управления каналами (оставляем) --- #

# ... (здесь обработчики ConfirmSetupCallback, ChannelManageCallback, ChannelRemoveCallback) ... #
# Убедитесь, что они импортированы и зарегистрированы, если они есть в этом файле
# Например:
# @callback_router.callback_query(ChannelManageCallback.filter(F.action == 'add'))
# async def handle_add_channel_button(...):
#     ...
# @callback_router.callback_query(ChannelRemoveCallback.filter())
# async def handle_remove_channel_select(...):
#     ...
# @callback_router.callback_query(ChannelManageCallback.filter(F.action == 'finish'))
# async def handle_finish_manage(...):
#     ...
# @callback_router.callback_query(ChannelManageCallback.filter(F.action == 'cancel'))
# async def handle_cancel_manage(...):
#     ...

# УДАЛЯЕМ ИЛИ КОММЕНТИРУЕМ ОБРАБОТЧИК КНОПКИ ПРОВЕРКИ ПОДПИСКИ
# @callback_router.callback_query(SubscriptionCheckCallback.filter())
# async def handle_subscription_check(query: types.CallbackQuery, callback_data: SubscriptionCheckCallback, bot: Bot, db_manager: DatabaseManager, subscription_service: SubscriptionService):
#     ...

# @callback_router.callback_query(F.data.startswith("check_sub_"))
# async def handle_subscription_check_callback(callback: types.CallbackQuery, bot: Bot, db_manager: DatabaseManager):
#     ... 

@callback_router.callback_query(F.data.startswith("subcheck:"))
async def handle_subcheck_callback(callback: types.CallbackQuery, bot: Bot, db_manager: DatabaseManager, subscription_service: SubscriptionService):
    """Обрабатывает нажатие на кнопку проверки подписки, делегируя основную логику в SubscriptionService."""
    requesting_user_id = callback.from_user.id
    
    # Извлекаем ID пользователя, для которого предназначена кнопка, из callback_data
    # Формат subcheck:target_user_id
    try:
        parts = callback.data.split(":")
        if len(parts) < 2 or not parts[1].isdigit():
            logger.error(f"[SUBCHECK_CALLBACK_VALIDATION] Некорректный формат callback_data: {callback.data} от user {requesting_user_id}")
            await callback.answer("Ошибка: неверный формат данных кнопки.", show_alert=True)
            return
        target_user_id = int(parts[1])
    except Exception as e:
        logger.error(f"[SUBCHECK_CALLBACK_VALIDATION] Ошибка извлечения target_user_id из {callback.data}: {e}")
        await callback.answer("Ошибка обработки данных кнопки.", show_alert=True)
        return

    # Проверяем, что кнопку нажал именно тот пользователь, для которого она предназначена
    if requesting_user_id != target_user_id:
        logger.warning(f"[SUBCHECK_CALLBACK_AUTH] Пользователь {requesting_user_id} нажал кнопку, предназначенную для {target_user_id}. Отклонено.")
        await callback.answer("Эта кнопка не для вас.", show_alert=True)
        return

    # Логируем, что проверка пройдена и передаем управление в сервис
    chat_id = callback.message.chat.id
    chat_title = callback.message.chat.title or f"Чат {chat_id}"
    user_name = callback.from_user.full_name
    logger.info(f"[SUBCHECK_CALLBACK_DELEGATING] Пользователь {user_name} ({requesting_user_id}) прошел первичную проверку кнопки в чате {chat_title} ({chat_id}). Делегирование в SubscriptionService...")

    # Передаем управление в SubscriptionService для полной обработки
    await subscription_service.handle_subscription_check_callback(callback)

# Вспомогательная функция для удаления сообщений
async def delete_message_after_delay(bot: Bot, chat_id: int, message_id: int, delay: int):
    """Удаляет сообщение через указанное количество секунд."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.error(f"Не удалось удалить сообщение {message_id} в чате {chat_id}: {e}") 

# @callback_router.callback_query(F.data.startswith("confirm_setup:"))
# async def confirm_setup_callback(query: types.CallbackQuery, state: FSMContext):
#     # Этот обработчик больше не нужен, так как логика перенесена в fsm_private.py
#     # await state.update_data(target_chat_id=query.message.chat.id) # Неправильно - chat.id будет ЛС
#     # callback_data = ConfirmSetupCallback.unpack(query.data)
#     # chat_id_to_setup = callback_data.chat_id
#     # await state.update_data(target_chat_id=chat_id_to_setup)
#     # logger.info(f"[DEPRECATED_CALLBACK] confirm_setup_callback сработал для chat {chat_id_to_setup}")
#     # await Activation.awaiting_code.set() # Ошибка AttributeError: 'State' object has no attribute 'set'
#     # await query.message.answer('Пожалуйста, введите код активации для этого чата.')
#     logger.warning("Сработал устаревший обработчик confirm_setup_callback в callbacks.py. Он должен быть удален или отключен.")
#     await query.answer("Эта кнопка обрабатывается другим модулем (ошибка).", show_alert=True)
#     # Не удаляем сообщение, чтобы была видна ошибка

# Конец файла callbacks.py 