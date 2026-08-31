import os
import json
import asyncio
import discord
import sqlite3
from datetime import datetime, timezone

from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GUILD_ID = int(os.getenv("GUILD_ID"))

if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN is missing from .env")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is missing from .env")


# OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)


# --------------------------------------------------
# DISCORD BOT SETUP
# --------------------------------------------------

intents = discord.Intents.default()


class BearBot(commands.Bot):

    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)

        # Sync commands to your Discord server.
        await self.tree.sync(guild=guild)


bot = BearBot(
    command_prefix="!",
    intents=intents
)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


# --------------------------------------------------
# TEST COMMAND
# --------------------------------------------------

@bot.tree.command(
    name="bear",
    description="Test the Bear Trap tracker",
    guild=discord.Object(id=GUILD_ID)
)
async def bear(interaction: discord.Interaction):

    await interaction.response.send_message(
        "🐻 Bear Trap tracker is alive!"
    )


# --------------------------------------------------
# AI EXTRACTION
# --------------------------------------------------
def extract_bear_data(image_urls):

    prompt = """
You are reading screenshots from the mobile game Kingshot.

The screenshots show results from a Hunting Trap event, also called
Bear Trap.

You may receive multiple screenshots from the SAME event.

Some screenshots overlap and show duplicate player rankings.

Your job is to extract:

EVENT-LEVEL INFORMATION:
- event_type
- event_date
- event_time
- rallies
- alliance_damage

PLAYER RESULTS:
For every visible player, extract:
- rank
- player_name
- damage

IMPORTANT RULES FOR EVENT INFORMATION:

1. event_type should be the event shown in the screenshot.
   Example: "Bear Trap 2"

2. Extract the event date exactly if visible.
   Return it in YYYY-MM-DD format.

3. Extract the event time if visible.
   Return it in HH:MM:SS format.

4. rallies must be a whole integer.

5. alliance_damage must be a whole integer with no commas.

6. If any event-level information is not visible or cannot be read
   confidently, return null.

IMPORTANT RULES FOR PLAYER RESULTS:

1. Preserve the player's name as closely as possible to exactly how
   it appears on screen.

2. Do NOT autocorrect player names.

3. Preserve capitalization, numbers, spaces, and unusual spellings.

4. Do not replace unusual names with more common spellings.

5. Damage must be returned as a whole integer with no commas.

6. Do not estimate damage.

7. Do not invent players that are not visible.

8. Some screenshots overlap and show the same rank more than once.
   Extract every visible result from every screenshot.

9. Ignore profile pictures, icons, decorative UI, and alliance banners
   unless they are part of the visible player name.

10. If a player name or damage number is difficult to read, return your
    best reading but set "uncertain": true.

11. Return ONLY valid JSON.

12. Do not include markdown or explanations.

Use exactly this format:

{
  "event_type": null,
  "event_date": null,
  "event_time": null,
  "rallies": null,
  "alliance_damage": null,

  "players": [
    {
      "rank": 1,
      "player_name": "Example Player",
      "damage": 123456789,
      "uncertain": false
    }
  ]
}
"""

    content = [
        {
            "type": "input_text",
            "text": prompt
        }
    ]

    for url in image_urls:
        content.append(
            {
                "type": "input_image",
                "image_url": url,
                "detail": "high"
            }
        )

    response = client.responses.create(
        model="gpt-5",
        input=[
            {
                "role": "user",
                "content": content
            }
        ]
    )

    return json.loads(response.output_text)


# --------------------------------------------------
# MERGE DUPLICATES
# --------------------------------------------------

def merge_players(players):

    merged = {}
    conflicts = []

    for player in players:

        rank = player["rank"]

        if rank not in merged:

            merged[rank] = player

        else:

            existing = merged[rank]

            # Same information = harmless duplicate.
            if (
                existing["player_name"] == player["player_name"]
                and existing["damage"] == player["damage"]
            ):
                continue

            # Same rank but different data.
            conflicts.append(
                {
                    "rank": rank,
                    "first": existing,
                    "second": player
                }
            )

    sorted_players = [
        merged[rank]
        for rank in sorted(merged.keys())
    ]

    return sorted_players, conflicts



# --------------------------------------------------
# APPROVAL WORKFLOW
# --------------------------------------------------

class BearTrapReviewView(discord.ui.View):

    def __init__(self, data, players, source_message, submitted_by):
        super().__init__(timeout=900)
        self.data = data
        self.players = players
        self.source_message = source_message
        self.submitted_by = submitted_by
        self.completed = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.submitted_by:
            await interaction.response.send_message(
                "❌ Only the person who requested this preview can approve or reject it.",
                ephemeral=True
            )
            return False
        return True

    def disable_buttons(self):
        for child in self.children:
            child.disabled = True

    @discord.ui.button(label="Approve & Save", style=discord.ButtonStyle.success)
    async def approve(self, interaction, button):
        if self.completed:
            await interaction.response.send_message(
                "This review has already been completed.", ephemeral=True
            )
            return

        self.completed = True
        self.disable_buttons()

        try:
            event_id = await asyncio.to_thread(
                save_bear_result, self.data, self.players,
                self.source_message, interaction.user.id
            )
        except Exception as error:
            self.completed = False
            for child in self.children:
                child.disabled = False
            print("Error saving Bear Trap result:")
            print(error)
            await interaction.response.edit_message(
                content=(
                    "❌ I couldn't save this result. No data was written; "
                    "check the bot's terminal and try again."
                ),
                view=self
            )
            return

        await interaction.response.edit_message(
            content=(
                "✅ **Bear Trap result saved!**\n"
                f"Event ID: **{event_id}**\n"
                f"Player rankings saved: **{len(self.players)}**"
            ),
            view=self
        )

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction, button):
        if self.completed:
            await interaction.response.send_message(
                "This review has already been completed.", ephemeral=True
            )
            return

        self.completed = True
        self.disable_buttons()
        await interaction.response.edit_message(
            content="🗑️ **Bear Trap result rejected.** Nothing was saved.",
            view=self
        )

    async def on_timeout(self):
        if not self.completed:
            self.disable_buttons()


# --------------------------------------------------
# PROCESS BEAR TRAP MESSAGE
# --------------------------------------------------

@bot.tree.context_menu(
    name="Process Bear Trap",
    guild=discord.Object(id=GUILD_ID)
)
async def process_bear_trap(
    interaction: discord.Interaction,
    message: discord.Message
):

    print("Received Bear Trap processing request.")

    # Find image attachments.
    images = [
        attachment
        for attachment in message.attachments
        if (
            attachment.content_type
            and attachment.content_type.startswith("image/")
        )
    ]

    # Backup method if Discord doesn't provide content type.
    if not images:

        valid_extensions = (
            ".png",
            ".jpg",
            ".jpeg",
            ".webp"
        )

        images = [
            attachment
            for attachment in message.attachments
            if attachment.filename.lower().endswith(
                valid_extensions
            )
        ]

    if not images:

        await interaction.response.send_message(
            "❌ I couldn't find any images attached "
            "to that message.",
            ephemeral=True
        )

        return


    # Tell Discord we are processing.
    await interaction.response.defer(
        ephemeral=True,
        thinking=True
    )


    try:

        # Discord attachment URLs.
        image_urls = [
            image.url
            for image in images
        ]

        # Run the blocking OpenAI request in a worker thread.
        data = await asyncio.to_thread(
            extract_bear_data,
            image_urls
        )

        players = data.get("players", [])

        merged_players, conflicts = merge_players(
            players
        )


        # Build the result message.
        lines = []

        lines.append(
            "🐻 **Bear Trap data extracted!**"
        )

        lines.append(
            f"📸 Screenshots processed: "
            f"**{len(images)}**"
        )

        lines.append(
            f"👥 Unique rankings found: "
            f"**{len(merged_players)}**"
        )

        lines.append("")

        lines.append("**Event information:**")

        event_type = data.get("event_type")
        event_date = data.get("event_date")
        event_time = data.get("event_time")
        rallies = data.get("rallies")
        alliance_damage = data.get("alliance_damage")

        if event_type:
            lines.append(f"🐻 Event: **{event_type}**")

        if event_date:
            lines.append(f"📅 Date: **{event_date}**")

        if event_time:
            lines.append(f"🕒 Time: **{event_time}**")

        if rallies is not None:
            lines.append(f"🎯 Rallies: **{rallies:,}**")

        if alliance_damage is not None:
            lines.append(
                f"💥 Alliance damage: "
                f"**{alliance_damage:,}**"
            )

        if (
            not event_type
            and not event_date
            and not event_time
            and rallies is None
            and alliance_damage is None
        ):
            lines.append(
                "⚠️ No event information was found."
            )

        lines.append("")


        # Show players.
        lines.append("**Results found:**")

        for player in merged_players:

            uncertain = ""

            if player.get("uncertain", False):
                uncertain = " ⚠️"

            damage = (
                f"{player['damage']:,}"
            )

            lines.append(
                f"**{player['rank']}.** "
                f"{player['player_name']} — "
                f"{damage}{uncertain}"
            )


        # Missing ranks.
        ranks = [
            player["rank"]
            for player in merged_players
        ]

        if ranks:

            missing = [
                rank
                for rank in range(
                    min(ranks),
                    max(ranks) + 1
                )
                if rank not in ranks
            ]

            if missing:

                lines.append("")

                lines.append(
                    "⚠️ **Missing ranks:** "
                    + ", ".join(
                        str(rank)
                        for rank in missing
                    )
                )


        # Conflicts.
        if conflicts:

            lines.append("")

            lines.append(
                f"🚨 **Conflicting duplicate ranks: "
                f"{len(conflicts)}**"
            )

            for conflict in conflicts:

                lines.append(
                    f"Rank {conflict['rank']}: "
                    f"{conflict['first']['player_name']} "
                    f"vs "
                    f"{conflict['second']['player_name']}"
                )


        lines.append("")

        if conflicts:
            lines.append(
                "🚫 **Not saved — resolve conflicting ranks and reprocess.**"
            )
        else:
            lines.append("🔍 **Review this preview before saving.**")


        result = "\n".join(lines)


        # Discord messages are limited in length.
        if len(result) > 1900:

            result = result[:1850]

            result += (
                "\n\n⚠️ Output was truncated. "
                "The full report is too large for one "
                "Discord message."
            )


        review_view = None

        if not conflicts:
            review_view = BearTrapReviewView(
                data,
                merged_players,
                message,
                interaction.user.id
            )

        await interaction.followup.send(
            result,
            ephemeral=True,
            view=review_view
        )

    except Exception as error:

        print(
            "Error processing Bear Trap:"
        )

        print(error)

        await interaction.followup.send(
            "❌ I ran into an error while processing "
            "those screenshots. Check the bot's "
            "terminal for the error.",
            ephemeral=True
        )


DB_PATH = "data/beartrap.db"



def save_bear_result(data, players, source_message, submitted_by):
    if not players:
        raise ValueError("Cannot save a result with no player rankings.")

    connection = sqlite3.connect(DB_PATH)

    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO events (
                event_type,
                event_date,
                event_time,
                rallies,
                alliance_damage,
                submitted_by,
                discord_message_id,
                discord_channel_id,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("event_type") or "Unknown Bear Trap",
                data.get("event_date"),
                data.get("event_time"),
                data.get("rallies"),
                data.get("alliance_damage"),
                str(submitted_by),
                str(source_message.id),
                str(source_message.channel.id),
                datetime.now(timezone.utc).isoformat(timespec="seconds")
            )
        )

        event_id = cursor.lastrowid
        cursor.executemany(
            """
            INSERT INTO player_results (
                event_id,
                rank,
                player_name,
                damage,
                uncertain
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    event_id,
                    player["rank"],
                    player["player_name"],
                    player["damage"],
                    int(player.get("uncertain", False))
                )
                for player in players
            ]
        )

        connection.commit()
        return event_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def setup_database():

    os.makedirs("data", exist_ok=True)

    connection = sqlite3.connect(DB_PATH)
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            event_date TEXT,
            rallies INTEGER,
            alliance_damage INTEGER,
            submitted_by TEXT,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS player_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            rank INTEGER NOT NULL,
            player_name TEXT NOT NULL,
            damage INTEGER NOT NULL,

            FOREIGN KEY (event_id)
                REFERENCES events(id)
        )
    """)



    event_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(events)")
    }

    if "event_time" not in event_columns:
        cursor.execute("ALTER TABLE events ADD COLUMN event_time TEXT")

    if "discord_message_id" not in event_columns:
        cursor.execute(
            "ALTER TABLE events ADD COLUMN discord_message_id TEXT"
        )

    if "discord_channel_id" not in event_columns:
        cursor.execute(
            "ALTER TABLE events ADD COLUMN discord_channel_id TEXT"
        )

    result_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(player_results)")
    }

    if "uncertain" not in result_columns:
        cursor.execute(
            "ALTER TABLE player_results "
            "ADD COLUMN uncertain INTEGER NOT NULL DEFAULT 0"
        )
    connection.commit()
    connection.close()

setup_database()
bot.run(DISCORD_TOKEN)
