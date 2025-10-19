/**
 * @file Webhook.gs
 * @description Handles incoming webhooks from Telegram and provides setup functions.
 */

// A global function to be called from the menu to run all setup tasks
function InitialSetup() {
  // 1. Set up the spreadsheet structure and default values
  try {
    setupSpreadsheet();
    Browser.msgBox('Step 1/3: Spreadsheet setup complete. Sheets created/verified.');
  } catch (e) {
    Browser.msgBox(`Error in Spreadsheet setup: ${e.message}`);
    return;
  }

  // 2. Set the Telegram webhook
  try {
    const webhookResponse = setWebhook();
    Browser.msgBox(`Step 2/3: Webhook setup complete. Response: ${webhookResponse}`);
  } catch (e) {
    Browser.msgBox(`Error in Webhook setup: ${e.message}`);
    return;
  }

  // 3. Set up the recurring cleanup trigger
  try {
    setupCleanupTrigger();
    Browser.msgBox('Step 3/3: Cleanup trigger setup complete. Your bot is now fully configured and running!');
  } catch (e) {
    Browser.msgBox(`Error in Cleanup Trigger setup: ${e.message}`);
  }
}


/**
 * The main function that processes POST requests from Telegram.
 * @param {Object} e The event parameter from the Apps Script trigger.
 */
function doPost(e) {
  try {
    const update = JSON.parse(e.postData.contents);
    Logger.log(JSON.stringify(update, null, 2));
    handleUpdate(update);
  } catch (error) {
    Logger.log(`Error in doPost: ${error.toString()}\n${error.stack}`);
  }
  return ContentService.createTextOutput(JSON.stringify({ ok: true }));
}

/**
 * Sets the Telegram webhook to this script's URL.
 */
function setWebhook() {
  const url = ScriptApp.getService().getUrl();
  const response = safeTelegramApiCall('setWebhook', {
    url: url,
    allowed_updates: ['message', 'chat_member', 'callback_query'],
  });
  return JSON.stringify(response);
}

/**
 * Utility function to get webhook information.
 */
function getWebhookInfo() {
    const response = safeTelegramApiCall('getWebhookInfo', {});
    Browser.msgBox(JSON.stringify(response, null, 2));
}
