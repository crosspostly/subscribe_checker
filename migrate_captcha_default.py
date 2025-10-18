import asyncio
import aiosqlite
import logging
import os

# --- Настройки ---
# Пытаемся импортировать имя БД из конфига бота
# Если скрипт будет запускаться из другой папки, возможно, придется указать путь явно
try:
    from bot.config import DB_NAME
except ImportError:
    print("Не удалось импортировать DB_NAME из bot.config. Убедитесь, что скрипт находится в корне проекта.")
    print("Используется имя файла по умолчанию: 'subbot.db'")
    DB_NAME = "subbot.db"

DATABASE_PATH = DB_NAME # Путь к файлу базы данных

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# --- ---

async def apply_migration():
    """Подключается к БД и включает captcha_enabled для всех чатов."""
    if not os.path.exists(DATABASE_PATH):
        logger.error(f"Ошибка: Файл базы данных '{DATABASE_PATH}' не найден.")
        return

    logger.info(f"Подключение к базе данных: {DATABASE_PATH}")
    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Запрос для включения капчи
            update_query = "UPDATE chats SET captcha_enabled = 1 WHERE captcha_enabled = 0 OR captcha_enabled IS NULL;"
            
            logger.info("Выполнение запроса: " + update_query)
            cursor = await db.execute(update_query)
            await db.commit()
            
            # cursor.rowcount может не всегда возвращать корректное число для UPDATE в aiosqlite
            # Просто сообщим об успешном выполнении
            logger.info(f"Миграция успешно применена. Для {cursor.rowcount if cursor.rowcount != -1 else 'нескольких'} чатов установлено captcha_enabled = 1.")

    except aiosqlite.Error as e:
        logger.error(f"Ошибка SQLite при применении миграции: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Непредвиденная ошибка: {e}", exc_info=True)

async def main():
    logger.info("--- Запуск скрипта миграции для включения капчи по умолчанию ---")
    await apply_migration()
    logger.info("--- Скрипт миграции завершен ---")

if __name__ == "__main__":
    # Проверка, запущен ли бот (простой способ - проверить PID файл, если он есть, или спросить пользователя)
    # В данном случае, просто предупредим
    print("\nВАЖНО: Убедитесь, что бот остановлен перед запуском этой миграции!\n")
    confirm = input("Продолжить выполнение миграции? (yes/no): ")
    if confirm.lower() == 'yes':
        asyncio.run(main())
    else:
        print("Миграция отменена.") 