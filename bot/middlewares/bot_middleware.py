from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject

class BotMiddleware(BaseMiddleware):
    """Пробрасывает экземпляр Bot в хендлеры."""
    def __init__(self, bot: Bot):
        super().__init__()
        self.bot = bot

    async def __call__(
        self, 
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]], 
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Передаем экземпляр bot в data для использования в хендлерах
        data['bot'] = self.bot
        return await handler(event, data) 