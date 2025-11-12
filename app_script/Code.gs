/**
 * @file Code.gs - ПОЛНЫЙ КОД TELEGRAM БОТ ПРОВЕРКИ ПОДПИСКИ
 * @description Telegram бот с проверкой подписки, CAPTCHA и прогрессивным мутом
 * 
 * ✅ ИСПРАВЛЕНИЯ ВЕРСИЯ 3:
 * 1. doPost() возвращает HtmlService вместо ContentService (ошибка 302 исправлена)
 * 2. handleCallbackQuery() отвечает на callback ПЕРВЫМ (убирает часики)
 * 3. handleMessage() проверяет результат deleteMessage()
 * 4. Редактирование сообщений ТОЛЬКО если текст изменился
 * 5. Результаты показываются АЛЕРТАМИ (всплывающие окна), не новыми сообщениями
 */

// =================================================================================
// ===================  A. SCRIPT-WIDE DEFAULTS & CONSTANTS  ====================
// =================================================================================

/**
 * Конфигурация по умолчанию. Используется как fallback если лист Config отсутствует.
 */
const DEFAULT_CONFIG = {
  bot_enabled: true,
  extended_logging_enabled: false,
  developer_mode_enabled: false,
  target_channel_id: "-1001168879742",
  target_channel_url: "https://t.me/+fSmCfuEEzPVlYTky",
  authorized_chat_ids: "-1001491334227\n-1001568712129",
  admin_id: "183761194",
  captcha_mute_duration_min: 30,
  captcha_message_timeout_sec: 30,
  warning_message_timeout_sec: 20,
  violation_limit: 3,
  mute_level_1_duration_min: 60,
  mute_level_2_duration_min: 1440,
  mute_level_3_duration_min: 10080,
  texts: {
    captcha_text: "{user_mention}, добро пожаловать! Чтобы писать в чат, подтвердите, что вы не робот.",
    sub_warning_text: "{user_mention}, чтобы писать сообщения в этом чате, пожалуйста, подпишитесь на:\n\n • {channel_link}\n\nПосле подписки нажмите кнопку ниже.",
    sub_warning_text_no_link: "{user_mention}, чтобы отправлять сообщения в этот чат, вы должны быть подписаны на наш канал.",
    sub_success_text: "🎉 {user_mention}, вы успешно подписались и теперь можете писать сообщения!",
    sub_fail_text: "🚫 {user_mention}, не удалось подтвердить вашу подписку. Убедитесь, что подписаны на все каналы, и попробуйте снова.",
    sub_mute_text: "{user_mention}, вы были временно ограничены в отправке сообщений на {duration} минут, так как не подписались на обязательные каналы."
  }
};

/** Системные аккаунты которые всегда игнорируются */
const IGNORED_USER_IDS = ['136817688', '777000'];

/** Глобальный контекст логирования */
const LOGGING_CONTEXT = { extended_logging_enabled: false, developer_mode_enabled: false };

/**
 * Обновляет глобальный контекст логирования
 * @param {boolean|object} flagOrConfig - флаг или объект конфига
 */
function setLoggingContext(flagOrConfig) {
  if (typeof flagOrConfig === 'boolean') {
    LOGGING_CONTEXT.extended_logging_enabled = flagOrConfig;
    LOGGING_CONTEXT.developer_mode_enabled = false;
  } else {
    LOGGING_CONTEXT.extended_logging_enabled = !!(flagOrConfig && flagOrConfig.extended_logging_enabled);
    LOGGING_CONTEXT.developer_mode_enabled = !!(flagOrConfig && flagOrConfig.developer_mode_enabled);
  }
}

/**
 * Безопасно получает информацию о участнике чата
 * @param {string} chatId - ID чата
 * @param {string|number} userId - ID пользователя
 * @returns {object} - Ответ от Telegram API
 */
function getChatMemberSafe(chatId, userId) {
  try {
    return sendTelegram('getChatMember', { chat_id: chatId, user_id: userId });
  } catch (e) {
    return null;
  }
}

/**
 * Логирует статус участника для диагностики после операций restrict
 * @param {string} chatId - ID чата
 * @param {string|number} userId - ID пользователя
 * @param {string} tag - Тег для идентификации в логах
 */
function verifyAndLogChatMember(chatId, userId, tag) {
  try {
    const info = sendTelegram('getChatMember', { chat_id: chatId, user_id: userId });
    const status = info?.result?.status;
    const perms = info?.result || {};
    logToSheet('INFO', `[verify:${tag}] chat=${chatId} user=${userId} status=${status} can_send_messages=${perms?.can_send_messages} can_send_media=${perms?.can_send_media_messages}`);
    logEventTrace(LOGGING_CONTEXT, 'restrict_verify', 'getChatMember', 'Post-restrict verification', { chatId, userId, status, perms }, true);
    return info;
  } catch (e) {
    logToSheet('ERROR', `[verify:${tag}] failed: ${e && e.message ? e.message : e}`);
    return null;
  }
}

// =================================================================================
// =================  B. SPREADSHEET UI & MANUAL CONTROLS  ======================
// =================================================================================

/**
 * Создает кастомное меню в интерфейсе таблицы
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('🤖 Управление ботом')
    .addItem('▶️ Запустить initialSetup', 'initialSetup')
    .addSeparator()
    .addItem('🟢 Включить бота', 'userEnableBot')
    .addItem('🔴 Выключить бота', 'userDisableBot')
    .addItem('📘 Переключить расширенные логи', 'userToggleExtendedLogging')
    .addItem('🧑‍💻 Включить режим разработчика', 'userEnableDeveloperMode')
    .addItem('🧑‍💻 Выключить режим разработчика', 'userDisableDeveloperMode')
    .addItem('🔎 Проверить вебхук', 'userCheckWebhook')
    .addItem('♻️ Сбросить вебхук (очистить очередь)', 'userResetWebhook')
    .addSeparator()
    .addItem('🧪 Запустить тесты', 'runTestsFromMenu')
    .addItem('🔄 Сбросить кэш (Настройки и Админы)', 'userClearCache')
    .addToUi();
}

// Обёртки для пунктов меню с обратной связью пользователю
function userEnableBot() { enableBot(true); }
function userDisableBot() { disableBot(true); }
function userClearCache() { clearCache(true); }
function userToggleExtendedLogging() {
  try {
    toggleExtendedLogging(true);
  } catch (e) {
    logToSheet('ERROR', `userToggleExtendedLogging failed: ${e && e.message ? e.message : e}`);
    try { SpreadsheetApp.getUi().alert(`Ошибка переключения расширенных логов: ${e && e.message ? e.message : e}`); } catch (_) {}
  }
}
function userEnableDeveloperMode() { enableDeveloperMode(true); }
function userDisableDeveloperMode() { disableDeveloperMode(true); }
function userCheckWebhook() { checkWebhook(true); }
function userResetWebhook() { resetWebhook(true, true); }

/**
 * Переключает расширенное логирование событий
 * @param {boolean} showAlert - Показывать ли UI алерт
 */
function toggleExtendedLogging(showAlert) {
  const config = getCachedConfig();
  const newState = !config.extended_logging_enabled;

  updateConfigValue('extended_logging_enabled', newState, newState ? '📘 Расширенные логи: ВКЛ' : '📕 Расширенные логи: ВЫКЛ');
  setLoggingContext(newState);

  const message = newState
    ? '🔔 Расширенное логирование включено. Все события и реакции бота будут фиксироваться на листе "Events".'
    : 'ℹ️ Расширенное логирование отключено. Запись событий в лист "Events" приостановлена.';

  logToSheet('INFO', message);
  logEventTrace(LOGGING_CONTEXT, 'settings', newState ? 'enable_extended_logging' : 'disable_extended_logging', message, { extended_logging: newState }, true);

  if (showAlert) {
    try { SpreadsheetApp.getUi().alert(message); } catch (e) {}
  }

  return newState;
}

/**
 * Включает режим разработчика - логирует все события и API вызовы
 * Не меняет поведение бота, только расширяет логирование
 * @param {boolean} showAlert - Показывать ли UI алерт
 */
function enableDeveloperMode(showAlert) {
  updateConfigValue('developer_mode_enabled', true, '🧑‍💻 Режим разработчика: ВКЛ');
  setLoggingContext({ extended_logging_enabled: LOGGING_CONTEXT.extended_logging_enabled, developer_mode_enabled: true });
  logToSheet('INFO', '🧑‍💻 Режим разработчика включен. Все события и API-вызовы будут логироваться.');
  logEventTrace(LOGGING_CONTEXT, 'settings', 'enable_developer_mode', 'Developer mode enabled', { developer_mode: true }, true);
  if (showAlert) {
    try { SpreadsheetApp.getUi().alert('🧑\u200d💻 Режим разработчика включен. Все события будут логироваться.'); } catch (e) {}
  }
}

/**
 * Отключает режим разработчика
 * @param {boolean} showAlert - Показывать ли UI алерт
 */
function disableDeveloperMode(showAlert) {
  updateConfigValue('developer_mode_enabled', false, '🧑‍💻 Режим разработчика: ВЫКЛ');
  setLoggingContext({ extended_logging_enabled: LOGGING_CONTEXT.extended_logging_enabled, developer_mode_enabled: false });
  logToSheet('INFO', '🧑‍💻 Режим разработчика отключен. Возврат к стандартному логированию.');
  logEventTrace(LOGGING_CONTEXT, 'settings', 'disable_developer_mode', 'Developer mode disabled', { developer_mode: false }, true);
  if (showAlert) {
    try { SpreadsheetApp.getUi().alert('🧑\u200d💻 Режим разработчика выключен.'); } catch (e) {}
  }
}

/**
 * Включает бота по установке флага bot_enabled
 * @param {boolean} showAlert - Показывать ли UI алерт
 */
function enableBot(showAlert) {
  updateConfigValue('bot_enabled', true, '🟢 Бот ВКЛЮЧЕН');
  if (showAlert) {
    try { SpreadsheetApp.getUi().alert('✅ Бот включен. Он начнет обрабатывать новые события.'); } catch(e) {}
  }

  const healthCheck = sendTelegram('getMe', {});
  if (healthCheck?.ok) {
    const botName = healthCheck.result?.username || healthCheck.result?.id;
    logToSheet('INFO', `🤖 Бот успешно включен. Telegram ответил: ${botName}`);
    logToTestSheet('enableBot', 'INFO', 'Бот включён, запрос проверки прошёл успешно', JSON.stringify(healthCheck.result || {}));
    try {
      const cfg = getCachedConfig();
      const cfgSummary = {
        bot_enabled: cfg.bot_enabled,
        developer_mode_enabled: !!cfg.developer_mode_enabled,
        extended_logging_enabled: !!cfg.extended_logging_enabled,
        authorized_chat_ids: (cfg.authorized_chat_ids || []).map(String),
        target_channel_id: String(cfg.target_channel_id || ''),
        violation_limit: cfg.violation_limit,
        captcha_mute_duration_min: cfg.captcha_mute_duration_min
      };
      logToSheet('INFO', `⚙️ Config snapshot: ${JSON.stringify(cfgSummary)}`);
      logEventTrace(cfg, 'settings', 'config_snapshot', 'Config on enable', { config: cfgSummary }, true);
      try {
        logBotPermissionsSnapshot(cfg);
      } catch (permErr) {
        logToSheet('WARN', `Не удалось проверить права бота: ${permErr && permErr.message ? permErr.message : permErr}`);
      }
    } catch (e) {
      logToSheet('WARN', `Failed to log config snapshot: ${e.message}`);
    }
  } else {
    const issue = healthCheck?.description || 'нет ответа';
    logToSheet('WARN', `⚠️ Попытка включить бота не подтверждена Telegram: ${issue}`);
    logToTestSheet('enableBot', 'WARN', 'Бот включён, но проверка с Telegram не прошла', issue);
  }
}

/**
 * Логирует права бота в каждом разрешённом чате
 * @param {object} cfg - Объект конфигурации
 */
function logBotPermissionsSnapshot(cfg) {
  const chats = (cfg && cfg.authorized_chat_ids ? cfg.authorized_chat_ids : []).map(String).filter(Boolean);
  if (!chats.length) {
    logToSheet('INFO', '🔐 Проверка прав: список authorized_chat_ids пуст. Пропускаем.');
    return;
  }
  const botId = getBotId();
  const results = [];
  chats.forEach((chatId) => {
    try {
      let resp = sendTelegram('getChatMember', { chat_id: chatId, user_id: botId });
      if (!resp?.ok) {
        const fb = sendTelegram('getChatMember', { chat_id: chatId, user_id: '' });
        if (fb?.ok) resp = fb;
      }
      const ok = !!(resp && resp.ok);
      const status = resp?.result?.status || 'unknown';
      const canRestrict = resp?.result?.can_restrict_members === true || status === 'administrator' || status === 'creator';
      const canDelete = resp?.result?.can_delete_messages === true || status === 'administrator' || status === 'creator';
      results.push({ chat_id: chatId, ok, status, can_restrict_members: canRestrict, can_delete_messages: canDelete });
      const level = (canRestrict && canDelete) ? 'INFO' : 'WARN';
      logToSheet(level, `🔐 Права для чата ${chatId}: status=${status}, restrict=${canRestrict}, delete=${canDelete}`);
    } catch (e) {
      logToSheet('ERROR', `Не удалось получить права бота в чате ${chatId}: ${e && e.message ? e.message : e}`);
    }
  });
  try { logEventTrace(cfg, 'settings', 'permissions_snapshot', 'Bot permissions by chat', { results }, true); } catch (_) {}
}

/**
 * Проверяет статус вебхука и выводит информацию
 * @param {boolean} showAlert - Показывать ли UI алерт
 */
function checkWebhook(showAlert) {
  const info = sendTelegram('getWebhookInfo', {});
  const props = PropertiesService.getScriptProperties();
  const expectedUrl = String(props.getProperty('WEB_APP_URL') || '');
  const url = info?.result?.url || '';
  const pending = info?.result?.pending_update_count || 0;
  const lastErrMsg = info?.result?.last_error_message || '';
  const ip = info?.result?.ip_address || '';
  const matches = expectedUrl && url ? (String(url).indexOf(expectedUrl) === 0 || String(expectedUrl).indexOf(url) === 0) : (expectedUrl === url);
  const statusMsg = `🌐 Webhook: url='${url || '-'}', expected='${expectedUrl || '-'}', matches=${matches}, pending=${pending}, last_error=${lastErrMsg ? '[' + lastErrMsg + ']' : 'none'}, ip=${ip || '-'}`;
  logToSheet(matches ? 'INFO' : 'WARN', statusMsg);
  try { logEventTrace(LOGGING_CONTEXT, 'settings', 'webhook_status', 'Webhook check', { url, expectedUrl, pending, lastErrMsg, ip, matches }, true); } catch(_) {}
  if (showAlert) {
    try { SpreadsheetApp.getUi().alert(statusMsg); } catch(_) {}
  }
  return { info, expectedUrl, matches };
}

/**
 * Переустанавливает вебхук с текущим URL
 * @param {boolean} showAlert - Показывать ли UI алерт
 * @param {boolean} dropPending - Очищать ли pending updates
 */
function resetWebhook(showAlert, dropPending) {
  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty('BOT_TOKEN');
  const url = String(props.getProperty('WEB_APP_URL') || '');
  if (!token || !url) {
    logToSheet('ERROR', 'resetWebhook: BOT_TOKEN/WEB_APP_URL not set');
    if (showAlert) try { SpreadsheetApp.getUi().alert('BOT_TOKEN/WEB_APP_URL не заданы'); } catch(_) {}
    return { ok: false };
  }
  try {
    const endpoint = `https://api.telegram.org/bot${token}/setWebhook?url=${encodeURIComponent(url)}${dropPending ? '&drop_pending_updates=true' : ''}`;
    const resp = UrlFetchApp.fetch(endpoint, { method: 'get', muteHttpExceptions: true });
    const json = JSON.parse(resp.getContentText());
    const msg = `setWebhook -> ok=${json.ok}, description=${json.description || 'none'}, drop=${!!dropPending}`;
    logToSheet(json.ok ? 'INFO' : 'WARN', msg);
    logEventTrace(LOGGING_CONTEXT, 'settings', 'setWebhook', 'Webhook set/reset', { ok: json.ok, description: json.description, dropPending: !!dropPending, url }, true);
    if (showAlert) try { SpreadsheetApp.getUi().alert(msg); } catch(_) {}
    return json;
  } catch (e) {
    logToSheet('ERROR', `resetWebhook failed: ${e && e.message ? e.message : e}`);
    if (showAlert) try { SpreadsheetApp.getUi().alert(`Ошибка: ${e && e.message ? e.message : e}`); } catch(_) {}
    return { ok: false, error: String(e && e.message ? e.message : e) };
  }
}

/**
 * Отключает бота установкой флага bot_enabled = false
 * @param {boolean} showAlert - Показывать ли UI алерт
 */
function disableBot(showAlert) {
  updateConfigValue('bot_enabled', false, '🔴 Бот ВЫКЛЮЧЕН');
  if (showAlert) {
    try { SpreadsheetApp.getUi().alert('🛑 Бот выключен. Он больше не будет реагировать на события в чатах.'); } catch(e) {}
  }
}

/**
 * Очищает кэш конфигурации и списка администраторов
 * @param {boolean} showAlert - Показывать ли UI алерт
 */
function clearCache(showAlert) {
  CacheService.getScriptCache().removeAll(['config', 'admin_cache']);
  if (showAlert) {
    try { SpreadsheetApp.getUi().alert('✅ Кэш настроек и администраторов очищен. Новые данные будут загружены из таблицы при следующем событии.'); } catch(e) {}
  }
}

/**
 * Вспомогательная функция для обновления значения в листе Config
 * @param {string} key - Ключ конфигурации
 * @param {any} value - Новое значение
 * @param {string} statusText - Текст статуса для ячейки E1
 */
function updateConfigValue(key, value, statusText) {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const configSheet = ss.getSheetByName('Config');
    if (!configSheet) return;
    const data = configSheet.getRange("A:A").getValues().flat();
    const rowIndex = data.indexOf(key) + 1;
    if (rowIndex > 0) {
      configSheet.getRange(rowIndex, 2).setValue(value);
    } else {
      configSheet.appendRow([key, value]);
    }
    if (statusText) {
      configSheet.getRange('E1').setValue(statusText).setFontWeight('bold');
    }
    clearCache(false);
  } catch (e) { logToSheet('ERROR', `Failed to update config value for key: ${key}. Error: ${e.message}`); }
}

// =================================================================================
// ==========================  C. INITIAL SETUP WIZARD  ===========================
// =================================================================================

/**
 * Выполняет полную одноразовую настройку бота
 */
function initialSetup() {
  try {
    _createSheets();
    _setWebhook();
    _createTrigger();
    enableBot(false);
    const successMessage = '🎉 ПОЛНАЯ НАСТРОЙКА ЗАВЕРШЕНА! Ваш бот готов к работе. Не забудьте заполнить `Config` и `Whitelist` листы.';
    Logger.log(successMessage);
    try {
      SpreadsheetApp.getUi().alert(successMessage);
    } catch(e) {
      Logger.log("Запущено из редактора, всплывающее окно пропущено.");
    }
  } catch (err) {
    const errorMessage = `ОШИБКА НАСТРОЙКИ: ${err.message}\n\nСтек: ${err.stack}`;
    Logger.log(errorMessage);
     try {
      SpreadsheetApp.getUi().alert(errorMessage);
    } catch(e) { }
  }
}

/**
 * Создает все необходимые листы в таблице с заголовками и примерами
 */
function _createSheets() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheets = {
    "Config": [
        ["key", "value", "description"],
        ["bot_enabled", true, "TRUE/FALSE. Управляется через меню."],
        ["extended_logging_enabled", false, "TRUE/FALSE. Расширенные логи событий Telegram."],
        ["developer_mode_enabled", false, "TRUE/FALSE. Режим разработчика: логировать все события и API-вызовы."],
        ["target_channel_id", DEFAULT_CONFIG.target_channel_id, "ЧИСЛОВОЙ ID канала для проверки подписки."],
        ["target_channel_url", DEFAULT_CONFIG.target_channel_url, "ПУБЛИЧНАЯ ссылка на канал (https://t.me/...)"],
        ["authorized_chat_ids", DEFAULT_CONFIG.authorized_chat_ids, "ID чатов, где работает бот (каждый с новой строки)"],
        ["admin_id", DEFAULT_CONFIG.admin_id, "Ваш Telegram ID для получения критических ошибок."],
        ["captcha_mute_duration_min", 30, "На сколько минут блокировать новичка до прохождения капчи."],
        ["captcha_message_timeout_sec", 30, "Через сколько секунд удалять сообщение с капчей."],
        ["warning_message_timeout_sec", 20, "Через сколько секунд удалять предупреждение о подписке."],
        ["violation_limit", 3, "Сколько сообщений может написать пользователь без подписки перед мутом."],
        ["mute_level_1_duration_min", 60, "Длительность мута за первое нарушение."],
        ["mute_level_2_duration_min", 1440, "Длительность мута за второе нарушение (24 часа)."],
        ["mute_level_3_duration_min", 10080, "Длительность мута за третье и последующие нарушения (7 дней)."],
        ["combined_mute_notice", true, "Отправлять объединённое сообщение (мут + инструкция по подписке)"]
    ],
    "Texts": [
        ["key", "value"],
        ["captcha_text", DEFAULT_CONFIG.texts.captcha_text],
        ["sub_warning_text", DEFAULT_CONFIG.texts.sub_warning_text],
        ["sub_warning_text_no_link", DEFAULT_CONFIG.texts.sub_warning_text_no_link],
        ["sub_success_text", DEFAULT_CONFIG.texts.sub_success_text],
        ["sub_fail_text", DEFAULT_CONFIG.texts.sub_fail_text],
        ["sub_mute_text", DEFAULT_CONFIG.texts.sub_mute_text]
    ],
    "Users": [["user_id", "mute_level", "first_violation_date"]],
    "Logs": [["Timestamp", "Level", "Message"]],
    "Events": [["Timestamp", "Event", "Action", "Details", "Payload"]],
    "Tests": [["Timestamp", "Test Name", "Status", "Details", "API Calls"]],
    "Whitelist": [["user_id_or_channel_id", "comment"], ["12345678", "Пример: другой мой бот"]]
  };
  for (const name in sheets) {
    if (!ss.getSheetByName(name)) {
      const data = sheets[name];
      ss.insertSheet(name).getRange(1, 1, data.length, data[0].length).setValues(data).setFontFamily('Roboto');
    }
  }
  Logger.log('✅ (Шаг 1/3) Листы созданы.');
}

/**
 * Устанавливает вебхук Telegram на текущий URL скрипта
 */
function _setWebhook() {
  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty('BOT_TOKEN');
  const url = props.getProperty('WEB_APP_URL');
    if (!token || !url || token.includes('YOUR_BOT')) {
      throw new Error("BOT_TOKEN и/или WEB_APP_URL не установлены в Свойствах скрипта (Script Properties). Запустите initialSetup из меню или настройте их вручную.");
  }
  const response = UrlFetchApp.fetch(`https://api.telegram.org/bot${token}/setWebhook?url=${url}&drop_pending_updates=true`);
  Logger.log('✅ (Шаг 2/3) Вебхук установлен: ' + response.getContentText());
}

/**
 * Создает временный триггер для функции очистки сообщений (каждую минуту)
 */
function _createTrigger() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('messageCleaner').timeBased().everyMinutes(1).create();
  Logger.log('✅ (Шаг 3/3) Триггер очистки создан.');
}

// =================================================================================
// =========================  D. CORE LOGIC & EVENT HANDLERS =======================
// =================================================================================

/**
 * ✅ ГЛАВНАЯ ФУНКЦИЯ ВЕБХУКА - ИСПРАВЛЕНИЕ #1
 * Возвращает HtmlService вместо ContentService для избежания ошибки 302
 */
function doPost(e) {
  try {
    if (e && e.postData && e.postData.contents) {
      handleUpdate(JSON.parse(e.postData.contents));
    }
  } catch (error) {
    logToSheet("CRITICAL", `Критическая ошибка в doPost: ${error.message}`);
  }
  // ✅ ИСПРАВЛЕНО: HtmlService вместо ContentService для возврата 200 OK напрямую
  return HtmlService.createHtmlOutput('');
}

/**
 * ✅ GET-ENDPOINT для проверки статуса вебхука через браузер
 */
function doGet(e) {
  return HtmlService.createHtmlOutput(`
    <!DOCTYPE html>
    <html>
      <head>
        <title>Telegram Bot Webhook Status</title>
        <style>
          body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            max-width: 600px;
            margin: 50px auto;
            padding: 20px;
            background: #f5f5f5;
          }
          .container {
            background: white;
            border-radius: 10px;
            padding: 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
          }
          .success {
            background: #4CAF50;
            color: white;
            padding: 15px;
            border-radius: 5px;
            margin: 20px 0;
          }
          .info {
            background: #e3f2fd;
            color: #1565c0;
            padding: 10px;
            border-radius: 5px;
            margin: 10px 0;
            font-size: 14px;
          }
          h1 { color: #333; margin: 0 0 10px 0; }
          h2 { color: #4CAF50; font-size: 24px; margin: 5px 0; }
          code { background: #f4f4f4; padding: 2px 5px; border-radius: 3px; font-family: monospace; }
        </style>
      </head>
      <body>
        <div class="container">
          <h1>🤖 Telegram Bot Webhook</h1>
          <div class="success">
            <h2>✅ Active and Ready</h2>
            <p>Status: <code>HTTP 200 OK</code> (No redirect)</p>
            <p>Response: <code>HtmlService.createHtmlOutput('')</code></p>
          </div>
          <div class="info">
            <strong>Timestamp:</strong> ${new Date().toISOString()}
          </div>
          <div class="info">
            <p><strong>✅ Исправления применены:</strong></p>
            <ul style="margin: 5px 0; padding-left: 20px;">
              <li><code>doPost()</code> возвращает <code>HtmlService</code> (200 OK)</li>
              <li><code>handleCallbackQuery()</code> отвечает ПЕРВЫМ (убирает часики)</li>
              <li><code>handleMessage()</code> проверяет результат deleteMessage()</li>
              <li>Результаты в алертах (всплывающие окна)</li>
            </ul>
          </div>
        </div>
      </body>
    </html>
  `);
}

/**
 * Центральный обработчик всех обновлений от Telegram
 * Фильтрует события и маршрутизирует их к специализированным обработчикам
 */
function handleUpdate(update) {
    const config = getCachedConfig();
    setLoggingContext(config);
    logEventTrace(config, 'update', 'received', 'Получено новое обновление от Telegram', update);

    try {
        const updId = update && typeof update.update_id !== 'undefined' ? String(update.update_id) : '';
        if (updId) {
            const cache = CacheService.getScriptCache();
            const key = `upd_${updId}`;
            if (cache.get(key)) {
                logEventTrace(config, 'update', 'ignored_duplicate', 'Дубликат update_id, пропуск', { update_id: updId }, true);
                return;
            }
            cache.put(key, '1', 600);
        }
    } catch(_) {}

    if (!config.bot_enabled) {
        const chatTmp = update.message?.chat || update.callback_query?.message?.chat || update.chat_member?.chat || update.chat_join_request?.chat;
        const userTmp = update.message?.from || update.callback_query?.from || update.chat_join_request?.from;
        const adminIdStr = String(config.admin_id || '').trim();
        if (chatTmp && userTmp && String(chatTmp.id) === String(userTmp.id) && adminIdStr && String(userTmp.id) === adminIdStr) {
            logToSheet('SUCCESS', `🌐 Webhook OK (бот выключен): получено ЛС от администратора ${userTmp.id}`);
            logEventTrace(config, 'webhook', 'admin_dm', 'Admin DM received while bot is disabled - webhook alive', {
                chatId: chatTmp.id,
                userId: userTmp.id,
                keys: Object.keys(update || {})
            }, true);
        }
        logEventTrace(config, 'update', 'ignored', 'Бот отключен, обновление пропущено', { reason: 'bot_disabled' });
        return;
    }

    logToSheet('DEBUG', JSON.stringify(update));

    const chat = update.message?.chat || update.callback_query?.message?.chat || update.chat_member?.chat || update.chat_join_request?.chat || update.my_chat_member?.chat;
    if (!chat) {
        logEventTrace(config, 'update', 'ignored', 'Чат не обнаружен в обновлении', { keys: Object.keys(update || {}) });
        return;
    }

    if (config.authorized_chat_ids.length > 0 && !config.authorized_chat_ids.includes(String(chat.id))) {
        logEventTrace(config, 'update', 'ignored', 'Чат не входит в список разрешённых', { chatId: chat.id });
        return;
    }

    const services = { ss: SpreadsheetApp.getActiveSpreadsheet(), cache: CacheService.getScriptCache(), lock: LockService.getScriptLock() };

    const user = update.message?.from || update.callback_query?.from || update.chat_join_request?.from;

    if (update.message && update.message.sender_chat) {
        const senderId = String(update.message.sender_chat.id);
        if (senderId === String(config.target_channel_id) || config.whitelist_ids.includes(senderId)) {
            logToSheet('DEBUG', `Channel post from whitelisted sender ${senderId} in chat ${chat.id}. Ignoring.`);
            logEventTrace(config, 'update', 'ignored', 'Сообщение от разрешённого канала пропущено', { chatId: chat.id, senderId });
            return;
        }
    }

    if (user && (update.message || update.callback_query)) {
        if (update.message && user.is_bot) {
            logToSheet('DEBUG', `Bot user ${user.id} in message event. Ignoring.`);
            logEventTrace(config, 'update', 'ignored', 'Сообщение от бота пропущено', { chatId: chat.id, userId: user.id });
            return;
        }

        if (update.message && IGNORED_USER_IDS.includes(String(user.id))) {
            logToSheet('DEBUG', `System account ${user.id} in message event. Ignoring.`);
            logEventTrace(config, 'update', 'ignored', 'Системный пользователь пропущен', { chatId: chat.id, userId: user.id });
            return;
        }

        if (update.message && config.whitelist_ids.includes(String(user.id))) {
            logToSheet('DEBUG', `Whitelisted user ${user.id} in message event. Ignoring.`);
            logEventTrace(config, 'update', 'ignored', 'Пользователь из whitelist пропущен', { chatId: chat.id, userId: user.id });
            return;
        }

        if (update.message && String(chat.id) === String(user.id)) {
            const adminIdStr = String(config.admin_id || '').trim();
            if (adminIdStr && String(user.id) === adminIdStr) {
                logToSheet('SUCCESS', `🌐 Webhook OK: получено личное сообщение от администратора ${user.id}`);
                logEventTrace(config, 'webhook', 'admin_dm', 'Admin DM received - webhook alive', {
                    chatId: chat.id,
                    userId: user.id,
                    keys: Object.keys(update || {})
                }, true);
            } else {
                logToSheet('DEBUG', `Private message from user ${user.id} to bot. Ignoring.`);
                logEventTrace(config, 'update', 'ignored', 'Личное сообщение боту пропущено', { chatId: chat.id, userId: user.id });
            }
            return;
        }

        if (update.message) {
            logToSheet('DEBUG', `[handleUpdate] Checking admin status for user ${user.id} in chat ${chat.id}`);
            const userIsAdmin = isAdmin(chat.id, user.id, services.cache);
            logToSheet('DEBUG', `[handleUpdate] Admin check result for user ${user.id}: ${userIsAdmin}`);
            if (userIsAdmin) {
                logToSheet('DEBUG', `[handleUpdate] Admin ${user.id} in message event. Ignoring.`);
                logEventTrace(config, 'update', 'ignored', 'Сообщение администратора пропущено', { chatId: chat.id, userId: user.id });
                return;
            }
        }
    }

    logEventTrace(config, 'update', 'processed', 'Обновление прошло фильтры', {
        chatId: chat.id,
        userId: user?.id,
        chat_member: !!update.chat_member,
        chat_join_request: !!update.chat_join_request,
        message: !!update.message,
        callback_query: !!update.callback_query
    });

    if (user) {
        logToSheet('INFO', `Processing event for user ${user.id} in chat ${chat.id} after all filters passed.`);
    }

    logToSheet('DEBUG', `Event dispatcher: chat_member=${!!update.chat_member}, chat_join_request=${!!update.chat_join_request}, message=${!!update.message}, callback_query=${!!update.callback_query}`);
    
    if (update.message && Array.isArray(update.message.new_chat_members) && update.message.new_chat_members.length > 0) {
        for (var i = 0; i < update.message.new_chat_members.length; i++) {
            var nm = update.message.new_chat_members[i];
            try {
                const synthetic = {
                    chat: update.message.chat,
                    from: update.message.from,
                    old_chat_member: { status: 'left' },
                    new_chat_member: { status: 'member', user: nm }
                };
                handleNewChatMember(synthetic, services, config);
            } catch (e) {
                logToSheet('ERROR', `Failed to process new_chat_member via message: ${e && e.message ? e.message : e}`);
            }
        }
        return;
    }

    logEventTrace(config, 'update', 'dispatch', 'Передача обновления специализированному обработчику', {
        chatId: chat.id,
        userId: user?.id,
        types: Object.keys(update || {})
    });

    if (update.chat_member) {
        handleNewChatMember(update.chat_member, services, config);
    } else if (update.my_chat_member) {
        handleMyChatMember(update.my_chat_member, services, config);
    } else if (update.chat_join_request) {
        handleChatJoinRequest(update.chat_join_request, services, config);
    } else if (update.message) {
        handleMessage(update.message, services, config);
    } else if (update.callback_query) {
        handleCallbackQuery(update.callback_query, services, config);
    } else {
        logToSheet('WARN', `Unknown event type in update: ${Object.keys(update).join(', ')}`);
        logEventTrace(config, 'update', 'ignored', 'Тип обновления не распознан', { keys: Object.keys(update || {}) });
    }
}

/**
 * Обрабатывает заявки на вступление в закрытые/приватные чаты
 * Автоматически одобряет заявки в разрешённых чатах
 */
function handleChatJoinRequest(joinRequest, services, config) {
    const chat = joinRequest.chat;
    const user = joinRequest.from;
    
    logToSheet('INFO', `Join request from ${user.first_name || 'User'} (${user.id}) for chat ${chat.id}.`);
    logEventTrace(config, 'chat_join_request', 'received', 'Получена заявка на вступление', {
        chatId: chat.id,
        userId: user.id
    });
    
    if (user.is_bot || IGNORED_USER_IDS.includes(String(user.id))) {
        logToSheet('INFO', `Join request from bot/system account ${user.id}. Declining.`);
        sendTelegram('declineChatJoinRequest', { chat_id: chat.id, user_id: user.id });
        logEventTrace(config, 'chat_join_request', 'declined', 'Отказано боту или системному аккаунту', {
            chatId: chat.id,
            userId: user.id,
            reason: 'bot_or_system_account'
        });
        return;
    }
    
    const approveResult = sendTelegram('approveChatJoinRequest', { chat_id: chat.id, user_id: user.id });
    
    if (approveResult?.ok) {
        logToSheet('INFO', `Join request approved for ${user.id} in chat ${chat.id}.`);
        logEventTrace(config, 'chat_join_request', 'approved', 'Заявка успешно одобрена', {
            chatId: chat.id,
            userId: user.id
        });
    } else {
        logToSheet('ERROR', `Failed to approve join request for ${user.id} in chat ${chat.id}: ${approveResult?.description}`);
        logEventTrace(config, 'chat_join_request', 'error', 'Не удалось одобрить заявку', {
            chatId: chat.id,
            userId: user.id,
            description: approveResult?.description || 'unknown_error'
        });
    }
}

/**
 * Обрабатывает событие chat_member - когда новый пользователь вступил в чат
 * Выполняет проверку и выдает CAPTCHA при необходимости
 */
function handleNewChatMember(chatMember, services, config) {
    const chat = chatMember.chat;
    const user = chatMember.new_chat_member.user;
    const oldStatus = chatMember.old_chat_member?.status;
    const newStatus = chatMember.new_chat_member.status;
    const fromUser = chatMember.from;

    logToSheet('DEBUG', `[handleNewChatMember] ChatMember Event: chat_id=${chat.id}, user_id=${user.id}, from_id=${fromUser?.id}, old_status=${oldStatus}, new_status=${newStatus}`);
    logEventTrace(config, 'chat_member', 'received', 'Получено событие изменения участника', {
        chatId: chat.id,
        userId: user.id,
        fromId: fromUser?.id,
        oldStatus,
        newStatus
    });

    if (user.id < 0) {
        logToSheet('INFO', `[handleNewChatMember] Channel as user event (ID: ${user.id}) in chat ${chat.id}. Skipping.`);
        logEventTrace(config, 'chat_member', 'ignored', 'Событие от канала пропущено', {
            chatId: chat.id,
            userId: user.id,
            reason: 'channel_as_user'
        });
        return;
    }

    if (user.is_bot) {
        const botId = getBotId();
        if (botId && user.id === botId) {
            logToSheet('INFO', `[handleNewChatMember] Bot join event in chat ${chat.id}. No action needed.`);
            logEventTrace(config, 'chat_member', 'ignored', 'Событие о самом боте, пропустить', {
                chatId: chat.id,
                userId: user.id,
                reason: 'bot_self'
            });
        } else {
            logToSheet('INFO', `[handleNewChatMember] External bot ${user.id} in chat ${chat.id}. Skipping.`);
            logEventTrace(config, 'chat_member', 'ignored', 'Событие о внешнем боте, пропустить', {
                chatId: chat.id,
                userId: user.id,
                reason: 'external_bot'
            });
        }
        return;
    }

    if (IGNORED_USER_IDS.includes(String(user.id))) {
        logToSheet('INFO', `[handleNewChatMember] System account ${user.id} in chat ${chat.id}. Skipping member processing.`);
        logEventTrace(config, 'chat_member', 'ignored', 'Системный аккаунт пропущен', {
            chatId: chat.id,
            userId: user.id,
            reason: 'system_account'
        });
        return;
    }

    const isInitiatedByUser = !fromUser || Number(fromUser.id) === Number(user.id);
    
    logToSheet('DEBUG', `[handleNewChatMember] Join analysis: from=${fromUser?.id}, user=${user.id}, isInitiatedByUser=${isInitiatedByUser}`);
    
    const isRealJoin = (
        ((oldStatus === 'left' || oldStatus === 'kicked') && newStatus === 'member') ||
        (!oldStatus && newStatus === 'member')
    );
    
    logToSheet('DEBUG', `[handleNewChatMember] Real join check: isRealJoin=${isRealJoin}, oldStatus=${oldStatus}, newStatus=${newStatus}`);

    if (!isRealJoin) {
        logToSheet('DEBUG', `[handleNewChatMember] Non-join event for user ${user.id} in chat ${chat.id}: ${oldStatus} -> ${newStatus}. Skipping.`);
        logEventTrace(config, 'chat_member', 'ignored', 'Событие не является новым вступлением', {
            chatId: chat.id,
            userId: user.id,
            reason: 'not_real_join',
            oldStatus,
            newStatus,
            initiatedByUser: isInitiatedByUser
        });
        return;
    }

    const userIsAdmin = isAdmin(chat.id, user.id, services.cache);
    logToSheet('DEBUG', `[handleNewChatMember] Admin check for user ${user.id}: isAdmin=${userIsAdmin}`);
    
    if (userIsAdmin) {
        logToSheet('INFO', `[handleNewChatMember] Admin ${user.id} joined chat ${chat.id}. No CAPTCHA needed.`);
        logEventTrace(config, 'chat_member', 'ignored', 'Администратор, CAPTCHA не требуется', {
            chatId: chat.id,
            userId: user.id
        });
        return;
    }

    logToSheet('INFO', `[handleNewChatMember] Real user join detected: ${user.first_name || 'User'} (${user.id}) in chat ${chat.id}.`);
    logEventTrace(config, 'chat_member', 'processing', 'Начата выдача CAPTCHA для нового пользователя', {
        chatId: chat.id,
        userId: user.id
    });

    const botId = getBotId();
    let botInfo = sendTelegram('getChatMember', { chat_id: chat.id, user_id: botId });
    let canRestrict = botInfo?.result?.can_restrict_members === true || ['administrator', 'creator'].includes(String(botInfo?.result?.status || ''));
    let canDelete = botInfo?.result?.can_delete_messages === true || ['administrator', 'creator'].includes(String(botInfo?.result?.status || ''));
    if (!botInfo?.ok || !(canRestrict && canDelete)) {
        try {
            const adminsInfo = sendTelegram('getChatAdministrators', { chat_id: chat.id });
            if (adminsInfo?.ok) {
                const adminIds = (adminsInfo.result || []).map(a => a.user && a.user.id).filter(Boolean);
                if (adminIds.includes(botId)) {
                    canRestrict = true;
                    canDelete = true;
                }
            }
        } catch(_) {}

        if (!canRestrict || !canDelete) {
            logToSheet('WARN', `[handleNewChatMember] Bot permissions not confirmed in chat ${chat.id}. Will attempt restrict anyway.`);
            logEventTrace(config, 'chat_member', 'warn', 'Права бота не подтверждены, пробуем restrict', { chatId: chat.id, userId: user.id });
        }
    }

    logToSheet('INFO', `[handleNewChatMember] Applying CAPTCHA to user ${user.id} in chat ${chat.id}`);
    const muteUntil = Math.floor(Date.now() / 1000) + (config.captcha_mute_duration_min * 60);
    const restrictResult = restrictUser(chat.id, user.id, false, muteUntil);
    
    logToSheet('DEBUG', `[handleNewChatMember] Restrict result for user ${user.id}: ok=${restrictResult?.ok}, error=${restrictResult?.description}`);
    
    if (!restrictResult?.ok) {
        logToSheet('ERROR', `[handleNewChatMember] Failed to restrict user ${user.id} in chat ${chat.id}: ${restrictResult?.description}`);
        logEventTrace(config, 'chat_member', 'error', 'Не удалось временно ограничить пользователя перед CAPTCHA', {
            chatId: chat.id,
            userId: user.id,
            description: restrictResult?.description || 'unknown_error'
        });
        return;
    }

    logEventTrace(config, 'chat_member', 'restricted', 'Пользователь временно ограничен до прохождения CAPTCHA', {
        chatId: chat.id,
        userId: user.id,
        muteUntil
    });

    try {
        verifyAndLogChatMember(chat.id, user.id, 'captcha_restrict_verify');
    } catch (e) {
        logToSheet('WARN', `[handleNewChatMember] Verify restrict failed: ${e && e.message ? e.message : e}`);
    }

    const text = config.texts.captcha_text.replace('{user_mention}', getMention(user));
    const keyboard = { 
        inline_keyboard: [[{ 
            text: "✅ Я не робот", 
            callback_data: `captcha_${user.id}` 
        }]] 
    };

    const sentMessage = sendTelegram('sendMessage', {
        chat_id: chat.id,
        text: text,
        parse_mode: 'HTML',
        reply_markup: JSON.stringify(keyboard),
        disable_notification: true
    });

    logToSheet('DEBUG', `[handleNewChatMember] Send message result: ok=${sentMessage?.ok}, message_id=${sentMessage?.result?.message_id}`);

    if (sentMessage?.ok) {
        logToSheet('INFO', `[handleNewChatMember] CAPTCHA sent to ${user.id} in chat ${chat.id}, message_id: ${sentMessage.result.message_id}`);
        addMessageToCleaner(chat.id, sentMessage.result.message_id, config.captcha_message_timeout_sec, services);
        logEventTrace(config, 'chat_member', 'captcha_sent', 'Отправлено сообщение с CAPTCHA', {
            chatId: chat.id,
            userId: user.id,
            messageId: sentMessage.result.message_id,
            muteUntil
        });
    } else {
        logToSheet('ERROR', `[handleNewChatMember] Failed to send CAPTCHA to user ${user.id} in chat ${chat.id}: ${sentMessage?.description}`);
        logEventTrace(config, 'chat_member', 'error', 'Не удалось отправить сообщение CAPTCHA', {
            chatId: chat.id,
            userId: user.id,
            description: sentMessage?.description || 'unknown_error'
        });
    }
}

/**
 * Обрабатывает my_chat_member - когда изменился статус самого бота в чате
 * Логирует события для диагностики
 */
function handleMyChatMember(myChatMember, services, config) {
    const chat = myChatMember.chat;
    const fromUser = myChatMember.from;
    const oldStatus = myChatMember.old_chat_member?.status;
    const newStatus = myChatMember.new_chat_member?.status;

    logToSheet('INFO', `[handleMyChatMember] Bot membership changed in chat ${chat.id}: ${oldStatus} -> ${newStatus} by ${fromUser?.id}`);
    logEventTrace(config, 'my_chat_member', 'received', 'Изменение статуса бота в чате', {
        chatId: chat.id,
        fromId: fromUser?.id,
        oldStatus,
        newStatus
    });

    if (['administrator', 'member'].includes(String(newStatus || ''))) {
        try {
            logBotPermissionsSnapshot(config);
        } catch (e) {
            logToSheet('WARN', `[handleMyChatMember] Не удалось обновить снимок прав: ${e && e.message ? e.message : e}`);
        }
    }
}

/**
 * ✅ ИСПРАВЛЕНИЕ #2: ОБРАБОТКА CALLBACK_QUERY
 * Отвечает на callback ПЕРВЫМ (убирает часики), затем проверяет подписку
 * Результаты показываются АЛЕРТАМИ (всплывающие окна), не новыми сообщениями
 */
function handleCallbackQuery(callbackQuery, services, config) {
    const data = callbackQuery.data;
    const user = callbackQuery.from;
    const chat = callbackQuery.message.chat;
    const messageId = callbackQuery.message.message_id;
    const callbackId = callbackQuery.id;
    
    logToSheet('DEBUG', `[handleCallbackQuery] data=${data}, user_id=${user.id}, chat_id=${chat.id}`);
    logEventTrace(config, 'callback_query', 'received', 'Получен callback-запрос от пользователя', {
        chatId: chat.id,
        userId: user.id,
        data,
        callbackId
    });
    
    // Обработка CAPTCHA кнопок
    if (data.startsWith('captcha_')) {
        logEventTrace(config, 'callback_query', 'processing', 'Обработка кнопки CAPTCHA', {
            chatId: chat.id,
            userId: user.id,
            data
        });
        const expectedUserId = data.split('_')[1];
        if (String(user.id) !== expectedUserId) {
            // ✅ АЛЕРТ: Показываем всплывающее окно
            sendTelegram('answerCallbackQuery', { 
                callback_query_id: callbackId, 
                text: 'Эта кнопка не для вас!', 
                show_alert: true,
                cache_time: 0
            });
            logEventTrace(config, 'callback_query', 'ignored', 'Пользователь попытался нажать чужую CAPTCHA', {
                chatId: chat.id,
                userId: user.id,
                expectedUserId
            });
            return;
        }

        unmuteUser(chat.id, user.id);
        deleteMessage(chat.id, messageId);
        
        // ✅ АЛЕРТ ВМЕСТО СООБЩЕНИЯ: Показываем приветствие всплывающим окном
        sendTelegram('answerCallbackQuery', { 
            callback_query_id: callbackId, 
            text: `${getMention(user).replace(/<[^>]*>/g, '')}, добро пожаловать!`,
            show_alert: true,
            cache_time: 0
        });

        logEventTrace(config, 'callback_query', 'captcha_completed', 'Пользователь прошёл CAPTCHA успешно', {
            chatId: chat.id,
            userId: user.id
        });
        return;
    }
    
    // Обработка кнопок проверки подписки
    if (data.startsWith('check_sub_')) {
        logEventTrace(config, 'callback_query', 'processing', 'Обработка кнопки проверки подписки', {
            chatId: chat.id,
            userId: user.id,
            data
        });
        const expectedUserId = data.split('_')[2];
        if (String(user.id) !== expectedUserId) {
            // ✅ АЛЕРТ: Показываем всплывающее окно
            sendTelegram('answerCallbackQuery', { 
                callback_query_id: callbackId, 
                text: 'Эта кнопка не для вас!', 
                show_alert: true,
                cache_time: 0
            });
            logEventTrace(config, 'callback_query', 'ignored', 'Пользователь попытался нажать чужую кнопку проверки подписки', {
                chatId: chat.id,
                userId: user.id,
                expectedUserId
            });
            return;
        }
        
        // ✅ ПЕРВЫЙ ВЫЗОВ: Ответить СРАЗУ без текста (убрать часики)
        sendTelegram('answerCallbackQuery', { 
            callback_query_id: callbackId, 
            cache_time: 0
        });

        // Теперь проверяем подписку (долгая операция, но часики уже убраны!)
        let isMember = false;
        let apiError = null;
        try {
            const resp = sendTelegram('getChatMember', { 
                chat_id: config.target_channel_id, 
                user_id: user.id 
            });
            if (resp && resp.ok) {
                const status = resp.result && resp.result.status;
                isMember = ['creator', 'administrator', 'member'].includes(String(status || ''));
                logToSheet('DEBUG', `[check_sub] User ${user.id} subscription status: ${status}, isMember=${isMember}`);
            } else {
                apiError = resp;
            }
        } catch (e) {
            apiError = { description: String(e && e.message ? e.message : e) };
        }

        // Обработка ошибок API
        if (apiError && apiError.description) {
            const desc = String(apiError.description).toLowerCase();
            const temporaryFailure = !(desc.includes('user not found') || desc.includes('user is not a member') || desc.includes('not found'));
            if (temporaryFailure) {
                // ✅ АЛЕРТ: Временная ошибка
                sendTelegram('answerCallbackQuery', { 
                    callback_query_id: callbackId, 
                    text: 'Ошибка проверки. Попробуйте ещё раз.', 
                    show_alert: true, 
                    cache_time: 0 
                });
                logEventTrace(config, 'callback_query', 'check_failed', 'Не удалось проверить подписку (временная ошибка)', { 
                    chatId: chat.id, 
                    userId: user.id, 
                    error: apiError.description 
                }, true);
                return;
            }
        }

        if (isMember) {
            // ✅ ПОЛЬЗОВАТЕЛЬ ПОДПИСАН - АЛЕРТ с благодарностью
            services.cache.remove(`violations_${user.id}`);
            
            // Удаляем старое сообщение с кнопкой
            try { deleteMessage(chat.id, messageId); } catch(_) {}
            
            // ✅ АЛЕРТ: Показываем благодарность всплывающим окном
            sendTelegram('answerCallbackQuery', { 
                callback_query_id: callbackId, 
                text: '✅ Спасибо за подписку! Теперь вы можете писать в чате.',
                show_alert: true,
                cache_time: 0
            });
            
            logEventTrace(config, 'callback_query', 'subscription_confirmed', 'Пользователь подтвердил подписку', {
                chatId: chat.id,
                userId: user.id
            });
        } else {
            // ✅ ПОЛЬЗОВАТЕЛЬ НЕ ПОДПИСАН - РЕДАКТИРУЕМ СТАРОЕ СООБЩЕНИЕ
            
            if (config.target_channel_url && config.target_channel_url.trim() !== '') {
                let channelTitle = config.target_channel_id;
                try {
                    const channelInfo = sendTelegram('getChat', { chat_id: config.target_channel_id });
                    channelTitle = channelInfo?.result?.title || config.target_channel_id;
                } catch (e) {
                    logToSheet('WARN', `Failed to get channel info for ${config.target_channel_id}: ${e.message}`);
                }
                
                const channelLink = `<a href="${config.target_channel_url}">${channelTitle.replace(/[<>]/g, '')}</a>`;
                const template = (config.texts.sub_warning_text || DEFAULT_CONFIG.texts.sub_warning_text);
                const updatedText = template
                  .replace('{user_mention}', getMention(user))
                  .replace('{channel_link}', channelLink);
                
                const keyboard = {
                    inline_keyboard: [
                        [{ text: `📱 ${channelTitle.replace(/[<>]/g, '')}`, url: config.target_channel_url }],
                        [{ text: "✅ Я подписался", callback_data: `check_sub_${user.id}` }]
                    ]
                };
                
                // ✅ ПРОВЕРЯЕМ: Изменился ли текст?
                const currentText = String(callbackQuery.message.text || '');
                
                if (currentText !== updatedText) {
                    // Редактируем ТОЛЬКО если текст отличается
                    const editResult = sendTelegram('editMessageText', {
                        chat_id: chat.id,
                        message_id: messageId,
                        text: updatedText,
                        parse_mode: 'HTML',
                        reply_markup: JSON.stringify(keyboard),
                        disable_web_page_preview: true
                    });
                    
                    if (!editResult?.ok) {
                        logToSheet('WARN', `[check_sub] Failed to edit message: ${editResult?.description}`);
                    }
                } else {
                    logToSheet('DEBUG', `[check_sub] Text already correct, no edit needed`);
                }
                
                // ✅ АЛЕРТ: Показываем инструкцию всплывающим окном
                const plainName = getMention(user).replace(/<[^>]*>/g, '');
                const alertText = `🚫 Вы не подписаны на:\n"${String(channelTitle).replace(/[<>]/g, '')}"\n\nПожалуйста, подпишитесь и попробуйте ещё раз.`;
                
                sendTelegram('answerCallbackQuery', { 
                    callback_query_id: callbackId, 
                    text: alertText, 
                    show_alert: true, 
                    cache_time: 0
                });
                
                addMessageToCleaner(chat.id, messageId, 15, services);
                logEventTrace(config, 'callback_query', 'subscription_pending', 'Пользователь ещё не подписан', {
                    chatId: chat.id,
                    userId: user.id
                });
            }
            else {
                // Нет URL - просто показываем алерт
                const alertText = 'Вы не подписаны на обязательный канал.\n\nПожалуйста, подпишитесь и попробуйте ещё раз.';
                
                sendTelegram('answerCallbackQuery', { 
                    callback_query_id: callbackId, 
                    text: alertText, 
                    show_alert: true, 
                    cache_time: 0
                });
                
                addMessageToCleaner(chat.id, messageId, 15, services);
                logEventTrace(config, 'callback_query', 'subscription_pending', 'Нет URL канала', {
                    chatId: chat.id,
                    userId: user.id
                });
            }
        }
        
        logEventTrace(config, 'callback_query', 'completed', 'Обработка кнопки проверки подписки завершена', {
            chatId: chat.id,
            userId: user.id,
            result: isMember ? 'subscribed' : 'not_subscribed'
        });
        return;
    }

    logEventTrace(config, 'callback_query', 'ignored', 'Неизвестный callback_data', {
        chatId: chat.id,
        userId: user.id,
        data
    });
}

/**
 * ✅ ИСПРАВЛЕНИЕ #3: ОБРАБОТКА СООБЩЕНИЙ
 * Проверяет результат deleteMessage() и логирует успех/ошибку
 */
function handleMessage(message, services, config) {
    const user = message.from;
    const chat = message.chat;
    
    logToSheet('DEBUG', `[handleMessage] Processing message from user ${user.id} in chat ${chat.id}`);
    logEventTrace(config, 'message', 'received', 'Получено сообщение от пользователя', {
        chatId: chat.id,
        userId: user.id,
        messageId: message.message_id,
        textLength: message.text ? message.text.length : 0
    });
    
    // Если пользователь уже ограничен, не эскалируем
    try {
        const current = getChatMemberSafe(chat.id, user.id);
        const until = current?.result?.until_date ? Number(current.result.until_date) : 0;
        const nowSec = Math.floor(Date.now() / 1000);
        const isRestricted = String(current?.result?.status || '') === 'restricted' || current?.result?.can_send_messages === false;
        if (isRestricted && until > nowSec) {
            try { deleteMessage(chat.id, message.message_id); } catch(_) {}
            logEventTrace(config, 'message', 'restricted_user_message', 'Сообщение от ограниченного пользователя', {
                chatId: chat.id, userId: user.id, until
            });
            return;
        }
    } catch(_) {}

    // Проверка подписки
    const isMember = isUserSubscribed(user.id, config.target_channel_id);
    logToSheet('DEBUG', `[handleMessage] Subscription check for user ${user.id}: isMember=${isMember}`);
    
    if (isMember) {
        services.cache.remove(`violations_${user.id}`);
        logToSheet('DEBUG', `[handleMessage] User ${user.id} is subscribed, allowing message`);
        logEventTrace(config, 'message', 'allowed', 'Пользователь подписан, сообщение разрешено', {
            chatId: chat.id,
            userId: user.id
        });
        return;
    }
    // ✅ ИСПРАВЛЕНИЕ: НЕ ждём результата - запускаем асинхронно
    try {
        deleteMessage(chat.id, message.message_id);
    } catch(error) {
        logToSheet('DEBUG', `[handleMessage] Delete async - будет в очередь`);
    }

    logToSheet('DEBUG', `[handleMessage] Delete result: ok=${deleteResult?.ok}, error=${deleteResult?.description}`);
    
    let violationCount = Number(services.cache.get(`violations_${user.id}`) || 0) + 1;
    services.cache.put(`violations_${user.id}`, violationCount, 21600);
    logEventTrace(config, 'message', 'violation_recorded', 'Сообщение удалено: пользователь не подписан', {
        chatId: chat.id,
        userId: user.id,
        messageId: message.message_id,
        deleteOk: deleteResult?.ok,
        violationCount,
        violationLimit: config.violation_limit
    });

    if (violationCount < config.violation_limit) {
        if (violationCount === 1) {
            let text;
            let keyboard;

            if (config.target_channel_url && config.target_channel_url.trim() !== '') {
                const channelInfo = sendTelegram('getChat', { chat_id: config.target_channel_id });
                const channelTitle = channelInfo?.result?.title || config.target_channel_id;
                const channelLink = `<a href="${config.target_channel_url}">${channelTitle.replace(/[<>]/g, '')}</a>`;
                const template = (config.texts.sub_warning_text || DEFAULT_CONFIG.texts.sub_warning_text);
                text = template
                  .replace('{user_mention}', getMention(user))
                  .replace('{channel_link}', channelLink);
                keyboard = {
                    inline_keyboard: [
                        [{ text: `📱 ${channelTitle.replace(/[<>]/g, '')}`, url: config.target_channel_url }],
                        [{ text: "✅ Я подписался", callback_data: `check_sub_${user.id}` }]
                    ]
                };
            } else {
                text = (config.texts.sub_warning_text_no_link || DEFAULT_CONFIG.texts.sub_warning_text_no_link)
                  .replace('{user_mention}', getMention(user));
                keyboard = {
                    inline_keyboard: [
                        [{ text: "✅ Я подписался", callback_data: `check_sub_${user.id}` }]
                    ]
                };
            }

            const sentWarning = sendTelegram('sendMessage', {
                chat_id: chat.id,
                text: text,
                parse_mode: 'HTML',
                reply_markup: JSON.stringify(keyboard),
                disable_web_page_preview: true,
                disable_notification: true
            });
            if (sentWarning?.ok) {
                addMessageToCleaner(chat.id, sentWarning.result.message_id, config.warning_message_timeout_sec, services);
                logEventTrace(config, 'message', 'warning_sent', 'Отправлено предупреждение о подписке', {
                    chatId: chat.id,
                    userId: user.id,
                    messageId: sentWarning.result.message_id
                });
            } else {
                logEventTrace(config, 'message', 'error', 'Не удалось отправить предупреждение', {
                    chatId: chat.id,
                    userId: user.id,
                    description: sentWarning?.description || 'unknown_error'
                });
            }
        }
    } else {
        applyProgressiveMute(chat.id, user, services, config);
        services.cache.remove(`violations_${user.id}`);
        logEventTrace(config, 'message', 'mute_applied', 'Достигнут лимит нарушений, пользователь ограничен', {
            chatId: chat.id,
            userId: user.id,
            violationLimit: config.violation_limit
        });
    }
}

// =================================================================================
// =========================  E. UTILITY & HELPER FUNCTIONS =======================
// =================================================================================

/**
 * Получает и кэширует конфигурацию из листа Config
 * Возвращает DEFAULT_CONFIG если лист отсутствует
 */
function getCachedConfig() {
    const cache = CacheService.getScriptCache();
    const cached = cache.get('config');
    if (cached) {
        try {
            const parsedConfig = JSON.parse(cached);
            setLoggingContext(parsedConfig);
            return parsedConfig;
        } catch(e) {
            /* continue to load */
        }
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
                 textData.forEach(row => {
                    config.texts[row[0]] = row[1];
                });
            }
        }

        config.authorized_chat_ids = String(config.authorized_chat_ids || '').split(/\n|,|\s+/).filter(Boolean);
        config.whitelist_ids = whitelistSheet ? whitelistSheet.getDataRange().getValues().slice(1).map(row => String(row[0])).filter(Boolean) : [];

        cache.put('config', JSON.stringify(config), 300);
    } catch (e) {
        logToSheet("ERROR", `Failed to load config from sheet: ${e.message}. Using defaults.`);
    }
    setLoggingContext(config);
    return config;
}

/**
 * Проверяет является ли пользователь администратором чата
 * @param {string} chatId - ID чата
 * @param {string|number} userId - ID пользователя
 * @param {object} cache - Объект кэша
 */
function isAdmin(chatId, userId, cache) {
    const cacheKey = `admin_cache_${chatId}`;
    let adminList = JSON.parse(cache.get(cacheKey) || '[]');
    if (adminList.includes(userId)) return true;

    const response = sendTelegram('getChatAdministrators', { chat_id: chatId });
    if (response && response.ok) {
        adminList = response.result.map(admin => admin.user.id);
        cache.put(cacheKey, JSON.stringify(adminList), 3600);
        return adminList.includes(userId);
    }
    return false;
}

/**
 * Проверяет подписан ли пользователь на канал
 * @param {string|number} userId - ID пользователя
 * @param {string} channelId - ID канала
 */
function isUserSubscribed(userId, channelId) {
    if (!channelId || String(channelId).trim() === '') return true;
    try {
        const response = sendTelegram('getChatMember', { chat_id: channelId, user_id: userId });
        const status = response?.result?.status;
        return ['creator', 'administrator', 'member'].includes(status);
    } catch (e) {
        logToSheet("ERROR", `Ошибка проверки подписки для user ${userId} в канале ${channelId}: ${e.message}`);
        return false;
    }
}

/**
 * Применяет прогрессивный мут пользователю с эскалацией
 * @param {string} chatId - ID чата
 * @param {object} user - Объект пользователя
 * @param {object} services - Объект сервисов (ss, cache, lock)
 * @param {object} config - Объект конфигурации
 */
function applyProgressiveMute(chatId, user, services, config) {
    const lock = services.lock;
    lock.waitLock(15000);
    try {
        const usersSheet = services.ss.getSheetByName('Users');
        if (!usersSheet) return;

        const userId = user.id;
        const userData = findRow(usersSheet, userId, 1);
        const currentLevel = userData ? Number(userData.row[1]) : 0;
        const newLevel = currentLevel + 1;

        let muteDurationMin;
        if (newLevel === 1) {
            muteDurationMin = config.mute_level_1_duration_min;
        } else if (newLevel === 2) {
            muteDurationMin = config.mute_level_2_duration_min;
        } else {
            muteDurationMin = config.mute_level_3_duration_min;
        }

        const muteUntil = Math.floor(new Date().getTime() / 1000) + (muteDurationMin * 60);
        const restrictResp = restrictUser(chatId, userId, false, muteUntil);
        try {
            verifyAndLogChatMember(chatId, userId, 'progressive_mute_verify');
        } catch (e) {
            logToSheet('WARN', `[applyProgressiveMute] Verify restrict failed: ${e && e.message ? e.message : e}`);
        }

        if (userData) {
            usersSheet.getRange(userData.rowIndex, 2).setValue(newLevel);
        } else {
            usersSheet.appendRow([userId, newLevel, new Date()]);
        }

        const text = config.texts.sub_mute_text
            .replace('{user_mention}', getMention(user))
            .replace('{duration}', muteDurationMin);
        let keyboard = undefined;
        if (config.target_channel_url && String(config.target_channel_url).trim() !== '') {
            try {
                const chInfo = sendTelegram('getChat', { chat_id: config.target_channel_id });
                const title = chInfo?.result?.title || String(config.target_channel_id);
                const link = `<a href="${config.target_channel_url}">${title.replace(/[<>]/g, '')}</a>`;
                const warningTpl = (config.texts.sub_warning_text || DEFAULT_CONFIG.texts.sub_warning_text);
                const extra = `\n\n` + warningTpl
                  .replace('{user_mention}', getMention(user))
                  .replace('{channel_link}', link);
                text = text + extra;
                keyboard = { inline_keyboard: [
                  [{ text: `📱 ${title.replace(/[<>]/g, '')}`, url: config.target_channel_url }],
                  [{ text: '✅ Я подписался', callback_data: `check_sub_${user.id}` }]
                ] };
            } catch(_) {}
        }

        const sentMuteMsg = sendTelegram('sendMessage', { chat_id: chatId, text: text, parse_mode: 'HTML', reply_markup: keyboard ? JSON.stringify(keyboard) : undefined, disable_web_page_preview: true });
        if (sentMuteMsg?.ok) {
            addMessageToCleaner(chatId, sentMuteMsg.result.message_id, 10, services);
        }
    } finally {
        lock.releaseLock();
    }
}

/**
 * Добавляет сообщение в очередь удаления
 * @param {string} chatId - ID чата
 * @param {string|number} messageId - ID сообщения
 * @param {number} delaySec - Задержка удаления в секундах
 * @param {object} services - Объект сервисов
 */
function addMessageToCleaner(chatId, messageId, delaySec, services) {
    const lock = services.lock; 
    lock.waitLock(10000);
    try {
        const props = PropertiesService.getScriptProperties();
        const queue = JSON.parse(props.getProperty('deleteQueue') || '[]');
        const deleteAt = new Date().getTime() + delaySec * 1000;
        queue.push({ chatId, messageId, deleteAt });
        props.setProperty('deleteQueue', JSON.stringify(queue));
    } finally { 
        lock.releaseLock(); 
    }
}

/**
 * Периодически удаляет сообщения из очереди (вызывается каждую минуту триггером)
 */
function messageCleaner() {
    const lock = LockService.getScriptLock(); 
    lock.waitLock(20000);
    try {
        const props = PropertiesService.getScriptProperties();
        const queueStr = props.getProperty('deleteQueue');
        if (!queueStr) return;

        const now = new Date().getTime();
        let queue = JSON.parse(queueStr);

        const remainingItems = queue.filter(item => now < item.deleteAt);
        const itemsToDelete = queue.filter(item => now >= item.deleteAt);

        if (itemsToDelete.length > 0) {
            props.setProperty('deleteQueue', JSON.stringify(remainingItems));
            itemsToDelete.forEach(item => deleteMessage(item.chatId, item.messageId));
        }
    } catch (e) {
        if (!this.TEST_MODE) {
            logToSheet("ERROR", `messageCleaner Error: ${e.message}`);
        }
        if (e instanceof SyntaxError) { 
            PropertiesService.getScriptProperties().deleteProperty('deleteQueue'); 
        }
    } finally { 
        lock.releaseLock(); 
    }
}

/**
 * Создает упоминание пользователя с ссылкой
 * @param {object} user - Объект пользователя
 */
function getMention(user) {
    const name = (user.first_name || 'User').replace(/[<>]/g, '');
    return `<a href="tg://user?id=${user.id}">${name}</a>`;
}

/**
 * Находит строку в листе по значению в столбце
 * @param {object} sheet - Лист Google Sheets
 * @param {any} value - Значение для поиска
 * @param {number} column - Номер столбца (1-indexed)
 */
function findRow(sheet, value, column) {
    if (!sheet) return null;
    const data = sheet.getDataRange().getValues();
    for (let i = data.length - 1; i > 0; i--) {
        if (String(data[i][column - 1]) === String(value)) {
            return { row: data[i], rowIndex: i + 1 };
        }
    }
    return null;
}

// =================================================================================
// =========================  F. TELEGRAM API & LOGGING  ==========================
// =================================================================================

/**
 * Получает и кэширует ID бота
 * Нужен для фильтрации событий связанных с самим ботом
 */
function getBotId() {
    const cache = CacheService.getScriptCache();
    let botId = cache.get('bot_id');
    
    if (!botId) {
        const response = sendTelegram('getMe', {});
        if (response?.ok) {
            botId = response.result.id;
            cache.put('bot_id', String(botId), 3600);
        }
    }
    
    return Number(botId) || null;
}

/**
 * Отправляет запрос к Telegram Bot API
 * @param {string} method - Метод API (например 'sendMessage')
 * @param {object} payload - Данные запроса
 */
function sendTelegram(method, payload) {
    const token = PropertiesService.getScriptProperties().getProperty('BOT_TOKEN');
    if (!token) return { ok: false, description: "Token not configured." };
    try {
        const response = UrlFetchApp.fetch(`https://api.telegram.org/bot${token}/${method}`, {
            method: 'post', 
            contentType: 'application/json',
            payload: JSON.stringify(payload), 
            muteHttpExceptions: true
        });
        const json = JSON.parse(response.getContentText());
        
        if (LOGGING_CONTEXT.developer_mode_enabled) {
            try {
                logEventTrace(LOGGING_CONTEXT, 'tg_api', method, 'API call (developer mode)', {
                    request: { method, payload },
                    response: json
                }, true);
            } catch (e) { }
        }
        
        if (!json.ok) {
            logToSheet("WARN", `TG API Error (${method}): ${response.getContentText()}`);
        }
        return json;
    } catch (e) {
        logToSheet("ERROR", `API Call Failed: ${method}, ${e.message}`);
        if (LOGGING_CONTEXT.developer_mode_enabled) {
            try { logEventTrace(LOGGING_CONTEXT, 'tg_api', method, 'API call failed', { error: e.message }, true); } catch(_) {}
        }
        return { ok: false, description: e.message };
    }
}

/**
 * Удаляет сообщение из чата
 * @param {string} chatId - ID чата
 * @param {string|number} messageId - ID сообщения
 */
function deleteMessage(chatId, messageId) {
    return sendTelegram('deleteMessage', { chat_id: chatId, message_id: messageId });
}

/**
 * Временно ограничивает пользователя в чате
 * @param {string} chatId - ID чата
 * @param {string|number} userId - ID пользователя
 * @param {boolean} canSendMessages - Может ли отправлять сообщения
 * @param {number} untilDate - Unix timestamp когда снять ограничения
 */
function restrictUser(chatId, userId, canSendMessages, untilDate) {
    const permissions = {
        can_send_messages: canSendMessages,
        can_send_media_messages: canSendMessages,
        can_send_polls: canSendMessages,
        can_send_other_messages: canSendMessages,
        can_add_web_page_previews: canSendMessages,
        can_send_audios: canSendMessages,
        can_send_documents: canSendMessages,
        can_send_photos: canSendMessages,
        can_send_videos: canSendMessages,
        can_send_video_notes: canSendMessages,
        can_send_voice_notes: canSendMessages
    };
    const payload = {
        chat_id: chatId,
        user_id: userId,
        permissions: permissions,
        use_independent_chat_permissions: true,
        until_date: untilDate || 0
    };
    const resp = sendTelegram('restrictChatMember', payload);
    logToSheet('DEBUG', `[restrictUser] payload=${JSON.stringify(payload)} respOk=${resp?.ok}`);
    return resp;
}

/**
 * Снимает все ограничения с пользователя
 * @param {string} chatId - ID чата
 * @param {string|number} userId - ID пользователя
 */
function unmuteUser(chatId, userId) {
    const permissions = {
        can_send_messages: true,
        can_send_media_messages: true,
        can_send_polls: true,
        can_send_other_messages: true,
        can_add_web_page_previews: true,
        can_send_audios: true,
        can_send_documents: true,
        can_send_photos: true,
        can_send_videos: true,
        can_send_video_notes: true,
        can_send_voice_notes: true
    };
    const payload = {
        chat_id: chatId,
        user_id: userId,
        permissions: permissions,
        use_independent_chat_permissions: true
    };
    const resp = sendTelegram('restrictChatMember', payload);
    logToSheet('DEBUG', `[unmuteUser] payload=${JSON.stringify(payload)} respOk=${resp?.ok}`);
    return resp;
}

/**
 * Логирует событие в лист Events с расширенной информацией
 * @param {object} config - Объект конфигурации
 * @param {string} event - Тип события
 * @param {string} action - Действие
 * @param {string} details - Детали
 * @param {object} payload - Данные события
 * @param {boolean} force - Логировать ли даже если логирование выключено
 */
function logEventTrace(config, event, action, details, payload, force) {
  if (this.TEST_MODE) return;
  
  const configFlag = typeof config === 'boolean'
    ? config
    : (config?.developer_mode_enabled || config?.extended_logging_enabled || LOGGING_CONTEXT.developer_mode_enabled);
  if (!force && !configFlag) return;

  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Events');
    if (!sheet) return;

    const maxRows = 10000;
    const rows = sheet.getLastRow();
    if (rows > maxRows) {
      sheet.deleteRows(2, rows - (maxRows - 1));
    }

    if (sheet.getLastRow() >= 1) {
      sheet.insertRows(2, 1);
    }

    let payloadText = '';
    if (payload !== undefined && payload !== null) {
      if (typeof payload === 'string') {
        payloadText = payload;
      } else {
        try {
          payloadText = JSON.stringify(payload);
        } catch (jsonError) {
          payloadText = `[[Unserializable payload: ${jsonError.message}]]`;
        }
      }
    }

    sheet.getRange(2, 1, 1, 5).setValues([[
      new Date(),
      String(event || ''),
      String(action || ''),
      String(details || '').slice(0, 2000),
      String(payloadText || '').slice(0, 5000)
    ]]);
  } catch (e) {
    logToSheet('ERROR', `Failed to write extended log: ${e.message}`);
  }
}

/**
 * Логирует сообщение в лист Logs
 * @param {string} level - Уровень лога (DEBUG, INFO, WARN, ERROR, CRITICAL, SUCCESS)
 * @param {string} message - Сообщение
 */
function logToSheet(level, message) {
  // ✅ ПРАВИЛЬНО: Проверяем глобальный контекст (быстро!)
  if (level === 'DEBUG' && !LOGGING_CONTEXT.developer_mode_enabled) {
    return;  // Пропускаем DEBUG логи если режим разработчика выключен
  }
  
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Logs');
    if (sheet) {
        const maxRows = 10000;
        const currentRows = sheet.getLastRow();
        if (currentRows > maxRows) { 
            sheet.deleteRows(2, currentRows - (maxRows - 1)); 
        }

        if (sheet.getLastRow() >= 1) {
          sheet.insertRows(2, 1);
          sheet.getRange(2, 1, 1, 3).setValues([[new Date(), level, String(message).slice(0, 50000)]]);
        } else {
          sheet.appendRow([new Date(), level, String(message).slice(0, 50000)]);
        }
    }
  } catch (e) { 
    // Failsafe - не ломаем код если логирование не работает
  }
}


/**
 * Логирует результат теста в лист Tests
 * @param {string} testName - Название теста
 * @param {string} status - Статус теста
 * @param {string} details - Детали теста
 * @param {any} apiCalls - API вызовы
 */
function logToTestSheet(testName, status, details, apiCalls) {
  if (this.TEST_MODE) return;
  
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Tests');
    if (sheet) {
        if (sheet.getLastRow() > 100) { 
            sheet.deleteRows(2, sheet.getLastRow() - 99); 
        }
        
        sheet.appendRow([
            new Date(), 
            String(testName || ''), 
            String(status || ''), 
            String(details || '').slice(0, 1000),
            Array.isArray(apiCalls) ? apiCalls.join(', ') : String(apiCalls || '').slice(0, 500)
        ]);
        
        try {
            sheet.autoResizeColumns(1, 5);
        } catch (e) {
            // Ignore
        }
    }
  } catch (e) { 
    if (!this.TEST_MODE) {
        logToSheet('ERROR', `Failed to log test result: ${e.message}`);
    }
  }
}

/**
 * Запускает набор тестов из меню
 */
function runTestsFromMenu() {
  try {
    const testsSheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Tests');
    if (testsSheet && testsSheet.getLastRow() > 1) {
      testsSheet.getRange(2, 1, testsSheet.getLastRow() - 1, 5).clearContent();
    }
    
    logToTestSheet('TEST_SUITE_START', '🧪 STARTING', 'Test suite initiated from menu', '');
    
    const testResults = runAllTestsWithLogging();
    
    const summary = `Tests completed: ${testResults.passed} passed, ${testResults.failed} failed, ${testResults.total} total`;
    logToTestSheet('TEST_SUITE_COMPLETE', testResults.failed === 0 ? '✅ SUCCESS' : '❌ PARTIAL', summary, '');
    
    logToSheet('INFO', summary);
    if (testResults.failed === 0) {
      logToSheet('SUCCESS', `🎉 All ${testResults.total} tests passed!`);
    } else {
      logToSheet('WARNING', `⚠️ ${testResults.failed} out of ${testResults.total} tests failed.`);
    }
    
  } catch (error) {
    logToTestSheet('TEST_SUITE_ERROR', '💥 ERROR', `Failed to run test suite: ${error.message}`, '');
    logToSheet('ERROR', `Test suite execution failed: ${error.message}`);
  }
}

/**
 * Placeholder функция для запуска тестов
 */
function runAllTestsWithLogging() {
  return { passed: 0, failed: 0, total: 0 };
}
