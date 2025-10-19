/**
 * @file TelegramAPI.gs
 * @description Wrapper functions for all Telegram Bot API calls.
 */

const BOT_TOKEN = PropertiesService.getScriptProperties().getProperty('BOT_TOKEN');

/**
 * A safe, rate-limited, and lock-protected wrapper for all Telegram API calls.
 * @param {String} method The Telegram API method name (e.g., 'sendMessage').
 * @param {Object} payload The JSON payload for the API method.
 * @returns {Object} The parsed JSON response from Telegram.
 */
function safeTelegramApiCall(method, payload) {
  const lock = LockService.getScriptLock();
  // Wait up to 10 seconds for the lock to become available.
  try {
    lock.waitLock(10000);
  } catch (e) {
    Logger.log('Could not acquire lock after 10 seconds.');
    return { ok: false, description: 'Could not acquire lock' };
  }

  try {
    // Basic rate limiting: ensure at least 50ms between calls.
    const cache = CacheService.getScriptCache();
    const lastCallTimestamp = cache.get('lastApiCallTimestamp');
    const now = Date.now();

    if (lastCallTimestamp) {
      const timeSinceLastCall = now - parseInt(lastCallTimestamp, 10);
      if (timeSinceLastCall < 50) { // Approx. 20 calls/sec
        Utilities.sleep(50 - timeSinceLastCall);
      }
    }
    cache.put('lastApiCallTimestamp', String(Date.now()), 1); // Cache for 1 second.

    const url = `https://api.telegram.org/bot${BOT_TOKEN}/${method}`;
    const options = {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify(payload),
      muteHttpExceptions: true, // IMPORTANT: Allows us to handle errors gracefully.
    };

    const response = UrlFetchApp.fetch(url, options);
    const responseCode = response.getResponseCode();
    const responseText = response.getContentText();

    if (responseCode !== 200) {
      Logger.log(`API Error: ${method} failed with code ${responseCode}. Response: ${responseText}`);
    }

    return JSON.parse(responseText);

  } catch (error) {
    Logger.log(`Exception in safeTelegramApiCall: ${error.message}`);
    return { ok: false, description: `Exception: ${error.message}` };
  } finally {
    lock.releaseLock(); // ALWAYS release the lock.
  }
}

// --- Helper functions utilizing the safe wrapper ---

/**
 * Sends a message.
 * @param {String} chatId The ID of the chat.
 * @param {String} text The text of the message.
 * @param {Object} [replyMarkup] Optional: An object for an inline keyboard.
 * @returns {Object} The API response from Telegram.
 */
function sendMessage(chatId, text, replyMarkup) {
  const payload = {
    chat_id: chatId,
    text: text,
    parse_mode: 'Markdown',
  };
  if (replyMarkup) {
    payload.reply_markup = replyMarkup;
  }
  return safeTelegramApiCall('sendMessage', payload);
}

/**
 * Deletes a message.
 * @param {String} chatId The ID of the chat.
 * @param {String} messageId The ID of the message to delete.
 * @returns {Object} The API response from Telegram.
 */
function deleteMessage(chatId, messageId) {
  const payload = {
    chat_id: chatId,
    message_id: messageId,
  };
  return safeTelegramApiCall('deleteMessage', payload);
}

/**
 * Restricts a chat member.
 * @param {String} chatId The ID of the chat.
 * @param {String} userId The ID of the user to restrict.
 * @param {Object} permissions The permissions object.
 * @param {Number} [untilDate] Optional: Unix timestamp for when the restriction lifts.
 * @returns {Object} The API response from Telegram.
 */
function restrictChatMember(chatId, userId, permissions, untilDate) {
  const payload = {
    chat_id: chatId,
    user_id: userId,
    permissions: permissions,
  };
  if (untilDate) {
    payload.until_date = untilDate;
  }
  return safeTelegramApiCall('restrictChatMember', payload);
}

/**
 * Gets information about a chat member.
 * @param {String} chatId The ID of the chat.
 * @param {String} userId The ID of the user.
 * @returns {Object} The API response from Telegram.
 */
function getChatMember(chatId, userId) {
  const payload = {
    chat_id: chatId,
    user_id: userId,
  };
  return safeTelegramApiCall('getChatMember', payload);
}

/**
 * Answers a callback query (from an inline button press).
 * @param {String} callbackQueryId The ID of the callback query.
 * @param {String} [text] Optional: Text to show as a notification.
 * @param {Boolean} [showAlert] Optional: Whether to show the text as an alert.
 * @returns {Object} The API response from Telegram.
 */
function answerCallbackQuery(callbackQueryId, text, showAlert) {
  const payload = {
    callback_query_id: callbackQueryId,
  };
  if (text) {
    payload.text = text;
  }
  if (showAlert) {
    payload.show_alert = showAlert;
  }
  return safeTelegramApiCall('answerCallbackQuery', payload);
}
