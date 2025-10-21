#!/bin/bash

# Скрипт загрузки бота на сервер Beget
# Путь назначения: ../opt/beget/bots/subbot

# Настройки
REMOTE_USER=""  # Введите ваше имя пользователя
REMOTE_HOST=""  # Введите адрес сервера (например, example.beget.com)
REMOTE_PATH="../opt/beget/bots/subbot"

# Проверка заполнения данных
if [ -z "$REMOTE_USER" ] || [ -z "$REMOTE_HOST" ]; then
    echo "ОШИБКА: Заполните REMOTE_USER и REMOTE_HOST в файле upload_to_beget.sh"
    exit 1
fi

# Подготовка данных для загрузки
echo "Подготовка данных для загрузки..."

# Создание архива с проектом
echo "Создание архива..."
tar -czf deployment/subbot.tar.gz --exclude="venv" --exclude="__pycache__" --exclude=".git" --exclude="logs" --exclude="deployment" .

# Загрузка архива на сервер
echo "Загрузка на сервер..."
scp deployment/subbot.tar.gz $REMOTE_USER@$REMOTE_HOST:~/

# Подключение к серверу и распаковка архива
echo "Распаковка архива на сервере..."
ssh $REMOTE_USER@$REMOTE_HOST << EOF
    mkdir -p $REMOTE_PATH
    tar -xzf ~/subbot.tar.gz -C $REMOTE_PATH
    cd $REMOTE_PATH
    
    # Установка виртуального окружения и зависимостей
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    
    # Настройка прав доступа
    chmod +x $REMOTE_PATH/bot/__main__.py
    
    echo "Установка завершена!"
EOF

echo "Процесс загрузки завершен!" 