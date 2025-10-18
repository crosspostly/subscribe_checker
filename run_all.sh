#!/bin/bash

# --- Настройки ---
TELETHON_SCRIPT_NAME="collect_user_ids_telethon.py"
AIOGRAM_SCRIPT_NAME="execute_actions_aiogram.py"
PYTHON_EXECUTABLE="python3" # Или просто "python", если python3 - это python по умолчанию

# Цвета для вывода (опционально)
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Функция для проверки наличия команды
command_exists() {
  command -v "$1" >/dev/null 2>&1
}

echo -e "${YELLOW}--- Начало выполнения пакетного задания ---${NC}"

# 1. Проверка наличия Python
if ! command_exists $PYTHON_EXECUTABLE; then
  echo -e "${RED}Ошибка: Интерпретатор Python '$PYTHON_EXECUTABLE' не найден. Установите Python.${NC}"
  exit 1
fi
echo -e "${GREEN}Интерпретатор Python найден: $($PYTHON_EXECUTABLE --version)${NC}"

# 2. Проверка наличия скрипта сбора данных Telethon
if [ ! -f "$TELETHON_SCRIPT_NAME" ]; then
  echo -e "${RED}Ошибка: Скрипт '$TELETHON_SCRIPT_NAME' не найден в текущей директории.${NC}"
  exit 1
fi

# 3. Проверка наличия скрипта исполнителя Aiogram
if [ ! -f "$AIOGRAM_SCRIPT_NAME" ]; then
  echo -e "${RED}Ошибка: Скрипт '$AIOGRAM_SCRIPT_NAME' не найден в текущей директории.${NC}"
  exit 1
fi

# 4. Напоминание о переменных окружения (пользователь должен их установить сам)
echo -e "\n${YELLOW}ВАЖНО: Убедитесь, что установлены следующие переменные окружения:${NC}"
echo "  - TELETHON_API_ID"
echo "  - TELETHON_API_HASH"
echo "  - TELETHON_CHAT_ID"
echo "  - TELEGRAM_BOT_TOKEN"
echo "  - AIOGRAM_TARGET_CHAT_ID (опционально, если отличается от TELETHON_CHAT_ID или значения по умолчанию в скрипте)"
echo -e "Первый запуск Telethon-скрипта может потребовать интерактивной авторизации (ввод номера телефона и кода).\n"
# Можно добавить небольшую паузу, чтобы пользователь успел прочитать
# read -p "Нажмите Enter для продолжения..."

# --- Шаг 1: Запуск скрипта сбора ID (Telethon) ---
echo -e "${YELLOW}--- Шаг 1: Запуск скрипта сбора ID ($TELETHON_SCRIPT_NAME) ---${NC}"
$PYTHON_EXECUTABLE "$TELETHON_SCRIPT_NAME"
TELETHON_EXIT_CODE=$? # Сохраняем код выхода

if [ $TELETHON_EXIT_CODE -eq 0 ]; then
  echo -e "\n${GREEN}--- Скрипт сбора ID ($TELETHON_SCRIPT_NAME) завершен успешно. ---${NC}"
else
  echo -e "\n${RED}--- Ошибка: Скрипт сбора ID ($TELETHON_SCRIPT_NAME) завершился с кодом $TELETHON_EXIT_CODE. ---${NC}"
  echo -e "${RED}Проверьте логи скрипта. Выполнение прервано.${NC}"
  exit $TELETHON_EXIT_CODE
fi

# Проверка, создан ли файл с данными (опционально, но полезно)
OUTPUT_DATA_FILE="user_ids_for_bot.json" # Имя файла должно совпадать с тем, что в Telethon-скрипте
if [ ! -f "$OUTPUT_DATA_FILE" ]; then
    echo -e "\n${RED}--- Ошибка: Файл с данными '$OUTPUT_DATA_FILE' не был создан Telethon-скриптом. ---${NC}"
    echo -e "${RED}Выполнение прервано. Проверьте работу скрипта $TELETHON_SCRIPT_NAME.${NC}"
    exit 1
fi

# --- Шаг 2: Запуск скрипта выполнения действий (Aiogram) ---
echo -e "\n${YELLOW}--- Шаг 2: Запуск скрипта выполнения действий ($AIOGRAM_SCRIPT_NAME) ---${NC}"
$PYTHON_EXECUTABLE "$AIOGRAM_SCRIPT_NAME"
AIOGRAM_EXIT_CODE=$?

if [ $AIOGRAM_EXIT_CODE -eq 0 ]; then
  echo -e "\n${GREEN}--- Скрипт выполнения действий ($AIOGRAM_SCRIPT_NAME) завершен успешно. ---${NC}"
else
  echo -e "\n${RED}--- Ошибка: Скрипт выполнения действий ($AIOGRAM_SCRIPT_NAME) завершился с кодом $AIOGRAM_EXIT_CODE. ---${NC}"
  echo -e "${RED}Проверьте логи скрипта.${NC}"
  exit $AIOGRAM_EXIT_CODE
fi

echo -e "\n${GREEN}--- Все операции пакетного задания успешно завершены. ---${NC}"
exit 0 