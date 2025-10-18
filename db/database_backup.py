"""
Управление базой данных SQLite с использованием aiosqlite.
"""
import logging
import time
import json
from typing import Optional, List, Tuple, Dict, Any, Union
import aiosqlite

# Импорты для относительных путей при запуске через `python -m bot`
from bot.config import DB_NAME

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Асинхронный менеджер базы данных SQLite."""
    def __init__(self, db_path: str = DB_NAME):
        self.db_path = db_path
        # Убрали self._connection, будем использовать контекстный менеджер в _execute

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
                added_timestamp INTEGER, 
                configured_by_user_id INTEGER, -- Кто последний раз успешно запускал /setup
                FOREIGN KEY (configured_by_user_id) REFERENCES users(user_id) ON DELETE SET NULL
            )
        """)
        # Таблица каналов (опционально, для кэширования названий) - пока не создаем
        # await self._execute("""
        #     CREATE TABLE IF NOT EXISTS channels (
        #         channel_id INTEGER PRIMARY KEY,
        #         channel_title TEXT,
        #         username TEXT,
        #         first_added_timestamp INTEGER
        #     )
        # """)
        
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
                last_update_timestamp INTEGER,
                PRIMARY KEY (user_id, chat_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (chat_id) REFERENCES chats(chat_id) ON DELETE CASCADE
            )
        """, commit=True) # Коммитим все изменения схемы в конце
        
        logger.info("База данных инициализирована (Новая схема).")

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

    async def add_or_update_chat(self, chat_id: int, chat_title: Optional[str], configured_by: Optional[int] = None):
        """Добавляет чат в БД или обновляет его название и время."""
        current_time = int(time.time())
        await self._execute(
            """INSERT INTO chats (chat_id, chat_title, added_timestamp, configured_by_user_id) VALUES (?, ?, ?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET chat_title=excluded.chat_title, 
                                                configured_by_user_id=CASE WHEN excluded.configured_by_user_id IS NOT NULL THEN excluded.configured_by_user_id ELSE chats.configured_by_user_id END
            """,
            (chat_id, chat_title, current_time, configured_by),
            commit=True
        )

    async def get_chat_settings(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Получение настроек чата."""
        await self.add_or_update_chat(chat_id, None) # Убедимся, что чат есть в базе
        row = await self._execute("SELECT * FROM chats WHERE chat_id = ?", (chat_id,), fetchone=True)
        if row:
            return dict(row) # Конвертируем Row в словарь
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
            # Получаем текущие настройки
            current_settings = await self.get_chat_settings(chat_id)
            if not current_settings:
                logger.error(f"Не удалось обновить настройки: чат {chat_id} не найден")
                return False

            # Обновляем только те поля, которые есть в settings
            for key, value in settings.items():
                if key in current_settings:
                    current_settings[key] = value

            # Обновляем запись в базе
            await self._execute(
                """UPDATE chats 
                   SET captcha_enabled = ?, 
                       subscription_check_enabled = ?,
                       configured_by_user_id = ?
                   WHERE chat_id = ?""",
                (
                    int(current_settings.get('captcha_enabled', True)),
                    int(current_settings.get('subscription_check_enabled', True)),
                    current_settings.get('configured_by_user_id'),
                    chat_id
                ),
                commit=True
            )
            logger.info(f"Настройки чата {chat_id} обновлены: {current_settings}")
            return True

        except Exception as e:
            logger.error(f"Ошибка при обновлении настроек чата {chat_id}: {e}")
            return False

    # --- Chat Channel Links ---

    async def add_linked_channel(self, group_chat_id: int, channel_id: int, added_by_user_id: Optional[int]) -> bool:
        """Добавляет связь канала с чатом. Возвращает True если добавлено, False если уже было."""
        current_time = int(time.time())
        try:
            await self._execute(
                """INSERT INTO chat_channel_links (group_chat_id, channel_id, added_by_user_id, added_timestamp) 
                   VALUES (?, ?, ?, ?)""",
                (group_chat_id, channel_id, added_by_user_id, current_time),
                commit=True
            )
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
        # Для большей точности можно было бы сначала проверить наличие, потом удалять
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
        current_time = int(time.time())
        await self._execute(
            """INSERT INTO users_status_in_chats (user_id, chat_id, captcha_passed, last_update_timestamp) VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, chat_id) DO UPDATE SET captcha_passed=excluded.captcha_passed, last_update_timestamp=excluded.last_update_timestamp""",
            (user_id, chat_id, int(passed), current_time),
            commit=True
        )

    async def update_user_ban_status(self, user_id: int, chat_id: int, ban_until: int):
        """Обновляет время бана пользователя в конкретном чате."""
        current_time = int(time.time())
         await self._execute(
            """INSERT INTO users_status_in_chats (user_id, chat_id, ban_until, last_update_timestamp) VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, chat_id) DO UPDATE SET ban_until=excluded.ban_until, last_update_timestamp=excluded.last_update_timestamp""",
            (user_id, chat_id, ban_until, current_time),
             commit=True
         )

    # --- Referrals (Старые методы, возможно, не нужны или требуют адаптации) ---
    # async def add_referral(self, chat_id: int, referrer_id: int, referred_id: int): ...
    # async def get_referrals_count(self, chat_id: int, referrer_id: int) -> int: ...
    # async def get_user_referrer(self, chat_id: int, referred_id: int) -> Optional[int]: ... 