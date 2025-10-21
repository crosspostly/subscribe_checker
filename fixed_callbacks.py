import asyncio
from aiogram.types import Bot
from aiogram.exceptions import TelegramAPIError
from log import logger, format_captcha_log

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