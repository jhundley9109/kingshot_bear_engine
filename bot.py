import os
import json
import asyncio
import discord
from datetime import datetime, timedelta, timezone

from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI

from data_access import BearTrapRepository
from services.trend_chart_service import create_player_trend_chart


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
repository = BearTrapRepository(DB_PATH)

@bear_group.command(name="status", description="Check the Bear Trap tracker")
async def bear_status(interaction: discord.Interaction):
    await interaction.response.send_message("🐻 Bear Trap tracker is alive!")


@bear_group.command(
    name="summary",
    description="Show the most recently saved Bear Trap report"
)
async def bear_summary(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    event, players = await asyncio.to_thread(
        repository.fetch_latest_summary,
        interaction.channel_id
    )

    if event is None:
        await interaction.followup.send(
            "🐻 No approved Bear Trap reports have been saved yet."
        )
        return

    leaders = players[:5]

    lines = [
        f"🐻 **{event.get_event_type()} summary**",
        f"Event ID: **{event.get_event_id()}**",
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


@bear_group.command(
    name="leaderboard",
    description="Rank players by total saved Bear Trap damage"
)
async def bear_leaderboard(
    interaction: discord.Interaction,
    limit: int = 10
):
    limit = max(1, min(limit, 25))
    await interaction.response.defer(thinking=True)
    players = await asyncio.to_thread(
        repository.fetch_leaderboard,
        interaction.channel_id,
        limit
    )

    if not players:
        await interaction.followup.send(
            "🐻 No approved Bear Trap reports have been saved yet."
        )
        return

    lines = ["🐻 **Bear Trap leaderboard**"]
    for position, player in enumerate(players, start=1):
        lines.append(
            f"**{position}.** {player['player_name']} — "
            f"{player['total_damage']:,} total "
            f"({player['appearances']} events, "
            f"{player['average_damage']:,.0f} avg)"
        )

    await interaction.followup.send("\n".join(lines))


@bear_player_group.command(
    name="search",
    description="Search a player's saved Bear Trap history"
)
async def bear_player(
    interaction: discord.Interaction,
    name: str
):
    await interaction.response.defer(thinking=True)
    players, history = await asyncio.to_thread(
        repository.fetch_player_history,
        interaction.channel_id,
        name
    )

    if not players:
        await interaction.followup.send(
            f"🐻 No saved player results match **{name}**."
        )
        return

    lines = [f"🐻 **Player search: {name}**"]

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
        uncertain = " ⚠️" if result["uncertain"] else ""
        lines.append(
            f"{date_label} — {result['player_name']} "
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
        "ID    Player",
        "----  ------------------------------",
    ]
    for player in players:
        name = player.get_canonical_name().replace("`", "ˋ")
        lines.append(f"{player.get_player_id():<4}  {name}")

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


@bear_player_group.command(
    name="trend",
    description="Chart a player's damage over the last one or three months"
)
async def bear_player_trend(
    interaction: discord.Interaction,
    name: str,
    months: int = 1
):
    if months not in (1, 3):
        await interaction.response.send_message(
            "❌ Choose either `months: 1` or `months: 3`.",
            ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)
    since_date = (
        datetime.now(timezone.utc).date() - timedelta(days=months * 30)
    ).isoformat()
    rows = await asyncio.to_thread(
        repository.fetch_player_trend,
        interaction.channel_id,
        name,
        since_date
    )

    if not rows:
        await interaction.followup.send(
            f"🐻 No saved results for **{name}** in the last {months} month(s)."
        )
        return

    chart = await asyncio.to_thread(
        create_player_trend_chart,
        rows,
        months
    )
    await interaction.followup.send(
        f"🐻 **{name} — last {months} month(s)**",
        file=discord.File(chart, filename="bear-player-trend.png")
    )


repository.setup()

bot.run(DISCORD_TOKEN)
