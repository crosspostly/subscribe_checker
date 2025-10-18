import asyncio
import logging
import os # Добавляем импорт os
from aiogram import Bot
from aiogram.types import ChatPermissions
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
# import aiogram # для вывода версии в print, если нужно, но лучше убрать если не используется активно

# --- НАСТРОЙКИ СКРИПТА ---
# BOT_TOKEN будет читаться из переменной окружения TELEGRAM_BOT_TOKEN
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    # Вместо print и return, лучше выбросить исключение, если токен критичен
    # logger.critical("Переменная окружения TELEGRAM_BOT_TOKEN не установлена!")
    # return # Это не сработает на уровне модуля
    raise ValueError("Переменная окружения TELEGRAM_BOT_TOKEN должна быть установлена.")

TARGET_CHAT_ID = -1001568712129  # ID чата, который вы предоставили

# Путь к файлу базы данных SQLite вашего бота
DB_PATH = "bot/db/database.sqlite" # Убедитесь, что путь правильный

# Задержка между обработкой каждого пользователя (в секундах)
# Увеличьте, если сталкиваетесь с ошибками флуд-контроля
DELAY_PER_USER = 0.8  # Рекомендуется 0.5 - 1.5 секунды

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
# --- КОНЕЦ НАСТРОЕК ---

# Предполагается, что ваш DatabaseManager находится здесь:
# Если он в другом месте, исправьте импорт
from bot.db.database import DatabaseManager


async def mass_unmute_and_cleanup(bot: Bot, db_manager: DatabaseManager, chat_id: int):
    logger.info(f"Запуск массового анмута и очистки для чата ID: {chat_id}")

    try:
        user_ids = await db_manager.get_all_user_ids_in_chat(chat_id)
        if not user_ids:
            logger.info(f"В базе данных не найдено пользователей для чата ID: {chat_id}.")
            return
        logger.info(f"Найдено {len(user_ids)} пользователей в БД для чата {chat_id}. Начинаем обработку...")
    except Exception as e:
        logger.error(f"Ошибка при получении пользователей из БД для чата {chat_id}: {e}", exc_info=True)
        return

    processed_count = 0
    unmuted_count = 0
    kicked_count = 0

    # Права для полного анмута
    unmute_permissions = ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_invite_users=True, 
        can_change_info=False,
        can_pin_messages=False
    )

    for user_id in user_ids:
        processed_count += 1
        # Пропускаем ID самого бота, если он есть в списке
        if bot.id == user_id:
            logger.info(f"  Пропуск ID самого бота: {user_id}")
            continue
            
        logger.info(f"\n--- Обработка пользователя {processed_count}/{len(user_ids)}: ID {user_id} ---")

        # 1. Попытка анмута
        try:
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=unmute_permissions
            )
            logger.info(f"  [АНМУТ] Пользователю {user_id} установлены полные права (анмут).")
            unmuted_count += 1
        except TelegramForbiddenError as e:
            logger.warning(f"  [АНМУТ-ОШИБКА] Недостаточно прав для анмута {user_id} или бот не админ: {e}")
        except TelegramBadRequest as e:
            error_msg_lower = str(e).lower()
            if "user not found" in error_msg_lower or \
               "chat not found" in error_msg_lower or \
               "participant_not_found" in error_msg_lower or \
               "user_is_deactivated" in error_msg_lower or \
               "member user not found" in error_msg_lower or \
               "user_not_participant" in error_msg_lower: # Добавлено user_not_participant
                logger.info(f"  [АНМУТ-ПРЕДУПРЕЖДЕНИЕ] Пользователь {user_id}, вероятно, неактивен или не в чате. Пропуск анмута. Ошибка: {e}")
            elif "member list is empty" in error_msg_lower: # Если пытаемся снять ограничения с того, кого и так нет
                 logger.info(f"  [АНМУТ-ПРЕДУПРЕЖДЕНИЕ] Пользователь {user_id} не найден в чате для анмута (member list empty). Ошибка: {e}")
            else:
                logger.error(f"  [АНМУТ-ОШИБКА] Не удалось размутить пользователя {user_id}: {e}")
        except TelegramRetryAfter as e:
            logger.warning(f"  [АНМУТ-FLOOD] Слишком много запросов. Ожидание {e.retry_after} секунд...")
            await asyncio.sleep(e.retry_after)
            try:
                await bot.restrict_chat_member(chat_id=chat_id, user_id=user_id, permissions=unmute_permissions)
                logger.info(f"  [АНМУТ-ПОВТОР] Пользователю {user_id} установлены полные права.")
                unmuted_count += 1
            except Exception as e_retry:
                 logger.error(f"  [АНМУТ-ПОВТОР-ОШИБКА] Не удалось размутить {user_id} после ожидания: {e_retry}")
        except Exception as e:
            logger.error(f"  [АНМУТ-НЕИЗВЕСТНАЯ-ОШИБКА] для пользователя {user_id}: {e}", exc_info=True)
        
        await asyncio.sleep(0.1) 

        # 2. Попытка проверки и кика "собачки"
        is_candidate_for_kick = False
        try:
            await bot.get_chat(user_id)
        except TelegramBadRequest as e:
            error_msg = str(e).lower()
            if "chat not found" == error_msg or \
               "user not found" == error_msg or \
               "peer_id_invalid" == error_msg:
                logger.info(f"  [ПРОВЕРКА-УДАЛЕНИЯ] Пользователь {user_id} похож на удаленный аккаунт (get_chat ошибка: {e}). Кандидат на кик.")
                is_candidate_for_kick = True
            else:
                logger.warning(f"  [ПРОВЕРКА-УДАЛЕНИЯ] Не удалось проверить статус {user_id} (не типовая ошибка для собачки): {e}")
        except TelegramForbiddenError as e:
            if "user is deactivated" in str(e).lower():
                 logger.info(f"  [ПРОВЕРКА-УДАЛЕНИЯ] Пользователь {user_id} деактивирован (get_chat ошибка: {e}). Кандидат на кик.")
                 is_candidate_for_kick = True
            else:
                logger.warning(f"  [ПРОВЕРКА-УДАЛЕНИЯ] Доступ запрещен к {user_id} (возможно, заблокировал бота): {e}")
        except Exception as e:
            logger.error(f"  [ПРОВЕРКА-УДАЛЕНИЯ-НЕИЗВЕСТНАЯ-ОШИБКА] для {user_id}: {e}", exc_info=True)

        if is_candidate_for_kick:
            try:
                await bot.ban_chat_member(chat_id=chat_id, user_id=user_id, revoke_messages=False) # revoke_messages=False, чтобы не удалять сообщения
                logger.info(f"    [КИК-УСПЕХ] Пользователь {user_id} (предположительно удаленный) кикнут из чата {chat_id}.")
                kicked_count += 1
            except TelegramForbiddenError as e:
                logger.warning(f"    [КИК-ОШИБКА] Недостаточно прав для кика {user_id} из чата {chat_id} или бот не админ: {e}")
            except TelegramBadRequest as e:
                error_msg_lower = str(e).lower()
                if "user_not_mutual_contact" in error_msg_lower or \
                   "user_is_an_administrator_of_the_chat" in error_msg_lower or \
                   "rights_too_high" in error_msg_lower or \
                   "chatmember_status_invalid" in error_msg_lower: # Например, пытаемся кикнуть того, кто уже не участник
                     logger.warning(f"    [КИК-ОШИБКА] Не могу кикнуть {user_id} (админ/неконтакт/не участник?): {e}")
                else:
                    logger.error(f"    [КИК-ОШИБКА] Не удалось кикнуть {user_id} из чата {chat_id}: {e}")
            except TelegramRetryAfter as e:
                logger.warning(f"    [КИК-FLOOD] Слишком много запросов. Ожидание {e.retry_after} секунд...")
                await asyncio.sleep(e.retry_after)
                try:
                    await bot.ban_chat_member(chat_id=chat_id, user_id=user_id, revoke_messages=False)
                    logger.info(f"    [КИК-ПОВТОР-УСПЕХ] Пользователь {user_id} кикнут после ожидания.")
                    kicked_count += 1
                except Exception as e_retry:
                    logger.error(f"    [КИК-ПОВТОР-ОШИБКА] Не удалось кикнуть {user_id} после ожидания: {e_retry}")
            except Exception as e:
                logger.error(f"    [КИК-НЕИЗВЕСТНАЯ-ОШИБКА] для {user_id} в чате {chat_id}: {e}", exc_info=True)
        
        logger.info(f"--- Пауза {DELAY_PER_USER} сек. ---")
        await asyncio.sleep(DELAY_PER_USER)

    logger.info("\n--- ЗАВЕРШЕНИЕ РАБОТЫ СКРИПТА ---")
    logger.info(f"Всего обработано записей из БД: {processed_count}")
    logger.info(f"Попыток анмута совершено: {unmuted_count}")
    logger.info(f"Пользователей кикнуто (предположительно удаленных): {kicked_count}")

async def main_aiogram_script():
    bot = Bot(token=BOT_TOKEN)
    
    try:
        db_manager = DatabaseManager(db_path=DB_PATH)
        # Если ваш DatabaseManager требует явного вызова connect/init_pool
        if hasattr(db_manager, 'connect') and asyncio.iscoroutinefunction(db_manager.connect):
            await db_manager.connect()
        elif hasattr(db_manager, 'init_pool') and asyncio.iscoroutinefunction(db_manager.init_pool):
             await db_manager.init_pool()

    except Exception as e:
        logger.error(f"Не удалось инициализировать или подключиться к DatabaseManager: {e}", exc_info=True)
        logger.error("Убедитесь, что класс DatabaseManager и путь к БД указаны верно.")
        if bot.session:
            await bot.session.close()
        return

    try:
        # Получим ID самого бота для последующего пропуска
        bot_info = await bot.get_me()
        bot.id = bot_info.id # Сохраняем ID бота в объекте бота для удобства
        logger.info(f"Бот успешно инициализирован: {bot_info.full_name} (ID: {bot.id})")
        await mass_unmute_and_cleanup(bot, db_manager, TARGET_CHAT_ID)
    except Exception as e:
        logger.critical(f"Критическая ошибка при выполнении основного скрипта: {e}", exc_info=True)
    finally:
        if bot.session:
            await bot.session.close()
        if hasattr(db_manager, 'disconnect') and asyncio.iscoroutinefunction(db_manager.disconnect):
            await db_manager.disconnect()
        elif hasattr(db_manager, 'close_pool') and asyncio.iscoroutinefunction(db_manager.close_pool): # Если есть метод close_pool
            await db_manager.close_pool()
        logger.info("Сессия бота и соединение с БД (если было) закрыты.")

if __name__ == '__main__':
    print("Инструкции по использованию (Aiogram версия):")
    print("1. Убедитесь, что Aiogram установлен: pip install aiogram")
    print("2. Заполните BOT_TOKEN (ВАШ_БОТ_ТОКЕН), TARGET_CHAT_ID (уже ваш), и DB_PATH в начале этого скрипта.")
    print("3. Убедитесь, что класс DatabaseManager доступен по пути 'bot.db.database' и что метод 'get_all_user_ids_in_chat(chat_id)' в нем существует.")
    print("4. Убедитесь, что бот, чей токен используется, является администратором в целевом чате с правами на ограничение и бан участников.")
    print("5. Запустите скрипт: python unmute_cleanup_aiogram.py")
    
    # import sys # Если будете использовать ниже
    # if sys.platform == "win32":
    #     asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            
    asyncio.run(main_aiogram_script()) 