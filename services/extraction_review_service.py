IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
DISCORD_MESSAGE_LIMIT = 1900


def find_image_attachments(attachments):
    images = [
        attachment
        for attachment in attachments
        if attachment.content_type
        and attachment.content_type.startswith("image/")
    ]
    if images:
        return images
    return [
        attachment
        for attachment in attachments
        if attachment.filename.lower().endswith(IMAGE_EXTENSIONS)
    ]


def find_missing_ranks(players):
    ranks = {player["rank"] for player in players}
    if not ranks:
        return []
    return [rank for rank in range(min(ranks), max(ranks) + 1) if rank not in ranks]


def build_extraction_preview(
    data, players, conflicts, screenshot_count, existing_event_id=None
):
    lines = [
        "🐻 **Bear Trap data extracted!**",
        f"📸 Screenshots processed: **{screenshot_count}**",
        f"👥 Unique rankings found: **{len(players)}**",
        "",
        "**Event information:**",
    ]

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
    lines.extend([
        f"📅 Date: **{event_date or 'Not found'}**",
        f"🕒 Time: **{event_time or 'Not found'}**",
    ])
    if rallies is not None:
        lines.append(f"🎯 Rallies: **{rallies:,}**")

    extracted_player_damage = sum(player["damage"] for player in players)
    if alliance_damage is not None:
        lines.extend([
            f"💥 Alliance damage: **{alliance_damage:,}**",
            f"👥 Extracted player damage: **{extracted_player_damage:,}**",
        ])
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
        lines.append("⚠️ No event information was found.")

    lines.extend(["", "**Results found:**"])
    for player in players:
        uncertain = " ⚠️" if player.get("uncertain", False) else ""
        lines.append(
            f"**{player['rank']}.** {player['player_name']} — "
            f"{player['damage']:,}{uncertain}"
        )

    missing = find_missing_ranks(players)
    if missing:
        lines.extend([
            "",
            "⚠️ **Missing ranks:** " + ", ".join(str(rank) for rank in missing),
        ])

    if conflicts:
        lines.extend(["", f"🚨 **Conflicting duplicate ranks: {len(conflicts)}**"])
        for conflict in conflicts:
            lines.append(
                f"Rank {conflict['rank']}: "
                f"{conflict['first']['player_name']} vs "
                f"{conflict['second']['player_name']}"
            )

    lines.append("")
    if conflicts:
        lines.append("🚫 **Not saved — resolve conflicting ranks and reprocess.**")
    elif existing_event_id:
        lines.append(
            "🔁 **A matching report exists — use Replace existing report "
            "to overwrite it.**"
        )
    else:
        lines.append("🔍 **Review this preview before saving.**")

    result = "\n".join(lines)
    if len(result) > DISCORD_MESSAGE_LIMIT:
        truncation_notice = (
            "\n\n⚠️ Output was truncated. "
            "The full report is too large for one Discord message."
        )
        result = result[: DISCORD_MESSAGE_LIMIT - len(truncation_notice)]
        result += truncation_notice
    return result
