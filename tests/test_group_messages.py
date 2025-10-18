import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
import time

from aiogram import Bot, types
from aiogram.fsm.context import FSMContext
from aiogram.types import ChatMemberUpdated, Chat, User
from aiogram.enums.chat_member_status import ChatMemberStatus

from bot.handlers.group_messages import on_user_join, handle_group_message # Импортируем функции, которые будем тестировать
from bot.db.database import DatabaseManager
from bot.services.captcha import CaptchaService
from bot.services.subscription import SubscriptionService
from bot.utils.helpers import get_user_mention_html

# Фикстура для мока Bot
@pytest.fixture
def mock_bot():
    bot = AsyncMock(spec=Bot)
    # Мокаем get_chat_member для возврата статуса админа бота, если нужно
    bot.get_chat_member.return_value = AsyncMock(status='administrator') 
    # Мокаем get_chat для получения информации о пользователе/чате
    # Добавляем title по умолчанию
    bot.get_chat.return_value = AsyncMock(spec=Chat, id=-100123, title="Test Chat Title by mock_bot", is_premium=False) 
    return bot

# Фикстура для мока DatabaseManager
@pytest.fixture
def mock_db_manager():
    db = AsyncMock(spec=DatabaseManager)
    # Мокаем get_user_status_in_chat для возврата словаря или None
    db.get_user_status_in_chat = AsyncMock(return_value={
        'user_id': 12345, # Примерные значения по умолчанию
        'chat_id': -100123,
        'sub_fail_count': 0,
        'is_captcha_passed': True,
        'ban_until': None
    })
    # Мокаем update_sub_fail_count
    db.update_sub_fail_count = AsyncMock(return_value=None)
    # Мокаем reset_sub_fail_count
    db.reset_sub_fail_count = AsyncMock(return_value=None)
    # Мокаем get_chat_settings для возврата словаря
    db.get_chat_settings = AsyncMock(return_value={
        'chat_id': -100123,
        'captcha_enabled': False,
        'subscription_check_enabled': True,
        'is_activated': True,
        'setup_complete': True
    })
    # Мокаем update_user_captcha_status (нужен для тестов колбэка капчи, если будем добавлять)
    db.update_user_captcha_status = AsyncMock(return_value=None)
    return db

# Фикстура для мока CaptchaService
@pytest.fixture
def mock_captcha_service():
    captcha = AsyncMock(spec=CaptchaService)
    # Мокаем start_captcha_for_user, чтобы он ничего не делал в тесте и можно было проверить его вызов
    captcha.start_captcha_for_user = AsyncMock(return_value=None) 
    # Оставим send_captcha для обратной совместимости, если где-то еще используется, но основной новый метод - start_captcha_for_user
    captcha.send_captcha = AsyncMock(return_value=None) 
    return captcha

# Фикстура для мока SubscriptionService
@pytest.fixture
def mock_subscription_service():
    sub = AsyncMock(spec=SubscriptionService)
    # Мокаем check_subscription, чтобы он возвращал статус подписки
    sub.check_subscription.return_value = (True, []) # По умолчанию подписан
    # Мокаем send_subscription_warning, чтобы можно было проверить его вызов
    sub.send_subscription_warning = AsyncMock(return_value=None)
    return sub

# Фикстура для мока FSMContext (если нужно)
@pytest.fixture
def mock_fsm_context():
    context = AsyncMock(spec=FSMContext)
    return context

# Фикстура для создания объекта ChatMemberUpdated при вступлении
@pytest.fixture
def join_event():
    # Создаем моки для чата и пользователя
    mock_chat = MagicMock(spec=Chat)
    mock_chat.id = -123456789 # ID группового чата
    mock_chat.title = "Test Group Chat"
    
    mock_user = MagicMock(spec=User)
    mock_user.id = 987654321 # ID пользователя
    mock_user.first_name = "TestUser"
    mock_user.last_name = ""
    mock_user.username = "testuser"
    mock_user.full_name = "Test User FullName" # Добавляем full_name
    mock_user.is_bot = False # По умолчанию пользователь не бот
    
    # Создаем объект ChatMemberUpdated
    event = MagicMock(spec=ChatMemberUpdated)
    event.chat = mock_chat
    event.new_chat_member = MagicMock(spec=types.ChatMember)
    event.new_chat_member.status = ChatMemberStatus.MEMBER # Пользователь вступил
    event.new_chat_member.user = mock_user
    
    # Мокируем old_chat_member, чтобы избежать AttributeError
    event.old_chat_member = MagicMock(spec=types.ChatMember)
    event.old_chat_member.status = ChatMemberStatus.LEFT # Например, пользователь покинул чат ранее
    
    # Мокаем message, так как некоторые функции могут его использовать
    # Хотя on_user_join принимает event, другие части логики могут использовать message
    # Пока не обязательно, но может понадобиться
    event.message = AsyncMock(spec=types.Message)
    event.message.chat = mock_chat # Привязываем чат к сообщению
    
    return event

# Тест для сценария: Пользователь вступил, капча отключена, подписан -> Ничего не происходит (идеальный сценарий)
@pytest.mark.asyncio
async def test_on_user_join_subscribed(mock_bot, mock_db_manager, mock_captcha_service, mock_subscription_service, join_event):
    # Настраиваем моки для этого теста
    # Предполагаем, что в настройках чата (которые нужно будет мокать) капча отключена
    # и проверка подписки включена, и пользователь подписан (по умолчанию в mock_subscription_service)
    
    # Мокаем get_chat_settings для имитации отключенной капчи и включенной проверки подписки
    # Возвращаем СЛОВАРЬ, а не AsyncMock
    mock_db_manager.get_chat_settings.return_value = {
        'chat_id': join_event.chat.id, # Добавим для полноты, хотя может и не использоваться напрямую в этой ветке
        'captcha_enabled': False,
        'subscription_check_enabled': True,
        'is_activated': True, # Важно для прохождения начальных проверок
        'setup_complete': True # Важно для прохождения начальных проверок
    }
    
    # Устанавливаем, что get_chat_member возвращает статус обычного пользователя
    mock_bot.get_chat_member.return_value = AsyncMock(status=ChatMemberStatus.MEMBER)
    
    # Запускаем обработчик
    await on_user_join(
        event=join_event,
        bot=mock_bot,
        db_manager=mock_db_manager,
        captcha_service=mock_captcha_service,
        subscription_service=mock_subscription_service
    )

    # Проверяем, что функции, связанные с мутом и капчей, НЕ вызывались
    mock_bot.restrict_chat_member.assert_not_called()
    mock_captcha_service.start_captcha_for_user.assert_not_called()
    # Проверяем, что проверка подписки вызывалась
    mock_subscription_service.check_subscription.assert_called_once_with(join_event.new_chat_member.user.id, join_event.chat.id)
    # Проверяем, что обновление предупреждений НЕ вызывалось (т.к. подписан)
    mock_db_manager.update_sub_fail_count.assert_not_called()

# Тест для сценария: Пользователь вступил, капча включена
@pytest.mark.asyncio
async def test_on_user_join_captcha_enabled(mock_bot, mock_db_manager, mock_captcha_service, mock_subscription_service, join_event):
    # Настраиваем моки для этого теста: капча включена, проверка подписки не важна для этого теста
    # Также чат должен быть активирован и настройка завершена
    mock_db_manager.get_chat_settings.return_value = { # Возвращаем словарь, как в database.py
        'chat_id': join_event.chat.id,
        'captcha_enabled': True,
        'subscription_check_enabled': False, # Не важно для этого теста
        'is_activated': True,
        'setup_complete': True 
    }

    # Запускаем обработчик
    await on_user_join(
        event=join_event,
        bot=mock_bot,
        db_manager=mock_db_manager,
        captcha_service=mock_captcha_service,
        subscription_service=mock_subscription_service 
    )

    # Проверяем, что start_captcha_for_user была вызвана с корректными аргументами
    mock_captcha_service.start_captcha_for_user.assert_called_once_with(
        bot=mock_bot,
        chat_id=join_event.chat.id,
        user_id=join_event.new_chat_member.user.id,
        user_name=join_event.new_chat_member.user.full_name,
        chat_title=join_event.chat.title
    )
    # Прямой вызов restrict_chat_member больше не проверяем здесь, т.к. это внутри start_captcha_for_user
    mock_bot.restrict_chat_member.assert_not_called() # Убедимся, что on_user_join сам его не дергает

    # Проверка подписки НЕ должна вызываться при включенной капче (по вашей логике)
    mock_subscription_service.check_subscription.assert_not_called()
    # Обновление предупреждений НЕ должно вызываться при включенной капче
    mock_db_manager.update_sub_fail_count.assert_not_called()

# Тест для сценария: Пользователь вступил, капча отключена, не подписан
@pytest.mark.asyncio
async def test_on_user_join_not_subscribed(mock_bot, mock_db_manager, mock_captcha_service, mock_subscription_service, join_event):
    # Настраиваем моки для этого теста: капча отключена, проверка подписки включена, пользователь НЕ подписан
    # Чат активирован и настройка завершена
    mock_db_manager.get_chat_settings.return_value = {
        'chat_id': join_event.chat.id,
        'captcha_enabled': False,
        'subscription_check_enabled': True,
        'is_activated': True,
        'setup_complete': True
    }
    # Мокаем check_subscription, чтобы он вернул, что пользователь не подписан
    mock_subscription_service.check_subscription.return_value = (False, [123, 456]) # Не подписан на каналы 123 и 456
    
    # Мокаем get_user_status_in_chat, чтобы он вернул начальный статус (0 неудач)
    # Важно: get_user_status_in_chat в database.py возвращает dict или None
    mock_db_manager.get_user_status_in_chat.return_value = {
        'user_id': join_event.new_chat_member.user.id,
        'chat_id': join_event.chat.id,
        'sub_fail_count': 0,
        'is_captcha_passed': False, # или True, в зависимости от логики, но для этого теста не критично
        'ban_until': None
    }
    # Мокаем update_sub_fail_count, чтобы можно было проверить его вызов
    mock_db_manager.update_sub_fail_count = AsyncMock(return_value=None)

    # Устанавливаем, что get_chat_member возвращает статус обычного пользователя
    mock_bot.get_chat_member.return_value = AsyncMock(status=ChatMemberStatus.MEMBER)

    # Запускаем обработчик
    await on_user_join(
        event=join_event,
        bot=mock_bot,
        db_manager=mock_db_manager,
        captcha_service=mock_captcha_service, 
        subscription_service=mock_subscription_service
    )

    # Проверяем, что капча НЕ отправлялась
    mock_captcha_service.start_captcha_for_user.assert_not_called()
    # Проверяем, что пользователь НЕ был ограничен сразу (не было мута)
    mock_bot.restrict_chat_member.assert_not_called()
    # Проверяем, что проверка подписки вызывалась
    mock_subscription_service.check_subscription.assert_called_once_with(join_event.new_chat_member.user.id, join_event.chat.id)
    # Удаляем проверку mock_db_manager.update_sub_fail_count, так как логика перенесена
    # Убедимся, что send_subscription_warning был вызван из on_user_join в этом сценарии
    mock_subscription_service.send_subscription_warning.assert_called_once_with(
        chat_id=join_event.chat.id,
        user_id=join_event.new_chat_member.user.id,
        user_mention=get_user_mention_html(join_event.new_chat_member.user),
        missing_channel_ids=[123, 456]
    )

# Тест для сценария: Пользователь вступил, премиум, капча отключена, не подписан
@pytest.mark.asyncio
async def test_on_user_join_premium_not_subscribed(mock_bot, mock_db_manager, mock_captcha_service, mock_subscription_service, join_event):
    # Настраиваем моки для этого теста: пользователь премиум, капча отключена, проверка подписки включена, пользователь НЕ подписан
    # Чат активирован и настройка завершена
    join_event.new_chat_member.user.is_premium = True # Делаем пользователя премиум для этого теста
    # mock_bot.get_chat.return_value было изменено на AsyncMock(spec=User...) - это правильно для user_info
    # Теперь убедимся, что get_chat_member для проверки статуса тоже настроен
    mock_bot.get_chat_member.return_value = AsyncMock(status=ChatMemberStatus.MEMBER) # Пользователь - обычный участник

    # Это уже было, но для ясности:
    mock_bot.get_chat.return_value = AsyncMock(spec=User, id=join_event.new_chat_member.user.id, full_name=join_event.new_chat_member.user.full_name, is_premium=True)

    mock_db_manager.get_chat_settings.return_value = {
        'chat_id': join_event.chat.id,
        'captcha_enabled': False,
        'subscription_check_enabled': True,
        'is_activated': True,
        'setup_complete': True
    }
    # Мокаем check_subscription, чтобы он вернул, что пользователь не подписан
    mock_subscription_service.check_subscription.return_value = (False, [789]) # Не подписан на канал 789
    # Мокаем get_user_status_in_chat
    mock_db_manager.get_user_status_in_chat.return_value = {
        'user_id': join_event.new_chat_member.user.id,
        'chat_id': join_event.chat.id,
        'sub_fail_count': 0,
        'is_captcha_passed': False,
        'ban_until': None
    }
    # Мокаем update_sub_fail_count
    mock_db_manager.update_sub_fail_count = AsyncMock(return_value=None)

    # Запускаем обработчик
    await on_user_join(
        event=join_event,
        bot=mock_bot,
        db_manager=mock_db_manager,
        captcha_service=mock_captcha_service,
        subscription_service=mock_subscription_service
    )

    # Проверяем, что капча НЕ отправлялась (т.к. отключена)
    mock_captcha_service.start_captcha_for_user.assert_not_called()
    # Проверяем, что пользователь НЕ был ограничен сразу (не было мута)
    mock_bot.restrict_chat_member.assert_not_called()
    # Проверяем, что проверка подписки вызывалась (даже для премиум)
    mock_subscription_service.check_subscription.assert_called_once_with(join_event.new_chat_member.user.id, join_event.chat.id)
    # Удаляем проверку mock_db_manager.update_sub_fail_count, так как логика перенесена
    # Убедимся, что send_subscription_warning был вызван из on_user_join в этом сценарии
    mock_subscription_service.send_subscription_warning.assert_called_once_with(
        chat_id=join_event.chat.id,
        user_id=join_event.new_chat_member.user.id,
        user_mention=get_user_mention_html(join_event.new_chat_member.user),
        missing_channel_ids=[789]
    )

# Фикстура для создания объекта types.Message
@pytest.fixture
def group_message(mock_db_manager, mock_bot):
    # Создаем моки для чата и пользователя
    mock_chat = MagicMock(spec=Chat)
    mock_chat.id = -123456789 # ID группового чата
    mock_chat.title = "Test Group Message Chat" # Добавляем title для чата

    mock_user = MagicMock(spec=User)
    mock_user.id = 987654321 # ID пользователя
    mock_user.first_name = "TestUser"
    mock_user.last_name = ""
    mock_user.username = "testuser"
    mock_user.full_name = "Test User FullName" # Добавляем full_name
    mock_user.is_bot = False # <--- ДОБАВЛЯЕМ ЯВНО ЗДЕСЬ

    # Создаем объект Message
    message = MagicMock(spec=types.Message)
    message.chat = mock_chat
    message.from_user = mock_user
    message.text = "Test message"
    message.sender_chat = None # По умолчанию сообщение не от имени канала
    message.message_id = 123456789 # Добавляем message_id
    # Добавляем атрибуты контента по умолчанию None
    message.photo = None
    message.video = None
    message.document = None
    message.sticker = None
    message.voice = None
    message.video_note = None # Также используется в handler

    # Мокаем delete для удобства
    message.delete = AsyncMock()

    # Новый мок для get_user_status_in_chat, возвращает словарь
    mock_db_manager.get_user_status_in_chat.return_value = {
        'user_id': message.from_user.id,
        'chat_id': message.chat.id,
        'sub_fail_count': 0,
        'is_captcha_passed': True, # Предполагаем, что капчу прошел, если она была
        'ban_until': None
    }
    # Мокаем update_sub_fail_count
    mock_db_manager.update_sub_fail_count = AsyncMock(return_value=None)
    # Мокаем is_admin, чтобы он возвращал False для этого теста
    # Это можно сделать через mock_bot.get_chat_member или напрямую, если is_admin мокается отдельно.
    # Для простоты пока предположим, что is_admin корректно вернет False (например, пользователь не в списке админов)
    # или mock_bot.get_chat_member вернет статус не админа.
    # Для явности, можно добавить:
    # async def mock_is_admin(*args, **kwargs): return False
    # mocker.patch('bot.handlers.group_messages.is_admin', new=mock_is_admin) # Если is_admin импортирован напрямую
    # Или настроить mock_bot.get_chat_member, чтобы is_admin вернул False
    mock_bot.get_chat_member.return_value = AsyncMock(status=ChatMemberStatus.MEMBER) # Обычный участник

    # Мокаем get_chat_settings, чтобы чат был активен и настроен
    mock_db_manager.get_chat_settings.return_value = {
        'chat_id': message.chat.id,
        'captcha_enabled': False,
        'subscription_check_enabled': True,
        'is_activated': True,
        'setup_complete': True
    }

    return message

@pytest.mark.asyncio
async def test_handle_group_message_not_subscribed_first_warning(
    mock_bot, mock_db_manager, mock_subscription_service, group_message, mock_fsm_context
):
    # Настраиваем моки для этого конкретного теста
    mock_db_manager.get_chat_settings.return_value = {
        'chat_id': group_message.chat.id, 'captcha_enabled': False, 
        'subscription_check_enabled': True, 'is_activated': True, 'setup_complete': True
    }
    mock_subscription_service.check_subscription.return_value = (False, [123]) # Не подписан
    
    mock_db_manager.get_user_status_in_chat.return_value = {
        'user_id': group_message.from_user.id, 'chat_id': group_message.chat.id,
        'sub_fail_count': 0, 'is_captcha_passed': True, 'ban_until': None
    }
    mock_bot.get_chat_member.return_value = AsyncMock(status=ChatMemberStatus.MEMBER) # Не админ

    # Запускаем обработчик
    await handle_group_message(
        message=group_message,
        bot=mock_bot,
        db_manager=mock_db_manager,
        state=mock_fsm_context,
        subscription_service=mock_subscription_service
    )

    # Удаляем проверку mock_captcha_service.start_captcha_for_user.assert_not_called()
    mock_bot.restrict_chat_member.assert_not_called()
    # Проверяем, что проверка подписки вызывалась
    mock_subscription_service.check_subscription.assert_called_once_with(group_message.from_user.id, group_message.chat.id)
    # Проверяем, что счетчик предупреждений был обновлен до 1
    mock_db_manager.update_sub_fail_count.assert_called_once_with(group_message.from_user.id, group_message.chat.id, increment_by=1)
    # Проверяем, что сообщение пользователя НЕ было удалено
    group_message.delete.assert_not_called()

@pytest.mark.asyncio
async def test_handle_group_message_not_subscribed_second_warning(
    mock_bot, mock_db_manager, mock_subscription_service, group_message, mock_fsm_context
):
    # Настраиваем моки
    mock_db_manager.get_chat_settings.return_value = {
        'chat_id': group_message.chat.id, 'captcha_enabled': False,
        'subscription_check_enabled': True, 'is_activated': True, 'setup_complete': True
    }
    mock_subscription_service.check_subscription.return_value = (False, [123]) # Не подписан
    mock_db_manager.get_user_status_in_chat.return_value = {
        'user_id': group_message.from_user.id, 'chat_id': group_message.chat.id,
        'sub_fail_count': 1, 'is_captcha_passed': True, 'ban_until': None # Уже есть 1 неудача
    }
    mock_bot.get_chat_member.return_value = AsyncMock(status=ChatMemberStatus.MEMBER) # Не админ

    # Запускаем обработчик
    await handle_group_message(
        message=group_message,
        bot=mock_bot,
        db_manager=mock_db_manager,
        state=mock_fsm_context,
        subscription_service=mock_subscription_service
    )

    # Удаляем проверку mock_captcha_service.start_captcha_for_user.assert_not_called()
    mock_bot.restrict_chat_member.assert_not_called()
    # Проверяем, что проверка подписки вызывалась
    mock_subscription_service.check_subscription.assert_called_once_with(group_message.from_user.id, group_message.chat.id)
    # Проверяем, что счетчик предупреждений был обновлен до 2
    mock_db_manager.update_sub_fail_count.assert_called_once_with(group_message.from_user.id, group_message.chat.id, increment_by=1)
     # Проверяем, что сообщение пользователя НЕ было удалено
    group_message.delete.assert_not_called()

@pytest.mark.asyncio
async def test_handle_group_message_not_subscribed_third_warning_mute(
    mock_bot, mock_db_manager, mock_subscription_service, group_message, mock_fsm_context
):
    # Настраиваем моки
    mock_db_manager.get_chat_settings.return_value = {
        'chat_id': group_message.chat.id, 'captcha_enabled': False,
        'subscription_check_enabled': True, 'is_activated': True, 'setup_complete': True
    }
    mock_subscription_service.check_subscription.return_value = (False, [123]) # Не подписан
    mock_db_manager.get_user_status_in_chat.return_value = {
        'user_id': group_message.from_user.id, 'chat_id': group_message.chat.id,
        'sub_fail_count': 2, 'is_captcha_passed': True, 'ban_until': None # Уже 2 неудачи
    }
    mock_bot.get_chat_member.return_value = AsyncMock(status=ChatMemberStatus.MEMBER) # Не админ


    # Запускаем обработчик
    await handle_group_message(
        message=group_message,
        bot=mock_bot,
        db_manager=mock_db_manager,
        state=mock_fsm_context,
        subscription_service=mock_subscription_service
    )

    # Удаляем проверку mock_captcha_service.start_captcha_for_user.assert_not_called()
    # Проверяем, что пользователь был ограничен (мут на 24 часа)
    mock_bot.restrict_chat_member.assert_called_once_with(
        chat_id=group_message.chat.id,
        user_id=group_message.from_user.id,
        permissions=types.ChatPermissions(can_send_messages=False),
        until_date=pytest.approx(time.time() + 24 * 3600, abs=5) # Мут на 24 часа (86400 сек), с допуском в 5 сек
    )
    # Проверяем, что проверка подписки вызывалась
    mock_subscription_service.check_subscription.assert_called_once_with(group_message.from_user.id, group_message.chat.id)
    # Проверяем, что счетчик предупреждений был сброшен до 0 после мута
    # Ожидаем два вызова: один для инкремента до 3, второй для сброса до 0
    assert mock_db_manager.update_sub_fail_count.call_count == 1 # Ожидаем только инкремент до мута
    mock_db_manager.update_sub_fail_count.assert_called_with(group_message.from_user.id, group_message.chat.id, increment_by=1)

    # Проверяем вызов reset_sub_fail_count после мута
    mock_db_manager.reset_sub_fail_count.assert_called_once_with(group_message.from_user.id, group_message.chat.id)

    # Проверяем, что send_subscription_warning был вызван (перед мутом)
    mock_subscription_service.send_subscription_warning.assert_called_once()
    args, kwargs = mock_subscription_service.send_subscription_warning.call_args
    assert kwargs.get('chat_id') == group_message.chat.id
    assert kwargs.get('user_id') == group_message.from_user.id
    assert kwargs.get('missing_channel_ids') == [123]

    # Проверяем, что сообщение пользователя БЫЛО удалено
    group_message.delete.assert_called_once()

@pytest.mark.asyncio
async def test_handle_group_message_subscribed(
    mock_bot, mock_db_manager, mock_subscription_service, group_message, mock_fsm_context
):
    # Настраиваем моки: капча отключена, проверка подписки включена, пользователь подписан
    mock_db_manager.get_chat_settings.return_value = {
        'chat_id': group_message.chat.id, 'captcha_enabled': False,
        'subscription_check_enabled': True, 'is_activated': True, 'setup_complete': True
    }
    mock_subscription_service.check_subscription.return_value = (True, []) # Подписан
    mock_db_manager.get_user_status_in_chat.return_value = {
        'user_id': group_message.from_user.id, 'chat_id': group_message.chat.id,
        'sub_fail_count': 1, 'is_captcha_passed': True, 'ban_until': None # Был 1 счетчик неудач
    }
    mock_bot.get_chat_member.return_value = AsyncMock(status=ChatMemberStatus.MEMBER) # Не админ

    # Запускаем обработчик
    await handle_group_message(
        message=group_message,
        bot=mock_bot,
        db_manager=mock_db_manager,
        state=mock_fsm_context,
        subscription_service=mock_subscription_service
    )

    # Удаляем проверку mock_captcha_service.start_captcha_for_user.assert_not_called()
    mock_bot.restrict_chat_member.assert_not_called()
    mock_db_manager.reset_sub_fail_count.assert_called_once_with(group_message.from_user.id, group_message.chat.id)
    group_message.delete.assert_not_called()
    # Проверяем, что проверка подписки вызывалась
    mock_subscription_service.check_subscription.assert_called_once_with(group_message.from_user.id, group_message.chat.id)
    # Проверяем, что send_subscription_warning НЕ был вызван
    mock_subscription_service.send_subscription_warning.assert_not_called()

@pytest.mark.asyncio
async def test_handle_group_message_user_is_admin(
    mock_bot, mock_db_manager, mock_subscription_service, group_message, mock_fsm_context, mocker
):
    """Тест: пользователь является админом. Никакие проверки не должны срабатывать."""

    # Настраиваем моки
    mock_db_manager.get_chat_settings.return_value = { # Не важно, но пусть будет
        'chat_id': group_message.chat.id, 'captcha_enabled': True, 
        'subscription_check_enabled': True, 'is_activated': True, 'setup_complete': True
    }
    # Мокаем is_admin напрямую, чтобы она возвращала True
    # Вместо мокирования mock_bot.get_chat_member, которое может не срабатывать из-за кеширования или других причин внутри is_admin
    mocker.patch('bot.handlers.group_messages.is_admin', return_value=True)

    await handle_group_message(
        message=group_message,
        bot=mock_bot,
        db_manager=mock_db_manager,
        state=mock_fsm_context,
        subscription_service=mock_subscription_service
    )

    # Проверяем, что никакие ключевые сервисы не вызывались
    mock_subscription_service.check_subscription.assert_not_called()
    mock_db_manager.update_sub_fail_count.assert_not_called()
    mock_db_manager.reset_sub_fail_count.assert_not_called()
    mock_subscription_service.send_subscription_warning.assert_not_called()
    mock_bot.restrict_chat_member.assert_not_called()
    group_message.delete.assert_not_called()

@pytest.mark.asyncio
@pytest.mark.parametrize("inactive_setting", ["is_activated", "setup_complete"])
async def test_handle_group_message_chat_not_ready(
    mock_bot, mock_db_manager, mock_subscription_service, group_message, mock_fsm_context, inactive_setting
):
    """Тест: чат не активирован или настройка не завершена. Обработчик должен выйти."""
    settings = {
        'chat_id': group_message.chat.id, 'captcha_enabled': True, 
        'subscription_check_enabled': True, 'is_activated': True, 'setup_complete': True
    }
    settings[inactive_setting] = False # Делаем чат неактивным или ненастроенным
    mock_db_manager.get_chat_settings.return_value = settings
    # mock_bot.get_chat_member.return_value = AsyncMock(status=ChatMemberStatus.MEMBER) # Не админ

    await handle_group_message(
        message=group_message,
        bot=mock_bot,
        db_manager=mock_db_manager,
        state=mock_fsm_context,
        subscription_service=mock_subscription_service
    )
    # Проверяем, что после get_chat_settings других вызовов не было (или были только начальные логи)
    mock_bot.get_chat_member.assert_not_called() # is_admin не должен был проверяться
    mock_subscription_service.check_subscription.assert_not_called()
    mock_db_manager.get_user_status_in_chat.assert_not_called()

@pytest.mark.asyncio
async def test_handle_group_message_user_banned(
    mock_bot, mock_db_manager, mock_subscription_service, group_message, mock_fsm_context
):
    """Тест: пользователь забанен. Сообщение должно удаляться."""
    mock_db_manager.get_chat_settings.return_value = {
        'chat_id': group_message.chat.id, 'captcha_enabled': False, 
        'subscription_check_enabled': True, 'is_activated': True, 'setup_complete': True
    }
    mock_bot.get_chat_member.return_value = AsyncMock(status=ChatMemberStatus.MEMBER) # Не админ
    mock_db_manager.get_user_status_in_chat.return_value = {
        'user_id': group_message.from_user.id, 'chat_id': group_message.chat.id,
        'sub_fail_count': 0, 'is_captcha_passed': True, 
        'ban_until': time.time() + 3600 # Забанен на час
    }

    await handle_group_message(
        message=group_message,
        bot=mock_bot,
        db_manager=mock_db_manager,
        state=mock_fsm_context,
        subscription_service=mock_subscription_service
    )

    group_message.delete.assert_called_once()
    mock_subscription_service.check_subscription.assert_not_called() # Другие проверки не нужны

@pytest.mark.asyncio
async def test_on_user_join_chat_not_activated(
    mock_bot, mock_db_manager, mock_captcha_service, mock_subscription_service, join_event
):
    """Тест: on_user_join, чат не активирован (is_activated=False)."""
    mock_db_manager.get_chat_settings.return_value = {
        'chat_id': join_event.chat.id, 'captcha_enabled': True, 
        'subscription_check_enabled': True, 'is_activated': False, 'setup_complete': True
    }

    await on_user_join(
        event=join_event,
        bot=mock_bot,
        db_manager=mock_db_manager,
        captcha_service=mock_captcha_service,
        subscription_service=mock_subscription_service
    )
    # Проверяем, что после get_chat_settings и проверки is_activated других вызовов не было
    mock_captcha_service.start_captcha_for_user.assert_not_called()
    mock_subscription_service.check_subscription.assert_not_called()

@pytest.mark.asyncio
async def test_on_user_join_setup_not_complete(
    mock_bot, mock_db_manager, mock_captcha_service, mock_subscription_service, join_event
):
    """Тест: on_user_join, настройка чата не завершена (setup_complete=False)."""
    # Этот тест актуален, если в on_user_join есть проверка setup_complete ПЕРЕД captcha_enabled
    # В текущей логике on_user_join (от 9 мая) проверка setup_complete отсутствует до логики капчи/подписки.
    # Если она появится, этот тест будет нужен. Пока он может быть избыточен или должен проверять другое.
    # Оставим его как пример, но отметим, что он зависит от актуальной логики on_user_join.
    mock_db_manager.get_chat_settings.return_value = {
        'chat_id': join_event.chat.id, 'captcha_enabled': True, 
        'subscription_check_enabled': True, 'is_activated': True, 'setup_complete': False
    }

    await on_user_join(
        event=join_event,
        bot=mock_bot,
        db_manager=mock_db_manager,
        captcha_service=mock_captcha_service,
        subscription_service=mock_subscription_service
    )
    # Ожидаемое поведение: если setup_complete проверяется до капчи, то вызовы ниже не должны произойти.
    # В текущей версии on_user_join (после is_activated) сразу идет блок капчи, потом подписки.
    # Если is_activated=True, то код дойдет до captcha_enabled.
    # Если captcha_enabled=True, то start_captcha_for_user вызовется.
    # Поэтому этот тест в текущем виде, скорее всего, не покажет выход из-за setup_complete=False, 
    # если captcha_enabled=True. Если captcha_enabled=False, то дойдет до subscription_check_enabled.
    # Для корректной проверки setup_complete в on_user_join, эта проверка должна быть раньше в коде on_user_join.
    # ПОКА предполагаем, что is_activated=True, setup_complete=False, captcha_enabled=True.
    # В этом случае start_captcha_for_user ДОЛЖЕН быть вызван, если setup_complete не проверяется до него.
    # Если setup_complete в on_user_join станет важной ранней проверкой, этот тест нужно будет адаптировать.
    # Пока что он не будет сильно отличаться от test_on_user_join_captcha_enabled, если setup_complete не мешает.
    # Для примера, если бы setup_complete=False приводило к выходу ДО капчи:
    # mock_captcha_service.start_captcha_for_user.assert_not_called()
    # mock_subscription_service.check_subscription.assert_not_called()
    # Но пока мы ожидаем, что капча сработает, если включена.
    if mock_db_manager.get_chat_settings.return_value.get('captcha_enabled', False):
        mock_captcha_service.start_captcha_for_user.assert_called_once()
    else:
        mock_captcha_service.start_captcha_for_user.assert_not_called()
        if mock_db_manager.get_chat_settings.return_value.get('subscription_check_enabled', False):
            mock_subscription_service.check_subscription.assert_called_once() # или not_called, если админ
        else:
            mock_subscription_service.check_subscription.assert_not_called()

@pytest.mark.asyncio
async def test_on_user_join_is_bot_user(
    mock_bot, mock_db_manager, mock_captcha_service, mock_subscription_service, join_event
):
    """Тест: on_user_join, присоединился бот."""
    join_event.new_chat_member.user.is_bot = True
    # Не важно, какие настройки у чата, для бота выход должен быть ранним
    mock_db_manager.get_chat_settings.return_value = {
        'chat_id': join_event.chat.id, 'captcha_enabled': True, 
        'subscription_check_enabled': True, 'is_activated': True, 'setup_complete': True
    }

    await on_user_join(
        event=join_event,
        bot=mock_bot,
        db_manager=mock_db_manager,
        captcha_service=mock_captcha_service,
        subscription_service=mock_subscription_service
    )

    mock_captcha_service.start_captcha_for_user.assert_not_called()
    mock_subscription_service.check_subscription.assert_not_called()
    mock_db_manager.get_chat_settings.assert_not_called() # Выход должен быть до получения настроек чата

@pytest.mark.asyncio
async def test_handle_group_message_from_bot_user(
    mock_bot, mock_db_manager, mock_subscription_service, group_message, mock_fsm_context
):
    """Тест: сообщение отправлено другим ботом. Должно быть проигнорировано."""
    group_message.from_user.is_bot = True

    # Настройки чата не должны влиять на выход из-за is_bot
    mock_db_manager.get_chat_settings.return_value = {
        'chat_id': group_message.chat.id, 'captcha_enabled': True, 
        'subscription_check_enabled': True, 'is_activated': True, 'setup_complete': True
    }

    await handle_group_message(
        message=group_message,
        bot=mock_bot,
        db_manager=mock_db_manager,
        state=mock_fsm_context,
        subscription_service=mock_subscription_service
    )

    # Проверяем, что никакие основные действия не были выполнены
    mock_db_manager.get_chat_settings.assert_not_called() # ИСПРАВЛЕНО: не должен вызываться, если вышли из-за is_bot
    mock_bot.get_chat_member.assert_not_called() # is_admin не должен был проверяться
    mock_subscription_service.check_subscription.assert_not_called()
    mock_db_manager.update_sub_fail_count.assert_not_called()
    mock_db_manager.reset_sub_fail_count.assert_not_called()
    mock_subscription_service.send_subscription_warning.assert_not_called()
    mock_bot.restrict_chat_member.assert_not_called()
    group_message.delete.assert_not_called()

@pytest.mark.asyncio
async def test_handle_group_message_from_sender_chat(
    mock_bot, mock_db_manager, mock_subscription_service, group_message, mock_fsm_context
):
    """Тест: сообщение отправлено от имени канала. Должно быть проигнорировано."""
    group_message.sender_chat = MagicMock(spec=Chat, id=-999888, title="Test Channel Sender")
    # from_user оставляем как есть, проверка sender_chat идет раньше

    # Настройки чата не должны влиять
    mock_db_manager.get_chat_settings.return_value = {
        'chat_id': group_message.chat.id, 'captcha_enabled': True, 
        'subscription_check_enabled': True, 'is_activated': True, 'setup_complete': True
    }
    
    await handle_group_message(
        message=group_message,
        bot=mock_bot,
        db_manager=mock_db_manager,
        state=mock_fsm_context,
        subscription_service=mock_subscription_service
    )

    # Проверяем, что никакие основные действия не были выполнены
    mock_db_manager.get_chat_settings.assert_not_called() # ИСПРАВЛЕНО: не должен вызываться, если вышли из-за sender_chat
    group_message.from_user.is_bot = False # Убедимся, что выход не из-за is_bot
    mock_bot.get_chat_member.assert_not_called() 
    mock_subscription_service.check_subscription.assert_not_called()
    mock_db_manager.update_sub_fail_count.assert_not_called()
    mock_db_manager.reset_sub_fail_count.assert_not_called()
    mock_subscription_service.send_subscription_warning.assert_not_called()
    mock_bot.restrict_chat_member.assert_not_called()
    group_message.delete.assert_not_called()

@pytest.mark.asyncio
async def test_handle_group_message_from_user_is_none(
    mock_bot, mock_db_manager, mock_subscription_service, group_message, mock_fsm_context
):
    """Тест: у сообщения нет отправителя (message.from_user is None). Должно быть проигнорировано."""
    group_message.from_user = None

    # Этот тест должен выйти раньше всех остальных проверок
    
    await handle_group_message(
        message=group_message,
        bot=mock_bot,
        db_manager=mock_db_manager,
        state=mock_fsm_context,
        subscription_service=mock_subscription_service
    )

    # Проверяем, что никакие действия не были выполнены
    mock_db_manager.get_chat_settings.assert_not_called()
    mock_bot.get_chat_member.assert_not_called()
    mock_subscription_service.check_subscription.assert_not_called()
    mock_db_manager.update_sub_fail_count.assert_not_called()
    mock_db_manager.reset_sub_fail_count.assert_not_called()
    mock_subscription_service.send_subscription_warning.assert_not_called()
    mock_bot.restrict_chat_member.assert_not_called()
    group_message.delete.assert_not_called()

# TODO: Добавить тесты для других сценариев (капча включена, не подписан, премиум и т.д.) 