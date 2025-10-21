"""
Сервис для управления логикой капчи.
"""
import logging
import asyncio
from aiogram import Bot, types
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatPermissions
from typing import Optional
import time
from html import escape

# Импортируем DatabaseManager для проверки активации
from bot.db.database import DatabaseManager 
# УДАЛЯЕМ импорт экземпляра менеджера базы данных
# from bot.bot_instance import db_manager 
from ..keyboards.inline import get_captcha_keyboard
from ..utils.helpers import get_user_mention_html

logger = logging.getLogger(__name__)

# Функция для форматирования логов капчи
def format_captcha_log(chat_id, chat_title, user_id, user_name, message, message_id=None):
    """Форматирует сообщения логов капчи с названиями чатов и пользователей."""
    user_info = f"{user_name} (ID: {user_id})" if user_name else f"Пользователь {user_id}"
    chat_info = f"{chat_title} (ID: {chat_id})" if chat_title else f"Чат {chat_id}"
    msg_info = f" (сообщение: {message_id})" if message_id else ""
    
    return f"[CAPTCHA] {user_info} в чате {chat_info}{msg_info}: {message}"

class CaptchaService:
    def __init__(self, bot: Bot, db_manager: DatabaseManager):
        self.bot = bot
        self.db_manager = db_manager
        self._captcha_cleanup_tasks = {} # Словарь для хранения задач удаления сообщений капчи

    async def send_captcha(self, message: types.Message):
        """Отправляет сообщение с капчей и удаляет исходное сообщение пользователя."""
        user = message.from_user
        chat_id = message.chat.id
        chat_title = message.chat.title or f"Чат {chat_id}"

        # --- Проверка активации чата ---
        chat_settings = await self.db_manager.get_chat_settings(chat_id)
        if not chat_settings or not chat_settings.get('is_activated', 0):
            logger.debug(format_captcha_log(chat_id, chat_title, user.id, user.full_name, 
                                     f"Капча не отправлена, так как чат не активирован."))
            # Опционально: можно удалить сообщение пользователя, даже если чат не активирован
            try:
                await message.delete()
                logger.debug(format_captcha_log(chat_id, chat_title, user.id, user.full_name, 
                                        f"Исходное сообщение удалено (чат не активирован)."))
            except TelegramAPIError:
                pass # Игнорируем ошибки удаления
            return # Не отправляем капчу
        # ---------------------------------
            
        user_name = user.full_name
        user_mention = get_user_mention_html(user)

        try:
            # Удаляем исходное сообщение пользователя
            await message.delete()
            logger.debug(format_captcha_log(chat_id, chat_title, user.id, user_name, 
                                    f"Удалено исходное сообщение", message.message_id))
        except TelegramAPIError as e:
            logger.warning(format_captcha_log(chat_id, chat_title, user.id, user_name, 
                                    f"Не удалось удалить исходное сообщение: {e}", message.message_id))

        try:
            # Отправляем сообщение с капчей
            captcha_msg = await self.bot.send_message(
                chat_id,
                f"🛡️ {user_mention}, пожалуйста, подтвердите, что вы не робот, нажав кнопку ниже.",
                reply_markup=get_captcha_keyboard(user.id),
                parse_mode="HTML",
                disable_notification=True
            )
            logger.info(format_captcha_log(chat_id, chat_title, user.id, user_name, 
                                  f"Отправлена капча (будет активна 10 секунд)", captcha_msg.message_id))
            
            # <--- Сохраняем сообщение в БД для последующей очистки --- >
            await self.db_manager.add_bot_message_for_cleanup(chat_id, captcha_msg.message_id)
            logger.debug(format_captcha_log(chat_id, chat_title, user.id, user_name, 
                                   f"Сообщение капчи {captcha_msg.message_id} добавлено в БД для очистки."))
            # <---------------------------------------------------------- >

            # Запускаем задачу на удаление капчи через 10 секунд
            task_key = (chat_id, captcha_msg.message_id)
            if task_key in self._captcha_cleanup_tasks:
                # Отменяем предыдущую задачу, если по какой-то причине она еще висит
                self._captcha_cleanup_tasks[task_key].cancel()
                logger.debug(format_captcha_log(chat_id, chat_title, user.id, user_name, 
                                       f"Отменена предыдущая задача удаления для сообщения {captcha_msg.message_id}", captcha_msg.message_id))

            self._captcha_cleanup_tasks[task_key] = asyncio.create_task(
                self._delete_message_after_delay(chat_id, chat_title, captcha_msg.message_id, 10, user.id, user_name)
            )
            logger.debug(format_captcha_log(chat_id, chat_title, user.id, user_name, 
                                   f"Новая задача удаления для сообщения {captcha_msg.message_id} запланирована.", captcha_msg.message_id))

        except TelegramAPIError as e:
            logger.error(format_captcha_log(chat_id, chat_title, user.id, user_name, 
                                  f"Ошибка отправки капчи: {e}"))
            # Попытка удалить исходное сообщение, если отправка капчи не удалась (хотя выше уже пытались)
            try:
                await message.delete()
            except TelegramAPIError:
                pass
        except Exception as e:
            logger.critical(format_captcha_log(chat_id, chat_title, user.id, user_name, 
                                     f"Непредвиденная ошибка при отправке капчи: {e}"), exc_info=True)

    async def _delete_message_after_delay(self, chat_id: int, chat_title: str, message_id: int, delay: int, user_id: int = None, user_name: str = None):
        """Удаляет сообщение с указанной задержкой, с логикой повторных попыток и удалением из БД очистки."""
        task_key = (chat_id, message_id) # Формируем ключ задачи
        logger.debug(format_captcha_log(chat_id, chat_title, user_id, user_name, 
                               f"Запланировано удаление капчи через {delay} секунд", message_id))
        await asyncio.sleep(delay)

        max_attempts = 2
        attempt_delay_seconds = 2
        deleted_successfully_from_tg = False

        try:
            for attempt in range(max_attempts):
                try:
                    await self.bot.delete_message(chat_id, message_id)
                    logger.info(format_captcha_log(chat_id, chat_title, user_id, user_name, 
                                           f"Сообщение капчи {message_id} успешно удалено из Telegram (попытка {attempt + 1})."))
                    deleted_successfully_from_tg = True
                    break
                except TelegramAPIError as e:
                    error_message = str(e).lower()
                    if "message to delete not found" in error_message or \
                       "message can't be deleted" in error_message:
                        logger.warning(format_captcha_log(chat_id, chat_title, user_id, user_name, 
                                                 f"Сообщение капчи {message_id} уже удалено из Telegram или не может быть удалено: {e} (попытка {attempt + 1})."))
                        deleted_successfully_from_tg = True
                        break
                    
                    logger.warning(format_captcha_log(chat_id, chat_title, user_id, user_name, 
                                             f"Попытка {attempt + 1}/{max_attempts} не удалась для сообщения капчи {message_id} в Telegram: {e}"))
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(attempt_delay_seconds)
                    else:
                        logger.error(format_captcha_log(chat_id, chat_title, user_id, user_name, 
                                                f"Не удалось окончательно удалить сообщение капчи {message_id} из Telegram после {max_attempts} попыток: {e}"))
                except Exception as e_general:
                    logger.error(format_captcha_log(chat_id, chat_title, user_id, user_name, 
                                           f"Непредвиденная ошибка при удалении сообщения капчи {message_id} из Telegram (попытка {attempt + 1}): {e_general}"), exc_info=True)
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(attempt_delay_seconds)
                    else:
                        logger.critical(format_captcha_log(chat_id, chat_title, user_id, user_name, 
                                           f"Непредвиденная ошибка не позволила удалить сообщение капчи {message_id} из Telegram после {max_attempts} попыток."), exc_info=True)
        finally:
            # Удаляем задачу из словаря после завершения (успешного или нет)
            if task_key in self._captcha_cleanup_tasks:
                del self._captcha_cleanup_tasks[task_key]
                logger.debug(format_captcha_log(chat_id, chat_title, user_id, user_name, 
                                       f"Задача удаления капчи {message_id} удалена из словаря."))

        # Если сообщение было удалено из Telegram (или его там и не было),
        # то удаляем его из нашей БД (очереди на очистку)
        if deleted_successfully_from_tg:
            try:
                await self.db_manager.remove_bot_message_from_cleanup(chat_id, message_id)
                logger.info(format_captcha_log(chat_id, chat_title, user_id, user_name, 
                                       f"Запись о сообщении капчи {message_id} удалена из БД очистки."))
            except Exception as e_db:
                logger.error(format_captcha_log(chat_id, chat_title, user_id, user_name, 
                                       f"Ошибка при удалении записи о сообщении капчи {message_id} из БД очистки: {e_db}"), exc_info=True)
        else:
            logger.warning(format_captcha_log(chat_id, chat_title, user_id, user_name, 
                                     f"Сообщение капчи {message_id} не было удалено из Telegram, запись в БД очистки НЕ удалена."))

    async def is_user_verified(self, user_id: int, chat_id: int, chat_title: str = None, user_name: str = None) -> bool:
        """Проверяет, прошел ли пользователь капчу в данном чате."""
        # УДАЛЯЕМ локальный импорт DatabaseManager из зависимостей
        # from bot.bot_instance import db_manager 
        
        # Получаем статус пользователя в чате
        user_status = await self.db_manager.get_user_status_in_chat(user_id, chat_id) # Используем self.db_manager
        
        # Проверяем, прошел ли пользователь капчу
        captcha_passed = user_status and user_status['captcha_passed'] if user_status else 0
        
        status_str = "прошел" if captcha_passed else "не прошел"
        logger.debug(format_captcha_log(chat_id, chat_title, user_id, user_name, 
                               f"Проверка статуса капчи: {status_str} (DB: {captcha_passed})"))
        return bool(captcha_passed)
        
    async def start_captcha_for_user(self, bot: Bot, chat_id: int, user_id: int, user_name: str, chat_title: Optional[str] = None):
        """Отправляет капчу при входе пользователя в чат."""

        # --- Проверка активации чата ---
        chat_settings = await self.db_manager.get_chat_settings(chat_id)
        actual_chat_title = chat_title or f"Чат {chat_id}"

        if not chat_settings or not chat_settings.get('is_activated', 0):
            logger.debug(f"[CAPTCHA] Капча при входе для {user_id} в чате {actual_chat_title} ({chat_id}) не отправлена, так как чат не активирован.")
            return 
        # ---------------------------------
           
        try:
            escaped_user_name = escape(user_name)
            user_mention = f"<a href='tg://user?id={user_id}'>{escaped_user_name}</a>"
            
            current_status = await self.is_user_verified(user_id, chat_id, actual_chat_title, user_name)
            if current_status:
                logger.info(format_captcha_log(chat_id, actual_chat_title, user_id, user_name, 
                                     f"Капча уже пройдена в БД, пропускаем отправку новой капчи при входе"))
                return
                
            captcha_msg = await bot.send_message(
                chat_id,
                f"🛡️ {user_mention}, чтобы писать сообщения в чате нажмите кнопку ниже.",
                reply_markup=get_captcha_keyboard(user_id),
                parse_mode="HTML",
                disable_notification=True
            )
            logger.info(format_captcha_log(chat_id, actual_chat_title, user_id, user_name, 
                                  f"Отправлена капча при входе в чат (будет активна 60 секунд)", captcha_msg.message_id)) # Увеличил время активности, если мут 60 минут

            await self.db_manager.add_bot_message_for_cleanup(chat_id, captcha_msg.message_id)
            logger.debug(format_captcha_log(chat_id, actual_chat_title, user_id, user_name, 
                                   f"Сообщение капчи {captcha_msg.message_id} (при входе) добавлено в БД для очистки."))

            # Запускаем задачу на удаление капчи через 60 секунд (или до прохождения)
            task_key = (chat_id, captcha_msg.message_id)
            if task_key in self._captcha_cleanup_tasks:
                 self._captcha_cleanup_tasks[task_key].cancel()
                 logger.debug(format_captcha_log(chat_id, actual_chat_title, user_id, user_name, 
                                       f"Отменена предыдущая задача удаления для сообщения {captcha_msg.message_id} (при входе)", captcha_msg.message_id))

            self._captcha_cleanup_tasks[task_key] = asyncio.create_task(
                self._delete_message_after_delay(chat_id, actual_chat_title, captcha_msg.message_id, 60, user_id, user_name) # Задержка 60 секунд
            )
            logger.debug(format_captcha_log(chat_id, actual_chat_title, user_id, user_name, 
                                   f"Новая задача удаления для сообщения {captcha_msg.message_id} (при входе) запланирована.", captcha_msg.message_id))

            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                    can_change_info=False,
                    can_invite_users=False,
                    can_pin_messages=False
                ),
                until_date=int(time.time()) + (60 * 60) # Мут на 60 минут, пока не пройдет или время не выйдет
            )
            logger.info(format_captcha_log(chat_id, actual_chat_title, user_id, user_name, "Установлен мут на время прохождения капчи при входе."))

        except Exception as e:
            logger.error(format_captcha_log(chat_id, actual_chat_title, user_id, user_name, 
                                  f"Ошибка отправки капчи при входе: {e}"), exc_info=True)
