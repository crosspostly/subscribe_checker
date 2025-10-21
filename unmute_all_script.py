import asyncio
import sqlite3
import logging
import time
import os
import sys
from aiogram import Bot
from aiogram.types import ChatPermissions
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramBadRequest
from bot.config import settings, DB_NAME
# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Конфигурация (будет загружена из bot.config) ---
BOT_TOKEN = None
DATABASE_PATH = None

# --- Разрешения для снятия мута (все разрешено) ---
UNMUTE_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_change_info=False,  # Обычно не нужно пользователям
    can_invite_users=True,  # Обычно это право есть у всех
    can_pin_messages=False  # Обычно не нужно пользователям
)

def load_config():
    """Загружает конфигурацию из bot.config"""
    global BOT_TOKEN, DATABASE_PATH
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
             logger.error("Не удалось определить корневую директорию проекта (папка 'bot' не найдена).")
             return False

        # Добавляем корневую директорию проекта в sys.path
        if project_root not in sys.path:
             sys.path.insert(0, project_root)

        # Теперь импорт bot.config должен работать
        # from bot.config import BOT_TOKEN as TOKEN_FROM_CONFIG, DB_NAME # <--- ЭТУ СТРОКУ УДАЛИТЬ ИЛИ ЗАКОММЕНТИРОВАТЬ

        # Получаем токен бота из импортированного объекта settings
        BOT_TOKEN = settings.bot_token.get_secret_value() # <--- ЭТА СТРОКА ДОЛЖНА БЫТЬ ЗДЕСЬ

        # Формируем полный путь к БД относительно корневой директории проекта
        DATABASE_PATH = os.path.join(project_root, DB_NAME)
        # Check if the database file exists within the project structure
        expected_db_path_in_bot_dir = os.path.join(project_root, 'bot', 'db', DB_NAME)
        if os.path.exists(expected_db_path_in_bot_dir):
             DATABASE_PATH = expected_db_path_in_bot_dir
             logger.info(f"Используется путь к БД: {DATABASE_PATH}")
        else:
             logger.warning(f"Стандартный путь к БД ({expected_db_path_in_bot_dir}) не найден. Используется путь из config.py: {DATABASE_PATH}")


        logger.info(f"Конфигурация загружена. BOT_TOKEN: {'OK' if BOT_TOKEN else 'NOT FOUND'}. DATABASE_PATH: {DATABASE_PATH}")

        if not BOT_TOKEN or not DATABASE_PATH:
            logger.error("Не удалось загрузить BOT_TOKEN или определить DATABASE_PATH. Проверьте bot/config.py и структуру проекта.")
            return False
        if not os.path.exists(DATABASE_PATH):
            logger.error(f"Файл базы данных не найден по пути: {DATABASE_PATH}. Убедитесь, что путь корректен и БД существует.")
            return False

        return True

    except ImportError as e:
        logger.error(f"Не удалось импортировать 'bot.config'. Проверьте структуру проекта и содержимое bot/config.py. Ошибка: {e}")
        return False
    except Exception as e:
        logger.error(f"Ошибка при загрузке конфигурации: {e}", exc_info=True)
        return False

async def get_active_chats_from_db(db_path: str) -> list[int]:
    """Получает ID всех чатов, где бот активен (is_activated = 1)."""
    chats = []
    try:
        # Используем aiosqlite, так как основной бот, скорее всего, его использует
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row # или sqlite3.Row, если используется стандартный sqlite3.Row
            async with db.execute("SELECT DISTINCT chat_id FROM chats WHERE is_activated = 1") as cursor:
                rows = await cursor.fetchall()
                chats = [row['chat_id'] for row in rows]
        logger.info(f"Найдено {len(chats)} активных чатов в БД.")
    except sqlite3.Error as e: # Ловим и sqlite3.Error для общности
        logger.error(f"Ошибка при доступе к БД SQLite для получения активных чатов: {e}")
    except ImportError:
        logger.error("Не удалось импортировать aiosqlite. Пожалуйста, установите его: pip install aiosqlite")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при получении активных чатов: {e}", exc_info=True)
    return chats

async def get_restricted_users_in_chat_from_db(db_path: str, chat_id: int) -> list[int]:
    """
    Получает ID пользователей, которые имеют активные ограничения (мут) в указанном чате,
    на основе данных из таблицы users_status_in_chats (поле ban_until_ts).
    """
    restricted_users = []
    current_timestamp = int(time.time())
    try:
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            # ban_until_ts > 0 означает, что это временное ограничение, а не вечный бан.
            # ban_until_ts > current_timestamp означает, что ограничение еще активно.
            query = """
                SELECT user_id 
                FROM users_status_in_chats 
                WHERE chat_id = ? AND ban_until_ts > 0 AND ban_until_ts > ?
            """
            async with db.execute(query, (chat_id, current_timestamp)) as cursor:
                rows = await cursor.fetchall()
                restricted_users = [row['user_id'] for row in rows]
        logger.info(f"В чате {chat_id} найдено {len(restricted_users)} пользователей с активными ограничениями (по данным БД).")
    except sqlite3.Error as e:
        logger.error(f"Ошибка SQLite при получении ограниченных пользователей для чата {chat_id}: {e}")
    except ImportError:
        logger.error("Не удалось импортировать aiosqlite.")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при получении ограниченных пользователей для чата {chat_id}: {e}", exc_info=True)
    return restricted_users

async def unmute_user_in_chat(bot: Bot, chat_id: int, user_id: int):
    """Снимает ограничения с пользователя в указанном чате."""
    try:
        # Получаем текущие права пользователя, чтобы убедиться, что он участник
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        if member.status not in [member.status.MEMBER, member.status.RESTRICTED]:
             logger.info(f"Пользователь {user_id} в чате {chat_id} не является участником или уже не ограничен ({member.status}). Пропуск.")
             return False

        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=UNMUTE_PERMISSIONS,
            until_date=0  # 0 означает "навсегда" (снять ограничения)
        )
        logger.info(f"Пользователь {user_id} успешно размучен в чате {chat_id}.")
        
        # Опционально: обновить ban_until_ts в БД на 0 или удалить запись
        # Это зависит от того, как ваш основной бот обрабатывает снятие мута
        # await update_user_ban_status_in_db(DATABASE_PATH, chat_id, user_id, 0)
        return True
    except TelegramForbiddenError:
        logger.warning(f"Недостаточно прав для снятия ограничений с {user_id} в чате {chat_id} (бот не админ или нет нужных прав?).")
    except TelegramBadRequest as e:
        if "user is an administrator of the chat" in str(e).lower():
            logger.info(f"Пользователь {user_id} в чате {chat_id} является администратором, не может быть ограничен/размучен ботом.")
        elif "user_not_participant" in str(e).lower():
            logger.info(f"Пользователь {user_id} не является участником чата {chat_id}.")
        elif "member is not restricted" in str(e).lower() or "rights are same" in str(e).lower():
             logger.info(f"Пользователь {user_id} в чате {chat_id} уже не ограничен или права не изменились.")
        else:
            logger.error(f"Ошибка BadRequest (API) при снятии ограничений с {user_id} в чате {chat_id}: {e}")
    except TelegramAPIError as e:
        logger.error(f"Ошибка API при снятии ограничений с {user_id} в чате {chat_id}: {e}")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при снятии ограничений с {user_id} в чате {chat_id}: {e}", exc_info=True)
    return False

async def update_user_ban_status_in_db(db_path: str, chat_id: int, user_id: int, ban_until: int):
    """Обновляет ban_until_ts для пользователя в БД после успешного размута скриптом."""
    try:
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "UPDATE users_status_in_chats SET ban_until_ts = ? WHERE user_id = ? AND chat_id = ?",
                (ban_until, user_id, chat_id)
            )
            await db.commit()
            logger.info(f"Статус ограничений (ban_until_ts={ban_until}) для user {user_id} в chat {chat_id} обновлен в БД.")
    except Exception as e:
        logger.error(f"Ошибка при обновлении ban_until_ts для user {user_id} в chat {chat_id}: {e}", exc_info=True)


async def main():
    if not load_config() or not BOT_TOKEN or not DATABASE_PATH:
        logger.critical("Завершение работы скрипта из-за ошибки конфигурации.")
        return

    bot = Bot(token=BOT_TOKEN)
    logger.info("Скрипт для снятия ограничений (мутов) запущен.")
    
    logger.warning("ВАЖНО: Этот скрипт может идентифицировать и размутить только тех пользователей,")
    logger.warning("ограничения которым были наложены ВАШИМ БОТОМ, и информация о которых")
    logger.warning("(в частности, user_id, chat_id и время окончания мута ban_until_ts)")
    logger.warning("хранится в таблице 'users_status_in_chats' вашей базы данных.")
    logger.warning("Скрипт НЕ МОЖЕТ получить список всех замученных пользователей напрямую из Telegram, если они были замучены не этим ботом.")

    active_chat_ids = await get_active_chats_from_db(DATABASE_PATH)
    if not active_chat_ids:
        logger.info("Нет активных чатов в БД для обработки.")
        await bot.session.close()
        return

    total_unmuted_globally = 0
    processed_chats_count = 0

    for chat_id in active_chat_ids:
        logger.info(f"--- Обработка чата {chat_id} ---")
        try:
            # Проверка, что бот все еще в чате и является админом (хотя бы базовые права)
            chat_info = await bot.get_chat(chat_id)
            if chat_info.type == 'channel':
                logger.info(f"Чат {chat_id} ('{chat_info.title}') является каналом, пропускаем.")
                continue
            
            bot_member = await bot.get_chat_member(chat_id, bot.id)
            if not bot_member.status == 'administrator':
                logger.warning(f"Бот не является администратором в чате {chat_id} ('{chat_info.title}'). Пропускаем чат.")
                continue
            if not bot_member.can_restrict_members:
                logger.warning(f"У бота нет прав на ограничение пользователей в чате {chat_id} ('{chat_info.title}'). Не смогу размутить. Пропускаем чат.")
                continue

        except TelegramForbiddenError:
            logger.warning(f"Бот не имеет доступа к чату {chat_id} (возможно, кикнут или нет прав). Пропускаем.")
            continue
        except TelegramAPIError as e:
            logger.error(f"Ошибка API при получении информации о чате/боте в чате {chat_id}: {e}. Пропускаем чат.")
            continue
        
        restricted_user_ids = await get_restricted_users_in_chat_from_db(DATABASE_PATH, chat_id)
        if not restricted_user_ids:
            logger.info(f"В чате {chat_id} не найдено пользователей с активными ограничениями (согласно БД).")
        else:
            logger.info(f"В чате {chat_id} найдено {len(restricted_user_ids)} пользователей для попытки размута: {restricted_user_ids}")
            unmuted_in_this_chat = 0
            for user_id_to_unmute in restricted_user_ids:
                if await unmute_user_in_chat(bot, chat_id, user_id_to_unmute):
                    unmuted_in_this_chat += 1
                    # Обновляем статус в БД, чтобы при следующем запуске скрипта не пытаться снова размутить
                    await update_user_ban_status_in_db(DATABASE_PATH, chat_id, user_id_to_unmute, 0) 
                await asyncio.sleep(0.3) # Небольшая задержка между запросами к API
            
            if unmuted_in_this_chat > 0:
                logger.info(f"В чате {chat_id} успешно размучено {unmuted_in_this_chat} пользователей.")
                total_unmuted_globally += unmuted_in_this_chat
        
        processed_chats_count += 1
        await asyncio.sleep(1) # Задержка между обработкой чатов

    logger.info(f"--- Завершение работы скрипта ---")
    logger.info(f"Всего обработано чатов: {processed_chats_count}")
    logger.info(f"Всего снято ограничений с пользователей (глобально): {total_unmuted_globally}")
    
    await bot.session.close()
    logger.info("Соединение с Telegram API закрыто.")

if __name__ == "__main__":
    asyncio.run(main()) 