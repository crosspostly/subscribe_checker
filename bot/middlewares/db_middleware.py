from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

# Импортируем DatabaseManager из правильного файла
from bot.db.database import DatabaseManager  

class DbSessionMiddleware(BaseMiddleware):
    """Пробрасывает менеджер базы данных в хендлеры."""
    def __init__(self, db_manager: DatabaseManager):
        super().__init__()
        self.db_manager = db_manager

    async def __call__(
        self, 
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]], 
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Передаем менеджер БД в data для использования в хендлерах
        data['db_manager'] = self.db_manager
        return await handler(event, data) 