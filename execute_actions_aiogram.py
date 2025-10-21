# execute_actions_aiogram.py
import asyncio
import logging
import os
import json
from aiogram import Bot
from aiogram.types import ChatPermissions
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    # logger здесь еще не инициализирован, используем print или raise
    # print("Критическая ошибка: Переменная окружения TELEGRAM_BOT_TOKEN должна быть установлена.")
    # exit(1) # Выход, если токен не установлен
    raise ValueError("Переменная окружения TELEGRAM_BOT_TOKEN должна быть установлена.")

TARGET_CHAT_ID = os.getenv('AIOGRAM_TARGET_CHAT_ID', -1001568712129) # ID чата, где бот будет выполнять действия
INPUT_FILE = 'user_ids_for_bot.json' # Файл с ID от Telethon-скрипта
DELAY_PER_ACTION = 1.0 # Задержка между действиями бота (кик/анмут)

# Преобразуем TARGET_CHAT_ID в int, если он задан через env
try:
    TARGET_CHAT_ID = int(TARGET_CHAT_ID)
except ValueError:
    print(f"Ошибка: TARGET_CHAT_ID ('{TARGET_CHAT_ID}') должен быть числом. Проверьте значение или переменную окружения AIOGRAM_TARGET_CHAT_ID.")
    exit(1)


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(module)s - %(message)s")
logger = logging.getLogger(__name__)
# --- КОНЕЦ НАСТРОЕК ---

async def execute_bot_actions(bot: Bot, chat_id: int, ids_to_kick: list, ids_to_unmute: list):
    logger.info(f"Запуск выполнения действий ботом для чата ID: {chat_id}")
    
    kicked_count = 0
    unmuted_count = 0

    # Анмут пользователей
    if ids_to_unmute:
        logger.info(f"\n--- Начало анмута {len(ids_to_unmute)} пользователей ---")
        unmute_permissions = ChatPermissions(
            can_send_messages=True, can_send_media_messages=True, can_send_polls=True,
            can_send_other_messages=True, can_add_web_page_previews=True, can_invite_users=True,
            can_change_info=False, can_pin_messages=False
        )
        for i, user_id in enumerate(ids_to_unmute):
            if hasattr(bot, 'id') and bot.id == user_id: # Проверка, есть ли у bot атрибут id
                logger.info(f"  Пропуск анмута самого бота ID: {user_id}")
                continue
            logger.info(f"  Анмут {i+1}/{len(ids_to_unmute)}. Пользователь ID: {user_id}")
            try:
                await bot.restrict_chat_member(chat_id, user_id, permissions=unmute_permissions)
                logger.info(f"    [АНМУТ-УСПЕХ] Пользователь {user_id} размучен.")
                unmuted_count += 1
            except TelegramRetryAfter as e:
                logger.warning(f"    [АНМУТ-FLOOD] {user_id}: Ожидание {e.retry_after} сек.")
                await asyncio.sleep(e.retry_after + 0.5) # Добавляем немного к retry_after
                try: # Повторная попытка
                    await bot.restrict_chat_member(chat_id, user_id, permissions=unmute_permissions)
                    logger.info(f"    [АНМУТ-УСПЕХ-ПОВТОР] Пользователь {user_id} размучен.")
                    unmuted_count += 1
                except Exception as e_retry:
                    logger.error(f"    [АНМУТ-ОШИБКА-ПОВТОР] {user_id}: {e_retry}")
            except Exception as e:
                logger.error(f"    [АНМУТ-ОШИБКА] {user_id}: {e}")
            await asyncio.sleep(DELAY_PER_ACTION)
    else:
        logger.info("Нет пользователей для анмута.")

    # Кик "собачек"
    if ids_to_kick:
        logger.info(f"\n--- Начало кика {len(ids_to_kick)} удаленных аккаунтов ---")
        for i, user_id in enumerate(ids_to_kick):
            if hasattr(bot, 'id') and bot.id == user_id:
                logger.info(f"  Пропуск кика самого бота ID: {user_id}")
                continue
            logger.info(f"  Кик {i+1}/{len(ids_to_kick)}. Аккаунт ID: {user_id}")
            try:
                await bot.ban_chat_member(chat_id, user_id, revoke_messages=False)
                logger.info(f"    [КИК-УСПЕХ] Аккаунт {user_id} кикнут.")
                kicked_count += 1
            except TelegramRetryAfter as e:
                logger.warning(f"    [КИК-FLOOD] {user_id}: Ожидание {e.retry_after} сек.")
                await asyncio.sleep(e.retry_after + 0.5)
                try: # Повторная попытка
                    await bot.ban_chat_member(chat_id, user_id, revoke_messages=False)
                    logger.info(f"    [КИК-УСПЕХ-ПОВТОР] Аккаунт {user_id} кикнут.")
                    kicked_count += 1
                except Exception as e_retry:
                    logger.error(f"    [КИК-ОШИБКА-ПОВТОР] {user_id}: {e_retry}")
            except Exception as e:
                logger.error(f"    [КИК-ОШИБКА] {user_id}: {e}")
            await asyncio.sleep(DELAY_PER_ACTION)
    else:
        logger.info("Нет удаленных аккаунтов для кика.")

    logger.info("\n--- ЗАВЕРШЕНИЕ ДЕЙСТВИЙ БОТА ---")
    logger.info(f"Пользователей размучено: {unmuted_count}")
    logger.info(f"Удаленных аккаунтов кикнуто: {kicked_count}")

async def main_executor_script():
    bot = Bot(token=BOT_TOKEN)
    # Получим ID самого бота для последующего пропуска, если execute_bot_actions его ожидает
    # bot.id можно установить здесь, чтобы не делать это в каждом цикле
    try:
        bot_info = await bot.get_me()
        bot.id = bot_info.id # Сохраняем ID бота в объекте бота для удобства
        logger.info(f"Бот-исполнитель инициализирован: {bot_info.full_name} (ID: {bot.id})")
    except Exception as e:
        logger.error(f"Не удалось получить информацию о боте: {e}. ID бота не будет использоваться для пропуска.")
        # hasattr(bot, 'id') будет False, если bot.id не установлен

    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        ids_to_kick = data.get("ids_to_kick", [])
        ids_to_unmute = data.get("ids_to_unmute", [])
    except FileNotFoundError:
        logger.error(f"Файл с данными {INPUT_FILE} не найден. Запустите сначала Telethon-скрипт сбора ID.")
        if bot.session: await bot.session.close()
        return
    except json.JSONDecodeError:
        logger.error(f"Ошибка декодирования JSON из файла {INPUT_FILE}.")
        if bot.session: await bot.session.close()
        return
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при чтении файла {INPUT_FILE}: {e}")
        if bot.session: await bot.session.close()
        return
        
    await execute_bot_actions(bot, TARGET_CHAT_ID, ids_to_kick, ids_to_unmute)
    
    if bot.session: await bot.session.close()
    logger.info("Сессия бота-исполнителя закрыта.")

if __name__ == '__main__':
    print("Инструкции по использованию (Aiogram-исполнитель):")
    print(f"1. Убедитесь, что файл '{INPUT_FILE}' существует и содержит ID (создается Telethon-скриптом).")
    print("2. Убедитесь, что переменная окружения TELEGRAM_BOT_TOKEN установлена.")
    print(f"3. Убедитесь, что переменная окружения AIOGRAM_TARGET_CHAT_ID установлена или значение по умолчанию ({TARGET_CHAT_ID}) корректно.")
    print(f"4. Убедитесь, что бот является админом в чате {TARGET_CHAT_ID} с нужными правами.")
    print(f"5. Запустите скрипт: python execute_actions_aiogram.py")

    # import sys # Для Windows asyncio policy, если нужно
    # if sys.platform == "win32":
    #     asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main_executor_script()) 