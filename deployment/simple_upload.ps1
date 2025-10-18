# Скрипт автоматической загрузки
$user = Read-Host "Введите пользователя"
$host_addr = Read-Host "Введите адрес сервера"
$path = "../opt/beget/bots/subbot"

# Обновляем скрипт
$content = Get-Content -Path "deployment\upload_to_beget.ps1" -Raw
$content = $content -replace '\$REMOTE_USER = ""', "`$REMOTE_USER = `"$user`""
$content = $content -replace '\$REMOTE_HOST = ""', "`$REMOTE_HOST = `"$host_addr`""
Set-Content -Path "deployment\upload_to_beget.ps1" -Value $content

# Запускаем
Write-Host "Начинаю загрузку..."
.\deployment\upload_to_beget.ps1 