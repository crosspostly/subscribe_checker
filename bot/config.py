from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr

# Имя файла базы данных (можно вынести в .env при желании)
DB_NAME = 'bot_data.db'

class Settings(BaseSettings):
    # Загружаем переменные из .env файла
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    # Токен бота обязателен
    bot_token: SecretStr
    # Имя пользователя бота (опционально, берется из .env)
    bot_owner_id: int | None = None
    bot_owner_username: str | None = None

    # Настройки для Telethon
    telethon_api_id: int | None = None
    telethon_api_hash: str | None = None
    telethon_phone: str | None = None # Опционально, для неинтерактивного входа

    # Имя файла базы данных (по умолчанию, можно переопределить в .env)
    db_name: str = 'bot_data.db'

    # Можно добавить другие глобальные настройки по мере необходимости
    # super_admin_id: int | None = None

# Создаем экземпляр настроек, который будем импортировать в другие модули
settings = Settings()
# Отладочные принты оставим пока, чтобы убедиться, что BOT_OWNER_ID читается
print(f"[DEBUG config.py] Attempting to load BOT_OWNER_ID from .env")
print(f"[DEBUG config.py] Loaded settings.bot_owner_id: {settings.bot_owner_id}")
print(f"[DEBUG config.py] Type of settings.bot_owner_id: {type(settings.bot_owner_id)}")
print(f"[DEBUG config.py] Loaded settings.bot_owner_username: {settings.bot_owner_username}")
print(f"[DEBUG config.py] Type of settings.bot_owner_username: {type(settings.bot_owner_username)}")
# Удалены принты для settings.bot_username, так как поле bot_username будет удалено из Settings


# Определяем BOT_USERNAME для использования в коде
# Приоритет: из .env, если нет - используем значение по умолчанию (можно задать выше)
# BOT_USERNAME будет получен динамически из API и сохранен в bot_instance (или аналогичном месте)
# BOT_USERNAME = settings.bot_username or 'YourCheckSubBot'
BOT_OWNER_ID = settings.bot_owner_id
BOT_OWNER_USERNAME = settings.bot_owner_username