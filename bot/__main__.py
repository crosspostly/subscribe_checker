import asyncio
import logging
import os
import sys # Добавляем sys
import time # Добавляем time для работы с временем
import shutil # Добавляем shutil для работы с файлами и папками
# import aioschedule # Удаляем импорт aioschedule
from apscheduler.schedulers.asyncio import AsyncIOScheduler # <--- Импортируем APScheduler

# Импортируем нужные объекты
import bot.bot_instance as bi # <--- НОВЫЙ СПОСОБ ИМПОРТА

# Импортируем роутеры
from bot.handlers import admin, callbacks, group_messages, group_admin, fsm_private, private_messages

# Импортируем сервисы
from bot.services.captcha import CaptchaService
from bot.services.subscription import SubscriptionService
# Добавляем импорт нового сервиса очистки пользователей
from bot.services.user_cleanup_service import scheduled_user_cleanup_task

# Импортируем настройки для доступа к BOT_USERNAME
from bot.config import settings, BOT_OWNER_ID # Импортируем BOT_OWNER_ID для напоминаний

# Импортируем исключения, необходимые для аннотаций
from aiogram.exceptions import TelegramAPIError, TelegramConflictError, TelegramForbiddenError
from aiogram.utils.markdown import hbold # Для форматирования текста уведомления

# --- Настройка логирования с colorlog --- (Новый блок)

LOGS_DIR = "logs"
LOG_LEVEL = logging.INFO # Уровень логирования (INFO, DEBUG, WARNING, ERROR, CRITICAL)
LOG_FILE_MAX_SIZE_MB = 300 # Максимальный размер папки логов в МБ
LOG_FILE_MAX_SIZE_BYTES = LOG_FILE_MAX_SIZE_MB * 1024 * 1024 # Переводим в байты
LOG_FORMAT_CONSOLE = '%(log_color)s%(asctime)s | %(levelname)-8s | %(name)-15s | %(funcName)-20s | %(lineno)-4d | %(message)s%(reset)s'
LOG_FORMAT_FILE = '%(asctime)s | %(levelname)-8s | %(name)-25s | %(funcName)-20s | %(lineno)-4d | %(message)s'

# Создаем папку для логов
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR)

# Базовая конфигурация logging
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT_FILE)

# Настройка colorlog для консоли
try:
    import colorlog
    # Настройка обработчика для консоли с цветами
    console_handler = colorlog.StreamHandler(sys.stdout)
    console_handler.setFormatter(colorlog.ColoredFormatter(LOG_FORMAT_CONSOLE, datefmt='%Y-%m-%d %H:%M:%S'))

    # Настройка обработчика для файла (без цветов)
    file_handler = logging.FileHandler(os.path.join(LOGS_DIR, "bot.log"), encoding='utf-8')
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT_FILE, datefmt='%Y-%m-%d %H:%M:%S'))

    # Получаем корневой логгер и добавляем обработчики
    root_logger = logging.getLogger()
    root_logger.handlers = [] # Удаляем стандартные обработчики basicConfig
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.setLevel(LOG_LEVEL)

    logging.getLogger('aiogram').setLevel(logging.WARNING) # Уменьшаем шум от aiogram
    logging.getLogger('aiosqlite').setLevel(logging.WARNING) # Уменьшаем шум от aiosqlite
    logging.getLogger('asyncio').setLevel(logging.WARNING)
    logging.getLogger('apscheduler').setLevel(logging.WARNING) # <--- Добавим для APScheduler

    logger = logging.getLogger(__name__) # Получаем логгер для этого модуля
    logger.info("Colorlog успешно настроен.")

except ImportError:
    print("Библиотека colorlog не найдена. Установите ее: pip install colorlog")
    print("Логирование будет работать без цветов в консоли.")
    # Используем стандартную конфигурацию без цветов
    logging.basicConfig(
        level=LOG_LEVEL,
        format=LOG_FORMAT_FILE,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(os.path.join(LOGS_DIR, "bot.log"), encoding='utf-8')
        ],
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logging.getLogger('aiogram').setLevel(logging.WARNING)
    logging.getLogger('aiosqlite').setLevel(logging.WARNING)
    logging.getLogger('asyncio').setLevel(logging.WARNING)
    logging.getLogger('apscheduler').setLevel(logging.WARNING) # <--- Добавим для APScheduler
    logger = logging.getLogger(__name__)
    logger.warning("Colorlog не найден, логирование в консоли без цветов.")

# ---------------------------------------

# --- Новая функция для обработки устаревших чатов ---
async def process_legacy_chats(bot_instance, db_manager_instance):
    """При старте проверяет "старые" неактивированные чаты и деактивирует их, уведомляя админов."""
    logger.info("Запуск проверки устаревших неактивированных чатов...")
    try:
        legacy_chats = await db_manager_instance.get_legacy_unactivated_chats()
        if not legacy_chats:
            logger.info("Не найдено устаревших неактивированных чатов для обработки.")
            return

        logger.warning(f"Найдено {len(legacy_chats)} устаревших чатов, требующих переактивации. Начинаю обработку...")
        processed_count = 0
        deactivated_count = 0
        
        bot_username = bi.actual_bot_username # Получаем актуальный юзернейм
        if not bot_username:
             logger.error("Не удалось получить юзернейм бота для уведомления устаревших чатов. Обработка прервана.")
             return

        for chat_info in legacy_chats:
            chat_id = chat_info['chat_id']
            chat_title = chat_info.get('chat_title') or f"Чат ID {chat_id}"
            logger.info(f"Обработка устаревшего чата: {chat_id} ('{chat_title}')...")

            notification_text = (
                f"⚠️ {hbold('Вниманию администраторов чата!')} ⚠️\\n\\n"
                f"Бот @{bot_username} в вашем чате «{hbold(chat_title)}» требует "
                f"повторной активации владельцем бота для корректной работы в связи с обновлением системы.\\n\\n"
                f"Пожалуйста, один из администраторов группы должен выполнить команду /code в личных сообщениях с ботом (@{bot_username}), "
                f"а затем отправить полученный код (вида `setup_КОД`) прямо в этот чат («{chat_title}»).\\n\\n"
                f"После этого владелец бота получит запрос на активацию. "
                f"До момента активации основной функционал бота в этом чате (проверка подписок и т.д.) будет приостановлен.\\n\\n"
                f"Приносим извинения за возможные неудобства."
            )

            deactivate_chat = False
            try:
                await bot_instance.send_message(chat_id, notification_text, parse_mode="HTML", disable_web_page_preview=True)
                logger.info(f"Уведомление успешно отправлено в устаревший чат {chat_id} ('{chat_title}').")
                deactivate_chat = True # Деактивируем после успешной отправки
            except TelegramForbiddenError:
                logger.warning(f"Не удалось отправить уведомление в устаревший чат {chat_id} ('{chat_title}') - бот заблокирован или удален. Чат будет деактивирован в БД.")
                deactivate_chat = True # Деактивируем, даже если не смогли уведомить
            except TelegramAPIError as e:
                # Обработка других ошибок API, например, если чат не найден
                logger.error(f"Ошибка API при отправке уведомления в устаревший чат {chat_id} ('{chat_title}'): {e}. Деактивация будет выполнена.")
                deactivate_chat = True # Деактивируем, так как чат, вероятно, недоступен
            except Exception as e_send:
                 logger.error(f"Непредвиденная ошибка при отправке уведомления в устаревший чат {chat_id} ('{chat_title}'): {e_send}. Деактивация НЕ будет выполнена для этого чата.")
                 # Не деактивируем при совсем непонятных ошибках

            if deactivate_chat:
                if await db_manager_instance.deactivate_legacy_chat(chat_id):
                    deactivated_count += 1
                # Опционально: выход из чата
                # try:
                #     await bot_instance.leave_chat(chat_id)
                #     logger.info(f"Бот покинул устаревший чат {chat_id} ('{chat_title}').")
                # except Exception as e_leave:
                #     logger.error(f"Не удалось покинуть устаревший чат {chat_id} ('{chat_title}'): {e_leave}")
            
            processed_count += 1
            await asyncio.sleep(0.1) # Небольшая пауза между обработкой чатов

        logger.warning(f"Обработка устаревших чатов завершена. Обработано: {processed_count}, Деактивировано в БД: {deactivated_count}.")

    except Exception as e:
        logger.error(f"Критическая ошибка в процессе обработки устаревших чатов: {e}", exc_info=True)

async def main():
    logger.info("Запуск бота...")

    # Устанавливаем актуальный юзернейм бота через функцию в bot_instance
    await bi.set_actual_bot_username() 
    if not bi.actual_bot_username:
        logger.error("НЕ УДАЛОСЬ ОПРЕДЕЛИТЬ ЮЗЕРНЕЙМ БОТА. Проверьте токен и доступ к API Telegram. Сообщения с упоминанием бота могут быть некорректны (@None).")
    # Старая логика прямой установки bi.actual_bot_username из __main__ удалена.

    # Инициализация базы данных
    try:
        await bi.db_manager.init_db()
        logger.info("База данных успешно инициализирована.")
        # ВЫЗЫВАЕМ МИГРАЦИИ ПОСЛЕ ИНИЦИАЛИЗАЦИИ
        await bi.db_manager.run_migrations()
        logger.info("Миграции базы данных успешно выполнены.")
    except Exception as e:
        logger.critical(f"Критическая ошибка при инициализации или миграции БД: {e}", exc_info=True)
        return # Завершаем работу, если БД не инициализирована или миграция не удалась

    # --- Создание экземпляров сервисов ---
    captcha_service = CaptchaService(bi.bot, bi.db_manager)
    subscription_service = SubscriptionService(bi.bot, bi.db_manager)
    logger.info("Экземпляры CaptchaService и SubscriptionService созданы.")

    # --- Передача сервисов в workflow_data диспетчера ---
    # Это позволит передавать их в обработчики как аргументы
    bi.dp["captcha_service"] = captcha_service
    bi.dp["subscription_service"] = subscription_service
    logger.info("Сервисы CaptchaService и SubscriptionService добавлены в workflow_data диспетчера.")

    # --- Запуск обработки устаревших чатов ПОСЛЕ инициализации БД и получения юзернейма ---
    # Запускаем в фоне, чтобы не блокировать старт бота
    # asyncio.create_task(process_legacy_chats(bi.bot, bi.db_manager)) # ВРЕМЕННО ОТКЛЮЧЕНО: функция отработала, чаты обработаны.
    # --- Конец вызова --- 

    # Подключение роутеров
    bi.dp.include_router(private_messages.pm_router)
    logger.debug("Роутер для ЛС (pm_router) подключен.")
    bi.dp.include_router(fsm_private.fsm_private_router)
    logger.debug("Роутер FSM в ЛС подключен.")
    
    bi.dp.include_router(group_admin.group_admin_router)
    logger.debug("Роутер администрирования групп подключен.")
    bi.dp.include_router(admin.admin_router)
    logger.debug("Админский роутер подключен.")
    bi.dp.include_router(callbacks.callback_router)
    logger.debug("Роутер коллбеков подключен.")
    bi.dp.include_router(group_messages.group_msg_router)
    logger.debug("Роутер сообщений групп подключен.")

    # Удаление вебхука перед запуском (на всякий случай)
    try:
        await bi.bot.delete_webhook(drop_pending_updates=True)
        logger.info("Вебхук удален, ожидающие обновления сброшены.")
    except TelegramAPIError as e:
        logger.warning(f"Не удалось удалить вебхук: {e}")

    # --- Инициализация и запуск APScheduler --- 
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow") # Укажите ваш часовой пояс или удалите timezone для UTC

    # Добавляем задачу clean_old_bot_messages
    scheduler.add_job(
        clean_old_bot_messages, 
        trigger='interval', 
        hours=1, 
        id='clean_bot_messages_job', # Даем ID для удобства управления
        replace_existing=True, # Заменять задачу, если она уже существует с таким ID
        args=[bi.bot, bi.db_manager] # <--- ИЗМЕНЕНИЕ ЗДЕСЬ
    )
    logger.info("Запланирована задача clean_old_bot_messages каждые 1 час через APScheduler.")

    # Добавляем задачу send_daily_activation_reminders
    # Эта задача будет выполняться каждый день в определенное время (например, в 10:00)
    scheduler.add_job(
        send_daily_activation_reminders,
        trigger='cron',
        hour=10, # Например, в 10 утра
        minute=0,
        id='daily_activation_reminders_job',
        replace_existing=True,
        kwargs={"bot_instance": bi.bot, "db_manager_instance": bi.db_manager} 
    )
    logger.info("Запланирована задача send_daily_activation_reminders (ежедневно в 10:00) через APScheduler.")
    
    # Добавляем задачу clean_logs_task
    # Эта задача будет выполняться, например, раз в день
    scheduler.add_job(
        clean_logs_task, 
        trigger='cron', 
        hour=3, # Например, в 3 часа ночи
        minute=30,
        id='clean_logs_job',
        replace_existing=True
    )
    logger.info("Запланирована задача clean_logs_task (ежедневно в 03:30) через APScheduler.")

    # Добавляем новую задачу очистки удаленных пользователей
    scheduler.add_job(
        scheduled_user_cleanup_task, 
        trigger='interval', 
        hours=24, 
        id='user_cleanup_job',
        replace_existing=True,
        kwargs={"bot": bi.bot, "db_manager": bi.db_manager} # Передаем bot и db_manager
    )
    logger.info("Запланирована задача scheduled_user_cleanup_task (каждые 24 часа) через APScheduler.")

    scheduler.start()
    logger.info("APScheduler запущен.")
    # --- Конец блока APScheduler --- 

    # Настройка команд меню бота
    # Запуск фоновой задачи напоминаний (ПЕРЕД setup_bot_commands, чтобы owner_id был доступен)
    # asyncio.create_task(send_daily_activation_reminders(bi.bot, bi.db_manager))
    logger.info("Запущена фоновая задача ежедневных напоминаний об активации.")

    await setup_bot_commands(bi.bot)
    logger.info("Команды меню бота настроены")

    # Запуск поллинга
    logger.info("Запуск polling...")
    try:
        # Получаем список используемых типов обновлений
        allowed_update_types = bi.dp.resolve_used_update_types()
        # Гарантированно добавляем 'chat_member', если его нет
        if "chat_member" not in allowed_update_types:
            allowed_update_types.append("chat_member")
            logger.info("Тип обновления 'chat_member' принудительно добавлен в allowed_updates.")

        # Убираем цикл while True, так как start_polling сам по себе является блокирующим вызовом,
        # который работает до получения сигнала остановки или критической ошибки.
            await bi.dp.start_polling(bi.bot, allowed_updates=allowed_update_types, timeout=30)

    except TelegramConflictError:
        logger.critical("ОШИБКА: Обнаружен другой запущенный экземпляр бота! Завершение работы.")
    except Exception as e:
        logger.critical(f"Критическая ошибка в процессе polling: {e}", exc_info=True)
    finally:
        logger.info("Завершение работы APScheduler...")
        if scheduler.running:
            scheduler.shutdown()
        logger.info("APScheduler остановлен.")
        
        logger.info("Завершение работы бота...")
        try:
            await bi.bot.session.close()
            logger.info("Сессия бота закрыта.")
        except Exception as e:
            logger.error(f"Ошибка при закрытии сессии бота: {e}")
        await bi.db_manager.close_db()
        logger.info("Соединение с БД закрыто.")
        logger.info("Бот остановлен.")

async def send_daily_activation_reminders(bot_instance, db_manager_instance):
    """Фоновая задача: Ежедневно отправляет напоминания об активации."""
    from aiogram import Bot # Импорт внутри функции
    from bot.db.database import DatabaseManager # Импорт внутри функции
    from bot.config import BOT_OWNER_USERNAME # Импортируем здесь, чтобы избежать циклич. импорта
    while True:
        try:
            REMINDER_INTERVAL_SECONDS = 24 * 60 * 60
            if not BOT_OWNER_ID:
                 logger.warning("Не указан BOT_OWNER_ID, задача напоминаний не будет работать корректно.")
                 await asyncio.sleep(REMINDER_INTERVAL_SECONDS)
                 continue

            current_time = int(time.time())
            reminder_threshold_ts = current_time - REMINDER_INTERVAL_SECONDS
            chats_to_remind = await db_manager_instance.get_unactivated_chats_for_reminder(
                owner_id=BOT_OWNER_ID, 
                reminder_threshold_ts=reminder_threshold_ts
            )
            if chats_to_remind:
                logger.info(f"Найдено {len(chats_to_remind)} чатов, которым нужно отправить напоминание об активации.")
                for chat_info in chats_to_remind:
                    chat_id = chat_info.get('chat_id')
                    chat_title = chat_info.get('chat_title', f'Чат ID {chat_id}') 
                    configured_by_user_id = chat_info.get('configured_by_user_id')
                    if not configured_by_user_id:
                        logger.warning(f"Чат {chat_id} ('{chat_title}') в списке напоминаний, но configured_by_user_id не найден. Пропускаем.")
                        continue
                    
                    admin_contact = "администратором бота"
                    if BOT_OWNER_USERNAME:
                        admin_contact = f'администратором бота (@{BOT_OWNER_USERNAME})'
                    
                    reminder_text = (
                        f"🔔 <b>Напоминание об активации чата</b> «{chat_title}»!\n\n"
                        f"Бот в чате «{chat_title}» настроен, но еще не активирован "
                        f"и не выполняет свои функции.\n\n"
                        f"Пожалуйста, введите код активации в этом диалоге, чтобы включить бота.\n"
                        f"Если у вас нет кода, свяжитесь с {admin_contact}."
                    )
                    try:
                        await bot_instance.send_message(configured_by_user_id, reminder_text, parse_mode="HTML")
                        logger.info(f"Отправлено напоминание об активации пользователю {configured_by_user_id} для чата {chat_id} ('{chat_title}').")
                        await db_manager_instance.update_last_activation_request_ts(chat_id)
                        logger.debug(f"Обновлен last_activation_request_ts для чата {chat_id}.")
                    except TelegramForbiddenError:
                        logger.warning(f"Не удалось отправить напоминание пользователю {configured_by_user_id} (бот заблокирован?). Чат {chat_id}.")
                    except Exception as e:
                        logger.error(f"Ошибка при отправке напоминания пользователю {configured_by_user_id} для чата {chat_id}: {e}", exc_info=True)
            else:
                logger.debug("Нет чатов, которым нужно отправить напоминание об активации.")
        except Exception as e:
            logger.error(f"Ошибка в фоновой задаче ежедневных напоминаний: {e}", exc_info=True)
        await asyncio.sleep(REMINDER_INTERVAL_SECONDS)

async def setup_bot_commands(bot_instance):
    """Устанавливает команды меню бота"""
    from aiogram import Bot # Импорт внутри функции
    from aiogram.types import BotCommand, BotCommandScopeDefault
    commands = [
        BotCommand(command="start", description="Начать работу с ботом"),
        BotCommand(command="code", description="Получить код настройки для группы"),
        BotCommand(command="chats", description="Показать настроенные чаты"),
        BotCommand(command="help", description="Показать справку по командам")
    ]
    try:
        await bot_instance.set_my_commands(commands, scope=BotCommandScopeDefault())
        logger.info("Команды меню бота успешно настроены")
    except TelegramAPIError as e:
        logger.error(f"Ошибка при настройке команд меню бота: {e}")

async def clean_old_bot_messages(bot_instance, db_manager_instance):
    """
    Периодическая задача для удаления старых сообщений бота, которые могли остаться
    из-за перезапусков или ошибок при удалении.
    """
    logger.info("Запущена задача очистки старых сообщений бота...")
    AGE_SECONDS_FOR_CLEANUP = 10 * 60 
    try:
        messages_to_delete = await db_manager_instance.get_old_bot_messages_for_cleanup(AGE_SECONDS_FOR_CLEANUP)
        if not messages_to_delete:
            logger.info("Нет старых сообщений бота для удаления.")
            return
        logger.info(f"Найдено {len(messages_to_delete)} старых сообщений бота для удаления (старше {AGE_SECONDS_FOR_CLEANUP // 60} минут).")
        deleted_count = 0
        for msg_info in messages_to_delete:
            chat_id = msg_info['chat_id']
            message_id = msg_info['message_id']
            try:
                await bot_instance.delete_message(chat_id=chat_id, message_id=message_id)
                logger.info(f"Сообщение {message_id} успешно удалено из чата {chat_id}.")
                await db_manager_instance.remove_bot_message_from_cleanup(chat_id, message_id)
                logger.debug(f"Запись о сообщении {message_id} в чате {chat_id} удалена из БД.")
                deleted_count += 1
            except TelegramAPIError as e:
                if "message to delete not found" in str(e).lower() or \
                   "message can't be deleted" in str(e).lower() or \
                   "message_not_modified" in str(e).lower():
                    logger.warning(f"Сообщение {message_id} в чате {chat_id} уже удалено или не может быть удалено: {e}. Удаляю запись из БД.")
                    await db_manager_instance.remove_bot_message_from_cleanup(chat_id, message_id)
                    logger.debug(f"Запись о сообщении {message_id} в чате {chat_id} (не найдено в TG) удалена из БД.")
                elif isinstance(e, TelegramForbiddenError):
                     logger.warning(f"Не удалось удалить сообщение {message_id} из чата {chat_id}: бот заблокирован или нет прав. {e}. Удаляю запись из БД.")
                     await db_manager_instance.remove_bot_message_from_cleanup(chat_id, message_id)
                else:
                    logger.error(f"Ошибка при удалении сообщения {message_id} из чата {chat_id}: {e}")
            except Exception as e:
                logger.error(f"Непредвиденная ошибка при обработке сообщения {message_id} в чате {chat_id} для удаления: {e}", exc_info=True)
        if deleted_count > 0:
            logger.info(f"Успешно удалено {deleted_count} из {len(messages_to_delete)} найденных старых сообщений бота.")
        elif messages_to_delete:
            logger.warning(f"Не удалось удалить ни одно из {len(messages_to_delete)} найденных сообщений из-за ошибок (см. логи выше).")
    except Exception as e:
        logger.error(f"Ошибка в задаче очистки старых сообщений бота: {e}", exc_info=True)

async def clean_logs_task():
    """Фоновая задача: Периодически проверяет размер папки логов и очищает её."""
    # Ждем небольшое время после старта, чтобы не нагружать систему сразу
    await asyncio.sleep(60) # Ждем 60 секунд
    logger.info("Запущена фоновая задача очистки логов.")

    while True:
        try:
            if not os.path.exists(LOGS_DIR):
                logger.warning(f"Папка логов \'{LOGS_DIR}\' не найдена, очистка невозможна.")
                await asyncio.sleep(3600) # Ждем 1 час перед следующей попыткой
                continue

            # Вычисляем текущий размер папки логов
            total_size = 0
            for dirpath, dirnames, filenames in os.walk(LOGS_DIR):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if not os.path.islink(fp): # Проверяем, что это не симлинк
                        total_size += os.path.getsize(fp)

            logger.debug(f"Текущий размер папки логов \'{LOGS_DIR}\': {total_size / (1024*1024):.2f} МБ (лимит: {LOG_FILE_MAX_SIZE_MB} МБ)")

            # Если размер превышает лимит, начинаем очистку
            if total_size > LOG_FILE_MAX_SIZE_BYTES:
                logger.warning(f"Размер папки логов ({total_size / (1024*1024):.2f} МБ) превышает лимит ({LOG_FILE_MAX_SIZE_MB} МБ). Начинаю очистку...")
                
                # Получаем список файлов с информацией о времени модификации
                files = []
                for dirpath, dirnames, filenames in os.walk(LOGS_DIR):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        if not os.path.islink(fp): # Проверяем, что это не симлинк
                            files.append((fp, os.path.getmtime(fp)))
                            
                # Сортируем файлы по времени модификации (самые старые в начале)
                files.sort(key=lambda x: x[1])
                
                # Удаляем файлы, пока размер не станет меньше лимита или пока не останется файлов
                for fp, mtime in files:
                    try:
                        file_size_before_delete = os.path.getsize(fp) # Получаем размер ДО удаления
                        os.remove(fp)
                        total_size -= file_size_before_delete # Вычитаем сохраненный размер
                        logger.info(f"Удален старый файл лога: {fp}")
                        
                        if total_size < LOG_FILE_MAX_SIZE_BYTES:
                            logger.info("Размер папки логов стал меньше лимита.")
                            break # Прекращаем удаление, если достигли лимита
                            
                    except OSError as e:
                        logger.error(f"Ошибка при удалении файла лога {fp}: {e}")
                    except Exception as e:
                        logger.error(f"Непредвиденная ошибка при удалении файла лога {fp}: {e}", exc_info=True)
                        
                logger.warning(f"Очистка папки логов завершена. Текущий размер: {total_size / (1024*1024):.2f} МБ")

        except Exception as e:
            logger.error(f"Ошибка в фоновой задаче очистки логов: {e}", exc_info=True)

        # Ждем перед следующей проверкой (например, 1 час = 3600 секунд)
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        # Запускаем основную асинхронную функцию main()
        asyncio.run(main())

    except KeyboardInterrupt:
        logger.info("Получен сигнал завершения (KeyboardInterrupt). Завершаю работу...")
    except Exception as e:
        logger.critical(f"Неперехваченное исключение на верхнем уровне: {e}", exc_info=True)
    finally:
        logger.info("Программа завершена.") 