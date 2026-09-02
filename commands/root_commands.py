import asyncio

import discord
from discord import app_commands

from commands.support import prepare_report_scope
from services.discord_formatting import (
    channel_label,
    code_table_chunks,
    damage_text,
    discord_text_chunks,
    guild_label,
    guild_scope_line,
    table_name_cell,
)
from services.recap_service import (
    RECAP_MODEL,
    build_recap_data,
    generate_bear_recap,
    recap_cache_key,
)


def _leaderboard_table_chunks(
    players, all_servers=False, max_message_length=1900
):
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
            (f"{player['discord_guild_id']:>19}  " if all_servers else "")
            + f"{position:>3}  "
            f"{table_name_cell(player['player_name'], 20)}  "
            f"{player['appearances']:>6}  "
            f"{damage_text(player['total_damage']):>16}  "
            f"{damage_text(player['average_damage']):>14}  "
            f"{damage_text(player['best_damage']):>16}"
        )
    return code_table_chunks(
        header, separator, rows, max_length=max_message_length
    )


def register_root_commands(
    group, repository, openai_client, bot_owner_ids, log_event
):
    @group.command(name="status", description="Check the Bear Trap tracker")
    async def status(interaction: discord.Interaction):
        await interaction.response.send_message("🐻 Bear Trap tracker is alive!")

    @group.command(
        name="summary",
        description="Show the most recently saved Bear Trap report",
    )
    @app_commands.describe(
        channel="Optional Bear channel to read from",
        all_channels="Show the latest report across this server",
        all_servers="Owner only: include every configured server",
    )
    async def summary(
        interaction: discord.Interaction,
        channel: discord.TextChannel = None,
        all_channels: bool = False,
        all_servers: bool = False,
    ):
        scope = await prepare_report_scope(
            interaction, bot_owner_ids, channel, all_channels, all_servers
        )
        if scope is None:
            return
        await interaction.response.defer(thinking=True)
        event, players = await asyncio.to_thread(
            repository.fetch_latest_summary,
            scope.channel_id,
            scope.guild_id,
        )
        if event is None:
            await interaction.followup.send(
                f"🐻 No approved Bear Trap reports have been saved for "
                f"{scope.label} yet."
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
            lines.extend(["", "**Top 5**"])
            for player in leaders:
                uncertain = " ⚠️" if player.get_uncertain() else ""
                lines.append(
                    f"{player.get_rank()}. {player.get_raw_player_name()} — "
                    f"{player.get_damage():,}{uncertain}"
                )
        await interaction.followup.send("\n".join(lines))

    @group.command(
        name="leaderboard",
        description="Rank players by total saved Bear Trap damage",
    )
    @app_commands.describe(
        limit="Maximum players to show. Use 0 or leave blank for all players.",
        channel="Optional Bear channel to read from",
        all_channels="Rank players across this server",
        all_servers="Owner only: rank across every configured server",
    )
    async def leaderboard(
        interaction: discord.Interaction,
        limit: int = 0,
        channel: discord.TextChannel = None,
        all_channels: bool = False,
        all_servers: bool = False,
    ):
        scope = await prepare_report_scope(
            interaction, bot_owner_ids, channel, all_channels, all_servers
        )
        if scope is None:
            return
        limit = max(0, min(limit, 100))
        row_limit = limit or None
        await interaction.response.defer(thinking=True)
        players = await asyncio.to_thread(
            repository.fetch_leaderboard,
            scope.channel_id,
            scope.guild_id,
            row_limit,
        )
        if not players:
            await interaction.followup.send(
                f"🐻 No approved Bear Trap reports have been saved for "
                f"{scope.label} yet."
            )
            return

        total_events = players[0]["total_events"] or 0
        title = (
            f"🐻 **Bear Trap leaderboard for {scope.label}** — "
            f"{len(players)} players, {total_events} saved events"
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

    @group.command(
        name="recap",
        description="Generate a funny recap from the latest Bear Trap events",
    )
    @app_commands.describe(
        events="Number of recent events to recap (2-10)",
        channel="Optional Bear channel to read from",
        all_channels="Include recent events across this server",
        all_servers="Owner only: include every configured server",
    )
    async def recap(
        interaction: discord.Interaction,
        events: int = 5,
        channel: discord.TextChannel = None,
        all_channels: bool = False,
        all_servers: bool = False,
    ):
        scope = await prepare_report_scope(
            interaction, bot_owner_ids, channel, all_channels, all_servers
        )
        if scope is None:
            return
        await interaction.response.defer(thinking=True)
        event_count = max(2, min(events, 10))
        source_events, results = await asyncio.to_thread(
            repository.fetch_recap_source,
            scope.channel_id,
            scope.guild_id,
            event_count,
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
                    generate_bear_recap, openai_client, recap_data
                )
            except Exception as error:
                log_event(f"Bear recap generation failed: {error}")
                await interaction.followup.send(
                    "❌ I couldn't generate the Bear recap. Check the bot logs "
                    "and OpenAI API balance, then try again."
                )
                return
            if not recap_text:
                await interaction.followup.send(
                    "❌ OpenAI returned an empty recap."
                )
                return
            await asyncio.to_thread(
                repository.save_cached_recap,
                cache_key,
                RECAP_MODEL,
                len(source_events),
                recap_text,
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
