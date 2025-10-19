/**
 * @file Triggers.gs
 * @description Manages time-based and event-driven triggers for the script.
 */

/**
 * Creates a one-time trigger to execute a function after a delay.
 * @param {String} functionName The name of the function to trigger.
 * @param {Number} delayInSeconds The delay in seconds.
 * @param {Object} args An object containing arguments to pass to the triggered function.
 */
function createOneTimeTrigger(functionName, delayInSeconds, args) {
  const triggerTime = Date.now() + delayInSeconds * 1000;
  // Apps Script triggers can be unreliable for short intervals.
  // It's better to use a minimum of one minute.
  if (delayInSeconds < 60) {
      Utilities.sleep(delayInSeconds * 1000); // For short delays, just sleep the thread.
      this[functionName]({parameter: args}); // and call the function directly.
      return;
  }
  ScriptApp.newTrigger(functionName)
    .timeBased()
    .at(new Date(triggerTime))
    .withParameters(args)
    .create();
}

/**
 * Handler for the CAPTCHA timeout trigger.
 * Mutes the user if they haven't passed the CAPTCHA in time.
 * @param {Object} e The event object from the trigger, containing arguments like {userId: '123'}.
 */
function captchaTimeoutHandler(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);

  try {
    const userId = e.parameter.userId;
    if (!userId) return;

    const userRow = findUserRow(userId);

    if (userRow && userRow.data.state === 'PENDING_CAPTCHA') {
      const chatId = userRow.data.chat_id;
      const durationMinutes = parseInt(getSetting('restriction_duration_minutes'), 10) || 30;
      const untilDate = Math.floor(Date.now() / 1000) + durationMinutes * 60;

      // Mute the user (they are already muted, just formalize it with a duration)
      const permissions = { can_send_messages: false };
      restrictChatMember(chatId, userId, permissions, untilDate);

      // Update state in sheet
      userRow.data.state = 'RESTRICTED';
      userRow.data.restricted_until_ts = untilDate;
      updateUserData(userRow.rowNum, userRow.data);

      // Delete CAPTCHA message and notify
      deleteMessage(chatId, userRow.data.last_message_id);
      let muteMessage = getMessage('captcha_timeout_mute').replace('{username}', `@User_${userId}`);
      sendMessage(chatId, muteMessage);
      
      // Set a trigger to un-restrict them later
      createOneTimeTrigger('unrestrictHandler', durationMinutes * 60, { userId: userId });
    }
  } finally {
    lock.releaseLock();
  }
}

/**
 * Handler for the un-restriction trigger.
 * Restores default permissions for the user.
 * @param {Object} e The event object from the trigger, containing arguments like {userId: '123'}.
 */
function unrestrictHandler(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);

  try {
    const userId = e.parameter.userId;
    if (!userId) return;

    const userRow = findUserRow(userId);

    if (userRow && userRow.data.state === 'RESTRICTED') {
      const chatId = userRow.data.chat_id;

      // Restore default permissions
      const permissions = { can_send_messages: true };
      restrictChatMember(chatId, userId, permissions);

      // Update user state
      userRow.data.state = 'ACTIVE';
      userRow.data.violation_count = 0;
      userRow.data.restricted_until_ts = '';
      updateUserData(userRow.rowNum, userRow.data);
    }
  } finally {
    lock.releaseLock();
  }
}

/**
 * Sets up a recurring trigger for cleanup tasks.
 */
function setupCleanupTrigger() {
  const allTriggers = ScriptApp.getProjectTriggers();
  if (!allTriggers.some(t => t.getHandlerFunction() === 'cleanupRoutine')) {
    ScriptApp.newTrigger('cleanupRoutine').timeBased().everyHours(1).create();
    Logger.log('Cleanup trigger created.');
  }
}

/**
 * Performs routine cleanup tasks.
 */
function cleanupRoutine() {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const allUsers = getAllUsers();
    const now = Math.floor(Date.now() / 1000);
    allUsers.forEach(user => {
      if (user.state === 'RESTRICTED' && user.restricted_until_ts > 0 && now > user.restricted_until_ts) {
        unrestrictHandler({ parameter: { userId: user.user_id } });
      }
    });
  } finally {
    lock.releaseLock();
  }
}
