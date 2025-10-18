import asyncio
import aiosqlite
import os

DATABASE_PATH = 'bot_data.db' # Укажите правильный путь к вашей БД

async def migrate():
    print(f"Connecting to database: {DATABASE_PATH}")
    if not os.path.exists(DATABASE_PATH):
        print(f"Error: Database file not found at {DATABASE_PATH}")
        return

    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row # Убедимся, что строки возвращаются как Row объекты

            # Проверяем наличие столбца ban_until_ts в таблице users_status_in_chats
            cursor = await db.execute("PRAGMA table_info(users_status_in_chats);")
            columns = await cursor.fetchall()
            column_names = [col['name'] for col in columns]

            if 'ban_until_ts' not in column_names:
                print("Column 'ban_until_ts' not found. Adding it...")
                # Добавляем столбец
                await db.execute("ALTER TABLE users_status_in_chats ADD COLUMN ban_until_ts INTEGER DEFAULT NULL;")
                await db.commit()
                print("Column 'ban_until_ts' added successfully.")
            else:
                print("Column 'ban_until_ts' already exists. No migration needed.")

    except Exception as e:
        print(f"An error occurred during migration: {e}")

if __name__ == "__main__":
    asyncio.run(migrate()) 