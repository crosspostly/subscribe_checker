import asyncio
import logging
import os
import sys
import time # Для задержек

from telethon import TelegramClient
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.types import ChatBannedRights, ChannelParticipantsAdmins
from telethon.errors.rpcerrorlist import ( # Импортируем ошибки Telethon
    UserNotParticipantError, ChatAdminRequiredError, UserAdminInvalidError,
    UserKickedError, ChannelPrivateError, ChatWriteForbiddenError,
    SessionPasswordNeededError, FloodWaitError, ApiIdInvalidError, ApiIdPublishedFloodError
)

from aiogram import Bot
from aiogram.types import ChatPermissions
from aiogram.exceptions import ( # Импортируем ошибки AIOgram
    TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter, TelegramAPIError as AiogramTelegramAPIError
)

# Импортируем настройки из bot.config (нужно убедиться, что bot.config и .env доступны)
# Возможно, потребуется настройка sys.path, как мы делали ранее
try:
    # Определяем абсолютный путь к директории, где находится этот скрипт
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Ищем корневую директорию проекта, ища директорию 'bot'
    current_dir = script_dir
    project_root = None
    # Traverse up the directory tree until 'bot' directory is found
    while current_dir != os.path.dirname(current_dir): # Stop at filesystem root
        if os.path.exists(os.path.join(current_dir, 'bot', '__init__.py')) or \
           os.path.exists(os.path.join(current_dir, 'bot', '__main__.py')):
            project_root = current_dir
            break
        current_dir = os.path.dirname(current_dir)

    if not project_root:
         raise ImportError("Не удалось определить корневую директорию проекта (папка 'bot' не найдена).")

    # Добавляем корневую директорию проекта в sys.path
    if project_root not in sys.path:
         sys.path.insert(0, project_root)

    # Теперь импорт bot.config должен работать
    from bot.config import settings

    # Импортируем DatabaseManager
    from bot.db.database import DatabaseManager

except ImportError as e:
    # Добавим обработку ошибки импорта DatabaseManager
    if 'DatabaseManager' in str(e):
        print(f"КРИТИЧЕСКАЯ ОШИБКА ИМПОРТА БАЗЫ ДАННЫХ: {e}")
        print("Убедитесь, что файл bot/db/database.py существует и содержит класс DatabaseManager.")
    else:
        print(f"КРИТИЧЕСКАЯ ОШИБКА ИМПОРТА КОНФИГУРАЦИИ: {e}")
        print("Убедитесь, что файл bot/config.py существует и доступен, а структура проекта корректна.")
    sys.exit(1)
except Exception as e:
    print(f"КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАГРУЗКЕ КОНФИГУРАЦИИ: {e}")
    sys.exit(1)


# --- НАСТРОЙКИ СКРИПТА --- (берутся из .env через settings)
# API_ID и API_HASH для Telethon должны быть в .env: TELETHON_API_ID, TELETHON_API_HASH
# BOT_TOKEN для AIOgram должен быть в .env: BOT_TOKEN
# CHAT_IDENTIFIER может быть в .env: TELETHON_CHAT_ID, или использовать значение по умолчанию ниже

# CHAT_IDENTIFIER: Username или ID чата. Приоритет: .env -> значение в скрипте
TARGET_CHAT_IDENTIFIER = os.getenv('TELETHON_CHAT_ID', settings.bot_owner_id) # Пример: используем ID владельца как чат по умолчанию, если не указано
# Или можно задать конкретное значение по умолчанию, если TELETHON_CHAT_ID не в .env:
# TARGET_CHAT_IDENTIFIER = os.getenv('TELETHON_CHAT_ID', -1001568712129)

# Преобразуем TARGET_CHAT_IDENTIFIER в int, если возможно (если это не username)
try:
    TARGET_CHAT_IDENTIFIER = int(TARGET_CHAT_IDENTIFIER)
except (ValueError, TypeError):
    pass # Оставляем как строку (username), если не удалось преобразовать в int

# Имя файла сессии для Telethon
SESSION_NAME = 'cleanup_session' # Можно изменить, если нужно несколько сессий

# Задержка между обработкой каждого пользователя (в секундах)
DELAY_PER_USER = 0.5 # Рекомендуется 0.3 - 1.0 секунды

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- Разрешения для снятия мута (все разрешено) ---
UNMUTE_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_media_messages=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_invite_users=True,
    can_change_info=False,
    can_pin_messages=False
)

# --- Функции для сохранения/загрузки состояния ---
STATE_FILE = 'cleanup_last_processed_id.txt'

def read_last_id(filename: str) -> int | None:
    """Читает последний обработанный ID из файла."""
    try:
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                content = f.read().strip()
                if content:
                    return int(content)
    except (IOError, ValueError) as e:
        logger.error(f"Ошибка чтения файла состояния '{filename}': {e}")
    return None

def save_last_id(filename: str, user_id: int):
    """Сохраняет последний обработанный ID в файл."""
    try:
        with open(filename, 'w') as f:
            f.write(str(user_id))
        # logger.debug(f"Последний обработанный ID {user_id} сохранен в '{filename}'") # Можно раскомментировать для отладки
    except IOError as e:
        logger.error(f"Ошибка сохранения файла состояния '{filename}': {e}")

async def main():
    logger.info("Запуск гибридного скрипта очистки чата (Telethon + Aiogram + DB)...")

    client = None
    bot = None
    bot_session_needs_close = False
    db_manager = None
    db_connection_established = False
    bot_id = None
    last_processed_id = None
    current_last_id_to_save = None # ID, который будет сохранен при выходе

    try:
        # Читаем последний обработанный ID при старте
        last_processed_id = read_last_id(STATE_FILE)
        if last_processed_id:
            logger.info(f"Обнаружен предыдущий запуск. Попытка возобновить после ID: {last_processed_id}")
        else:
            logger.info("Предыдущее состояние не найдено. Начинаем обработку с начала (в обратном порядке).")

        # Инициализация DatabaseManager
        try:
            db_name = getattr(settings, 'db_name', 'bot_data.db')
            # Определяем путь к БД относительно корня проекта (логика из load_config)
            script_dir = os.path.dirname(os.path.abspath(__file__))
            current_dir = script_dir
            project_root = None
            while current_dir != os.path.dirname(current_dir):
                if os.path.exists(os.path.join(current_dir, 'bot', '__init__.py')) or \
                   os.path.exists(os.path.join(current_dir, 'bot', '__main__.py')):
                    project_root = current_dir
                    break
                current_dir = os.path.dirname(current_dir)
            if not project_root:
                raise RuntimeError("Не удалось определить корневую директорию проекта (папка 'bot' не найдена).")
            
            db_path = os.path.join(project_root, db_name)
            # Проверка, если БД лежит в bot/db
            expected_db_path_in_bot_dir = os.path.join(project_root, 'bot', 'db', db_name)
            if os.path.exists(expected_db_path_in_bot_dir):
                 db_path = expected_db_path_in_bot_dir
            
            if not os.path.exists(db_path):
                 raise FileNotFoundError(f"Файл базы данных не найден по пути: {db_path}")
            
            logger.info(f"Используется путь к БД: {db_path}")
            db_manager = DatabaseManager(db_path=db_path)
            # Если есть асинхронное подключение
            if hasattr(db_manager, 'connect') and asyncio.iscoroutinefunction(db_manager.connect):
                await db_manager.connect()
            elif hasattr(db_manager, 'init_pool') and asyncio.iscoroutinefunction(db_manager.init_pool):
                 await db_manager.init_pool()
            db_connection_established = True
            logger.info("DatabaseManager успешно инициализирован и подключен.")
        except FileNotFoundError as e:
             logger.critical(f"Ошибка инициализации БД: {e}")
             sys.exit(1)
        except Exception as e:
            logger.critical(f"Ошибка инициализации DatabaseManager: {e}", exc_info=True)
            sys.exit(1) # Выходим, если БД не инициализирована

        # Инициализация Telethon клиента
        try:
            telethon_api_id = getattr(settings, 'telethon_api_id', None)
            telethon_api_hash = getattr(settings, 'telethon_api_hash', None)

            if telethon_api_id is None:
                telethon_api_id = 18234613  # <-- ВОЗВРАЩАЕМ ВАШЕ ЗНАЧЕНИЕ ПО УМОЛЧАНИЮ
                logger.warning(f"TELETHON_API_ID не найден в настройках, используется значение по умолчанию: '{telethon_api_id}'")

            if telethon_api_hash is None:
                telethon_api_hash = 'ba5a77b44fb64379a59a37b9049f21f4'  # <-- ВОЗВРАЩАЕМ ВАШЕ ЗНАЧЕНИЕ ПО УМОЛЧАНИЮ
                logger.warning(f"TELETHON_API_HASH не найден в настройках, используется значение по умолчанию: '{telethon_api_hash}'")

            # Преобразуем API_ID в int, если это необходимо, и проверяем
            try:
                telethon_api_id = int(telethon_api_id)
            except (ValueError, TypeError):
                logger.critical(f"TELETHON_API_ID '{telethon_api_id}' не может быть преобразован в число. Проверьте настройки или значения по умолчанию в скрипте.")
                raise ValueError(f"Некорректный TELETHON_API_ID: {telethon_api_id}") 

            client = TelegramClient(SESSION_NAME, telethon_api_id, telethon_api_hash)
        except Exception as e:
            # Перехватываем ValueError от некорректного ID и другие ошибки инициализации
            logger.critical(f"Ошибка инициализации Telethon клиента: {e}", exc_info=True)
            raise # Передаем исключение выше для обработки в основном блоке finally

        # Инициализация AIOgram бота
        try:
            bot_token = settings.bot_token.get_secret_value()
            bot = Bot(token=bot_token)
            bot_info = await bot.get_me()
            bot_id = bot_info.id # <--- СОХРАНЯЕМ ID В ПЕРЕМЕННУЮ
            bot_session_needs_close = True # Сессия была открыта успешно
            logger.info(f"AIOgram Бот инициализирован: {bot_info.full_name} (ID: {bot_id})")
        except Exception as e:
            logger.critical(f"Ошибка инициализации AIOgram бота: {e}", exc_info=True)
            # Не выходим, а позволяем finally закрыть Telethon, если он был создан
            raise # Передаем исключение выше для обработки в основном блоке finally

        # Подключение Telethon клиента
        try:
            logger.info(f"Подключение Telethon клиента (сессия: {SESSION_NAME})...")
            await client.connect()

            if not await client.is_user_authorized():
                logger.critical("Telethon клиент не авторизован, и файл сессии не найден.")
                logger.critical("Пожалуйста, запустите этот скрипт один раз на вашем локальном компьютере, чтобы войти в систему и создать файл 'cleanup_session.session'.")
                logger.critical("Затем загрузите этот файл сессии на сервер вместе с остальным кодом.")
                raise ConnectionError("Telethon session file not found or invalid.")
            else:
                 # Если уже авторизован, просто стартуем без параметров
                 await client.start()

            logger.info("Telethon клиент успешно авторизован.")

        except FloodWaitError as e:
            logger.error(f"Telethon FloodWaitError: Слишком много запросов. Пожалуйста, подождите {e.value} секунд.")
            raise # Передаем исключение выше
        except (ApiIdInvalidError, ApiIdPublishedFloodError):
             logger.critical("TELETHON_API_ID и/или TELETHON_API_HASH недействительны или используются слишком часто.")
             logger.critical("Получите новые на my.telegram.org и обновите .env файл.")
             raise # Передаем исключение выше
        except Exception as e:
            logger.critical(f"Ошибка авторизации Telethon клиента: {e}", exc_info=True)
            raise # Передаем исключение выше

        # Получение сущности чата по идентификатору
        chat = None
        try:
            logger.info(f"Попытка получить сущность чата для идентификатора: {TARGET_CHAT_IDENTIFIER}")
            chat = await client.get_entity(TARGET_CHAT_IDENTIFIER)
            logger.info(f"Чат найден: '{getattr(chat, 'title', chat.id)}' (ID: {chat.id}). Проверка типа...")
            if hasattr(chat, 'broadcast') and chat.broadcast:
                 logger.warning(f"Идентификатор {TARGET_CHAT_IDENTIFIER} соответствует каналу, а не группе. Скрипт лучше работает с группами.")
            elif not hasattr(chat, 'left') and not hasattr(chat, 'kicked'):
                 logger.info(f"Идентификатор {TARGET_CHAT_IDENTIFIER} соответствует типу группы.")
            else:
                 logger.warning(f"Идентификатор {TARGET_CHAT_IDENTIFIER} соответствует неизвестному или нестандартному типу сущности: {type(chat).__name__}.")

        except (ValueError, TypeError) as e:
            logger.critical(f"Ошибка: Не удалось найти сущность для идентификатора '{TARGET_CHAT_IDENTIFIER}'. Проверьте правильность username/ID. Детали: {e}")
            raise # Передаем исключение выше
        except ChannelPrivateError:
            logger.critical(f"Ошибка: Сущность '{TARGET_CHAT_IDENTIFIER}' приватная, и авторизованный аккаунт не имеет к ней доступа.")
            raise # Передаем исключение выше
        except Exception as e:
            logger.critical(f"Произошла непредвиденная ошибка при получении информации о сущности '{TARGET_CHAT_IDENTIFIER}': {e}", exc_info=True)
            raise # Передаем исключение выше

        # Получение ID администраторов с помощью Telethon
        admins_ids = set() # Используем set для быстрого поиска
        try:
            logger.info(f"Получение списка администраторов в чате '{getattr(chat, 'title', chat.id)}'...")
            async for admin_user in client.iter_participants(chat, filter=ChannelParticipantsAdmins):
                admins_ids.add(admin_user.id)
            logger.info(f"Найдено {len(admins_ids)} администраторов. Они будут пропущены.")
        except ChatAdminRequiredError:
            logger.warning("Предупреждение: Недостаточно прав у аккаунта Telethon для получения списка администраторов. Пропускаем их определение.")
        except Exception as e:
            logger.error(f"Ошибка при получении списка администраторов: {e}", exc_info=True)

        logger.info(f"\nНачинаем перебор участников в чате '{getattr(chat, 'title', chat.id)}'...")

        processed_count = 0
        unmuted_count = 0
        kicked_deleted_count = 0
        skipped_count = 0
        error_count = 0
        processed_after_resume = 0 # Счетчик реально обработанных после точки возобновления
        found_start_point = (last_processed_id is None) # Начинаем сразу, если ID не было

        try: # Вложенный try-except для цикла перебора участников
            # Убираем reverse=True и aggressive=True, используем стандартную итерацию
            # async for participant in client.iter_participants(chat, aggressive=True, reverse=True):
            async for participant in client.iter_participants(chat):
                # participant уже является объектом User (или Channel)
                user = participant
                current_user_id = user.id # Сохраняем ID для удобства

                # Логика возобновления
                if not found_start_point:
                    if current_user_id == last_processed_id:
                        logger.info(f"Найдена точка возобновления (ID: {last_processed_id}). Следующий участник будет обработан.")
                        found_start_point = True # Нашли, со следующего начнем
                    # Пропускаем всех, пока не найдем точку старта
                    continue 
                
                # Если мы здесь, значит, пользователь подлежит обработке
                processed_count += 1 # Общий счетчик просмотренных после точки старта
                processed_after_resume += 1 # Счетчик реально обработанных
                action_taken_this_user = False
                current_user_log_prefix = f"Пользователь {processed_after_resume} (ID: {current_user_id}):" # Используем счетчик после возобновления

                # --- Начало блока обработки пользователя --- 
                if hasattr(user, 'is_self') and user.is_self:
                     logger.info(f"  {current_user_log_prefix} Пропуск (этот аккаунт Telethon)...")
                     skipped_count += 1
                     await asyncio.sleep(0.01)
                     continue

                # Пропускаем самого бота AIOgram, используя сохраненный ID
                if user.id == bot_id:
                    logger.info(f"  {current_user_log_prefix} Пропуск (AIOgram бот)...")
                    skipped_count += 1
                    await asyncio.sleep(0.01)
                    continue

                if user.id in admins_ids:
                     logger.info(f"  {current_user_log_prefix} Пропуск (Администратор)...")
                     skipped_count += 1
                     await asyncio.sleep(0.01)
                     continue

                logger.info(f"\n--- {current_user_log_prefix} Обработка. Имя: {user.first_name or ''} {user.last_name or ''} (@{user.username or 'N/A'}) ---")

                # 1. Удаление "собачек"
                if user.deleted:
                    logger.info(f"  {current_user_log_prefix} [УДАЛЕНИЕ] Является удаленным аккаунтом. Попытка кика через AIOgram...")
                    try:
                        await bot.ban_chat_member(chat_id=chat.id, user_id=user.id, revoke_messages=False)
                        logger.info(f"    [УДАЛЕНИЕ-УСПЕХ] {current_user_log_prefix} Удаленный аккаунт кикнут.")
                        kicked_deleted_count += 1
                        action_taken_this_user = True
                        await asyncio.sleep(DELAY_PER_USER * 1.5)
                    except (TelegramForbiddenError, TelegramBadRequest) as e:
                        error_msg_lower = str(e).lower()
                        if "user is an administrator" in error_msg_lower or "can't remove chat owner" in error_msg_lower:
                             logger.warning(f"    [УДАЛЕНИЕ-ОШИБКА AIOgram] {current_user_log_prefix} Недостаточно прав для кика (вероятно, админ). ({e})")
                        elif "user not found" in error_msg_lower or "user_not_participant" in error_msg_lower:
                             logger.warning(f"    [УДАЛЕНИЕ-ОШИБКА AIOgram] {current_user_log_prefix} Пользователь уже не в чате. ({e})")
                        else:
                             logger.error(f"    [УДАЛЕНИЕ-ОШИБКА AIOgram] {current_user_log_prefix} Не удалось кикнуть: {e}")
                             error_count += 1
                    except TelegramRetryAfter as e:
                         logger.warning(f"    [УДАЛЕНИЕ-FLOOD AIOgram] {current_user_log_prefix} Слишком много запросов. Ожидание {e.retry_after} секунд...")
                         await asyncio.sleep(e.retry_after)
                         # Можно добавить повторную попытку, но для удаления может быть излишне
                         error_count += 1 # Считаем как ошибку, т.к. пропустили
                    except Exception as e:
                         logger.error(f"    [УДАЛЕНИЕ-НЕИЗВЕСТНАЯ-ОШИБКА] {current_user_log_prefix} Не удалось кикнуть: {type(e).__name__} - {e}", exc_info=True)
                         error_count += 1
                    continue # Переход к следующему после попытки кика

                # 2. Анмут (если не "собачка" и не админ)
                is_muted = False
                # participant.banned_rights присутствует, если есть *любые* ограничения
                if hasattr(participant, 'banned_rights') and participant.banned_rights:
                    # Главный критерий мута - send_messages == False
                    if not participant.banned_rights.send_messages:
                        is_muted = True
                        logger.info(f"  {current_user_log_prefix} [ПРОВЕРКА-МУТА] ЗАМУЧЕН (не может отправлять сообщения).")
                    else:
                         # Могут быть другие ограничения (отправка медиа, стикеров и т.д.)
                         # Можно добавить логику для снятия и этих ограничений, если нужно,
                         # но UNMUTE_PERMISSIONS уже разрешает все.
                         # Важно, что он *может* отправлять текстовые сообщения.
                         logger.info(f"  {current_user_log_prefix} [ПРОВЕРКА-МУТА] Есть ограничения, но может отправлять сообщения. Анмут не требуется.")
                         logger.debug(f"  {current_user_log_prefix} Детали ограничений: {participant.banned_rights}")
                         skipped_count += 1 # Считаем как пропуск, т.к. основной анмут не нужен

                if is_muted:
                    logger.info(f"  {current_user_log_prefix} [АНМУТ] Попытка размутить через AIOgram...")
                    try:
                        await bot.restrict_chat_member(
                            chat_id=chat.id,
                            user_id=user.id,
                            permissions=UNMUTE_PERMISSIONS,
                            until_date=0 # Снять временные ограничения
                        )
                        logger.info(f"    [АНМУТ-УСПЕХ] {current_user_log_prefix} Пользователь размучен.")
                        unmuted_count += 1
                        action_taken_this_user = True
                        await asyncio.sleep(DELAY_PER_USER)
                    except (TelegramForbiddenError, TelegramBadRequest) as e:
                        error_msg_lower = str(e).lower()
                        if "user is an administrator" in error_msg_lower:
                            logger.warning(f"    [АНМУТ-ОШИБКА AIOgram] {current_user_log_prefix} Является администратором, не может быть ограничен/размучен ботом.")
                        elif "user not found" in error_msg_lower or "user_not_participant" in error_msg_lower:
                            logger.warning(f"    [АНМУТ-ОШИБКА AIOgram] {current_user_log_prefix} Не найден в чате. Пропуск анмута. ({e})")
                        elif "member is not restricted" in error_msg_lower or "rights are same" in error_msg_lower:
                             logger.info(f"    [АНМУТ-ИНФО] {current_user_log_prefix} Уже не ограничен или права не изменились. Пропуск анмута. ({e})")
                        else:
                            logger.error(f"    [АНМУТ-ОШИБКА AIOgram] {current_user_log_prefix} Не удалось размутить: {e}")
                            error_count += 1
                    except TelegramRetryAfter as e:
                        logger.warning(f"    [АНМУТ-FLOOD AIOgram] {current_user_log_prefix} Слишком много запросов на размут. Ожидание {e.retry_after} секунд...")
                        await asyncio.sleep(e.retry_after)
                        try:
                             await bot.restrict_chat_member(chat_id=chat.id, user_id=user.id, permissions=UNMUTE_PERMISSIONS, until_date=0)
                             logger.info(f"    [АНМУТ-ПОВТОР-УСПЕХ] {current_user_log_prefix} Размучен после ожидания.")
                             unmuted_count += 1
                             action_taken_this_user = True
                             await asyncio.sleep(DELAY_PER_USER)
                        except Exception as e_retry:
                             logger.error(f"    [АНМУТ-ПОВТОР-ОШИБКА] {current_user_log_prefix} Не удалось размутить после ожидания: {e_retry}", exc_info=True)
                             error_count += 1
                    except Exception as e:
                        logger.error(f"    [АНМУТ-НЕИЗВЕСТНАЯ-ОШИБКА] {current_user_log_prefix}: {type(e).__name__} - {e}", exc_info=True)
                        error_count += 1
                    # --- Дополнительная проверка и очистка мута в БД --- 
                    if db_manager and action_taken_this_user: # Если размут был успешен (или прошлая попытка была успешной)
                        try:
                             # Обновляем статус мута в БД (устанавливаем ban_until_ts = 0)
                             # Убедитесь, что метод называется правильно!
                            if hasattr(db_manager, 'update_user_ban_status'): 
                                await db_manager.update_user_ban_status(user_id=user.id, chat_id=chat.id, ban_until_ts=0)
                                logger.info(f"    [БД-ОЧИСТКА] Запись о муте для {current_user_log_prefix} очищена в БД.")
                            else:
                                 logger.warning(f"    [БД-ОЧИСТКА] Метод 'update_user_ban_status' не найден в DatabaseManager. Не могу очистить запись о муте.")
                        except Exception as e_db:
                            logger.error(f"    [БД-ОЧИСТКА-ОШИБКА] Не удалось обновить статус мута для {current_user_log_prefix} в БД: {e_db}", exc_info=True)
                            error_count += 1 # Считаем ошибку БД

                elif not user.deleted: # Если не собачка и не был замучен
                    logger.info(f"  {current_user_log_prefix} [ПРОВЕРКА-МУТА] Не замучен. Анмут не требуется.")
                    skipped_count +=1
                    # --- Дополнительная проверка и очистка мута в БД (даже если не замучен по API) ---
                    # Если по API он не замучен, но в БД есть активная запись, ее тоже нужно очистить
                    if db_manager:
                         try:
                              # Нужен метод для проверки статуса мута в БД, например, get_user_ban_until_ts
                              # Если такого метода нет, эту логику можно убрать или адаптировать
                              if hasattr(db_manager, 'get_user_ban_until_ts'):
                                   ban_until_ts = await db_manager.get_user_ban_until_ts(user_id=user.id, chat_id=chat.id)
                                   current_timestamp = int(time.time())
                                   if ban_until_ts and ban_until_ts > current_timestamp:
                                        logger.warning(f"    [БД-НЕСООТВЕТСТВИЕ] Пользователь {current_user_log_prefix} не замучен по API, но в БД есть активный мут до {ban_until_ts}. Очищаем запись...")
                                        if hasattr(db_manager, 'update_user_ban_status'):
                                             await db_manager.update_user_ban_status(user_id=user.id, chat_id=chat.id, ban_until_ts=0)
                                             logger.info(f"    [БД-ОЧИСТКА] Запись о муте для {current_user_log_prefix} очищена в БД.")
                                        else:
                                             logger.warning(f"    [БД-ОЧИСТКА] Метод 'update_user_ban_status' не найден. Не могу очистить запись.")
                              # else:
                              #      logger.debug(f"    [БД-ПРОВЕРКА] Метод 'get_user_ban_until_ts' не найден. Пропускаем проверку несоответствий.")
                         except Exception as e_db_check:
                              logger.error(f"    [БД-ПРОВЕРКА-ОШИБКА] Не удалось проверить/обновить статус для {current_user_log_prefix} в БД: {e_db_check}", exc_info=True)
                              error_count += 1

                # Задержка, если не было активных действий
                if not action_taken_this_user and not user.deleted:
                    await asyncio.sleep(DELAY_PER_USER / 2.0)

                # Обновляем ID для сохранения после КАЖДОЙ успешной попытки обработки
                # (даже если ошибок не было, но и действий не требовалось)
                current_last_id_to_save = current_user_id

        except ChatAdminRequiredError:
            logger.critical(f"\nКритическая ошибка Telethon: У аккаунта нет прав администратора в чате '{getattr(chat, 'title', chat.id)}' для перебора участников. Скрипт не может продолжить.")
            error_count += 1 # Указываем на ошибку перед выходом из цикла
        except FloodWaitError as e:
            logger.error(f"\nTelethon FloodWaitError при переборе участников: Ожидание {e.value} секунд.")
            await asyncio.sleep(e.value) # Ждем и позволяем продолжить, если возможно
        except Exception as e:
            logger.critical(f"\nНепредвиденная ошибка при переборе участников: {type(e).__name__} - {e}", exc_info=True)
            error_count += 1 # Указываем на ошибку перед выходом из цикла

        # --- Итоги после цикла ---
        logger.info("\n--- ЗАВЕРШЕНИЕ ПЕРЕБОРА УЧАСТНИКОВ ---")
        logger.info(f"Всего обработано записей участников: {processed_count}")
        logger.info(f"Пользователей успешно размучено: {unmuted_count}")
        logger.info(f"Удаленных аккаунтов ('собачек') кикнуто: {kicked_deleted_count}")
        logger.info(f"Пропущено (админы, боты, не замученные): {skipped_count}")
        if error_count > 0:
             logger.warning(f"Возникло ошибок при обработке: {error_count}")
        logger.info("--- --- --- --- --- --- --- --- --- ---")


    except Exception as e: # Ловим ошибки инициализации/авторизации/получения чата
         # Логирование уже произошло на этапе возникновения ошибки
         logger.error(f"Произошла критическая ошибка на этапе подготовки. См. логи выше. Тип ошибки: {type(e).__name__}")
         # Завершаем работу, finally выполнится

    finally:
        logger.info("Завершение работы скрипта. Закрытие соединений...")
        
        # Сохраняем последний обработанный ID перед выходом
        if current_last_id_to_save is not None:
            logger.info(f"Сохранение последнего обработанного ID: {current_last_id_to_save}")
            save_last_id(STATE_FILE, current_last_id_to_save)
        else:
            logger.info("Нет ID для сохранения (обработка не дошла до участников или произошла ошибка до начала).")

        # Закрытие соединения с БД
        if db_manager and db_connection_established:
             if hasattr(db_manager, 'disconnect') and asyncio.iscoroutinefunction(db_manager.disconnect):
                 try:
                     await db_manager.disconnect()
                     logger.info("Соединение с DatabaseManager закрыто.")
                 except Exception as e_db_close:
                     logger.error(f"Ошибка при закрытии соединения с БД: {e_db_close}", exc_info=True)
             elif hasattr(db_manager, 'close_pool') and asyncio.iscoroutinefunction(db_manager.close_pool):
                 try:
                     await db_manager.close_pool()
                     logger.info("Пул соединений с DatabaseManager закрыт.")
                 except Exception as e_db_close:
                     logger.error(f"Ошибка при закрытии пула соединений с БД: {e_db_close}", exc_info=True)
             else:
                  logger.info("Методы disconnect/close_pool не найдены в DatabaseManager или не асинхронны.")
        elif db_manager:
             logger.info("Соединение с БД не было установлено или уже закрыто.")
        else:
             logger.info("DatabaseManager не был инициализирован.")

        # Закрытие Telethon
        if client and client.is_connected():
            try:
                await client.disconnect()
                logger.info("Telethon клиент отключен.")
            except Exception as e:
                logger.error(f"Ошибка при отключении Telethon клиента: {e}", exc_info=True)
        elif client:
             logger.info("Telethon клиент не был подключен или уже отключен.")
        else:
             logger.info("Telethon клиент не был инициализирован.")

        if bot and bot_session_needs_close: # Закрываем сессию только если она была успешно открыта
            try:
                await bot.session.close()
                logger.info("AIOgram бот сессия закрыта.")
            except Exception as e:
                logger.error(f"Ошибка при закрытии сессии AIOgram бота: {e}", exc_info=True)
        elif bot:
             logger.info("AIOgram сессия не требует закрытия (не была открыта или уже закрыта).")
        else:
             logger.info("AIOgram бот не был инициализирован.")
        logger.info("Скрипт завершил работу.")


# Точка входа в скрипт
if __name__ == '__main__':
    print("\n\n--- Гибридный скрипт очистки чата (Telethon + Aiogram) ---")
    print("Инструкции по использованию:")
    print("1. Установите зависимости: pip install -r requirements.txt (убедитесь, что telethon и aiogram включены).")
    print("2. Добавьте в ваш .env файл:\n   TELETHON_API_ID=<Ваш API ID>\n   TELETHON_API_HASH=<Ваш API Hash>\n   BOT_TOKEN=<Ваш токен бота AIOgram>\n   TELETHON_CHAT_ID=<Username или ID чата для очистки (опционально, если не указан - будет использоваться bot_owner_id)>\n   TELETHON_PHONE=<Номер телефона аккаунта для Telethon авторизации (опционально, потребуется интерактивный ввод при первом запуске)>")
    print("3. Убедитесь, что аккаунт, используемый для Telethon, является администратором в целевом чате с правами на бан и ограничение участников.")
    print("4. Убедитесь, что AIOgram бот, чей токен используется, является администратором в целевом чате с правами на ограничение и бан участников.")
    print("\n>>> ПЕРВЫЙ ЗАПУСК ДЛЯ АВТОРИЗАЦИИ TELETHON <<<")
    print("Для первого запуска (или если файл сессии не найден/поврежден) потребуется интерактивный ввод номера телефона, кода и, возможно, пароля 2FA.")
    print("ЗАПУСТИТЕ СКРИПТ В ИНТЕРАКТИВНОМ ТЕРМИНАЛЕ НА СЕРВЕРЕ/КОМПЬЮТЕРЕ: python cleanup_telethon_aiogram.py")
    print("Введите запрашиваемые данные в консоль.")
    print("После успешной авторизации Telethon создаст файл сессии.")
    print("\n>>> ПОСЛЕДУЮЩИЕ ЗАПУСКИ (НЕИНТЕРАКТИВНЫЕ) <<<")
    print("После первой авторизации скрипт может быть запущен неинтерактивно (например, через cron или systemd): python cleanup_telethon_aiogram.py")
    print("\nНачинаем выполнение...")

    # Предварительные проверки конфигурации - УДАЛЕНЫ, так как логика теперь в main()
    # Проверка наличия bot_token остается, так как он критичен
    if not hasattr(settings, 'bot_token') or not settings.bot_token.get_secret_value():
         print("\nКРИТИЧЕСКАЯ ОШИБКА: BOT_TOKEN отсутствует или пуст в .env / bot.config.Settings.")
         sys.exit(1)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nРабота скрипта прервана пользователем (Ctrl+C).")
        # Блок finally в main() должен был уже выполниться или выполнится при выходе из asyncio.run
    except Exception as e:
        # Ловим ошибки, которые могли возникнуть *вне* main(), например, при импорте asyncio
        logger.critical(f"Непредвиденная ошибка верхнего уровня: {e}", exc_info=True)
        # Пытаемся выполнить очистку, если возможно (хотя клиенты могут быть не инициализированы)
        # Обычно finally в main() должен справиться, но это дополнительная мера предосторожности
        # (на практике здесь редко что-то можно сделать безопасно)
        sys.exit(1)