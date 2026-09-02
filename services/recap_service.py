import hashlib
import json
from collections import defaultdict


RECAP_PROMPT_VERSION = "bear-recap-v1"
RECAP_MODEL = "gpt-5-mini"


def build_recap_data(events, results):
    event_data = [dict(event) for event in events]
    event_position = {
        event["event_id"]: position for position, event in enumerate(event_data)
    }
    by_player = defaultdict(list)
    participant_counts = defaultdict(int)
    for result in results:
        item = dict(result)
        item["event_position"] = event_position[item["event_id"]]
        player_key = (item.get("discord_guild_id"), item["player_name"])
        by_player[player_key].append(item)
        participant_counts[item["event_id"]] += 1

    for position, event in enumerate(event_data):
        event["participants"] = participant_counts[event["event_id"]]
        previous = event_data[position + 1] if position + 1 < len(event_data) else None
        current_damage = event["alliance_damage"]
        previous_damage = previous["alliance_damage"] if previous else None
        event["alliance_change_from_previous"] = None
        event["alliance_change_percent"] = None
        if current_damage is not None and previous_damage is not None:
            change = current_damage - previous_damage
            event["alliance_change_from_previous"] = change
            if previous_damage:
                event["alliance_change_percent"] = round(
                    change * 100 / previous_damage, 1
                )

    players = []
    for (guild_id, player_name), appearances in by_player.items():
        appearances.sort(key=lambda item: item["event_position"])
        damage_values = [item["damage"] for item in appearances]
        latest = appearances[0]
        previous = appearances[1] if len(appearances) > 1 else None
        change = latest["damage"] - previous["damage"] if previous else None
        change_percent = None
        if previous and previous["damage"]:
            change_percent = round(change * 100 / previous["damage"], 1)
        players.append({
            "name": player_name,
            "server_id": guild_id,
            "server_name": appearances[0].get("discord_guild_name"),
            "events_participated": len(appearances),
            "average_damage": round(sum(damage_values) / len(damage_values)),
            "window_best_damage": max(damage_values),
            "latest": {
                "event_id": latest["event_id"],
                "damage": latest["damage"],
                "rank": latest["rank"],
            },
            "change_from_previous": change,
            "change_percent": change_percent,
            "results": [
                {
                    "event_id": item["event_id"],
                    "damage": item["damage"],
                    "rank": item["rank"],
                }
                for item in appearances
            ],
        })

    players.sort(
        key=lambda item: (
            item["latest"]["event_id"] != event_data[0]["event_id"],
            -item["latest"]["damage"],
            item["name"].casefold(),
        )
    )
    return {
        "events": event_data,
        "players": players,
    }


def recap_cache_key(recap_data):
    source = {
        "prompt_version": RECAP_PROMPT_VERSION,
        "model": RECAP_MODEL,
        "data": recap_data,
    }
    encoded = json.dumps(
        source, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def recap_input_text(recap_data):
    return json.dumps(recap_data, separators=(",", ":"), ensure_ascii=False)
