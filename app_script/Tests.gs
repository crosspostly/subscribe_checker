/**
 * @file Tests.gs
 * @description Unit testing suite for the Telegram bot. This file is NOT part of the production deployment.
 * To run tests: In the Apps Script editor, select 'runAllTests' from the function dropdown and click 'Run'.
 * Then, check the logs (Ctrl+Enter or Cmd+Enter) for the results.
 */

// =================================================================================
// 1. TEST RUNNER
// =================================================================================

function runAllTests() {
  Logger.log('Starting tests...');
  const testFunctions = [
      test_isUserSubscribed_isMember,
      test_isUserSubscribed_isNotMember,
      test_handleNewChatMember_CAPTCHA,
      test_handleMessage_ViolationCount,
      test_applyProgressiveMute_level1,
      test_messageCleaner_deletesExpired
  ];
  
  let passed = 0;
  let failed = 0;

  for (const testFunc of testFunctions) {
      // Reset mocks for each test to ensure isolation
      MOCK_API_CALLS.length = 0; 
      try {
          testFunc();
          Logger.log(`✅ PASS: ${testFunc.name}`);
          passed++;
      } catch (e) {
          Logger.log(`❌ FAIL: ${testFunc.name} -> ${e.message} \nStack: ${e.stack || 'No stack trace'}`);
          failed++;
      }
  }

  Logger.log('\n--- TEST SUMMARY ---');
  if (failed === 0) {
      Logger.log(`✅ All ${passed} tests passed!`);
  } else {
      Logger.log(`❌ ${failed} of ${passed + failed} tests failed.`);
  }
  Logger.log('--------------------');
}


// =================================================================================
// 2. MOCK OBJECTS & HELPERS (Simulating Google/Telegram Services)
// =================================================================================

const MOCK_API_CALLS = [];
const TEST_CHAT_ID = -100987654321;
const TEST_USER_ID = 123456789;
const TEST_CHANNEL_ID = -1001122334455;

// --- Mocks ---
class MockUrlFetchApp {
  fetch(url, options) {
    const payload = JSON.parse(options.payload);
    const method = url.split('/').pop();
    MOCK_API_CALLS.push({ method, payload });
    
    // Simulate responses for specific methods
    if (method === 'getChatMember') {
        return new MockHttpResponse(200, JSON.stringify({ ok: true, result: { status: payload.user_id === TEST_USER_ID ? 'member' : 'left' } }));
    }
    if (method === 'sendMessage') {
        return new MockHttpResponse(200, JSON.stringify({ ok: true, result: { message_id: Math.floor(Math.random() * 10000) } }));
    }
    return new MockHttpResponse(200, JSON.stringify({ ok: true, result: {} }));
  }
}

class MockHttpResponse {
  constructor(code, content) { this.code = code; this.content = content; }
  getResponseCode() { return this.code; }
  getContentText() { return this.content; }
}

class MockCache {
  constructor() { this.store = {}; }
  get(key) { return this.store[key] || null; }
  put(key, value, timeout) { this.store[key] = value; }
  remove(key) { delete this.store[key]; }
}

class MockLock {
  waitLock(ms) {}
  releaseLock() {}
}

class MockProperties {
    constructor() { this.props = {}; }
    getProperty(key) { return this.props[key] || null; }
    setProperty(key, value) { this.props[key] = value; }
    deleteProperty(key) { delete this.props[key]; }
}

class MockRange {
    constructor(value) { this.value = value; }
    getValue() { return this.value; }
    getValues() { return this.value; }
    setValue(val) { 
        if(Array.isArray(this.value)) { this.value[0] = val; }
        else { this.value = val; }
    }
}

class MockSheet {
  constructor(data) { this.data = data || []; }
  getDataRange() { return new MockRange(this.data); }
  getRange(row, col) { return new MockRange(this.data[row-1][col-1]); }
  appendRow(rowData) { this.data.push(rowData); }
}

class MockSpreadsheet {
  constructor(sheet) { this.sheet = sheet || new MockSheet(); }
  getSheetByName(name) { return this.sheet; }
}

// --- Assertion Helpers ---
function assertEquals(expected, actual, message) {
  if (expected != actual) {
    throw new Error(`${message}: Expected '${expected}', but got '${actual}'`);
  }
}

function assertTrue(condition, message) {
  if (!condition) {
    throw new Error(`${message}: Condition was not true`);
  }
}

// =================================================================================
// 3. UNIT TESTS
// =================================================================================

function getMockServices(mockSheet) {
    return {
        ss: new MockSpreadsheet(mockSheet),
        cache: new MockCache(),
        lock: new MockLock(),
        properties: new MockProperties(),
        fetch: new MockUrlFetchApp()
    };
}

function test_isUserSubscribed_isMember() {
  const services = getMockServices();
  const result = isUserSubscribed(TEST_USER_ID, TEST_CHANNEL_ID, services);
  assertTrue(result, "test_isUserSubscribed_isMember");
  assertEquals(1, MOCK_API_CALLS.length, "test_isUserSubscribed_isMember [API calls]");
  assertEquals("getChatMember", MOCK_API_CALLS[0].method, "test_isUserSubscribed_isMember [API method]");
}

function test_isUserSubscribed_isNotMember() {
  const services = getMockServices();
  const result = isUserSubscribed(999, TEST_CHANNEL_ID, services); // Different user
  assertTrue(!result, "test_isUserSubscribed_isNotMember");
}

function test_handleNewChatMember_CAPTCHA() {
    const services = getMockServices();
    const config = { captcha_mute_duration_min: 30, captcha_message_timeout_sec: 25, texts: { captcha_text: "Welcome {user_mention}" }};
    services.cache.put('config', JSON.stringify(config), 300);

    const chatMember = {
        chat: { id: TEST_CHAT_ID, title: "Test Chat" },
        new_chat_member: { id: TEST_USER_ID, first_name: "Test", is_bot: false, status: "member" }
    };
    
    handleNewChatMember(chatMember, services);
    
    // 1. Check for restrictChatMember call
    const restrictCall = MOCK_API_CALLS.find(c => c.method === 'restrictChatMember');
    assertTrue(restrictCall, "CAPTCHA test [restrict call]");
    assertEquals(TEST_USER_ID, restrictCall.payload.user_id, "CAPTCHA test [user_id]");
    
    // 2. Check for sendMessage call
    const messageCall = MOCK_API_CALLS.find(c => c.method === 'sendMessage');
    assertTrue(messageCall, "CAPTCHA test [message call]");
    assertTrue(messageCall.payload.text.includes("Welcome"), "CAPTCHA test [message text]");
    
    // 3. Check cache for captcha data
    const captchaData = services.cache.get(`captcha_${TEST_USER_ID}`);
    assertTrue(captchaData, "CAPTCHA test [cache data]");
    assertEquals(TEST_USER_ID, JSON.parse(captchaData).userId, "CAPTCHA test [cache user id]");
}

function test_handleMessage_ViolationCount() {
    const mockSheet = new MockSheet([['key','value'],['target_channel_id', TEST_CHANNEL_ID], ['violation_limit', 3]]);
    const services = getMockServices(mockSheet);
    
    const message = {
        message_id: 555,
        chat: { id: TEST_CHAT_ID },
        from: { id: 999, is_bot: false, first_name: "Violator" }
    };
    
    // 1st violation
    handleMessage(message, services);
    assertEquals('1', services.cache.get(`violations_999`), 'Violation count after 1st message');
    
    // 2nd violation
    handleMessage(message, services);
    assertEquals('2', services.cache.get(`violations_999`), 'Violation count after 2nd message');
}

function test_applyProgressiveMute_level1() {
  const mockSheet = new MockSheet([['user_id', 'mute_level'], [999, 0]]); // Different user
  const services = getMockServices(mockSheet);
  const config = { mute_level_1_duration_min: 30, texts: { sub_mute_text: "{user_mention} muted for {duration}" }};
  services.cache.put('config', JSON.stringify(config), 300);

  applyProgressiveMute(TEST_CHAT_ID, 12345, services);

  // Check if mute was applied
  const restrictCall = MOCK_API_CALLS.find(c => c.method === 'restrictChatMember');
  assertTrue(restrictCall, 'applyProgressiveMute [restrict call]');
  
  // Check if mute level was updated in the sheet
  assertEquals(1, mockSheet.data[mockSheet.data.length - 1][1], 'applyProgressiveMute [sheet write]');
}


function test_messageCleaner_deletesExpired() {
    const services = getMockServices();
    const messageId1 = 101, messageId2 = 102;
    const now = new Date().getTime();
    
    // One expired, one not
    const queue = [
        { chatId: TEST_CHAT_ID, messageId: messageId1, deleteAt: now - 5000 },
        { chatId: TEST_CHAT_ID, messageId: messageId2, deleteAt: now + 20000 }
    ];
    services.properties.setProperty('deleteQueue', JSON.stringify(queue));
    services.cache.put('config', JSON.stringify({texts:{}}), 300);

    messageCleaner(services);

    // Should be one API call to delete the expired message
    const deleteCall = MOCK_API_CALLS.find(c => c.method === 'deleteMessage');
    assertTrue(deleteCall, 'messageCleaner [delete call]');
    assertEquals(messageId1, deleteCall.payload.message_id, 'messageCleaner [message_id]');
    
    // The queue in properties should now only contain the non-expired message
    const updatedQueue = JSON.parse(services.properties.getProperty('deleteQueue'));
    assertEquals(1, updatedQueue.length, 'messageCleaner [queue length]');
    assertEquals(messageId2, updatedQueue[0].messageId, 'messageCleaner [remaining message]');
}

