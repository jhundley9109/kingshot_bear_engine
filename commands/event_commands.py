import asyncio

import discord
from discord import app_commands

from commands.support import (
    log_discord_request,
    prepare_report_scope,
    prepare_trend_since_date,
)
from services.discord_formatting import (
    channel_label,
    code_table_chunks,
    guild_label,
    guild_scope_line,
    table_text,
)
from services.trend_chart_service import create_event_trend_chart
from views.review_views import EventDeleteView


def register_event_commands(group, repository, bot_owner_ids, log_event):
    @group.command(name="list", description="List saved events")
    @app_commands.describe(
        channel="Optional Bear channel to read from",
        all_channels="List events from this server",
        all_servers="Owner only: list events from every configured server",
    )
    @log_discord_request(log_event, "/bear event list")
    async def list_events(
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
            header = (
                "Guild ID             Server         Channel       Event  "
                "Date / Time           Damage"
            )
            separator = (
                "-------------------  -------------  ------------  -----  "
                "--------------------  ----------------"
            )
        elif all_channels:
            header = "Channel             ID    Date / Time           Rallies  Damage"
            separator = (
                "------------------  ----  --------------------  -------  "
                "----------------"
            )
        else:
            header = "ID    Date / Time           Rallies  Damage"
            separator = "----  --------------------  -------  ----------------"

        rows = []
        for event in events:
            timestamp = (
                f"{event.get_event_date() or '-'} "
                f"{event.get_event_time() or '-'}"
            )
            rallies = (
                event.get_rallies() if event.get_rallies() is not None else "-"
            )
            damage = (
                f"{event.get_alliance_damage():,}"
                if event.get_alliance_damage() is not None
                else "-"
            )
            if all_servers:
                server = table_text(
                    event.get_discord_guild_name()
                    or event.get_discord_guild_id()
                    or "unknown",
                    13,
                )
                name = table_text(
                    channel_label(event.get_discord_channel_name()), 12
                )
                rows.append(
                    f"{event.get_discord_guild_id():<19}  {server:<13}  "
                    f"{name:<12}  {event.get_event_id():<5}  "
                    f"{timestamp:<20}  {damage}"
                )
            elif all_channels:
                name = table_text(
                    channel_label(event.get_discord_channel_name()), 18
                )
                rows.append(
                    f"{name:<18}  {event.get_event_id():<4}  "
                    f"{timestamp:<20}  {str(rallies):<7}  {damage}"
                )
            else:
                rows.append(
                    f"{event.get_event_id():<4}  {timestamp:<20}  "
                    f"{str(rallies):<7}  {damage}"
                )
        chunks = code_table_chunks(header, separator, rows, title=title)
        if len(events) == 50:
            chunks[-1] += "\nShowing the latest 50 events."
        for chunk in chunks:
            await interaction.followup.send(chunk, ephemeral=True)

    @group.command(name="details", description="Show details for one event ID")
    @app_commands.describe(
        channel="Optional Bear channel to read from",
        all_channels="Allow lookup across this server",
        all_servers="Owner only: allow lookup across every server",
    )
    @log_discord_request(log_event, "/bear event details")
    async def details(
        interaction: discord.Interaction,
        event_id: int,
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
        event, results = await asyncio.to_thread(
            repository.fetch_event_details,
            event_id,
            scope.channel_id,
            scope.guild_id,
        )
        if event is None:
            await interaction.followup.send(
                "❌ No event with that ID exists in that scope.", ephemeral=True
            )
            return
        lines = [
            f"🐻 **Event ID {event.get_event_id()}**",
            f"Server: **{guild_label(event.get_discord_guild_name(), event.get_discord_guild_id())}**",
            f"Channel: **#{channel_label(event.get_discord_channel_name())}**",
            f"Type: **{event.get_event_type()}**",
            f"Date: **{event.get_event_date()} {event.get_event_time()}**",
            f"Rallies: **{event.get_rallies() if event.get_rallies() is not None else 'Not found'}**",
            (
                f"Alliance damage: **{event.get_alliance_damage():,}**"
                if event.get_alliance_damage() is not None
                else "Alliance damage: **Not found**"
            ),
            f"Participants: **{len(results)}**",
        ]
        await interaction.followup.send("\n".join(lines))

    @group.command(
        name="delete",
        description="Delete a saved event after confirmation",
    )
    @app_commands.describe(
        channel="Optional Bear channel to read from",
        all_channels="Allow deletion lookup across this server",
        all_servers="Owner only: allow deletion lookup across every server",
    )
    @log_discord_request(log_event, "/bear event delete")
    async def delete(
        interaction: discord.Interaction,
        event_id: int,
        channel: discord.TextChannel = None,
        all_channels: bool = False,
        all_servers: bool = False,
    ):
        scope = await prepare_report_scope(
            interaction, bot_owner_ids, channel, all_channels, all_servers
        )
        if scope is None:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        event, results = await asyncio.to_thread(
            repository.fetch_event_details,
            event_id,
            scope.channel_id,
            scope.guild_id,
        )
        if event is None:
            await interaction.followup.send(
                "❌ No event with that ID exists in that scope.", ephemeral=True
            )
            return

        location = (
            f"{guild_label(event.get_discord_guild_name(), event.get_discord_guild_id())} "
            f"/ #{channel_label(event.get_discord_channel_name())}"
        )
        await interaction.followup.send(
            f"⚠️ Delete Event ID **{event_id}** from **{location}** with "
            f"**{len(results)}** player results? This cannot be undone.",
            ephemeral=True,
            view=EventDeleteView(
                repository,
                event_id,
                scope.channel_id,
                scope.guild_id,
                interaction.user.id,
            ),
        )

    @group.command(
        name="trend",
        description="Chart event rallies, participation, and damage over time",
    )
    @app_commands.describe(
        channel="Optional Bear channel to read from",
        all_channels="Chart events across this server",
        all_servers="Owner only: chart across every configured server",
    )
    @log_discord_request(log_event, "/bear event trend")
    async def trend(
        interaction: discord.Interaction,
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
            repository.fetch_event_trend,
            scope.channel_id,
            scope.guild_id,
            since_date,
        )
        if not rows:
            await interaction.followup.send(
                f"🐻 No saved events for {scope.label} in the last "
                f"{months} month(s)."
            )
            return

        chart = await asyncio.to_thread(create_event_trend_chart, rows, months)
        message = (
            f"🐻 **Event trends for {scope.label} — last {months} month(s)**"
        )
        guild_line = guild_scope_line(rows) if all_servers else None
        if guild_line:
            message += f"\n{guild_line}"
        await interaction.followup.send(
            message,
            file=discord.File(chart, filename="bear-event-trend.png"),
        )
