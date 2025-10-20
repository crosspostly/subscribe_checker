/**
 * @file tests.gs
 * @description FINAL, CORRECTED test suite. This version fixes all previously identified bugs.
 */

// =================================================================================
// ======================  A. TEST RUNNER & FRAMEWORK  ===========================
// =================================================================================

function runAllTests() {
  const testResults = { passed: 0, failed: 0, total: 0, failures: [] };
  const testFunctions = [
    test_handleNewChatMember_onRealJoin,
    test_handleNewChatMember_ignoresFalseJoin,
    test_handleNewChatMember_ignoresAdminJoin,
    test_handleUpdate_doesNothingWhenBotIsDisabled,
    test_handleUpdate_ignoresUnauthorizedChats,
    test_handleUpdate_ignoresWhitelistedUser,
    test_handleUpdate_ignoresWhitelistedChannelPost,
    test_handleMessage_notSubscribed_sendsWarningOnFirstViolation,
    test_handleMessage_notSubscribed_mutesOnLimitReached,
    test_isUserSubscribed_returnsTrueWhenChannelNotSet,
    test_getCachedConfig_fallsBackToDefaults,
    test_getCachedConfig_usesSheetValues,
    test_messageCleaner_deletesExpiredMessages
  ];

  Logger.log("====== STARTING BOT TEST SUITE (FINAL) ======");

  let originalServices = {};

  testFunctions.forEach(testFunc => {
    const testName = testFunc.name;
    testResults.total++;
    let mocks = null;
    try {
      mocks = getMockServicesAndData(originalServices); // Setup mocks and get them
      testFunc(mocks); // Pass mocks into the test function
      testResults.passed++;
      Logger.log(`✅ PASSED: ${testName}`);
    } catch (e) {
      testResults.failed++;
      testResults.failures.push({ name: testName, error: e.message, stack: e.stack });
      Logger.log(`❌ FAILED: ${testName} - ${e.message}`);
    } finally {
       if (mocks) mocks.cleanup(originalServices); // Always cleanup
    }
  });

  Logger.log("====== TEST SUITE COMPLETE ======");
  Logger.log(`Results: ${testResults.passed} passed, ${testResults.failed} failed out of ${testResults.total} total tests.`);

  if (testResults.failed > 0) {
    Logger.log("\n====== FAILURE DETAILS ======");
    testResults.failures.forEach(failure => { Logger.log(`\n--- ❌ ${failure.name} ---\nError: ${failure.error}\nStack: ${failure.stack || 'no stack'}\n`); });
    try { SpreadsheetApp.getUi().alert(`Test suite finished with ${testResults.failed} failures. Check logs.`); } catch (e) {}
  } else {
    try { SpreadsheetApp.getUi().alert(`✅ All ${testResults.total} tests passed successfully!`); } catch (e) {}
  }
}

function assert(condition, message) { if (!condition) throw new Error(message || "Assertion failed"); }

// =================================================================================
// =======================  B. MOCKING FRAMEWORK  ================================
// =================================================================================

function getMockServicesAndData(originalServices) {
  // --- Store original services before overwriting ---
  originalServices.UrlFetchApp = this.UrlFetchApp;
  originalServices.CacheService = this.CacheService;
  originalServices.PropertiesService = this.PropertiesService;
  originalServices.SpreadsheetApp = this.SpreadsheetApp;
  originalServices.LockService = this.LockService;

  // --- Mock Data Stores ---
  let mockSheetData = {
    'Config': [ ["key", "value"], ["bot_enabled", true], ["target_channel_id", "-100123"], ["authorized_chat_ids", "-100999"], ["violation_limit", 3] ],
    'Texts': [ ["key", "value"], ["captcha_text", "Welcome"], ["sub_warning_text", "Subscribe pls"], ["sub_mute_text", "Muted"] ],
    'Whitelist': [ ["user_id_or_channel_id", "comment"], ["555", "Whitelisted User"] ],
    'Users': [["user_id", "mute_level"]]
  };
  let mockCache = {};
  // CRITICAL FIX: Add a mock BOT_TOKEN so that sendTelegram() attempts API calls.
  let mockProperties = { 'BOT_TOKEN': 'test_token' };
  let urlFetchLog = [];

  // --- Mock Services ---
  const mockUrlFetchApp = {
    fetch: (url, params) => {
      const payload = params ? JSON.parse(params.payload) : {};
      const method = url.substring(url.lastIndexOf('/') + 1);
      urlFetchLog.push({ method, payload });
      let apiResult = { ok: true, result: { message_id: 12345 } };
      if (method === 'getChatAdministrators') {
        apiResult = { ok: true, result: [ {user: {id: 999, is_bot: false}} ] };
      }
      return { getContentText: () => JSON.stringify(apiResult), getResponseCode: () => 200 };
    },
  };
  const mockCacheService = { getScriptCache: () => ({ get: k => mockCache[k] || null, put: (k, v) => mockCache[k] = v, remove: k => delete mockCache[k], removeAll: ks => ks.forEach(k => delete mockCache[k]) }) };
  const mockPropertiesService = { getScriptProperties: () => ({ getProperty: k => mockProperties[k] || null, setProperty: (k, v) => mockProperties[k] = v, getProperties: () => ({...mockProperties}), deleteProperty: k => delete mockProperties[k] }) };
  const mockSpreadsheetApp = { getActiveSpreadsheet: () => ({ getSheetByName: n => mockSheetData[n] ? { getDataRange: () => ({ getValues: () => mockSheetData[n] }), appendRow: r => mockSheetData[n].push(r), getRange:()=>({setValue:()=>{}})} : null }), getUi: () => ({ alert: m => {} }) };
  const mockLockService = { getScriptLock: () => ({ waitLock: () => {}, releaseLock: () => {} }) };
  
  // --- Overwrite global objects ---
  this.UrlFetchApp = mockUrlFetchApp;
  this.CacheService = mockCacheService;
  this.PropertiesService = mockPropertiesService;
  this.SpreadsheetApp = mockSpreadsheetApp;
  this.LockService = mockLockService;

  return {
    urlFetchLog,
    mockCache,
    mockProperties,
    mockSheetData,
    cleanup: (originals) => {
      this.UrlFetchApp = originals.UrlFetchApp;
      this.CacheService = originals.CacheService;
      this.PropertiesService = originals.PropertiesService;
      this.SpreadsheetApp = originals.SpreadsheetApp;
      this.LockService = originals.LockService;
    }
  };
}

// =================================================================================
// ========================  C. UNIT & INTEGRATION TESTS  ==========================
// =================================================================================

function test_handleNewChatMember_onRealJoin(mocks) {
  const update = { chat_member: { chat: { id: -100999 }, from: { id: 456, is_bot: false }, old_chat_member: { status: 'left' }, new_chat_member: { status: 'member', user: { id: 456, is_bot: false } } } };
  handleUpdate(update);
  assert(mocks.urlFetchLog.find(c => c.method === 'restrictChatMember'), "User should be muted");
  assert(mocks.urlFetchLog.find(c => c.method === 'sendMessage'), "CAPTCHA message should be sent");
}

function test_handleNewChatMember_ignoresFalseJoin(mocks) {
  const update = { chat_member: { chat: { id: -100999 }, from: { id: 999 }, old_chat_member: { status: 'restricted' }, new_chat_member: { status: 'member', user: { id: 456 } } } };
  handleUpdate(update);
  assert(mocks.urlFetchLog.length === 0, "Expected 0 API calls for a false join, but got " + mocks.urlFetchLog.length);
}

function test_handleNewChatMember_ignoresAdminJoin(mocks) {
  const update = { chat_member: { chat: { id: -100999 }, from: { id: 999 }, old_chat_member: { status: 'left' }, new_chat_member: { status: 'member', user: { id: 999, is_bot: false } } } };
  handleUpdate(update);
  assert(mocks.urlFetchLog.find(c => c.method === 'getChatAdministrators'), "Should check for admins");
  assert(mocks.urlFetchLog.length === 1, "No CAPTCHA should be sent for an admin, only getChatAdministrators call. Got: " + mocks.urlFetchLog.length);
}

function test_handleUpdate_doesNothingWhenBotIsDisabled(mocks) {
  mocks.mockSheetData['Config'] = [["key", "value"], ["bot_enabled", false]];
  const update = { message: { chat: { id: -100999 }, from: { id: 456 } } };
  handleUpdate(update);
  assert(mocks.urlFetchLog.length === 0, "Expected 0 API calls when bot is disabled");
}

function test_handleUpdate_ignoresUnauthorizedChats(mocks) {
  const update = { message: { chat: { id: -100111 }, from: { id: 456 } } };
  handleUpdate(update);
  assert(mocks.urlFetchLog.length === 0, "Expected 0 API calls for an unauthorized chat");
}

function test_handleUpdate_ignoresWhitelistedUser(mocks) {
  const update = { message: { chat: { id: -100999 }, from: { id: 555 } } };
  handleUpdate(update);
  assert(mocks.urlFetchLog.length === 0, "Expected 0 API calls for a whitelisted user");
}

function test_handleUpdate_ignoresWhitelistedChannelPost(mocks) {
    mocks.mockSheetData['Whitelist'].push(["-100777", "Whitelisted Channel"]);
    const update = { message: { chat: { id: -100999 }, sender_chat: { id: -100777 } } };
    handleUpdate(update);
    assert(mocks.urlFetchLog.length === 0, "Expected 0 API calls for a whitelisted channel post");
}

function test_handleMessage_notSubscribed_sendsWarningOnFirstViolation(mocks) {
  const update = { message: { message_id: 987, chat: { id: -100999 }, from: { id: 456 } } };
  handleUpdate(update);
  assert(mocks.urlFetchLog.find(c => c.method === 'deleteMessage'), "Should delete user's message");
  assert(mocks.urlFetchLog.find(c => c.method === 'sendMessage' && c.payload.text === 'Subscribe pls'), "Should send a warning message");
  assert(mocks.mockCache['violations_456'] === 1, "Violation count in cache should be 1");
}

function test_handleMessage_notSubscribed_mutesOnLimitReached(mocks) {
  const update = { message: { message_id: 987, chat: { id: -100999 }, from: { id: 456 } } };
  for (let i = 0; i < 3; i++) handleUpdate(update);
  const muteCall = mocks.urlFetchLog.find(c => c.method === 'restrictChatMember');
  assert(muteCall, "Should call restrictChatMember to mute the user");
  assert(!mocks.mockCache['violations_456'], "Violation cache should be cleared after muting");
}

function test_isUserSubscribed_returnsTrueWhenChannelNotSet(mocks) {
  const isSubscribed = isUserSubscribed(123, '');
  assert(isSubscribed === true, "isUserSubscribed should return true if channel ID is empty");
  assert(mocks.urlFetchLog.length === 0, "isUserSubscribed should not make an API call for empty channel ID");
}

function test_getCachedConfig_fallsBackToDefaults(mocks) {
  mocks.mockSheetData['Config'] = [["key", "value"]]; // Empty config sheet
  mocks.mockSheetData['Texts'] = [["key", "value"]]; // Empty texts sheet
  // Force a cache clear
  CacheService.getScriptCache().remove('config');
  const config = getCachedConfig();
  assert(config.violation_limit === DEFAULT_CONFIG.violation_limit, "Should use default violation_limit");
  assert(config.texts.captcha_text === DEFAULT_CONFIG.texts.captcha_text, "Should use default captcha_text");
}

function test_getCachedConfig_usesSheetValues(mocks) {
  mocks.mockSheetData['Config'].push(["violation_limit", 99]);
  mocks.mockSheetData['Texts'] = [["key", "value"], ["captcha_text", "Hi there"]];
  CacheService.getScriptCache().remove('config');
  const config = getCachedConfig();
  assert(config.violation_limit === 99, "Should use violation_limit from sheet");
  assert(config.texts.captcha_text === "Hi there", "Should use captcha_text from sheet");
}

function test_messageCleaner_deletesExpiredMessages(mocks) {
    const now = new Date().getTime();
    const queue = [{ chatId: -1001, messageId: 101, deleteAt: now - 5000 }, { chatId: -1002, messageId: 102, deleteAt: now + 5000 }];
    // Correctly use the mocked properties object to set up the test
    mocks.mockProperties['deleteQueue'] = JSON.stringify(queue);

    messageCleaner();
    
    assert(mocks.urlFetchLog.length === 1, "Expected 1 API call to delete a message, got " + mocks.urlFetchLog.length);
    assert(mocks.urlFetchLog[0].method === 'deleteMessage', "Should delete the expired message");
    const updatedQueue = JSON.parse(mocks.mockProperties['deleteQueue']);
    assert(updatedQueue.length === 1 && updatedQueue[0].messageId === 102, "The non-expired item should remain");
}
