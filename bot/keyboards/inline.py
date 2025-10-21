"""
Inline клавиатуры для FSM управления каналами и других нужд.
"""
from typing import List, Dict, Union, Optional, Any

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Импортируем коллбэки из нового файла
from bot.data.callback_data import (
    ConfirmSetupCallback, ChannelManageCallback, ChannelRemoveCallback # Убираем SubscriptionCheckCallback, если он больше нигде не используется в этом файле
)

# --- CallbackData Factories ---

class ChannelManageCallback(CallbackData, prefix="ch_manage"):
    """ CallbackData для кнопок главного меню управления каналами."""
    action: str # add_start, remove_start, finish, cancel

class ChannelRemoveCallback(CallbackData, prefix="ch_remove"):
    """ CallbackData для кнопок выбора канала для удаления."""
    action: str # select, back
    channel_id: int # ID канала для удаления (0 для кнопки back)


# --- Keyboard Generators ---

def get_channel_management_keyboard(channels: List[Dict[str, Union[int, str]]]) -> InlineKeyboardMarkup:
    """Создает инлайн-клавиатуру для управления списком каналов.

    Args:
        channels: Список словарей вида [{'id': int, 'title': str}, ...]

    Returns:
        Инлайн-клавиатура.
    """
    builder = InlineKeyboardBuilder()

    # Кнопка добавления
    builder.button(text="➕ Добавить канал", callback_data="mng:add_channel")

    # Кнопки удаления для каждого канала
    for channel in channels:
        channel_id = channel['id']
        channel_title = channel.get('title', f'ID {channel_id}')
        # Обрезаем слишком длинные названия для кнопки
        display_title = (channel_title[:20] + '...') if len(channel_title) > 23 else channel_title
        builder.button(
            text=f"➖ Удалить '{display_title}'",
            callback_data=f"mng:remove_start:{channel_id}"
        )

    # Кнопка завершения
    # Добавляем ее только если есть хотя бы один канал (или всегда?)
    # Решим пока добавлять всегда, т.к. можно добавить, а потом передумать и нажать Готово.
    builder.button(text="✅ Готово", callback_data="mng:finish")

    # Автоматически располагает кнопки (по умолчанию по 1 в ряд, но можно настроить)
    # Попробуем расположить кнопки удаления по 1 в ряд, а Добавить/Готово - вместе.
    builder.adjust(1)

    return builder.as_markup()

def get_channel_remove_keyboard(channels: List[Dict[str, Union[int, str]]]) -> InlineKeyboardMarkup:
    """Возвращает клавиатуру для выбора канала для удаления.

    Args:
        channels: Список словарей каналов [{'id': int, 'title': str}, ...]
                  из state.current_channels.
    """
    builder = InlineKeyboardBuilder()
    if not channels:
        # На всякий случай, хотя проверка должна быть раньше
        builder.button(text="Нет каналов для удаления", callback_data="ignore_no_channels")
    else:
        for channel_data in channels:
            channel_id = channel_data['id']
            # Обрезаем слишком длинные названия
            channel_title = channel_data.get('title', f"ID {channel_id}")
            button_text = f"❌ {channel_title[:30]}{'...' if len(channel_title) > 30 else ''}"
            builder.button(
                text=button_text,
                callback_data=ChannelRemoveCallback(action="select", channel_id=channel_id)
            )
    # Кнопка Назад
    builder.button(
        text="⬅️ Назад",
        callback_data=ChannelRemoveCallback(action="back", channel_id=0)
    )
    # Располагаем каналы по одному в строке, последняя кнопка - Назад
    builder.adjust(1)
    return builder.as_markup()

# Пример другой клавиатуры (если понадобится)
# def get_some_other_keyboard():
#     builder = InlineKeyboardBuilder()
#     builder.button(text="Кнопка 1", callback_data="data_1")
#     return builder.as_markup()

def get_captcha_keyboard(user_id: int):
    """Создает inline-кнопку для прохождения капчи."""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="✅ Я не робот",
        callback_data=f"captcha_pass_{user_id}" # Добавим префикс для ясности
    ))
    return builder.as_markup()


def get_start_keyboard():
    """Создает клавиатуру для команды /start в ЛС."""
    builder = InlineKeyboardBuilder()
    # Удаляем кнопку - управление через команды
    # builder.row(
    #     InlineKeyboardButton(
    #         text="➕ Добавить/Управлять каналами чата",
    #         callback_data="manage_channels_info" # Пока просто инфо
    #     )
    # )
    # Сюда можно добавить другие кнопки (Партнерка и т.д.)
    # builder.row(InlineKeyboardButton(text="Партнерская программа", callback_data="affiliate_info"))
    # Возвращаем пустую клавиатуру или можно вернуть None, если клавиатура не нужна
    return builder.as_markup() # Вернет пустую клавиатуру

def get_subscription_check_keyboard(user_id: int, channels: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """Создает клавиатуру для проверки подписки со ссылками на каналы."""
    builder = InlineKeyboardBuilder()
    # Добавляем ссылки на каналы
    for channel in channels:
        try:
            # Пытаемся получить username, если нет - используем invite_link или приватную ссылку
            link = f"https://t.me/{channel['username']}" if channel.get('username') else channel.get('invite_link')
            # Пытаемся сформировать приватную ссылку если channel_id это число (обычно отрицательное для супергрупп/каналов)
            # и нет других ссылок
            if not link and isinstance(channel.get('id'), int) and channel['id'] < 0:
                # abs() для ID и убираем префикс -100 для приватных ссылок на каналы
                # однако, для обычных ссылок (типа t.me/c/channel_id_without_100/message_id) нужен ID без -100
                # Для простой ссылки на канал (без message_id) может быть сложно сформировать универсальную приватную ссылку,
                # так как сам Telegram не всегда их легко отдает.
                # Попробуем просто ссылку на чат, если это возможно:
                # link = f"tg://resolve?domain=c&id={abs(channel['id']) % 10**12}" # Это не всегда работает
                # Для простоты, если нет username и invite_link, кнопку-ссылку не делаем, будет только в тексте
                pass # Не будем добавлять кнопку-ссылку если нет явного username или invite_link

            if link:
                builder.button(text=f"Канал: {channel.get('title', channel.get('id'))}", url=link)
        except Exception as e:
            print(f"Error creating button for channel {channel.get('id')}: {e}") # Логгируем ошибку

    # Добавляем кнопку "Я подписался"
    builder.button(
        text="✅ Я подписался", # Текст кнопки можно сделать универсальнее
        callback_data=f"subcheck:{user_id}" # Изменено для совместимости с существующим обработчиком
    )
    # Указываем, что кнопки должны располагаться вертикально
    builder.adjust(1)
    return builder.as_markup()

# --- Клавиатура подтверждения начала настройки чата --- #

def get_confirm_setup_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """Создает клавиатуру для подтверждения начала настройки в ЛС.

    Args:
        chat_id: ID чата, для которого запрашивается настройка.

    Returns:
        Инлайн-клавиатура с кнопками Да/Нет.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Да, настроить этот чат",
        callback_data=ConfirmSetupCallback(chat_id=chat_id).pack()
    )
    builder.button(
        text="❌ Отмена",
        callback_data="cancel_setup"
    )
    builder.adjust(1) # Кнопки друг под другом
    return builder.as_markup() 