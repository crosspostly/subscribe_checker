/**
 * @file Code.gs
 * @description All-in-one script for a Telegram subscription and CAPTCHA bot.
 */

// =================================================================================
// 1. GLOBAL CONFIGURATION & WEBHOOK ENTRY POINT
// =================================================================================

// ---!!! IMPORTANT: PASTE YOUR BOT TOKEN HERE !!!---
const BOT_TOKEN = 'YOUR_BOT_TOKEN';

const TELEGRAM_API_URL = 'https://api.telegram.org/bot' + BOT_TOKEN;
const SCRIPT_URL = ScriptApp.getService().getUrl();

/**
 * Main function that Telegram calls. This is the entry point for all updates.
 * @param {Object} e The event parameter from the web app request.
 */
function doPost(e) {
  try {
    if (e && e.postData && e.postData.contents) {
      const update = JSON.parse(e.postData.contents);
      handleUpdate(update);
    } else {
        logToSheet('Error', 'doPost called with invalid event object');
    }
  } catch (error) {
    logToSheet('Error', `doPost Error: ${error.message} \nStack: ${error.stack}`);
  }
  return ContentService.createTextOutput("OK");
}

/**
 * The main update handler/dispatcher.
 * @param {Object} update The parsed update object from Telegram.
 */
function handleUpdate(update, externalServices) {
  const services = externalServices || {
    ss: SpreadsheetApp.getActiveSpreadsheet(),
    cache: CacheService.getScriptCache(),
    lock: LockService.getScriptLock(),
    properties: PropertiesService.getScriptProperties(),
    fetch: UrlFetchApp
  };
    
  if (update.chat_member) {
    handleNewChatMember(update.chat_member, services);
  } else if (update.message) {
    handleMessage(update.message, services);
  } else if (update.callback_query) {
    handleCallbackQuery(update.callback_query, services);
  }
}

// =================================================================================
// 2. CORE LOGIC - HANDLING USER ACTIONS
// =================================================================================

/**
 * Handles a new user joining or leaving the chat.
 * @param {Object} chatMember The chat_member update object.
 */
function handleNewChatMember(chatMember, services) {
  const newUser = chatMember.new_chat_member;
  const chat = chatMember.chat;
  const status = newUser.status;

  // Process only when a new member actually joins
  if (status !== 'member') {
    return;
  }
    
  const config = getCachedConfig(services);
  
  // Mute the user immediately
  const muteUntil = new Date().getTime() / 1000 + config.captcha_mute_duration_min * 60;
  restrictUser(chat.id, newUser.id, false, muteUntil, services);

  // Send CAPTCHA message
  const text = config.texts.captcha_text.replace('{user_mention}', getMention(newUser));
  const keyboard = {
    inline_keyboard: [
      [{ text: "✅ Я не робот", callback_data: `captcha_${newUser.id}` }]
    ]
  };
  const sentMessage = sendTelegram('sendMessage', {
    chat_id: chat.id,
    text: text,
    parse_mode: 'HTML',
    reply_markup: JSON.stringify(keyboard)
  }, services);

  if (sentMessage && sentMessage.ok) {
    const messageId = sentMessage.result.message_id;
    const captchaData = {
      userId: newUser.id,
      chatId: chat.id,
      messageId: messageId,
      status: 'pending' 
    };
    services.cache.put(`captcha_${newUser.id}`, JSON.stringify(captchaData), config.captcha_message_timeout_sec);
    addMessageToCleaner(chat.id, messageId, config.captcha_message_timeout_sec, services);
  }
}

/**
 * Handles incoming callback queries from inline buttons.
 */
function handleCallbackQuery(callbackQuery, services) {
  const data = callbackQuery.data;
  const user = callbackQuery.from;
  const chat = callbackQuery.message.chat;
  const messageId = callbackQuery.message.message_id;

  if (data.startsWith('captcha_')) {
    const expectedUserId = data.split('_')[1];
    
    if (String(user.id) !== expectedUserId) {
      sendTelegram('answerCallbackQuery', { callback_query_id: callbackQuery.id, text: 'Эта кнопка не для вас!', show_alert: true }, services);
      return;
    }

    const captchaDataStr = services.cache.get(`captcha_${user.id}`);
    
    if (captchaDataStr) { 
      const captchaData = JSON.parse(captchaDataStr);
      captchaData.status = 'passed';
      services.cache.put(`captcha_${user.id}`, JSON.stringify(captchaData), 21600);

      unmuteUser(chat.id, user.id, services);
      deleteMessage(chat.id, messageId, services);
      sendTelegram('answerCallbackQuery', { callback_query_id: callbackQuery.id, text: '✅ Проверка пройдена!', show_alert: false }, services);

      const successMsg = sendTelegram('sendMessage', {chat_id: chat.id, text: `${getMention(user)}, добро пожаловать! Теперь вы можете отправлять сообщения.`}, services);
      if (successMsg.ok) {
        addMessageToCleaner(chat.id, successMsg.result.message_id, 10, services);
      }

    } else { 
      sendTelegram('answerCallbackQuery', { callback_query_id: callbackQuery.id, text: '⏳ Время вышло. Попробуйте войти в чат заново.', show_alert: true }, services);
    }
  }
}

/**
 * Handles incoming messages from users.
 */
function handleMessage(message, services) {
  const user = message.from;
  const chat = message.chat;
  const config = getCachedConfig(services);
  
  if(user.is_bot || String(chat.id) === String(user.id)) return;
  
  const isMember = isUserSubscribed(user.id, config.target_channel_id, services);

  if (!isMember) {
    deleteMessage(chat.id, message.message_id, services);

    let violationCount = Number(services.cache.get(`violations_${user.id}`) || 0);
    violationCount++;
    
    if (violationCount < config.violation_limit) {
      if(violationCount === 1) {
        const text = config.texts.sub_warning_text.replace('{user_mention}', getMention(user));
        const sentWarning = sendTelegram('sendMessage', {chat_id: chat.id, text: text, parse_mode: 'HTML'}, services);
        if(sentWarning.ok) {
           addMessageToCleaner(chat.id, sentWarning.result.message_id, config.warning_message_timeout_sec, services);
        }
      }
      services.cache.put(`violations_${user.id}`, violationCount, 3600);
    } else { 
      applyProgressiveMute(chat.id, user.id, services);
      services.cache.remove(`violations_${user.id}`);
    }
  } else {
    services.cache.remove(`violations_${user.id}`);
  }
}

// =================================================================================
// 3. HELPER & UTILITY FUNCTIONS
// =================================================================================

function isUserSubscribed(userId, channelId, services) {
  if (!channelId) return true;
  try {
    const response = sendTelegram('getChatMember', { chat_id: channelId, user_id: userId }, services);
    if (!response || !response.ok) return false;
    const status = response.result.status;
    return ['creator', 'administrator', 'member'].indexOf(status) !== -1;
  } catch (e) {
    return false;
  }
}

function applyProgressiveMute(chatId, userId, services) {
    const lock = services.lock;
    lock.waitLock(15000);

    try {
        const config = getCachedConfig(services);
        const usersSheet = services.ss.getSheetByName('Users');
        const userData = findRow(usersSheet, userId, 1);
        
        let currentLevel = userData ? userData.row[1] : 0;
        const newLevel = currentLevel + 1;

        let muteDurationMin;
        switch(newLevel) {
            case 1: muteDurationMin = config.mute_level_1_duration_min; break;
            case 2: muteDurationMin = config.mute_level_2_duration_min; break;
            default: muteDurationMin = config.mute_level_3_duration_min; break;
        }

        const muteUntil = new Date().getTime() / 1000 + muteDurationMin * 60;
        restrictUser(chatId, userId, false, muteUntil, services);

        if (userData) {
            usersSheet.getRange(userData.rowIndex, 2).setValue(newLevel);
        } else {
            usersSheet.appendRow([userId, newLevel]);
        }
      
        const user = {id: userId, first_name: 'Пользователь'};
        let text = config.texts.sub_mute_text
            .replace('{user_mention}', getMention(user))
            .replace('{duration}', muteDurationMin);
        const sentMuteMsg = sendTelegram('sendMessage', {chat_id: chatId, text: text, parse_mode: 'HTML'}, services);
        if(sentMuteMsg.ok) {
          addMessageToCleaner(chatId, sentMuteMsg.result.message_id, 30, services);
        }

    } finally {
        lock.releaseLock();
    }
}

function getMention(user) {
  const name = user.first_name || 'Пользователь';
  return `<a href="tg://user?id=${user.id}">${name.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</a>`;
}

function findRow(sheet, value, column) {
    if (!sheet) return null; // Guard against non-existent sheet
    const data = sheet.getDataRange().getValues();
    for (let i = 0; i < data.length; i++) {
        if (data[i][column - 1] == value) {
            return { row: data[i], rowIndex: i + 1 };
        }
    }
    return null;
}

// =================================================================================
// 4. GARBAGE COLLECTOR - FOR DELETING MESSAGES
// =================================================================================

function addMessageToCleaner(chatId, messageId, delaySec, services) {
  const lock = services.lock;
  lock.waitLock(10000);
  try {
    const properties = services.properties;
    const queueStr = properties.getProperty('deleteQueue') || '[]';
    const queue = JSON.parse(queueStr);
    
    const deleteAt = new Date().getTime() + delaySec * 1000;
    queue.push({ chatId, messageId, deleteAt });
    
    properties.setProperty('deleteQueue', JSON.stringify(queue));
  } finally {
    lock.releaseLock();
  }
}

function messageCleaner() {
  const services = {
    ss: SpreadsheetApp.getActiveSpreadsheet(),
    cache: CacheService.getScriptCache(),
    lock: LockService.getScriptLock(),
    properties: PropertiesService.getScriptProperties(),
    fetch: UrlFetchApp
  };
    
  const lock = services.lock;
  lock.waitLock(20000); // Wait longer in trigger context
  
  let queue;
  const properties = services.properties;

  try {
    const queueStr = properties.getProperty('deleteQueue');
    if (!queueStr) return;
    
    queue = JSON.parse(queueStr);
    const now = new Date().getTime();
    
    const stillPending = [];
    const config = getCachedConfig(services); // Get config for texts
    
    for (const item of queue) {
      if (now >= item.deleteAt) {
        const captchaDataStr = services.cache.get(`captcha_${item.messageId}`); // Check if it's a captcha message
        if(captchaDataStr) {
          const captchaData = JSON.parse(captchaDataStr);
          if(captchaData.status === 'pending') {
             const user = {id: captchaData.userId, first_name: 'Пользователь'};
             editMessageText(item.chatId, item.messageId, config.texts.captcha_timeout_text.replace('{user_mention}', getMention(user)), services);
             addMessageToCleaner(item.chatId, item.messageId, 30, services);
             captchaData.status = 'failed';
             services.cache.put(`captcha_${captchaData.userId}`, JSON.stringify(captchaData), 3600);
             continue;
          }
        }
        deleteMessage(item.chatId, item.messageId, services);
      } else {
        stillPending.push(item);
      }
    }
    
    properties.setProperty('deleteQueue', JSON.stringify(stillPending));

  } catch(e) {
    logToSheet('Error', `Cleaner Error: ${e.message}`);
    if (e instanceof SyntaxError) {
      properties.deleteProperty('deleteQueue');
    }
  } finally {
    lock.releaseLock();
  }
}

// =================================================================================
// 5. TELEGRAM API WRAPPERS
// =================================================================================

function sendTelegram(method, payload, services) {
  try {
    const fetchApp = services ? services.fetch : UrlFetchApp;
    const options = {
      'method': 'post',
      'contentType': 'application/json',
      'payload': JSON.stringify(payload),
      'muteHttpExceptions': true
    };
    const response = fetchApp.fetch(`${TELEGRAM_API_URL}/${method}`, options);
    const responseText = response.getContentText();
    return JSON.parse(responseText);
  } catch (e) {
    logToSheet('Error', `API Call Failed: ${method}, Payload: ${JSON.stringify(payload)}, Error: ${e.message}`);
    return { ok: false, description: e.message };
  }
}

function deleteMessage(chatId, messageId, services) {
  return sendTelegram('deleteMessage', { chat_id: chatId, message_id: messageId }, services);
}

function editMessageText(chatId, messageId, text, services) {
  return sendTelegram('editMessageText', { chat_id: chatId, message_id: messageId, text: text, parse_mode: 'HTML' }, services);
}

function restrictUser(chatId, userId, canSendMessages, untilDate, services) {
  const permissions = { can_send_messages: canSendMessages };
  if(canSendMessages){ // Full unmute
      permissions.can_send_media_messages = true;
      permissions.can_send_polls = true;
      permissions.can_send_other_messages = true;
      permissions.can_add_web_page_previews = true;
      permissions.can_invite_users = true;
  }
  return sendTelegram('restrictChatMember', {
    chat_id: chatId,
    user_id: userId,
    permissions: JSON.stringify(permissions),
    until_date: untilDate || 0
  }, services);
}

function unmuteUser(chatId, userId, services) {
    return restrictUser(chatId, userId, true, 0, services);
}


// =================================================================================
// 6. CACHING AND DATA MANAGEMENT
// =================================================================================
function getCachedConfig(services) {
  const cache = services.cache;
  const cachedConfig = cache.get('config');
  if (cachedConfig) {
    return JSON.parse(cachedConfig);
  }

  const ss = services.ss;
  const configSheet = ss.getSheetByName('Config');
  const textsSheet = ss.getSheetByName('Texts');
  
  const configData = configSheet.getDataRange().getValues();
  const textsData = textsSheet.getDataRange().getValues();

  const config = {};
  configData.slice(1).forEach(row => {
    if(row[0]) config[row[0]] = isNaN(row[1]) ? row[1] : Number(row[1]);
  });

  config.texts = {};
  textsData.slice(1).forEach(row => {
    if(row[0]) config.texts[row[0]] = row[1];
  });
  
  cache.put('config', JSON.stringify(config), 300); // Cache for 5 minutes
  return config;
}

function logToSheet(sheetName, message) {
    try {
        const ss = SpreadsheetApp.getActiveSpreadsheet();
        let sheet = ss.getSheetByName(sheetName);
        if (!sheet) {
            sheet = ss.insertSheet(sheetName);
            sheet.appendRow(['Timestamp', 'Message']);
        }
        sheet.appendRow([new Date(), message]);
    } catch (e) {
        Logger.log(`Failed to log to sheet ${sheetName}. Original message: ${message}. Error: ${e.message}`);
    }
}


// =================================================================================
// 7. ONE-TIME SETUP FUNCTION
// =================================================================================

/**
 * Run this function MANUALLY ONCE to set up the bot.
 */
function initialSetup() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  
  const requiredSheets = {
    'Config': ['key', 'value'],
    'Texts': ['key', 'value'],
    'Users': ['user_id', 'mute_level'],
    'Logs': ['timestamp', 'message']
  };

  for (const sheetName in requiredSheets) {
    if (!ss.getSheetByName(sheetName)) {
      const sheet = ss.insertSheet(sheetName);
      sheet.appendRow(requiredSheets[sheetName]).setFrozenRows(1);
    }
  }

  const configSheet = ss.getSheetByName('Config');
  configSheet.clearContents().appendRow(requiredSheets['Config']);
  const defaultConfig = [
    ['target_channel_id', ''],
    ['admin_id', 'YOUR_ADMIN_ID'],
    ['violation_limit', 3],
    ['captcha_mute_duration_min', 30],
    ['captcha_message_timeout_sec', 25],
    ['warning_message_timeout_sec', 15],
    ['mute_level_1_duration_min', 30],
    ['mute_level_2_duration_min', 300],
    ['mute_level_3_duration_min', 3000]
  ];
  configSheet.getRange(2, 1, defaultConfig.length, 2).setValues(defaultConfig);

  const textsSheet = ss.getSheetByName('Texts');
  textsSheet.clearContents().appendRow(requiredSheets['Texts']);
  const defaultTexts = [
      ['captcha_text', '{user_mention}, добро пожаловать!\n\nДля защиты чата от ботов, пожалуйста, подтвердите, что вы человек, нажав на кнопку ниже.'],
      ['captcha_timeout_text', '{user_mention}, время на прохождение проверки вышло. Вы временно не можете отправлять сообщения.'],
      ['sub_warning_text', '{user_mention}, чтобы писать в этом чате, вы должны быть подписаны на наш канал. Пожалуйста, подпишитесь и попробуйте снова.'],
      ['sub_mute_text', '🚫 {user_mention} был ограничен в отправке сообщений на {duration} минут за нарушение правил подписки.']
  ];
  textsSheet.getRange(2, 1, defaultTexts.length, 2).setValues(defaultTexts);
  
  const webhookResponse = sendTelegram('setWebhook', { url: SCRIPT_URL });
  logToSheet('Logs', 'Webhook Setup: ' + (webhookResponse.description || 'Failed'));
  
  ScriptApp.getProjectTriggers().forEach(trigger => ScriptApp.deleteTrigger(trigger));
  
  ScriptApp.newTrigger('messageCleaner')
    .timeBased()
    .everyMinutes(1)
    .create();
  
  logToSheet('Logs', 'Time-based trigger for messageCleaner created.');

  SpreadsheetApp.flush();
  
  ss.toast('Setup complete! IMPORTANT: Go to "Config" sheet and enter your target channel ID and admin ID.', '✅ SETUP COMPLETE', -1);
}
