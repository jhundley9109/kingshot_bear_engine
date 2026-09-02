import asyncio

import discord
from discord import app_commands

from commands.support import prepare_report_scope, prepare_trend_since_date
from services.discord_formatting import (
    code_table_chunks,
    guild_label,
    guild_scope_line,
    line_chunks,
    player_result_context,
    table_text,
)
from services.trend_chart_service import create_player_trend_chart


def _player_stats_chunks(
    summary,
    history,
    scope,
    all_channels=False,
    all_servers=False,
    max_message_length=1900,
):
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
        rows.append(
            f"Event **{result['event_id']}** — {context} — "
            f"{result['event_type']} — rank **#{result['rank']}** — "
            f"**{result['damage']:,}** damage{uncertain}"
        )
    return line_chunks(
        lines,
        rows,
        continued_lines=[
            f"🐻 **{summary['player_name']} event results (continued)**"
        ],
        max_length=max_message_length,
    )


def register_player_commands(group, repository, bot, bot_owner_ids):
    @group.command(
        name="search",
        description="Search a player's saved Bear Trap history",
    )
    @app_commands.describe(
        channel="Optional Bear channel to read from",
        all_channels="Search across this server",
        all_servers="Owner only: search every configured server",
    )
    async def search(
        interaction: discord.Interaction,
        name: str,
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
        players, history = await asyncio.to_thread(
            repository.fetch_player_history,
            scope.channel_id,
            scope.guild_id,
            name,
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
                        player["discord_guild_id"],
                    ) + " — "
                lines.append(
                    f"{server_prefix}{player['player_name']} — "
                    f"{player['appearances']} events, "
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

    @group.command(
        name="stats",
        description="Show a player's totals and stats for every participating event",
    )
    @app_commands.describe(
        playername="Player name or saved alias",
        channel="Optional Bear channel to read from",
        all_channels="Include events across this server",
        all_servers="Owner only: include every configured server",
    )
    async def stats(
        interaction: discord.Interaction,
        playername: str,
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
        summary, history = await asyncio.to_thread(
            repository.fetch_player_stats,
            scope.channel_id,
            scope.guild_id,
            playername,
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

    @group.command(
        name="list",
        description="List canonical players stored by the tracker",
    )
    @app_commands.describe(
        all_servers="Owner only: list players from every configured server"
    )
    async def list_players(
        interaction: discord.Interaction,
        all_servers: bool = False,
    ):
        scope = await prepare_report_scope(
            interaction, bot_owner_ids, all_servers=all_servers
        )
        if scope is None:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        players = await asyncio.to_thread(
            repository.fetch_players, scope.guild_id, 100
        )
        if not players:
            await interaction.followup.send(
                "🐻 No player identities have been saved yet.", ephemeral=True
            )
            return

        title = "🐻 **Canonical players"
        title += (
            " across all configured servers" if all_servers else " in this server"
        )
        title += "**"
        if all_servers:
            header = "Guild ID             Server            ID    Events  Player"
            separator = (
                "-------------------  ----------------  ----  ------  "
                "------------------------"
            )
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
                row = (
                    f"{player.get_guild_id():<19}  {server:<16}  "
                    f"{player.get_player_id():<4}  "
                    f"{player.get_event_count():<6}  {name}"
                )
            else:
                row = (
                    f"{player.get_player_id():<4}  "
                    f"{player.get_event_count():<6}  {name}"
                )
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

    @group.command(
        name="rename",
        description="Set a player's canonical name while preserving old aliases",
    )
    async def rename(
        interaction: discord.Interaction,
        old_name: str,
        new_name: str,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            player = await asyncio.to_thread(
                repository.rename_player,
                old_name,
                new_name,
                interaction.guild_id,
            )
        except ValueError as error:
            await interaction.followup.send(f"❌ {error}", ephemeral=True)
            return

        await interaction.followup.send(
            f"✅ Player ID **{player.get_player_id()}** is now named "
            f"**{player.get_canonical_name()}**. Historical results will "
            "follow this player identity.",
            ephemeral=True,
        )

    @group.command(
        name="trend",
        description="Chart a player's damage over the last one or three months",
    )
    @app_commands.describe(
        channel="Optional Bear channel to read from",
        all_channels="Chart player results across this server",
        all_servers="Owner only: chart across every configured server",
    )
    async def trend(
        interaction: discord.Interaction,
        name: str,
        months: int = 1,
        channel: discord.TextChannel = None,
        all_channels: bool = False,
        all_servers: bool = False,
    ):
        scope = await prepare_report_scope(
            interaction, bot_owner_ids, channel, all_channels, all_servers
        )
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
            since_date,
        )
        if not rows:
            await interaction.followup.send(
                f"🐻 No saved results for **{name}** in {scope.label} "
                f"in the last {months} month(s)."
            )
            return

        chart = await asyncio.to_thread(
            create_player_trend_chart, rows, months, name
        )
        message = f"🐻 **{name} in {scope.label} — last {months} month(s)**"
        guild_line = guild_scope_line(rows) if all_servers else None
        if guild_line:
            message += f"\n{guild_line}"
        await interaction.followup.send(
            message,
            file=discord.File(chart, filename="bear-player-trend.png"),
        )
