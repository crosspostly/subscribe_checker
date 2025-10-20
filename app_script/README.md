# Telegram Subscription & CAPTCHA Bot

This Google Apps Script creates a Telegram bot with two primary functions:
1.  **Subscription Enforcement**: It ensures that users in your chat group are also members of a designated Telegram channel.
2.  **CAPTCHA Verification**: It requires new users to solve a simple "I am not a robot" CAPTCHA to prevent spam bots.

## Features

- **All-in-One `Code.gs`**: The entire logic is contained within a single, easy-to-manage file.
- **Spreadsheet-based Configuration**: Easily change settings like your target channel, mute durations, and message texts directly in a Google Sheet.
- **Progressive Muting**: Users who repeatedly violate the subscription rule are muted for progressively longer durations.
- **CAPTCHA on Entry**: New users are automatically muted and must pass a CAPTCHA to speak.
- **Automated Cleanup**: Warning messages and old CAPTCHA prompts are automatically deleted.
- **Unit Testing Suite**: Includes a `Tests.gs` file to verify functionality.

## Quick Setup Guide

Follow these steps to get your bot running in minutes.

### Step 1: Prepare Your Google Sheet

1.  **Create a new Google Sheet**.
2.  Go to **Extensions -> Apps Script**.
3.  **Copy and paste** the content of `Code.gs` into the `Code.gs` file in the editor.
4.  Create a new script file named `Tests.gs` by clicking the `+` icon and paste the content from this project's `Tests.gs` file (optional, for testing).
5.  Create `README.md` and `todo.md` files as well.

### Step 2: Initial Script Setup

1.  In the `Code.gs` file, **find the `initialSetup` function**.
2.  From the function dropdown menu at the top, select **`initialSetup`** and click **Run**. 
3.  Authorize the script when prompted.
4.  This will automatically create the necessary sheets (`Config`, `Texts`, `Users`, `Logs`) and populate them with default values.

### Step 3: Deploy the Script

1.  Click the **Deploy** button -> **New deployment**.
2.  Select Type: **Web app**.
3.  Configure:
    -   **Execute as**: `Me`
    -   **Who has access**: `Anyone`
4.  Click **Deploy**.
5.  **Crucially, copy the Web app URL**. You will need it in the next step.

### Step 4: Final Configuration & Webhook Setup

1.  Go back to the `Code.gs` file in the script editor.
2.  **Fill in the constants at the top**:
    -   `BOT_TOKEN`: Paste the token you got from `@BotFather` on Telegram.
    -   `WEB_APP_URL`: Paste the URL you copied during deployment.
3.  In the Google Sheet, go to the **`Config`** sheet and fill in the `target_channel_id` and your `admin_id`.
4.  In the script editor, select the **`_setWebhook`** function from the dropdown and click **Run**.
5.  (Optional) Run **`_getWebhookInfo`** to confirm the webhook was set correctly.
6.  Finally, select the **`_createTrigger`** function and click **Run**. This sets up the automated message cleaner.

**That's it! Your bot is now live.**

## How It Works

-   **`doPost(e)`**: This is the main entry point. Telegram sends all updates (new messages, new members, etc.) to your Web App URL, which triggers this function.
-   **`handleUpdate`**: This function acts as a router, directing the update to the appropriate handler (`handleMessage`, `handleNewChatMember`, etc.).
-   **`handleNewChatMember`**: When a new user joins, this function mutes them and sends the CAPTCHA keyboard.
-   **`handleCallbackQuery`**: This handles the "I am not a robot" button press. If successful, it unmutes the user.
-   **`handleMessage`**: If a user tries to speak, this function checks if they are subscribed to the `target_channel_id`. If not, it deletes their message and issues a warning or a progressive mute.
-   **`messageCleaner` / `main`**: This function runs on a time-based trigger (e.g., every minute) to delete old warning and CAPTCHA messages, keeping the chat clean.
-   **Google Sheets**: Acts as a simple database for configuration, storing mute levels for users, and logging errors.
