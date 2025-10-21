import asyncio
import os # Добавим для переменных окружения, если решим использовать
import logging # <--- ДОБАВЛЕНО

# <--- ДОБАВЛЕНО: Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
# Для более детальной отладки Telethon можно раскомментировать следующую строку:
logging.getLogger('telethon').setLevel(logging.DEBUG) # <--- РАСКОММЕНТИРОВАНО

from telethon import TelegramClient
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.types import ChatBannedRights, ChannelParticipantsAdmins
from telethon.errors.rpcerrorlist import UserNotParticipantError, ChatAdminRequiredError, UserAdminInvalidError, UserKickedError, ChannelPrivateError, ChatWriteForbiddenError

# --- НАСТРОЙКИ ---
# Попробуем прочитать из переменных окружения, если они есть, иначе используем значения из кода
API_ID = os.getenv('TELETHON_API_ID', 18234613) # Ваш API ID
API_HASH = os.getenv('TELETHON_API_HASH', 'ba5a77b44fb64379a59a37b9049f21f4') # Ваш API Hash
CHAT_IDENTIFIER = os.getenv('TELETHON_CHAT_ID', -1001568712129) # Username или ID чата

# Преобразуем API_ID и CHAT_IDENTIFIER в int, если они заданы
try:
    API_ID = int(API_ID)
except ValueError:
    print("Ошибка: API_ID должен быть числом. Проверьте значение или переменную окружения TELETHON_API_ID.")
    exit()

try:
    # CHAT_IDENTIFIER может быть строкой (username) или числом (ID)
    CHAT_IDENTIFIER = int(CHAT_IDENTIFIER)
except ValueError:
    pass # Оставляем как строку, если это username

SESSION_NAME = 'my_unmute_session_v2' # Изменим имя сессии на всякий случай

# Более гранулированные задержки
DELAY_AFTER_KICK = 1.2  # Секунд после кика "собачки"
DELAY_AFTER_UNMUTE = 0.8 # Секунд после успешного анмута
DELAY_IF_NO_ACTION = 0.2 # Секунд, если для пользователя не было действий (чтобы не частить с iter_participants)
# --- КОНЕЦ НАСТРОЕК ---

async def main():
    print("Запуск скрипта для анмута и очистки чата (оптимизированная версия)...")
    print(f"Используется API_ID: {API_ID}")
    print(f"Используется CHAT_IDENTIFIER: {CHAT_IDENTIFIER}")
    print(f"Имя сессии: {SESSION_NAME}")

    async with TelegramClient(SESSION_NAME, API_ID, API_HASH) as client:
        if not await client.is_user_authorized():
            print("Клиент не авторизован. Пожалуйста, запустите скрипт и следуйте инструкциям для входа (номер телефона, код).")
            return

        try:
            chat = await client.get_entity(CHAT_IDENTIFIER)
            print(f"Чат найден: '{getattr(chat, 'title', chat.id)}' (ID: {chat.id})")
        except (ValueError, TypeError) as e: # TypeError если CHAT_IDENTIFIER некорректного типа для get_entity
            print(f"Ошибка: Не удалось найти чат '{CHAT_IDENTIFIER}'. Проверьте правильность username/ID. Детали: {e}")
            return
        except ChannelPrivateError:
            print(f"Ошибка: Чат '{CHAT_IDENTIFIER}' приватный и бот/пользователь не имеет к нему доступа.")
            return
        except Exception as e:
            print(f"Произошла непредвиденная ошибка при получении информации о чате: {e}")
            return

        processed_count = 0
        unmuted_count = 0
        kicked_deleted_count = 0
        skipped_not_muted_count = 0
        
        # Получим список администраторов один раз, чтобы не пытаться изменять их права (хотя анмут админу не повредит)
        admins = []
        try:
            async for admin_user in client.iter_participants(chat, filter=ChannelParticipantsAdmins):
                admins.append(admin_user.id)
            print(f"Найдено {len(admins)} администраторов в чате. Их права изменяться не будут (пропуск).")
        except ChatAdminRequiredError:
            print("Предупреждение: не удалось получить список администраторов. Убедитесь, что у вас есть права админа.")
        except Exception as e:
            print(f"Предупреждение: ошибка при получении списка администраторов: {e}")


        print(f"\nНачинаем перебор участников в чате '{getattr(chat, 'title', chat.id)}'...")
        try:
            async for user in client.iter_participants(chat, aggressive=False): # aggressive=False может помочь с некоторыми лимитами
                processed_count += 1
                action_taken_this_user = False
                
                # Пропускаем администраторов
                if user.id in admins:
                    # print(f"\n--- Обработка пользователя {processed_count}: ID {user.id} (АДМИН, ПРОПУСК) ---")
                    await asyncio.sleep(0.05) # Совсем небольшая пауза для админов
                    continue

                print(f"\n--- Обработка пользователя {processed_count}: ID {user.id}, Имя: {user.first_name or ''} {user.last_name or ''} (@{user.username or 'N/A'}) ---")

                # 1. Проверка и удаление "собачек"
                if user.deleted:
                    print(f"  [УДАЛЕНИЕ] Пользователь {user.id} является удаленным аккаунтом ('собачка'). Попытка кика...")
                    kick_rights = ChatBannedRights(until_date=None, view_messages=True)
                    try:
                        await client(EditBannedRequest(chat, user.id, kick_rights))
                        print(f"    [УДАЛЕНИЕ-УСПЕХ] Удаленный аккаунт {user.id} успешно кикнут.")
                        kicked_deleted_count += 1
                        action_taken_this_user = True
                        await asyncio.sleep(DELAY_AFTER_KICK)
                    except (UserNotParticipantError, UserKickedError):
                        print(f"    [УДАЛЕНИЕ-ИНФО] Удаленный аккаунт {user.id} уже не участник или кикнут.")
                    except (ChatAdminRequiredError, UserAdminInvalidError):
                        print(f"    [УДАЛЕНИЕ-ОШИБКА] Недостаточно прав для кика {user.id}.")
                    except ChatWriteForbiddenError:
                        print(f"    [УДАЛЕНИЕ-ОШИБКА] Нет прав на запись в чате для кика {user.id} (возможно, вы сами замучены или чат только для чтения).")
                    except Exception as e:
                        print(f"    [УДАЛЕНИЕ-ОШИБКА] Не удалось кикнуть {user.id}: {type(e).__name__} - {e}")
                    continue # Переходим к следующему пользователю после попытки кика собачки

                # 2. Проверка и анмут (только если не "собачка")
                participant_data = getattr(user, 'participant', None)
                is_muted = False
                if participant_data and hasattr(participant_data, 'banned_rights') and participant_data.banned_rights:
                    if participant_data.banned_rights.send_messages:
                        is_muted = True
                        print(f"  [ПРОВЕРКА-МУТА] Пользователь {user.id} ЗАМУЧЕН (не может отправлять сообщения).")
                
                if is_muted:
                    print(f"  [АНМУТ] Попытка размутить пользователя {user.id}...")
                    unmute_rights = ChatBannedRights(
                        until_date=None, send_messages=False, send_media=False, send_stickers=False,
                        send_gifs=False, send_games=False, send_inline=False, send_polls=False,
                        embed_links=False, invite_users=False, change_info=False, pin_messages=False
                    )
                    try:
                        await client(EditBannedRequest(chat, user.id, unmute_rights))
                        print(f"    [АНМУТ-УСПЕХ] Пользователь {user.id} успешно размучен.")
                        unmuted_count += 1
                        action_taken_this_user = True
                        await asyncio.sleep(DELAY_AFTER_UNMUTE)
                    except UserNotParticipantError: # Может случиться, если пользователь вышел, пока скрипт работал
                        print(f"    [АНМУТ-ОШИБКА] Пользователь {user.id} не является участником чата. Пропуск.")
                    except (ChatAdminRequiredError, UserAdminInvalidError):
                        print(f"    [АНМУТ-ОШИБКА] Недостаточно прав для анмута {user.id}.")
                    except ChatWriteForbiddenError:
                        print(f"    [АНМУТ-ОШИБКА] Нет прав на запись в чате для анмута {user.id}.")
                    except Exception as e:
                        print(f"    [АНМУТ-ОШИБКА] Не удалось размутить {user.id}: {type(e).__name__} - {e}")
                elif not user.deleted : # Если не собачка и не был замучен
                    print(f"  [ПРОВЕРКА-МУТА] Пользователь {user.id} не замучен. Анмут не требуется.")
                    skipped_not_muted_count +=1

                if not action_taken_this_user and not user.deleted:
                    await asyncio.sleep(DELAY_IF_NO_ACTION)

        except ChatAdminRequiredError:
            print(f"\nКритическая ошибка: У вашего аккаунта нет прав администратора в чате '{getattr(chat, 'title', chat.id)}' для получения списка участников или изменения их прав. Скрипт не может продолжить.")
            return
        except Exception as e:
            print(f"\nПроизошла непредвиденная ошибка при переборе участников: {type(e).__name__} - {e}", exc_info=True)
            return

        print("\n--- ЗАВЕРШЕНИЕ ---")
        print(f"Всего обработано записей участников: {processed_count}")
        print(f"Пользователей успешно размучено: {unmuted_count}")
        print(f"Пропущено (не были замучены): {skipped_not_muted_count}")
        print(f"Удаленных аккаунтов ('собачек') кикнуто: {kicked_deleted_count}")
        print("Скрипт завершил работу.")

if __name__ == '__main__':
    print("Инструкции по использованию (Оптимизированная Telethon версия):")
    print("1. Убедитесь, что Telethon установлен: pip install telethon")
    print("2. Убедитесь, что переменные окружения TELETHON_API_ID, TELETHON_API_HASH, TELETHON_CHAT_ID установлены,")
    print("   либо измените значения по умолчанию прямо в скрипте.")
    print("3. Аккаунт, используемый для запуска, должен быть администратором в целевом чате с правами на бан и ограничение участников.")
    print("4. Запустите скрипт: python unmute_and_cleanup_chat.py")
    print("5. При первом запуске с новым SESSION_NAME потребуется авторизация.")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nРабота скрипта прервана пользователем.") 