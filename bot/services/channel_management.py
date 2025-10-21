"""
Сервис для управления каналами, связанными с чатом (добавление/удаление).
"""
import logging
from typing import List, Optional, Dict, Any

from aiogram import Bot, types
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext

from bot.db import DatabaseManager
from bot.keyboards.inline import get_channel_management_keyboard
from bot.utils.chat_info import get_chat_administrators_ids
from bot.texts import (
    YOU_ARE_NOT_ADMIN, CHANNEL_ADDED_SUCCESS, CHANNEL_REMOVED_SUCCESS, 
    ERROR_GETTING_CHANNEL_INFO, BOT_NEED_ADMIN_IN_CHANNEL, ERROR_ADDING_CHANNEL, 
    ERROR_REMOVING_CHANNEL, INSTRUCTION_AFTER_SETUP
)

logger = logging.getLogger(__name__)

class ChannelManagementService:
    """Обрабатывает логику добавления и удаления каналов для проверки подписки."""

    def __init__(self, bot: Bot, db: DatabaseManager):
        self.bot = bot
        self.db = db

    async def get_linked_channels(self, chat_id: int) -> List[int]:
        """Получает список ID каналов, привязанных к чату."""
        # Используем новый метод БД
        return await self.db.get_linked_channels_for_chat(chat_id)

    async def get_channel_details(self, channel_id: int) -> Optional[types.Chat]:
        """Получает информацию о канале по его ID."""
        try:
            channel = await self.bot.get_chat(channel_id)
            return channel
        except TelegramAPIError as e:
            logger.error(f"Ошибка при получении информации о канале {channel_id}: {e}")
            return None

    async def handle_channel_select(self, callback_query: types.CallbackQuery, state: FSMContext):
        """Обрабатывает нажатие кнопки с каналом в меню управления."""
        if not callback_query.message or not callback_query.data:
            return # Необходимые данные отсутствуют

        chat_id = callback_query.message.chat.id
        user_id = callback_query.from_user.id

        # Проверка, что пользователь все еще админ чата
        admin_ids = await get_chat_administrators_ids(self.bot, chat_id)
        if user_id not in admin_ids:
            await callback_query.answer(YOU_ARE_NOT_ADMIN, show_alert=True)
            await callback_query.message.delete() # Удаляем сообщение с настройками
            await state.clear()
            return

        try:
            action, channel_id_str = callback_query.data.split(":")[1:3]
            channel_id = int(channel_id_str)
        except (ValueError, IndexError):
            logger.warning(f"Некорректный формат callback_data: {callback_query.data}")
            await callback_query.answer("Ошибка формата данных.")
            return

        # Получаем текущие связанные каналы (снова, чтобы иметь актуальные данные)
        current_linked_channels = await self.get_linked_channels(chat_id)

        success = False
        alert_text = ""
        
        # Используем новые методы БД
        if channel_id in current_linked_channels:
            # Удаляем канал
            removed = await self.db.remove_linked_channel(group_chat_id=chat_id, channel_id=channel_id)
            if removed:
                success = True
                alert_text = CHANNEL_REMOVED_SUCCESS
                logger.info(f"Пользователь {user_id} удалил канал {channel_id} из чата {chat_id}")
            else:
                alert_text = ERROR_REMOVING_CHANNEL
                logger.warning(f"Не удалось удалить канал {channel_id} из чата {chat_id} (возможно, уже удален)")
        else:
            # Добавляем канал (сначала проверка)
            channel_info = await self.get_channel_details(channel_id)
            if not channel_info:
                alert_text = ERROR_GETTING_CHANNEL_INFO
            else:
                try:
                    # Проверяем, есть ли бот админом в канале
                    bot_member = await self.bot.get_chat_member(channel_id, self.bot.id)
                    if bot_member.status not in [types.ChatMemberStatus.ADMINISTRATOR, types.ChatMemberStatus.CREATOR]:
                        alert_text = BOT_NEED_ADMIN_IN_CHANNEL
                    else:
                        # Добавляем связь в БД
                        added = await self.db.add_linked_channel(
                            group_chat_id=chat_id, 
                            channel_id=channel_id, 
                            added_by_user_id=user_id # Записываем, кто добавил
                        )
                        if added:
                            success = True
                            alert_text = CHANNEL_ADDED_SUCCESS
                            logger.info(f"Пользователь {user_id} добавил канал {channel_id} в чат {chat_id}")
                        else:
                            alert_text = ERROR_ADDING_CHANNEL # Возможно, IntegrityError из-за гонки состояний
                            logger.warning(f"Не удалось добавить канал {channel_id} в чат {chat_id} (возможно, уже добавлен)")
                except TelegramAPIError as e:
                    logger.error(f"Ошибка API при проверке/добавлении канала {channel_id} для чата {chat_id}: {e}")
                    alert_text = f"{ERROR_ADDING_CHANNEL} (Ошибка API: {e.message})"

        # Отвечаем на callback
        await callback_query.answer(alert_text)

        # Если действие было успешным, обновляем клавиатуру
        if success:
            # Получаем обновленный список каналов, связанных с чатом
            new_linked_channels = await self.get_linked_channels(chat_id)
            # Получаем данные из состояния (forwarded_channels)
            state_data = await state.get_data()
            forwarded_channels: List[Dict[str, Any]] = state_data.get('forwarded_channels', [])
            
            # Создаем новую клавиатуру
            keyboard = await get_channel_management_keyboard(forwarded_channels, new_linked_channels)
            try:
                await callback_query.message.edit_reply_markup(reply_markup=keyboard)
            except TelegramAPIError as e:
                # Если сообщение не изменилось или другая ошибка
                logger.warning(f"Не удалось обновить клавиатуру управления каналами: {e}")

    async def finish_setup(self, callback_query: types.CallbackQuery, state: FSMContext):
        """Завершает процесс настройки каналов."""
        if not callback_query.message:
             return
             
        chat_id = callback_query.message.chat.id
        user_id = callback_query.from_user.id

        # Проверка, что пользователь все еще админ чата
        admin_ids = await get_chat_administrators_ids(self.bot, chat_id)
        if user_id not in admin_ids:
            await callback_query.answer(YOU_ARE_NOT_ADMIN, show_alert=True)
            await callback_query.message.delete() # Удаляем сообщение с настройками
            await state.clear()
            return

        # Получаем финальный список каналов и настройки чата
        linked_channels_ids = await self.get_linked_channels(chat_id)
        chat_settings = await self.db.get_chat_settings(chat_id)
        sub_check_enabled = chat_settings['subscription_check_enabled'] if chat_settings else False

        # Записываем, кто последний раз успешно настроил
        await self.db.add_or_update_chat(chat_id, callback_query.message.chat.title, configured_by=user_id)
        
        text = INSTRUCTION_AFTER_SETUP
        if linked_channels_ids and sub_check_enabled:
            text += "\n\n✅ Проверка подписки <b>включена</b> для следующих каналов:"
            channels_details = []
            for chan_id in linked_channels_ids:
                 detail = await self.get_channel_details(chan_id)
                 channels_details.append(f"- {detail.title if detail else f'ID: {chan_id}'}")
            text += "\n" + "\n".join(channels_details)
        elif linked_channels_ids and not sub_check_enabled:
             text += f"\n\n⚠️ Вы добавили каналы, но проверка подписки сейчас <b>выключена</b>. Используйте /toggle_sub чтобы включить её."
        else:
            text += "\n\nℹ️ Вы не добавили ни одного канала для проверки."
            if sub_check_enabled:
                text += " Проверка подписки будет неактивна, пока не добавлены каналы."

        # Удаляем инлайн-клавиатуру
        await callback_query.message.edit_text(text, reply_markup=None, parse_mode="HTML")
        # await callback_query.message.delete() # Или удаляем сообщение полностью
        await callback_query.answer("Настройка завершена.")
        await state.clear() 