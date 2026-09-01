import os
import json
import asyncio
import discord
import re
import unicodedata
from datetime import datetime, timedelta, timezone

from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI

from data_access import BearTrapRepository
from services.trend_chart_service import create_event_trend_chart, create_player_trend_chart


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
# BEAR TRAP COMMAND GROUP
# --------------------------------------------------

bear_group = app_commands.Group(
    name="bear",
    description="Bear Trap reports and statistics"
)

bot.tree.add_command(
    bear_group,
    guild=discord.Object(id=GUILD_ID)
)

bear_player_group = app_commands.Group(
    name="player",
    description="Player history and identity tools"
)
bear_group.add_command(bear_player_group)

bear_event_group = app_commands.Group(
    name="event",
    description="Bear Trap event reports and management"
)
bear_group.add_command(bear_event_group)


# --------------------------------------------------
# LOGGING
# --------------------------------------------------
def log_event(message):
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{timestamp}] {message}", flush=True)


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

7. One attachment may be a Mail / Success / Battle Overview screenshot.
   It may show a timestamp banner, event text such as "[Hunting Trap 2]",
   and the exact labels "Rallies:" and "Total Alliance Damage:".
   Read those values as event metadata.

8. Treat the Battle Overview's Total Alliance Damage as the authoritative
   alliance_damage value. Do not derive it from a partial player-ranking
   screenshot.

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

def player_match_name(name):
    normalized = unicodedata.normalize("NFKC", str(name)).casefold()
    normalized = re.sub(r"^\s*(\[[^\]]{1,12}\]\s*)+", "", normalized)
    return " ".join(normalized.split())


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
                player_match_name(existing["player_name"])
                == player_match_name(player["player_name"])
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

    def __init__(
        self, data, players, source_message, submitted_by,
        submitted_at, existing_event_id=None
    ):
        super().__init__(timeout=900)
        self.data = data
        self.players = players
        self.source_message = source_message
        self.submitted_by = submitted_by
        self.submitted_at = submitted_at
        self.existing_event_id = existing_event_id
        self.completed = False
        self.replace_existing.disabled = existing_event_id is None

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

    async def save_review(self, interaction, replace_existing=False):
        if self.completed:
            await interaction.response.send_message(
                "This review has already been completed.", ephemeral=True
            )
            return
        if self.existing_event_id and not replace_existing:
            await interaction.response.send_message(
                "⚠️ This matches an existing saved report. Use **Replace existing report** "
                "to overwrite it, or Reject to discard this preview.",
                ephemeral=True
            )
            return

        self.completed = True
        self.disable_buttons()
        try:
            if replace_existing:
                event_id = await asyncio.to_thread(
                    repository.replace_result, self.existing_event_id, self.data,
                    self.players, self.source_message, interaction.user.id,
                    self.submitted_at
                )
                action = "replaced"
            else:
                event_id = await asyncio.to_thread(
                    repository.save_result, self.data, self.players,
                    self.source_message, interaction.user.id,
                    self.submitted_at
                )
                action = "saved"
        except Exception as error:
            self.completed = False
            for child in self.children:
                child.disabled = False
            self.replace_existing.disabled = self.existing_event_id is None
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
                f"✅ **Bear Trap result {action}!**\n"
                f"Event ID: **{event_id}**\n"
                f"Player rankings saved: **{len(self.players)}**"
            ),
            view=self
        )

    @discord.ui.button(label="Approve & Save", style=discord.ButtonStyle.success)
    async def approve(self, interaction, button):
        await self.save_review(interaction)

    @discord.ui.button(
        label="Replace existing report", style=discord.ButtonStyle.secondary
    )
    async def replace_existing(self, interaction, button):
        await self.save_review(interaction, replace_existing=True)

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


class EventDeleteView(discord.ui.View):
    def __init__(self, event_id, channel_id, requested_by):
        super().__init__(timeout=900)
        self.event_id = event_id
        self.channel_id = channel_id
        self.requested_by = requested_by

    async def interaction_check(self, interaction):
        if interaction.user.id != self.requested_by:
            await interaction.response.send_message(
                "❌ Only the user who requested this deletion can confirm it.",
                ephemeral=True
            )
            return False
        return True

    def disable_buttons(self):
        for child in self.children:
            child.disabled = True

    @discord.ui.button(label="Confirm delete", style=discord.ButtonStyle.danger)
    async def confirm_delete(self, interaction, button):
        self.disable_buttons()
        try:
            event = await asyncio.to_thread(
                repository.delete_event,
                self.event_id,
                self.channel_id
            )
        except ValueError as error:
            await interaction.response.edit_message(content=f"❌ {error}", view=self)
            return
        await interaction.response.edit_message(
            content=(
                f"🗑️ Deleted Event ID **{event.get_event_id()}** "
                f"({event.get_event_date()} {event.get_event_time()})."
            ),
            view=self
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_delete(self, interaction, button):
        self.disable_buttons()
        await interaction.response.edit_message(
            content="Deletion cancelled. Nothing was changed.",
            view=self
        )


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

    report_submitted_at = datetime.now(timezone.utc)
    log_event("Received Bear Trap processing request.")

    await interaction.response.defer(
        ephemeral=True,
        thinking=True
    )

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

        await interaction.followup.send(
            "❌ I couldn't find any images attached "
            "to that message.",
            ephemeral=True
        )

        return


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

        log_event("Received OpenAI Bear Trap extraction response.")

        players = data.get("players", [])

        merged_players, conflicts = merge_players(
            players
        )

        existing_event_id = await asyncio.to_thread(
            repository.find_existing_report,
            data,
            message
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

        if existing_event_id:
            lines.append(
                f"⚠️ Existing saved report detected: **Event ID {existing_event_id}**"
            )

        event_type = data.get("event_type")
        event_date = data.get("event_date")
        event_time = data.get("event_time")
        rallies = data.get("rallies")
        alliance_damage = data.get("alliance_damage")

        if event_type:
            lines.append(f"🐻 Event: **{event_type}**")

        lines.append(
            f"📅 Date: **{event_date or 'Not found'}**"
        )
        lines.append(
            f"🕒 Time: **{event_time or 'Not found'}**"
        )

        if rallies is not None:
            lines.append(f"🎯 Rallies: **{rallies:,}**")

        extracted_player_damage = sum(
            player["damage"]
            for player in merged_players
        )

        if alliance_damage is not None:
            lines.append(
                f"💥 Alliance damage: "
                f"**{alliance_damage:,}**"
            )
            lines.append(
                f"👥 Extracted player damage: "
                f"**{extracted_player_damage:,}**"
            )

            difference = alliance_damage - extracted_player_damage
            if difference:
                lines.append(
                    f"ℹ️ Difference: **{difference:,}** "
                    "(likely rankings not included in the screenshots)"
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
        elif existing_event_id:
            lines.append(
                "🔁 **A matching report exists — use Replace existing report "
                "to overwrite it.**"
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
                interaction.user.id,
                report_submitted_at,
                existing_event_id
            )

        send_options = {
            "ephemeral": True
        }
        if review_view is not None:
            send_options["view"] = review_view

        await interaction.followup.send(
            result,
            **send_options
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
repository = BearTrapRepository(DB_PATH)


def resolve_report_channel_id(interaction, channel=None, all_channels=False):
    if all_channels:
        return None
    if channel is not None:
        return channel.id
    return interaction.channel_id


def report_scope_label(interaction, channel=None, all_channels=False):
    if all_channels:
        return "all Bear channels"
    selected = channel or interaction.channel
    channel_name = getattr(selected, "name", None)
    if channel_name:
        return f"#{channel_name}"
    return "this channel"


def channel_label(value):
    return value or "unknown-channel"


@bear_group.command(name="status", description="Check the Bear Trap tracker")
async def bear_status(interaction: discord.Interaction):
    await interaction.response.send_message("🐻 Bear Trap tracker is alive!")


@bear_group.command(
    name="summary",
    description="Show the most recently saved Bear Trap report"
)
@app_commands.describe(
    channel="Optional Bear channel to read from",
    all_channels="Show the latest report across all Bear channels"
)
async def bear_summary(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None,
    all_channels: bool = False
):
    await interaction.response.defer(thinking=True)
    channel_id = resolve_report_channel_id(interaction, channel, all_channels)
    scope = report_scope_label(interaction, channel, all_channels)
    event, players = await asyncio.to_thread(
        repository.fetch_latest_summary,
        channel_id
    )

    if event is None:
        await interaction.followup.send(
            f"🐻 No approved Bear Trap reports have been saved for {scope} yet."
        )
        return

    leaders = players[:5]

    lines = [
        f"🐻 **{event.get_event_type()} summary**",
        f"Event ID: **{event.get_event_id()}**",
        f"Channel: **#{channel_label(event.get_discord_channel_name())}**",
        f"Players: **{len(players)}**",
    ]

    if event.get_event_date():
        event_label = event.get_event_date()
        if event.get_event_time():
            event_label += f" {event.get_event_time()}"
        lines.append(f"Date: **{event_label}**")

    if event.get_rallies() is not None:
        lines.append(f"Rallies: **{event.get_rallies():,}**")

    if event.get_alliance_damage() is not None:
        lines.append(f"Alliance damage: **{event.get_alliance_damage():,}**")

    uncertain_count = sum(player.get_uncertain() for player in players)
    if uncertain_count:
        lines.append(f"⚠️ Uncertain entries: **{uncertain_count}**")

    if leaders:
        lines.append("")
        lines.append("**Top 5**")
        for player in leaders:
            uncertain = " ⚠️" if player.get_uncertain() else ""
            lines.append(
                f"{player.get_rank()}. {player.get_raw_player_name()} — "
                f"{player.get_damage():,}{uncertain}"
            )

    await interaction.followup.send("\n".join(lines))


def _table_text(value, width):
    value = str(value).replace("`", "'")
    if len(value) <= width:
        return value
    return value[: width - 3] + "..."


def _damage_text(value):
    return f"{int(value or 0):,}"


def _has_rtl_text(value):
    return any(unicodedata.bidirectional(char) in {"R", "AL", "AN"} for char in value)


def _table_name_cell(value, width):
    value = _table_text(value, width)
    padding = " " * max(0, width - len(value))
    if _has_rtl_text(value):
        return f"{padding}\u2067{value}\u2069"
    return f"{padding}{value}"


def _leaderboard_table_chunks(players, max_message_length=1900):
    header = (
        f"{'#':>3}  {'Player':>24}  {'Events':>6}  "
        f"{'Total Damage':>16}  {'Avg/Event':>14}  {'Best':>16}"
    )
    separator = (
        f"{'-' * 3}  {'-' * 24}  {'-' * 6}  "
        f"{'-' * 16}  {'-' * 14}  {'-' * 16}"
    )
    chunks = []
    current = ["```text", header, separator]

    for position, player in enumerate(players, start=1):
        row = (
            f"{position:>3}  "
            f"{_table_name_cell(player['player_name'], 24)}  "
            f"{player['appearances']:>6}  "
            f"{_damage_text(player['total_damage']):>16}  "
            f"{_damage_text(player['average_damage']):>14}  "
            f"{_damage_text(player['best_damage']):>16}"
        )
        candidate = "\n".join(current + [row, "```"])
        if len(candidate) > max_message_length and len(current) > 3:
            current.append("```")
            chunks.append("\n".join(current))
            current = ["```text", header, separator]
        current.append(row)

    current.append("```")
    chunks.append("\n".join(current))
    return chunks


@bear_group.command(
    name="leaderboard",
    description="Rank players by total saved Bear Trap damage"
)
@app_commands.describe(
    limit="Maximum players to show. Use 0 or leave blank for all players.",
    channel="Optional Bear channel to read from",
    all_channels="Rank players across all Bear channels"
)
async def bear_leaderboard(
    interaction: discord.Interaction,
    limit: int = 0,
    channel: discord.TextChannel = None,
    all_channels: bool = False
):
    limit = max(0, min(limit, 100))
    row_limit = limit or None
    channel_id = resolve_report_channel_id(interaction, channel, all_channels)
    scope = report_scope_label(interaction, channel, all_channels)
    await interaction.response.defer(thinking=True)
    players = await asyncio.to_thread(
        repository.fetch_leaderboard,
        channel_id,
        row_limit
    )

    if not players:
        await interaction.followup.send(
            f"🐻 No approved Bear Trap reports have been saved for {scope} yet."
        )
        return

    total_events = players[0]["total_events"] or 0
    title = (
        f"🐻 **Bear Trap leaderboard for {scope}** — {len(players)} players, "
        f"{total_events} saved events"
    )
    if limit:
        title += f" showing top {limit}"

    chunks = _leaderboard_table_chunks(players)
    await interaction.followup.send(f"{title}\n{chunks[0]}")
    for chunk in chunks[1:]:
        await interaction.followup.send(chunk)


@bear_player_group.command(
    name="search",
    description="Search a player's saved Bear Trap history"
)
@app_commands.describe(
    channel="Optional Bear channel to read from",
    all_channels="Search across all Bear channels"
)
async def bear_player(
    interaction: discord.Interaction,
    name: str,
    channel: discord.TextChannel = None,
    all_channels: bool = False
):
    await interaction.response.defer(thinking=True)
    channel_id = resolve_report_channel_id(interaction, channel, all_channels)
    scope = report_scope_label(interaction, channel, all_channels)
    players, history = await asyncio.to_thread(
        repository.fetch_player_history,
        channel_id,
        name
    )

    if not players:
        await interaction.followup.send(
            f"🐻 No saved player results match **{name}** for {scope}."
        )
        return

    lines = [f"🐻 **Player search: {name}**", f"Scope: **{scope}**"]

    if len(players) > 1:
        lines.append("**Matching players**")
        for player in players:
            lines.append(
                f"{player['player_name']} — {player['appearances']} events, "
                f"{player['average_damage']:,.0f} avg, "
                f"{player['best_damage']:,} best"
            )
        lines.append("")

    lines.append("**Recent results**")
    for result in history:
        date_label = result["event_date"] or "Unknown date"
        if result["event_time"]:
            date_label += f" {result['event_time']}"
        channel_prefix = ""
        if all_channels:
            channel_prefix = f"#{channel_label(result['discord_channel_name'])} — "
        uncertain = " ⚠️" if result["uncertain"] else ""
        lines.append(
            f"{channel_prefix}{date_label} — {result['player_name']} "
            f"#{result['rank']} — {result['damage']:,}{uncertain}"
        )

    await interaction.followup.send("\n".join(lines))



@bear_player_group.command(
    name="list",
    description="List canonical players stored by the tracker"
)
async def bear_player_list(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    players = await asyncio.to_thread(repository.fetch_players, 50)

    if not players:
        await interaction.followup.send(
            "🐻 No player identities have been saved yet.",
            ephemeral=True
        )
        return

    lines = [
        "🐻 **Canonical players**",
        "```text",
        "ID    Events  Player",
        "----  ------  ------------------------------",
    ]
    for player in players:
        name = player.get_canonical_name().replace("`", "ˋ")
        lines.append(
            f"{player.get_player_id():<4}  {player.get_event_count():<6}  {name}"
        )

    lines.append("```")
    if len(players) == 50:
        lines.append("Showing the first 50 players.")

    await interaction.followup.send("\n".join(lines), ephemeral=True)


@bear_player_group.command(
    name="rename",
    description="Set a player's canonical name while preserving old aliases"
)
async def bear_player_rename(
    interaction: discord.Interaction,
    old_name: str,
    new_name: str
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        player = await asyncio.to_thread(
            repository.rename_player,
            old_name,
            new_name
        )
    except ValueError as error:
        await interaction.followup.send(f"❌ {error}", ephemeral=True)
        return

    await interaction.followup.send(
        f"✅ Player ID **{player.get_player_id()}** is now named "
        f"**{player.get_canonical_name()}**. Historical results will "
        "follow this player identity.",
        ephemeral=True
    )


@bear_event_group.command(name="list", description="List saved events")
@app_commands.describe(
    channel="Optional Bear channel to read from",
    all_channels="List events from all Bear channels"
)
async def bear_event_list(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None,
    all_channels: bool = False
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    channel_id = resolve_report_channel_id(interaction, channel, all_channels)
    scope = report_scope_label(interaction, channel, all_channels)
    events = await asyncio.to_thread(repository.fetch_events, channel_id, 50)
    if not events:
        await interaction.followup.send(f"🐻 No saved events for {scope}.", ephemeral=True)
        return
    lines = [f"🐻 **Saved events for {scope}**", "```text"]
    if all_channels:
        lines.extend([
            "Channel             ID    Date / Time           Rallies  Damage",
            "------------------  ----  --------------------  -------  ----------------"
        ])
    else:
        lines.extend([
            "ID    Date / Time           Rallies  Damage",
            "----  --------------------  -------  ----------------"
        ])
    for event in events:
        timestamp = f"{event.get_event_date() or '-'} {event.get_event_time() or '-'}"
        rallies = event.get_rallies() if event.get_rallies() is not None else "-"
        damage = f"{event.get_alliance_damage():,}" if event.get_alliance_damage() is not None else "-"
        if all_channels:
            name = _table_text(channel_label(event.get_discord_channel_name()), 18)
            lines.append(f"{name:<18}  {event.get_event_id():<4}  {timestamp:<20}  {str(rallies):<7}  {damage}")
        else:
            lines.append(f"{event.get_event_id():<4}  {timestamp:<20}  {str(rallies):<7}  {damage}")
    lines.append("```")
    if len(events) == 50: lines.append("Showing the latest 50 events.")
    await interaction.followup.send("\n".join(lines), ephemeral=True)


@bear_event_group.command(name="details", description="Show details for one event ID")
@app_commands.describe(
    channel="Optional Bear channel to read from",
    all_channels="Allow looking up an event from any Bear channel"
)
async def bear_event_details(
    interaction: discord.Interaction,
    event_id: int,
    channel: discord.TextChannel = None,
    all_channels: bool = False
):
    await interaction.response.defer(thinking=True)
    channel_id = resolve_report_channel_id(interaction, channel, all_channels)
    event, results = await asyncio.to_thread(repository.fetch_event_details, event_id, channel_id)
    if event is None:
        await interaction.followup.send("❌ No event with that ID exists in that scope.", ephemeral=True)
        return
    lines = [f"🐻 **Event ID {event.get_event_id()}**", f"Channel: **#{channel_label(event.get_discord_channel_name())}**", f"Type: **{event.get_event_type()}**", f"Date: **{event.get_event_date()} {event.get_event_time()}**", f"Rallies: **{event.get_rallies() if event.get_rallies() is not None else 'Not found'}**", f"Alliance damage: **{event.get_alliance_damage():,}**" if event.get_alliance_damage() is not None else "Alliance damage: **Not found**", f"Participants: **{len(results)}**"]
    await interaction.followup.send("\n".join(lines))


@bear_event_group.command(name="delete", description="Delete a saved event after confirmation")
@app_commands.describe(
    channel="Optional Bear channel to read from",
    all_channels="Allow deleting an event from any Bear channel by event ID"
)
async def bear_event_delete(
    interaction: discord.Interaction,
    event_id: int,
    channel: discord.TextChannel = None,
    all_channels: bool = False
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    channel_id = resolve_report_channel_id(interaction, channel, all_channels)
    event, results = await asyncio.to_thread(repository.fetch_event_details, event_id, channel_id)
    if event is None:
        await interaction.followup.send("❌ No event with that ID exists in that scope.", ephemeral=True)
        return
    await interaction.followup.send(
        f"⚠️ Delete Event ID **{event_id}** from **#{channel_label(event.get_discord_channel_name())}** with **{len(results)}** player results? This cannot be undone.",
        ephemeral=True,
        view=EventDeleteView(event_id, channel_id, interaction.user.id)
    )


@bear_event_group.command(
    name="trend",
    description="Chart event rallies, participation, and damage over time"
)
@app_commands.describe(
    channel="Optional Bear channel to read from",
    all_channels="Chart events across all Bear channels"
)
async def bear_event_trend(
    interaction: discord.Interaction,
    months: int = 1,
    channel: discord.TextChannel = None,
    all_channels: bool = False
):
    if months not in (1, 3):
        await interaction.response.send_message(
            "❌ Choose either `months: 1` or `months: 3`.",
            ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)
    channel_id = resolve_report_channel_id(interaction, channel, all_channels)
    scope = report_scope_label(interaction, channel, all_channels)
    since_date = (
        datetime.now(timezone.utc).date() - timedelta(days=months * 30)
    ).isoformat()
    rows = await asyncio.to_thread(
        repository.fetch_event_trend,
        channel_id,
        since_date
    )
    if not rows:
        await interaction.followup.send(
            f"🐻 No saved events for {scope} in the last {months} month(s)."
        )
        return

    chart = await asyncio.to_thread(create_event_trend_chart, rows, months)
    await interaction.followup.send(
        f"🐻 **Event trends for {scope} — last {months} month(s)**",
        file=discord.File(chart, filename="bear-event-trend.png")
    )


@bear_player_group.command(
    name="trend",
    description="Chart a player's damage over the last one or three months"
)
@app_commands.describe(
    channel="Optional Bear channel to read from",
    all_channels="Chart player results across all Bear channels"
)
async def bear_player_trend(
    interaction: discord.Interaction,
    name: str,
    months: int = 1,
    channel: discord.TextChannel = None,
    all_channels: bool = False
):
    if months not in (1, 3):
        await interaction.response.send_message(
            "❌ Choose either `months: 1` or `months: 3`.",
            ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)
    channel_id = resolve_report_channel_id(interaction, channel, all_channels)
    scope = report_scope_label(interaction, channel, all_channels)
    since_date = (
        datetime.now(timezone.utc).date() - timedelta(days=months * 30)
    ).isoformat()
    rows = await asyncio.to_thread(
        repository.fetch_player_trend,
        channel_id,
        name,
        since_date
    )

    if not rows:
        await interaction.followup.send(
            f"🐻 No saved results for **{name}** in {scope} in the last {months} month(s)."
        )
        return

    chart = await asyncio.to_thread(
        create_player_trend_chart,
        rows,
        months,
        name
    )
    await interaction.followup.send(
        f"🐻 **{name} in {scope} — last {months} month(s)**",
        file=discord.File(chart, filename="bear-player-trend.png")
    )


repository.setup()

bot.run(DISCORD_TOKEN)
