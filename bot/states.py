from aiogram.fsm.state import State, StatesGroup

# class AddChannel(StatesGroup):
#     waiting_for_channel_id = State()

class ManageChannels(StatesGroup):
    managing_list = State()  # Основное состояние управления списком
    waiting_for_channel_select = State() # Ожидание выбора канала через кнопку request_chat после команды

    # Сценарий 2: Через добавление бота админом
    waiting_for_channel_select_admin = State() # Ожидание выбора канала через кнопку request_chat после добавления админом

    managing_list = State()              # Состояние управления списком (отображены кнопки Добавить/Удалить/Готово)
    waiting_for_channel_remove = State() # Ожидание выбора канала для удаления (отображена клавиатура с каналами)
    adding_channel = State()             # Состояние добавления нового канала
    
    # Состояния для передачи прав
    waiting_for_transfer_target = State() # Ожидание ввода ID пользователя для передачи прав
    waiting_for_transfer_confirm = State() # Ожидание подтверждения передачи прав

# Состояние для ожидания кода активации
class Activation(StatesGroup):
    awaiting_code = State() # Ожидание ввода кода активации

# Состояния для предоставления доступа владельцем
class OwnerGrantAccessStates(StatesGroup):
    awaiting_days_input = State()      # Владелец ожидает ввода количества дней
    awaiting_confirmation = State()  # (Опционально) Ожидание подтверждения перед сохранением

# Другие группы состояний можно добавлять сюда же
# class SomeOtherFeature(StatesGroup):
#     step1 = State()
#     step2 = State() 