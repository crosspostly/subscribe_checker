# collect_user_ids_telethon.py
import asyncio
import os
import json
from telethon import TelegramClient
from telethon.tl.types import ChannelParticipantsAdmins, ChannelParticipantsBanned, ChannelParticipantsSearch
from telethon.errors.rpcerrorlist import ChatAdminRequiredError

# --- НАСТРОЙКИ ---
API_ID = os.getenv('TELETHON_API_ID', 23746403)
API_HASH = os.getenv('TELETHON_API_HASH', '68016b0a173c5e183196731107ef19fe')
CHAT_IDENTIFIER = os.getenv('TELETHON_CHAT_ID', -1001568712129)
SESSION_NAME = 'my_collector_session'
OUTPUT_FILE = 'user_ids_for_bot.json'
DELAY_ITERATION = 0.05 # Небольшая задержка при переборе, чтобы не слишком агрессивно

# Настройка логирования (базовая)
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    API_ID = int(API_ID)
except ValueError:
    logger.critical("Ошибка: API_ID должен быть числом. Проверьте значение или переменную окружения TELETHON_API_ID.")
    exit(1)
try:
    CHAT_IDENTIFIER = int(CHAT_IDENTIFIER)
except ValueError:
    pass # Оставляем как строку, если это username

async def main_collector():
    logger.info(f"Запуск скрипта сбора ID пользователей (Telethon) для чата: {CHAT_IDENTIFIER}...")
    ids_to_kick = []
    ids_to_unmute = []

    async with TelegramClient(SESSION_NAME, API_ID, API_HASH) as client:
        if not await client.is_user_authorized():
            logger.error("Клиент не авторизован. Пожалуйста, запустите скрипт для входа (введите номер телефона и код).")
            return
        logger.info("Клиент успешно авторизован.")

        try:
            chat = await client.get_entity(CHAT_IDENTIFIER)
            logger.info(f"Чат найден: '{getattr(chat, 'title', chat.id)}' (ID: {chat.id})")
        except ChatAdminRequiredError:
            logger.critical(f"Критическая ошибка: У аккаунта нет прав администратора в чате '{CHAT_IDENTIFIER}' или чат недоступен.")
            return
        except Exception as e:
            logger.error(f"Ошибка получения информации о чате '{CHAT_IDENTIFIER}': {e}", exc_info=True)
            return

        admins = []
        try:
            logger.info("Получение списка администраторов...")
            async for admin_user in client.iter_participants(chat, filter=ChannelParticipantsAdmins):
                admins.append(admin_user.id)
            logger.info(f"Найдено администраторов: {len(admins)}. Они будут пропущены.")
        except ChatAdminRequiredError:
            logger.warning("Не удалось получить список администраторов (необходимы права администратора в чате). Продолжаем без списка админов.")
        except Exception as e:
            logger.warning(f"Ошибка при получении списка администраторов: {e}. Продолжаем без списка админов.")

        processed_count = 0
        logger.info("Начало перебора участников чата...")
        try:
            async for user in client.iter_participants(chat, aggressive=False):
                processed_count += 1
                if processed_count % 200 == 0: # Логируем каждые 200 пользователей
                    logger.info(f"Обработано участников: {processed_count}...")

                if user.id in admins:
                    continue

                if user.bot: # Пропускаем других ботов
                    # logger.debug(f"Пропущен бот: {user.id} (@{user.username or ''})")
                    continue

                if user.deleted:
                    if user.id not in ids_to_kick: # Избегаем дубликатов, если вдруг
                        ids_to_kick.append(user.id)
                        logger.info(f"  Найден удаленный аккаунт для кика: {user.id}")
                else:
                    participant_data = getattr(user, 'participant', None)
                    if participant_data and hasattr(participant_data, 'banned_rights') and \
                       participant_data.banned_rights and participant_data.banned_rights.send_messages:
                        if user.id not in ids_to_unmute:
                            ids_to_unmute.append(user.id)
                            logger.info(f"  Найден пользователь для анмута: {user.id} ({user.first_name or ''} @{user.username or 'N/A'})")
                
                await asyncio.sleep(DELAY_ITERATION)
        except ChatAdminRequiredError: # Может возникнуть здесь, если права были отозваны во время работы
            logger.error("Ошибка: Потеряны права администратора во время перебора участников.")
        except Exception as e:
            logger.error(f"Неожиданная ошибка во время перебора участников: {e}", exc_info=True)

    # Убираем дубликаты на всякий случай, хотя логика выше уже должна это делать
    output_data = {
        "ids_to_kick": list(set(ids_to_kick)),
        "ids_to_unmute": list(set(ids_to_unmute))
    }
    
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=4)
        logger.info(f"Сбор ID завершен. Данные сохранены в файл: {OUTPUT_FILE}")
    except IOError as e:
        logger.error(f"Ошибка записи в файл {OUTPUT_FILE}: {e}")

    logger.info(f"Найдено ID для кика: {len(output_data['ids_to_kick'])}")
    logger.info(f"Найдено ID для анмута: {len(output_data['ids_to_unmute'])}")
    logger.info("Работа скрипта сбора завершена.")

if __name__ == '__main__':
    print("Инструкции по использованию (Telethon-сборщик ID):")
    print("1. Установите Telethon: pip install telethon")
    print("2. Убедитесь, что переменные окружения TELETHON_API_ID, TELETHON_API_HASH, TELETHON_CHAT_ID установлены,")
    print("   либо измените значения по умолчанию прямо в скрипте.")
    print("3. Аккаунт, используемый для запуска, должен иметь возможность читать участников чата (обычно админские права не нужны для этого, но для get_entity могут потребоваться, если чат приватный).")
    print("4. Запустите скрипт: python collect_user_ids_telethon.py")
    print(f"5. Результаты будут сохранены в {OUTPUT_FILE}")

    asyncio.run(main_collector()) 