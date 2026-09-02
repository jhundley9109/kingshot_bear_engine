import json
import re
import unicodedata

from services.discord_formatting import DISCORD_MESSAGE_LIMIT


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
BEAR_EXTRACTION_MODEL = "gpt-5"
BEAR_EXTRACTION_PROMPT = """
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


def extract_bear_data(openai_client, image_urls):
    content = [{"type": "input_text", "text": BEAR_EXTRACTION_PROMPT}]
    content.extend(
        {"type": "input_image", "image_url": url, "detail": "high"}
        for url in image_urls
    )
    response = openai_client.responses.create(
        model=BEAR_EXTRACTION_MODEL,
        input=[{"role": "user", "content": content}],
    )
    return json.loads(response.output_text)


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
            continue

        existing = merged[rank]
        if (
            player_match_name(existing["player_name"])
            == player_match_name(player["player_name"])
            and existing["damage"] == player["damage"]
        ):
            continue
        conflicts.append({"rank": rank, "first": existing, "second": player})

    return [merged[rank] for rank in sorted(merged)], conflicts


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
