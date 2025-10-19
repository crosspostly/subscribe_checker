/**
 * @file Settings.gs
 * @description Manages loading and accessing settings and messages from the cache.
 */

/**
 * Loads all settings and messages from the 'Config' and 'Messages' sheets into CacheService.
 * Should be called at the beginning of key operations to ensure the cache is warm.
 */
function loadSettingsAndMessagesToCache() {
  // 1. Read 'Config' sheet into an object.
  // 2. Read 'Messages' sheet into an object.
  // 3. Store both objects in CacheService.
}

/**
 * Retrieves a specific setting value by its key.
 * @param {String} key The key of the setting (e.g., 'chat_id').
 * @returns {String|Boolean|Number} The value of the setting.
 */
function getSetting(key) {
  // Reads the settings object from cache and returns the value for the key.
}

/**
 * Retrieves a specific message template by its key.
 * @param {String} key The key of the message (e.g., 'captcha_question').
 * @returns {String} The message template.
 */
function getMessage(key) {
  // Reads the messages object from cache and returns the value for the key.
}
