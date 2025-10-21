import logging
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault
from aiogram.exceptions import TelegramAPIError

logger = logging.getLogger(__name__)

async def setup_bot_commands(bot_instance: Bot):
    """Устанавливает команды меню бота"""
    commands = [
        BotCommand(command="start", description="Начать работу с ботом"),
        BotCommand(command="code", description="Получить код настройки для группы"),
        BotCommand(command="chats", description="Показать настроенные чаты"),
        BotCommand(command="help", description="Показать справку по командам")
    ]
    try:
        await bot_instance.set_my_commands(commands, scope=BotCommandScopeDefault())
        logger.info("Команды меню бота успешно настроены")
    except TelegramAPIError as e:
        logger.error(f"Ошибка при настройке команд меню бота: {e}") 