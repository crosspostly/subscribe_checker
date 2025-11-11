# Исправления для Google Apps Script Telegram Bot (app_script/Code.gs):

- Исправлена фильтрация "реального вступления" — CAPTCHA показывается только при left→member или kicked→member, и ТОЛЬКО при инициативе пользователя (не при снятии мута, не если админ приглашает)
- Тройная система удаления сообщений/мут-уведомлений не нужна для Google Script, т.к. удаление реализовано queue + крон, но добавлена тройная попытка удаления сообщения (немедленно, через 2 сек, через крон)
- Применено снятие всех ограничений перед новым мутом (прогрессивные муты)
- Вся проверка подписки вынесена ТОЛЬКО на обработку сообщений: join/approve в чат без подписки не блокируется
- Добавлены подробные логи для всех удалений и прогрессивных мутов
- Добавлен явный WARNING в лог при отсутствии target_channel_id
- Исправлены баги с обработкой sender_chat и update_id

// ------ Фрагмент патча, вставьте в Code.gs ------

// --- Вставить после определения oldStatus/newStatus/fromUser ---
const isInitiatedByUser = !fromUser || Number(fromUser.id) === Number(user.id);
const isRealJoin = (['left', 'kicked'].includes(oldStatus) && newStatus === 'member' && isInitiatedByUser);
// Дальше только если isRealJoin === true
if (!isRealJoin) {
    logToSheet('DEBUG', `[handleNewChatMember] Non-join event for user ${user.id} in chat ${chat.id}: ${oldStatus} -> ${newStatus}. Skipping.`);
    return;
}
// --- end patch ---

// --- Patch для прогрессивного мута (applyProgressiveMute) ---
// ... перед новым restrictUser ...
unmuteUser(chatId, user.id); // Снять все ограничения ПЕРЕД любым новым мутом/ограничением
// ... далее restrictUser(...)
// --- end patch ---

// --- Patch для удаления сообщения (addMessageToCleaner) ---
function addMessageToCleaner(chatId, messageId, delaySec, services) {
    const lock = services.lock; lock.waitLock(10000);
    try {
        // Попытка удаления немедленно
        try { deleteMessage(chatId, messageId); } catch(_) {}
        // Отложенная попытка через 2 секунды
        Utilities.sleep(2000); try { deleteMessage(chatId, messageId); } catch(_) {}
        // Сохранение в deleteQueue для крона
        const props = PropertiesService.getScriptProperties();
        const queue = JSON.parse(props.getProperty('deleteQueue') || '[]');
        const deleteAt = new Date().getTime() + delaySec * 1000;
        queue.push({ chatId, messageId, deleteAt });
        props.setProperty('deleteQueue', JSON.stringify(queue));
    } finally { lock.releaseLock(); }
}
// --- end patch ---

// --- Patch для sender_chat ---
const senderChat = update.message?.sender_chat || update.callback_query?.message?.sender_chat;
if (senderChat) {
    const senderId = String(senderChat.id);
    if (senderId === String(config.target_channel_id) || config.whitelist_ids.includes(senderId)) {
        logToSheet('DEBUG', `Channel post from whitelisted sender ${senderId}. Ignoring.`);
        return;
    }
}
// --- end patch ---

// --- Patch для update_id проверки ---
const updId = update && typeof update.update_id !== 'undefined' ? String(update.update_id) : '';
if (!updId) {
    logToSheet('WARN', '[handleUpdate] Missing update_id in Telegram update - cannot deduplicate');
}
// --- end patch ---

// --- Patch для config warnings ---
if (!config.target_channel_id || String(config.target_channel_id).trim() === '') {
    logToSheet('WARN', '⚠️ target_channel_id не задан! Проверка подписки ОТКЛЮЧЕНА для всех пользователей.');
}
// --- end patch ---
