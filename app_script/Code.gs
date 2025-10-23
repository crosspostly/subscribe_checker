/**
 * @file Code.gs
 * @description Advanced, robust, all-in-one script for a Telegram subscription and CAPTCHA bot.
 * This is the full, readable, and final version of the code, implementing all features from first_todo.md.
 */

// =================================================================================
// ===================  A. SCRIPT-WIDE DEFAULTS & CONSTANTS  ====================_
// =================================================================================

/**
 * Default configuration. Used as a fallback if the 'Config' sheet is missing or a key is not found.
 * This ensures the bot remains operational even with a misconfigured sheet.
 */
const DEFAULT_CONFIG = {
  bot_enabled: true,
  extended_logging_enabled: false,
  developer_mode_enabled: false,
  target_channel_id: "-1001168879742", // Default: customer-provided channel ID
  target_channel_url: "https://t.me/+fSmCfuEEzPVlYTky", // Default: customer-provided invite link
  authorized_chat_ids: "-1001491334227\n-1001568712129", // Default: customer-provided chat IDs (newline-separated)
  admin_id: "183761194", // Default: customer-provided admin ID
  captcha_mute_duration_min: 30,     // 30 minutes as requested
  captcha_message_timeout_sec: 30,   // 30 seconds as requested
  warning_message_timeout_sec: 20,   // 20 seconds as requested  
  violation_limit: 3,                // 3 attempts as requested
  mute_level_1_duration_min: 60,     // 1 hour as requested
  mute_level_2_duration_min: 1440,   // 24 hours as requested (1440 min)
  mute_level_3_duration_min: 10080,  // 7 days as requested (10080 min)
  texts: {
    captcha_text: "{user_mention}, добро пожаловать! Чтобы писать в чат, подтвердите, что вы не робот.",
    sub_warning_text: "{user_mention}, чтобы писать сообщения в этом чате, пожалуйста, подпишитесь на:\n\n • {channel_link}\n\nПосле подписки нажмите кнопку ниже.",
    sub_warning_text_no_link: "{user_mention}, чтобы отправлять сообщения в этот чат, вы должны быть подписаны на наш канал.",
    sub_success_text: "🎉 {user_mention}, вы успешно подписались и теперь можете писать сообщения!",
    sub_fail_text: "🚫 {user_mention}, не удалось подтвердить вашу подписку. Убедитесь, что подписаны на все каналы, и попробуйте снова.",
    sub_mute_text: "{user_mention}, вы были временно ограничены в отправке сообщений на {duration} минут, так как не подписались на обязательные каналы."
  }
};

/** System user IDs to always ignore. 136817688 is "Group" (anonymous admin), 777000 is "Telegram" (channel posts). */
const IGNORED_USER_IDS = ['136817688', '777000'];

/**
 * Stores the most recent logging configuration to avoid recalculating for every helper call.
 */
const LOGGING_CONTEXT = { extended_logging_enabled: false, developer_mode_enabled: false };

function setLoggingContext(flagOrConfig) {
  if (typeof flagOrConfig === 'boolean') {
    LOGGING_CONTEXT.extended_logging_enabled = flagOrConfig;
    LOGGING_CONTEXT.developer_mode_enabled = false;
  } else {
    LOGGING_CONTEXT.extended_logging_enabled = !!(flagOrConfig && flagOrConfig.extended_logging_enabled);
    LOGGING_CONTEXT.developer_mode_enabled = !!(flagOrConfig && flagOrConfig.developer_mode_enabled);
  }
}

function getChatMemberSafe(chatId, userId) {
  try {
    return sendTelegram('getChatMember', { chat_id: chatId, user_id: userId });
  } catch (e) {
    return null;
  }
}

/**
 * Reads getChatMember and logs effective status/permissions for diagnostics.
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
// =================  B. SPREADSHEET UI & MANUAL CONTROLS  ====================_
// =================================================================================

/**
 * Creates a custom menu in the spreadsheet UI when the file is opened.
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

// Wrapper functions for menu items to provide user feedback.
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
 * Toggles extended event logging and updates the Config sheet accordingly.
 * @param {boolean} showAlert Whether to show UI feedback.
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
 * Enables developer mode: logs all events and API calls to Events sheet.
 * Does not change bot behavior. Purely observational.
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
 * Disables developer mode logging.
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
 * Enables the bot by setting the 'bot_enabled' flag to true.
 * @param {boolean} showAlert If true, shows a UI alert to the user.
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
    // Log current configuration and texts snapshot for visibility
    try {
      const cfg = getCachedConfig();
      const cfgSummary = {
        bot_enabled: cfg.bot_enabled,
        developer_mode_enabled: !!cfg.developer_mode_enabled,
        extended_logging_enabled: !!cfg.extended_logging_enabled,
        authorized_chat_ids: (cfg.authorized_chat_ids || []).map(String),
        target_channel_id: String(cfg.target_channel_id || ''),
        target_channel_url: String(cfg.target_channel_url || ''),
        violation_limit: cfg.violation_limit,
        captcha_mute_duration_min: cfg.captcha_mute_duration_min,
        warning_message_timeout_sec: cfg.warning_message_timeout_sec,
        mute_schedule_min: [cfg.mute_level_1_duration_min, cfg.mute_level_2_duration_min, cfg.mute_level_3_duration_min]
      };
      const textsSummary = {
        captcha_text: cfg.texts?.captcha_text,
        sub_warning_text: cfg.texts?.sub_warning_text,
        sub_warning_text_no_link: cfg.texts?.sub_warning_text_no_link || DEFAULT_CONFIG.texts.sub_warning_text_no_link,
        sub_success_text: cfg.texts?.sub_success_text,
        sub_fail_text: cfg.texts?.sub_fail_text,
        sub_mute_text: cfg.texts?.sub_mute_text
      };
      logToSheet('INFO', `⚙️ Config snapshot: ${JSON.stringify(cfgSummary)}`);
      logToSheet('INFO', `📝 Texts snapshot: ${JSON.stringify(textsSummary)}`);
      logEventTrace(cfg, 'settings', 'config_snapshot', 'Config and texts on enable', { config: cfgSummary, texts: textsSummary }, true);
      // Дополнительно: лог прав бота в разрешённых чатах
      try {
        logBotPermissionsSnapshot(cfg);
      } catch (permErr) {
        logToSheet('WARN', `Не удалось проверить права бота: ${permErr && permErr.message ? permErr.message : permErr}`);
      }
      // Дополнительно: проверим состояние вебхука
      try {
        const status = checkWebhook(false);
        const pending = Number(status?.info?.result?.pending_update_count || 0);
        const lastErr = String(status?.info?.result?.last_error_message || '');
        if (pending > 10 || lastErr) {
          logToSheet('WARN', `Авто-сброс вебхука: pending=${pending}, last_error='${lastErr}'`);
          resetWebhook(false, true);
        }
      } catch (whErr) {
        logToSheet('WARN', `Не удалось проверить вебхук: ${whErr && whErr.message ? whErr.message : whErr}`);
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
 * Logs bot permissions for each authorized chat (delete, restrict) and writes an event trace.
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
      // 1) Прямой запрос
      let resp = sendTelegram('getChatMember', { chat_id: chatId, user_id: botId });
      // 2) Fallback, если чат не найден или не ok — пробуем без user_id, как в моках
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
 * Checks webhook status via getWebhookInfo and logs a readable summary. Optionally shows an alert.
 */
function checkWebhook(showAlert) {
  const info = sendTelegram('getWebhookInfo', {});
  const props = PropertiesService.getScriptProperties();
  const expectedUrl = String(props.getProperty('WEB_APP_URL') || '');
  const url = info?.result?.url || '';
  const pending = info?.result?.pending_update_count || 0;
  const lastErrDate = info?.result?.last_error_date || 0;
  const lastErrMsg = info?.result?.last_error_message || '';
  const ip = info?.result?.ip_address || '';
  const matches = expectedUrl && url ? (String(url).indexOf(expectedUrl) === 0 || String(expectedUrl).indexOf(url) === 0) : (expectedUrl === url);
  const statusMsg = `🌐 Webhook: url='${url || '-'}', expected='${expectedUrl || '-'}', matches=${matches}, pending=${pending}, last_error=${lastErrMsg ? '[' + lastErrMsg + ']' : 'none'}, ip=${ip || '-'}`;
  logToSheet(matches ? 'INFO' : 'WARN', statusMsg);
  try { logEventTrace(LOGGING_CONTEXT, 'settings', 'webhook_status', 'Webhook check', { url, expectedUrl, pending, lastErrDate, lastErrMsg, ip, matches }, true); } catch(_) {}
  if (showAlert) {
    try { SpreadsheetApp.getUi().alert(statusMsg); } catch(_) {}
  }
  return { info, expectedUrl, matches };
}

/**
 * Re-sets webhook to WEB_APP_URL, optionally dropping pending updates.
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
 * Disables the bot by setting the 'bot_enabled' flag to false.
 * @param {boolean} showAlert If true, shows a UI alert to the user.
 */
function disableBot(showAlert) {
  updateConfigValue('bot_enabled', false, '🔴 Бот ВЫКЛЮЧЕН');
  if (showAlert) {
    try { SpreadsheetApp.getUi().alert('🛑 Бот выключен. Он больше не будет реагировать на события в чатах.'); } catch(e) {}
  }
}

/**
 * Clears the script cache for configuration and admin lists.
 * @param {boolean} showAlert If true, shows a UI alert to the user.
 */
function clearCache(showAlert) {
  CacheService.getScriptCache().removeAll(['config', 'admin_cache']);
  if (showAlert) {
    try { SpreadsheetApp.getUi().alert('✅ Кэш настроек и администраторов очищен. Новые данные будут загружены из таблицы при следующем событии.'); } catch(e) {}
  }
}

/**
 * Helper to update a specific key-value pair in the 'Config' sheet.
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
    clearCache(false); // Clear cache automatically without showing a second popup
  } catch (e) { logToSheet('ERROR', `Failed to update config value for key: ${key}. Error: ${e.message}`); }
}

// =================================================================================
// ==========================  C. INITIAL SETUP WIZARD  ==========================
// =================================================================================

/**
 * Performs a full one-time setup of the bot.
 */
function initialSetup() {
  try {
    _createSheets();
    _setWebhook();
    _createTrigger();
    enableBot(false); // Enable bot logic without showing a popup
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
    } catch(e) { /* Failsafe for non-UI context */ }
  }
}

/**
 * Creates all necessary sheets with headers and examples.
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
 * Sets the Telegram webhook to this script's URL.
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
 * Creates a time-based trigger for the message cleaner function.
 */
function _createTrigger() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t)); // Prevent duplicate triggers
  ScriptApp.newTrigger('messageCleaner').timeBased().everyMinutes(1).create();
  Logger.log('✅ (Шаг 3/3) Триггер очистки создан.');
}

// =================================================================================
// =========================  D. CORE LOGIC & EVENT HANDLERS =====================
// =================================================================================

/**
 * Main entry point for all Telegram updates.
 */
function doPost(e) {
  try {
    if (e && e.postData && e.postData.contents) {
      handleUpdate(JSON.parse(e.postData.contents));
    }
  } catch (error) {
    logToSheet("CRITICAL", `Критическая ошибка в doPost: ${error.message}`);
  }
  return ContentService.createTextOutput("OK");
}

/**
 * Central hub for processing all incoming updates.
 */
function handleUpdate(update) {
    const config = getCachedConfig();
    setLoggingContext(config);
    logEventTrace(config, 'update', 'received', 'Получено новое обновление от Telegram', update);

    // Идемпотентность: игнорируем дубликаты update_id в ближайшие 10 минут
    try {
        const updId = update && typeof update.update_id !== 'undefined' ? String(update.update_id) : '';
        if (updId) {
            const cache = CacheService.getScriptCache();
            const key = `upd_${updId}`;
            if (cache.get(key)) {
                logEventTrace(config, 'update', 'ignored_duplicate', 'Дубликат update_id, пропуск', { update_id: updId }, true);
                return;
            }
            cache.put(key, '1', 600); // 10 минут
        }
    } catch(_) {}

    if (!config.bot_enabled) {
        // Даже если бот выключен, для администратора в ЛС логируем факт доставки вебхука
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
        // ЛС с администратором — логируем отдельным событием, подтверждая работу вебхука
        const adminIdStr = String(config.admin_id || '').trim();
        if (adminIdStr && String(user.id) === adminIdStr) {
            logToSheet('SUCCESS', `🌐 Webhook OK: получено личное сообщение от администратора ${user.id}. Ключи обновления: ${Object.keys(update || {}).join(', ')}`);
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
            logToTestSheet('handleUpdate DEBUG', '🔍 DEBUG', `Checking admin status: user ${user.id}, chat ${chat.id}`, '');
            const userIsAdmin = isAdmin(chat.id, user.id, services.cache);
            logToSheet('DEBUG', `[handleUpdate] Admin check result for user ${user.id}: ${userIsAdmin}`);
            logToTestSheet('handleUpdate DEBUG', '🔍 DEBUG', `Admin check result: user ${user.id}, isAdmin=${userIsAdmin}`, '');
            if (userIsAdmin) {
                logToSheet('DEBUG', `[handleUpdate] Admin ${user.id} in message event. Ignoring.`);
                logToTestSheet('handleUpdate DEBUG', '🔍 DEBUG', `SKIPPING: Admin ${user.id} in message event`, '');
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
    // Обработка join-сообщений (legacy): message.new_chat_members
    if (update.message && Array.isArray(update.message.new_chat_members) && update.message.new_chat_members.length > 0) {
        for (var i = 0; i < update.message.new_chat_members.length; i++) {
            var nm = update.message.new_chat_members[i];
            try {
                const synthetic = {
                    chat: update.message.chat,
                    from: update.message.from, // может быть приглашавший; handleNewChatMember учтёт
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
 * Handles new user join events with comprehensive filtering and proper CAPTCHA logic.
 * Based on Python implementation from bot/handlers/group_messages.py
 */
/**
 * Handles join requests in closed/private chats - auto-approves them.
 * Based on Telegram Bot API for handling chat_join_request updates.
 */
function handleChatJoinRequest(joinRequest, services, config) {
    const chat = joinRequest.chat;
    const user = joinRequest.from;
    
    logToSheet('INFO', `Join request from ${user.first_name || 'User'} (${user.id}) for chat ${chat.id}.`);
    logEventTrace(config, 'chat_join_request', 'received', 'Получена заявка на вступление', {
        chatId: chat.id,
        userId: user.id
    });
    
    // Skip bots and system accounts
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
    
    // Auto-approve join requests (you can add additional checks here)
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

function handleNewChatMember(chatMember, services, config) {
    const chat = chatMember.chat;
    const user = chatMember.new_chat_member.user;
    const oldStatus = chatMember.old_chat_member?.status;
    const newStatus = chatMember.new_chat_member.status;
    const fromUser = chatMember.from;

    logToSheet('DEBUG', `[handleNewChatMember] ChatMember Event: chat_id=${chat.id}, user_id=${user.id}, from_id=${fromUser?.id}, old_status=${oldStatus}, new_status=${newStatus}`);
    logToTestSheet('handleNewChatMember DEBUG', '🔍 DEBUG', `Processing chat_member event: user ${user.id}, from ${fromUser?.id}, status ${oldStatus} -> ${newStatus} in chat ${chat.id}`, '');
    logEventTrace(config, 'chat_member', 'received', 'Получено событие изменения участника', {
        chatId: chat.id,
        userId: user.id,
        fromId: fromUser?.id,
        oldStatus,
        newStatus
    });

    // Skip negative IDs (channels acting as users)
    if (user.id < 0) {
        logToSheet('INFO', `[handleNewChatMember] Channel as user event (ID: ${user.id}) in chat ${chat.id}. Skipping.`);
        logToTestSheet('handleNewChatMember DEBUG', '🔍 DEBUG', `SKIPPING: Negative ID (channel) ${user.id}`, '');
        logEventTrace(config, 'chat_member', 'ignored', 'Событие от канала пропущено', {
            chatId: chat.id,
            userId: user.id,
            reason: 'channel_as_user'
        });
        return;
    }

    // Skip if event is about the bot itself or other bots
    if (user.is_bot) {
        const botId = getBotId();
        if (botId && user.id === botId) {
            logToSheet('INFO', `[handleNewChatMember] Bot join event in chat ${chat.id}. No action needed.`);
            logToTestSheet('handleNewChatMember DEBUG', '🔍 DEBUG', `SKIPPING: Bot itself ${user.id}`, '');
            logEventTrace(config, 'chat_member', 'ignored', 'Событие о самом боте, пропустить', {
                chatId: chat.id,
                userId: user.id,
                reason: 'bot_self'
            });
        } else {
            logToSheet('INFO', `[handleNewChatMember] External bot ${user.id} in chat ${chat.id}. Skipping.`);
            logToTestSheet('handleNewChatMember DEBUG', '🔍 DEBUG', `SKIPPING: Other bot ${user.id}`, '');
            logEventTrace(config, 'chat_member', 'ignored', 'Событие о внешнем боте, пропустить', {
                chatId: chat.id,
                userId: user.id,
                reason: 'external_bot'
            });
        }
        return;
    }

    // Skip system accounts and other bots
    if (IGNORED_USER_IDS.includes(String(user.id))) {
        logToSheet('INFO', `[handleNewChatMember] System account ${user.id} in chat ${chat.id}. Skipping member processing.`);
        logToTestSheet('handleNewChatMember DEBUG', '🔍 DEBUG', `SKIPPING: System account ${user.id}`, '');
        logEventTrace(config, 'chat_member', 'ignored', 'Системный аккаунт пропущен', {
            chatId: chat.id,
            userId: user.id,
            reason: 'system_account'
        });
        return;
    }

    // CRITICAL FIX: Determine if this is a real user-initiated join
    // If 'from' field is missing, we default to assuming it's user-initiated (backwards compatibility)
    // If 'from' exists and differs from the user, it's an admin action (unmute/invite)
    const isInitiatedByUser = !fromUser || Number(fromUser.id) === Number(user.id);
    
    logToSheet('DEBUG', `[handleNewChatMember] Join analysis: from=${fromUser?.id}, user=${user.id}, isInitiatedByUser=${isInitiatedByUser}`);
    logToTestSheet('handleNewChatMember DEBUG', '🔍 DEBUG', `Join analysis: from=${fromUser?.id}, user=${user.id}, isInitiatedByUser=${isInitiatedByUser}`, '');
    
    // Реальным вступлением считаем переход в 'member' из left/kicked/нет статуса
    // (в том числе при приглашении админом). restricted->member по-прежнему не считаем новым вступлением.
    const isRealJoin = (
        ((oldStatus === 'left' || oldStatus === 'kicked') && newStatus === 'member') ||
        (!oldStatus && newStatus === 'member')
    );
    
    // Admin actions should NOT trigger CAPTCHA (isInitiatedByUser = false)

    logToSheet('DEBUG', `[handleNewChatMember] Real join check: isRealJoin=${isRealJoin}, oldStatus=${oldStatus}, newStatus=${newStatus}`);
    logToTestSheet('handleNewChatMember DEBUG', '🔍 DEBUG', `Real join check: isRealJoin=${isRealJoin}, reasons: ${oldStatus}->${newStatus}, initiated by user: ${isInitiatedByUser}`, '');

    if (!isRealJoin) {
        logToSheet('DEBUG', `[handleNewChatMember] Non-join event for user ${user.id} in chat ${chat.id}: ${oldStatus} -> ${newStatus}. Skipping.`);
        logToTestSheet('handleNewChatMember DEBUG', '🔍 DEBUG', `SKIPPING: Non-join event for user ${user.id}: ${oldStatus} -> ${newStatus}`, '');
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

    // Skip admins - check AFTER determining it's a real join
    const userIsAdmin = isAdmin(chat.id, user.id, services.cache);
    logToSheet('DEBUG', `[handleNewChatMember] Admin check for user ${user.id}: isAdmin=${userIsAdmin}`);
    logToTestSheet('handleNewChatMember DEBUG', '🔍 DEBUG', `Admin check for user ${user.id}: isAdmin=${userIsAdmin}`, '');
    
    if (userIsAdmin) {
        logToSheet('INFO', `[handleNewChatMember] Admin ${user.id} joined chat ${chat.id}. No CAPTCHA needed.`);
        logToTestSheet('handleNewChatMember DEBUG', '🔍 DEBUG', `SKIPPING: Admin user ${user.id} joined chat ${chat.id}`, '');
        logEventTrace(config, 'chat_member', 'ignored', 'Администратор, CAPTCHA не требуется', {
            chatId: chat.id,
            userId: user.id
        });
        return;
    }

    logToSheet('INFO', `[handleNewChatMember] Real user join detected: ${user.first_name || 'User'} (${user.id}) in chat ${chat.id}.`);
    logToTestSheet('handleNewChatMember DEBUG', '🔍 DEBUG', `PROCESSING: Real user join detected for user ${user.id}`, '');
    logEventTrace(config, 'chat_member', 'processing', 'Начата выдача CAPTCHA для нового пользователя', {
        chatId: chat.id,
        userId: user.id
    });

    // Check if bot has necessary permissions (only for real joins)
    const botId = getBotId();
    let botInfo = sendTelegram('getChatMember', { chat_id: chat.id, user_id: botId });
    let canRestrict = botInfo?.result?.can_restrict_members === true || ['administrator', 'creator'].includes(String(botInfo?.result?.status || ''));
    let canDelete = botInfo?.result?.can_delete_messages === true || ['administrator', 'creator'].includes(String(botInfo?.result?.status || ''));
    if (!botInfo?.ok || !(canRestrict && canDelete)) {
        // Альтернативная проверка: через список админов
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
            // Продолжаем попытку restrict, даже если не смогли подтвердить права (пусть API ответ подтвердит/опровергнет)
            logToSheet('WARN', `[handleNewChatMember] Bot permissions not confirmed in chat ${chat.id}. Will attempt restrict anyway.`);
            logToTestSheet('handleNewChatMember DEBUG', '⚠️ WARN', `Permissions not confirmed; attempting restrict`, '');
            logEventTrace(config, 'chat_member', 'warn', 'Права бота не подтверждены, пробуем restrict', { chatId: chat.id, userId: user.id });
        }
    }

    // Apply CAPTCHA logic
    logToSheet('INFO', `[handleNewChatMember] Applying CAPTCHA to user ${user.id} in chat ${chat.id}`);
    const muteUntil = Math.floor(Date.now() / 1000) + (config.captcha_mute_duration_min * 60);
    const restrictResult = restrictUser(chat.id, user.id, false, muteUntil);
    
    logToSheet('DEBUG', `[handleNewChatMember] Restrict result for user ${user.id}: ok=${restrictResult?.ok}, error=${restrictResult?.description}`);
    
    if (!restrictResult?.ok) {
        logToSheet('ERROR', `[handleNewChatMember] Failed to restrict user ${user.id} in chat ${chat.id}: ${restrictResult?.description}`);
        logToTestSheet('handleNewChatMember DEBUG', '❌ ERROR', `Failed to restrict user ${user.id}: ${restrictResult?.description}`, '');
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

    // Верификация фактических прав после restrict
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
        logToTestSheet('handleNewChatMember DEBUG', '✅ SUCCESS', `CAPTCHA sent to user ${user.id}, message ${sentMessage.result.message_id}`, '');
        addMessageToCleaner(chat.id, sentMessage.result.message_id, config.captcha_message_timeout_sec, services);
        logEventTrace(config, 'chat_member', 'captcha_sent', 'Отправлено сообщение с CAPTCHA', {
            chatId: chat.id,
            userId: user.id,
            messageId: sentMessage.result.message_id,
            muteUntil
        });
    } else {
        logToSheet('ERROR', `[handleNewChatMember] Failed to send CAPTCHA to user ${user.id} in chat ${chat.id}: ${sentMessage?.description}`);
        logToTestSheet('handleNewChatMember DEBUG', '❌ ERROR', `Failed to send CAPTCHA to user ${user.id}: ${sentMessage?.description}`, '');
        logEventTrace(config, 'chat_member', 'error', 'Не удалось отправить сообщение CAPTCHA', {
            chatId: chat.id,
            userId: user.id,
            description: sentMessage?.description || 'unknown_error'
        });
    }
}

/**
 * Handles my_chat_member updates (bot's own status in a chat changed).
 * Useful for confirming permissions and logging joins/removals.
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

    // When promoted to administrator or added, re-check and log permissions
    if (['administrator', 'member'].includes(String(newStatus || ''))) {
        try {
            logBotPermissionsSnapshot(config);
        } catch (e) {
            logToSheet('WARN', `[handleMyChatMember] Не удалось обновить снимок прав: ${e && e.message ? e.message : e}`);
        }
    }
}


/**
 * Handles callback queries from CAPTCHA and subscription check buttons.
 */
function handleCallbackQuery(callbackQuery, services, config) {
    const data = callbackQuery.data;
    const user = callbackQuery.from;
    const chat = callbackQuery.message.chat;
    const messageId = callbackQuery.message.message_id;
    
    logToSheet('DEBUG', `[handleCallbackQuery] data=${data}, user_id=${user.id}, chat_id=${chat.id}`);
    logEventTrace(config, 'callback_query', 'received', 'Получен callback-запрос от пользователя', {
        chatId: chat.id,
        userId: user.id,
        data
    });
    
    // Handle CAPTCHA buttons
    if (data.startsWith('captcha_')) {
        logEventTrace(config, 'callback_query', 'processing', 'Обработка кнопки CAPTCHA', {
            chatId: chat.id,
            userId: user.id,
            data
        });
        const expectedUserId = data.split('_')[1];
        if (String(user.id) !== expectedUserId) {
            sendTelegram('answerCallbackQuery', { callback_query_id: callbackQuery.id, text: 'Эта кнопка не для вас!', show_alert: true });
            logEventTrace(config, 'callback_query', 'ignored', 'Пользователь попытался нажать чужую CAPTCHA', {
                chatId: chat.id,
                userId: user.id,
                expectedUserId
            });
            return;
        }

        unmuteUser(chat.id, user.id);
        const deleteResult = deleteMessage(chat.id, messageId);
        sendTelegram('answerCallbackQuery', { callback_query_id: callbackQuery.id, text: '✅ Проверка пройдена!' });

        const welcomeMsg = `${getMention(user)}, добро пожаловать!`;
        const successMsg = sendTelegram('sendMessage', { chat_id: chat.id, text: welcomeMsg, parse_mode: 'HTML', disable_notification: true });
        if (successMsg?.ok) {
            addMessageToCleaner(chat.id, successMsg.result.message_id, 15, services);
            logEventTrace(config, 'callback_query', 'captcha_completed', 'Пользователь прошёл CAPTCHA успешно', {
                chatId: chat.id,
                userId: user.id,
                deleteOk: deleteResult?.ok,
                welcomeMessageId: successMsg.result.message_id
            });
        }
        else {
            logEventTrace(config, 'callback_query', 'error', 'Не удалось отправить приветственное сообщение после CAPTCHA', {
                chatId: chat.id,
                userId: user.id,
                description: successMsg?.description || 'unknown_error'
            });
        }
        return;
    }
    
    // Handle subscription check buttons
    if (data.startsWith('check_sub_')) {
        logEventTrace(config, 'callback_query', 'processing', 'Обработка кнопки проверки подписки', {
            chatId: chat.id,
            userId: user.id,
            data
        });
        const expectedUserId = data.split('_')[2];
        if (String(user.id) !== expectedUserId) {
            sendTelegram('answerCallbackQuery', { callback_query_id: callbackQuery.id, text: 'Эта кнопка не для вас!', show_alert: true });
            logEventTrace(config, 'callback_query', 'ignored', 'Пользователь попытался нажать чужую кнопку проверки подписки', {
                chatId: chat.id,
                userId: user.id,
                expectedUserId
            });
            return;
        }
        
        // Check subscription
        // Не кэшировать ответ на кнопку: Telegram может переиспользовать старый текст
        sendTelegram('answerCallbackQuery', { callback_query_id: callbackQuery.id, text: '⏳ Проверяем вашу подписку...', cache_time: 0 });
        
        const isMember = isUserSubscribed(user.id, config.target_channel_id);
        
        if (isMember) {
            // User is subscribed - success
            services.cache.remove(`violations_${user.id}`);
            const deleteResult = deleteMessage(chat.id, messageId);
            
            const successMsg = config.texts.sub_success_text.replace('{user_mention}', getMention(user));
            const sentMsg = sendTelegram('sendMessage', { 
                chat_id: chat.id, 
                text: successMsg, 
                parse_mode: 'HTML',
                disable_notification: true
            });
            if (sentMsg?.ok) {
                addMessageToCleaner(chat.id, sentMsg.result.message_id, 3, services);
            }
            logEventTrace(config, 'callback_query', 'subscription_confirmed', 'Пользователь подтвердил подписку через кнопку', {
                chatId: chat.id,
                userId: user.id,
                deleteOk: deleteResult?.ok,
                confirmationMessageId: sentMsg?.result?.message_id
            });
        } else {
            // User is still not subscribed
            // Build alert text to match Python version (titles only, no links)
            let alertText = '';
            
            // Update the message with channel info
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
                
                const editResult = sendTelegram('editMessageText', {
                    chat_id: chat.id,
                    message_id: messageId,
                    text: updatedText,
                    parse_mode: 'HTML',
                    reply_markup: JSON.stringify(keyboard),
                    disable_web_page_preview: true
                });
                
                addMessageToCleaner(chat.id, messageId, 15, services);
                logEventTrace(config, 'callback_query', 'subscription_pending', 'Пользователь ещё не подписан, сообщение обновлено', {
                    chatId: chat.id,
                    userId: user.id,
                    editOk: editResult?.ok,
                    channelTitle
                });

                // Alert mirrors Python: plain text with channel title only
                const plainName = getMention(user).replace(/<[^>]*>/g, '');
                alertText = `🚫 ${plainName}, вы все еще не подписаны на:\n  • ${String(channelTitle).replace(/[<>]/g, '')}\n\nПодпишитесь и попробуйте снова.`;
            }
            else {
                // Нет URL — оставляем кнопку "Я подписался" для повторной проверки
                const updatedText = (config.texts.sub_fail_text || DEFAULT_CONFIG.texts.sub_fail_text)
                  .replace('{user_mention}', getMention(user).replace(/<[^>]*>/g, ''));
                const keyboard = { inline_keyboard: [ [{ text: "✅ Я подписался", callback_data: `check_sub_${user.id}` }] ] };
                const editResult = sendTelegram('editMessageText', {
                    chat_id: chat.id,
                    message_id: messageId,
                    text: updatedText,
                    parse_mode: 'HTML',
                    reply_markup: JSON.stringify(keyboard),
                    disable_web_page_preview: true
                });
                addMessageToCleaner(chat.id, messageId, 15, services);
                logEventTrace(config, 'callback_query', 'subscription_pending', 'Нет URL канала, обновлено без ссылки', {
                    chatId: chat.id,
                    userId: user.id,
                    editOk: editResult?.ok
                });
                // Fallback alert mirrors Python's generic failure text
                alertText = (config.texts.sub_fail_text || DEFAULT_CONFIG.texts.sub_fail_text)
                  .replace('{user_mention}', getMention(user).replace(/<[^>]*>/g, ''));
            }
            
            sendTelegram('answerCallbackQuery', { callback_query_id: callbackQuery.id, text: alertText, show_alert: true, cache_time: 5 });
        }
        logEventTrace(config, 'callback_query', 'completed', 'Обработка кнопки проверки подписки завершена', {
            chatId: chat.id,
            userId: user.id,
            result: isMember ? 'subscribed' : 'not_subscribed'
        });
        return;
    }

    logEventTrace(config, 'callback_query', 'ignored', 'Неизвестный callback_data, действие не выполнено', {
        chatId: chat.id,
        userId: user.id,
        data
    });
}

/**
 * Handles regular messages to check for subscription status.
 * NOTE: All filtering (admins, bots, whitelist, private messages) is now done in handleUpdate
 */
function handleMessage(message, services, config) {
    const user = message.from;
    const chat = message.chat;
    
    logToSheet('DEBUG', `[handleMessage] Processing message from user ${user.id} in chat ${chat.id}`);
    logToTestSheet('handleMessage DEBUG', '🔍 DEBUG', `Processing message: user ${user.id}, chat ${chat.id}`, '');
    logEventTrace(config, 'message', 'received', 'Получено сообщение от пользователя', {
        chatId: chat.id,
        userId: user.id,
        messageId: message.message_id,
        textLength: message.text ? message.text.length : 0
    });
    
    // Если пользователь уже ограничен, не эскалируем и не шлём предупреждений
    try {
        const current = getChatMemberSafe(chat.id, user.id);
        const until = current?.result?.until_date ? Number(current.result.until_date) : 0;
        const nowSec = Math.floor(Date.now() / 1000);
        const isRestricted = String(current?.result?.status || '') === 'restricted' || current?.result?.can_send_messages === false;
        if (isRestricted && until > nowSec) {
            // Попробуем удалить сообщение, но больше ничего не делаем
            try { deleteMessage(chat.id, message.message_id); } catch(_) {}
            logEventTrace(config, 'message', 'restricted_user_message', 'Сообщение от уже ограниченного пользователя, эскалация пропущена', {
                chatId: chat.id, userId: user.id, until
            });
            return;
        }
    } catch(_) {}

    // Check subscription status
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

    // If not a member, delete message and handle violation
    const deleteResult = deleteMessage(chat.id, message.message_id);
    let violationCount = Number(services.cache.get(`violations_${user.id}`) || 0) + 1;
    services.cache.put(`violations_${user.id}`, violationCount, 21600); // Cache violations for 6 hours
    logEventTrace(config, 'message', 'violation_recorded', 'Сообщение удалено: пользователь не подписан', {
        chatId: chat.id,
        userId: user.id,
        messageId: message.message_id,
        deleteOk: deleteResult?.ok,
        violationCount,
        violationLimit: config.violation_limit
    });

    if (violationCount < config.violation_limit) {
        if (violationCount === 1) { // Send warning only on the first violation
            let text;
            let keyboard;

            // Всегда показываем кнопку проверки подписки. Ссылку на канал добавляем, если есть URL.
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
                // Нет URL канала — отправляем текст без ссылки, но с кнопкой проверки
                text = (config.texts.sub_warning_text || config.texts.sub_warning_text_no_link || DEFAULT_CONFIG.texts.sub_warning_text_no_link)
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
                logEventTrace(config, 'message', 'warning_sent', 'Отправлено предупреждение о необходимости подписки', {
                    chatId: chat.id,
                    userId: user.id,
                    messageId: sentWarning.result.message_id,
                    hasChannelLink: !!(config.target_channel_url && config.target_channel_url.trim() !== '')
                });
            } else {
                logEventTrace(config, 'message', 'error', 'Не удалось отправить предупреждение о подписке', {
                    chatId: chat.id,
                    userId: user.id,
                    description: sentWarning?.description || 'unknown_error'
                });
            }
        } else {
            // Повторные нарушения до порога: только удаляем сообщение, без мута
            logEventTrace(config, 'message', 'violation_notified', 'Повторное нарушение зафиксировано, предупреждение не отправлялось', {
                chatId: chat.id,
                userId: user.id,
                violationCount
            });
        }
    } else {
        applyProgressiveMute(chat.id, user, services, config);
        services.cache.remove(`violations_${user.id}`); // Reset counter after muting
        logEventTrace(config, 'message', 'mute_applied', 'Порог нарушений достигнут, пользователь временно ограничен', {
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
 * Task #2: Gets configuration, falling back to defaults and caching the result.
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

    let config = JSON.parse(JSON.stringify(DEFAULT_CONFIG)); // Start with defaults
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

        // BUG FIX: Only overwrite default texts if the Texts sheet has actual content.
        if (textsSheet) {
            const textData = textsSheet.getDataRange().getValues().slice(1).filter(row => row[0] && row[1]); // Filter rows with key and value
            if (textData.length > 0) {
                 config.texts = config.texts || {}; // Ensure texts object exists
                 textData.forEach(row => {
                    config.texts[row[0]] = row[1];
                });
            }
        }

        config.authorized_chat_ids = String(config.authorized_chat_ids || '').split(/\n|,|\s+/).filter(Boolean);
        config.whitelist_ids = whitelistSheet ? whitelistSheet.getDataRange().getValues().slice(1).map(row => String(row[0])).filter(Boolean) : [];

        cache.put('config', JSON.stringify(config), 300); // Cache for 5 minutes
    } catch (e) {
        logToSheet("ERROR", `Failed to load config from sheet: ${e.message}. Using defaults.`);
    }
    setLoggingContext(config);
    return config;
}

function isAdmin(chatId, userId, cache) {
    const cacheKey = `admin_cache_${chatId}`;
    let adminList = JSON.parse(cache.get(cacheKey) || '[]');
    if (adminList.includes(userId)) return true;

    const response = sendTelegram('getChatAdministrators', { chat_id: chatId });
    if (response && response.ok) {
        adminList = response.result.map(admin => admin.user.id);
        cache.put(cacheKey, JSON.stringify(adminList), 3600); // Cache admin list for 1 hour
        return adminList.includes(userId);
    }
    return false; // Fail safely
}

function isUserSubscribed(userId, channelId) {
    if (!channelId || String(channelId).trim() === '') return true; // If no channel is set, subscription check is waived.
    try {
        const response = sendTelegram('getChatMember', { chat_id: channelId, user_id: userId });
        const status = response?.result?.status;
        // Для приватных/приглашений у getChatMember может вернуться 400/left — это корректно; выше try/catch уже обрабатывает.
        return ['creator', 'administrator', 'member'].includes(status);
    } catch (e) {
        logToSheet("ERROR", `Ошибка проверки подписки для user ${userId} в канале ${channelId}: ${e.message}`);
        return false; // Fail safely
    }
}

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
        } else { // Level 3 and beyond
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
        // Отправляем одно объединённое сообщение: статус + кнопка подписки (если есть URL)
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
            // Удаляем сообщение о муте через 10 секунд, как в Python-версии
            addMessageToCleaner(chatId, sentMuteMsg.result.message_id, 10, services);
        }
    } finally {
        lock.releaseLock();
    }
}


function addMessageToCleaner(chatId, messageId, delaySec, services) {
    const lock = services.lock; lock.waitLock(10000);
    try {
        const props = PropertiesService.getScriptProperties();
        const queue = JSON.parse(props.getProperty('deleteQueue') || '[]');
        const deleteAt = new Date().getTime() + delaySec * 1000;
        queue.push({ chatId, messageId, deleteAt });
        props.setProperty('deleteQueue', JSON.stringify(queue));
    } finally { lock.releaseLock(); }
}

function messageCleaner() {
    const lock = LockService.getScriptLock(); lock.waitLock(20000);
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
        // В TEST_MODE не логируем ошибки чтобы не мешать тестам
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

function getMention(user) {
    const name = (user.first_name || 'User').replace(/[<>]/g, '');
    return `<a href="tg://user?id=${user.id}">${name}</a>`;
}

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
// =========================  F. TELEGRAM API & LOGGING  =========================_
// =================================================================================

/**
 * Gets and caches the bot's ID to avoid repeated API calls.
 * This is needed for filtering bot-related events.
 */
function getBotId() {
    const cache = CacheService.getScriptCache();
    let botId = cache.get('bot_id');
    
    if (!botId) {
        const response = sendTelegram('getMe', {});
        if (response?.ok) {
            botId = response.result.id;
            cache.put('bot_id', String(botId), 3600); // Cache for 1 hour
        }
    }
    
    return Number(botId) || null;
}

function sendTelegram(method, payload) {
    const token = PropertiesService.getScriptProperties().getProperty('BOT_TOKEN');
    if (!token) return { ok: false, description: "Token not configured." };
    try {
        const response = UrlFetchApp.fetch(`https://api.telegram.org/bot${token}/${method}`, {
            method: 'post', contentType: 'application/json',
            payload: JSON.stringify(payload), muteHttpExceptions: true
        });
        const json = JSON.parse(response.getContentText());
        // Developer mode: log API request/response to Events sheet without altering behavior
        if (LOGGING_CONTEXT.developer_mode_enabled) {
            try {
                logEventTrace(LOGGING_CONTEXT, 'tg_api', method, 'API call (developer mode)', {
                    request: { method, payload },
                    response: json
                }, true);
            } catch (e) { /* ignore logging failures */ }
        }
        if (!json.ok) {
            logToSheet("WARN", `TG API Error (${method}): ${response.getContentText()}`);
        }
        return json;
    } catch (e) {
        logToSheet("ERROR", `API Call Failed: ${method}, ${e.message}`);
        if (LOGGING_CONTEXT.developer_mode_enabled) {
            try { logEventTrace(LOGGING_CONTEXT, 'tg_api', method, 'API call failed (developer mode)', { error: e.message }, true); } catch(_) {}
        }
        return { ok: false, description: e.message };
    }
}

function deleteMessage(chatId, messageId) {
    return sendTelegram('deleteMessage', { chat_id: chatId, message_id: messageId });
}

function restrictUser(chatId, userId, canSendMessages, untilDate) {
    // Use full ChatPermissions set per current Bot API; do NOT stringify
    const permissions = {
        // Legacy aggregated permissions
        can_send_messages: canSendMessages,
        can_send_media_messages: canSendMessages,
        can_send_polls: canSendMessages,
        can_send_other_messages: canSendMessages,
        can_add_web_page_previews: canSendMessages,
        // Independent permissions (Bot API >= 7.0)
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
    // Диагностика: логируем полезную нагрузку и ответ (в developer mode попадёт в Events)
    logToSheet('DEBUG', `[restrictUser] payload=${JSON.stringify(payload)} respOk=${resp?.ok}`);
    return resp;
}

function unmuteUser(chatId, userId) {
    // Restore full permissions; do NOT stringify
    const permissions = {
        // Legacy aggregated permissions
        can_send_messages: true,
        can_send_media_messages: true,
        can_send_polls: true,
        can_send_other_messages: true,
        can_add_web_page_previews: true,
        // Independent permissions (Bot API >= 7.0)
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

function logEventTrace(config, event, action, details, payload, force) {
  // Skip logging during tests
  if (this.TEST_MODE) return;
  
  // In developer mode we always log everything
  const configFlag = typeof config === 'boolean'
    ? config
    : (config?.developer_mode_enabled || config?.extended_logging_enabled || LOGGING_CONTEXT.developer_mode_enabled);
  if (!force && !configFlag) return;

  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Events');
    if (!sheet) return;

    // Очистка Events при превышении 10 000 строк
    const maxRows = 10000;
    const rows = sheet.getLastRow();
    if (rows > maxRows) {
      sheet.deleteRows(2, rows - (maxRows - 1));
    }

    // Пишем свежие записи сверху (после шапки) для удобства чтения
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

function logToSheet(level, message) {
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Logs');
    if (sheet) {
        // Автоматическая очистка логов для предотвращения переполнения (держим не более 10 000 строк)
        const maxRows = 10000;
        const currentRows = sheet.getLastRow();
        if (currentRows > maxRows) { sheet.deleteRows(2, currentRows - (maxRows - 1)); }

        // Пишем свежие записи сверху (после шапки) для удобства чтения
        if (sheet.getLastRow() >= 1) {
          sheet.insertRows(2, 1);
          sheet.getRange(2, 1, 1, 3).setValues([[new Date(), level, String(message).slice(0, 50000)]]);
        } else {
          sheet.appendRow([new Date(), level, String(message).slice(0, 50000)]);
        }
    }
  } catch (e) { /* Failsafe, do nothing */ }
}

/**
 * Logs test results to the Tests sheet with detailed information
 * IMPORTANT: Avoid === comparisons when writing to Google Sheets cells
 */
function logToTestSheet(testName, status, details, apiCalls) {
  // Skip logging during tests
  if (this.TEST_MODE) return;
  
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Tests');
    if (sheet) {
        // Clear old test results (keep only last 100 entries)
        if (sheet.getLastRow() > 100) { 
            sheet.deleteRows(2, sheet.getLastRow() - 99); 
        }
        
        // Add test result - convert all values to strings to avoid Google Sheets issues
        sheet.appendRow([
            new Date(), 
            String(testName || ''), 
            String(status || ''), 
            String(details || '').slice(0, 1000),  // Limit details to 1000 chars
            Array.isArray(apiCalls) ? apiCalls.join(', ') : String(apiCalls || '').slice(0, 500)
        ]);
        
        // Auto-resize columns for better readability
        try {
            sheet.autoResizeColumns(1, 5);
        } catch (e) {
            // Ignore auto-resize errors
        }
    }
  } catch (e) { 
    if (!this.TEST_MODE) {
        logToSheet('ERROR', `Failed to log test result: ${e.message}`);
    }
  }
}

/**
 * Enhanced debug logging function for detailed test analysis
 */
function logTestDebug(testName, debugInfo) {
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Tests');
    if (sheet) {
        sheet.appendRow([
            new Date(), 
            String(testName || '') + ' [DEBUG]', 
            '🔍 DEBUG', 
            String(debugInfo || '').slice(0, 2000),  // More space for debug info
            ''
        ]);
    }
  } catch (e) { 
    logToSheet('ERROR', `Failed to log debug info: ${e.message}`);
  }
}

/**
 * Runs the comprehensive test suite from the menu and logs results to Tests sheet
 */
function runTestsFromMenu() {
  try {
    // Clear previous test results
    const testsSheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Tests');
    if (testsSheet && testsSheet.getLastRow() > 1) {
      testsSheet.getRange(2, 1, testsSheet.getLastRow() - 1, 5).clearContent();
    }
    
    logToTestSheet('TEST_SUITE_START', '🧪 STARTING', 'Comprehensive bot test suite initiated from menu', '');
    
    // Import and run tests from tests.gs
    // Note: This assumes tests.gs is included in the same project
    const testResults = runAllTestsWithLogging();
    
    const summary = `Tests completed: ${testResults.passed} passed, ${testResults.failed} failed, ${testResults.total} total`;
    logToTestSheet('TEST_SUITE_COMPLETE', testResults.failed === 0 ? '✅ SUCCESS' : '❌ PARTIAL', summary, '');
    
    // Log final summary to regular log as well - NO POPUP WINDOWS
    logToSheet('INFO', summary);
    if (testResults.failed === 0) {
      logToSheet('SUCCESS', `🎉 All ${testResults.total} tests passed! Check Tests sheet for details.`);
    } else {
      logToSheet('WARNING', `⚠️ ${testResults.failed} out of ${testResults.total} tests failed. Check Tests sheet for details.`);
    }
    
  } catch (error) {
    logToTestSheet('TEST_SUITE_ERROR', '💥 ERROR', `Failed to run test suite: ${error.message}`, '');
    logToSheet('ERROR', `Test suite execution failed: ${error.message}. Stack: ${error.stack || 'No stack available'}`);
  }
}
