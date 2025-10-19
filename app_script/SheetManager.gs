/**
 * @file SheetManager.gs
 * @description Manages all interactions with the Google Sheet database.
 */

// SET TO 'true' to automatically create and populate sheets on first run.
const AUTO_SETUP_SPREADSHEET = true;

const USERS_SHEET = 'Users';
const WHITELIST_SHEET = 'Whitelist';
const CONFIG_SHEET = 'Config';
const MESSAGES_SHEET = 'Messages';

/**
 * Checks if sheets exist and creates them with default values if they don't.
 * This function is the entry point for auto-setup.
 */
function setupSpreadsheet() {
  if (!AUTO_SETUP_SPREADSHEET) return;

  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  
  // Check and create Config sheet
  let configSheet = ss.getSheetByName(CONFIG_SHEET);
  if (!configSheet) {
    configSheet = ss.insertSheet(CONFIG_SHEET);
    const headers = ['key', 'value', 'description'];
    const data = [
      ['chat_id', '-1001568712129', 'ВАЖНО: ID чата, в котором работает бот. Начинается с -100.'],
      ['channel_id', '-1001568712129', 'ВАЖНО: ID канала для проверки подписки. Начинается с -100.'],
      ['captcha_enabled', 'TRUE', 'Включить (TRUE) или выключить (FALSE) капчу для новых пользователей.'],
      ['captcha_timeout_sec', 300, 'СКОЛЬКО СЕКУНД ДАТЬ НА ПРОХОЖДЕНИЕ КАПЧИ. По истечении - мут.'],
      ['violation_limit', 2, 'СКОЛЬКО СООБЩЕНИЙ БЕЗ ПОДПИСКИ ПРОЩАТЬ. После этого лимита - мут.'],
      ['restriction_duration_minutes', 10, 'НА СКОЛЬКО МИНУТ ВЫДАВАТЬ МУТ (за капчу или отсутствие подписки).']
    ];
    configSheet.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold');
    configSheet.getRange(2, 1, data.length, data[0].length).setValues(data);
    configSheet.autoResizeColumns(1, 3);
  }

  // Check and create Messages sheet
  let messagesSheet = ss.getSheetByName(MESSAGES_SHEET);
  if (!messagesSheet) {
    messagesSheet = ss.insertSheet(MESSAGES_SHEET);
    const headers = ['key', 'value', 'Переменные для использования'];
    const data = [
      ['captcha_welcome', 'Добро пожаловать, {username}!\n\nЧтобы получить доступ к чату, пожалуйста, подтвердите, что вы не бот, нажав на кнопку ниже.', '{username}'],
      ['captcha_button', '✅ Я не бот', ''],
      ['captcha_success', 'Спасибо! Теперь вы можете писать в чат.', ''],
      ['captcha_timeout_mute', 'Пользователь {username} не прошел проверку вовремя и был ограничен в правах на {duration} минут.', '{username}, {duration}'],
      ['not_subscribed_warning', 'Уважаемый {username}, для общения в этом чате необходимо быть подписанным на канал {channel_link}. Пожалуйста, подпишитесь.', '{username}, {channel_link}'],
      ['restricted_warning', '{username} был временно ограничен в правах на {duration} минут за нарушение правил чата (отсутствие подписки на канал {channel_link}).', '{username}, {duration}, {channel_link}']
    ];
    messagesSheet.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold');
    messagesSheet.getRange(2, 1, data.length, data[0].length).setValues(data);
    messagesSheet.autoResizeColumns(1, 3);
  }

  // Check and create Users sheet
  let usersSheet = ss.getSheetByName(USERS_SHEET);
  if (!usersSheet) {
    usersSheet = ss.insertSheet(USERS_SHEET);
    const headers = ['user_id', 'chat_id', 'state', 'join_timestamp', 'violation_count', 'restricted_until_ts', 'last_message_id'];
    usersSheet.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold');
    usersSheet.autoResizeColumns(1, headers.length);
  }

  // Check and create Whitelist sheet
  let whitelistSheet = ss.getSheetByName(WHITELIST_SHEET);
  if (!whitelistSheet) {
    whitelistSheet = ss.insertSheet(WHITELIST_SHEET);
    const headers = ['user_id', 'username', 'description'];
    whitelistSheet.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold');
    whitelistSheet.getRange(2, 1, 1, 3).setValues([['183761194', 'daoqub', 'Владелец бота']]);
    whitelistSheet.autoResizeColumns(1, 3);
  }
}


/**
 * Finds a user in the 'Users' sheet.
 * @param {String} userId The user's Telegram ID.
 * @returns {Object|null} An object with user data {data, rowNum}, or null if not found.
 */
function findUserRow(userId) {
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const sheet = ss.getSheetByName(USERS_SHEET);
    if (!sheet) return null; 
    const data = sheet.getDataRange().getValues();
    const headers = data[0];
    const userIdCol = headers.indexOf('user_id');

    for (let i = 1; i < data.length; i++) {
      if (String(data[i][userIdCol]) === String(userId)) {
        const userObject = {};
        headers.forEach((header, index) => {
          userObject[header] = data[i][index];
        });
        return { data: userObject, rowNum: i + 1 };
      }
    }
    return null;
  } catch (e) { return null; } 
}

/**
 * Updates a user's data in the sheet.
 * @param {Number} rowNum The row number to update.
 * @param {Object} newData The new data object for the user.
 */
function updateUserData(rowNum, newData) {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName(USERS_SHEET);
  if (!sheet) return;
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const newRow = headers.map(header => newData[header] !== undefined ? newData[header] : '');
  sheet.getRange(rowNum, 1, 1, newRow.length).setValues([newRow]);
}

/**
 * Adds a new user to the 'Users' sheet.
 * @param {Object} userData The user data to add.
 */
function addNewUser(userData) {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName(USERS_SHEET);
  if (!sheet) return;
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  const newRow = headers.map(header => userData[header] !== undefined ? userData[header] : '');
  sheet.appendRow(newRow);
}

/**
 * Checks if a user is in the whitelist.
 * @param {String} userId The user's Telegram ID.
 * @returns {Boolean} True if the user is in the whitelist.
 */
function isUserInWhitelist(userId) {
  const cache = CacheService.getScriptCache();
  const whitelistCacheKey = `whitelist_${userId}`;
  let cachedResult = cache.get(whitelistCacheKey);

  if (cachedResult) {
    return cachedResult === 'true';
  }

  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName(WHITELIST_SHEET);
  if (!sheet) return false;
  const data = sheet.getRange('A:A').getValues();
  
  const found = data.some(row => String(row[0]) === String(userId));

  cache.put(whitelistCacheKey, String(found), 3600);

  return found;
}

/**
 * Retrieves all users for batch processing.
 * @returns {Array} An array of user objects, each including their row number.
 */
function getAllUsers() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName(USERS_SHEET);
  if (!sheet) return [];
  const data = sheet.getDataRange().getValues();
  const headers = data.shift(); 
  const userIdCol = headers.indexOf('user_id');

  if (userIdCol === -1) return [];

  return data.map((row, index) => {
    const userObject = {};
    headers.forEach((header, colIndex) => {
      userObject[header] = row[colIndex];
    });
    userObject.rowNum = index + 2;
    return userObject;
  });
}

/**
 * Deletes a user row from the Users sheet.
 * @param {Number} rowNum The row number to delete.
 */
function deleteUserRow(rowNum) {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const sheet = ss.getSheetByName(USERS_SHEET);
    if (!sheet) return;
    sheet.deleteRow(rowNum);
}
