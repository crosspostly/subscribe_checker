import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

# Предполагаем, что путь к сервису user_cleanup_service корректен
# Возможно, потребуется настройка sys.path или другое решение для импортов в тестах
# Импортируем саму функцию задачи и батчевой очистки для тестирования
from bot.services.user_cleanup_service import scheduled_user_cleanup_task, cleanup_deleted_users_batch, get_candidate_user_ids_for_cleanup
# Импортируем класс DatabaseManager для мокирования его метода
from bot.db.database import DatabaseManager # Импортируем реальный класс для мокирования

from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramAPIError

# Удаляем класс MockDatabaseManager, так как будем мокировать метод напрямую
# class MockDatabaseManager:
#     ...

# Мок для Aiogram Bot (остается без изменений)
class MockBot(AsyncMock):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Настраиваем get_chat для имитации ответов
        self.get_chat.side_effect = self._mock_get_chat
        # Пользователи, для которых get_chat должен вернуть ошибку (удаленные/неактивные)
        self._deleted_or_inactive_ids = {3, 5, 101, 355, 588} # Примеры ID для имитации удаления

    async def _mock_get_chat(self, user_id):
        # print(f"DEBUG: MockBot.get_chat - Checking user {user_id}") # Отладочная печать
        if user_id in self._deleted_or_inactive_ids:
            # Имитация ошибки для удаленных/неактивных пользователей
            error_type = TelegramBadRequest if user_id % 2 == 0 else TelegramForbiddenError # Чередуем типы ошибок
            # print(f"DEBUG: MockBot.get_chat - Raising {error_type.__name__} for user {user_id}") # Отладочная печать
            raise error_type(method="getChat", message=f"User not found for user {user_id}")
        else:
            # Имитация успешного ответа для активных пользователей
            # print(f"DEBUG: MockBot.get_chat - Success for user {user_id}") # Отладочная печать
            mock_chat = MagicMock()
            mock_chat.id = user_id
            return mock_chat

# Добавляем фикстуру mocker
@pytest.mark.asyncio # Добавляем async marker
async def test_scheduled_user_cleanup_task(mocker):
    """
    Тест для основной задачи очистки пользователей.
    Проверяет, что задача корректно вызывает методы получения кандидатов,
    обработки партий и вызывает удаление для правильных пользователей.
    """
    mock_bot = MockBot()
    # Создаем реальный DatabaseManager, но будем мокировать его метод _execute
    db_manager_instance = DatabaseManager(':memory:') # Используем in-memory БД для инициализации
    
    # Мокируем метод _execute у экземпляра DatabaseManager
    mock_execute = mocker.patch.object(db_manager_instance, '_execute', new_callable=AsyncMock)

    # Определяем тестовые данные пользователей, которые будут использоваться в тесте
    all_users_data = [
        {'user_id': 1, 'last_seen_timestamp': 1600000000}, # Активный
        {'user_id': 2, 'last_seen_timestamp': 1600000010}, # Активный
        {'user_id': 3, 'last_seen_timestamp': 1600000020}, # Будет помечен как удаленный в MockBot
        {'user_id': 4, 'last_seen_timestamp': 1600000030}, # Активный
        {'user_id': 5, 'last_seen_timestamp': 1600000040}, # Будет помечен как удаленный в MockBot
    ]
    # Добавляем больше пользователей, чтобы покрыть ID из mock_bot._deleted_or_inactive_ids и создать объем
    # _deleted_or_inactive_ids в MockBot = {3, 5, 101, 355, 588}
    additional_user_ids = set(range(6, 600)) | {101, 355, 588} # Убедимся, что все нужные ID есть
    for i, user_id_val in enumerate(additional_user_ids):
         all_users_data.append({'user_id': user_id_val, 'last_seen_timestamp': 1600000000 + i * 10 + 50})


    # Готовим ожидаемый результат для SELECT запроса из get_candidate_user_ids_for_cleanup
    # Сервис сортирует по last_seen_timestamp ASC и ожидает список словарей [{'user_id': id}, ...]
    expected_select_rows = [{'user_id': user['user_id']} for user in sorted(all_users_data, key=lambda x: x['last_seen_timestamp'])]

    async def mock_execute_side_effect_impl(query, params=None, fetchall=False, commit=False):
        # Преобразуем query в строку и удаляем лишние пробелы/переносы для надежного сравнения
        query_str_for_comparison = ' '.join(str(query).split())
        print(f"DEBUG [Test]: Mock _execute called. Comparing with: '{query_str_for_comparison}'. Original query: '{str(query)[:100]}...', params: {params}, fetchall: {fetchall}, commit: {commit}")

        # Используем нормализованную строку для сравнения
        if "SELECT user_id FROM users ORDER BY last_seen_timestamp ASC" in query_str_for_comparison:
            if fetchall is True:
                print(f"DEBUG [Test]: Mock _execute (SELECT) returning {len(expected_select_rows)} rows.")
                return expected_select_rows
            else:
                print("DEBUG [Test]: Mock _execute (SELECT) called with fetchall=False, returning []. Should not happen for candidate selection.")
                return []
        elif "DELETE FROM users WHERE user_id = ?" in query_str_for_comparison:
            user_id_to_delete = params[0] if params and len(params) > 0 else "UNKNOWN"
            print(f"DEBUG [Test]: Mock _execute (DELETE) for user_id: {user_id_to_delete}. Commit: {commit}")
            return None
        else:
            print(f"DEBUG [Test]: Mock _execute called with unhandled query: '{query_str_for_comparison}'")
            return None

    mock_execute.side_effect = mock_execute_side_effect_impl

    # Запускаем тестируемую задачу
    await scheduled_user_cleanup_task(mock_bot, db_manager_instance)

    # Проверяем, что метод _execute был вызван для удаления каждого пользователя, который должен быть удален
    expected_deleted_ids = mock_bot._deleted_or_inactive_ids
    
    # Собираем user_id из всех вызовов _execute, которые были DELETE запросами
    actual_deleted_calls = set()
    # Проходим по всем вызовам мока _execute
    for call in mock_execute.call_args_list:
        query = call.args[0].strip()
        params = call.args[1] if len(call.args) > 1 else None
        # Проверяем, является ли вызов DELETE запросом и есть ли параметры (user_id)
        if query.startswith("DELETE FROM users WHERE user_id = ?") and params and len(params) > 0:
            actual_deleted_calls.add(params[0])

    # print(f"DEBUG: Actual delete calls recorded: {actual_deleted_calls}") # Отладочная печать
    # print(f"DEBUG: Expected deleted IDs: {expected_deleted_ids}") # Отладочная печать

    # Проверяем, что набор удаленных ID в точности совпадает с ожидаемым набором
    assert actual_deleted_calls == expected_deleted_ids, \
        f"Ожидалось удаление пользователей с ID {expected_deleted_ids}, но были вызваны удаления для: {actual_deleted_calls}"

# Можно добавить отдельные тесты для get_candidate_user_ids_for_cleanup и cleanup_deleted_users_batch, если потребуется более детальное тестирование

# @pytest.mark.asyncio
# async def test_get_candidate_user_ids_for_cleanup(mocker):
#     db_manager_instance = DatabaseManager(':memory:')
#     mock_execute = mocker.patch.object(db_manager_instance, '_execute', new_callable=AsyncMock)
#     
#     # Настраиваем мок _execute для возврата тестовых данных
#     test_users_data = [
#         {'user_id': 10, 'last_seen_timestamp': 1600001000},
#         {'user_id': 20, 'last_seen_timestamp': 1600002000},
#     ]
#     mock_execute.return_value = [{'user_id': user['user_id']} for user in test_users_data]
#     
#     candidates = await get_candidate_user_ids_for_cleanup(db_manager_instance)
#     
#     # Проверяем, что SELECT запрос был вызван
#     mock_execute.assert_called_once()
#     assert candidates == [10, 20]

# @pytest.mark.asyncio
# async def test_cleanup_deleted_users_batch(mocker):
#     mock_bot = MockBot()
#     db_manager_instance = DatabaseManager(':memory:')
#     mock_execute = mocker.patch.object(db_manager_instance, '_execute', new_callable=AsyncMock)
#     
#     user_ids_to_check = [1, 3, 4, 5, 6]
#     expected_deleted_in_batch = {user_id for user_id in user_ids_to_check if user_id in mock_bot._deleted_or_inactive_ids}
#     
#     await cleanup_deleted_users_batch(mock_bot, db_manager_instance, user_ids_to_check)
#     
#     # Проверяем, что _execute был вызван для удаления каждого пользователя, который должен быть удален в этой партии
#     actual_deleted_calls_batch = set()
#     for call in mock_execute.call_args_list:
#         query = call.args[0].strip()
#         params = call.args[1] if len(call.args) > 1 else None
#         if query.startswith("DELETE FROM users WHERE user_id = ?") and params and len(params) > 0:
#             actual_deleted_calls_batch.add(params[0])
#             
#     assert actual_deleted_calls_batch == expected_deleted_in_batch