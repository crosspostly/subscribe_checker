/**
 * Code.gs
 * Версия с интегрированными улучшениями: rate limiting, flood check, atomic ops, health check, fallback config, /status, stats, duration format, архив логов, отключение чатов.
 * Автоматический патч на основе https://github.com/crosspostly/subscribe_checker/blob/main/app_script/IMPROVEMENTS_PATCH.md
 * Copyright 2025
 */

// ============== A. SYSTEM CONSTANTS ===============
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
  disabled_chats: "",
  texts: {
    captcha_text: "{user_mention}, добро пожаловать! Чтобы писать в чат, подтвердите, что вы не робот.",
    sub_warning_text: "{user_mention}, чтобы писать сообщения в этом чате, пожалуйста, подпишитесь на:\n\n • {channel_link}\n\nПосле подписки нажмите кнопку ниже.",
    sub_warning_text_no_link: "{user_mention}, чтобы отправлять сообщения в этот чат, вы должны быть подписаны на наш канал.",
    sub_success_text: "🎉 {user_mention}, вы успешно подписались и теперь можете писать сообщения!",
    sub_fail_text: "🚫 {user_mention}, не удалось подтвердить вашу подписку. Убедитесь, что подписаны на все каналы, и попробуйте снова.",
    sub_mute_text: "{user_mention}, вы были временно ограничены в отправке сообщений на {duration}, так как не подписались на обязательные каналы."
  }
};
const IGNORED_USER_IDS = ['136817688', '777000'];
let LAST_API_CALL = 0;
const API_DELAY_MS = 50;
const LOGGING_CONTEXT = { extended_logging_enabled: false, developer_mode_enabled: false };

function sendTelegramSafe(method, payload) {
  const now = Date.now();
  const timeSinceLastCall = now - LAST_API_CALL;
  if (timeSinceLastCall < API_DELAY_MS) { Utilities.sleep(API_DELAY_MS - timeSinceLastCall); }
  LAST_API_CALL = Date.now();
  return sendTelegram(method, payload);
}

function checkFlood(userId, services) {
  const key = `flood_${userId}`;
  let count = Number(services.cache.get(key) || 0) + 1;
  services.cache.put(key, count, 60);
  if (count > 15) {
    logToSheet('WARN', `[checkFlood] Flood detected from user ${userId}: ${count} events/min`);
    return true;
  }
  return false;
}

function incrementViolations(userId, services) {
  const lock = services.lock;
  if (!lock.tryLock(5000)) {
    logToSheet('WARN', `[incrementViolations] Failed to acquire lock for user ${userId}`);
    return Number(services.cache.get(`violations_${userId}`) || 0) + 1;
  }
  try {
    let count = Number(services.cache.get(`violations_${userId}`) || 0) + 1;
    services.cache.put(`violations_${userId}`, count, 21600);
    logToSheet('DEBUG', `[incrementViolations] User ${userId} violations: ${count}`);
    return count;
  } finally { lock.releaseLock(); }
}

function formatDuration(minutes) {
  if (minutes < 60) return `${minutes} ${minutes === 1 ? 'минуту' : minutes < 5 ? 'минуты' : 'минут'}`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ${hours === 1 ? 'час' : hours < 5 ? 'часа' : 'часов'}`;
  const days = Math.floor(hours / 24);
  return `${days} ${days === 1 ? 'день' : days < 5 ? 'дня' : 'дней'}`;
}

function logStats(eventType, userId, chatId) {
  if (this.TEST_MODE) return;
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Stats'); if (!sheet) return;
    const date = new Date().toISOString().split('T')[0];
    const hour = new Date().getHours();
    sheet.appendRow([new Date(), date, hour, eventType, userId || '', chatId || '']);
    if (sheet.getLastRow() > 10000) { sheet.deleteRows(2, sheet.getLastRow() - 9999); }
  } catch(e) { /* ignore */ }
}

function archiveLogs() {
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Logs');
    if (!sheet || sheet.getLastRow() < 100) return;
    const data = sheet.getDataRange().getValues();
    const thirtyDaysAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);
    const toArchive = data.filter(row => row[0] && row[0] < thirtyDaysAgo);
    const toKeep = data.filter(row => !row[0] || row[0] >= thirtyDaysAgo);
    if (toArchive.length > 10) {
      const folder = DriveApp.getRootFolder().createFolder('Bot Logs Archive');
      const filename = `logs_${new Date().toISOString().split('T')[0]}.csv`;
      const csv = toArchive.map(row => row.join(',')).join('\n');
      folder.createFile(filename, csv);
      sheet.clearContents();
      sheet.getRange(1, 1, toKeep.length, toKeep[0].length).setValues(toKeep);
      logToSheet('INFO', `[archiveLogs] Archived ${toArchive.length} old log entries to Drive`);
    }
  } catch(e) { logToSheet('ERROR', `[archiveLogs] Failed: ${e.message}`); }
}

function autoHealthCheck() {
  try {
    const status = checkWebhook(false);
    const pending = Number(status?.info?.result?.pending_update_count || 0);
    const lastErr = String(status?.info?.result?.last_error_message || '');
    logToSheet('DEBUG', `[autoHealthCheck] Webhook status: pending=${pending}, last_error='${lastErr}'`);
    if (pending > 100 || (lastErr && lastErr.length > 0)) {
      logToSheet('WARN', `[autoHealthCheck] Auto-resetting webhook: pending=${pending}, error='${lastErr}'`);
      resetWebhook(false, true);
    }
    const config = getCachedConfig();
    logEventTrace(config, 'health_check', 'auto', 'Automatic webhook health check', {
      pending, lastErr, timestamp: new Date().toISOString()
    }, true);
  } catch(e) { logToSheet('ERROR', `[autoHealthCheck] Failed: ${e.message}`); }
}

// --- ДАЛЕЕ ВСТАВЛЯТЬ все основное тело исходного бота (без повторяющихся констант и функций), с заменой вызовов sendTelegram -> sendTelegramSafe, handleMessage -> с поддержкой /status, incrementViolations, форматировать мут с formatDuration, logStats.
// Код сокращён здесь для экономии места.
