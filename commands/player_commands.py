import asyncio

import discord
from discord import app_commands

from commands.support import (
    log_discord_request,
    prepare_report_scope,
    prepare_trend_since_date,
)
from services.discord_formatting import (
    code_table_chunks,
    guild_label,
    guild_scope_line,
    player_result_context,
    table_text,
)
from services.trend_chart_service import create_player_trend_chart
from views.command_forms import SelectField, TextField, command_form


def _player_stats_chunks(
    summary,
    history,
    scope,
    all_channels=False,
    all_servers=False,
    max_message_length=1900,
):
    summary_lines = [
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
            summary_lines.insert(2, guild_line)

    if all_servers:
        header = (
            f"{'Server':<19}  {'Channel':<16}  {'Event':>5}  "
            f"{'Date / Time':<19}  {'Type':<16}  {'Rank':>4}  "
            f"{'Damage':>15}  {'OCR':>3}"
        )
        separator = (
            f"{'-' * 19}  {'-' * 16}  {'-' * 5}  {'-' * 19}  "
            f"{'-' * 16}  {'-' * 4}  {'-' * 15}  {'-' * 3}"
        )
    elif all_channels:
        header = (
            f"{'Channel':<18}  {'Event':>5}  {'Date / Time':<19}  "
            f"{'Type':<16}  {'Rank':>4}  {'Damage':>15}  {'OCR':>3}"
        )
        separator = (
            f"{'-' * 18}  {'-' * 5}  {'-' * 19}  {'-' * 16}  "
            f"{'-' * 4}  {'-' * 15}  {'-' * 3}"
        )
    else:
        header = (
            f"{'Event':>5}  {'Date / Time':<19}  {'Type':<16}  "
            f"{'Rank':>4}  {'Damage':>15}  {'OCR':>3}"
        )
        separator = (
            f"{'-' * 5}  {'-' * 19}  {'-' * 16}  {'-' * 4}  "
            f"{'-' * 15}  {'-' * 3}"
        )

    rows = []
    for result in history:
        timestamp = result["event_date"] or "Unknown date"
        if result["event_time"]:
            timestamp += f" {result['event_time']}"
        event_type = table_text(result["event_type"], 16)
        ocr_flag = "!" if result["uncertain"] else ""
        row = (
            f"{result['event_id']:>5}  {timestamp:<19}  {event_type:<16}  "
            f"{'#' + str(result['rank']):>4}  {result['damage']:>15,}  "
            f"{ocr_flag:>3}"
        )
        if all_channels or all_servers:
            channel = table_text(
                result["discord_channel_name"] or "unknown-channel",
                16 if all_servers else 18,
            )
            row = f"{channel:<{16 if all_servers else 18}}  {row}"
        if all_servers:
            server = table_text(
                result["discord_guild_name"]
                or result["discord_guild_id"]
                or "unknown-server",
                19,
            )
            row = f"{server:<19}  {row}"
        rows.append(row)

    return code_table_chunks(
        header,
        separator,
        rows,
        title="\n".join(summary_lines),
        continued_title=f"🐻 **{summary['player_name']} event results (continued)**",
        max_length=max_message_length,
    )


def register_player_commands(group, repository, bot, bot_owner_ids, log_event):
    @group.command(
        name="search",
        description="Search a player's saved Bear Trap history",
    )
    @log_discord_request(log_event, "/bear player search")
    @command_form(
        "Search player history",
        fields=(
            TextField(
                name="name",
                label="Player name",
                placeholder="Name or saved alias",
                required=True,
            ),
        ),
        include_scope=True,
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
    @log_discord_request(log_event, "/bear player stats")
    @command_form(
        "Player statistics",
        fields=(
            TextField(
                name="playername",
                label="Player name",
                placeholder="Name or saved alias",
                required=True,
            ),
        ),
        include_scope=True,
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
    @log_discord_request(log_event, "/bear player list")
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
    @log_discord_request(log_event, "/bear player rename")
    @command_form(
        "Rename player",
        fields=(
            TextField(
                name="old_name",
                label="Current name or alias",
                required=True,
            ),
            TextField(
                name="new_name",
                label="New canonical name",
                required=True,
            ),
        ),
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
    @log_discord_request(log_event, "/bear player trend")
    @command_form(
        "Player damage trend",
        fields=(
            TextField(
                name="name",
                label="Player name",
                placeholder="Name or saved alias",
                required=True,
            ),
            SelectField(
                name="months",
                label="Time range",
                options=(
                    ("1 month", "1", True),
                    ("3 months", "3", False),
                ),
                parser=int,
            ),
        ),
        include_scope=True,
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
