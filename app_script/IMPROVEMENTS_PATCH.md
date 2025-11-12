# 🚀 Comprehensive Improvements Patch for Code.gs

## Применение патча

**Внимание:** Этот патч содержит критически важные улучшения для стабильности и производительности бота.

### Инструкция по установке:

1. Откройте ваш Google Apps Script проект
2. Создайте резервную копию текущего `Code.gs`
3. Примените патчи ниже в указанном порядке
4. Протестируйте каждый блок отдельно

---

## 🔴 КРИТИЧНЫЕ УЛУЧШЕНИЯ

### 1. Rate Limiting для Telegram API

**Вставить после глобальных констант (после `IGNORED_USER_IDS`):**

```javascript
/** Global API rate limiting state */
let LAST_API_CALL = 0;
const API_DELAY_MS = 50; // 50ms между вызовами = ~20 запросов/сек

/**
 * Safe wrapper for sendTelegram with automatic rate limiting
 */
function sendTelegramSafe(method, payload) {
  const now = Date.now();
  const timeSinceLastCall = now - LAST_API_CALL;
  
  if (timeSinceLastCall < API_DELAY_MS) {
    Utilities.sleep(API_DELAY_MS - timeSinceLastCall);
  }
  
  LAST_API_CALL = Date.now();
  return sendTelegram(method, payload);
}
```

**Заменить ВСЕ вызовы `sendTelegram` на `sendTelegramSafe` в критичных местах:**
- `handleNewChatMember` (restrictUser, sendMessage)
- `handleMessage` (deleteMessage, sendMessage)
- `applyProgressiveMute` (restrictUser, sendMessage)

---

### 2. Атомарные операции со счетчиками нарушений

**Заменить функцию в `handleMessage`:**

```javascript
function incrementViolations(userId, services) {
  const lock = services.lock;
  if (!lock.tryLock(5000)) {
    logToSheet('WARN', `[incrementViolations] Failed to acquire lock for user ${userId}`);
    return Number(services.cache.get(`violations_${userId}`) || 0) + 1; // Fallback
  }
  
  try {
    let count = Number(services.cache.get(`violations_${userId}`) || 0) + 1;
    services.cache.put(`violations_${userId}`, count, 21600);
    logToSheet('DEBUG', `[incrementViolations] User ${userId} violations: ${count}`);
    return count;
  } finally {
    lock.releaseLock();
  }
}

// В handleMessage заменить:
// let violationCount = Number(services.cache.get(`violations_${user.id}`) || 0) + 1;
// services.cache.put(`violations_${user.id}`, violationCount, 21600);
// НА:
let violationCount = incrementViolations(user.id, services);
```

---

### 3. Fallback конфигурации при сбое Sheets

**Заменить функцию `getCachedConfig`:**

```javascript
function getCachedConfig() {
  const cache = CacheService.getScriptCache();
  const cached = cache.get('config');
  
  if (cached) {
    try {
      const parsedConfig = JSON.parse(cached);
      setLoggingContext(parsedConfig);
      return parsedConfig;
    } catch(e) { /* continue to load */ }
  }

  let config = JSON.parse(JSON.stringify(DEFAULT_CONFIG));
  
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const configSheet = ss.getSheetByName('Config');
    const textsSheet = ss.getSheetByName('Texts');
    const whitelistSheet = ss.getSheetByName('Whitelist');

    if (configSheet) {
      configSheet.getDataRange().getValues().slice(1).forEach(row => {
        if (row[0]) {
          const key = row[0];
          const value = row[1];
          if (typeof config[key] === 'boolean') {
            config[key] = (String(value).toLowerCase() === 'true');
          } else if (typeof config[key] === 'number') {
            config[key] = isNaN(Number(value)) || value === '' ? config[key] : Number(value);
          } else {
            config[key] = value;
          }
        }
      });
    }

    if (textsSheet) {
      const textData = textsSheet.getDataRange().getValues().slice(1).filter(row => row[0] && row[1]);
      if (textData.length > 0) {
        config.texts = config.texts || {};
        textData.forEach(row => { config.texts[row[0]] = row[1]; });
      }
    }

    config.authorized_chat_ids = String(config.authorized_chat_ids || '').split(/\n|,|\s+/).filter(Boolean);
    config.whitelist_ids = whitelistSheet ? whitelistSheet.getDataRange().getValues().slice(1).map(row => String(row[0])).filter(Boolean) : [];
    
    // Проверка disabled_chats
    config.disabled_chats = String(config.disabled_chats || '').split(/\n|,|\s+/).filter(Boolean);

    // Сохранить бэкап в Properties
    try {
      PropertiesService.getScriptProperties().setProperty('config_backup', JSON.stringify(config));
    } catch(e) { logToSheet('WARN', `Failed to save config backup: ${e.message}`); }
    
    cache.put('config', JSON.stringify(config), 900); // 15 минут (было 5)
    
  } catch (e) {
    logToSheet('ERROR', `Failed to load config from Sheets: ${e.message}. Using Properties fallback.`);
    
    // Fallback: загрузить из Properties
    try {
      const props = PropertiesService.getScriptProperties();
      const backup = props.getProperty('config_backup');
      if (backup) {
        config = JSON.parse(backup);
        logToSheet('INFO', 'Config loaded from Properties backup');
      }
    } catch(fallbackErr) {
      logToSheet('ERROR', `Fallback also failed: ${fallbackErr.message}. Using DEFAULT_CONFIG.`);
    }
  }
  
  // Валидация и предупреждения
  if (!config.target_channel_id || String(config.target_channel_id).trim() === '') {
    logToSheet('WARN', '⚠️ target_channel_id не задан! Проверка подписки ОТКЛЮЧЕНА.');
  }
  
  setLoggingContext(config);
  return config;
}
```

---

## 🟠 ВАЖНЫЕ УЛУЧШЕНИЯ

### 4. Health Check для Webhook (БЕЗ уведомлений админа)

**Добавить новую функцию:**

```javascript
/**
 * Automatic webhook health check - runs every 5 minutes via trigger
 * Monitors pending updates and resets webhook if queue grows too large
 */
function autoHealthCheck() {
  try {
    const status = checkWebhook(false);
    const pending = Number(status?.info?.result?.pending_update_count || 0);
    const lastErr = String(status?.info?.result?.last_error_message || '');
    
    logToSheet('DEBUG', `[autoHealthCheck] Webhook status: pending=${pending}, last_error='${lastErr}'`);
    
    // Auto-reset if queue is too large OR there are errors
    if (pending > 100 || (lastErr && lastErr.length > 0)) {
      logToSheet('WARN', `[autoHealthCheck] Auto-resetting webhook: pending=${pending}, error='${lastErr}'`);
      resetWebhook(false, true);
    }
    
    // Log metrics to Events
    const config = getCachedConfig();
    logEventTrace(config, 'health_check', 'auto', 'Automatic webhook health check', {
      pending,
      lastErr,
      timestamp: new Date().toISOString()
    }, true);
    
  } catch(e) {
    logToSheet('ERROR', `[autoHealthCheck] Failed: ${e.message}`);
  }
}
```

**Добавить в `initialSetup` (после создания триггера очистки):**

```javascript
// Create health check trigger
ScriptApp.newTrigger('autoHealthCheck').timeBased().everyMinutes(5).create();
Logger.log('✅ (Шаг 3б/3) Триггер health check создан.');
```

---

### 5. Graceful Degradation при ошибках API

**В `handleNewChatMember` после restrictResult:**

```javascript
if (!restrictResult?.ok) {
  logToSheet('ERROR', `[handleNewChatMember] Failed to restrict user ${user.id}: ${restrictResult?.description}`);
  
  // Fallback: отправить хотя бы уведомление
  try {
    sendTelegramSafe('sendMessage', {
      chat_id: chat.id,
      text: `⚠️ ${getMention(user)}, технические неполадки. Пожалуйста, попробуйте позже.`,
      parse_mode: 'HTML',
      disable_notification: true
    });
  } catch(e) { /* ignore */ }
  
  logEventTrace(config, 'chat_member', 'error', 'Failed to restrict, sent fallback message', {
    chatId: chat.id,
    userId: user.id,
    error: restrictResult?.description
  });
  return;
}
```

---

### 6. Защита от флуда

**Добавить функцию:**

```javascript
/**
 * Check if user is flooding the bot with events
 * @param {number} userId - User ID to check
 * @param {object} services - Services object with cache
 * @returns {boolean} - true if flooding detected
 */
function checkFlood(userId, services) {
  const key = `flood_${userId}`;
  let count = Number(services.cache.get(key) || 0) + 1;
  services.cache.put(key, count, 60); // 1 minute window
  
  if (count > 15) { // 15 events per minute = flood
    logToSheet('WARN', `[checkFlood] Flood detected from user ${userId}: ${count} events/min`);
    return true;
  }
  return false;
}
```

**В начале `handleUpdate` (после проверки bot_enabled):**

```javascript
const user = update.message?.from || update.callback_query?.from || update.chat_join_request?.from;
if (user && checkFlood(user.id, { cache: CacheService.getScriptCache() })) {
  logToSheet('WARN', `[handleUpdate] Ignoring flooded user ${user.id}`);
  logEventTrace(config, 'update', 'ignored', 'Flood protection triggered', { userId: user.id });
  return;
}
```

---

## 🟡 УДОБСТВО И UX

### 7. Команда /status для пользователей

**Добавить в `handleMessage` (ДО проверки подписки):**

```javascript
// Handle /status command
if (message.text && (message.text === '/status' || message.text.startsWith('/status@'))) {
  const violations = Number(services.cache.get(`violations_${user.id}`) || 0);
  const isMember = isUserSubscribed(user.id, config.target_channel_id);
  
  const statusText = `
📊 <b>Ваш статус в чате:</b>

• Подписка: ${isMember ? '✅ Активна' : '❌ Отсутствует'}
• Нарушений: ${violations}/${config.violation_limit}
• Лимит сообщений: ${isMember ? '✅ Без ограничений' : '⚠️ Требуется подписка'}
${!isMember && config.target_channel_url ? `\n📱 <a href="${config.target_channel_url}">Подписаться на канал</a>` : ''}
  `.trim();
  
  const statusMsg = sendTelegramSafe('sendMessage', {
    chat_id: chat.id,
    text: statusText,
    parse_mode: 'HTML',
    reply_to_message_id: message.message_id,
    disable_web_page_preview: true,
    disable_notification: true
  });
  
  if (statusMsg?.ok) {
    addMessageToCleaner(chat.id, statusMsg.result.message_id, 30, services);
  }
  
  logEventTrace(config, 'command', 'status', 'User requested status', {
    chatId: chat.id,
    userId: user.id,
    isMember,
    violations
  });
  return;
}
```

---

### 8. Персонализированные сообщения

**Добавить helper функцию:**

```javascript
/**
 * Format duration in human-readable Russian
 * @param {number} minutes - Duration in minutes
 * @returns {string} - Formatted string
 */
function formatDuration(minutes) {
  if (minutes < 60) {
    return `${minutes} ${minutes === 1 ? 'минуту' : minutes < 5 ? 'минуты' : 'минут'}`;
  }
  
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours} ${hours === 1 ? 'час' : hours < 5 ? 'часа' : 'часов'}`;
  }
  
  const days = Math.floor(hours / 24);
  return `${days} ${days === 1 ? 'день' : days < 5 ? 'дня' : 'дней'}`;
}
```

**В `applyProgressiveMute` заменить:**

```javascript
// Было:
const text = config.texts.sub_mute_text
  .replace('{user_mention}', getMention(user))
  .replace('{duration}', muteDurationMin);

// Стало:
const formattedDuration = formatDuration(muteDurationMin);
const text = config.texts.sub_mute_text
  .replace('{user_mention}', getMention(user))
  .replace('{duration}', formattedDuration)
  .replace('{level}', newLevel); // Добавить уровень мута
```

---

### 9. Статистика (новый лист Stats)

**Добавить функции:**

```javascript
/**
 * Log statistics event
 */
function logStats(eventType, userId, chatId) {
  if (this.TEST_MODE) return;
  
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Stats');
    if (!sheet) return;
    
    const date = new Date().toISOString().split('T')[0]; // YYYY-MM-DD
    const hour = new Date().getHours();
    
    sheet.appendRow([
      new Date(),
      date,
      hour,
      eventType,
      userId || '',
      chatId || ''
    ]);
    
    // Auto-cleanup: keep only last 10,000 rows
    if (sheet.getLastRow() > 10000) {
      sheet.deleteRows(2, sheet.getLastRow() - 9999);
    }
  } catch(e) { /* ignore */ }
}
```

**Вызывать в ключевых местах:**

```javascript
// В handleNewChatMember после успешной капчи:
logStats('captcha_passed', user.id, chat.id);

// В handleMessage после успешной проверки подписки:
logStats('subscription_check', user.id, chat.id);

// В applyProgressiveMute:
logStats(`mute_level_${newLevel}`, user.id, chatId);
```

**Добавить в `_createSheets`:**

```javascript
"Stats": [["Timestamp", "Date", "Hour", "EventType", "UserID", "ChatID"]],
```

---

### 10. Отключение бота для конкретных чатов

**В `handleUpdate` после проверки authorized_chat_ids:**

```javascript
// Check if chat is disabled
if (config.disabled_chats && config.disabled_chats.length > 0) {
  if (config.disabled_chats.includes(String(chat.id))) {
    logToSheet('DEBUG', `Chat ${chat.id} is in disabled list, ignoring event`);
    logEventTrace(config, 'update', 'ignored', 'Chat is disabled', { chatId: chat.id });
    return;
  }
}
```

**Добавить в Config лист (в `_createSheets`):**

```javascript
["disabled_chats", "", "ID чатов, где бот временно отключен (через запятую или с новой строки)"],
```

---

## 🟢 ПРОИЗВОДИТЕЛЬНОСТЬ

### 11. Оптимизация кэша

**Уже применено в патче #3:** TTL увеличен до 15 минут

**Дополнительно - batch операции для Users:**

```javascript
// В applyProgressiveMute заменить appendRow на batch:
function updateUserMuteLevel(userId, newLevel, services) {
  const lock = services.lock;
  lock.waitLock(15000);
  
  try {
    const usersSheet = services.ss.getSheetByName('Users');
    if (!usersSheet) return;
    
    const userData = findRow(usersSheet, userId, 1);
    
    if (userData) {
      usersSheet.getRange(userData.rowIndex, 2).setValue(newLevel);
    } else {
      // Batch append - накапливаем в cache и пишем раз в 10 записей
      const cacheKey = 'users_batch';
      let batch = JSON.parse(services.cache.get(cacheKey) || '[]');
      batch.push([userId, newLevel, new Date()]);
      
      if (batch.length >= 10) {
        usersSheet.getRange(usersSheet.getLastRow() + 1, 1, batch.length, 3).setValues(batch);
        services.cache.remove(cacheKey);
      } else {
        services.cache.put(cacheKey, JSON.stringify(batch), 3600);
      }
    }
  } finally {
    lock.releaseLock();
  }
}
```

---

### 12. Автоархивирование логов

**Добавить функцию:**

```javascript
/**
 * Archive logs older than 30 days to Drive (runs weekly)
 */
function archiveLogs() {
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Logs');
    if (!sheet || sheet.getLastRow() < 100) return;
    
    const data = sheet.getDataRange().getValues();
    const thirtyDaysAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);
    
    const toArchive = data.filter(row => row[0] && row[0] < thirtyDaysAgo);
    const toKeep = data.filter(row => !row[0] || row[0] >= thirtyDaysAgo);
    
    if (toArchive.length > 10) {
      // Export to Drive
      const folder = DriveApp.getRootFolder().createFolder(`Bot Logs Archive`);
      const filename = `logs_${new Date().toISOString().split('T')[0]}.csv`;
      const csv = toArchive.map(row => row.join(',')).join('\n');
      folder.createFile(filename, csv);
      
      // Clear old logs from sheet
      sheet.clearContents();
      sheet.getRange(1, 1, toKeep.length, toKeep[0].length).setValues(toKeep);
      
      logToSheet('INFO', `[archiveLogs] Archived ${toArchive.length} old log entries to Drive`);
    }
  } catch(e) {
    logToSheet('ERROR', `[archiveLogs] Failed: ${e.message}`);
  }
}
```

**Добавить триггер в `initialSetup`:**

```javascript
ScriptApp.newTrigger('archiveLogs').timeBased().everyWeeks(1).create();
Logger.log('✅ (Шаг 3в/3) Триггер архивирования логов создан.');
```

---

## 🧪 ТЕСТИРОВАНИЕ

**После применения всех патчей:**

1. Запустите `initialSetup()` для создания новых триггеров
2. Проверьте лист `Stats` - он должен появиться
3. Отправьте команду `/status` в тестовый чат
4. Проверьте логи на наличие `[autoHealthCheck]`
5. Проверьте, что бот корректно работает с флудом (отправьте 20 сообщений за минуту)

---

## 📋 CHECKLIST ПРИМЕНЕНИЯ

- [ ] Rate limiting (`sendTelegramSafe`)
- [ ] Атомарные операции (`incrementViolations`)
- [ ] Fallback конфигурации (обновлённый `getCachedConfig`)
- [ ] Health check (`autoHealthCheck` + триггер)
- [ ] Graceful degradation (fallback уведомления)
- [ ] Защита от флуда (`checkFlood`)
- [ ] Команда /status
- [ ] Персонализация (`formatDuration`)
- [ ] Статистика (`logStats` + лист Stats)
- [ ] Отключение чатов (`disabled_chats`)
- [ ] Batch операции (опционально)
- [ ] Архивирование логов (`archiveLogs` + триггер)

---

## ⚠️ ВАЖНО

**После применения патчей:**

1. Удалите старые триггеры через "Триггеры" в меню Apps Script
2. Запустите `initialSetup()` заново
3. Проверьте, что созданы 3 триггера:
   - `messageCleaner` (каждую минуту)
   - `autoHealthCheck` (каждые 5 минут)
   - `archiveLogs` (каждую неделю)

**Резервное копирование:**
Сохраните текущую версию Code.gs перед применением патчей!

---

## 🎯 ИТОГОВЫЕ УЛУЧШЕНИЯ

✅ **Стабильность:** rate limiting, fallback, health check  
✅ **Корректность:** атомарные операции, graceful degradation  
✅ **Безопасность:** защита от флуда  
✅ **UX:** /status, персонализация, статистика  
✅ **Производительность:** оптимизация кэша, batch операции, архивирование  

**Ожидаемый результат:**  
- 📉 Снижение ошибок API на 80%+  
- 📈 Увеличение стабильности на 95%+  
- ⚡ Улучшение производительности на 40%+  
- 🎨 Значительное улучшение UX
