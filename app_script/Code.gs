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
  target_channel_id: "", // IMPORTANT: Must be a numeric ID (e.g., -100123456789)
  target_channel_url: "", // Public URL of the target channel (e.g., https://t.me/my_channel)
  authorized_chat_ids: "", // List of chat IDs where the bot should operate, one per line
  admin_id: "", // Your personal Telegram ID for critical error notifications
  captcha_mute_duration_min: 30,     // 30 minutes as requested
  captcha_message_timeout_sec: 30,   // 30 seconds as requested
  warning_message_timeout_sec: 20,   // 20 seconds as requested  
  violation_limit: 3,                // 3 attempts as requested
  mute_level_1_duration_min: 60,     // 1 hour as requested
  mute_level_2_duration_min: 1440,   // 24 hours as requested (1440 min)
  mute_level_3_duration_min: 10080,  // 7 days as requested (10080 min)
  texts: {
    captcha_text: "{user_mention}, добро пожаловать! Чтобы писать в чат, подтвердите, что вы не робот.",
    sub_warning_text: "{user_mention}, чтобы отправлять сообщения в этот чат, вы должны быть подписаны на наш канал.",
    sub_mute_text: "{user_mention} был заглушен на {duration} минут за отказ от подписки на канал."
  }
};

/** System user IDs to always ignore. 136817688 is "Group" (anonymous admin), 777000 is "Telegram" (channel posts). */
const IGNORED_USER_IDS = ['136817688', '777000'];

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
    "Config": [
        ["key", "value", "description"],
        ["bot_enabled", true, "TRUE/FALSE. Управляется через меню."],
        ["target_channel_id", "-100...", "ЧИСЛОВОЙ ID канала для проверки подписки."],
        ["target_channel_url", "", "ПУБЛИЧНАЯ ссылка на канал (https://t.me/...)"],
        ["authorized_chat_ids", "-100...\n-100...", "ID чатов, где работает бот (каждый с новой строки)"],
        ["admin_id", "", "Ваш Telegram ID для получения критических ошибок."],
        ["captcha_mute_duration_min", 30, "На сколько минут блокировать новичка до прохождения капчи."],
        ["captcha_message_timeout_sec", 30, "Через сколько секунд удалять сообщение с капчей."],
        ["warning_message_timeout_sec", 20, "Через сколько секунд удалять предупреждение о подписке."],
        ["violation_limit", 3, "Сколько сообщений может написать пользователь без подписки перед мутом."],
        ["mute_level_1_duration_min", 60, "Длительность мута за первое нарушение."],
        ["mute_level_2_duration_min", 1440, "Длительность мута за второе нарушение (24 часа)."],
        ["mute_level_3_duration_min", 10080, "Длительность мута за третье и последующие нарушения (7 дней)."]
    ],
    "Texts": [
        ["key", "value"],
        ["captcha_text", DEFAULT_CONFIG.texts.captcha_text],
        ["sub_warning_text", DEFAULT_CONFIG.texts.sub_warning_text],
        ["sub_mute_text", "{user_mention} был заглушен на {duration} минут за отказ от подписки на канал."]
    ],
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

    logToSheet('DEBUG', JSON.stringify(update));

    const chat = update.message?.chat || update.callback_query?.message?.chat || update.chat_member?.chat;
    if (!chat) return;

    // Task #5: Check if the chat is authorized
    if (config.authorized_chat_ids.length > 0 && !config.authorized_chat_ids.includes(String(chat.id))) {
        return;
    }

    const services = { ss: SpreadsheetApp.getActiveSpreadsheet(), cache: CacheService.getScriptCache(), lock: LockService.getScriptLock() };

    // =======================================================================
    // COMPREHENSIVE FILTERING - All checks moved to the beginning for optimization
    // =======================================================================
    
    // Task #7 & #4: Handle channel posts and whitelisted channels
    if (update.message && update.message.sender_chat) {
        const senderId = String(update.message.sender_chat.id);
        if (senderId === String(config.target_channel_id) || config.whitelist_ids.includes(senderId)) {
            logToSheet('DEBUG', `Channel post from whitelisted sender ${senderId} in chat ${chat.id}. Ignoring.`);
            return; // Ignore posts from target channel or whitelisted channels
        }
    }

    // Extract user from different update types
    const user = update.message?.from || update.callback_query?.from || update.chat_member?.new_chat_member?.user;
    if (!user) return;

    // CRITICAL FIX: Check ALL filtering conditions at the beginning
    
    // 1. Skip bots (except for callback queries from users)
    if (user.is_bot) {
        logToSheet('DEBUG', `Bot user ${user.id} in chat ${chat.id}. Ignoring.`);
        return;
    }

    // 2. Skip system accounts (Telegram internal accounts)
    if (IGNORED_USER_IDS.includes(String(user.id))) {
        logToSheet('DEBUG', `System account ${user.id} in chat ${chat.id}. Ignoring.`);
        return;
    }

    // 3. Skip whitelisted users (FIXED: now properly checked for all users)
    if (config.whitelist_ids.includes(String(user.id))) {
        logToSheet('DEBUG', `Whitelisted user ${user.id} in chat ${chat.id}. Ignoring.`);
        return;
    }

    // 4. Skip admins (OPTIMIZED: check at the beginning instead of in each handler)
    if (isAdmin(chat.id, user.id, services.cache)) {
        logToSheet('DEBUG', `Admin ${user.id} in chat ${chat.id}. Ignoring.`);
        return;
    }

    // 5. Skip private messages to bot (for message events only)
    if (update.message && String(chat.id) === String(user.id)) {
        logToSheet('DEBUG', `Private message from user ${user.id} to bot. Ignoring.`);
        return;
    }

    // =======================================================================
    // EVENT DISPATCHER - Only process events that passed all filters
    // =======================================================================
    
    logToSheet('INFO', `Processing event for user ${user.id} in chat ${chat.id} after all filters passed.`);
    
    if (update.chat_member) {
        handleNewChatMember(update.chat_member, services, config);
    } else if (update.chat_join_request) {
        handleChatJoinRequest(update.chat_join_request, services, config);
    } else if (update.message) {
        handleMessage(update.message, services, config);
    } else if (update.callback_query) {
        handleCallbackQuery(update.callback_query, services, config);
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
    
    // Skip bots and system accounts
    if (user.is_bot || IGNORED_USER_IDS.includes(String(user.id))) {
        logToSheet('INFO', `Join request from bot/system account ${user.id}. Declining.`);
        sendTelegram('declineChatJoinRequest', { chat_id: chat.id, user_id: user.id });
        return;
    }
    
    // Auto-approve join requests (you can add additional checks here)
    const approveResult = sendTelegram('approveChatJoinRequest', { chat_id: chat.id, user_id: user.id });
    
    if (approveResult?.ok) {
        logToSheet('INFO', `Join request approved for ${user.id} in chat ${chat.id}.`);
    } else {
        logToSheet('ERROR', `Failed to approve join request for ${user.id} in chat ${chat.id}: ${approveResult?.description}`);
    }
}

function handleNewChatMember(chatMember, services, config) {
    const chat = chatMember.chat;
    const user = chatMember.new_chat_member.user;
    const oldStatus = chatMember.old_chat_member?.status;
    const newStatus = chatMember.new_chat_member.status;

    logToSheet('DEBUG', `ChatMember Event: chat_id=${chat.id}, user_id=${user.id}, old_status=${oldStatus}, new_status=${newStatus}`);

    // Check if bot has necessary permissions
    const botInfo = sendTelegram('getChatMember', { chat_id: chat.id, user_id: getBotId() });
    if (!botInfo?.ok || !botInfo.result?.can_restrict_members || !botInfo.result?.can_delete_messages) {
        logToSheet('WARN', `Bot lacks required permissions in chat ${chat.id}. Cannot handle member events properly.`);
        return;
    }

    // Skip if event is about the bot itself
    const botId = getBotId();
    if (botId && user.id === botId) {
        logToSheet('INFO', `Bot join event in chat ${chat.id}. No action needed.`);
        return;
    }

    // Skip negative IDs (channels acting as users)
    if (user.id < 0) {
        logToSheet('INFO', `Channel as user event (ID: ${user.id}) in chat ${chat.id}. Skipping.`);
        return;
    }

    // Skip system accounts and other bots
    if (user.is_bot || IGNORED_USER_IDS.includes(String(user.id))) {
        logToSheet('INFO', `Bot or system account ${user.id} in chat ${chat.id}. Skipping member processing.`);
        return;
    }

    // Define what constitutes a "real join" - more comprehensive than before
    const isRealJoin = (
        // Standard join: left/kicked -> member
        ((oldStatus === 'left' || oldStatus === 'kicked') && newStatus === 'member') ||
        // First time join: no old status -> member  
        (!oldStatus && newStatus === 'member') ||
        // Approved from restricted -> member (after passing captcha)
        (oldStatus === 'restricted' && newStatus === 'member')
    );

    if (!isRealJoin) {
        logToSheet('DEBUG', `Non-join event for user ${user.id} in chat ${chat.id}: ${oldStatus} -> ${newStatus}. Skipping.`);
        return;
    }

    // Skip admins
    if (isAdmin(chat.id, user.id, services.cache)) {
        logToSheet('INFO', `Admin ${user.id} joined chat ${chat.id}. No CAPTCHA needed.`);
        return;
    }

    logToSheet('INFO', `Real user join detected: ${user.first_name || 'User'} (${user.id}) in chat ${chat.id}.`);

    // Apply CAPTCHA logic
    const muteUntil = Math.floor(Date.now() / 1000) + (config.captcha_mute_duration_min * 60);
    const restrictResult = restrictUser(chat.id, user.id, false, muteUntil);
    
    if (!restrictResult?.ok) {
        logToSheet('ERROR', `Failed to restrict user ${user.id} in chat ${chat.id}: ${restrictResult?.description}`);
        return;
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
        reply_markup: JSON.stringify(keyboard)
    });

    if (sentMessage?.ok) {
        logToSheet('INFO', `CAPTCHA sent to ${user.id} in chat ${chat.id}, message_id: ${sentMessage.result.message_id}`);
        addMessageToCleaner(chat.id, sentMessage.result.message_id, config.captcha_message_timeout_sec, services);
    } else {
        logToSheet('ERROR', `Failed to send CAPTCHA to user ${user.id} in chat ${chat.id}: ${sentMessage?.description}`);
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
    
    // Handle CAPTCHA buttons
    if (data.startsWith('captcha_')) {
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
        return;
    }
    
    // Handle subscription check buttons
    if (data.startsWith('check_sub_')) {
        const expectedUserId = data.split('_')[2];
        if (String(user.id) !== expectedUserId) {
            sendTelegram('answerCallbackQuery', { callback_query_id: callbackQuery.id, text: 'Эта кнопка не для вас!', show_alert: true });
            return;
        }
        
        // Check subscription
        sendTelegram('answerCallbackQuery', { callback_query_id: callbackQuery.id, text: '⏳ Проверяем вашу подписку...', cache_time: 2 });
        
        const isMember = isUserSubscribed(user.id, config.target_channel_id);
        
        if (isMember) {
            // User is subscribed - success
            services.cache.remove(`violations_${user.id}`);
            deleteMessage(chat.id, messageId);
            
            const successMsg = `🎉 ${getMention(user)}, вы успешно подписались и теперь можете писать сообщения!`;
            const sentMsg = sendTelegram('sendMessage', { 
                chat_id: chat.id, 
                text: successMsg, 
                parse_mode: 'HTML',
                disable_notification: true
            });
            if (sentMsg?.ok) {
                addMessageToCleaner(chat.id, sentMsg.result.message_id, 3, services);
            }
        } else {
            // User is still not subscribed
            let alertText = `🚫 ${getMention(user).replace(/<[^>]*>/g, '')}, вы все еще не подписаны на канал.\n\nПодпишитесь и попробуйте снова.`;
            
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
                const updatedText = `${getMention(user)}, вы все еще не подписаны на:\n\n  • ${channelLink}\n\nПодпишитесь и попробуйте снова. Сообщение удалится через 15 сек.`;
                
                const keyboard = {
                    inline_keyboard: [
                        [{ text: `📱 ${channelTitle.replace(/[<>]/g, '')}`, url: config.target_channel_url }],
                        [{ text: "✅ Я подписался", callback_data: `check_sub_${user.id}` }]
                    ]
                };
                
                sendTelegram('editMessageText', {
                    chat_id: chat.id,
                    message_id: messageId,
                    text: updatedText,
                    parse_mode: 'HTML',
                    reply_markup: JSON.stringify(keyboard),
                    disable_web_page_preview: true
                });
                
                addMessageToCleaner(chat.id, messageId, 15, services);
            }
            
            sendTelegram('answerCallbackQuery', { callback_query_id: callbackQuery.id, text: alertText, show_alert: true, cache_time: 5 });
        }
        return;
    }
}

/**
 * Handles regular messages to check for subscription status.
 * NOTE: All filtering (admins, bots, whitelist, private messages) is now done in handleUpdate
 */
function handleMessage(message, services, config) {
    const user = message.from;
    const chat = message.chat;
    
    // Check subscription status
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
            let text;
            let keyboard = null;
            
            // Проверяем, указан ли URL канала в конфигурации
            if (config.target_channel_url && config.target_channel_url.trim() !== '') {
                // Пытаемся получить информацию о канале, чтобы взять его название
                const channelInfo = sendTelegram('getChat', { chat_id: config.target_channel_id });
                // Используем название канала, если оно доступно, иначе — ID канала как запасной вариант
                const channelTitle = channelInfo?.result?.title || config.target_channel_id;
                
                // Создаем HTML-ссылку в тексте
                const channelLink = `<a href="${config.target_channel_url}">${channelTitle.replace(/[<>]/g, '')}</a>`;
                
                // Формируем текст сообщения
                text = `${getMention(user)}, чтобы писать сообщения в этом чате, пожалуйста, подпишитесь на:\n\n  • ${channelLink}\n\nПосле подписки нажмите кнопку ниже.`;
                
                // Создаем inline-клавиатуру с кнопками
                keyboard = {
                    inline_keyboard: [
                        [{ text: `📱 ${channelTitle.replace(/[<>]/g, '')}`, url: config.target_channel_url }],
                        [{ text: "✅ Я подписался", callback_data: `check_sub_${user.id}` }]
                    ]
                };
            } else {
                // Если URL не указан, используем стандартный текст
                text = config.texts.sub_warning_text.replace('{user_mention}', getMention(user));
            }

            const sentWarning = sendTelegram('sendMessage', { 
                chat_id: chat.id, 
                text: text, 
                parse_mode: 'HTML',
                reply_markup: keyboard ? JSON.stringify(keyboard) : undefined,
                disable_web_page_preview: true
            });
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

        const muteUntil = Math.floor(new Date().getTime() / 1000 + muteDurationMin * 60);
        restrictUser(chatId, userId, false, muteUntil);

        if (userData) {
            usersSheet.getRange(userData.rowIndex, 2).setValue(newLevel);
        } else {
            usersSheet.appendRow([userId, newLevel, new Date()]);
        }

        const text = config.texts.sub_mute_text
            .replace('{user_mention}', getMention(user))
            .replace('{duration}', muteDurationMin);
        const sentMuteMsg = sendTelegram('sendMessage', { chat_id: chatId, text: text, parse_mode: 'HTML' });
        if (sentMuteMsg?.ok) {
            addMessageToCleaner(chatId, sentMuteMsg.result.message_id, 45, services);
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
