/**
 * @file Settings.gs
 * @description Manages loading and accessing settings and messages from the cache.
 */

const SPREADSHEET_ID = PropertiesService.getScriptProperties().getProperty('SPREADSHEET_ID');
const CONFIG_SHEET = 'Config';
const MESSAGES_SHEET = 'Messages';

/**
 * Loads all settings and messages from the 'Config' and 'Messages' sheets into CacheService.
 * Should be called at the beginning of key operations to ensure the cache is warm.
 */
function loadSettingsAndMessagesToCache() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const cache = CacheService.getScriptCache();

  // Load Settings
  const configSheet = ss.getSheetByName(CONFIG_SHEET);
  const configData = configSheet.getDataRange().getValues();
  const settings = {};
  // Assuming the first row is header, and there's only one row of settings
  if (configData.length > 1) {
    const headers = configData[0];
    const values = configData[1];
    headers.forEach((key, index) => {
      settings[key] = values[index];
    });
  }
  cache.put('settings', JSON.stringify(settings), 21600); // Cache for 6 hours

  // Load Messages
  const messagesSheet = ss.getSheetByName(MESSAGES_SHEET);
  const messagesData = messagesSheet.getDataRange().getValues();
  const messages = {};
  if (messagesData.length > 1) {
    messagesData.slice(1).forEach(row => {
      const key = row[0];
      const text = row[1];
      if (key) {
        messages[key] = text;
      }
    });
  }
  cache.put('messages', JSON.stringify(messages), 21600); // Cache for 6 hours

  Logger.log('Settings and Messages have been loaded into cache.');
}

/**
 * Retrieves a cached object.
 * @param {String} key The key for the cache ('settings' or 'messages').
 * @returns {Object} The parsed object from cache.
 */
function getCachedObject(key) {
  const cache = CacheService.getScriptCache();
  let cachedData = cache.get(key);
  if (!cachedData) {
    Logger.log(`Cache miss for ${key}. Reloading cache...`);
    loadSettingsAndMessagesToCache();
    cachedData = cache.get(key);
  }
  return JSON.parse(cachedData || '{}');
}

/**
 * Retrieves a specific setting value by its key.
 * @param {String} key The key of the setting (e.g., 'chat_id').
 * @returns {String|Boolean|Number} The value of the setting.
 */
function getSetting(key) {
  return getCachedObject('settings')[key];
}

/**
 * Retrieves a specific message template by its key.
 * @param {String} key The key of the message (e.g., 'captcha_question').
 * @returns {String} The message template.
 */
function getMessage(key) {
  return getCachedObject('messages')[key];
}
