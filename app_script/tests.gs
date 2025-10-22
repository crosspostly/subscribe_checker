/**
 * @file tests.gs
 * @description FINAL, CORRECTED test suite. This version fixes all previously identified bugs.
 */

// =================================================================================
// ======================  A. TEST RUNNER & FRAMEWORK  ===========================
// =================================================================================

// ==================================================================================
// =====================  ENHANCED TESTING WITH TABLE LOGGING  ===================
// ==================================================================================

/**
 * Runs all tests with enhanced logging to Tests sheet
 */
function runAllTestsWithLogging() {
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
    test_messageCleaner_deletesExpiredMessages,
    // NEW TESTS for the improvements and bug fixes
    test_handleNewChatMember_checksPermissions,
    test_handleNewChatMember_skipsBotItself,
    test_handleNewChatMember_skipsSystemAccounts,
    test_handleNewChatMember_detectsRealJoins,
    test_handleChatJoinRequest_approvesUsers,
    test_handleCallbackQuery_subscriptionCheck_success,
    test_handleCallbackQuery_subscriptionCheck_failure,
    test_handleMessage_withChannelUrl_createsButtons,
    test_getBotId_cachesResult,
    test_sendTelegram_handlesErrors,
    test_getCachedConfig_handlesChannelUrl,
    // NEW FILTERING OPTIMIZATION TESTS
    test_handleUpdate_optimizedFiltering_whitelistedUser,
    test_handleUpdate_optimizedFiltering_adminUser,
    test_handleUpdate_optimizedFiltering_botUser,
    test_handleUpdate_optimizedFiltering_systemAccount,
    test_handleUpdate_optimizedFiltering_privateMessage,
    test_handleUpdate_optimizedFiltering_channelPost,
    test_handleUpdate_optimizedFiltering_whitelistedChannel,
    test_handleUpdate_optimizedFiltering_normalUserPasses
  ];

  // Log test start to Tests sheet
  logToTestSheet("🚀 STARTING BOT TEST SUITE", "INFO", `Starting ${testFunctions.length} tests`);

  let originalServices = {};

  testFunctions.forEach(testFunc => {
    const testName = testFunc.name;
    testResults.total++;
    let mocks = null;
    
    logToTestSheet(`Starting: ${testName}`, "TEST", "Initializing test environment");
    
    try {
      mocks = getMockServicesAndData(originalServices); // Setup mocks and get them
      testFunc(mocks); // Pass mocks into the test function
      testResults.passed++;
      
      logToTestSheet(`✅ PASSED: ${testName}`, "PASS", "Test completed successfully");
      Logger.log(`✅ PASSED: ${testName}`);
      
    } catch (e) {
      testResults.failed++;
      testResults.failures.push({ name: testName, error: e.message, stack: e.stack });
      
      logToTestSheet(`❌ FAILED: ${testName}`, "FAIL", `Error: ${e.message}`);
      Logger.log(`❌ FAILED: ${testName} - ${e.message}`);
      
    } finally {
       if (mocks) mocks.cleanup(originalServices); // Always cleanup
    }
  });

  // Log final results to Tests sheet
  logToTestSheet("🏁 TEST SUITE COMPLETE", "INFO", 
    `Results: ${testResults.passed} passed, ${testResults.failed} failed out of ${testResults.total} total tests`);

  Logger.log("------ TEST SUITE COMPLETE ------");
  Logger.log(`Results: ${testResults.passed} passed, ${testResults.failed} failed out of ${testResults.total} total tests.`);

  if (testResults.failed > 0) {
    Logger.log("\n------ FAILURE DETAILS ------");
    testResults.failures.forEach(failure => { 
      Logger.log(`\n--- ❌ ${failure.name} ---\nError: ${failure.error}\nStack: ${failure.stack || 'no stack'}\n`);
      logToTestSheet(`FAILURE DETAIL: ${failure.name}`, "ERROR", 
        `Error: ${failure.error}\nStack: ${failure.stack || 'No stack trace available'}`);
    });
    logToTestSheet(`❌ ${testResults.failed} TESTS FAILED`, "SUMMARY", "Check failure details above");
  } else {
    logToTestSheet(`✅ ALL ${testResults.total} TESTS PASSED`, "SUMMARY", "Test suite completed successfully");
  }
  
  // CRITICAL: Return the testResults object so runTestsFromMenu can access it
  return testResults;
}

/**
 * Legacy test runner for backward compatibility (uses popups, no sheet logging)
 */
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
    test_messageCleaner_deletesExpiredMessages,
    test_handleNewChatMember_checksPermissions,
    test_handleNewChatMember_skipsBotItself,
    test_handleNewChatMember_skipsSystemAccounts,
    test_handleNewChatMember_detectsRealJoins,
    test_handleChatJoinRequest_approvesUsers,
    test_handleCallbackQuery_subscriptionCheck_success,
    test_handleCallbackQuery_subscriptionCheck_failure,
    test_handleMessage_withChannelUrl_createsButtons,
    test_getBotId_cachesResult,
    test_sendTelegram_handlesErrors,
    test_getCachedConfig_handlesChannelUrl,
    test_handleUpdate_optimizedFiltering_whitelistedUser,
    test_handleUpdate_optimizedFiltering_adminUser,
    test_handleUpdate_optimizedFiltering_botUser,
    test_handleUpdate_optimizedFiltering_systemAccount,
    test_handleUpdate_optimizedFiltering_privateMessage,
    test_handleUpdate_optimizedFiltering_channelPost,
    test_handleUpdate_optimizedFiltering_whitelistedChannel,
    test_handleUpdate_optimizedFiltering_normalUserPasses
  ];

  Logger.log("------ STARTING BOT TEST SUITE (LEGACY) ------");

  let originalServices = {};

  testFunctions.forEach(testFunc => {
    const testName = testFunc.name;
    testResults.total++;
    let mocks = null;
    try {
      mocks = getMockServicesAndData(originalServices);
      testFunc(mocks);
      testResults.passed++;
      Logger.log(`✅ PASSED: ${testName}`);
    } catch (e) {
      testResults.failed++;
      testResults.failures.push({ name: testName, error: e.message, stack: e.stack });
      Logger.log(`❌ FAILED: ${testName} - ${e.message}`);
    } finally {
       if (mocks) mocks.cleanup(originalServices);
    }
  });

  Logger.log("------ TEST SUITE COMPLETE ------");
  Logger.log(`Results: ${testResults.passed} passed, ${testResults.failed} failed out of ${testResults.total} total tests.`);

  if (testResults.failed > 0) {
    Logger.log("\n------ FAILURE DETAILS ------");
    testResults.failures.forEach(failure => { Logger.log(`\n--- ❌ ${failure.name} ---\nError: ${failure.error}\nStack: ${failure.stack || 'no stack'}\n`); });
    try { SpreadsheetApp.getUi().alert(`Test suite finished with ${testResults.failed} failures. Check logs.`); } catch (e) {}
  } else {
    try { SpreadsheetApp.getUi().alert(`✅ All ${testResults.total} tests passed successfully!`); } catch (e) {}
  }
  
  return testResults;
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
        apiResult = { ok: true, result: [ { user: { id: 999, is_bot: false } } ] };
      } else if (method === 'getChatMember') {
        const targetUserId = payload ? payload.user_id : undefined;
        const isBotPermissionCheck = targetUserId === null || typeof targetUserId === 'undefined' || targetUserId === '';
        if (isBotPermissionCheck) {
          apiResult = { ok: true, result: { can_restrict_members: true, can_delete_messages: true, status: 'administrator' } };
        } else {
          apiResult = { ok: true, result: { status: 'left' } };
        }
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
  
  // CRITICAL: Set TEST_MODE to avoid logging during tests
  this.TEST_MODE = true;

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
      
      // CRITICAL: Reset TEST_MODE after tests
      this.TEST_MODE = false;
    }
  };
}

// =================================================================================
// ========================  C. UNIT & INTEGRATION TESTS  ==========================
// =================================================================================

function test_handleNewChatMember_onRealJoin(mocks) {
  const update = { chat_member: { chat: { id: -100999 }, from: { id: 456, is_bot: false }, old_chat_member: { status: 'left' }, new_chat_member: { status: 'member', user: { id: 456, is_bot: false } } } };
  
  // DEBUG: Log what we're testing
  logTestDebug('test_handleNewChatMember_onRealJoin', `Testing real join event: user ${update.chat_member.new_chat_member.user.id}, ${update.chat_member.old_chat_member.status} -> ${update.chat_member.new_chat_member.status}`);
  
  handleUpdate(update);
  
  // DEBUG: Log API calls made
  logTestDebug('test_handleNewChatMember_onRealJoin', `API calls made: ${mocks.urlFetchLog.map(c => c.method).join(', ')} (total: ${mocks.urlFetchLog.length})`);
  
  const restrictCall = mocks.urlFetchLog.find(c => c.method === 'restrictChatMember');
  const sendCall = mocks.urlFetchLog.find(c => c.method === 'sendMessage');
  
  logTestDebug('test_handleNewChatMember_onRealJoin', `Restrict call found: ${!!restrictCall}, Send call found: ${!!sendCall}`);
  
  assert(restrictCall, "User should be muted");
  assert(sendCall, "CAPTCHA message should be sent");
}

function test_handleNewChatMember_ignoresFalseJoin(mocks) {
  const update = { chat_member: { chat: { id: -100999 }, from: { id: 999 }, old_chat_member: { status: 'restricted' }, new_chat_member: { status: 'member', user: { id: 456 } } } };
  
  // DEBUG: Log what we're testing
  logTestDebug('test_handleNewChatMember_ignoresFalseJoin', `Testing false join event: user ${update.chat_member.new_chat_member.user.id}, from user ${update.chat_member.from.id}, ${update.chat_member.old_chat_member.status} -> ${update.chat_member.new_chat_member.status}`);
  
  handleUpdate(update);
  
  // DEBUG: Log API calls made
  logTestDebug('test_handleNewChatMember_ignoresFalseJoin', `API calls made: ${mocks.urlFetchLog.map(c => c.method).join(', ')} (total: ${mocks.urlFetchLog.length})`);
  
  assert(mocks.urlFetchLog.length === 0, "Expected 0 API calls for a false join, but got " + mocks.urlFetchLog.length);
}

function test_handleNewChatMember_ignoresAdminJoin(mocks) {
  const update = { chat_member: { chat: { id: -100999 }, from: { id: 999 }, old_chat_member: { status: 'left' }, new_chat_member: { status: 'member', user: { id: 999, is_bot: false } } } };
  
  // DEBUG: Log what we're testing
  logTestDebug('test_handleNewChatMember_ignoresAdminJoin', `Testing admin join event: user ${update.chat_member.new_chat_member.user.id} (admin), ${update.chat_member.old_chat_member.status} -> ${update.chat_member.new_chat_member.status}`);
  
  handleUpdate(update);
  
  // DEBUG: Log API calls made
  logTestDebug('test_handleNewChatMember_ignoresAdminJoin', `API calls made: ${mocks.urlFetchLog.map(c => c.method).join(', ')} (total: ${mocks.urlFetchLog.length})`);
  
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

// =================================================================================
// ====================  D. NEW ENHANCED TESTS (BUG FIXES)  ======================
// =================================================================================

function test_handleNewChatMember_checksPermissions(mocks) {
    // Mock bot without permissions
    const originalFetch = UrlFetchApp.fetch;
    UrlFetchApp.fetch = (url, params) => {
        if (url.includes('getChatMember')) {
            return { getContentText: () => JSON.stringify({ ok: true, result: { can_restrict_members: false, can_delete_messages: false } }) };
        }
        return originalFetch(url, params);
    };
    
    const update = { chat_member: { chat: { id: -100999 }, old_chat_member: { status: 'left' }, new_chat_member: { status: 'member', user: { id: 456, is_bot: false } } } };
    handleUpdate(update);
    
    // Should not proceed to send CAPTCHA if bot lacks permissions
    const captchaCall = mocks.urlFetchLog.find(c => c.method === 'sendMessage');
    assert(!captchaCall, "Should not send CAPTCHA if bot lacks permissions");
}

function test_handleNewChatMember_skipsBotItself(mocks) {
    // Mock getBotId to return a specific ID
    mocks.mockCache['bot_id'] = '123';
    
    const update = { chat_member: { chat: { id: -100999 }, old_chat_member: { status: 'left' }, new_chat_member: { status: 'member', user: { id: 123, is_bot: true } } } };
    handleUpdate(update);
    
    // Should skip processing bot join events
    const restrictCall = mocks.urlFetchLog.find(c => c.method === 'restrictChatMember');
    assert(!restrictCall, "Should not process bot's own join events");
}

function test_handleNewChatMember_skipsSystemAccounts(mocks) {
    const update = { chat_member: { chat: { id: -100999 }, old_chat_member: { status: 'left' }, new_chat_member: { status: 'member', user: { id: 777000, is_bot: false } } } };
    handleUpdate(update);
    
    // Should skip processing system account events
    const restrictCall = mocks.urlFetchLog.find(c => c.method === 'restrictChatMember');
    assert(!restrictCall, "Should not process system account events");
}

function test_handleNewChatMember_detectsRealJoins(mocks) {
    // Test different join scenarios
    const scenarios = [
        { old: 'left', new: 'member', shouldProcess: true },
        { old: 'kicked', new: 'member', shouldProcess: true },
        { old: 'restricted', new: 'member', shouldProcess: false }, // FIXED: restricted->member means user passed CAPTCHA, not new join!
        { old: null, new: 'member', shouldProcess: true },
        { old: 'member', new: 'left', shouldProcess: false },
        { old: 'member', new: 'restricted', shouldProcess: false }
    ];
    
    logTestDebug('test_handleNewChatMember_detectsRealJoins', `Testing ${scenarios.length} different join scenarios`);
    
    scenarios.forEach((scenario, index) => {
        mocks.urlFetchLog = []; // Clear log between tests
        const update = { chat_member: { 
            chat: { id: -100999 }, 
            old_chat_member: scenario.old ? { status: scenario.old } : null, 
            new_chat_member: { status: scenario.new, user: { id: 456 + index, is_bot: false } },
            from: { id: 456 + index } // User initiated the join themselves
        } };
        
        logTestDebug('test_handleNewChatMember_detectsRealJoins', `Scenario ${index}: Testing ${scenario.old} -> ${scenario.new} (should process: ${scenario.shouldProcess})`);
        
        handleUpdate(update);
        
        const hasRestrict = mocks.urlFetchLog.some(c => c.method === 'restrictChatMember');
        
        logTestDebug('test_handleNewChatMember_detectsRealJoins', `Scenario ${index} result: API calls made: ${mocks.urlFetchLog.map(c => c.method).join(', ')}, hasRestrict: ${hasRestrict}`);
        
        if (scenario.shouldProcess) {
            assert(hasRestrict, `Scenario ${index}: Should process join ${scenario.old} -> ${scenario.new}`);
        } else {
            assert(!hasRestrict, `Scenario ${index}: Should NOT process ${scenario.old} -> ${scenario.new}`);
        }
    });
}

function test_handleChatJoinRequest_approvesUsers(mocks) {
    const update = { chat_join_request: { chat: { id: -100999 }, from: { id: 456, is_bot: false, first_name: 'Test' } } };
    handleUpdate(update);
    
    const approveCall = mocks.urlFetchLog.find(c => c.method === 'approveChatJoinRequest');
    assert(approveCall, "Should approve legitimate join requests");
    assert(approveCall.payload.user_id === 456, "Should approve the correct user");
}

function test_handleCallbackQuery_subscriptionCheck_success(mocks) {
    // Mock successful subscription check
    const originalFetch = UrlFetchApp.fetch;
    UrlFetchApp.fetch = (url, params) => {
        if (url.includes('getChatMember')) {
            return { getContentText: () => JSON.stringify({ ok: true, result: { status: 'member' } }) };
        }
        return originalFetch(url, params);
    };
    
    const update = { callback_query: { 
        id: 'test123', 
        data: 'check_sub_456', 
        from: { id: 456 }, 
        message: { chat: { id: -100999 }, message_id: 123 } 
    } };
    handleUpdate(update);
    
    const deleteCall = mocks.urlFetchLog.find(c => c.method === 'deleteMessage');
    const successCall = mocks.urlFetchLog.find(c => c.method === 'sendMessage' && c.payload.text.includes('успешно подписались'));
    assert(deleteCall, "Should delete the subscription check message");
    assert(successCall, "Should send success message");
}

function test_handleCallbackQuery_subscriptionCheck_failure(mocks) {
    // Mock failed subscription check
    const originalFetch = UrlFetchApp.fetch;
    UrlFetchApp.fetch = (url, params) => {
        if (url.includes('getChatMember')) {
            return { getContentText: () => JSON.stringify({ ok: true, result: { status: 'left' } }) };
        }
        return originalFetch(url, params);
    };
    
    const update = { callback_query: { 
        id: 'test123', 
        data: 'check_sub_456', 
        from: { id: 456 }, 
        message: { chat: { id: -100999 }, message_id: 123 } 
    } };
    
    // Add channel URL to config
    mocks.mockSheetData['Config'].push(['target_channel_url', 'https://t.me/testchannel']);
    CacheService.getScriptCache().remove('config');
    
    handleUpdate(update);
    
    const editCall = mocks.urlFetchLog.find(c => c.method === 'editMessageText');
    assert(editCall, "Should edit message with subscription failure info");
}

function test_handleMessage_withChannelUrl_createsButtons(mocks) {
    // Add channel URL to config
    mocks.mockSheetData['Config'].push(['target_channel_url', 'https://t.me/testchannel']);
    CacheService.getScriptCache().remove('config');
    
    const update = { message: { message_id: 987, chat: { id: -100999 }, from: { id: 456 } } };
    handleUpdate(update);
    
    const sendCall = mocks.urlFetchLog.find(c => c.method === 'sendMessage' && c.payload.reply_markup);
    assert(sendCall, "Should send message with inline keyboard when channel URL is configured");
    
    const keyboard = JSON.parse(sendCall.payload.reply_markup);
    assert(keyboard.inline_keyboard.length >= 2, "Should have at least 2 rows of buttons");
    assert(keyboard.inline_keyboard[0][0].url, "First button should have URL");
    assert(keyboard.inline_keyboard[1][0].callback_data.includes('check_sub_'), "Second button should be subscription check");
}

function test_getBotId_cachesResult(mocks) {
    // Clear cache first
    mocks.mockCache['bot_id'] = null;
    
    // Mock API response
    const originalFetch = UrlFetchApp.fetch;
    UrlFetchApp.fetch = (url, params) => {
        if (url.includes('getMe')) {
            return { getContentText: () => JSON.stringify({ ok: true, result: { id: 999 } }) };
        }
        return originalFetch(url, params);
    };
    
    const botId1 = getBotId();
    const botId2 = getBotId();
    
    assert(botId1 === 999, "Should return correct bot ID");
    assert(botId2 === 999, "Should return same bot ID from cache");
    assert(mocks.mockCache['bot_id'] === '999', "Should cache bot ID");
}

function test_sendTelegram_handlesErrors(mocks) {
    // Test with invalid token
    const originalToken = mocks.mockProperties['BOT_TOKEN'];
    mocks.mockProperties['BOT_TOKEN'] = null;
    
    const result = sendTelegram('getMe', {});
    
    assert(result.ok === false, "Should return failure for missing token");
    assert(result.description === "Token not configured.", "Should return appropriate error message");
    
    // Restore token
    mocks.mockProperties['BOT_TOKEN'] = originalToken;
}

function test_getCachedConfig_handlesChannelUrl(mocks) {
    // Add channel URL to config
    mocks.mockSheetData['Config'].push(['target_channel_url', 'https://t.me/testchannel']);
    CacheService.getScriptCache().remove('config');
    
    const config = getCachedConfig();
    
    assert(config.target_channel_url === 'https://t.me/testchannel', "Should load channel URL from sheet");
    assert(config.target_channel_url.trim() !== '', "Channel URL should not be empty");
}

// =================================================================================
// =================  E. NEW FILTERING OPTIMIZATION TESTS  =======================
// =================================================================================

function test_handleUpdate_optimizedFiltering_whitelistedUser(mocks) {
    // Add user to whitelist
    mocks.mockSheetData['Whitelist'].push(['12345', 'Test whitelisted user']);
    CacheService.getScriptCache().remove('config');
    
    const update = { message: { chat: { id: -100999 }, from: { id: 12345, is_bot: false }, message_id: 987 } };
    handleUpdate(update);
    
    // Should be filtered out early, no API calls should be made
    assert(mocks.urlFetchLog.length === 0, "Whitelisted user should be filtered out early with no API calls");
}

function test_handleUpdate_optimizedFiltering_adminUser(mocks) {
    // Mock admin user - getChatAdministrators will return this user as admin
    const originalFetch = UrlFetchApp.fetch;
    UrlFetchApp.fetch = (url, params) => {
        if (url.includes('getChatAdministrators')) {
            const payload = params ? JSON.parse(params.payload) : {};
            mocks.urlFetchLog.push({ method: 'getChatAdministrators', payload });
            return { getContentText: () => JSON.stringify({ ok: true, result: [{ user: { id: 9999, is_bot: false } }] }) };
        }
        return originalFetch(url, params);
    };
    
    logTestDebug('test_handleUpdate_optimizedFiltering_adminUser', 'Testing admin user filtering - should check for admins but not process message');
    
    const update = { message: { chat: { id: -100999 }, from: { id: 9999, is_bot: false }, message_id: 987 } };
    handleUpdate(update);
    
    // DEBUG: Log API calls made
    logTestDebug('test_handleUpdate_optimizedFiltering_adminUser', `API calls made: ${mocks.urlFetchLog.map(c => c.method).join(', ')} (total: ${mocks.urlFetchLog.length})`);
    
    // Should only make getChatAdministrators call, then filter out
    const adminCall = mocks.urlFetchLog.find(c => c.method === 'getChatAdministrators');
    const deleteCall = mocks.urlFetchLog.find(c => c.method === 'deleteMessage');
    
    logTestDebug('test_handleUpdate_optimizedFiltering_adminUser', `Admin call found: ${!!adminCall}, Delete call found: ${!!deleteCall}`);
    
    assert(adminCall, "Should check for admins");
    assert(!deleteCall, "Admin user should be filtered out - no message deletion");
}

function test_handleUpdate_optimizedFiltering_botUser(mocks) {
    const update = { message: { chat: { id: -100999 }, from: { id: 123, is_bot: true }, message_id: 987 } };
    handleUpdate(update);
    
    // Bot should be filtered out early, no API calls
    assert(mocks.urlFetchLog.length === 0, "Bot user should be filtered out early with no API calls");
}

function test_handleUpdate_optimizedFiltering_systemAccount(mocks) {
    const update = { message: { chat: { id: -100999 }, from: { id: 777000, is_bot: false }, message_id: 987 } };
    handleUpdate(update);
    
    // System account should be filtered out early, no API calls
    assert(mocks.urlFetchLog.length === 0, "System account should be filtered out early with no API calls");
}

function test_handleUpdate_optimizedFiltering_privateMessage(mocks) {
    // Private message - chat.id equals user.id
    const update = { message: { chat: { id: 12345 }, from: { id: 12345, is_bot: false }, message_id: 987 } };
    
    // Need to add this chat to authorized chats for test
    mocks.mockSheetData['Config'].push(['authorized_chat_ids', '12345']);
    CacheService.getScriptCache().remove('config');
    
    handleUpdate(update);
    
    // Private message should be filtered out early, no API calls
    assert(mocks.urlFetchLog.length === 0, "Private message should be filtered out early with no API calls");
}

function test_handleUpdate_optimizedFiltering_channelPost(mocks) {
    // Channel post from target channel
    mocks.mockSheetData['Config'].push(['target_channel_id', '-100777']);
    CacheService.getScriptCache().remove('config');
    
    const update = { 
        message: { 
            chat: { id: -100999 }, 
            sender_chat: { id: -100777 }, // This is the target channel posting
            message_id: 987 
        } 
    };
    handleUpdate(update);
    
    // Channel post from target channel should be filtered out early
    assert(mocks.urlFetchLog.length === 0, "Channel post from target channel should be filtered out early");
}

function test_handleUpdate_optimizedFiltering_whitelistedChannel(mocks) {
    // Channel post from whitelisted channel
    mocks.mockSheetData['Whitelist'].push(['-100888', 'Whitelisted posting channel']);
    CacheService.getScriptCache().remove('config');
    
    const update = { 
        message: { 
            chat: { id: -100999 }, 
            sender_chat: { id: -100888 }, // This is a whitelisted channel
            message_id: 987 
        } 
    };
    handleUpdate(update);
    
    // Channel post from whitelisted channel should be filtered out early
    assert(mocks.urlFetchLog.length === 0, "Channel post from whitelisted channel should be filtered out early");
}

function test_handleUpdate_optimizedFiltering_normalUserPasses(mocks) {
    // Normal user that should pass all filters and get processed
    const update = { message: { chat: { id: -100999 }, from: { id: 456, is_bot: false }, message_id: 987 } };
    handleUpdate(update);
    
    // Should make API calls for normal processing (admin check, then subscription check, then delete message)
    const adminCall = mocks.urlFetchLog.find(c => c.method === 'getChatAdministrators');
    const deleteCall = mocks.urlFetchLog.find(c => c.method === 'deleteMessage');
    
    assert(adminCall, "Should check for admins for normal user");
    assert(deleteCall, "Should process normal user message (delete non-subscribed user message)");
    assert(mocks.urlFetchLog.length >= 2, "Normal user should trigger multiple API calls for processing");
}
