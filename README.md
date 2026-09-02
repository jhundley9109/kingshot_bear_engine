# 🐻 Kingshot Bear Trap Tracker

A Discord bot for tracking **Bear Trap / Hunting Trap** performance in the mobile game **Kingshot**.

Kingshot does not provide an easy way to export Bear Trap rankings as text, so this bot uses screenshot recognition to extract player rankings and damage from screenshots posted to Discord.

## How It Works

```text
Kingshot Bear Trap screenshots
            │
            ▼
    Upload to Discord
            │
            ▼
 Right-click the message
            │
            ▼
 Apps → Process Bear Trap
            │
            ▼
       OpenAI Vision
            │
            ▼
 Extract player rankings
            │
            ▼
  Validate / merge results
            │
            ▼
      Discord preview
```

The goal is to build historical Bear Trap statistics for an alliance without manually entering every player's damage.

---

# Features

Current functionality includes:

- Discord bot integration
- Message context-menu command
- Multiple screenshot processing
- OpenAI vision-based screenshot extraction
- Player rank extraction
- Player name extraction
- Damage extraction
- Duplicate rank detection and merging
- Missing rank detection
- Uncertain OCR result warnings
- Discord preview of extracted results

Planned functionality includes:

- Event metadata extraction
- Approve / Reject workflow
- SQLite historical storage
- Bear Trap 1 and Bear Trap 2 tracking
- Player performance history
- Alliance leaderboards
- Event-to-event comparisons
- Personal best tracking
- Participation statistics
- AI-generated alliance summaries

---

# Requirements

You will need:

- Python 3
- A Discord account
- A Discord server where you can install a bot
- An OpenAI API account and API key
- A machine capable of continuously running the Python bot

Linux is recommended for hosting.

This project was initially developed on Ubuntu.

---

# Installation

Clone the repository:

```bash
git clone YOUR_REPOSITORY_URL
cd kingshot-bear-bot
```

Create a Python virtual environment:

```bash
python3 -m venv venv
```

Activate it:

```bash
source venv/bin/activate
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

## Run continuously with systemd (Linux)

After creating the `.env` file described below, run the installer from the
repository root:

```bash
sudo ./scripts/install-systemd.sh
```

The installer creates/updates the `venv`, installs dependencies, enables the
bot at boot, starts it immediately, and configures weekly log rotation. The
service runs as the user who invoked `sudo` (or the repository owner when the
installer is run directly as root).

It installs the generated unit at
`/etc/systemd/system/kingshot-bear-engine.service` and the rotation policy at
`/etc/logrotate.d/kingshot-bear-engine`. Runtime output is written to
`/var/log/kingshot-bear-engine/bot.log`; the log is readable by the service
user and its group and is retained for eight weekly rotations.

Useful commands:

```bash
sudo systemctl status kingshot-bear-engine
sudo systemctl restart kingshot-bear-engine
sudo systemctl stop kingshot-bear-engine
sudo systemctl disable --now kingshot-bear-engine
tail -f /var/log/kingshot-bear-engine/bot.log
```

To install and enable the service without starting it immediately:

```bash
sudo ./scripts/install-systemd.sh --no-start
```

Re-run the installer after changing Python dependencies, the service template,
or the log rotation template. A normal code or `.env` change only requires
`sudo systemctl restart kingshot-bear-engine`. Do not also launch `bot.py`
manually while the service is running because two processes must not use the
same Discord token and SQLite database.

---

# Configuration

The bot uses environment variables for configuration.

Create a file called:

```text
.env
```

in the root of the project.

The file should contain:

```env
DISCORD_TOKEN=your_discord_bot_token
OPENAI_API_KEY=your_openai_api_key
GUILD_ID=your_discord_server_id
```

Do **not** commit this file to Git.

The project's `.gitignore` should contain:

```gitignore
.env
.env.*
venv/
__pycache__/
data/
*.db
*.sqlite
*.sqlite3
```

You can verify that Git is ignoring your `.env` file with:

```bash
git check-ignore .env
```

It should return:

```text
.env
```

---

# OpenAI API Setup

The bot uses the OpenAI API to extract information from Kingshot screenshots.

## 1. Create an API key

Open the OpenAI API Keys page:

https://platform.openai.com/api-keys

Create a new secret key.

For example, name it:

```text
Kingshot Bear Bot
```

Copy the generated key.

You will only be shown the complete secret key once.

Add it to `.env`:

```env
OPENAI_API_KEY=your_key_here
```

Never post this key in Discord, commit it to GitHub, or include it in screenshots.

If a key is accidentally exposed, revoke it and create a new one.

## 2. API Billing

OpenAI API usage is billed separately from a ChatGPT subscription.

Make sure the API project associated with your key is configured for API usage and has appropriate billing/credits available.

---

# Discord Bot Setup

## 1. Create a Discord Application

Open the Discord Developer Portal:

https://discord.com/developers/applications

Select:

```text
New Application
```

Give the application a name, such as:

```text
Kingshot Bear Trap Tracker
```

---

## 2. Create the Bot

Inside your Discord application, select:

```text
Bot
```

Use the token section to generate/reset your bot token.

Copy the token.

Add it to `.env`:

```env
DISCORD_TOKEN=your_bot_token_here
```

Your Discord bot token is effectively the bot's password.

Never commit or publicly share it.

If the token is accidentally exposed, return to the Discord Developer Portal and reset it immediately.

---

# Discord Installation Settings

Inside the Discord Developer Portal, open:

```text
Installation
```

Configure the application for installation into a Discord server.

For Guild Install, enable:

```text
applications.commands
bot
```

The bot should have the permissions necessary to:

- View Channels
- Send Messages
- Read Message History
- Attach Files

Use the generated installation link to install the bot into your Discord server.

---

# Finding Your Discord Server ID

The application uses your Discord server ID as:

```env
GUILD_ID=...
```

To find it:

### 1. Enable Developer Mode

In Discord, open:

```text
User Settings
    ↓
Advanced
    ↓
Developer Mode
```

Enable Developer Mode.

### 2. Copy the Server ID

Right-click your Discord server and select:

```text
Copy Server ID
```

Put the number into `.env`:

```env
GUILD_ID=123456789012345678
```

Do not include quotes.

---

# Example `.env`

A completed `.env` will look approximately like:

```env
DISCORD_TOKEN=YOUR_DISCORD_TOKEN
OPENAI_API_KEY=YOUR_OPENAI_API_KEY
GUILD_ID=123456789012345678
```

These should be the actual values on the machine running the bot.

Never put real credentials into documentation or Git.

---

# Running the Bot

Activate the Python environment:

```bash
cd ~/bear-bot
source venv/bin/activate
```

Start the bot:

```bash
python bot.py
```

You should see output similar to:

```text
Logged in as Kingshot Bear Trap Tracker
```

The bot should now appear online in Discord.

---

# Testing the Bot

The project includes a basic test command:

```text
/bear
```

If everything is configured correctly, the bot should respond:

```text
🐻 Bear Trap tracker is alive!
```

If this works, the following are configured correctly:

- Discord token
- Discord connection
- Discord application commands
- Guild ID
- Python environment

---

# Processing a Bear Trap Report

Take screenshots of the complete Bear Trap / Hunting Trap damage rankings in Kingshot.

Multiple screenshots will normally be required.

## 1. Upload the screenshots

Upload all screenshots belonging to the report as attachments to **one Discord message**.

For example:

```text
Discord Message

├── screenshot1.jpg
├── screenshot2.jpg
├── screenshot3.jpg
└── screenshot4.jpg
```

Screenshots may overlap. This is expected.

## 2. Process the report

Right-click the Discord message containing the screenshots.

Select:

```text
Apps
    ↓
Process Bear Trap
```

The bot will collect the image attachments and send them to OpenAI for processing.

---

# Screenshot Extraction

The bot attempts to extract:

```text
Rank
Player Name
Damage
```

For example:

```text
1. [XuX]PlayerOne — 1,746,978,512
2. [XuX]PlayerTwo — 1,502,037,235
3. [XuX]PlayerThree — 1,082,223,708
```

Player names may contain:

- spaces
- numbers
- capitalization
- alliance tags
- special characters
- non-English characters

The bot attempts to preserve names exactly as displayed.

---

# Overlapping Screenshots

Kingshot's interface may cause rankings to appear in more than one screenshot.

For example:

```text
Screenshot 1

1
2
3
4
5
12 ← player's pinned ranking
```

and:

```text
Screenshot 2

6
7
8
9
10
12 ← same pinned ranking
```

The bot detects matching duplicate ranks and merges them.

If duplicate ranks contain conflicting information, the submission can be flagged for review.

---

# OCR / Vision Accuracy

Screenshot extraction is not guaranteed to be perfect.

Player names are particularly susceptible to recognition errors because they can contain unusual spellings, numbers, special characters, or stylized text.

The bot may mark questionable results with:

```text
⚠️
```

These results should be reviewed before being treated as authoritative.

The project is being designed around the principle:

> AI extracts the data; application code validates and analyzes the data.

OpenAI should not be responsible for calculating historical statistics.

---

# Data Storage

The project is designed to use SQLite for historical data.

Runtime data is stored under:

```text
data/
```

Database files and runtime data should not be committed to Git.

The intended database will eventually track:

```text
Events
├── Event type
├── Date
├── Time
├── Rally count
└── Alliance damage

Player Results
├── Event
├── Rank
├── Player
├── Damage
└── Extraction confidence
```

SQLite will be the source of truth for historical statistics.

---

# Bear Trap 1 and Bear Trap 2

The initial development focus is:

```text
Bear Trap 2
```

However, the application is intended to eventually support both:

```text
Bear Trap 1
Bear Trap 2
```

The storage and analysis code should therefore avoid assuming every event is Bear Trap 2.

---

# Development

Run the bot locally:

```bash
source venv/bin/activate
python bot.py
```

Stop it with:

```text
Ctrl+C
```

After changing the Python code, restart the process for the changes to take effect.

Check Git status with:

```bash
git status
```

Commit changes with:

```bash
git add .
git commit -m "Description of change"
git push
```

Never commit `.env`, API keys, Discord tokens, or runtime database files.

---

# Troubleshooting

## `/bear` does not appear

Make sure:

- `GUILD_ID` is correct
- the bot is installed in that server
- `applications.commands` was enabled
- the bot restarted successfully
- Discord command synchronization completed

## Bot appears offline

Check the terminal running:

```bash
python bot.py
```

Look for authentication or connection errors.

Verify:

```env
DISCORD_TOKEN=...
```

contains the correct current token.

## Screenshot processing fails

Verify:

```env
OPENAI_API_KEY=...
```

is configured.

Also verify that the OpenAI API project has API access/billing configured.

Check the terminal where the bot is running for the complete Python/OpenAI error.

## `Process Bear Trap` does not appear

Make sure the application's commands have successfully synchronized with the Discord guild.

Restart the bot after adding or modifying Discord application commands.

---

# Security

Never commit:

```text
.env
Discord bot tokens
OpenAI API keys
SQLite runtime databases
```

If either API credential is accidentally committed to a public or private Git repository, assume it has been compromised and rotate it.

Do not simply delete the credential from the newest commit.

---

# Project Status

🚧 **Active development**

The screenshot extraction pipeline is functional.

The next major development areas are:

1. Event metadata extraction
2. Review / approval workflow
3. SQLite persistence
4. Historical statistics
5. Player performance commands
6. Alliance summaries
7. Bear Trap 1 support
