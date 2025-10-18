# PowerShell скрипт для загрузки бота на сервер Beget
# Путь назначения: ../opt/beget/bots/subbot

# Настройки
$REMOTE_USER = "root"  # Введите ваше имя пользователя
$REMOTE_HOST = "212.67.9.100"  # Введите адрес сервера (например, example.beget.com)
$REMOTE_PATH = "../opt/beget/bots/subbot"

# Проверка установки программ
function Check-Command {
    param (
        [string]$cmdName
    )
    return (Get-Command -Name $cmdName -ErrorAction SilentlyContinue)
}

if (-not (Check-Command -cmdName "ssh") -or -not (Check-Command -cmdName "scp")) {
    Write-Host "ОШИБКА: Требуются утилиты SSH и SCP. Установите OpenSSH или Git for Windows." -ForegroundColor Red
    exit 1
}

# Проверка заполнения данных
if ([string]::IsNullOrEmpty($REMOTE_USER) -or [string]::IsNullOrEmpty($REMOTE_HOST)) {
    Write-Host "ОШИБКА: Заполните REMOTE_USER и REMOTE_HOST в файле upload_to_beget.ps1" -ForegroundColor Red
    exit 1
}

# Подготовка данных для загрузки
Write-Host "Подготовка данных для загрузки..." -ForegroundColor Cyan

# Проверка наличия 7-Zip для создания архива
if (Check-Command -cmdName "7z") {
    # Создание архива с проектом
    Write-Host "Создание архива..." -ForegroundColor Cyan
    $exclude = "venv", "__pycache__", ".git", "logs", "deployment"
    $excludeArgs = $exclude | ForEach-Object { "-xr!$_" }
    
    & 7z a -ttar deployment\subbot.tar . $excludeArgs
    & 7z a -tgzip deployment\subbot.tar.gz deployment\subbot.tar
    
    # Удаляем временный tar файл
    Remove-Item -Path "deployment\subbot.tar" -Force
} else {
    Write-Host "7-Zip не найден. Установите 7-Zip для создания архива." -ForegroundColor Red
    exit 1
}

# Загрузка архива на сервер
Write-Host "Загрузка на сервер..." -ForegroundColor Cyan
& scp "deployment\subbot.tar.gz" "${REMOTE_USER}@${REMOTE_HOST}:~/"

# Подключение к серверу и распаковка архива
Write-Host "Распаковка архива на сервере..." -ForegroundColor Cyan
$sshCommands = @"
mkdir -p $REMOTE_PATH
tar -xzf ~/subbot.tar.gz -C $REMOTE_PATH
cd $REMOTE_PATH

# Установка виртуального окружения и зависимостей
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Настройка прав доступа
chmod +x ${REMOTE_PATH}/bot/__main__.py

echo "Установка завершена!"
"@

& ssh "$REMOTE_USER@$REMOTE_HOST" $sshCommands

Write-Host "Процесс загрузки завершен!" -ForegroundColor Green 