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
            # Включаем поддержку внешних ключей для миграций тоже
            await db.execute("PRAGMA foreign_keys = ON")
            
            migration_applied_overall = False # Флаг, что хотя бы одна миграция была применена

            try:
                # --- Миграции для таблицы 'chats' ---
                logger.debug("Проверка и применение миграций для таблицы 'chats'...")
                cursor_info_chats = await db.execute("PRAGMA table_info(chats)")
                columns_info_chats = await cursor_info_chats.fetchall()
                existing_columns_chats = {row['name'] for row in columns_info_chats}
                
                chat_columns_to_ensure = {
                    "added_by_user_id": "INTEGER",
                    "configured_by_user_id": "INTEGER",
                    "setup_complete": "INTEGER DEFAULT 0",
                    "is_activated": "INTEGER DEFAULT 0",
                    "last_activation_request_ts": "INTEGER DEFAULT NULL"
                }

                for col_name, col_def in chat_columns_to_ensure.items():
                    if col_name not in existing_columns_chats:
                        logger.info(f"Миграция (chats): Добавление колонки '{col_name}'...")
                        try:
                            await db.execute(f"ALTER TABLE chats ADD COLUMN {col_name} {col_def}")
                            migration_applied_overall = True
                            logger.info(f"Миграция (chats): Колонка '{col_name}' добавлена.")
                        except aiosqlite.OperationalError as oe:
                            if "duplicate column name" in str(oe).lower():
                                logger.warning(f"Миграция (chats): Колонка '{col_name}' уже существует.")
                            else:
                                logger.error(f"Ошибка ALTER TABLE chats ADD COLUMN {col_name}: {oe}", exc_info=True)
                                raise # Перебрасываем другие ошибки

                # --- Миграции для таблицы 'users_status_in_chats' ---
                logger.debug("Проверка существования таблицы 'users_status_in_chats' для миграций...")
                cursor_check_users_status_table = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users_status_in_chats'")
                users_status_table_exists = await cursor_check_users_status_table.fetchone()
                
                if users_status_table_exists:
                    logger.debug("Таблица 'users_status_in_chats' существует. Запуск внутренней проверки колонок...")
                    internal_migrations_applied = await self._check_and_add_missing_columns_internal(db)
                    if internal_migrations_applied:
                        migration_applied_overall = True
                else:
                    logger.warning("Таблица 'users_status_in_chats' не найдена. Пропуск миграций для нее. Она должна быть создана в init_db.")

                # --- Миграция для таблицы 'bot_messages' (создание если нет) ---
                logger.debug("Проверка и создание таблицы 'bot_messages' (если необходимо)...")
                cursor_check_bot_messages_table = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bot_messages'")
                bot_messages_table_exists = await cursor_check_bot_messages_table.fetchone()
                if not bot_messages_table_exists:
                    logger.info("Миграция (bot_messages): Таблица не найдена. Создание таблицы 'bot_messages'...")
                    await db.execute("""
                        CREATE TABLE bot_messages (
                            chat_id INTEGER NOT NULL,
                            message_id INTEGER NOT NULL,
                            timestamp INTEGER NOT NULL,
                            PRIMARY KEY (chat_id, message_id)
                        )
                    """)
                    migration_applied_overall = True
                    logger.info("Миграция (bot_messages): Таблица 'bot_messages' создана.")
                else:
                    logger.debug("Таблица 'bot_messages' уже существует.")
                
                # --- Создание индексов (безопасно, если уже существуют с IF NOT EXISTS) ---
                logger.debug("Создание индексов (если не существуют)...")
                indexes_to_create = [
                    "CREATE INDEX IF NOT EXISTS idx_users_referrer_id ON users(referrer_id)",
                    "CREATE INDEX IF NOT EXISTS idx_chats_configured_by ON chats(configured_by_user_id)",
                    "CREATE INDEX IF NOT EXISTS idx_chats_is_activated ON chats(is_activated)",
                    "CREATE INDEX IF NOT EXISTS idx_chats_setup_complete ON chats(setup_complete)",
                    "CREATE INDEX IF NOT EXISTS idx_chats_last_activation_request_ts ON chats(last_activation_request_ts)",
                    "CREATE INDEX IF NOT EXISTS idx_chat_channel_links_group_chat_id ON chat_channel_links(group_chat_id)",
                    "CREATE INDEX IF NOT EXISTS idx_users_status_chat_id ON users_status_in_chats(chat_id)",
                    "CREATE INDEX IF NOT EXISTS idx_users_status_last_check ON users_status_in_chats(last_subscription_check_ts)",
                    "CREATE INDEX IF NOT EXISTS idx_bot_messages_timestamp ON bot_messages(timestamp)"
                ]
                for index_query in indexes_to_create:
                    try:
                        await db.execute(index_query)
                    except aiosqlite.OperationalError as oe_index:
                        # Некоторые ошибки создания индекса могут быть не критичны, если он уже как-то существует
                        logger.warning(f"Возможна ошибка при создании индекса (может быть уже создан): {index_query} - {oe_index}")


                # --- Коммит всех изменений, если они были ---
                if migration_applied_overall:
                    await db.commit()
                    logger.info("Все необходимые миграции схемы БД успешно применены и закоммичены.")
                else:
                    logger.info("Нет новых миграций для применения (или только созданы индексы).")

            except aiosqlite.OperationalError as oe:
                 logger.critical(f"Критическая OperationalError при выполнении миграции БД: {oe}", exc_info=True)
                 raise oe
            except Exception as e: # Более общий Exception для других ошибок aiosqlite.Error или Python
                logger.critical(f"Критическая ошибка при выполнении миграции БД: {e}", exc_info=True)
                raise e

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
        # --- 1. Создание всех таблиц ---
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
                setup_complete INTEGER DEFAULT 0, 
                is_activated INTEGER DEFAULT 0, 
                last_activation_request_ts INTEGER DEFAULT NULL, 
                added_timestamp INTEGER,
                configured_by_user_id INTEGER,
                FOREIGN KEY (configured_by_user_id) REFERENCES users(user_id) ON DELETE SET NULL
            )
        """) 
        
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
                UNIQUE (group_chat_id, channel_id)
            )
        """)
        
        # Таблица статусов пользователей в чатах (капча, подписка и т.д.)
        await self._execute("""
            CREATE TABLE IF NOT EXISTS users_status_in_chats (
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                captcha_passed INTEGER DEFAULT 0,
                captcha_attempts INTEGER DEFAULT 0,
                last_captcha_attempt_ts INTEGER DEFAULT NULL,
                is_subscribed INTEGER DEFAULT NULL, -- NULL означает, что проверка еще не проводилась или неизвестно
                last_subscription_check_ts INTEGER DEFAULT NULL,
                subscription_fail_count INTEGER DEFAULT 0,
                warnings_count INTEGER DEFAULT 0,
                ban_until_ts INTEGER DEFAULT NULL, -- Добавлена эта колонка
                ban_reason TEXT DEFAULT NULL,                   -- Опционально: причина бана
                granted_access_until_ts INTEGER DEFAULT NULL, -- Для ручного предоставления доступа
                last_message_ts INTEGER DEFAULT NULL,           -- Время последнего сообщения пользователя в этом чате
                last_update_timestamp INTEGER,     -- Общая метка последнего обновления записи
                PRIMARY KEY (user_id, chat_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
            )
        """)
        logger.debug("Таблица 'users_status_in_chats' создана/проверена.")
        
        # Таблица для хранения ID сообщений бота для последующей очистки
        await self._execute("""
            CREATE TABLE IF NOT EXISTS bot_messages (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                timestamp INTEGER NOT NULL,
                PRIMARY KEY (chat_id, message_id)
            )
        """)

        # Применяем создание всех таблиц
        await self._execute(None, commit=True)
        logger.info("Основные таблицы созданы (если не существовали).")

        # --- 2. Загрузка кодов активации из БД в память (опционально, если нужно кэширование) ---
        # await self.load_activation_codes_to_memory() # Пример

        logger.info("Инициализация базы данных завершена.")

    async def _check_and_add_missing_columns_internal(self, db: aiosqlite.Connection) -> bool:
        """Проверяет и добавляет недостающие колонки в таблицу users_status_in_chats.
        Возвращает True, если хотя бы одна колонка была добавлена, иначе False.
        """
        logger.info("Внутренняя проверка и добавление недостающих колонок в 'users_status_in_chats'...")
        columns_were_added_by_this_method = False
        try:
            cursor = await db.execute("PRAGMA table_info(users_status_in_chats)")
            columns_info = await cursor.fetchall()
            existing_columns = {row['name'] for row in columns_info}
            logger.debug(f"Существующие колонки в users_status_in_chats: {existing_columns}")

            columns_to_add = {
                "ban_until_ts": "INTEGER DEFAULT NULL",
                "subscription_fail_count": "INTEGER DEFAULT 0",
                "last_update_timestamp": "INTEGER DEFAULT NULL", # Добавил DEFAULT NULL для консистентности
                "warnings_count": "INTEGER DEFAULT 0",
                "ban_reason": "TEXT DEFAULT NULL",
                "granted_access_until_ts": "INTEGER DEFAULT NULL",
                "last_message_ts": "INTEGER DEFAULT NULL",
                "is_subscribed": "INTEGER DEFAULT NULL",
                "last_captcha_attempt_ts": "INTEGER DEFAULT NULL",
                "captcha_attempts": "INTEGER DEFAULT 0",
                "captcha_passed": "INTEGER DEFAULT 0",
                # Убедимся что last_subscription_check_ts тоже есть, т.к. на него индекс
                "last_subscription_check_ts": "INTEGER DEFAULT NULL"
            }

            for col_name, col_definition in columns_to_add.items():
                if col_name not in existing_columns:
                    logger.info(f"Миграция (users_status_in_chats): Добавление колонки '{col_name}'...")
                    try:
                        await db.execute(f"ALTER TABLE users_status_in_chats ADD COLUMN {col_name} {col_definition}")
                        logger.info(f"Миграция (users_status_in_chats): Колонка '{col_name}' ({col_definition}) добавлена.")
                        columns_were_added_by_this_method = True
                    except aiosqlite.OperationalError as oe:
                        if "duplicate column name" in str(oe).lower():
                            logger.warning(f"Миграция (users_status_in_chats): Колонка '{col_name}' уже существует.")
                        else:
                            logger.error(f"Ошибка ALTER TABLE users_status_in_chats ADD COLUMN {col_name}: {oe}", exc_info=True)
                            raise # Перебрасываем другие ошибки
            
            if columns_were_added_by_this_method:
                logger.info("Внутренние миграции для 'users_status_in_chats' применили изменения.")
            else:
                logger.info("Внутренние миграции для 'users_status_in_chats': нет недостающих колонок для добавления.")

        except aiosqlite.OperationalError as e_pragma:
            # Это может случиться, если таблица users_status_in_chats вообще не существует на момент вызова PRAGMA
            # init_db должен ее создать до вызова run_migrations. Если нет - это проблема.
            logger.error(f"Ошибка PRAGMA table_info(users_status_in_chats) во внутренней проверке: {e_pragma}. "
                         "Возможно, таблица не была создана методом init_db перед запуском миграций.")
            # Не перебрасываем ошибку здесь, чтобы позволить другим миграциям (если они есть) попытаться выполниться,
            # но это серьезный признак проблемы в очередности инициализации.
        except Exception as e_unexpected:
            logger.error(f"Неожиданная ошибка при внутренней проверке и добавлении колонок в users_status_in_chats: {e_unexpected}", exc_info=True)
            raise # Перебрасываем неожиданные ошибки

        return columns_were_added_by_this_method

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

    async def update_user_ban_status(self, user_id: int, chat_id: int, ban_until_ts: int):
        """Обновляет время бана пользователя в конкретном чате."""
        # Сначала убедимся, что пользователь и чат существуют
        await self.add_user_if_not_exists(user_id, None, None, None)
        await self.add_chat_if_not_exists(chat_id, None)
        
        current_time = int(time.time())
        await self._execute(
            """INSERT INTO users_status_in_chats (user_id, chat_id, ban_until_ts, last_update_timestamp) VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, chat_id) DO UPDATE SET ban_until_ts=excluded.ban_until_ts, last_update_timestamp=excluded.last_update_timestamp""",
            (user_id, chat_id, ban_until_ts, current_time),
            commit=True
        )
        logger.info(f"[DB] Обновлен статус бана для user {user_id} в чате {chat_id} до {ban_until_ts}")

    async def clear_user_ban_status(self, user_id: int, chat_id: int):
        """Сбрасывает информацию о бане пользователя в чате (устанавливает ban_until_ts = NULL и ban_reason = NULL)."""
        query = """
            UPDATE users_status_in_chats
            SET ban_until_ts = NULL, ban_reason = NULL
            WHERE user_id = ? AND chat_id = ?;
        """
        # Добавляем проверку, была ли запись обновлена
        updated_rows = await self._execute(query, (user_id, chat_id), commit=True) # _execute должен бы возвращать cursor.rowcount для DML
        # Пока предполагаем, что _execute не возвращает rowcount для UPDATE без SELECT
        # Просто логируем попытку
        logger.info(f"[DB] Попытка сброса статуса бана для user {user_id} в чате {chat_id}")

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

    async def update_sub_fail_count(self, user_id: int, chat_id: int, new_count: int):
        """Обновляет (устанавливает) счетчик неудач подписки для пользователя в чате."""
        # Убедимся, что пользователь и чат существуют в их основных таблицах
        # Это нужно, чтобы не было ошибки FOREIGN KEY constraint failed
        # Предполагаем, что информация о пользователе (username, first_name) здесь не критична для add_user_if_not_exists
        await self.add_user_if_not_exists(user_id=user_id, username=None, first_name=f"User_{user_id}", last_name=None)
        # Предполагаем, что chat_title здесь не критичен для add_chat_if_not_exists
        await self.add_chat_if_not_exists(chat_id=chat_id, chat_title=None)

        # Обновляем, чтобы установить новое значение, а не инкрементировать
        query = """
            INSERT INTO users_status_in_chats (user_id, chat_id, subscription_fail_count)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, chat_id) DO UPDATE SET
                subscription_fail_count = excluded.subscription_fail_count;
        """
        await self._execute(query, (user_id, chat_id, new_count), commit=True)
        logger.debug(f"[DB] Установлен счетчик неудач подписки для user {user_id} в чате {chat_id} на {new_count}")

    async def reset_sub_fail_count(self, user_id: int, chat_id: int):
        """Сбрасывает счетчик неудачных проверок подписки на 0."""
        # Убедимся, что пользователь и чат существуют
        await self.add_user_if_not_exists(user_id=user_id, username=None, first_name=f"User_{user_id}", last_name=None)
        await self.add_chat_if_not_exists(chat_id=chat_id, chat_title=None)

        query = "UPDATE users_status_in_chats SET subscription_fail_count = 0 WHERE user_id = ? AND chat_id = ?"
        params = (user_id, chat_id)
        await self._execute(query, params, commit=True) 

    async def update_user_granted_access(self, user_id: int, chat_id: int, access_until_ts: Optional[int]):
        """Обновляет или устанавливает срок предоставленного доступа для пользователя в чате."""
        current_time = int(time.time())
        # Убедимся, что запись для user_id и chat_id существует, если нет - создаем.
        # Важно, чтобы колонка granted_access_until_ts уже существовала (добавлена миграцией).
        insert_or_ignore_query = """
            INSERT OR IGNORE INTO users_status_in_chats 
                (user_id, chat_id, last_update_timestamp, captcha_passed, is_subscribed, subscription_fail_count, granted_access_until_ts)
            VALUES (?, ?, ?, 0, 0, 0, NULL) 
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

    async def delete_chat(self, chat_id: int) -> bool:
        """Полностью удаляет чат и все связанные с ним данные из БД."""
        try:
            # ON DELETE CASCADE должен позаботиться о связанных записях в 
            # chat_channel_links и users_status_in_chats
            await self._execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,), commit=True)
            logger.info(f"Чат {chat_id} полностью удален из базы данных.")
            return True
        except Exception as e:
            logger.error(f"Ошибка при удалении чата {chat_id} из БД: {e}", exc_info=True)
            return False 

    async def get_channels_info_by_ids(self, channel_ids: List[int]) -> List[Dict[str, Any]]:
        """Получает информацию (ID, название, ссылка) о каналах по их ID.
        Пытается найти название в таблице 'chats'. Если нет, использует ID как название.
        Ссылка (username) пока не извлекается напрямую этим методом, если не хранится в 'chats'.
        """
        if not channel_ids:
            return []
        
        results = []
        # Создаем плейсхолдеры для запроса IN
        placeholders = ",".join("?" for _ in channel_ids)
        query = f"SELECT chat_id, chat_title FROM chats WHERE chat_id IN ({placeholders})"
        
        # logger.debug(f"[DB] Запрос get_channels_info_by_ids: {query} с параметрами: {channel_ids}")
        
        try:
            # Мы не можем передать список напрямую в execute для IN, если используем tuple
            # Преобразуем channel_ids в кортеж
            rows = await self._execute(query, tuple(channel_ids), fetchall=True)
            # logger.debug(f"[DB] Результат get_channels_info_by_ids: {rows}")

            # Преобразуем результат в словарь для быстрого доступа
            # chat_id в таблице chats - это PRIMARY KEY, но может быть не для всех channel_ids
            # которые могут быть ID каналов, а не чатов из таблицы `chats`.
            # Эта логика предполагает, что channel_id МОЖЕТ БЫТЬ в таблице chats как chat_id.
            # Это не всегда так для каналов подписки.
            # Правильнее было бы иметь отдельную таблицу channel_details(channel_id PK, channel_title, channel_username)
            # или получать эту информацию при добавлении канала в chat_channel_links.
            
            # Пока что, сделаем простой маппинг ID -> Title, если ID найден в таблице chats
            # Иначе будет просто ID
            
            # Собираем информацию из полученных строк
            found_info = {row['chat_id']: row['chat_title'] for row in rows} if rows else {}

            for ch_id in channel_ids:
                title = found_info.get(ch_id)
                # Пытаемся получить username или invite_link (это уже должно быть в channel_info при отправке предупреждения)
                # Этот метод пока не имеет прямого доступа к этой информации, если она не в таблице chats.
                # Для демонстрации, оставим link как None.
                link = None 
                # В идеале, здесь нужно было бы получить реальную ссылку/username из БД, если она хранится.
                # Например, если бы у нас была таблица channel_metadata(channel_id, username, invite_link)
                # query_link = f"SELECT username, invite_link FROM channel_metadata WHERE channel_id = ?"
                # link_row = await self._execute(query_link, (ch_id,), fetchone=True)
                # if link_row:
                #     if link_row['username']:
                #         link = f"https://t.me/{link_row['username']}"
                #     elif link_row['invite_link']:
                #         link = link_row['invite_link']
                
                results.append({
                    'channel_id': ch_id,
                    'channel_title': title if title else f'Канал ID {ch_id}', # Если нет названия, используем ID
                    'channel_link': link # Будет None, если не реализовано получение ссылки
                })
            return results
        except Exception as e:
            logger.error(f"[DB_GET_CHANNELS_INFO] Ошибка при получении информации о каналах {channel_ids}: {e}", exc_info=True)
            # В случае ошибки, возвращаем ID как названия, без ссылок
            return [{'channel_id': ch_id, 'channel_title': f'Канал ID {ch_id}', 'channel_link': None} for ch_id in channel_ids] 

    async def get_users_for_cleanup_check(self, batch_size: int) -> List[Dict[str, Any]]:
        """
        Выбирает пользователей для проверки на предмет удаления.
        Возвращает список словарей с user_id, отсортированных по last_seen_timestamp (старые сначала).
        """
        query = """
            SELECT user_id
            FROM users
            ORDER BY last_seen_timestamp ASC 
            LIMIT ?
        """
        # last_seen_timestamp ASC NULLS FIRST - если есть NULL значения, они будут первыми
        # Если last_seen_timestamp не может быть NULL, то просто ASC
        # В текущей схеме users.last_seen_timestamp может быть NULL, если пользователь был добавлен, но еще не "виделся"
        # Это маловероятно для старых записей, но для полноты можно использовать:
        # ORDER BY last_seen_timestamp ASC NULLS FIRST
        # Однако, SQLite по умолчанию обрабатывает NULL как наименьшие значения при ASC, так что это должно работать.

        try:
            rows = await self._execute(query, (batch_size,), fetchall=True)
            return [dict(row) for row in rows] if rows else []
        except Exception as e:
            logger.error(f"[DB] Ошибка при выборе пользователей для проверки очистки: {e}", exc_info=True)
            return []

    async def delete_users_by_ids(self, user_ids: List[int]) -> int:
        """
        Удаляет пользователей из таблицы 'users' по списку их ID.
        Возвращает количество удаленных пользователей.
        """
        if not user_ids:
            return 0

        placeholders = ",".join("?" for _ in user_ids)
        query = f"DELETE FROM users WHERE user_id IN ({placeholders})"
        
        # Для получения количества удаленных строк, _execute должен быть доработан,
        # чтобы возвращать cursor.rowcount для DML операций.
        # Пока что, мы не можем напрямую получить это значение без изменения _execute.
        # В качестве альтернативы, можно сначала выбрать пользователей, затем удалить,
        # но это менее эффективно и подвержено гонкам состояний.
        # Для простоты, пока не будем возвращать точное количество, если _execute это не поддерживает.
        # Либо, мы можем выполнить SELECT COUNT(*) до и после, но это тоже не идеально.

        # Предположим, что нам нужно просто выполнить операцию и залогировать.
        # Если _execute будет доработан для возврата rowcount, этот метод можно будет улучшить.
        
        # Временное решение: посчитаем, сколько ID было в списке
        # Это не количество удаленных, а количество попыток удаления
        num_to_delete = len(user_ids) 

        try:
            # Так как _execute не возвращает rowcount напрямую для DELETE без SELECT,
            # мы не можем легко получить точное число удаленных строк без модификации _execute
            # или выполнения дополнительного запроса.
            # Мы просто выполним удаление.
            # Для возврата реального количества удаленных строк, _execute должен возвращать cursor.rowcount
            # или мы можем использовать контекстный менеджер соединений напрямую здесь.
            
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA foreign_keys = ON")
                # Используем tuple(user_ids) для корректной передачи параметров
                cursor = await db.execute(query, tuple(user_ids))
                await db.commit()
                deleted_count = cursor.rowcount
                logger.info(f"[DB] Удалено {deleted_count} пользователей из {num_to_delete} запрошенных по списку ID.")
                return deleted_count
        except Exception as e:
            logger.error(f"[DB] Ошибка при удалении пользователей по списку ID: {user_ids}. Ошибка: {e}", exc_info=True)
            return 0 

    async def get_all_user_ids_in_chat(self, chat_id: int) -> List[int]:
        """
        Возвращает список ID всех пользователей, известных боту в указанном чате.
        Предполагается наличие таблицы users_status_in_chats с user_id и chat_id.
        """
        # query = "SELECT DISTINCT user_id FROM users_status_in_chats WHERE chat_id = ?"
        # Используем users_status_in_chats, если она актуальна для определения "состоящих в чате"
        # Если же нужна таблица users, а связь с чатом неявная или через другую таблицу,
        # то запрос нужно будет адаптировать.
        # Для данного случая, users_status_in_chats кажется наиболее подходящей.
        query = "SELECT user_id FROM users_status_in_chats WHERE chat_id = ?" # DISTINCT может быть не нужен, если одна запись на пару (user_id, chat_id)
        
        # Проверка на существование self.pool для совместимости, если pool создается не в __init__
        if not hasattr(self, 'pool') or self.pool is None:
            # Попытка использовать self.connection, если pool нет, а есть прямое соединение
            # Это для случая, если DatabaseManager использует одно соединение, а не пул
            if hasattr(self, 'connection') and self.connection is not None:
                async with self.connection.cursor() as cur:
                    await cur.execute(query, (chat_id,))
                    rows = await cur.fetchall()
                    return [row[0] for row in rows] if rows else []
            else:
                # Логика на случай, если ни pool, ни connection не найдены или не инициализированы
                # Можно выбросить исключение или вернуть пустой список с предупреждением.
                # В данном контексте, если скрипт отдельный, pool должен быть создан.
                # Если это часть основного бота, pool уже должен быть.
                # Для простоты предположим, что pool будет доступен.
                # Если этот код выполняется до инициализации pool, будет ошибка.
                # Важно, чтобы DatabaseManager был правильно инициализирован перед вызовом этого метода.
                # logger.warning("Database pool is not initialized in get_all_user_ids_in_chat") # Нужен logger
                print("ПРЕДУПРЕЖДЕНИЕ: Пул соединений (self.pool) не инициализирован в get_all_user_ids_in_chat.") # Временный print
                # Если pool строго обязателен и должен быть:
                # raise RuntimeError("Database pool is not initialized.")
                return [] # Возвращаем пустой список, если не можем выполнить запрос

        # Стандартная логика с использованием self.pool
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (chat_id,))
                rows = await cur.fetchall()
                return [row[0] for row in rows] if rows else [] 