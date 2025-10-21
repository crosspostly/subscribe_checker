import asyncio
import aiosqlite
import os
import logging

# Настройка логирования для миграции
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATABASE_PATH = 'bot_data.db' # Укажите правильный путь к вашей БД

async def migrate():
    logger.info(f"Попытка подключения к базе данных: {DATABASE_PATH}")
    if not os.path.exists(DATABASE_PATH):
        logger.error(f"Файл базы данных не найден по пути: {DATABASE_PATH}")
        return

    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            logger.info(f"Успешное подключение к {DATABASE_PATH}.")

            # 1. Проверяем наличие таблицы users_status_in_chats
            cursor_check_table = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users_status_in_chats'")
            table_exists = await cursor_check_table.fetchone()

            if not table_exists:
                logger.error("Таблица 'users_status_in_chats' не найдена. Миграция не может быть выполнена.")
                return

            # 2. Проверяем наличие столбца subscription_fail_count
            cursor_info = await db.execute("PRAGMA table_info(users_status_in_chats);")
            columns = await cursor_info.fetchall()
            column_names = [col['name'] for col in columns]
            logger.info(f"Существующие колонки в 'users_status_in_chats': {column_names}")

            if 'subscription_fail_count' not in column_names:
                logger.info("Колонка 'subscription_fail_count' не найдена. Попытка добавить...")
                try:
                    await db.execute("ALTER TABLE users_status_in_chats ADD COLUMN subscription_fail_count INTEGER DEFAULT 0")
                    await db.commit()
                    logger.info("Колонка 'subscription_fail_count' успешно добавлена со значением по умолчанию 0.")
                except aiosqlite.OperationalError as oe_add:
                    if "duplicate column name" in str(oe_add).lower():
                        logger.warning(f"Колонка 'subscription_fail_count' уже существует (ошибка дублирования). Пропускаем добавление.")
                    else:
                        logger.error(f"Ошибка ALTER TABLE при добавлении 'subscription_fail_count': {oe_add}", exc_info=True)
                        raise
            else:
                logger.info("Колонка 'subscription_fail_count' уже существует. Миграция не требуется.")

            # 3. (Опционально) Проверить и установить DEFAULT 0, если колонка существует, но не имеет DEFAULT
            # Это более сложная миграция и может потребовать пересоздания таблицы для SQLite < 3.36
            # Пока что предполагаем, что если колонка есть, то она была создана с DEFAULT или будет обрабатываться кодом.
            # Если бы мы хотели гарантировать DEFAULT 0 для существующих записей, где оно NULL:
            # if 'subscription_fail_count' in column_names:
            #     logger.info("Проверка и обновление существующих NULL значений в 'subscription_fail_count' на 0...")
            #     await db.execute("UPDATE users_status_in_chats SET subscription_fail_count = 0 WHERE subscription_fail_count IS NULL")
            #     await db.commit()
            #     logger.info("Завершено обновление NULL значений в 'subscription_fail_count'.")


    except aiosqlite.Error as e:
        logger.error(f"Ошибка SQLite при выполнении миграции: {e}", exc_info=True)
    except Exception as e_global:
        logger.error(f"Непредвиденная ошибка при миграции: {e_global}", exc_info=True)

if __name__ == '__main__':
    asyncio.run(migrate()) 