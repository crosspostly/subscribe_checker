import logging
from typing import Optional, List, Dict, Any, Tuple
import asyncio
import time

from aiogram import Router, F, types, Bot
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.utils.markdown import hlink, hbold, hitalic, hcode, hpre
from aiogram.fsm.context import FSMContext # Импортируем FSMContext

from bot.db.database import DatabaseManager
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.data.callback_data import ManageSpecificChatCallback
from bot.utils.helpers import get_user_mention_html
from bot.bot_instance import bot, db_manager, actual_bot_username
from bot.middlewares.db_middleware import DbSessionMiddleware
from bot.middlewares.bot_middleware import BotMiddleware

from bot.states import Activation # Импортируем StatesGroup Activation
from bot.services.channel_management import ChannelManagementService # Импортируем сервис управления каналами

logger = logging.getLogger(__name__)
pm_router = Router()

# Регистрируем middleware
pm_router.message.middleware.register(DbSessionMiddleware(db_manager))
pm_router.callback_query.middleware.register(DbSessionMiddleware(db_manager))

pm_router.message.middleware.register(BotMiddleware(bot))
pm_router.callback_query.middleware.register(BotMiddleware(bot))

# Фильтр, чтобы роутер реагировал только на сообщения в личке
pm_router.message.filter(F.chat.type == ChatType.PRIVATE) 
pm_router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE) # Добавляем фильтр для колбэков

# Хелпер для извлечения реферер ID из payload
def extract_referrer_id(payload: Optional[str]) -> Optional[int]:
    if payload and payload.isdigit():
        try:
            ref_id = int(payload)
            # Доп. проверка: ID не должен быть слишком большим или отрицательным
            if 0 < ref_id < 2**31: # Примерный диапазон для user_id
                return ref_id
        except (ValueError, TypeError):
            pass
    return None

# --- Вспомогательные функции ---

async def _get_channel_title(bot: Bot, channel_id: int) -> str:
    """Безопасно получает название канала по ID с форматированием."""
    try:
        chat = await bot.get_chat(channel_id)
        title = chat.title or f"ID: {channel_id}" # Используем ИЛИ для краткости
        link = None
        if chat.username:
            link = f"https://t.me/{chat.username}"
        # Проверяем наличие invite_link безопаснее
        elif hasattr(chat, 'invite_link') and chat.invite_link:
             link = chat.invite_link # Ссылка-приглашение для приватных каналов

        # Возвращаем ссылку если есть, иначе жирный текст
        return hlink(title, link) if link else hbold(title)
    except TelegramAPIError as e:
        logger.warning(f"Не удалось получить информацию о канале {channel_id}: {e}")
        # Оставляем курсив для ошибок
        return hitalic(f"Канал ID {channel_id} (ошибка доступа)")
    except Exception as e:
        logger.error(f"Неожиданная ошибка при получении информации о канале {channel_id}: {e}", exc_info=True)
        return hitalic(f"Канал ID {channel_id} (ошибка)")

async def _format_configured_chats(bot: Bot, db_manager: DatabaseManager, user_id: int) -> Tuple[str, Optional[types.InlineKeyboardMarkup]]:
    """Формирует текст и клавиатуру со списком чатов и каналов.
    
    Returns:
        Кортеж (text, keyboard)
    """
    configured_chats = await db_manager.get_chats_configured_by_user(user_id)
    builder = InlineKeyboardBuilder() # Создаем билдер клавиатуры
    
    if not configured_chats:
        text = (
            f"Вы пока не настроили проверку подписок ни в одном чате.\n\n"
            f"➡️ Чтобы начать, добавьте меня (@{actual_bot_username}) в нужную группу и "
            f"используйте команду /code, чтобы получить код настройки."
        )
        return text, None # Возвращаем текст без клавиатуры

    text_parts = ["\n✨ <b>Ваши настроенные чаты и каналы:</b>\n"]
    for i, chat_info in enumerate(configured_chats):
        chat_id = chat_info.get('chat_id')
        # chat_title из БД как fallback
        chat_title_from_db = chat_info.get('chat_title') or f"Чат {chat_id}"
        
        # Формируем отображение чата
        actual_title = chat_title_from_db # Название для кнопки и как fallback
        chat_display_name = hbold(actual_title) # По умолчанию просто жирное название

        if chat_id: # Только если есть chat_id, пытаемся получить инфо
            try:
                # Пытаемся получить актуальную информацию о чате
                chat_api_info = await bot.get_chat(chat_id) # bot должен быть доступен здесь
                
                actual_title = chat_api_info.title or actual_title # Обновляем title, если он изменился
                chat_display_name = hbold(actual_title) # Обновляем для отображения по умолчанию

                if chat_api_info.username:
                    chat_display_name = hlink(actual_title, f"https://t.me/{chat_api_info.username}")
                # Если нужна ссылка-приглашение (раскомментировать и доработать, если необходимо):
                # elif hasattr(chat_api_info, 'invite_link') and chat_api_info.invite_link:
                #     chat_display_name = hlink(actual_title, chat_api_info.invite_link)
                # else: # Если не username и не invite_link, просто жирное название (уже установлено)
                #     pass
            except TelegramAPIError as e_api:
                logger.warning(f"Не удалось получить актуальную информацию для чата {chat_id} ({actual_title}) при формировании списка: {e_api}")
                # Оставляем chat_display_name как hbold(actual_title)
            except Exception as e_general: 
                logger.error(f"Неожиданная ошибка при получении информации для чата {chat_id} ({actual_title}): {e_general}", exc_info=True)
                # Оставляем chat_display_name как hbold(actual_title)

        text_parts.append(f"\n{i+1}. 💬 {chat_display_name}")

        channel_ids = chat_info.get('channels', [])
        if channel_ids:
            channel_tasks = [_get_channel_title(bot, ch_id) for ch_id in channel_ids]
            channel_titles = await asyncio.gather(*channel_tasks)
            channels_str = "\n".join([f"   • {title}" for title in channel_titles])
            text_parts.append(f"   └─ Каналы для проверки:\n{channels_str}")
        else:
            text_parts.append("   └─ Каналы для проверки: (нет)")
            
        # Добавляем кнопку управления для этого чата
        if chat_id: # Убедимся, что ID чата есть
             builder.button(
                 text=f"⚙️ Управлять {actual_title[:25]}{'...' if len(actual_title) > 25 else ''}", # Используем actual_title
                 callback_data=ManageSpecificChatCallback(chat_id=chat_id).pack()
             )

    text_parts.append(
        f"\n\n💡 Используйте команду /code для настройки нового чата."
    )
    
    builder.adjust(1) # Кнопки управления по одной в ряд
    keyboard = builder.as_markup() if configured_chats else None # Клавиатура только если есть чаты
    
    return "\n".join(text_parts), keyboard

# Функция для создания HTML-ссылки на чат
def get_chat_link_html(chat_id: int, chat_title: str) -> str:
    """Создает HTML-ссылку на чат."""
    # Убираем -100 из ID чата для корректной ссылки
    link_id = str(chat_id).replace('-100', '')
    return hlink(chat_title, f"https://t.me/c/{link_id}")

# --- Обработчики команд ---

@pm_router.message(Command("code"))
async def cmd_get_setup_code(message: types.Message):
    """Отправляет пользователю код для активации настройки группы."""
    user = message.from_user
    if not user:
        return # Маловероятно в ЛС, но проверка не помешает

    # Генерируем код. Можно использовать что-то более уникальное,
    # но для простоты user_id достаточен, если не ожидается конфликтов.
    setup_code = f"setup_{user.id}"
    logger.info(f"Пользователь {user.id} ({user.username}) запросил код настройки: {setup_code}")

    text = (
        f"🔑 Ваш уникальный код для настройки группы:\n\n"
        f"   {hcode(setup_code)}\n\n"
        f"Скопируйте этот код (нажмите на него) и отправьте его "
        f"<b>одним сообщением</b> в ту группу, где вы хотите настроить "
        f"проверку подписки на каналы."
    )
    # Используем parse_mode="HTML" из aiogram.enums.ParseMode для консистентности, если импортируем
    await message.answer(text, parse_mode="HTML")

@pm_router.message(CommandStart(deep_link=True, deep_link_encoded=False))
@pm_router.message(CommandStart())
async def cmd_start_in_pm(message: types.Message, command: CommandObject, db_manager: DatabaseManager, bot: Bot):
    """Обработчик команды /start в личных сообщениях."""
    user = message.from_user
    if not user:
        logger.warning("Получено сообщение /start без информации о пользователе.")
        return

    start_payload = command.args
    referrer_id = extract_referrer_id(start_payload)
    # Проверяем, что реферер не сам пользователь
    actual_referrer_id = referrer_id if referrer_id and user.id != referrer_id else None

    logger.info(f"Пользователь {user.id} ({user.username or 'no_username'}) запустил /start в ЛС. Payload: {start_payload}, Referrer ID: {actual_referrer_id}")

    # 1. Проверяем, есть ли пользователь в БД
    existing_user_data = await db_manager.get_user(user.id)
    is_new_user = existing_user_data is None

    # 2. Добавляем или обновляем пользователя
    # Метод add_user_if_not_exists сам обрабатывает оба случая (новый/существующий)
    await db_manager.add_user_if_not_exists(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language_code=user.language_code,
        is_premium=bool(user.is_premium), # Приводим к bool на всякий случай
        referrer_id=actual_referrer_id if is_new_user else None # Передаем реферера только если пользователь новый
    )

    # Если пользователь не новый, но реферера у него не было, а сейчас пришел с ним
    if not is_new_user and actual_referrer_id and existing_user_data and existing_user_data.get('referrer_id') is None:
         try:
             await db_manager.record_referral(referred_id=user.id, referrer_id=actual_referrer_id)
             logger.info(f"Записан реферер {actual_referrer_id} для существующего пользователя {user.id}")
         except Exception as e: # Ловим возможные ошибки БД
             logger.error(f"Ошибка при записи реферера {actual_referrer_id} для {user.id}: {e}")

    # 3. Формируем ответ
    user_mention = hlink(user.first_name or "Пользователь", f"tg://user?id={user.id}")

    if is_new_user:
        text_parts = [
            f"👋 Привет, {user_mention}!\n",
            f"Я — бот для проверки подписки на каналы в ваших группах.",
            f"С моей помощью вы можете гарантировать, что новые участники подписаны на важные каналы перед тем, как писать в чат.\n",
            f"📌 <b>Как начать:</b>",
            f"1️⃣ Добавьте меня (@{actual_bot_username}) в вашу группу.",
            f"2️⃣ Выдайте права администратора (желательно, для удаления сервисных сообщений).",
            f"3️⃣ Используйте команду /code прямо здесь, в личных сообщениях со мной, чтобы получить код настройки.",
            f"4️⃣ Отправьте полученный код в группу.\n",
            f"ℹ️ Доступные команды можно посмотреть здесь: /help"
        ]
        # Добавляем информацию о реферере, если он есть
        if actual_referrer_id:
             referrer_info = await db_manager.get_user(actual_referrer_id)
             ref_mention = f"пользователя {hitalic(str(actual_referrer_id))}" # Запасной вариант
             if referrer_info:
                 # Используем имя или username, если есть
                 ref_name = referrer_info.get('first_name') or referrer_info.get('username')
                 if ref_name:
                      # Создаем ссылку на профиль реферера
                     ref_mention = f"пользователя {hlink(ref_name, f'tg://user?id={actual_referrer_id}')}"
             text_parts.append(f"\n🤝 P.S. Вы присоединились по приглашению {ref_mention}!")
        text = "\n".join(text_parts)

    else:
        # Ответ для вернувшегося пользователя
        welcome_back = f"👋 С возвращением, {user_mention}!"
        # Получаем список настроенных чатов
        chats_list_text, keyboard = await _format_configured_chats(bot, db_manager, user.id)
        # Объединяем приветствие и список
        text = f"{welcome_back}\n{chats_list_text}"
        # Удаляем напоминание о командах
        # text += f"\n\nДоступные команды: /code, /chats, /help"

    # Отправляем ответное сообщение
    # Убираем клавиатуру, так как она теперь пустая
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)

@pm_router.message(Command("chats"))
async def cmd_mychats(message: types.Message, bot: Bot, db_manager: DatabaseManager):
    """Показывает список чатов и каналов, настроенных пользователем."""
    user = message.from_user
    if not user:
        return

    logger.info(f"Пользователь {user.id} ({user.username or 'no_username'}) запросил /chats")
    # Получаем текст и клавиатуру
    text, keyboard = await _format_configured_chats(bot, db_manager, user.id)
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True)

@pm_router.message(Command("help"))
async def show_help(message: types.Message):
    logger.info(f"Пользователь {message.from_user.id} вызвал команду /help")
    """Отправляет пользователю справочное сообщение."""
    
    user_id = message.from_user.id
    user_setup_code = f"setup_{user_id}"
    bot_username_val = actual_bot_username if actual_bot_username else "этого бота"

    text = f"""ℹ️ {hbold(f"Справка по командам бота (@{bot_username_val})")}


{hbold("В Личных Сообщениях (ЛС):")}
  • /start - Начать работу с ботом, приветствие.
  • /code - Получить уникальный код для настройки бота в группе.
  • /chats - Показать список настроенных вами чатов и управлять ими.
  • /help - Показать эту справку.


{hbold("В Группе (для Администраторов):")}
  • {hcode(user_setup_code)} - {hitalic("(Скопируйте по клику)")} Отправьте этот ваш персональный код в группу для начала настройки и привязки к боту.
  • {hcode("/channels")} - Управление списком каналов для проверки подписки (настройка откроется в ЛС).
  • {hcode("/captcha")} - Включить или выключить проверку капчей для новых участников (работает как переключатель).
  • {hcode("/subcheck")} - Включить или выключить проверку подписки на каналы (работает как переключатель).
  • {hcode("/rmchat")} - {hitalic("(Осторожно! Только для админов группы)")} Полностью удалить все данные этого чата из базы бота. Потребуется подтверждение.


{hbold("Как работает проверка:")}
  ✓ Если включена капча, новые участники должны нажать кнопку в сообщении, которое появится в группе.
  ✓ Если включена проверка подписки, сообщения пользователей (не админов), не подписанных на все обязательные каналы, будут удаляться. После нескольких удалений подряд пользователь получит временный мут.


❓ Возникли вопросы? Обращайтесь к {hcode("@daoqub")}
"""
    # Очистка текста от лишних отступов, сохраняя переносы строк, заданные в f-string
    lines = text.strip().splitlines()
    cleaned_lines = [line.lstrip() for line in lines]
    cleaned_text = "\n".join(cleaned_lines)

    try:
        await message.answer(cleaned_text, parse_mode="HTML", disable_web_page_preview=True)
        logger.info(f"Сообщение /help успешно отправлено пользователю {message.from_user.id}")
    except Exception as e:
        logger.error(f"Ошибка при отправке /help пользователю {message.from_user.id}: {e}", exc_info=True)

@pm_router.message(Command("test_html"))
async def cmd_test_html(message: types.Message):
    logger.info(f"Пользователь {message.from_user.id} вызвал команду /test_html")
    test_text = f"Это {hbold('жирный')} текст, это {hcode('код')}, а это {hitalic('курсив')}."
    try:
        await message.answer(test_text, parse_mode="HTML")
        logger.info(f"Сообщение /test_html успешно отправлено пользователю {message.from_user.id}")
    except Exception as e:
        logger.error(f"Ошибка при отправке /test_html пользователю {message.from_user.id}: {e}", exc_info=True)

# --- Обработчик состояния Activation.awaiting_code (в ЛС) ---

@pm_router.message(Activation.awaiting_code, F.chat.type == ChatType.PRIVATE)
async def process_activation_code(message: types.Message, state: FSMContext, db_manager: DatabaseManager):
    """Обрабатывает введенный код активации."""
    user = message.from_user
    if not user or not message.text:
        return # Игнорируем пустые сообщения или сообщения без пользователя

    activation_code = message.text.strip()
    user_id = user.id

    # Получаем данные из FSM контекста
    data = await state.get_data()
    target_chat_id = data.get('target_chat_id')
    target_chat_title = data.get('target_chat_title')

    if not target_chat_id or not target_chat_title:
        logger.error(f"Пользователь {user_id} в состоянии awaiting_code без target_chat_id/title в FSM.")
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте начать настройку заново.")
        await state.clear()
        return

    logger.info(f"Пользователь {user_id} ввел код активации: {activation_code} для чата {target_chat_id}")

    # Проверка кода активации
    if db_manager.is_valid_activation_code(activation_code):
        # Код верный!
        try:
            # Отмечаем чат как активированный в БД
            await db_manager.mark_chat_activated(target_chat_id, user_id)

            # Очищаем состояние FSM
            await state.clear()

            # Запускаем FSM управления каналами
            # Убедимся, что ChannelManagementService ожидает chat_id и user_id
            await ChannelManagementService.start_channel_management(user_id, target_chat_id, state) # Предполагаем, что сервис принимает эти args

            success_text = (\
                f"🎉 Чат \"{target_chat_title}\" успешно активирован!\\n\\n"\
                f"Теперь вы можете приступить к настройке каналов для проверки подписки.\\n"\
                f"Бот переведен в режим настройки каналов для этого чата."\
            )
            await message.answer(success_text)
            logger.info(f"Чат {target_chat_id} активирован и начато управление каналами для пользователя {user_id}")

            # Обновляем время последнего запроса активации
            await db_manager.update_last_activation_request_ts(target_chat_id)

        except Exception as e:
            logger.error(f"Ошибка при активации чата {target_chat_id} или запуске ChannelManagementService для пользователя {user_id}: {e}", exc_info=True)
            await message.answer("Произошла ошибка при активации. Пожалуйста, свяжитесь с администратором (@daoqub).")
            # Оставляем в состоянии или очищаем? Пока оставим в состоянии, чтобы пользователь мог попробовать еще раз или обратиться за помощью.
            # await state.clear()

    else:
        # Код неверный
        error_text = (\
            "❌ Неверный код активации.\\n\\n"\
            "Пожалуйста, проверьте код и попробуйте еще раз.\\n"\
            "Если проблема повторяется, свяжитесь с администратором (@daoqub) для получения помощи."\
        )
        await message.answer(error_text)
        logger.warning(f"Пользователь {user_id} ввел неверный код активации для чата {target_chat_id}: {activation_code}")
        # Оставляем в состоянии awaiting_code

# --- Конец обработчика состояния Activation.awaiting_code ---

# Убедитесь, что pm_router импортирован и используется в основном файле бота (__main__.py)
# dp.include_router(pm_router)
