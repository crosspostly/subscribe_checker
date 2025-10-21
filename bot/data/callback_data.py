"""
Определения CallbackData для инлайн-кнопок.
"""
from aiogram.filters.callback_data import CallbackData

class ConfirmSetupCallback(CallbackData, prefix="confirm_setup"):
    chat_id: int
    approve: bool

class ChannelManageCallback(CallbackData, prefix="ch_manage"):
    action: str # 'add', 'remove', 'save', 'cancel'
    # chat_id не нужен, так как он в state

class ChannelRemoveCallback(CallbackData, prefix="ch_remove"):
    channel_id: int
    # chat_id не нужен, так как он в state

class CaptchaCallback(CallbackData, prefix="captcha"):
    # chat_id не нужен, он в state или в инфе о кнопке
    action: str # 'pass' или 'fail'
    user_id: int # ID пользователя, который должен нажать

class SubscriptionCheckCallback(CallbackData, prefix="sub_check"):
    user_id: int
    # chat_id не нужен, подразумевается чат кнопки

# Новый CallbackData для кнопки управления конкретным чатом из /chats
class ManageSpecificChatCallback(CallbackData, prefix="mng_chat"):
    chat_id: int 

# CallbackData для кнопок в уведомлении владельцу о предоставлении доступа
class OwnerGrantAccessCallback(CallbackData, prefix="owner_grant"):
    action: str  # "grant" (открыть доступ), "cancel_grant" (отмена)
    user_id: int # ID пользователя, которому предоставляется доступ
    chat_id: int # ID чата, в котором предоставляется доступ 

# CallbackData для кнопок решения владельца по активации чата
class OwnerActivationChoiceCallback(CallbackData, prefix="owner_act_choice"):
    action: str         # "approve", "approve_grant", "reject"
    target_user_id: int # ID админа, запросившего настройку
    target_chat_id: int # ID чата, который настраивается 

# Новый CallbackData для кнопки, которую нажимает админ для старта настройки после одобрения владельцем
class DirectAdminSetupCallback(CallbackData, prefix="direct_admin_setup"):
    chat_id: int        # ID чата для настройки
    admin_id: int       # ID админа, который должен настраивать (для проверки) 