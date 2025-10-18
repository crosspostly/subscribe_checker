# Автоматическая загрузка бота на сервер Beget
# Скрипт запрашивает данные входа и выполняет загрузку

# Запрос данных для подключения
$REMOTE_USER = Read-Host "root"
$REMOTE_HOST = Read-Host "212.67.9.100"
$REMOTE_PATH = "../opt/beget/bots/subbot"

# Обновляем файл upload_to_beget.ps1 с полученными данными
$uploadScript = Get-Content -Path "deployment\upload_to_beget.ps1" -Raw
$uploadScript = $uploadScript -replace '\$REMOTE_USER = ""', "`$REMOTE_USER = `"$REMOTE_USER`""
$uploadScript = $uploadScript -replace '\$REMOTE_HOST = ""', "`$REMOTE_HOST = `"$REMOTE_HOST`""
Set-Content -Path "deployment\upload_to_beget.ps1" -Value $uploadScript

# Запускаем скрипт загрузки
Write-Host "Запуск процесса загрузки на сервер $REMOTE_HOST..." -ForegroundColor Cyan
& .\deployment\upload_to_beget.ps1

# После загрузки показываем инструкции по запуску
Write-Host "`nДля запуска бота на сервере выполните:" -ForegroundColor Yellow
Write-Host "1. Подключитесь к серверу: ssh $REMOTE_USER@$REMOTE_HOST" -ForegroundColor White
Write-Host "2. Перейдите в каталог бота: cd $REMOTE_PATH" -ForegroundColor White
Write-Host "3. Активируйте окружение: source venv/bin/activate" -ForegroundColor White
Write-Host "4. Запустите бота: python -m bot" -ForegroundColor White
Write-Host "`nДля запуска в фоновом режиме используйте:" -ForegroundColor Green
Write-Host 'nohup python -m bot > logs/bot.log 2>&1' -ForegroundColor Green 