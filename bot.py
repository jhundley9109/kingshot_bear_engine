import os
import asyncio
import discord
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI

from data_access import BearTrapRepository
from services.discord_formatting import (
    channel_label,
    code_table_chunks,
    damage_text,
    discord_text_chunks,
    guild_label,
    guild_scope_line,
    line_chunks,
    player_result_context,
    table_name_cell,
    table_text,
)
from services.extraction_review_service import (
    build_extraction_preview,
    extract_bear_data,
    find_image_attachments,
    merge_players,
)
from services.recap_service import (
    RECAP_MODEL,
    build_recap_data,
    generate_bear_recap,
    recap_cache_key,
)
from services.trend_chart_service import create_event_trend_chart, create_player_trend_chart
from views.review_views import BearTrapReviewView, EventDeleteView


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
guild_ids_value = os.getenv("GUILD_IDS") or os.getenv("GUILD_ID", "")
GUILD_IDS = [int(value.strip()) for value in guild_ids_value.split(",") if value.strip()]
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


# OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)


# --------------------------------------------------
# DISCORD BOT SETUP
# --------------------------------------------------

intents = discord.Intents.default()


class BearBot(commands.Bot):

    async def setup_hook(self):
        for guild_id in GUILD_IDS:
            await self.tree.sync(guild=discord.Object(id=guild_id))


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

CONFIGURED_GUILDS = [discord.Object(id=guild_id) for guild_id in GUILD_IDS]
bot.tree.add_command(bear_group, guilds=CONFIGURED_GUILDS)

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
# PROCESS BEAR TRAP MESSAGE
# --------------------------------------------------

@app_commands.context_menu(name="Process Bear Trap")
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

    images = find_image_attachments(message.attachments)

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
            client,
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

        result = build_extraction_preview(
            data,
            merged_players,
            conflicts,
            len(images),
            existing_event_id
        )


        review_view = None

        if not conflicts:
            review_view = BearTrapReviewView(
                repository,
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


bot.tree.add_command(process_bear_trap, guilds=CONFIGURED_GUILDS)


DB_PATH = "data/beartrap.db"
repository = BearTrapRepository(DB_PATH)


@dataclass(frozen=True)
class ReportScope:
    channel_id: object
    guild_id: object
    label: str
    all_channels: bool
    all_servers: bool


async def prepare_report_scope(
    interaction, channel=None, all_channels=False, all_servers=False
):
    selected_count = sum((channel is not None, all_channels, all_servers))
    if selected_count > 1:
        await interaction.response.send_message(
            "❌ Choose only one of `channel`, `all_channels`, or `all_servers`.",
            ephemeral=True
        )
        return None
    if all_servers and interaction.user.id not in BOT_OWNER_IDS:
        await interaction.response.send_message(
            "❌ `all_servers` is restricted to configured bot owners.",
            ephemeral=True
        )
        return None

    if all_servers:
        channel_id = guild_id = None
        label = "all configured Discord servers"
    elif all_channels:
        channel_id = None
        guild_id = interaction.guild_id
        guild_name = getattr(interaction.guild, "name", "this server")
        label = f"all Bear channels in {guild_name}"
    else:
        selected_channel = channel or interaction.channel
        channel_id = selected_channel.id
        guild_id = interaction.guild_id
        channel_name = getattr(selected_channel, "name", None)
        label = f"#{channel_name}" if channel_name else "this channel"

    return ReportScope(
        channel_id=channel_id,
        guild_id=guild_id,
        label=label,
        all_channels=all_channels,
        all_servers=all_servers,
    )


async def prepare_trend_since_date(interaction, months):
    if months not in (1, 3):
        await interaction.response.send_message(
            "❌ Choose either `months: 1` or `months: 3`.",
            ephemeral=True
        )
        return None
    return (
        datetime.now(timezone.utc).date() - timedelta(days=months * 30)
    ).isoformat()


@bear_group.command(name="status", description="Check the Bear Trap tracker")
async def bear_status(interaction: discord.Interaction):
    await interaction.response.send_message("🐻 Bear Trap tracker is alive!")


@bear_group.command(
    name="summary",
    description="Show the most recently saved Bear Trap report"
)
@app_commands.describe(
    channel="Optional Bear channel to read from",
    all_channels="Show the latest report across this server",
    all_servers="Owner only: include every configured server"
)
async def bear_summary(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None,
    all_channels: bool = False,
    all_servers: bool = False
):
    scope = await prepare_report_scope(interaction, channel, all_channels, all_servers)
    if scope is None:
        return
    await interaction.response.defer(thinking=True)
    event, players = await asyncio.to_thread(
        repository.fetch_latest_summary,
        scope.channel_id,
        scope.guild_id
    )

    if event is None:
        await interaction.followup.send(
            f"🐻 No approved Bear Trap reports have been saved for {scope.label} yet."
        )
        return

    leaders = players[:5]

    lines = [
        f"🐻 **{event.get_event_type()} summary**",
        f"Event ID: **{event.get_event_id()}**",
        f"Server: **{guild_label(event.get_discord_guild_name(), event.get_discord_guild_id())}**",
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


def _leaderboard_table_chunks(players, all_servers=False,
                              max_message_length=1900):
    guild_header = f"{'Guild ID':>19}  " if all_servers else ""
    guild_separator = f"{'-' * 19}  " if all_servers else ""
    header = guild_header + (
        f"{'#':>3}  {'Player':>20}  {'Events':>6}  "
        f"{'Total Damage':>16}  {'Avg/Event':>14}  {'Best':>16}"
    )
    separator = guild_separator + (
        f"{'-' * 3}  {'-' * 20}  {'-' * 6}  "
        f"{'-' * 16}  {'-' * 14}  {'-' * 16}"
    )
    rows = []
    for position, player in enumerate(players, start=1):
        rows.append(
            (f"{player['discord_guild_id']:>19}  " if all_servers else "") +
            f"{position:>3}  "
            f"{table_name_cell(player['player_name'], 20)}  "
            f"{player['appearances']:>6}  "
            f"{damage_text(player['total_damage']):>16}  "
            f"{damage_text(player['average_damage']):>14}  "
            f"{damage_text(player['best_damage']):>16}"
        )
    return code_table_chunks(
        header, separator, rows, max_length=max_message_length
    )


@bear_group.command(
    name="leaderboard",
    description="Rank players by total saved Bear Trap damage"
)
@app_commands.describe(
    limit="Maximum players to show. Use 0 or leave blank for all players.",
    channel="Optional Bear channel to read from",
    all_channels="Rank players across this server",
    all_servers="Owner only: rank across every configured server"
)
async def bear_leaderboard(
    interaction: discord.Interaction,
    limit: int = 0,
    channel: discord.TextChannel = None,
    all_channels: bool = False,
    all_servers: bool = False
):
    scope = await prepare_report_scope(interaction, channel, all_channels, all_servers)
    if scope is None:
        return
    limit = max(0, min(limit, 100))
    row_limit = limit or None
    await interaction.response.defer(thinking=True)
    players = await asyncio.to_thread(
        repository.fetch_leaderboard,
        scope.channel_id,
        scope.guild_id,
        row_limit
    )

    if not players:
        await interaction.followup.send(
            f"🐻 No approved Bear Trap reports have been saved for {scope.label} yet."
        )
        return

    total_events = players[0]["total_events"] or 0
    title = (
        f"🐻 **Bear Trap leaderboard for {scope.label}** — {len(players)} players, "
        f"{total_events} saved events"
    )
    if limit:
        title += f" showing top {limit}"

    if all_servers:
        guild_line = guild_scope_line(players)
        if guild_line:
            title += f"\n{guild_line}"
    chunks = _leaderboard_table_chunks(players, all_servers)
    await interaction.followup.send(f"{title}\n{chunks[0]}")
    for chunk in chunks[1:]:
        await interaction.followup.send(chunk)


@bear_group.command(
    name="recap",
    description="Generate a funny recap from the latest Bear Trap events"
)
@app_commands.describe(
    events="Number of recent events to recap (2-10)",
    channel="Optional Bear channel to read from",
    all_channels="Include recent events across this server",
    all_servers="Owner only: include every configured server"
)
async def bear_recap(
    interaction: discord.Interaction,
    events: int = 5,
    channel: discord.TextChannel = None,
    all_channels: bool = False,
    all_servers: bool = False
):
    scope = await prepare_report_scope(interaction, channel, all_channels, all_servers)
    if scope is None:
        return
    await interaction.response.defer(thinking=True)
    event_count = max(2, min(events, 10))
    source_events, results = await asyncio.to_thread(
        repository.fetch_recap_source,
        scope.channel_id,
        scope.guild_id,
        event_count
    )
    if len(source_events) < 2:
        await interaction.followup.send(
            f"🐻 At least two saved events are needed to recap {scope.label}."
        )
        return

    recap_data = build_recap_data(source_events, results)
    cache_key = recap_cache_key(recap_data)
    cached = await asyncio.to_thread(repository.fetch_cached_recap, cache_key)
    if cached is None:
        try:
            recap_text = await asyncio.to_thread(
                generate_bear_recap, client, recap_data
            )
        except Exception as error:
            log_event(f"Bear recap generation failed: {error}")
            await interaction.followup.send(
                "❌ I couldn't generate the Bear recap. Check the bot logs "
                "and OpenAI API balance, then try again."
            )
            return
        if not recap_text:
            await interaction.followup.send("❌ OpenAI returned an empty recap.")
            return
        await asyncio.to_thread(
            repository.save_cached_recap,
            cache_key,
            RECAP_MODEL,
            len(source_events),
            recap_text
        )
        cache_label = "newly generated"
    else:
        recap_text = cached["recap_text"]
        cache_label = "cached"

    heading = (
        f"🐻 **Bear Trap recap for {scope.label}** — latest "
        f"{len(source_events)} events ({cache_label})"
    )
    chunks = discord_text_chunks(recap_text)
    if all_servers:
        guild_line = guild_scope_line(source_events)
        await interaction.followup.send(
            f"{heading}\n{guild_line}" if guild_line else heading
        )
        start_at = 0
    else:
        await interaction.followup.send(f"{heading}\n\n{chunks[0]}")
        start_at = 1
    for chunk in chunks[start_at:]:
        await interaction.followup.send(chunk)


@bear_player_group.command(
    name="search",
    description="Search a player's saved Bear Trap history"
)
@app_commands.describe(
    channel="Optional Bear channel to read from",
    all_channels="Search across this server",
    all_servers="Owner only: search every configured server"
)
async def bear_player(
    interaction: discord.Interaction,
    name: str,
    channel: discord.TextChannel = None,
    all_channels: bool = False,
    all_servers: bool = False
):
    scope = await prepare_report_scope(interaction, channel, all_channels, all_servers)
    if scope is None:
        return
    await interaction.response.defer(thinking=True)
    players, history = await asyncio.to_thread(
        repository.fetch_player_history,
        scope.channel_id,
        scope.guild_id,
        name
    )

    if not players:
        await interaction.followup.send(
            f"🐻 No saved player results match **{name}** for {scope.label}."
        )
        return

    lines = [f"🐻 **Player search: {name}**", f"Scope: **{scope.label}**"]

    if len(players) > 1:
        lines.append("**Matching players**")
        for player in players:
            server_prefix = ""
            if all_servers:
                server_prefix = guild_label(
                    player["discord_guild_name"],
                    player["discord_guild_id"]
                ) + " — "
            lines.append(
                f"{server_prefix}{player['player_name']} — {player['appearances']} events, "
                f"{player['average_damage']:,.0f} avg, "
                f"{player['best_damage']:,} best"
            )
        lines.append("")

    lines.append("**Recent results**")
    for result in history:
        context, uncertain = player_result_context(
            result, all_channels, all_servers
        )
        lines.append(
            f"{context} — {result['player_name']} "
            f"#{result['rank']} — {result['damage']:,}{uncertain}"
        )

    await interaction.followup.send("\n".join(lines))


def _player_stats_chunks(summary, history, scope, all_channels=False,
                         all_servers=False,
                         max_message_length=1900):
    lines = [
        f"🐻 **Player stats: {summary['player_name']}**",
        f"Scope: **{scope}**",
        f"Events: **{summary['appearances']:,}**",
        f"Total damage: **{summary['total_damage']:,}**",
        f"Average damage/event: **{summary['average_damage']:,.0f}**",
        f"Best damage: **{summary['best_damage']:,}**",
        f"Best rank: **#{summary['best_rank']}**",
        "",
        "**Event results**",
    ]
    if all_servers:
        guild_line = guild_scope_line(history)
        if guild_line:
            lines.insert(2, guild_line)
    rows = []
    for result in history:
        context, uncertain = player_result_context(
            result, all_channels, all_servers
        )
        row = (
            f"Event **{result['event_id']}** — {context} — "
            f"{result['event_type']} — rank **#{result['rank']}** — "
            f"**{result['damage']:,}** damage{uncertain}"
        )
        rows.append(row)
    return line_chunks(
        lines,
        rows,
        continued_lines=[
            f"🐻 **{summary['player_name']} event results (continued)**"
        ],
        max_length=max_message_length,
    )


@bear_player_group.command(
    name="stats",
    description="Show a player's totals and stats for every participating event"
)
@app_commands.describe(
    playername="Player name or saved alias",
    channel="Optional Bear channel to read from",
    all_channels="Include events across this server",
    all_servers="Owner only: include every configured server"
)
async def bear_player_stats(
    interaction: discord.Interaction,
    playername: str,
    channel: discord.TextChannel = None,
    all_channels: bool = False,
    all_servers: bool = False
):
    scope = await prepare_report_scope(interaction, channel, all_channels, all_servers)
    if scope is None:
        return
    await interaction.response.defer(thinking=True)
    summary, history = await asyncio.to_thread(
        repository.fetch_player_stats,
        scope.channel_id,
        scope.guild_id,
        playername
    )

    if summary is None:
        await interaction.followup.send(
            f"🐻 No saved player results match **{playername}** for {scope.label}."
        )
        return

    chunks = _player_stats_chunks(
        summary, history, scope.label, all_channels, all_servers
    )
    for chunk in chunks:
        await interaction.followup.send(chunk)



@bear_player_group.command(
    name="list",
    description="List canonical players stored by the tracker"
)
@app_commands.describe(
    all_servers="Owner only: list players from every configured server"
)
async def bear_player_list(
    interaction: discord.Interaction,
    all_servers: bool = False
):
    scope = await prepare_report_scope(interaction, all_servers=all_servers)
    if scope is None:
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    players = await asyncio.to_thread(repository.fetch_players, scope.guild_id, 100)

    if not players:
        await interaction.followup.send(
            "🐻 No player identities have been saved yet.",
            ephemeral=True
        )
        return

    title = "🐻 **Canonical players"
    title += " across all configured servers" if all_servers else " in this server"
    title += "**"
    if all_servers:
        header = "Guild ID             Server            ID    Events  Player"
        separator = "-------------------  ----------------  ----  ------  ------------------------"
    else:
        header = "ID    Events  Player"
        separator = "----  ------  ------------------------------"
    rows = []
    for player in players:
        name = player.get_canonical_name().replace("`", "ˋ")
        if all_servers:
            guild = bot.get_guild(int(player.get_guild_id()))
            server = table_text(
                getattr(guild, "name", None) or player.get_guild_id(), 16
            )
            row = f"{player.get_guild_id():<19}  {server:<16}  {player.get_player_id():<4}  {player.get_event_count():<6}  {name}"
        else:
            row = f"{player.get_player_id():<4}  {player.get_event_count():<6}  {name}"
        rows.append(row)
    chunks = code_table_chunks(
        header,
        separator,
        rows,
        title=title,
        continued_title="🐻 **Canonical players (continued)**",
    )
    if len(players) == 100:
        chunks[-1] += "\nShowing the first 100 players."
    for chunk in chunks:
        await interaction.followup.send(chunk, ephemeral=True)


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
            new_name,
            interaction.guild_id
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
    all_channels="List events from this server",
    all_servers="Owner only: list events from every configured server"
)
async def bear_event_list(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None,
    all_channels: bool = False,
    all_servers: bool = False
):
    scope = await prepare_report_scope(interaction, channel, all_channels, all_servers)
    if scope is None:
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    events = await asyncio.to_thread(
        repository.fetch_events, scope.channel_id, scope.guild_id, 50
    )
    if not events:
        await interaction.followup.send(
            f"🐻 No saved events for {scope.label}.", ephemeral=True
        )
        return
    title = f"🐻 **Saved events for {scope.label}**"
    if all_servers:
        header = "Guild ID             Server         Channel       Event  Date / Time           Damage"
        separator = "-------------------  -------------  ------------  -----  --------------------  ----------------"
    elif all_channels:
        header = "Channel             ID    Date / Time           Rallies  Damage"
        separator = "------------------  ----  --------------------  -------  ----------------"
    else:
        header = "ID    Date / Time           Rallies  Damage"
        separator = "----  --------------------  -------  ----------------"
    rows = []
    for event in events:
        timestamp = f"{event.get_event_date() or '-'} {event.get_event_time() or '-'}"
        rallies = event.get_rallies() if event.get_rallies() is not None else "-"
        damage = f"{event.get_alliance_damage():,}" if event.get_alliance_damage() is not None else "-"
        if all_servers:
            server = table_text(
                event.get_discord_guild_name()
                or event.get_discord_guild_id()
                or "unknown",
                13,
            )
            name = table_text(channel_label(event.get_discord_channel_name()), 12)
            rows.append(f"{event.get_discord_guild_id():<19}  {server:<13}  {name:<12}  {event.get_event_id():<5}  {timestamp:<20}  {damage}")
        elif all_channels:
            name = table_text(channel_label(event.get_discord_channel_name()), 18)
            rows.append(f"{name:<18}  {event.get_event_id():<4}  {timestamp:<20}  {str(rallies):<7}  {damage}")
        else:
            rows.append(f"{event.get_event_id():<4}  {timestamp:<20}  {str(rallies):<7}  {damage}")
    chunks = code_table_chunks(header, separator, rows, title=title)
    if len(events) == 50: chunks[-1] += "\nShowing the latest 50 events."
    for chunk in chunks:
        await interaction.followup.send(chunk, ephemeral=True)


@bear_event_group.command(name="details", description="Show details for one event ID")
@app_commands.describe(
    channel="Optional Bear channel to read from",
    all_channels="Allow lookup across this server",
    all_servers="Owner only: allow lookup across every server"
)
async def bear_event_details(
    interaction: discord.Interaction,
    event_id: int,
    channel: discord.TextChannel = None,
    all_channels: bool = False,
    all_servers: bool = False
):
    scope = await prepare_report_scope(interaction, channel, all_channels, all_servers)
    if scope is None:
        return
    await interaction.response.defer(thinking=True)
    event, results = await asyncio.to_thread(
        repository.fetch_event_details, event_id, scope.channel_id, scope.guild_id
    )
    if event is None:
        await interaction.followup.send("❌ No event with that ID exists in that scope.", ephemeral=True)
        return
    lines = [f"🐻 **Event ID {event.get_event_id()}**", f"Server: **{guild_label(event.get_discord_guild_name(), event.get_discord_guild_id())}**", f"Channel: **#{channel_label(event.get_discord_channel_name())}**", f"Type: **{event.get_event_type()}**", f"Date: **{event.get_event_date()} {event.get_event_time()}**", f"Rallies: **{event.get_rallies() if event.get_rallies() is not None else 'Not found'}**", f"Alliance damage: **{event.get_alliance_damage():,}**" if event.get_alliance_damage() is not None else "Alliance damage: **Not found**", f"Participants: **{len(results)}**"]
    await interaction.followup.send("\n".join(lines))


@bear_event_group.command(name="delete", description="Delete a saved event after confirmation")
@app_commands.describe(
    channel="Optional Bear channel to read from",
    all_channels="Allow deletion lookup across this server",
    all_servers="Owner only: allow deletion lookup across every server"
)
async def bear_event_delete(
    interaction: discord.Interaction,
    event_id: int,
    channel: discord.TextChannel = None,
    all_channels: bool = False,
    all_servers: bool = False
):
    scope = await prepare_report_scope(interaction, channel, all_channels, all_servers)
    if scope is None:
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    event, results = await asyncio.to_thread(
        repository.fetch_event_details, event_id, scope.channel_id, scope.guild_id
    )
    if event is None:
        await interaction.followup.send("❌ No event with that ID exists in that scope.", ephemeral=True)
        return
    await interaction.followup.send(
        f"⚠️ Delete Event ID **{event_id}** from **{guild_label(event.get_discord_guild_name(), event.get_discord_guild_id())} / #{channel_label(event.get_discord_channel_name())}** with **{len(results)}** player results? This cannot be undone.",
        ephemeral=True,
        view=EventDeleteView(
            repository,
            event_id,
            scope.channel_id,
            scope.guild_id,
            interaction.user.id,
        )
    )


@bear_event_group.command(
    name="trend",
    description="Chart event rallies, participation, and damage over time"
)
@app_commands.describe(
    channel="Optional Bear channel to read from",
    all_channels="Chart events across this server",
    all_servers="Owner only: chart across every configured server"
)
async def bear_event_trend(
    interaction: discord.Interaction,
    months: int = 1,
    channel: discord.TextChannel = None,
    all_channels: bool = False,
    all_servers: bool = False
):
    scope = await prepare_report_scope(interaction, channel, all_channels, all_servers)
    if scope is None:
        return
    since_date = await prepare_trend_since_date(interaction, months)
    if since_date is None:
        return

    await interaction.response.defer(thinking=True)
    rows = await asyncio.to_thread(
        repository.fetch_event_trend,
        scope.channel_id,
        scope.guild_id,
        since_date
    )
    if not rows:
        await interaction.followup.send(
            f"🐻 No saved events for {scope.label} in the last {months} month(s)."
        )
        return

    chart = await asyncio.to_thread(create_event_trend_chart, rows, months)
    message = f"🐻 **Event trends for {scope.label} — last {months} month(s)**"
    guild_line = guild_scope_line(rows) if all_servers else None
    if guild_line:
        message += f"\n{guild_line}"
    await interaction.followup.send(
        message,
        file=discord.File(chart, filename="bear-event-trend.png")
    )


@bear_player_group.command(
    name="trend",
    description="Chart a player's damage over the last one or three months"
)
@app_commands.describe(
    channel="Optional Bear channel to read from",
    all_channels="Chart player results across this server",
    all_servers="Owner only: chart across every configured server"
)
async def bear_player_trend(
    interaction: discord.Interaction,
    name: str,
    months: int = 1,
    channel: discord.TextChannel = None,
    all_channels: bool = False,
    all_servers: bool = False
):
    scope = await prepare_report_scope(interaction, channel, all_channels, all_servers)
    if scope is None:
        return
    since_date = await prepare_trend_since_date(interaction, months)
    if since_date is None:
        return

    await interaction.response.defer(thinking=True)
    rows = await asyncio.to_thread(
        repository.fetch_player_trend,
        scope.channel_id,
        scope.guild_id,
        name,
        since_date
    )

    if not rows:
        await interaction.followup.send(
            f"🐻 No saved results for **{name}** in {scope.label} "
            f"in the last {months} month(s)."
        )
        return

    chart = await asyncio.to_thread(
        create_player_trend_chart,
        rows,
        months,
        name
    )
    message = f"🐻 **{name} in {scope.label} — last {months} month(s)**"
    guild_line = guild_scope_line(rows) if all_servers else None
    if guild_line:
        message += f"\n{guild_line}"
    await interaction.followup.send(
        message,
        file=discord.File(chart, filename="bear-player-trend.png")
    )


def main():
    repository.setup(GUILD_IDS[0])
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
