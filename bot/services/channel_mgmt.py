"""
Сервис для управления каналами подписки через FSM.

Отвечает за логику сценариев:
- Добавление/удаление каналов после команды /-> отправки кода в чат.
"""

import logging
import time
import asyncio
from typing import Union, List, Dict, Optional, Tuple, Set, TYPE_CHECKING

from aiogram import Bot, F, types
from aiogram.enums import ChatType, ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (KeyboardButton, ReplyKeyboardMarkup, KeyboardButtonRequestChat,
                         ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup, 
                         ChatAdministratorRights, ReplyKeyboardRemove)
from aiogram.utils.markdown import hbold, hlink, hitalic, hcode
from aiogram.fsm.storage.base import StorageKey, BaseStorage

# Используем абсолютные импорты
from bot.db.database import DatabaseManager
from bot.utils.helpers import get_user_mention_html
from bot.states import ManageChannels
from bot.keyboards.inline import get_channel_management_keyboard, get_channel_remove_keyboard

logger = logging.getLogger(__name__)

# --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ (ПЕРЕНЕСЕНА ИЗ КОНЦА ФАЙЛА) ---
# Вспомогательная функция для склонения слова "канал"
def _get_channel_word_form(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "канал"
    elif 2 <= count % 10 <= 4 and (count % 100 < 10 or count % 100 >= 20):
        return "канала"
    else:
        return "каналов"
# --- КОНЕЦ ВСПОМОГАТЕЛЬНОЙ ФУНКЦИИ ---

# --- Вспомогательная функция для удаления сообщения с задержкой ---
# Эту функцию можно вынести в utils, если она будет использоваться в нескольких местах
async def delete_message_after_delay(message: types.Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await message.delete()
        logger.debug(f"Сервисное сообщение {message.message_id} в чате {message.chat.id} автоматически удалено.")
    except Exception as e:
        logger.warning(f"Не удалось автоматически удалить сервисное сообщение {message.message_id} в чате {message.chat.id}: {e}")

class ChannelManagementService:
    """Обрабатывает FSM логику для управления каналами подписки."""
    def __init__(self, bot: Bot, db_manager: DatabaseManager, storage: BaseStorage):
        self.bot = bot
        self.db = db_manager
        self.storage = storage # Сохраняем storage

    async def get_channel_title(self, channel_id: int) -> Optional[str]:
        try:
            chat = await self.bot.get_chat(channel_id)
            return chat.title if chat else None
        except Exception as e:
            logger.error(f"Error getting channel title for {channel_id}: {e}")
            return None

    async def check_bot_permissions(self, channel_id: int) -> bool:
        try:
            chat_member = await self.bot.get_chat_member(channel_id, self.bot.id)
            logger.info(f"Bot permissions in channel {channel_id}: {chat_member.status}")
            # Проверяем статус, а не просто наличие
            if not isinstance(chat_member, (types.ChatMemberAdministrator, types.ChatMemberOwner)):
                logger.warning(f"Bot is not an admin in channel {channel_id}, status: {chat_member.status}")
                return False
            # Дополнительно можно проверить конкретные права, если они важны (например, can_invite_users)
            # if isinstance(chat_member, types.ChatMemberAdministrator) and not chat_member.can_invite_users:
            #     logger.warning(f"Bot is admin in {channel_id} but lacks 'can_invite_users' permission.")
            #     # Возвращать False или True в зависимости от требований
            #     return True # Пока считаем, что достаточно быть админом
            return True
        except Exception as e:
            logger.error(f"Error checking bot permissions in channel {channel_id}: {e}")
            return False

    async def update_management_interface(self, user_id: int, state: FSMContext) -> None:
        try:
            state_data = await state.get_data()
            target_chat_id = state_data.get('target_chat_id')
            target_chat_title = state_data.get('target_chat_title', f"ID {target_chat_id}") # Получаем название чата
            current_channels = state_data.get('current_channels', [])
            # Сообщение, которое редактируем (если есть)
            message_id_to_edit = state_data.get('management_message_id')

            text_parts = [f"⚙️ Управление каналами для чата {hbold(target_chat_title)}\n"] # Используем название чата

            if not current_channels:
                text_parts.append("Список каналов для проверки пока пуст.")
            else:
                text_parts.append("Текущие каналы для проверки подписки:")
                channel_lines = []
                for i, channel in enumerate(current_channels):
                    ch_id = channel['id']
                    ch_title = channel.get('title', f'Канал ID {ch_id}') # Используем .get()
                    # Пытаемся сформировать ссылку, если ID похож на ID приватного канала
                    try:
                        if str(ch_id).startswith('-100'):
                           # Для приватных каналов ссылка формируется иначе и требует ID любого поста
                           # Простой link может не работать, используем title или ID
                           channel_link_text = ch_title
                        elif ch_title and not ch_title.startswith("Канал ID"):
                           # Для публичных каналов по title/username (если он есть)
                           # Это тоже не всегда username, может быть просто title
                           # Безопаснее просто показывать title
                           channel_link_text = ch_title
                        else: # Если title не получили или это просто ID
                           channel_link_text = f"Канал ID {ch_id}"
                        channel_lines.append(f"{i+1}. {channel_link_text}")
                    except Exception as e_link:
                        logger.warning(f"Ошибка формирования строки для канала {ch_id} ('{ch_title}'): {e_link}")
                        channel_lines.append(f"{i+1}. {ch_title or f'Канал ID {ch_id}'}")

                text_parts.extend(channel_lines)

            text = "\n".join(text_parts) + "\n\nВыберите действие:"

            # Используем новую клавиатуру управления
            keyboard = get_channel_management_keyboard(current_channels) # Передаем каналы для кнопок удаления

            send_method = self.bot.edit_message_text if message_id_to_edit else self.bot.send_message
            send_kwargs = {
                "chat_id": user_id,
                "text": text,
                "reply_markup": keyboard,
                "parse_mode": "HTML",
                "disable_web_page_preview": True # Отключаем превью ссылок
            }
            if message_id_to_edit:
                send_kwargs["message_id"] = message_id_to_edit
                logger.info(f"[FSM_MGMT] Редактируем интерфейс управления user={user_id}, msg_id={message_id_to_edit}")
            else:
                logger.info(f"[FSM_MGMT] Отправляем НОВЫЙ интерфейс управления user={user_id}")

            try:
                 sent_message = await send_method(**send_kwargs)
                 # Если отправили новое сообщение, сохраняем его ID для будущих редактирований
                 if not message_id_to_edit and sent_message:
                     await state.update_data(management_message_id=sent_message.message_id)
                     logger.debug(f"[FSM_MGMT] Сохранен ID сообщения интерфейса: {sent_message.message_id}")

            except TelegramBadRequest as e_bad_request:
                if "message is not modified" in str(e_bad_request).lower():
                    logger.warning(f"[FSM_MGMT] Сообщение {message_id_to_edit} не было изменено (содержимое идентично): {e_bad_request}")
                    # Ничего не делаем, сообщение уже актуально
                else:
                    # Другая ошибка BadRequest, передаем ее дальше
                    raise e_bad_request
            except TelegramAPIError as e:
                # Если не удалось отредактировать (например, сообщение слишком старое), пробуем отправить новое
                if "message to edit not found" in str(e).lower(): # Добавил .lower() для надежности
                    logger.warning(f"[FSM_MGMT] Не удалось отредактировать сообщение {message_id_to_edit} (не найдено), отправляем новое. Ошибка: {e}")
                    await state.update_data(management_message_id=None) # Сбрасываем ID
                    
                    # --- ИСПРАВЛЕНИЕ: Удаляем message_id перед отправкой нового сообщения ---
                    if "message_id" in send_kwargs:
                        del send_kwargs["message_id"]
                    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---
                        
                    sent_message = await self.bot.send_message(**send_kwargs)
                    if sent_message:
                        await state.update_data(management_message_id=sent_message.message_id)
                        logger.debug(f"[FSM_MGMT] Отправлен и сохранен ID нового сообщения интерфейса: {sent_message.message_id}")
                else:
                    # Другая ошибка API
                    logger.error(f"[FSM_MGMT] Непредвиденная ошибка API при обновлении интерфейса: {e}", exc_info=True)
                    raise e # Передаем ее дальше

        except Exception as e:
            logger.error(f"[FSM_MGMT] Не удалось обновить интерфейс управления user={user_id}: {e}", exc_info=True)
            try:
                # Попытка отправить простое сообщение об ошибке
                await self.bot.send_message(user_id, "Не удалось отобразить интерфейс управления.", reply_markup=types.ReplyKeyboardRemove())
            except Exception:
                pass # Если и это не удалось, просто игнорируем

    async def start_channel_management(self, target_chat_id: int, target_chat_title: str, admin_user_id: int):
        """
        Инициирует FSM для управления каналами из команды /managechannels.
        Отправляет начальное сообщение с кнопками в ЛС админу.
        """
        # Создаем ключ и контекст FSM для пользователя в ЛС
        user_fsm_key = StorageKey(bot_id=self.bot.id, chat_id=admin_user_id, user_id=admin_user_id)
        state = FSMContext(storage=self.storage, key=user_fsm_key)
        
        # Очищаем предыдущее состояние на всякий случай
        await state.clear()

        logger.info(f"[MGMT_START] Инициация управления каналами для чата {target_chat_id} ('{target_chat_title}') админом {admin_user_id}.")

        try:
            # Получаем текущие каналы из БД
            linked_channel_ids = await self.db.get_linked_channels_for_chat(target_chat_id)
            logger.debug(f"[MGMT_START] Найденные каналы в БД для чата {target_chat_id}: {linked_channel_ids}")

            # Получаем их названия
            channel_tasks = [self.get_channel_title(ch_id) for ch_id in linked_channel_ids]
            channel_titles = await asyncio.gather(*channel_tasks)

            # Сохраняем начальные данные в state
            initial_channels_data = [
                {'id': ch_id, 'title': title or f"Канал ID {ch_id}"} # Используем ID, если название недоступно
                for ch_id, title in zip(linked_channel_ids, channel_titles)
            ]
            logger.debug(f"[MGMT_START] Сформированные данные каналов для state: {initial_channels_data}")

            await state.update_data(
                user_id=admin_user_id, # ID админа, который управляет
                target_chat_id=target_chat_id,
                target_chat_title=target_chat_title,
                current_channels=initial_channels_data, # Список словарей каналов
                is_management_session=True # Флаг, что это сессия редактирования
            )

            # Устанавливаем состояние
            await state.set_state(ManageChannels.managing_list)
            logger.info(f"[MGMT_START] Установлено состояние ManageChannels.managing_list для user={admin_user_id}")

            # Отправляем интерфейс управления в ЛС
            await self.update_management_interface(admin_user_id, state)

        except TelegramForbiddenError:
             logger.warning(f"[MGMT_START] Не удалось начать управление для user={admin_user_id} (бот заблокирован?).")
             await state.clear() # Очищаем состояние
        except Exception as e:
            logger.error(f"[MGMT_START] Ошибка при старте управления каналами для user={admin_user_id}, chat={target_chat_id}: {e}", exc_info=True)
            await state.clear()
            try:
                await self.bot.send_message(admin_user_id, "Произошла ошибка при запуске управления каналами. Попробуйте позже.", reply_markup=types.ReplyKeyboardRemove())
            except TelegramAPIError: pass # Не удалось даже отправить ошибку

    async def _ask_channel_selection(self, user_id: int, target_chat_id: int, message_to_edit: Optional[types.Message] = None):
        """Отправляет (или редактирует) сообщение с кнопкой выбора канала в ЛС."""
        prefix = "add"
        request_id = hash(f"{prefix}_{user_id}_{target_chat_id}_{time.time()}") % (2**31 - 1)
        select_channel_button = KeyboardButton(
            text="➡️ Выберите канал для добавления ⬅️",
            request_chat=KeyboardButtonRequestChat(
                request_id=request_id,
                chat_is_channel=True,
                bot_is_member=True # Убеждаемся, что бот есть в канале
                # bot_administrator_rights=types.ChatAdministratorRights(can_invite_users=True) # Можно добавить, если нужно
            )
        )
        # Убираем ReplyKeyboardRemove(), используем инлайн-кнопки или ничего
        keyboard = ReplyKeyboardMarkup(keyboard=[[select_channel_button]], resize_keyboard=True, one_time_keyboard=True)
        text = "Пожалуйста, нажмите кнопку ниже и выберите канал, который хотите добавить для проверки подписки."

        # Сохраняем request_id в state для проверки при получении chat_shared
        state = FSMContext(storage=self.storage, key=StorageKey(bot_id=self.bot.id, chat_id=user_id, user_id=user_id))
        await state.update_data(last_request_id=request_id) # Сохраняем ID запроса

        try:
            # Редактирование ReplyKeyboardMarkup не поддерживается, всегда отправляем новое сообщение
            # if message_to_edit:
            #     # Редактируем текст существующего сообщения (интерфейса)
            #     await self.bot.edit_message_text(chat_id=user_id, message_id=message_to_edit.message_id, text=text, reply_markup=keyboard)
            # else:
            #     # Отправляем новое сообщение
            #     await self.bot.send_message(user_id, text, reply_markup=keyboard)
            # Всегда отправляем новое сообщение для ReplyKeyboard
            await self.bot.send_message(user_id, text, reply_markup=keyboard)

            logger.info(f"[FSM_MGMT] Отправлен запрос выбора КАНАЛА (req_id={request_id}) user={user_id} для chat={target_chat_id}")

        except TelegramForbiddenError:
            logger.warning(f"[FSM_MGMT] Не удалось отправить ЛС user={user_id} (бот заблокирован?). Настройка прервана.")
            await state.clear() # Очищаем состояние
            # Пытаемся вернуть старый интерфейс, если было сообщение для редактирования
            if message_to_edit:
                try: await self.update_management_interface(user_id, state)
                except: pass
            raise # Передаем исключение выше
        except TelegramAPIError as e:
            logger.error(f"[FSM_MGMT] Ошибка API при запросе выбора канала user={user_id}: {e}")
            # Пытаемся вернуть старый интерфейс
            if message_to_edit:
                 try: await self.update_management_interface(user_id, state)
                 except: pass
            raise

    async def handle_add_more_channels_button(self, query: types.CallbackQuery, state: FSMContext):
        """Обработка кнопки 'Добавить еще канал'."""
        try:
            state_data = await state.get_data()
            target_chat_id = state_data.get('target_chat_id')
            if not target_chat_id:
                logger.error(f"[FSM_MGMT] Нет target_chat_id в состоянии user={query.from_user.id}")
                await query.answer("Ошибка: не найден ID чата. Начните сначала.")
                return

            await state.set_state(ManageChannels.adding_channel)
            await self._ask_channel_selection(query.from_user.id, target_chat_id, query.message)
            await query.answer()
        except Exception as e:
            logger.error(f"[FSM_MGMT] Ошибка при обработке кнопки добавления канала user={query.from_user.id}: {e}", exc_info=True)
            await query.answer("Произошла ошибка. Попробуйте позже.")
            await state.clear()

    async def handle_channel_select(self, message: types.Message, state: FSMContext):
        """Обрабатывает выбор канала через CHAT_SHARED."""
        user = message.from_user
        shared_chat_info = message.chat_shared
        selected_channel_id = shared_chat_info.chat_id
        request_id = shared_chat_info.request_id

        logger.info(f"[FSM_MGMT] Получен выбор канала user={user.id}: channel_id={selected_channel_id}, request_id={request_id}")

        state_data = await state.get_data()
        target_chat_id = state_data.get('target_chat_id')
        if not target_chat_id:
            logger.error(f"[FSM_MGMT] КРИТ! Нет target_chat_id в состоянии user={user.id}, channel={selected_channel_id}. State: {state_data}")
            await message.reply("Внутренняя ошибка (нет ID чата). Начните сначала.", reply_markup=types.ReplyKeyboardRemove())
            await state.clear()
            return

        # Проверяем, не добавлен ли уже этот канал
        current_channels = state_data.get('current_channels', [])
        if any(ch['id'] == selected_channel_id for ch in current_channels):
            await message.reply("Этот канал уже добавлен в список.", reply_markup=types.ReplyKeyboardRemove())
            await state.set_state(ManageChannels.managing_list)
            await self.update_management_interface(user.id, state)
            return

        # Проверяем права бота в канале
        has_permissions = await self.check_bot_permissions(selected_channel_id)
        if not has_permissions:
            await message.reply("⚠️ У меня нет доступа к этому каналу.", reply_markup=types.ReplyKeyboardRemove())
            await state.set_state(ManageChannels.managing_list)
            await self.update_management_interface(user.id, state)
            return

        # Получаем название канала
        channel_title = await self.get_channel_title(selected_channel_id)

        # Добавляем канал в список
        current_channels.append({'id': selected_channel_id, 'title': channel_title})
        await state.update_data(current_channels=current_channels)

        # Обновляем интерфейс
        await state.set_state(ManageChannels.managing_list)
        await self.update_management_interface(user.id, state)

    async def handle_wrong_channel_select(self, message: types.Message, state: FSMContext):
        """Ловит любые другие сообщения в состоянии ожидания выбора канала."""
        user = message.from_user
        state_data = await state.get_data()
        target_chat_id = state_data.get('target_chat_id')
        logger.warning(f"[FSM_MGMT] Неверный ввод от user={user.id} в состоянии waiting_for_channel_select: {message.text[:50]}...")
        await message.reply("Пожалуйста, используйте <b>кнопку</b> ниже, чтобы выбрать канал.", parse_mode="HTML")
        # Повторно отправляем запрос
        if target_chat_id:
            try:
                await self._ask_channel_selection(user.id, target_chat_id)
            except Exception:
                await message.answer("Произошла ошибка при повторном запросе выбора канала.")
                await state.clear()
        else:
             await message.answer("Критическая ошибка: не найден ID чата. Начните сначала.")
             await state.clear()

    # --- Обработчики кнопок интерфейса управления --- #

    async def handle_remove_channel_start(self, query: types.CallbackQuery, state: FSMContext):
        """Обработка кнопки 'Удалить канал'. Показывает клавиатуру с каналами."""
        user_id = query.from_user.id
        state_data = await state.get_data()
        target_chat_id = state_data.get('target_chat_id')
        current_channels = state_data.get('current_channels', [])

        logger.info(f"[FSM_MGMT] user={user_id} нажал 'Удалить' для chat={target_chat_id}")

        if not target_chat_id:
            logger.error(f"[FSM_MGMT] Нет target_chat_id при нажатии 'Удалить' user={user_id}")
            await query.message.edit_text("Ошибка: не найден ID чата. Начните сначала.")
            await state.clear()
            return
        if not current_channels:
             logger.warning(f"[FSM_MGMT] Нет каналов для удаления user={user_id}, chat={target_chat_id}")
             await query.answer("Нет добавленных каналов для удаления.", show_alert=True)
             return # Остаемся в том же состоянии

        # Переходим в состояние ожидания выбора канала для удаления
        await state.set_state(ManageChannels.waiting_for_channel_remove)

        # Формируем клавиатуру для удаления
        remove_keyboard = get_channel_remove_keyboard(current_channels)
        try:
            await query.message.edit_text("Выберите канал, который хотите удалить из списка:", reply_markup=remove_keyboard)
            logger.info(f"[FSM_MGMT] Показана клавиатура удаления для user={user_id}, chat={target_chat_id}")
        except TelegramAPIError as e:
            logger.error(f"[FSM_MGMT] Ошибка при показе клавиатуры удаления user={user_id}: {e}")
            # Возвращаемся к основному интерфейсу
            await state.set_state(ManageChannels.managing_list)
            await self.update_management_interface(user.id, state)
            await query.answer("Ошибка отображения списка для удаления.", show_alert=True)
        await query.answer() # Закрываем часики у кнопки "Удалить"
    async def handle_remove_channel_confirm(self, query: types.CallbackQuery, callback_data: Dict, state: FSMContext):
        """Обработка нажатия на кнопку с каналом для удаления."""
        user_id = query.from_user.id
        channel_id_to_remove = int(callback_data['channel_id']) # CallbackData хранит ID как строку?
        state_data = await state.get_data()
        target_chat_id = state_data.get('target_chat_id')
        current_channels: List[Dict] = state_data.get('current_channels', [])
        logger.info(f"[FSM_MGMT] user={user_id} выбрал удалить канал {channel_id_to_remove} для chat={target_chat_id}")
        removed_channel_title = f"ID {channel_id_to_remove}"
        new_channels_list = []
        found = False
        for ch_data in current_channels:
            if ch_data['id'] == channel_id_to_remove:
                removed_channel_title = ch_data.get('title', removed_channel_title)
                found = True
            else:
                new_channels_list.append(ch_data)

        if found:
            await state.update_data(current_channels=new_channels_list)
            logger.info(f"[FSM_MGMT] Канал {channel_id_to_remove} ('{removed_channel_title}') временно удален user={user_id}, chat={target_chat_id}")
            await query.answer(f"Канал '{removed_channel_title}' удален из списка.")
        else:
            logger.warning(f"[FSM_MGMT] Канал {channel_id_to_remove} не найден в state для удаления user={user_id}, chat={target_chat_id}")
            await query.answer("Этот канал уже был удален.", show_alert=True)

        # Возвращаемся к основному интерфейсу управления
        await state.set_state(ManageChannels.managing_list)
        await self.update_management_interface(user.id, state)

    async def handle_cancel_channel_removal(self, query: types.CallbackQuery, state: FSMContext):
        """Обработка кнопки 'Отмена' на экране удаления канала."""
        user_id = query.from_user.id
        logger.info(f"[FSM_MGMT] user={user_id} отменил удаление канала.")
        await query.answer("Отмена удаления.")
        # Возвращаемся к основному интерфейсу управления
        await state.set_state(ManageChannels.managing_list)
        await self.update_management_interface(query.message.chat.id, state)
    async def handle_finish_channel_management(self, query: types.CallbackQuery, state: FSMContext):
        """Обрабатывает нажатие кнопки 'Завершить' в управлении каналами."""
        user_id = query.from_user.id
        try:
            state_data = await state.get_data()
            target_chat_id = state_data.get('target_chat_id')
            target_chat_title = state_data.get('target_chat_title', f"ID {target_chat_id}")
            # Получаем список каналов из состояния FSM (это список словарей)
            final_channels_in_state: List[Dict] = state_data.get('current_channels', []) 

            logger.info(f"[MGMT_FINISH] Пользователь {user_id} завершил управление каналами для чата {target_chat_id} ('{target_chat_title}'). Каналов в state: {len(final_channels_in_state)}.")
            logger.info(f"[MGMT_FINISH_DEBUG] Шаг 1: Проверка наличия каналов перед сохранением.")

            if not final_channels_in_state:
                logger.warning(f"[MGMT_FINISH] Попытка завершить без каналов user={user_id} chat={target_chat_id}.")
                await query.answer("⚠️ Вы не добавили ни одного канала! Настройка не завершена.", show_alert=True)
                logger.info(f"[MGMT_FINISH_DEBUG] Шаг 1.1: Завершение без каналов, query.answer вызван.")
                return # Важно: выходим, если нет каналов

            # --- НАЧАЛО БЛОКА СИНХРОНИЗАЦИИ С БД ---
            logger.info(f"[MGMT_FINISH_DEBUG] Шаг 1.5: Синхронизация каналов state с БД...")
            try:
                # Преобразуем каналы из state в множество ID
                state_channel_ids: Set[int] = {ch['id'] for ch in final_channels_in_state}
                
                # Получаем текущие каналы из БД
                db_channel_ids_list = await self.db.get_linked_channels_for_chat(target_chat_id)
                db_channel_ids: Set[int] = set(db_channel_ids_list)
            
                logger.debug(f"[MGMT_FINISH_SYNC] Каналы в state: {state_channel_ids}")
                logger.debug(f"[MGMT_FINISH_SYNC] Каналы в БД: {db_channel_ids}")
            
                # Определяем разницу
                channels_to_add = state_channel_ids - db_channel_ids
                channels_to_remove = db_channel_ids - state_channel_ids
            
                logger.info(f"[MGMT_FINISH_SYNC] Каналы для добавления в БД: {channels_to_add if channels_to_add else 'нет'}")
                logger.info(f"[MGMT_FINISH_SYNC] Каналы для удаления из БД: {channels_to_remove if channels_to_remove else 'нет'}")
                
                # Добавляем новые каналы
                for ch_id_add in channels_to_add:
                    try:
                        await self.db.add_linked_channel(target_chat_id, ch_id_add, user_id)
                        logger.info(f"[MGMT_FINISH_SYNC] Канал {ch_id_add} успешно добавлен в БД для чата {target_chat_id}.")
                    except Exception as e_add:
                        logger.error(f"[MGMT_FINISH_SYNC] Ошибка добавления канала {ch_id_add} для чата {target_chat_id}: {e_add}", exc_info=True)
                        # Решаем, что делать при ошибке: прервать или продолжить? Пока продолжаем.

                # Удаляем ненужные каналы
                for ch_id_remove in channels_to_remove:
                    try:
                        await self.db.remove_linked_channel(target_chat_id, ch_id_remove)
                        logger.info(f"[MGMT_FINISH_SYNC] Канал {ch_id_remove} успешно удален из БД для чата {target_chat_id}.")
                    except Exception as e_remove:
                        logger.error(f"[MGMT_FINISH_SYNC] Ошибка удаления канала {ch_id_remove} для чата {target_chat_id}: {e_remove}", exc_info=True)
                        # Решаем, что делать при ошибке: прервать или продолжить? Пока продолжаем.
                
                logger.info(f"[MGMT_FINISH_DEBUG] Шаг 1.6: Синхронизация каналов state с БД завершена.")

            except Exception as e_sync:
                logger.error(f"[MGMT_FINISH] Критическая ошибка при синхронизации каналов с БД для чата {target_chat_id}: {e_sync}", exc_info=True)
                await query.answer("❌ Ошибка сохранения списка каналов в БД. Попробуйте позже.", show_alert=True)
                # Не очищаем состояние, чтобы пользователь мог попробовать снова
                return
            # --- КОНЕЦ БЛОКА СИНХРОНИЗАЦИИ С БД ---

            logger.info(f"[MGMT_FINISH_DEBUG] Шаг 2: Вызов db.mark_setup_complete...")
            try:
                await self.db.mark_setup_complete(target_chat_id, user_id)
                logger.info(f"[MGMT_FINISH] Установлен флаг setup_complete=1 для чата {target_chat_id} (user={user_id}).")
                logger.info(f"[MGMT_FINISH_DEBUG] Шаг 2.1: mark_setup_complete успешно выполнен.")
            except Exception as e_db:
                logger.error(f"[MGMT_FINISH] Ошибка при установке setup_complete=1 для чата {target_chat_id}: {e_db}", exc_info=True)
                logger.info(f"[MGMT_FINISH_DEBUG] Шаг 2.2: Ошибка mark_setup_complete, вызов query.answer...")
                await query.answer("❌ Ошибка сохранения настроек в БД. Попробуйте позже.", show_alert=True)
                logger.info(f"[MGMT_FINISH_DEBUG] Шаг 2.3: query.answer для ошибки БД вызван.")
                return

            logger.info(f"[MGMT_FINISH_DEBUG] Шаг 3: Формирование текста сообщения...")
            success_text = (
                f"✅ Настройка каналов для чата {hbold(target_chat_title)} завершена!\n\n"
                f"Бот теперь будет проверять подписку на {len(final_channels_in_state)} " # Используем финальное количество из state
                f"{_get_channel_word_form(len(final_channels_in_state))}.\n\n"
                f"Вы можете вернуться к управлению каналами через команду /chats."
            )
            logger.info(f"[MGMT_FINISH_DEBUG] Шаг 3.1: Текст сообщения сформирован.")

            logger.info(f"[MGMT_FINISH_DEBUG] Шаг 4: Редактирование/отправка сообщения...")
            message_edited_or_sent = False
            try:
                await query.message.edit_text(success_text, parse_mode="HTML", reply_markup=None, disable_web_page_preview=True)
                logger.info(f"[MGMT_FINISH_DEBUG] Шаг 4.1: Сообщение {query.message.message_id} успешно отредактировано.")
                message_edited_or_sent = True
            except TelegramAPIError as e:
                logger.warning(f"[MGMT_FINISH] Не удалось отредактировать сообщение {query.message.message_id} для user={user_id}: {e}. Отправляем новое.")
                try:
                    await self.bot.send_message(user_id, success_text, parse_mode="HTML", disable_web_page_preview=True)
                    logger.info(f"[MGMT_FINISH_DEBUG] Шаг 4.2: Новое сообщение успешно отправлено.")
                    message_edited_or_sent = True
                except Exception as e_send:
                    logger.error(f"[MGMT_FINISH] Не удалось даже отправить новое сообщение user={user_id}: {e_send}")
                    logger.info(f"[MGMT_FINISH_DEBUG] Шаг 4.3: Ошибка отправки нового сообщения.")

            logger.info(f"[MGMT_FINISH_DEBUG] Шаг 5: Вызов query.answer...")
            try:
                await query.answer("Настройка завершена!")
                logger.info(f"[MGMT_FINISH_DEBUG] Шаг 5.1: query.answer успешно вызван.")
            except Exception as e_ans:
                 logger.error(f"[MGMT_FINISH] Ошибка при вызове query.answer(): {e_ans}", exc_info=True)
                 logger.info(f"[MGMT_FINISH_DEBUG] Шаг 5.2: Ошибка вызова query.answer.")

            logger.info(f"[MGMT_FINISH_DEBUG] Шаг 6: Очистка состояния FSM...")
            await state.clear()
            logger.info(f"[MGMT_FINISH] Состояние FSM очищено для user={user_id}.")
            logger.info(f"[MGMT_FINISH_DEBUG] Шаг 6.1: Состояние FSM очищено.")

        except Exception as e:
            logger.error(f"[MGMT_FINISH] Общая ошибка при завершении управления каналами user={user_id}: {e}", exc_info=True)
            logger.info(f"[MGMT_FINISH_DEBUG] Общая ошибка в блоке try, вызов query.answer...")
            try:
                await query.answer("❌ Произошла непредвиденная ошибка при завершении.", show_alert=True)
                logger.info(f"[MGMT_FINISH_DEBUG] query.answer для общей ошибки вызван.")
            except TelegramAPIError: 
                logger.info(f"[MGMT_FINISH_DEBUG] Ошибка ответа на query.answer для общей ошибки.")
                pass 
            logger.info(f"[MGMT_FINISH_DEBUG] Очистка состояния FSM после общей ошибки...")
            await state.clear() 
            logger.info(f"[MGMT_FINISH_DEBUG] Состояние FSM очищено после общей ошибки.")

    async def toggle_subscription_check(self, admin_user_id: int, target_chat_id: int, chat_title_for_msg: str, state: FSMContext):
        """Переключает настройку обязательной подписки для чата."""
        state_data = await state.get_data()
        current_status = await self.db.get_chat_setting(target_chat_id, 'subscription_check_enabled')
        new_status = not current_status
        await self.db.toggle_setting(target_chat_id, 'subscription_check_enabled', new_status, admin_user_id)
        logger.info(f"[FSM_MGMT] Переключена проверка подписки для чата {target_chat_id} на {' ВКЛ' if new_status else 'ВЫКЛ'} админом {admin_user_id}")

        if new_status:
            feedback_text = f"✅ Проверка подписки на каналы для чата {hbold(chat_title_for_msg)} ({hcode(target_chat_id)}) теперь {hbold('включена')}."
        else:
            feedback_text = f"✅ Проверка подписки на каналы для чата {hbold(chat_title_for_msg)} ({hcode(target_chat_id)}) теперь {hbold('выключена')}."
        
        try:
            sent_message = await self.bot.send_message(admin_user_id, feedback_text, parse_mode="HTML")
            # Добавляем автоудаление для этого сообщения через 5 секунд
            asyncio.create_task(delete_message_after_delay(sent_message, 5))
            logger.debug(f"Сообщение о статусе подписки user={admin_user_id} будет удалено через 5 сек.")
        except Exception as e_send:
            logger.error(f"Не удалось отправить/запланировать удаление сообщения о статусе подписки user={admin_user_id}: {e_send}")

        await self.update_management_interface(admin_user_id, state) # Передаем только user_id и state

    async def toggle_captcha(self, admin_user_id: int, target_chat_id: int, chat_title_for_msg: str, state: FSMContext):
        """Переключает настройку капчи для чата."""
        state_data = await state.get_data()
        current_status = await self.db.get_chat_setting(target_chat_id, 'captcha_enabled')
        new_status = not current_status
        await self.db.toggle_setting(target_chat_id, 'captcha_enabled', new_status, admin_user_id)
        logger.info(f"[FSM_MGMT] Переключена капча для чата {target_chat_id} на {' ВКЛ' if new_status else 'ВЫКЛ'} админом {admin_user_id}")

        if new_status:
            feedback_text = f"✅ Капча для новых пользователей в чате {hbold(chat_title_for_msg)} ({hcode(target_chat_id)}) теперь {hbold('включена')}."
        else:
            feedback_text = f"✅ Капча для новых пользователей в чате {hbold(chat_title_for_msg)} ({hcode(target_chat_id)}) теперь {hbold('выключена')}."

        try:
            sent_message = await self.bot.send_message(admin_user_id, feedback_text, parse_mode="HTML")
            # Добавляем автоудаление для этого сообщения через 5 секунд
            asyncio.create_task(delete_message_after_delay(sent_message, 5))
            logger.debug(f"Сообщение о статусе капчи user={admin_user_id} будет удалено через 5 сек.")
        except Exception as e_send:
            logger.error(f"Не удалось отправить/запланировать удаление сообщения о статусе капчи user={admin_user_id}: {e_send}")

        await self.update_management_interface(admin_user_id, state) # Передаем только user_id и state