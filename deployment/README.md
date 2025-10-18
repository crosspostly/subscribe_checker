# Загрузка бота на сервер Beget

## Подготовка

### Windows

1. Установите [Git for Windows](https://gitforwindows.org/) или [OpenSSH для Windows](https://docs.microsoft.com/ru-ru/windows-server/administration/openssh/openssh_install_firstuse) для доступа к командам SSH и SCP.
2. Установите [7-Zip](https://www.7-zip.org/) для создания архивов.

### Linux/Mac

Все необходимые инструменты уже должны быть установлены.

## Настройка скрипта загрузки

1. Откройте файл `upload_to_beget.ps1` (для Windows) или `upload_to_beget.sh` (для Linux/Mac) в папке `deployment`.
2. Заполните следующие параметры:
   - `REMOTE_USER` - ваше имя пользователя на сервере Beget
   - `REMOTE_HOST` - адрес сервера (например, example.beget.com)

## Загрузка на сервер

### Windows

1. Откройте PowerShell.
2. Перейдите в корневую папку проекта: `cd путь_к_проекту`
3. Запустите скрипт: `.\deployment\upload_to_beget.ps1`

### Linux/Mac

1. Откройте терминал.
2. Перейдите в корневую папку проекта: `cd путь_к_проекту`
3. Сделайте скрипт исполняемым: `chmod +x deployment/upload_to_beget.sh`
4. Запустите скрипт: `./deployment/upload_to_beget.sh`

## Запуск бота на сервере

После загрузки файлов на сервер, подключитесь к серверу через SSH:

```bash
ssh ваш_пользователь@ваш_сервер
```

Затем выполните следующие команды:

```bash
cd ../opt/beget/bots/subbot
source venv/bin/activate
```

### Запуск бота вручную

```bash
python -m bot
```

### Настройка автозапуска через cron

1. Откройте редактор crontab:

```bash
crontab -e
```

2. Добавьте следующую строку для автозапуска бота при перезагрузке сервера:

```
@reboot cd /opt/beget/bots/subbot && source venv/bin/activate && python -m bot > /opt/beget/bots/subbot/logs/bot.log 2>&1
```

3. Для запуска бота в фоновом режиме, вы можете использовать `nohup` или `screen`:

```bash
# Запуск с nohup
nohup python -m bot > logs/bot.log 2>&1 &

# Запуск с screen
screen -S subbot
python -m bot
# Нажмите Ctrl+A, затем D для отключения от сессии
```

4. Для подключения к существующей сессии screen:

```bash
screen -r subbot
```

## Проверка работы бота

После запуска проверьте логи бота:

```bash
tail -f logs/bot.log
```

Если все настроено правильно, вы увидите сообщения о запуске бота. 