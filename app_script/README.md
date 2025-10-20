# Telegram Subscription & CAPTCHA Bot (Final Version)

This Google Apps Script creates a sophisticated, highly configurable Telegram bot with two primary functions:
1.  **Subscription Enforcement**: It ensures that users in your designated chat groups are also members of a specific Telegram channel.
2.  **CAPTCHA Verification**: It requires new users to solve a simple "I am not a robot" CAPTCHA to prevent spam bots.

## ⭐️ Key Features

- **Full UI Control**: Manage the bot directly from a custom menu in your Google Sheet (**start**, **stop**, **clear cache**).
- **Sheet-based Configuration**: Easily change all settings (mute durations, timeouts, texts) in the `Config` sheet without touching the code.
- **Admin Immunity**: Automatically detects chat administrators and **completely ignores their messages and joins**, preventing accidental mutes or CAPTCHAs.
- **Intelligent Channel Post Handling**:
    -   **Automatic Passthrough for Target Channel**: Automatically ignores (never deletes) any posts from your main `target_channel_id`.
    -   **Whitelist for Other Channels**: Allows you to specify other channel IDs in the `Whitelist` sheet whose posts should also be ignored.
    -   Deletes posts from any other non-whitelisted channels.
- **Whitelist for Users**: A dedicated `Whitelist` sheet allows you to specify user IDs (e.g., other bots or trusted users) that the script should always ignore.
- **Authorized Chats**: A crucial security feature. The bot will **only operate** in chat groups whose IDs are listed in the `authorized_chat_ids` setting.
- **Smart CAPTCHA**: The CAPTCHA is triggered *only* on a real user join event, ignoring other status changes. It also won't be shown to joining administrators.
- **System Message Immunity**: Ignores messages from anonymous admins (`136817688`) and other system users, preventing false triggers.
- **Secure Secret Storage**: Uses `PropertiesService` to keep your bot token and web app URL safe.
- **Progressive Muting**: Users who repeatedly post without a subscription are muted for progressively longer durations.
- **Automated Cleanup**: A time-based trigger automatically deletes old CAPTCHA prompts and warning messages.

## 🚀 One-Time Setup Guide

Follow these steps carefully. You only need to do this once.

### Step 1: Create Sheet & Deploy

1.  **Create a new Google Sheet**.
2.  Go to **Extensions -> Apps Script**.
3.  You will see two files: `Code.gs` and `tests.gs`. **Ensure you are editing the `Code.gs` file**.
4.  **Paste the content** of this project's `Code.gs` into the editor, deleting any existing code.
5.  Click **Deploy** -> **New deployment**.
6.  Configure the Web App:
    -   **Execute as**: `Me`
    -   **Who has access**: `Anyone`
7.  Click **Deploy**. **COPY the Web app URL** shown in the popup. You will need it in the next step.

### Step 2: Run the Automated `initialSetup`

This single function now handles everything: saving secrets, creating sheets, and setting up triggers.

1.  Go back to the Apps Script editor.
2.  At the top of the `Code.gs` file, find the `_saveSecrets` function.
3.  **PASTE your Bot Token and the Web App URL** you just copied into the appropriate fields inside this function.
4.  Now, from the function dropdown menu at the top, select **`initialSetup`** and click **Run**.
5.  **Authorize the script** when prompted by Google. This is crucial.

**That's it!** The `initialSetup` function has automatically performed all necessary steps. A popup in your Sheet will confirm when the setup is complete.

### Step 3: Final Configuration in the Sheet

Your bot is now live, but you need to tell it *where* and *how* to work.

1.  Go to the **`Config`** sheet in your Google Sheet.
2.  In the `value` column, fill in:
    -   `target_channel_id`: The **numeric ID** (e.g., `-100123456789`) of the channel users must subscribe to.
    -   `authorized_chat_ids`: The numeric IDs of the chat groups where the bot should operate. **Put each ID on a new line**.

3.  (Optional) Go to the **`Whitelist`** sheet:
    - Add the **numeric ID** of any other channels whose posts should be allowed.
    - Add the user ID of any bots or trusted users the script should ignore.

> **CRITICAL NOTE:** For channel post handling to work correctly, you **must** use the channel's numeric ID (e.g., `-100123456789`), not its username (`@my_channel`). You can find the ID by using a bot like @userinfobot and forwarding a post from your channel to it.

## ⚙️ Using the Bot

### Bot Controls Menu

After setup, you will see a new menu in your Google Sheet named **"🤖 Управление ботом"**. 
- **🟢 Включить бота**: Activates the bot.
- **🔴 Выключить бота**: Deactivates the bot.
- **🔄 Сбросить кэш (Настройки и Админы)**: Instantly reloads all settings from the sheet and clears the cached list of chat administrators.

## 🧪 Running Tests (Optional)

This project includes a comprehensive test suite to verify the bot's logic without affecting your live environment.

1.  In the Apps Script editor, open the **`tests.gs`** file.
2.  From the function dropdown menu, select **`runAllTests`**.
3.  Click **Run**.
4.  The script will execute dozens of internal checks.
5.  After a few moments, a popup will appear in your Google Sheet with the results:
    -   **Success**: "✅ All tests passed successfully!"
    -   **Failure**: "Test suite finished with failures. Check the logs for details."
6.  You can view detailed logs for each test in the **Execution log** in the Apps Script editor.
