import asyncio
import logging
from typing import List

from aiogram import Bot
# Импорты для aiogram v3.x (с учетом вашей версии 3.20.0)
from aiogram.exceptions import (
    TelegramBadRequest,      # Изменено с TelegramBadRequestError
    TelegramForbiddenError,
    TelegramNotFound,        # Изменено с ChatNotFound (UserDeactivated и BotBlocked будут ловиться через эти)
    # BotBlocked, UserDeactivated - специфичных классов нет в выводе dir(),
    # они будут пойманы как TelegramForbiddenError или TelegramBadRequest
)

from bot.db.database import DatabaseManager # Убедитесь, что путь импорта корректен

logger = logging.getLogger(__name__)

USER_CHECK_BATCH_SIZE = 3000  # Количество пользователей для проверки за один раз
MAX_DELETIONS_PER_RUN = 100   # Максимальное количество удалений за один запуск
API_CALL_DELAY = 0.05         # Задержка между вызовами API в секундах (20 запросов/сек)

async def scheduled_user_cleanup_task(bot: Bot, db_manager: DatabaseManager):
    """
    Периодическая задача для поиска и удаления пользователей, удаливших свои аккаунты
    или заблокировавших бота.
    """
    logger.info("[UserCleanup] Запуск задачи очистки удаленных пользователей (aiogram v3.20.0 compatible).")
    
    candidate_users_data = [] # Инициализируем здесь на случай ошибки в try
    try:
        candidate_users_data = await db_manager.get_users_for_cleanup_check(USER_CHECK_BATCH_SIZE)
    except Exception as e:
        logger.error(f"[UserCleanup] Не удалось получить кандидатов на удаление из БД: {e}", exc_info=True)
        return

    if not candidate_users_data:
        logger.info("[UserCleanup] Не найдено пользователей для проверки в БД (выборка пуста).")
        return

    candidate_user_ids = [user['user_id'] for user in candidate_users_data]
    logger.info(f"[UserCleanup] Получено {len(candidate_user_ids)} пользователей из БД для проверки.")

    deleted_user_ids: List[int] = []
    checked_users_count = 0

    for user_id in candidate_user_ids:
        checked_users_count += 1
        is_deleted_or_inactive = False
        error_detail = ""
        try:
            await bot.get_chat(user_id=user_id)
        except TelegramNotFound as e:
            is_deleted_or_inactive = True
            error_detail = f"TelegramNotFound: {e}"
            logger.info(f"[UserCleanup] Пользователь {user_id} не найден (TelegramNotFound). Добавлен в список на удаление.")
        except TelegramForbiddenError as e:
            is_deleted_or_inactive = True
            error_detail = f"TelegramForbiddenError: {e}"
            # Анализируем сообщение об ошибке, если нужно различать причины
            if "bot was blocked by the user" in str(e).lower():
                logger.info(f"[UserCleanup] Бот заблокирован пользователем {user_id}. Добавлен в список на удаление.")
            elif "user is deactivated" in str(e).lower():
                 logger.info(f"[UserCleanup] Пользователь {user_id} деактивирован. Добавлен в список на удаление.")
            else:
                logger.warning(f"[UserCleanup] Ошибка Forbidden для пользователя {user_id}: {e}. Добавлен в список на удаление.")
        except TelegramBadRequest as e:
            error_message = str(e).lower()
            if "user not found" in error_message or \
               "chat not found" in error_message or \
               "user_id_invalid" in error_message or \
               "peer_id_invalid" in error_message:
                is_deleted_or_inactive = True
                error_detail = f"TelegramBadRequest (user/chat not found or invalid): {e}"
                logger.info(f"[UserCleanup] Пользователь {user_id} не найден или ID невалиден (BadRequest: {e}). Добавлен в список на удаление.")
            # Некоторые случаи деактивации или блокировки могут также приходить как BadRequest с определенным текстом
            elif "user is deactivated" in error_message:
                is_deleted_or_inactive = True
                error_detail = f"TelegramBadRequest (user deactivated): {e}"
                logger.info(f"[UserCleanup] Пользователь {user_id} деактивирован (BadRequest: {e}). Добавлен в список на удаление.")
            else:
                # Логируем неожиданные BadRequest, но не добавляем на удаление автоматически, если не уверены
                logger.warning(f"[UserCleanup] Неожиданная ошибка BadRequest для пользователя {user_id}: {e}")
        except Exception as e:
            logger.error(f"[UserCleanup] Непредвиденная ошибка при проверке пользователя {user_id}: {e}", exc_info=True)
        
        if is_deleted_or_inactive:
            deleted_user_ids.append(user_id)
            # logger.debug(f"[UserCleanup] User {user_id} marked for deletion due to: {error_detail}") # Для детальной отладки

        if len(deleted_user_ids) >= MAX_DELETIONS_PER_RUN:
            logger.info(f"[UserCleanup] Достигнут лимит MAX_DELETIONS_PER_RUN ({MAX_DELETIONS_PER_RUN}) найденных удаленных пользователей. Прерывание проверки.")
            break

        await asyncio.sleep(API_CALL_DELAY)

    logger.info(f"[UserCleanup] Проверено {checked_users_count} пользователей. Найдено {len(deleted_user_ids)} кандидатов на удаление.")

    if deleted_user_ids:
        ids_to_delete = deleted_user_ids[:MAX_DELETIONS_PER_RUN]
        logger.info(f"[UserCleanup] Попытка удалить {len(ids_to_delete)} пользователей.")
        try:
            deleted_count = await db_manager.delete_users_by_ids(ids_to_delete)
            logger.info(f"[UserCleanup] Успешно удалено {deleted_count} пользователей из БД.")
        except Exception as e:
            logger.error(f"[UserCleanup] Ошибка при удалении пользователей из БД: {e}", exc_info=True)
    else:
        logger.info("[UserCleanup] Не найдено пользователей для удаления в этой сессии.")

    logger.info("[UserCleanup] Задача очистки удаленных пользователей завершена.")

# Пример того, как это может быть вызвано из __main__.py или другого планировщика
# async def scheduled_user_cleanup_task(bot: Bot, db_manager: DatabaseManager):
#     await cleanup_deleted_users(bot, db_manager) 