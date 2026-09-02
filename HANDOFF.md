# Kingshot Bear Engine - Application Guide

## Purpose

Kingshot Bear Engine is a Discord bot for tracking Kingshot Hunting Trap, also called Bear Trap, performance from screenshots.

The game does not provide a clean export for Bear Trap rankings, so the bot accepts screenshots in Discord, uses OpenAI vision to extract structured data, lets the user review the parsed results, and stores approved reports in SQLite for later reporting.

The app supports multiple Bear events by tying saved reports to the Discord channel where they were processed. For example, `#bear-trap-1` and `#bear-trap-2` are tracked separately by default, while reporting commands can also query a selected channel or all saved Bear channels.

## Runtime Environment

The bot is intended to run on the remote Ubuntu server over SSH.

Typical runtime location:

```text
/home/jhundley/git/kingshot_bear_bot
```

Local development/review may happen in:

```text
/Users/jhundley/git/kingshot_bear_engine
```

Do not assume local macOS runs are equivalent to the Ubuntu runtime. Local syntax checks are fine, but bot runtime behavior should be validated on the Ubuntu server.

## Environment Variables

The `.env` file is required and must not be committed.

```env
DISCORD_TOKEN=...
OPENAI_API_KEY=...
GUILD_ID=...
```

`DISCORD_TOKEN` is the Discord bot token.

`OPENAI_API_KEY` is used for screenshot parsing.

`GUILD_ID` is the Discord server ID where guild-scoped slash/context-menu commands are synced.

To run the same bot on a different Discord server, update `GUILD_ID`, invite the bot to that server, and restart the process. Only change `DISCORD_TOKEN` if switching to a different Discord application/bot.

## Running The Bot

Activate the venv and start the process:

```bash
cd /home/jhundley/git/kingshot_bear_bot
source venv/bin/activate
python3 bot.py
```

To keep it running after SSH disconnects:

```bash
cd /home/jhundley/git/kingshot_bear_bot
source venv/bin/activate
mkdir -p logs
nohup python3 bot.py >> logs/bot.log 2>&1 &
```

Tail logs:

```bash
tail -f logs/bot.log
```

Find the running process:

```bash
ps aux | grep '[p]ython3 bot.py'
```

Stop it:

```bash
pkill -f 'python3 bot.py'
```

## High-Level Workflow

```text
User uploads Bear screenshots to a Discord message
        |
        v
User runs Apps -> Process Bear Trap on that message
        |
        v
Bot collects image attachments
        |
        v
OpenAI extracts event metadata and player results as JSON
        |
        v
Bot merges duplicate screenshot overlap and detects conflicts
        |
        v
Bot shows an ephemeral review message
        |
        v
User clicks Approve & Save, Replace existing report, or Reject
        |
        v
Approved data is written to SQLite
```

The bot logs when it receives a processing request and when the OpenAI extraction response returns.

## Screenshot Parsing

The context-menu command is:

```text
Process Bear Trap
```

It accepts image attachments using Discord attachment content types, with filename extension fallback for:

```text
.png
.jpg
.jpeg
.webp
```

The extraction prompt asks OpenAI to return JSON with:

```json
{
  "event_type": "Bear Trap 2",
  "event_date": "2026-08-30",
  "event_time": "21:30:05",
  "rallies": 70,
  "alliance_damage": 11542511822,
  "players": [
    {
      "rank": 1,
      "player_name": "Example Player",
      "damage": 123456789,
      "uncertain": false
    }
  ]
}
```

Event metadata can come from overview screenshots that include the success message, date/time, rallies, and total alliance damage.

If event date/time are missing, the save path falls back to the report submission timestamp.

## Review And Duplicate Handling

Screenshots often overlap. The same rank can appear in more than one screenshot.

Duplicate player rows are merged when they have the same rank, same damage, and effectively the same player name.

Player-name matching ignores leading alliance tags like `[XuX]`, so these are treated as the same player for matching:

```text
Capitano Totti
[XuX]Capitano Totti
```

If the same rank has conflicting data, the bot shows a conflict warning and does not allow saving until the screenshots are corrected or reprocessed.

If a matching saved report is detected, the review message enables `Replace existing report` so the event can be overwritten instead of duplicated.

## Commands

Root commands:

```text
/bear status
/bear summary
/bear leaderboard
/bear recap events:<2-10>
```

Player commands:

```text
/bear player list
/bear player search name:<name>
/bear player stats playername:<name>
/bear player rename old_name:<old> new_name:<new>
/bear player trend name:<name> months:<1|3>
```

Event commands:

```text
/bear event list
/bear event details event_id:<id>
/bear event delete event_id:<id>
/bear event trend months:<1|3>
```

Most reporting commands default to the Discord channel where they are run. This keeps `#bear-trap-1` and `#bear-trap-2` separated naturally.

Reporting commands also support optional scope parameters:

```text
channel:#bear-trap-2
all_channels:true
```

Useful test-channel examples:

```text
/bear event list all_channels:true
/bear leaderboard all_channels:true
/bear summary channel:#bear-trap-2
/bear player search name:lord stark all_channels:true
/bear player trend name:lord stark months:1 all_channels:true
/bear event trend months:1 all_channels:true
```

`/bear event list all_channels:true` includes the source channel name so saved events can be reviewed from a private testing/admin channel.

## Data Model

SQLite database:

```text
data/beartrap.db
```

The database and `data/` directory should not be committed.

Tables:

```text
events
------
id
event_type
event_date
event_time
rallies
alliance_damage
submitted_by
discord_message_id
discord_channel_id
discord_channel_name
created_at
```

```text
players
-------
id
canonical_name
created_at
updated_at
```

```text
player_aliases
--------------
id
player_id
alias_name
normalized_name
visual_key
```

```text
player_results
--------------
id
event_id
player_id
rank
player_name
damage
uncertain
```

`players` is the canonical identity table. Historical results point to `player_id`, so renaming a player preserves the full history.

`player_aliases` stores names seen from OCR and from manual renames. The identity resolver uses normalized names, visual keys, and fuzzy matching to catch likely OCR variations such as `Zer0th` vs `ZerOth`.

`player_results.player_name` stores the raw visible name from the screenshot for traceability.

## Code Structure

```text
bot.py
data_access.py
models/
  event/
    event_factory.py
    event_model.py
  player/
    player_factory.py
    player_model.py
  player_result/
    player_result_factory.py
    player_result_model.py
services/
  trend_chart_service.py
```

`bot.py` owns Discord setup, slash commands, context-menu processing, review buttons, formatting, and the OpenAI extraction prompt.

`data_access.py` exposes the `BearTrapRepository`, which coordinates database writes across events, players, aliases, and player results.

Each model folder contains:

```text
<thing>_model.py
<thing>_factory.py
```

Factory classes own SQL and return model objects or report rows.

Model classes expose getters and setters for table fields.

`services/trend_chart_service.py` generates chart images for player and event trends.

## Maintenance Notes

Restart the bot after changing command signatures, command descriptions, or guild configuration so Discord command sync can run again.

Use a private Discord test channel for testing reports without cluttering the real Bear channel. Reporting commands can read real Bear data from the test channel using `channel:` or `all_channels:true`.

Back up the SQLite database before manual cleanup:

```bash
cp data/beartrap.db data/beartrap.db.backup
```

Example cleanup for leading `[XuX]` canonical names:

```sql
UPDATE players
SET canonical_name = TRIM(SUBSTR(canonical_name, 6)),
    updated_at = datetime('now')
WHERE LOWER(canonical_name) LIKE '[xux]%';
```

Usually keep aliases even if canonical names are cleaned, because aliases help future OCR readings match the correct player.

## Development Checks

Local syntax check:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/kingshot_bear_pycache python3 -m py_compile bot.py data_access.py models/event/event_factory.py models/player/player_factory.py models/player_result/player_result_factory.py services/trend_chart_service.py
```

Chart rendering requires `matplotlib` in the active Python environment. The Ubuntu venv is the expected place to validate real chart generation.
