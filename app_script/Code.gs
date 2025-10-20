/**
 * @file Code.gs
 * @description Advanced, robust, all-in-one script for a Telegram subscription and CAPTCHA bot.
 * This is the full, readable, and final version of the code, implementing all features from first_todo.md.
 */

// =================================================================================
// ===================  A. SCRIPT-WIDE DEFAULTS & CONSTANTS  =====================
// =================================================================================

/**
 * Default configuration. Used as a fallback if the 'Config' sheet is missing or a key is not found.
 * This ensures the bot remains operational even with a misconfigured sheet.
 */
const DEFAULT_CONFIG = {
  bot_enabled: true,
  target_channel_id: "", // IMPORTANT: Must be a numeric ID (e.g., -100123456789)
  authorized_chat_ids: "", // List of chat IDs where the bot should operate, one per line
  admin_id: "", // Your personal Telegram ID for critical error notifications
  captcha_mute_duration_min: 5,
  captcha_message_timeout_sec: 300,
  warning_message_timeout_sec: 30,
  violation_limit: 3,
  mute_level_1_duration_min: 60,
  mute_level_2_duration_min: 1440, // 24 hours
  mute_level_3_duration_min: 10080, // 7 days
  texts: {
    captcha_text: "{user_mention}, добро пожаловать! Чтобы писать в чат, подтвердите, что вы не робот.",
    sub_warning_text: "{user_mention}, чтобы отправлять сообщения в этот чат, вы должны быть подписаны на наш канал.",
    sub_mute_text: "{user_mention} был заглушен на {duration} минут за отказ от подписки на канал."
  }
};

/** System user IDs to always ignore. 136817688 is "Group" (anonymous admin), 777000 is "Telegram" (channel posts). */
const IGNORED_USER_IDS = ['136817688', '777000'];

// =================================================================================
// =================  B. SPREADSHEET UI & MANUAL CONTROLS  =====================
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
    .addSeparator()
    .addItem('🔄 Сбросить кэш (Настройки и Админы)', 'userClearCache')
    .addToUi();
}

// Wrapper functions for menu items to provide user feedback.
function userEnableBot() { enableBot(true); }
function userDisableBot() { disableBot(true); }
function userClearCache() { clearCache(true); }

/**
 * Enables the bot by setting the 'bot_enabled' flag to true.
 * @param {boolean} showAlert If true, shows a UI alert to the user.
 */
function enableBot(showAlert) {
  updateConfigValue('bot_enabled', true, '🟢 Бот ВКЛЮЧЕН');
  if (showAlert) {
    try { SpreadsheetApp.getUi().alert('✅ Бот включен. Он начнет обрабатывать новые события.'); } catch(e) {}
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
    "Config": [ ["key", "value", "description"], ["bot_enabled", true, "TRUE/FALSE. Управляется через меню."], ["target_channel_id", "-100...", "ЧИСЛОВОЙ ID канала для проверки подписки."], ["authorized_chat_ids", "-100...\n-100...", "ID чатов, где работает бот (каждый с новой строки)"], ["admin_id", "", "Ваш Telegram ID для получения критических ошибок."] ],
    "Texts": [ ["key", "value"], ["captcha_text", DEFAULT_CONFIG.texts.captcha_text], ["sub_warning_text", DEFAULT_CONFIG.texts.sub_warning_text], ["sub_mute_text", DEFAULT_CONFIG.texts.sub_mute_text] ],
    "Users": [["user_id", "mute_level", "first_violation_date"]], 
    "Logs": [["Timestamp", "Level", "Message"]], 
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
    if (!config.bot_enabled) return; // Task #3: Check if bot is enabled

    const chat = update.message?.chat || update.callback_query?.message?.chat || update.chat_member?.chat;
    if (!chat) return;

    // Task #5: Check if the chat is authorized
    if (config.authorized_chat_ids.length > 0 && !config.authorized_chat_ids.includes(String(chat.id))) {
        return;
    }
    
    const services = { ss: SpreadsheetApp.getActiveSpreadsheet(), cache: CacheService.getScriptCache(), lock: LockService.getScriptLock() };

    // Task #7 & #4: Handle channel posts and whitelisted users
    if (update.message && update.message.sender_chat) {
        const senderId = String(update.message.sender_chat.id);
        if (senderId === String(config.target_channel_id) || config.whitelist_ids.includes(senderId)) {
            return; // Ignore posts from target channel or whitelisted channels
        }
    }

    const user = update.message?.from || update.callback_query?.from || update.chat_member?.new_chat_member?.user;
    if (!user) return;
    if (user.is_bot || IGNORED_USER_IDS.includes(String(user.id)) || config.whitelist_ids.includes(String(user.id))) {
        return; // Ignore bots, system users, and whitelisted users
    }

    // --- Event Dispatcher ---
    if (update.chat_member) {
        handleNewChatMember(update.chat_member, services, config); // Task #1: Handle new members correctly
    } else if (update.message) {
        handleMessage(update.message, services, config);
    } else if (update.callback_query) {
        handleCallbackQuery(update.callback_query, services, config);
    }
}

/**
 * Task #1: Handles a new user joining the chat, spam-free.
 */
function handleNewChatMember(chatMember, services, config) {
    // This is the crucial check: only trigger on a real user join.
    const isRealJoin = (chatMember.old_chat_member.status === 'left' || chatMember.old_chat_member.status === 'kicked') 
                     && chatMember.new_chat_member.status === 'member';
    if (!isRealJoin) return;

    const user = chatMember.new_chat_member.user;
    if (isAdmin(chatMember.chat.id, user.id, services.cache)) return; // Admins don't need CAPTCHA

    const muteUntil = Math.floor(new Date().getTime() / 1000 + config.captcha_mute_duration_min * 60);
    restrictUser(chatMember.chat.id, user.id, false, muteUntil);

    const text = config.texts.captcha_text.replace('{user_mention}', getMention(user));
    const keyboard = { inline_keyboard: [[{ text: "✅ Я не робот", callback_data: `captcha_${user.id}` }]] };
    const sentMessage = sendTelegram('sendMessage', { chat_id: chatMember.chat.id, text: text, parse_mode: 'HTML', reply_markup: JSON.stringify(keyboard) });

    if (sentMessage?.ok) {
        addMessageToCleaner(chatMember.chat.id, sentMessage.result.message_id, config.captcha_message_timeout_sec, services);
    }
}

/**
 * Handles callback queries from CAPTCHA buttons.
 */
function handleCallbackQuery(callbackQuery, services, config) {
    const data = callbackQuery.data;
    const user = callbackQuery.from;
    const chat = callbackQuery.message.chat;
    const messageId = callbackQuery.message.message_id;
    if (!data.startsWith('captcha_')) return;

    const expectedUserId = data.split('_')[1];
    if (String(user.id) !== expectedUserId) {
        sendTelegram('answerCallbackQuery', { callback_query_id: callbackQuery.id, text: 'Эта кнопка не для вас!', show_alert: true });
        return;
    }
    
    unmuteUser(chat.id, user.id);
    deleteMessage(chat.id, messageId);
    sendTelegram('answerCallbackQuery', { callback_query_id: callbackQuery.id, text: '✅ Проверка пройдена!' });

    const welcomeMsg = `${getMention(user)}, добро пожаловать!`;
    const successMsg = sendTelegram('sendMessage', { chat_id: chat.id, text: welcomeMsg, parse_mode: 'HTML' });
    if (successMsg?.ok) {
        addMessageToCleaner(chat.id, successMsg.result.message_id, 15, services);
    }
}

/**
 * Handles regular messages to check for subscription status.
 */
function handleMessage(message, services, config) {
    const user = message.from;
    const chat = message.chat;
    if (String(chat.id) === String(user.id)) return; // Ignore private messages to bot

    if (isAdmin(chat.id, user.id, services.cache)) return;
    
    const isMember = isUserSubscribed(user.id, config.target_channel_id);
    if (isMember) {
        services.cache.remove(`violations_${user.id}`);
        return;
    }

    // If not a member, delete message and handle violation
    deleteMessage(chat.id, message.message_id);
    let violationCount = Number(services.cache.get(`violations_${user.id}`) || 0) + 1;
    services.cache.put(`violations_${user.id}`, violationCount, 21600); // Cache violations for 6 hours

    if (violationCount < config.violation_limit) {
        if (violationCount === 1) { // Send warning only on the first violation
            const text = config.texts.sub_warning_text.replace('{user_mention}', getMention(user));
            const sentWarning = sendTelegram('sendMessage', { chat_id: chat.id, text: text, parse_mode: 'HTML' });
            if (sentWarning?.ok) {
                addMessageToCleaner(chat.id, sentWarning.result.message_id, config.warning_message_timeout_sec, services);
            }
        }
    } else {
        applyProgressiveMute(chat.id, user, services, config);
        services.cache.remove(`violations_${user.id}`); // Reset counter after muting
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
    if (cached) { try { return JSON.parse(cached); } catch(e) { /* continue to load */ } }

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
                config.texts = {}; // Overwrite only if new data exists
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
        return ['creator', 'administrator', 'member'].includes(status);
    } catch (e) {
        logToSheet("ERROR", `Ошибка проверки подписки для user ${userId} в канале ${channelId}: ${e.message}`);
        return false; // Fail safely
    }
}

function applyProgressiveMute(chatId, user, services, config) {
    const lock = services.lock; lock.waitLock(15000);
    try {
        const usersSheet = services.ss.getSheetByName('Users'); if (!usersSheet) return;
        const userId = user.id;
        const userData = findRow(usersSheet, userId, 1);
        const newLevel = (userData ? Number(userData.row[1]) : 0) + 1;

        let muteDurationMin;
        if (newLevel === 1) muteDurationMin = config.mute_level_1_duration_min;
        else if (newLevel === 2) muteDurationMin = config.mute_level_2_duration_min;
        else muteDurationMin = config.mute_level_3_duration_min;

        const muteUntil = Math.floor(new Date().getTime() / 1000 + muteDurationMin * 60);
        restrictUser(chatId, userId, false, muteUntil);

        if (userData) { usersSheet.getRange(userData.rowIndex, 2).setValue(newLevel); } 
        else { usersSheet.appendRow([userId, newLevel, new Date()]); }

        const text = config.texts.sub_mute_text.replace('{user_mention}', getMention(user)).replace('{duration}', muteDurationMin);
        const sentMuteMsg = sendTelegram('sendMessage', { chat_id: chatId, text: text, parse_mode: 'HTML' });
        if (sentMuteMsg?.ok) {
            addMessageToCleaner(chatId, sentMuteMsg.result.message_id, 45, services);
        }
    } finally { lock.releaseLock(); }
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
        logToSheet("ERROR", `messageCleaner Error: ${e.message}`);
        if (e instanceof SyntaxError) { PropertiesService.getScriptProperties().deleteProperty('deleteQueue'); }
    } finally { lock.releaseLock(); }
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
// =========================  F. TELEGRAM API & LOGGING  =========================
// =================================================================================

function sendTelegram(method, payload) {
    const token = PropertiesService.getScriptProperties().getProperty('BOT_TOKEN');
    if (!token) return { ok: false, description: "Token not configured." };
    try {
        const response = UrlFetchApp.fetch(`https://api.telegram.org/bot${token}/${method}`, {
            method: 'post', contentType: 'application/json',
            payload: JSON.stringify(payload), muteHttpExceptions: true
        });
        const json = JSON.parse(response.getContentText());
        if (!json.ok) {
            logToSheet("WARN", `TG API Error (${method}): ${response.getContentText()}`);
        }
        return json;
    } catch (e) {
        logToSheet("ERROR", `API Call Failed: ${method}, ${e.message}`);
        return { ok: false, description: e.message };
    }
}

function deleteMessage(chatId, messageId) {
    return sendTelegram('deleteMessage', { chat_id: chatId, message_id: messageId });
}

function restrictUser(chatId, userId, canSendMessages, untilDate) {
    const permissions = { 'can_send_messages': canSendMessages, 'can_send_media_messages': canSendMessages };
    return sendTelegram('restrictChatMember', {
        chat_id: chatId, user_id: userId, permissions: JSON.stringify(permissions), until_date: untilDate || 0
    });
}

function unmuteUser(chatId, userId) {
    const permissions = { 'can_send_messages': true, 'can_send_media_messages': true, 'can_send_other_messages': true, 'can_add_web_page_previews': true };
    return sendTelegram('restrictChatMember', { chat_id: chatId, user_id: userId, permissions: JSON.stringify(permissions) });
}

function logToSheet(level, message) {
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Logs');
    if (sheet) {
        if (sheet.getLastRow() > 5000) { sheet.deleteRows(2, sheet.getLastRow() - 4999); }
        sheet.appendRow([new Date(), level, String(message).slice(0, 50000)]);
    }
  } catch (e) { /* Failsafe, do nothing */ }
}
