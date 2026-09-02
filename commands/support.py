from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class ReportScope:
    channel_id: object
    guild_id: object
    label: str
    all_channels: bool
    all_servers: bool


async def prepare_report_scope(
    interaction,
    bot_owner_ids,
    channel=None,
    all_channels=False,
    all_servers=False,
):
    selected_count = sum((channel is not None, all_channels, all_servers))
    if selected_count > 1:
        await interaction.response.send_message(
            "❌ Choose only one of `channel`, `all_channels`, or `all_servers`.",
            ephemeral=True,
        )
        return None
    if all_servers and interaction.user.id not in bot_owner_ids:
        await interaction.response.send_message(
            "❌ `all_servers` is restricted to configured bot owners.",
            ephemeral=True,
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


async def prepare_trend_since_date(interaction, months, today=None):
    if months not in (1, 3):
        await interaction.response.send_message(
            "❌ Choose either `months: 1` or `months: 3`.",
            ephemeral=True,
        )
        return None
    today = today or datetime.now(timezone.utc).date()
    return (today - timedelta(days=months * 30)).isoformat()
