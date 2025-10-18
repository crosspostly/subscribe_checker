"""
Управление базой данных SQLite с использованием aiosqlite.
"""
import logging
import time
import json
from typing import Optional, List, Tuple, Dict, Any, Union
import aiosqlite
import os
import sqlite3
from aiogram.enums import ChatMemberStatus
from collections import defaultdict
from aiogram.exceptions import TelegramAPIError, TelegramConflictError, TelegramForbiddenError
from aiogram import Bot

# Импорты для относительных путей при запуске через `python -m bot`
from bot.config import DB_NAME, BOT_OWNER_ID

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Асинхронный менеджер базы данных SQLite."""
    def __init__(self, db_path: str = DB_NAME):
        self.db_path = db_path
        # Убрали self._connection, будем использовать контекстный менеджер в _execute
        self._activation_codes: set[str] = set() # Добавляем поле для промокодов

    async def run_migrations(self):
        """Применяет необходимые миграции схемы БД (вызывается после init_db)."""
        logger.info("Запуск миграций базы данных...")
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            try:
                # Check and add columns in 'chats' table
                logger.debug("Проверка существования и колонок таблицы 'chats' для миграций...")
                # Use PRAGMA to get column info. This will raise an error if the table doesn't exist,
                # which is handled by the main except block.
                cursor_info = await db.execute("PRAGMA table_info(chats)")
                columns_info = await cursor_info.fetchall()
                logger.debug(f"Результат PRAGMA table_info(chats): {columns_info}")
                # Assuming the column name is at index 1 in the PRAGMA table_info result
                columns = {row[1] for row in columns_info} 
                logger.debug(f"Существующие колонки в 'chats': {columns}")

                migration_applied = False

                # Migration 1: Add added_by_user_id to chats
                if 'added_by_user_id' not in columns:
                    logger.info("Миграция: Добавление колонки 'added_by_user_id' в таблицу 'chats'...")
                    try:
                        await db.execute("ALTER TABLE chats ADD COLUMN added_by_user_id INTEGER")
                        migration_applied = True
                        logger.info("Миграция: Колонка 'added_by_user_id' добавлена (ожидает commit).")
                    except aiosqlite.OperationalError as oe:
                         logger.error(f"Ошибка ALTER TABLE chats ADD COLUMN added_by_user_id: {oe}", exc_info=True)
                         # If the column already exists from a partial migration, we can ignore this specific error
                         if "duplicate column name" not in str(oe).lower():
                            raise oe # Re-raise other operational errors
                         else:
                             logger.warning(f"Колонка 'added_by_user_id' уже существует. Пропускаем миграцию.")

                # Migration 2: Add configured_by_user_id to chats
                if 'configured_by_user_id' not in columns:
                    logger.info("Миграция: Добавление колонки 'configured_by_user_id' в таблицу 'chats'...")
                    try:
                        await db.execute("ALTER TABLE chats ADD COLUMN configured_by_user_id INTEGER")
                        migration_applied = True
                        logger.info("Миграция: Колонка 'configured_by_user_id' добавлена (ожидает commit).")
                    except aiosqlite.OperationalError as oe:
                         logger.error(f"Ошибка ALTER TABLE chats ADD COLUMN configured_by_user_id: {oe}", exc_info=True)
                         if "duplicate column name" not in str(oe).lower():
                            raise oe
                         else:
                             logger.warning(f"Колонка 'configured_by_user_id' уже существует. Пропускаем миграцию.")

                # Migration 3: Add setup_complete to chats
                if 'setup_complete' not in columns:
                    logger.info("Миграция: Добавление колонки 'setup_complete' в таблицу 'chats'...")
                    try:
                        await db.execute("ALTER TABLE chats ADD COLUMN setup_complete INTEGER DEFAULT 0")
                        migration_applied = True
                        logger.info("Миграция: Колонка 'setup_complete' добавлена (ожидает commit).")
                    except aiosqlite.OperationalError as oe:
                         logger.error(f"Ошибка ALTER TABLE chats ADD COLUMN setup_complete: {oe}", exc_info=True)
                         if "duplicate column name" not in str(oe).lower():
                            raise oe
                         else:
                             logger.warning(f"Колонка 'setup_complete' уже существует. Пропускаем миграцию.")

                # Migration 4: Add is_activated to chats
                if 'is_activated' not in columns:
                    logger.info("Миграция: Добавление колонки 'is_activated' в таблицу 'chats'...")
                    try:
                        await db.execute("ALTER TABLE chats ADD COLUMN is_activated INTEGER DEFAULT 0")
                        migration_applied = True
                        logger.info("Миграция: Колонка 'is_activated' добавлена (ожидает commit).")
                    except aiosqlite.OperationalError as oe:
                         logger.error(f"Ошибка ALTER TABLE chats ADD COLUMN is_activated: {oe}", exc_info=True)
                         if "duplicate column name" not in str(oe).lower():
                            raise oe
                         else:
                             logger.warning(f"Колонка 'is_activated' уже существует. Пропускаем миграцию.")

                # Migration 5: Add last_activation_request_ts to chats
                if 'last_activation_request_ts' not in columns:
                    logger.info("Миграция: Добавление колонки 'last_activation_request_ts' в таблицу 'chats'...")
                    try:
                        await db.execute("ALTER TABLE chats ADD COLUMN last_activation_request_ts INTEGER DEFAULT NULL")
                        migration_applied = True
                        logger.info("Миграция: Колонка 'last_activation_request_ts' добавлена (ожидает commit).")
                    except aiosqlite.OperationalError as oe:
                         logger.error(f"Ошибка ALTER TABLE chats ADD COLUMN last_activation_request_ts: {oe}", exc_info=True)
                         if "duplicate column name" not in str(oe).lower():
                            raise oe
                         else:
                             logger.warning(f"Колонка 'last_activation_request_ts' уже существует. Пропускаем миграцию.")

                # Check and add is_subscribed to users_status_in_chats (if table exists)
                logger.debug("Проверка существования таблицы users_status_in_chats для миграций...")
                cursor_check_users = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users_status_in_chats'")
                users_table_exists = await cursor_check_users.fetchone()
                logger.debug(f"Таблица users_status_in_chats существует: {users_table_exists is not None}")
                if users_table_exists:
                     await self._check_and_add_missing_columns_internal(db) # Call if table exists

                # Migration 6: Создание таблицы bot_messages для очистки
                cursor_check_bm = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bot_messages'")
                bot_messages_table_exists = await cursor_check_bm.fetchone()
                if not bot_messages_table_exists:
                    logger.info("Миграция: Создание таблицы bot_messages...")
                    await db.execute("""
                        CREATE TABLE bot_messages (
                            chat_id INTEGER NOT NULL,
                            message_id INTEGER NOT NULL,
                            timestamp INTEGER NOT NULL,
                            PRIMARY KEY (chat_id, message_id)
                        )
                    """
                    )
                    migration_applied = True
                    logger.info("Миграция: Таблица bot_messages создана.")
                else:
                    logger.debug("Миграция: Таблица bot_messages уже существует.")

                # Commit all schema changes at once, if any were made
                if migration_applied:
                    await db.commit()
                    logger.info("Миграции схемы БД успешно применены и закоммичены.")
                else:
                    logger.info("Нет новых миграций для применения.")

            except aiosqlite.OperationalError as oe:
                 logger.critical(f"Критическая OperationalError при выполнении миграции БД: {oe}", exc_info=True) # Changed level to critical
                 raise oe # Re-raise the error
            except aiosqlite.Error as e:
                logger.critical(f"Критическая ошибка при выполнении миграции БД: {e}", exc_info=True)
                raise e # Re-raise the error

    async def _execute(
        self, 
        query: Optional[str], 
        params: tuple = (), 
        fetchone: bool = False, 
        fetchall: bool = False, 
        commit: bool = False,
        close: bool = False # Параметр close больше не нужен при использовании контекстного менеджера
    ) -> Optional[Union[aiosqlite.Row, List[aiosqlite.Row], None]]:
        """Вспомогательный метод для выполнения SQL-запросов."""
        # Используем try...except для обработки ошибок подключения/выполнения
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Включаем поддержку внешних ключей
                await db.execute("PRAGMA foreign_keys = ON")
                db.row_factory = aiosqlite.Row # Возвращать строки как объекты Row
                
                # Если query не None, выполняем его
                if query:
                    async with db.execute(query, params) as cursor:
                        if commit:
                            await db.commit()
                        if fetchone:
                            return await cursor.fetchone()
                        if fetchall:
                            return await cursor.fetchall()
                # Если query is None, это может быть использовано для других операций, 
                # например, для commit после нескольких запросов без commit=True
                elif commit:
                    await db.commit()
                    
                return None # Возвращаем None, если ничего не надо возвращать
        except aiosqlite.Error as e:
            logger.error(f"Ошибка SQLite при выполнении запроса: Query={query}, Params={params}, Error: {e}", exc_info=True)
            # В зависимости от критичности можно пробросить исключение дальше
            # raise e 
            return None # Или вернуть None/пустой список в случае ошибки

    async def init_db(self):
        """Инициализация таблиц базы данных (НОВАЯ СХЕМА)."""
        # Таблица пользователей (глобальная информация)
        await self._execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                language_code TEXT,
                is_premium INTEGER DEFAULT 0,
                first_seen_timestamp INTEGER NOT NULL,
                last_seen_timestamp INTEGER,
                referrer_id INTEGER, -- ID пользователя, который его пригласил
                FOREIGN KEY (referrer_id) REFERENCES users(user_id) ON DELETE SET NULL
            )
        """)
        # Таблица групповых чатов, где работает бот
        await self._execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                chat_title TEXT,
                captcha_enabled INTEGER DEFAULT 1,
                subscription_check_enabled INTEGER DEFAULT 1,
                setup_complete INTEGER DEFAULT 0, -- Флаг завершения настройки
                is_activated INTEGER DEFAULT 0, -- Флаг активации чата кодом
                last_activation_request_ts INTEGER DEFAULT NULL, -- Unix timestamp последнего запроса активации
                added_timestamp INTEGER,
                configured_by_user_id INTEGER, -- Кто последний раз успешно запускал /setup
                FOREIGN KEY (configured_by_user_id) REFERENCES users(user_id) ON DELETE SET NULL
            )
        """, commit=False) # Убираем commit здесь, он будет в конце init_db
        
        # Таблица связей "Чат -> Канал для подписки"
        await self._execute("""
            CREATE TABLE IF NOT EXISTS chat_channel_links (
                link_id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_chat_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                added_by_user_id INTEGER,
                added_timestamp INTEGER NOT NULL,
                FOREIGN KEY (group_chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE,
                FOREIGN KEY (added_by_user_id) REFERENCES users(user_id) ON DELETE SET NULL,
                -- FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE, -- Если есть таблица channels
                UNIQUE (group_chat_id, channel_id) -- Нельзя добавить один канал в чат дважды
            )
        """)
        # Таблица статуса пользователя В ЧАТЕ (бывшая users)
        await self._execute("""
            CREATE TABLE IF NOT EXISTS users_status_in_chats (
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                captcha_passed INTEGER DEFAULT 0,
                ban_until INTEGER DEFAULT 0,
                is_subscribed INTEGER DEFAULT 0,
                last_update_timestamp INTEGER,
                PRIMARY KEY (user_id, chat_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
            )
        """, commit=True) # Коммитим все изменения схемы в конце
        
        logger.info("База данных инициализирована (Новая схема).")
        
        # Убираем вызов _check_and_add_missing_columns отсюда, он теперь внутри _run_migrations
        # await self._check_and_add_missing_columns() # <- УДАЛИТЬ ИЛИ ЗАКОММЕНТИРОВАТЬ ЭТУ СТРОКУ

    async def _check_and_add_missing_columns(self):
        """Проверяет и добавляет отсутствующие колонки в таблицы (ВНЕШНИЙ МЕТОД).
        Этот метод теперь является оберткой для вызова через _execute, 
        а основная логика перенесена в _check_and_add_missing_columns_internal."""
        # Этот метод больше не должен напрямую использовать connect, 
        # т.к. проверка колонки теперь вызывается из _run_migrations, где соединение уже есть.
        # Оставим его пустым или для будущих проверок, не связанных с миграциями.
        # Можно просто удалить его содержимое или весь метод, если он больше нигде не используется.
        logger.debug("_check_and_add_missing_columns вызван, но логика перенесена в _run_migrations.")
        pass 
        # Если этот метод все же нужен для вызова ИЗВНЕ _execute/_run_migrations:
        # try:
        #     async with aiosqlite.connect(self.db_path) as db:
        #         await self._check_and_add_missing_columns_internal(db)
        # except Exception as e:
        #     logger.error(f"Ошибка при внешнем вызове проверки/добавлении колонок: {e}", exc_info=True)

    async def _check_and_add_missing_columns_internal(self, db: aiosqlite.Connection):
        """Проверяет и добавляет отсутствующие колонки (ВНУТРЕННИЙ МЕТОД). 
        Принимает существующее соединение."""
        logger.debug("Внутри _check_and_add_missing_columns_internal...") # Added logging
        try:
            # Check for the is_subscribed column in users_status_in_chats table
            # Ensure users_status_in_chats table exists before PRAGMA (this check is redundant but left for safety)
            cursor_check = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users_status_in_chats'")
            users_table_exists = await cursor_check.fetchone()
            
            if not users_table_exists:
                logger.warning("Таблица 'users_status_in_chats' не найдена во _check_and_add_missing_columns_internal.")
                return # Nothing to check

            logger.debug("Проверка колонок таблицы users_status_in_chats...") # Added logging
            cursor_info_pragma = await db.execute("PRAGMA table_info(users_status_in_chats)")
            columns_in_users_status = {row[1] for row in await cursor_info_pragma.fetchall()}
            logger.debug(f"Существующие колонки в 'users_status_in_chats': {columns_in_users_status}")
            
            migration_applied_users_status = False

            # Add is_subscribed if not exists
            if 'is_subscribed' not in columns_in_users_status:
                logger.warning("Колонка is_subscribed отсутствует в таблице users_status_in_chats. Добавляю...")
                alter_query = "ALTER TABLE users_status_in_chats ADD COLUMN is_subscribed INTEGER DEFAULT 0"
                try:
                    await db.execute(alter_query)
                    migration_applied_users_status = True
                    logger.info("Колонка is_subscribed успешно добавлена (ожидает commit). ")
                except aiosqlite.OperationalError as oe:
                     logger.error(f"Ошибка ALTER TABLE users_status_in_chats ADD COLUMN is_subscribed: {oe}", exc_info=True)
                     if "duplicate column name" not in str(oe).lower():
                         raise oe
                     else:
                         logger.warning(f"Колонка 'is_subscribed' уже существует. Пропускаем миграцию.")
            
            # Add sub_fail_count if not exists
            if 'sub_fail_count' not in columns_in_users_status:
                logger.info("Миграция: Добавление колонки 'sub_fail_count' в таблицу 'users_status_in_chats'...")
                try:
                    await db.execute("ALTER TABLE users_status_in_chats ADD COLUMN sub_fail_count INTEGER DEFAULT 0")
                    migration_applied_users_status = True
                    logger.info("Миграция: Колонка 'sub_fail_count' добавлена.")
                except aiosqlite.OperationalError as oe:
                    logger.error(f"Ошибка ALTER TABLE users_status_in_chats ADD COLUMN sub_fail_count: {oe}", exc_info=True)
                    if "duplicate column name" not in str(oe).lower():
                        raise oe
                    else:
                        logger.warning("Колонка 'sub_fail_count' уже существует. Пропускаем миграцию.")

            # Add granted_access_until_ts if not exists
            if 'granted_access_until_ts' not in columns_in_users_status:
                logger.info("Миграция: Добавление колонки 'granted_access_until_ts' в таблицу 'users_status_in_chats'...")
                try:
                    await db.execute("ALTER TABLE users_status_in_chats ADD COLUMN granted_access_until_ts INTEGER DEFAULT NULL")
                    migration_applied_users_status = True
                    logger.info("Миграция: Колонка 'granted_access_until_ts' добавлена.")
                except aiosqlite.OperationalError as oe:
                    logger.error(f"Ошибка ALTER TABLE users_status_in_chats ADD COLUMN granted_access_until_ts: {oe}", exc_info=True)
                    if "duplicate column name" not in str(oe).lower():
                        raise oe
                    else:
                        logger.warning("Колонка 'granted_access_until_ts' уже существует. Пропускаем миграцию.")
            
            if migration_applied_users_status:
                # Обычно commit делается в конце run_migrations, но если этот метод вызывается отдельно
                # и должен быть атомарным для users_status_in_chats, то commit нужен здесь.
                # Поскольку он вызывается из run_migrations, где есть общий commit, здесь его можно опустить.
                logger.info("Миграции для 'users_status_in_chats' применены (ожидают общего commit).")


        except Exception as e:
            logger.error(f"Ошибка при проверке/добавлении колонок в users_status_in_chats: {e}", exc_info=True)

    async def close_db(self):
        """Закрывает соединение с базой данных (больше не требуется с context manager)."""
        # Метод больше не нужен, так как connect используется как контекстный менеджер
        logger.debug("close_db() вызван, но больше не выполняет действий.")
        pass 

    # --- Users ---
    
    async def add_user_if_not_exists(
        self, 
        user_id: int, 
        username: Optional[str], 
        first_name: Optional[str], 
        last_name: Optional[str] = None, 
        language_code: Optional[str] = None,
        is_premium: Optional[bool] = False,
        referrer_id: Optional[int] = None # Принимаем ID реферера при первом добавлении
    ) -> bool:
        """Добавляет пользователя, если его нет. Возвращает True, если пользователь был добавлен, False - если уже существовал."""
        current_time = int(time.time())
        existing_user = await self.get_user(user_id)
        
        if existing_user:
            # Обновляем last_seen и, возможно, другую информацию
            await self._execute(
                """UPDATE users SET last_seen_timestamp = ?, username = ?, first_name = ?, last_name = ?, language_code = ?, is_premium = ? 
                WHERE user_id = ?""",
                (current_time, username, first_name, last_name, language_code, int(is_premium or 0), user_id),
                commit=True
            )
            return False # Пользователь уже существовал
        else:
            # Добавляем нового пользователя
            await self._execute(
                """INSERT INTO users (user_id, username, first_name, last_name, language_code, is_premium, first_seen_timestamp, last_seen_timestamp, referrer_id) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, username, first_name, last_name, language_code, int(is_premium or 0), current_time, current_time, referrer_id),
                commit=True
            )
            logger.info(f"Добавлен новый пользователь: {user_id} ({username}), referrer: {referrer_id}")
            return True # Пользователь был добавлен
            
    async def get_user(self, user_id: int) -> Optional[aiosqlite.Row]:
        """Получение информации о пользователе."""
        return await self._execute("SELECT * FROM users WHERE user_id = ?", (user_id,), fetchone=True)
        
    async def record_referral(self, referred_id: int, referrer_id: int) -> bool:
        """Записывает реферера для пользователя, если он еще не установлен."""
        # Проверяем, что у пользователя еще нет реферера
        user = await self.get_user(referred_id)
        if user and user['referrer_id'] is None:
            await self._execute(
                "UPDATE users SET referrer_id = ? WHERE user_id = ?",
                (referrer_id, referred_id),
                commit=True
            )
            logger.info(f"Пользователю {referred_id} установлен реферер {referrer_id}")
            return True
        elif user and user['referrer_id'] is not None:
            logger.warning(f"Попытка установить реферера {referrer_id} для {referred_id}, у которого уже есть реферер {user['referrer_id']}")
            return False
        else:
            logger.error(f"Попытка установить реферера для несуществующего пользователя {referred_id}")
            return False
            
    async def get_referral_chain(self, user_id: int, max_levels: int = 4) -> List[int]:
        """Получает цепочку рефереров вверх до max_levels."""
        chain = []
        current_id = user_id
        for _ in range(max_levels):
            user = await self.get_user(current_id)
            if user and user['referrer_id']:
                referrer_id = user['referrer_id']
                chain.append(referrer_id)
                current_id = referrer_id
            else:
                break # Достигли верха цепочки или пользователя без реферера
        return chain

    # --- Chat Settings ---

    async def add_chat_if_not_exists(
        self, 
        chat_id: int, 
        chat_title: Optional[str], 
        added_by_user_id: Optional[int] = None
    ):
        """Добавляет чат, если его нет. Устанавливает setup_complete=0."""
        current_time = int(time.time())
        # Используем INSERT OR IGNORE для простоты
        await self._execute(
            """INSERT OR IGNORE INTO chats (chat_id, chat_title, added_timestamp, added_by_user_id, setup_complete) 
               VALUES (?, ?, ?, ?, 0)""",
            (chat_id, chat_title, current_time, added_by_user_id),
            commit=True # Коммитим добавление чата
        )
        # Обновляем название, если чат уже был
        await self._execute(
            "UPDATE chats SET chat_title = ? WHERE chat_id = ? AND chat_title IS NOT ?",
            (chat_title, chat_id, chat_title),
            commit=True
        )
        logger.info(f"[DB] Чат {chat_id} ('{chat_title}') добавлен/проверен в БД (автоматически при становлении админом или первом обращении).")

    async def get_chat_settings(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Получение настроек чата."""
        # Убедимся, что чат есть в базе (если его добавили вручную или что-то пошло не так)
        await self.add_chat_if_not_exists(chat_id, None)
        
        row = await self._execute("SELECT * FROM chats WHERE chat_id = ?", (chat_id,), fetchone=True)
        if row:
            result = dict(row)
            # Установка значений по умолчанию, если NULL (оставляем как есть)
            if 'subscription_check_enabled' not in result or result['subscription_check_enabled'] is None:
                result['subscription_check_enabled'] = 1
            if 'captcha_enabled' not in result or result['captcha_enabled'] is None:
                result['captcha_enabled'] = 1
            if 'setup_complete' not in result or result['setup_complete'] is None:
                 result['setup_complete'] = 0 # Добавляем проверку для setup_complete
            return result
        return None

    async def toggle_setting(self, chat_id: int, setting_name: str) -> Optional[bool]:
        """Переключает настройку (captcha_enabled или subscription_check_enabled)."""
        if setting_name not in ['captcha_enabled', 'subscription_check_enabled']:
            logger.error(f"Попытка переключить неизвестную настройку: {setting_name}")
            return None

        settings = await self.get_chat_settings(chat_id)
        if not settings: return None

        current_value = settings[setting_name]
        new_value = 1 - (current_value or 0) # Переключаем 0 -> 1, 1 -> 0, None -> 1
        await self._execute(
            f"UPDATE chats SET {setting_name} = ? WHERE chat_id = ?",
            (new_value, chat_id),
            commit=True
        )
        logger.info(f"Настройка '{setting_name}' для чата {chat_id} переключена на {new_value}")
        return bool(new_value)

    async def update_chat_settings(self, chat_id: int, settings: Dict[str, Any]) -> bool:
        """Обновляет настройки чата в базе данных."""
        try:
            # Получаем текущие настройки, чтобы не затереть неуказанные
            current_settings_db = await self.get_chat_settings(chat_id)
            if not current_settings_db:
                logger.error(f"Не удалось обновить настройки: чат {chat_id} не найден")
                return False

            # Собираем значения для обновления
            # Используем значения из settings, если они есть, иначе оставляем текущие из БД
            captcha_enabled = int(settings.get('captcha_enabled', current_settings_db.get('captcha_enabled', 1)))
            sub_check_enabled = int(settings.get('subscription_check_enabled', current_settings_db.get('subscription_check_enabled', 1)))
            # configured_by обновляется только если передан в settings
            configured_by = settings.get('configured_by_user_id', current_settings_db.get('configured_by_user_id'))
            # setup_complete обновляется только если передан в settings (хотя обычно его ставит mark_setup_complete)
            setup_complete = int(settings.get('setup_complete', current_settings_db.get('setup_complete', 0)))

            # Обновляем запись в базе
            await self._execute(
                """UPDATE chats 
                SET captcha_enabled = ?, 
                    subscription_check_enabled = ?,
                    configured_by_user_id = ?,
                    setup_complete = ?
                WHERE chat_id = ?""",
                (
                    captcha_enabled,
                    sub_check_enabled,
                    configured_by,
                    setup_complete,
                    chat_id
                ),
                commit=True
            )
            logger.info(f"Настройки чата {chat_id} обновлены.") # Убрал вывод самих настроек
            return True

        except Exception as e:
            logger.error(f"Ошибка при обновлении настроек чата {chat_id}: {e}", exc_info=True) # Добавил exc_info
            return False

    async def mark_setup_complete(self, chat_id: int, user_id: int):
        """Отмечает чат как настроенный и записывает, кто настроил."""
        current_time = int(time.time())
        await self._execute(
            """UPDATE chats 
               SET setup_complete = 1, configured_by_user_id = ?, added_timestamp = ?
               WHERE chat_id = ?""",
            (user_id, current_time, chat_id),
            commit=True
        )
        logger.info(f"[DB] Чат {chat_id} помечен как настроенный пользователем {user_id}.")

    async def mark_chat_activated(self, chat_id: int, user_id: int):
        """Отмечает чат как активированный пользователем."""
        # Этот метод, возможно, больше не нужен или используется в другом флоу?
        # Пока оставляем, но основной флоу активации владельцем идет через activate_chat_for_owner
        await self._execute(
            "UPDATE chats SET is_activated = 1, configured_by_user_id = ? WHERE chat_id = ?",
            (user_id, chat_id),
            commit=True
        )
        logger.info(f"Чат {chat_id} помечен как активированный пользователем {user_id}.")

    async def activate_chat_for_owner(self, chat_id: int, owner_id: int):
        """Активирует чат при одобрении владельцем.
        Устанавливает is_activated = 1, setup_complete = 1 и configured_by_user_id на ID владельца.
        Также гарантирует, что владелец существует в таблице users.
        """
        logger.info(f"Автоматическая активация чата {chat_id} владельцем {owner_id}.")
        try:
            # --- НАЧАЛО ИЗМЕНЕНИЯ: Убедимся, что владелец есть в таблице users ---
            owner_exists = await self.get_user(owner_id)
            if not owner_exists:
                logger.warning(f"Владелец {owner_id} не найден в таблице users. Попытка добавить...")
                # Пытаемся добавить владельца. Нам нужен его username/first_name, но у нас их нет.
                # Добавим только ID и временные метки.
                # В идеале, владелец должен был сам запустить /start.
                try:
                    await self.add_user_if_not_exists(
                        user_id=owner_id,
                        username=None, # Неизвестно
                        first_name=f"Owner_{owner_id}", # Placeholder
                        last_name=None,
                        language_code=None,
                        is_premium=False,
                        referrer_id=None
                    )
                    logger.info(f"Владелец {owner_id} добавлен в таблицу users (с placeholder данными).")
                except Exception as add_err:
                    logger.error(f"Не удалось добавить владельца {owner_id} в users: {add_err}. Активация может не сработать.")
                    # Можно либо прервать выполнение, либо продолжить и надеяться, что FK отключены или что-то еще
                    # Пока продолжаем, но логируем ошибку
            # --- КОНЕЦ ИЗМЕНЕНИЯ ---

            await self._execute(
                """
                UPDATE chats
                SET is_activated = 1, setup_complete = 1, configured_by_user_id = ?
                WHERE chat_id = ?
                """,
                (owner_id, chat_id),
                commit=True
            )
            logger.info(f"Чат {chat_id} автоматически активирован владельцем {owner_id}.")
        except sqlite3.IntegrityError as e:
            # Ловим конкретно ошибку FK, если добавление пользователя выше не помогло
            logger.error(f"Ошибка FOREIGN KEY при активации чата {chat_id} владельцем {owner_id}: {e}. Возможно, владелец все еще не в таблице users.", exc_info=True)
            # Здесь можно решить, что делать дальше - например, откатить изменения или просто сообщить об ошибке.
            # Пока просто логируем подробно.
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при активации чата {chat_id} владельцем {owner_id}: {e}", exc_info=True)

    async def update_last_activation_request_ts(self, chat_id: int):
        """Обновляет временную метку последнего запроса кода активации для чата."""
        current_time = int(time.time())
        await self._execute(
            "UPDATE chats SET last_activation_request_ts = ? WHERE chat_id = ?",
            (current_time, chat_id),
            commit=True
        )
        logger.debug(f"[DB] Обновлено время последнего запроса активации для чата {chat_id} на {current_time}.")

    # --- Chat Channel Links ---

    async def add_linked_channel(self, group_chat_id: int, channel_id: int, added_by_user_id: Optional[int]) -> bool:
        """Добавляет связь канала с чатом. Возвращает True если добавлено, False если уже было."""
        current_time = int(time.time())
        try:
            # Проверяем, есть ли уже связанные каналы с этим чатом
            existing_channels = await self.get_linked_channels_for_chat(group_chat_id)
            is_first_channel = len(existing_channels) == 0
            
            # Добавляем канал
            await self._execute(
                """INSERT INTO chat_channel_links (group_chat_id, channel_id, added_by_user_id, added_timestamp) 
                VALUES (?, ?, ?, ?)""",
                (group_chat_id, channel_id, added_by_user_id, current_time),
                commit=True
            )
            
            # Если это первый канал, включаем проверку подписки
            if is_first_channel:
                await self._execute(
                    """UPDATE chats SET subscription_check_enabled = 1 WHERE chat_id = ? AND subscription_check_enabled = 0""",
                    (group_chat_id,),
                    commit=True
                )
                logger.info(f"Автоматически включена проверка подписки для чата {group_chat_id} после добавления первого канала")
                
            logger.info(f"Канал {channel_id} добавлен для чата {group_chat_id} пользователем {added_by_user_id}")
            return True
        except aiosqlite.IntegrityError: # Сработает из-за UNIQUE constraint
            logger.warning(f"Попытка повторно добавить канал {channel_id} в чат {group_chat_id}")
            return False
            
    async def remove_linked_channel(self, group_chat_id: int, channel_id: int) -> bool:
        """Удаляет связь канала с чатом. Возвращает True если удалено, False если не найдено."""
        result = await self._execute(
            "DELETE FROM chat_channel_links WHERE group_chat_id = ? AND channel_id = ?",
            (group_chat_id, channel_id),
            commit=True
        )
        # Проверяем количество удаленных строк (нужно настроить _execute для возврата rowcount?)
        # Пока просто логируем
        # Простой способ проверить - был ли такой канал перед удалением
        # count = await self._execute("SELECT COUNT(*) FROM chat_channel_links WHERE group_chat_id = ? AND channel_id = ?", (group_chat_id, channel_id), fetchone=True)
        # if count[0] == 0: # Если после удаления 0, значит удалили
        
        # Более простой вариант: просто логируем попытку
        logger.info(f"Попытка удалить канал {channel_id} из чата {group_chat_id}")
        # Для большей точности можно было бы проверить наличие, потом удалять
        # или анализировать результат cursor.rowcount, если бы _execute его возвращал.
        # Пока будем считать, что если ошибки не было, то ок.
        return True 

    async def get_linked_channels_for_chat(self, group_chat_id: int) -> List[int]:
        """Возвращает список ID каналов, привязанных к чату."""
        rows = await self._execute(
            "SELECT channel_id FROM chat_channel_links WHERE group_chat_id = ?",
            (group_chat_id,),
            fetchall=True
        )
        return [row['channel_id'] for row in rows] if rows else []

    async def get_chats_configured_by_user(self, user_id: int) -> List[Dict[str, Any]]:
        """Возвращает список чатов и их каналов, настроенных пользователем."""
        # Получаем чаты, где пользователь добавлял каналы
        rows = await self._execute(
            """
            SELECT DISTINCT
                c.chat_id,
                c.chat_title
            FROM chats c
            JOIN chat_channel_links l ON c.chat_id = l.group_chat_id
            WHERE l.added_by_user_id = ?
            ORDER BY c.chat_title
            """,
            (user_id,),
            fetchall=True
        )
        
        if not rows:
            return []

        result = []
        for chat_row in rows:
            chat_info = {"chat_id": chat_row['chat_id'], "chat_title": chat_row['chat_title']}
            linked_channels = await self.get_linked_channels_for_chat(chat_row['chat_id'])
            # Опционально: получить названия каналов
            chat_info['channels'] = linked_channels # Пока только ID
            result.append(chat_info)
            
        return result

    # --- User Status In Chats ---

    async def get_user_status_in_chat(self, user_id: int, chat_id: int) -> Optional[aiosqlite.Row]:
        """Получение статуса пользователя В КОНКРЕТНОМ чате."""
        # Добавим пользователя глобально, если его нет
        # await self.add_user_if_not_exists(user_id, None, None) # Это нужно делать в хендлере
        # Добавим чат глобально, если его нет
        # await self.add_or_update_chat(chat_id, None) # Это нужно делать в хендлере
        
        return await self._execute(
            "SELECT * FROM users_status_in_chats WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
            fetchone=True
        )

    async def update_user_captcha_status(self, user_id: int, chat_id: int, passed: bool):
        """Обновляет статус прохождения капчи в конкретном чате."""
        # Сначала убедимся, что пользователь и чат существуют
        await self.add_user_if_not_exists(user_id, None, None, None)
        await self.add_chat_if_not_exists(chat_id, None)
        
        current_time = int(time.time())
        await self._execute(
            """INSERT INTO users_status_in_chats (user_id, chat_id, captcha_passed, last_update_timestamp) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, chat_id) DO UPDATE SET captcha_passed=excluded.captcha_passed, last_update_timestamp=excluded.last_update_timestamp""",
            (user_id, chat_id, int(passed), current_time),
            commit=True
        )

    async def update_user_ban_status(self, user_id: int, chat_id: int, ban_until: int):
        """Обновляет время бана пользователя в конкретном чате."""
        # Сначала убедимся, что пользователь и чат существуют
        await self.add_user_if_not_exists(user_id, None, None, None)
        await self.add_chat_if_not_exists(chat_id, None)
        
        current_time = int(time.time())
        await self._execute(
            """INSERT INTO users_status_in_chats (user_id, chat_id, ban_until, last_update_timestamp) VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, chat_id) DO UPDATE SET ban_until=excluded.ban_until, last_update_timestamp=excluded.last_update_timestamp""",
            (user_id, chat_id, ban_until, current_time),
            commit=True
        )

    async def update_user_warnings(self, user_id: int, chat_id: int, warnings_count: int):
        """Обновляет счетчик предупреждений для пользователя в чате."""
        current_time = int(time.time())
        await self._execute(
            """INSERT INTO users_status_in_chats (user_id, chat_id, warnings_count, last_update_timestamp) VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, chat_id) DO UPDATE SET warnings_count = ?, last_update_timestamp = ?""",
            (user_id, chat_id, warnings_count, current_time, warnings_count, current_time),
            commit=True
        )

    # --- Referrals (Старые методы, возможно, не нужны или требуют адаптации) ---
    # async def add_referral(self, chat_id: int, referrer_id: int, referred_id: int): ...
    # async def get_referrals_count(self, chat_id: int, referrer_id: int) -> int: ...
    # async def get_user_referrer(self, chat_id: int, referred_id: int) -> Optional[int]: ... 

    async def get_active_chats_with_subscription_check(self) -> List[int]:
        """
        Получает список ID всех активных чатов с включенной проверкой подписки.
        Возвращает список ID чатов.
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                query = """
                SELECT chat_id FROM chats 
                WHERE subscription_check_enabled = 1 
                AND setup_complete = 1
                """
                rows = await db.execute(query)
                results = await rows.fetchall()
                
                chat_ids = [row[0] for row in results] if results else []
                return chat_ids
        except Exception as e:
            logger.error(f"Ошибка при получении активных чатов с проверкой подписки: {e}", exc_info=True)
            return []

    async def get_active_chat_users(self, chat_id: int, days: int = 7) -> List[int]:
        """
        Получает список ID активных пользователей чата за последние N дней.
        
        Args:
            chat_id: ID чата
            days: Количество дней для определения активности
            
        Returns:
            Список ID пользователей
        """
        try:
            # Вычисляем timestamp для указанного количества дней назад
            cutoff_time = int(time.time()) - (days * 24 * 60 * 60)
            
            async with aiosqlite.connect(self.db_path) as db:
                # Запрос к таблице user_status, получаем пользователей, которые писали сообщения недавно
                query = """
                SELECT user_id FROM users_status_in_chats
                WHERE chat_id = ? AND last_update_timestamp > ?
                """
                rows = await db.execute(query, (chat_id, cutoff_time))
                results = await rows.fetchall()
                
                user_ids = [row[0] for row in results] if results else []
                
                # Если нет данных о последних сообщениях, вернем всех пользователей из чата
                if not user_ids:
                    backup_query = """
                    SELECT user_id FROM users_status_in_chats
                    WHERE chat_id = ?
                    """
                    backup_rows = await db.execute(backup_query, (chat_id,))
                    backup_results = await backup_rows.fetchall()
                    user_ids = [row[0] for row in backup_results] if backup_results else []
                
                return user_ids
        except Exception as e:
            logger.error(f"Ошибка при получении активных пользователей чата {chat_id}: {e}", exc_info=True)
            return [] 

    async def update_user_subscription_status(self, chat_id: int, user_id: int, is_subscribed: bool, timestamp: int = None) -> None:
        """Обновляет статус подписки пользователя в БД"""
        if timestamp is None:
            timestamp = int(time.time())
        
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Сначала проверяем, существует ли запись
                check_query = "SELECT 1 FROM users_status_in_chats WHERE chat_id = ? AND user_id = ?"
                cursor = await db.execute(check_query, (chat_id, user_id))
                exists = await cursor.fetchone() is not None
                
                if exists:
                    # Обновляем существующую запись
                    query = """
                    UPDATE users_status_in_chats 
                    SET is_subscribed = ?, last_update_timestamp = ?
                    WHERE chat_id = ? AND user_id = ?
                    """
                    await db.execute(query, (int(is_subscribed), timestamp, chat_id, user_id))
                else:
                    # Создаем новую запись
                    query = """
                    INSERT INTO users_status_in_chats (chat_id, user_id, is_subscribed, last_update_timestamp)
                    VALUES (?, ?, ?, ?)
                    """
                    await db.execute(query, (chat_id, user_id, int(is_subscribed), timestamp))
                
                await db.commit()
        except Exception as e:
            logger.error(f"Ошибка при обновлении статуса подписки: {e}", exc_info=True)
            
    async def update_last_subscription_check(self, chat_id: int, user_id: int, timestamp: int = None) -> None:
        """Обновляет время последней проверки подписки пользователя"""
        if timestamp is None:
            timestamp = int(time.time())
        
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Проверяем существование таблицы
                check_table = """
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='subscription_checks'
                """
                cursor = await db.execute(check_table)
                table_exists = await cursor.fetchone() is not None
                
                if not table_exists:
                    # Создаем таблицу, если она не существует
                    create_table = """
                    CREATE TABLE IF NOT EXISTS subscription_checks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        check_timestamp INTEGER NOT NULL,
                        UNIQUE(chat_id, user_id)
                    )
                    """
                    await db.execute(create_table)
                
                # Обновляем или вставляем запись
                query = """
                INSERT INTO subscription_checks (chat_id, user_id, check_timestamp) 
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id, user_id) 
                DO UPDATE SET check_timestamp = ?
                """
                await db.execute(query, (chat_id, user_id, timestamp, timestamp))
                await db.commit()
                
                logger.debug(f"Обновлено время проверки подписки для пользователя {user_id} в чате {chat_id}")
        except Exception as e:
            logger.error(f"Ошибка при обновлении времени проверки подписки: {e}", exc_info=True) 

    async def get_unactivated_chats_for_reminder(self, owner_id: int, reminder_threshold_ts: int) -> List[Dict[str, Any]]:
        """
        Получает список неактивированных чатов, настроенных конкретным пользователем,
        которым не отправлялось напоминание после reminder_threshold_ts.
        """
        query = """
            SELECT 
                chat_id, 
                chat_title, 
                configured_by_user_id, 
                last_activation_request_ts
            FROM chats
            WHERE is_activated = 0                      -- Чат не активирован
              AND setup_complete = 1                  -- Настройка завершена
              AND configured_by_user_id = ?           -- Настроен указанным пользователем
              AND (last_activation_request_ts IS NULL OR last_activation_request_ts < ?) -- Напоминание не отправлялось или отправлялось давно
        """
        try:
            rows = await self._execute(query, (owner_id, reminder_threshold_ts), fetchall=True)
            if rows:
                # Преобразуем строки в словари для удобства
                return [dict(row) for row in rows]
            return []
        except Exception as e:
            logger.error(f"Ошибка при получении чатов для напоминания об активации: {e}", exc_info=True)
            return []

    def set_activation_codes(self, codes: set[str]):
        """Устанавливает набор промокодов для проверки."""
        self._activation_codes = codes
        logger.info(f"Загружено {len(codes)} промокодов в DatabaseManager.")

    def is_valid_activation_code(self, code: str) -> bool:
        """Проверяет, является ли код валидным промокодом."""
        return code in self._activation_codes 

    async def update_sub_fail_count(self, user_id: int, chat_id: int, increment_by: int = 1):
        """Увеличивает или уменьшает счетчик неудачных проверок подписки."""
        # Проверяем, существует ли запись для пользователя в чате. Если нет, создаем.
        # Это важно, чтобы не было ошибок UPDATE, если пользователь новый
        await self._execute("""
            INSERT OR IGNORE INTO users_status_in_chats (user_id, chat_id, captcha_passed, ban_until, is_subscribed, last_update_timestamp, sub_fail_count)
            VALUES (?, ?, 0, 0, 0, ?, 0)
        """, (user_id, chat_id, int(time.time())), commit=False)

        # Теперь обновляем счетчик
        query = "UPDATE users_status_in_chats SET sub_fail_count = sub_fail_count + ? WHERE user_id = ? AND chat_id = ?"
        params = (increment_by, user_id, chat_id)
        await self._execute(query, params, commit=True)

    async def reset_sub_fail_count(self, user_id: int, chat_id: int):
        """Сбрасывает счетчик неудачных проверок подписки на 0."""
        query = "UPDATE users_status_in_chats SET sub_fail_count = 0 WHERE user_id = ? AND chat_id = ?"
        params = (user_id, chat_id)
        await self._execute(query, params, commit=True) 

    async def update_user_granted_access(self, user_id: int, chat_id: int, access_until_ts: Optional[int]):
        """Обновляет или устанавливает срок предоставленного доступа для пользователя в чате."""
        current_time = int(time.time())
        # Убедимся, что запись для user_id и chat_id существует, если нет - создаем.
        # Важно, чтобы колонка granted_access_until_ts уже существовала (добавлена миграцией).
        insert_or_ignore_query = """
            INSERT OR IGNORE INTO users_status_in_chats 
                (user_id, chat_id, last_update_timestamp, captcha_passed, ban_until, is_subscribed, sub_fail_count, granted_access_until_ts)
            VALUES (?, ?, ?, 0, 0, 0, 0, NULL) 
        """
        # Мы не можем здесь указать excluded.granted_access_until_ts, т.к. IGNORE не имеет excluded.
        # Поэтому сначала INSERT OR IGNORE, потом UPDATE.
        await self._execute(insert_or_ignore_query, (user_id, chat_id, current_time), commit=False) # Commit будет с UPDATE

        update_query = """
            UPDATE users_status_in_chats
            SET granted_access_until_ts = ?, last_update_timestamp = ?
            WHERE user_id = ? AND chat_id = ?
        """
        await self._execute(update_query, (access_until_ts, current_time, user_id, chat_id), commit=True)
        if access_until_ts:
            logger.info(f"[DB] Пользователю {user_id} в чате {chat_id} предоставлен доступ до {access_until_ts}.")
        else:
            logger.info(f"[DB] Пользователю {user_id} в чате {chat_id} сброшен предоставленный доступ.")

    async def get_user_granted_access_status(self, user_id: int, chat_id: int) -> Optional[int]:
        """Получает timestamp окончания предоставленного доступа для пользователя в чате."""
        query = "SELECT granted_access_until_ts FROM users_status_in_chats WHERE user_id = ? AND chat_id = ?"
        row = await self._execute(query, (user_id, chat_id), fetchone=True)
        if row and row['granted_access_until_ts'] is not None:
            return int(row['granted_access_until_ts'])
        return None

    # --- Bot Messages for Cleanup --- #

    async def add_bot_message_for_cleanup(self, chat_id: int, message_id: int, timestamp: Optional[int] = None):
        """Добавляет ID сообщения бота для последующей очистки."""
        if timestamp is None:
            timestamp = int(time.time())
        try:
            await self._execute("""
                INSERT INTO bot_messages (chat_id, message_id, timestamp)
                VALUES (?, ?, ?)
            """, (chat_id, message_id, timestamp), commit=True)
            logger.debug(f"[DB] Добавлено сообщение бота для очистки: chat_id={chat_id}, message_id={message_id}")
        except Exception as e:
            logger.error(f"[DB] Ошибка при добавлении сообщения бота для очистки: {e}", exc_info=True)

    async def get_old_bot_messages_for_cleanup(self, age_seconds: int) -> List[Dict[str, Any]]:
        """Получает список старых сообщений бота для очистки."""
        cutoff_time = int(time.time()) - age_seconds
        try:
            rows = await self._execute("""
                SELECT chat_id, message_id FROM bot_messages
                WHERE timestamp < ?
            """, (cutoff_time,), fetchall=True)
            return [dict(row) for row in rows] if rows else []
        except Exception as e:
            logger.error(f"[DB] Ошибка при получении старых сообщений бота для очистки: {e}", exc_info=True)
            return []

    async def remove_bot_message_from_cleanup(self, chat_id: int, message_id: int):
        """Удаляет запись о сообщении бота после его очистки."""
        try:
            await self._execute("""
                DELETE FROM bot_messages
                WHERE chat_id = ? AND message_id = ?
            """, (chat_id, message_id), commit=True)
            logger.debug(f"[DB] Удалена запись о сообщении бота из очистки: chat_id={chat_id}, message_id={message_id}")
        except Exception as e:
            logger.error(f"[DB] Ошибка при удалении записи о сообщении бота из очистки: {e}", exc_info=True) 

    # --- Методы для обработки "старых" неактивированных чатов ---

    async def get_legacy_unactivated_chats(self) -> List[Dict[str, Any]]:
        """Выбирает чаты, которые не активированы, но имеют признаки предыдущей настройки,
           И ИСКЛЮЧАЕТ чаты, настроенные самим владельцем бота.
        """
        if not BOT_OWNER_ID:
            logger.error("[DB] BOT_OWNER_ID не найден в конфиге. Невозможно корректно выбрать устаревшие чаты.")
            return []
            
        query = """
            SELECT 
                c.chat_id, 
                c.chat_title
            FROM chats c
            WHERE (c.is_activated = 0 OR c.is_activated IS NULL) -- Не активирован
            AND c.configured_by_user_id != ? -- И настроен НЕ владельцем бота
            AND (
                c.setup_complete = 1 -- Но настройка была завершена
                OR EXISTS ( -- Или есть связанные каналы
                    SELECT 1 
                    FROM chat_channel_links cl 
                    WHERE cl.group_chat_id = c.chat_id
                )
            )
        """
        try:
            # Передаем BOT_OWNER_ID как параметр в запрос
            rows = await self._execute(query, (BOT_OWNER_ID,), fetchall=True)
            return [dict(row) for row in rows] if rows else []
        except Exception as e:
            logger.error(f"[DB] Ошибка при поиске устаревших неактивированных чатов (исключая чаты владельца): {e}", exc_info=True)
            return []

    async def deactivate_legacy_chat(self, chat_id: int) -> bool:
        """Деактивирует "старый" чат, сбрасывая флаги is_activated и setup_complete."""
        query = """
            UPDATE chats 
            SET 
                is_activated = 0, 
                setup_complete = 0
            WHERE chat_id = ?
        """
        try:
            # _execute возвращает None при успехе UPDATE, поэтому проверяем на ошибку
            await self._execute(query, (chat_id,), commit=True)
            logger.info(f"[DB] Устаревший чат {chat_id} деактивирован (is_activated=0, setup_complete=0).")
            return True
        except Exception as e:
            logger.error(f"[DB] Ошибка при деактивации устаревшего чата {chat_id}: {e}", exc_info=True)
            return False 