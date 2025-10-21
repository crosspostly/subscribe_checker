import logging
import asyncio # Возможно, потребуется asyncio для CaptchaService
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties # Для ParseMode
from aiogram.fsm.storage.memory import MemoryStorage # Импорт хранилища

# Обновленный импорт DatabaseManager
from bot.db.database import DatabaseManager
from bot.config import settings
# Возвращаем АБСОЛЮТНЫЕ импорты middleware:
from bot.middlewares.db_middleware import DbSessionMiddleware
from bot.middlewares.bot_middleware import BotMiddleware
# Импорт CaptchaService
from bot.services.captcha import CaptchaService

logger = logging.getLogger(__name__)

# Переменная для хранения актуального юзернейма бота
actual_bot_username: str | None = None

# Инициализация менеджера БД
db_manager = DatabaseManager()

# Инициализация хранилища состояний
storage = MemoryStorage()

# Инициализация бота и диспетчера
# Убираем db_manager из конструктора Dispatcher
dp = Dispatcher(storage=storage) 
bot = Bot(
    token=settings.bot_token.get_secret_value(),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

# Инициализация сервисов
captcha_service = CaptchaService(bot, db_manager)

# Функция для установки актуального юзернейма
async def set_actual_bot_username():
    global actual_bot_username
    try:
        bot_info = await bot.get_me()
        actual_bot_username = bot_info.username
        if actual_bot_username:
            logger.info(f"Актуальный юзернейм бота: @{actual_bot_username}")
        else:
            logger.error("Юзернейм бота не удалось получить через API (вернулся пустой).")
            # actual_bot_username остается None
    except Exception as e:
        logger.error(f"Не удалось получить юзернейм бота через API: {e}", exc_info=True)
        # actual_bot_username остается None
        # logger.error("Юзернейм бота не удалось определить ни через API, ни из конфига.") # Старый лог, когда был конфиг

# Регистрируем middleware для передачи db_manager в хендлеры
dp.update.middleware(DbSessionMiddleware(db_manager))

# Регистрируем middleware для передачи bot в хендлеры
dp.update.middleware(BotMiddleware(bot))

logger.info("Bot, Dispatcher, DB Manager и Middlewares инициализированы.") 