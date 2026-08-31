import os
import json
import asyncio
import discord
import sqlite3
from datetime import datetime

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

The screenshots show a Hunting Trap 2 / Bear Trap damage ranking.

Your job is to extract ONLY the visible player ranking results.

First, extract any event-level information visible in the
screenshots:

- event_type
- event_date
- rallies
- alliance_damage

If something is not visible, return null.

Then extract every visible player result.

IMPORTANT RULES:

1. Preserve the player's name exactly as displayed.
2. Damage must be returned as a whole integer with no commas.
3. Do not estimate damage.
4. Do not invent players that are not visible.
5. Some screenshots overlap and show the same rank more than once.
   Extract every visible result from every screenshot anyway.
6. Ignore icons, profile pictures, alliance banners, and decorative UI.
7. If you are unsure about a name or damage number, return your best
   reading and add "uncertain": true.
8. Return ONLY valid JSON.
9. Do not include markdown or explanations.

Use exactly this format:

{
  "event_type": "Bear Trap 2",
  "event_date": null,
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
        lines.append(
            "🔍 **Preview only — not saved yet.**"
        )


        result = "\n".join(lines)


        # Discord messages are limited in length.
        if len(result) > 1900:

            result = result[:1850]

            result += (
                "\n\n⚠️ Output was truncated. "
                "The full report is too large for one "
                "Discord message."
            )


        await interaction.followup.send(
            result,
            ephemeral=True
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

    connection.commit()
    connection.close()

setup_database()
bot.run(DISCORD_TOKEN)
