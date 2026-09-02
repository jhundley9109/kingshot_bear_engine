import os
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI

from commands.event_commands import register_event_commands
from commands.player_commands import register_player_commands
from commands.process_command import register_process_command
from commands.root_commands import register_root_commands
from data_access import BearTrapRepository


load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
guild_ids_value = os.getenv("GUILD_IDS") or os.getenv("GUILD_ID", "")
GUILD_IDS = [
    int(value.strip()) for value in guild_ids_value.split(",") if value.strip()
]
BOT_OWNER_IDS = {
    int(value.strip())
    for value in os.getenv("BOT_OWNER_IDS", "").split(",")
    if value.strip()
}

if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN is missing from .env")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is missing from .env")
if not GUILD_IDS:
    raise ValueError("GUILD_IDS or GUILD_ID is missing from .env")


def log_event(message):
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{timestamp}] {message}", flush=True)


class BearBot(commands.Bot):
    async def setup_hook(self):
        for guild_id in GUILD_IDS:
            await self.tree.sync(guild=discord.Object(id=guild_id))


client = OpenAI(api_key=OPENAI_API_KEY)
repository = BearTrapRepository("data/beartrap.db")
bot = BearBot(command_prefix="!", intents=discord.Intents.default())
configured_guilds = [discord.Object(id=guild_id) for guild_id in GUILD_IDS]

bear_group = app_commands.Group(
    name="bear",
    description="Bear Trap reports and statistics",
)
bear_player_group = app_commands.Group(
    name="player",
    description="Player history and identity tools",
)
bear_event_group = app_commands.Group(
    name="event",
    description="Bear Trap event reports and management",
)
bear_group.add_command(bear_player_group)
bear_group.add_command(bear_event_group)

register_root_commands(
    bear_group,
    repository,
    client,
    BOT_OWNER_IDS,
    log_event,
)
register_player_commands(
    bear_player_group,
    repository,
    bot,
    BOT_OWNER_IDS,
    log_event,
)
register_event_commands(
    bear_event_group,
    repository,
    BOT_OWNER_IDS,
    log_event,
)
bot.tree.add_command(bear_group, guilds=configured_guilds)
register_process_command(
    bot.tree,
    configured_guilds,
    repository,
    client,
    log_event,
)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


def main():
    repository.setup(GUILD_IDS[0])
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
