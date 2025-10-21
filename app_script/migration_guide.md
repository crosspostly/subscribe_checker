# 🔄 Migration Guide - Apps Script Bot Optimization

**Руководство по миграции на оптимизированную версию Google Apps Script бота**

---

## 📋 **Pre-Migration Checklist**

### ✅ **Что проверить перед обновлением:**

1. **Backup текущего кода:**
   ```javascript
   // Сохраните текущий app_script/Code.gs
   // Экспортируйте Google Sheets данные (Config, Whitelist, Users, Logs)
   ```

2. **Документируйте текущие настройки:**
   - ID авторизованных чатов
   - ID целевого канала  
   - Пользователи в белом списке
   - Кастомные тексты (если есть)

3. **Проверьте версию:**
   - Если у вас версия до октября 2024 → **обязательное обновление**
   - Если после → проверьте наличие фильтрации

---

## 🚀 **Migration Options**

### **Option 1: Clean Installation (Recommended)**

**Для новых инсталляций или кардинального обновления:**

```bash
# 1. Backup старых данных
# 2. Замените весь Code.gs новой версией
# 3. Замените tests.gs новой версией  
# 4. Выполните initialSetup()
# 5. Восстановите конфигурацию из backup
```

### **Option 2: Sequential Patches**

**Для поэтапного обновления:**

```bash
# Применяйте патчи по порядку:
git apply 0001-feat-improve-subscription-warning-with-channel-URL.patch
# Тестируйте
git apply 0002-feat-add-inline-keyboard-buttons-for-subscription-ch.patch  
# Тестируйте
git apply 0003-fix-major-bugfix-proper-new-member-handling-chat-joi.patch
# Тестируйте
```

### **Option 3: One-Shot Patch**

**Для опытных пользователей:**

```bash
# Применить все изменения сразу
git apply complete_optimization_changes.patch
```

---

## ⚙️ **Configuration Migration**

### **Новые обязательные поля Config:**

| Старое поле | Новое поле | Миграция |
|-------------|------------|----------|
| `bot_enabled` | `bot_enabled` | Без изменений |
| `target_channel_id` | `target_channel_id` | Без изменений |
| `authorized_chat_ids` | `authorized_chat_ids` | Без изменений |
| ❌ Не было | `target_channel_url` | **ДОБАВИТЬ** `https://t.me/yourchannel` |
| `captcha_mute_duration_min: 5` | `captcha_mute_duration_min: 30` | **ОБНОВИТЬ** |
| `captcha_message_timeout_sec: 300` | `captcha_message_timeout_sec: 30` | **ОБНОВИТЬ** |
| `warning_message_timeout_sec: 30` | `warning_message_timeout_sec: 20` | **ОБНОВИТЬ** |

### **Whitelist Migration:**

```javascript
// СТАРЫЙ ФОРМАТ (частичная фильтрация):
Whitelist лист: только каналы проверялись

// НОВЫЙ ФОРМАТ (полная фильтрация):
Whitelist лист: 
- ID пользователей (будут полностью игнорироваться)
- ID каналов (посты игнорируются) 
- ID ботов (все события игнорируются)
```

---

## 🔍 **Breaking Changes**

### **⚠️ Важные изменения поведения:**

1. **Фильтрация теперь полная:**
   ```javascript
   // ДО: Белый список проверялся поздно
   // ПОСЛЕ: Белый список проверяется в самом начале
   ```

2. **Админы фильтруются раньше:**
   ```javascript  
   // ДО: Админы проверялись в handleMessage
   // ПОСЛЕ: Админы проверяются в начале handleUpdate
   ```

3. **CAPTCHA только для реальных join:**
   ```javascript
   // ДО: CAPTCHA на все события чата
   // ПОСЛЕ: CAPTCHA только left→member, restricted→member
   ```

4. **Новый порядок фильтрации:**
   ```javascript
   // ОБЯЗАТЕЛЬНЫЙ порядок проверок:
   // 1. Боты → 2. Системные → 3. Белый список → 4. Админы → 5. Личка
   ```

---

## 🧪 **Post-Migration Testing**

### **Обязательные тесты после миграции:**

1. **Запуск test suite:**
   ```javascript
   runAllTests(); // Должно пройти 33+ тестов
   ```

2. **Функциональные тесты:**
   ```
   ✅ Новый участник → CAPTCHA отправляется
   ✅ Неподписанный пользователь → кнопки появляются  
   ✅ Админ пишет → игнорируется
   ✅ Бот пишет → игнорируется
   ✅ Пользователь в белом списке → игнорируется
   ✅ Канал постит → игнорируется
   ```

3. **Performance тест:**
   ```
   ✅ Лог показывает "filtered out early" для игнорируемых
   ✅ Нет лишних API вызовов для фильтруемых событий
   ```

---

## 🚨 **Troubleshooting**

### **Если что-то сломалось:**

**1. CAPTCHA не отправляется:**
```javascript
// Проверьте логи на наличие:
logToSheet('INFO', 'Real user join detected: ...')

// Если нет - проверьте:
// - Права бота в чате (can_restrict_members, can_delete_messages)
// - Не является ли пользователь админом/в белом списке
```

**2. Кнопки не появляются:**
```javascript
// Убедитесь что target_channel_url настроен:
Config лист: target_channel_url = https://t.me/yourchannel

// Проверьте в логах:
logToSheet('INFO', 'Processing event for user ... after all filters passed')
```

**3. Белый список не работает:**
```javascript
// НОВЫЙ формат Whitelist листа:
// [user_id, comment]
// 12345, "My other bot"
// -100777, "Partner channel"
```

**4. Производительность не улучшилась:**
```javascript
// Проверьте логи на наличие:
logToSheet('DEBUG', 'Bot user ... Ignoring.')
logToSheet('DEBUG', 'Whitelisted user ... Ignoring.')
logToSheet('DEBUG', 'Admin ... Ignoring.')

// Если нет - проверьте порядок функций в handleUpdate
```

---

## 📊 **Performance Metrics**

### **Ожидаемые улучшения:**

```bash
# API Calls сокращение:
ДО:  ~100 calls/день для 1000 событий
ПОСЛЕ: ~40 calls/день для 1000 событий  

# Response Time:
ДО:  2-5 секунд на фильтрацию
ПОСЛЕ: <1 секунда на фильтрацию

# Логи:
ДО:  Много DEBUG сообщений о проверках
ПОСЛЕ: Четкие "filtered out early" для игнорируемых
```

---

## 🔄 **Rollback Plan**

### **Если нужно откатиться:**

1. **Сохранить данные:**
   ```javascript
   // Экспортировать: Config, Whitelist, Users, Logs
   ```

2. **Откат кода:**
   ```bash
   # Восстановить backup Code.gs и tests.gs
   # Или использовать git revert
   ```

3. **Восстановить настройки:**
   ```javascript
   // Вернуть старые значения:
   captcha_mute_duration_min: 5
   captcha_message_timeout_sec: 300  
   warning_message_timeout_sec: 30
   ```

---

## ✅ **Migration Success Indicators**

### **Как понять, что миграция успешна:**

```javascript
✅ runAllTests() проходит без ошибок
✅ Логи показывают "filtered out early" для ботов/админов/белого списка
✅ CAPTCHA приходит только новым участникам
✅ Неподписанные получают кнопки с каналом
✅ API calls сократились на ~60%
✅ Response time уменьшился
```

---

## 🔗 **Support Resources**

- 📖 **[IMPROVEMENTS_SUMMARY.md](./IMPROVEMENTS_SUMMARY.md)** - Детали всех изменений
- 🚀 **[DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)** - Пошаговый деплой  
- 📝 **[app_script/README.md](./app_script/README.md)** - Полная документация
- 🧪 **[app_script/tests.gs](./app_script/tests.gs)** - Test suite

---

**💡 При возникновении проблем создайте Issue на GitHub с логами и описанием ошибки.**
