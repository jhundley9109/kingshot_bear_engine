# Kingshot Bear Trap Discord Bot - Project Handoff

## Project Overview

This is a custom Discord bot for a Kingshot alliance that tracks player performance in the game's **Hunting Trap**, commonly referred to by the alliance as **Bear Trap**.

The immediate focus is **Bear Trap 2**, but the architecture should eventually support Bear Trap 1 and other event types.

The main problem being solved is that Kingshot does not provide an easy way to export Bear Trap rankings as text. The results are primarily available as screenshots.

The bot therefore uses:

1. Discord for report submission
2. OpenAI vision to read screenshots
3. Structured JSON extraction
4. Validation and duplicate merging
5. SQLite for historical storage
6. Discord for displaying summaries and statistics

---

# Current Workflow

The current workflow is:

```text
User uploads multiple Bear Trap screenshots
        |
        v
Screenshots are attached to ONE Discord message
        |
        v
User right-clicks the message
        |
        v
Apps -> Process Bear Trap
        |
        v
Discord bot receives the message attachments
        |
        v
OpenAI Vision processes all screenshots together
        |
        v
Structured player data is returned
        |
        v
Python merges duplicate ranks from overlapping screenshots
        |
        v
Bot displays an ephemeral preview
```

The current version DOES NOT permanently save results yet.

---

# Current Environment

Development is being done directly on an Ubuntu server over SSH.

Project location:

```text
~/bear-bot
```

Current structure is approximately:

```text
bear-bot/
├── .env
├── .git/
├── .gitignore
├── bot.py
├── requirements.txt
├── HANDOFF.md
├── data/
└── venv/
```

Important:

- `.env` is NOT committed
- `venv/` is NOT committed
- `data/` is NOT committed
- Git repository is configured and pushed to GitHub
- GitHub remote configuration is already working

---

# Environment Variables

The `.env` file contains:

```env
DISCORD_TOKEN=...
OPENAI_API_KEY=...
GUILD_ID=...
```

Do not expose, print, commit, or modify these secrets.

`GUILD_ID` is the Discord server ID used for guild-specific command syncing during development.

---

# Python Dependencies

The project currently uses:

```text
discord.py
openai
python-dotenv
aiosqlite
```

The installed environment may contain additional packages captured in `requirements.txt`.

Activate the virtual environment with:

```bash
cd ~/bear-bot
source venv/bin/activate
```

Run the bot with:

```bash
python bot.py
```

Stop the bot with:

```text
Ctrl+C
```

---

# Current Discord Bot Features

## Slash Command

The following command works:

```text
/bear
```

Expected response:

```text
🐻 Bear Trap tracker is alive!
```

This confirms that:

- Discord token is valid
- Bot is online
- Application commands are syncing correctly
- Guild ID is correct

---

# Current Screenshot Processing

The bot has a Discord message context-menu command:

```text
Process Bear Trap
```

Workflow:

1. User posts one Discord message
2. The message contains multiple Bear Trap screenshots as attachments
3. User right-clicks the message
4. User selects:

```text
Apps -> Process Bear Trap
```

5. The bot collects image attachments
6. The bot sends the images to OpenAI
7. The bot extracts ranking data
8. The bot displays an ephemeral preview

The current attachment handling checks:

- Discord attachment `content_type`
- Image file extensions as a fallback

Supported extensions currently include:

```text
.png
.jpg
.jpeg
.webp
```

---

# Screenshot Characteristics

Kingshot reports are spread across multiple screenshots.

Important behavior:

- Screenshots can overlap
- The same player/rank may appear in multiple screenshots
- The player's own ranking may be pinned at the bottom of screenshots
- The pinned player may therefore appear repeatedly
- Player names can include:
  - alliance tags such as `[XuX]`
  - spaces
  - capitalization
  - numbers
  - special characters
  - Arabic characters
  - unusual spelling
- Damage values are large integers

The bot currently sends all screenshots together in one OpenAI request.

Example rankings:

```text
1. [XuX]INCREDIBLE HoSSy — 1,746,978,512
2. [XuX]MountainMan — 1,502,037,235
3. [XuX]annak — 1,082,223,708
4. [XuX]Scarlettbgonya — 944,101,284
5. [XuX]DeviconB — 767,368,184
...
12. [XuX]El Beef Chalupa — 452,453,767
```

---

# Current OpenAI Extraction

The bot currently sends a detailed prompt requesting structured JSON.

The intended output format is:

```json
{
  "players": [
    {
      "rank": 1,
      "player_name": "[XuX]INCREDIBLE HoSSy",
      "damage": 1746978512,
      "uncertain": false
    }
  ]
}
```

The bot then parses:

```python
json.loads(response.output_text)
```

The OpenAI request is blocking, so the Discord async handler runs it using:

```python
await asyncio.to_thread(
    extract_bear_data,
    image_urls
)
```

This prevents the blocking API request from freezing the Discord event loop.

The current model configured in `bot.py` is:

```python
model="gpt-5"
```

The model receives all screenshot URLs as image inputs in a single request.

---

# Current Extraction Results

The first real test used four screenshots.

The bot extracted 19 unique rankings successfully.

Example output:

```text
🐻 Bear Trap data extracted!

📸 Screenshots processed: 4
👥 Unique rankings found: 19

Results found:

1. [XuX]INCREDIBLE HoSSy — 1,746,978,512
2. [XuX]MountainMan — 1,502,037,235
3. [XuX]annak — 1,082,223,708
4. [XuX]Scarlettbgonya — 944,101,284
5. [XuX]DeyiconB — 767,368,184
6. [XuX]QueenBee — 708,954,229
7. [XuX]HECTO15 — 611,351,532
8. [XuX]Geras699 — 579,620,657 ⚠️
9. [XuX]Dhamms — 547,229,752
10. [XuX]Scotty Boy — 496,738,856
11. [XuX]Ranger1181 — 491,572,262
12. [XuX]El Beef Chalupa — 452,453,767
13. [XuX]منتصر — 438,462,951
14. [XuX]Poisonxx — 336,247,035
15. [XuX]Lord H3llFire — 303,549,418
16. [XuX]Zer0th — 259,246,520 ⚠️
17. [XuX]King tut — 188,220,477
18. [XuX]turbo — 78,816,102
19. [XuX]Teteu — 7,339,341
```

This was considered a very successful first extraction.

However, there was at least one likely player-name OCR error:

```text
Expected:
[XuX]DeviconB

Extracted:
[XuX]DeyiconB
```

This is one reason the next stage should include an approval/review workflow before data is permanently saved.

---

# Current Duplicate Handling

The bot has a `merge_players(players)` function.

Players are merged by rank.

If two screenshots contain the exact same:

- rank
- player name
- damage

then the duplicate is ignored.

If the same rank contains different data, it is recorded as a conflict.

The intended behavior is:

```text
Screenshot A:
Rank 12 -> El Beef Chalupa -> 452,453,767

Screenshot B:
Rank 12 -> El Beef Chalupa -> 452,453,767

Result:
One player result
```

But:

```text
Rank 5 -> Player A
Rank 5 -> Player B
```

should generate a conflict requiring review.

The bot also detects missing ranks.

Example:

```text
Ranks found:
1, 2, 3, 5

Missing:
4
```

---

# Important Prompt Behavior

The extraction prompt should emphasize:

```text
Player names are highly important.

Copy player names character-for-character as closely as possible.

Do not autocorrect names.

Do not replace unusual spellings with more common names.

Preserve:

- capitalization
- numbers
- spaces
- special characters
- unusual spellings

If any characters are difficult to read, return the best reading
and set:

"uncertain": true
```

Damage should always be returned as an integer with no commas.

Do not estimate or invent damage.

---

# Immediate Next Step

The next feature to implement is:

## Event Metadata Extraction

The AI extraction should also return:

```text
event_type
event_date
event_time
rallies
alliance_damage
```

The intended JSON format is:

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
      "player_name": "[XuX]INCREDIBLE HoSSy",
      "damage": 1746978512,
      "uncertain": false
    }
  ]
}
```

If a metadata field is not visible, it should return:

```json
null
```

Do not invent event metadata.

The current bot should display this information in the preview before saving anything.

---

# Planned Development Roadmap

## Phase 1 - DONE

- Discord bot created
- `/bear` test command working
- Context menu command working
- Multiple screenshots accepted
- OpenAI vision processing working
- Structured JSON extraction working
- Duplicate ranks merged
- Missing ranks detected
- Conflicting duplicate ranks detected
- Ephemeral preview displayed

---

## Phase 2 - NEXT

### Add event metadata extraction

Extract:

```text
event_type
event_date
event_time
rallies
alliance_damage
```

Display the metadata in the preview.

Do not save anything permanently yet.

---

## Phase 3 - Approval Workflow

Add buttons to the preview:

```text
Approve & Save
Reject
```

Possibly later:

```text
Edit Result
```

The ideal initial behavior:

```text
OpenAI extraction
        |
        v
Preview
        |
        +-------------------+
        |                   |
        v                   v
Approve                 Reject
        |                   |
        v                   v
Save to DB            Discard
```

Potential issue:

Discord interaction buttons have time limits, so the approval architecture should account for interaction expiration and avoid storing secrets or huge data structures in button IDs.

---

# Phase 4 - SQLite Database

SQLite is the planned permanent storage.

Suggested schema:

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
created_at
```

And:

```text
player_results
--------------
id
event_id
rank
player_name
damage
uncertain
```

Potentially also store:

```text
discord_message_id
discord_channel_id
```

for traceability.

The database file should be:

```text
data/beartrap.db
```

The database should NOT be committed to Git.

The `data/` directory is ignored.

---

# Phase 5 - Historical Statistics

Once multiple Bear Trap reports are stored, add commands such as:

```text
/bear leaderboard
/bear player
/bear summary
/bear compare
```

Potential statistics:

- Highest damage
- Average damage
- Personal best
- Alliance total damage trend
- Player improvement over previous event
- Biggest percentage increase
- Most consistent player
- Participation frequency
- Average alliance participation
- Historical rankings

Important design principle:

Use Python and SQLite for numerical/statistical calculations.

Use OpenAI primarily for:

- screenshot extraction
- natural language summaries
- fun alliance commentary

Do NOT repeatedly send the entire historical database to OpenAI.

The database should calculate the numbers first.

Then a compact summary can optionally be sent to OpenAI for commentary.

---

# Future AI Summary Example

The bot could calculate:

```json
{
  "event": "Bear Trap 2",
  "players": 42,
  "alliance_damage": 12000000000,
  "top_player": {
    "name": "Example",
    "damage": 1500000000
  },
  "biggest_improvement": {
    "name": "Example Player",
    "percent_change": 18.4
  }
}
```

Then ask OpenAI to generate a fun alliance summary.

This avoids token/context problems as the history grows.

---

# Future Bear Trap 1 Support

The database should support:

```text
Bear Trap 1
Bear Trap 2
```

Do not hard-code the entire application around Bear Trap 2.

`event_type` should remain a field.

Future event types may also be supported.

---

# Design Principles

1. Accuracy is more important than automation.
2. OCR/vision mistakes should be reviewable before permanent storage.
3. Never silently save uncertain data without a review path.
4. Preserve raw player names exactly when possible.
5. Do not use OpenAI for calculations that Python can perform.
6. Do not make one giant historical text file.
7. Do not repeatedly send the entire history to OpenAI.
8. SQLite is the source of truth.
9. Git is for source code, not runtime data or secrets.
10. Keep the first version simple and working before adding advanced features.

---

# Suggested Next Cursor Task

Review the current `bot.py` before making changes.

Then implement:

1. Event metadata extraction in `extract_bear_data()`.
2. Update the expected JSON structure.
3. Add event metadata to the ephemeral preview.
4. Preserve current ranking extraction behavior.
5. Preserve duplicate merging.
6. Preserve conflict detection.
7. Do NOT add permanent database saving yet.
8. Do NOT modify `.env` or expose secrets.

After implementing, test by:

1. Starting the bot.
2. Uploading a multi-screenshot Bear Trap report.
3. Right-clicking the message.
4. Selecting:

```text
Apps -> Process Bear Trap
```

Expected result:

- Event metadata shown when visible
- Player rankings extracted
- Duplicate ranks merged
- Missing ranks shown if applicable
- Uncertain entries marked
- No permanent data saved yet
