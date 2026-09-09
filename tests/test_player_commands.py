import unittest

from commands.player_commands import _player_stats_chunks


class PlayerCommandFormattingTests(unittest.TestCase):
    def test_player_stats_formats_event_history_as_table(self):
        summary = {
            "player_name": "Example Player",
            "appearances": 2,
            "total_damage": 962109241,
            "average_damage": 481054620.5,
            "best_damage": 509655474,
            "best_rank": 10,
        }
        history = [
            {
                "event_id": 8,
                "event_date": "2026-09-01",
                "event_time": "20:30:05",
                "event_type": "Hunting Trap 2",
                "rank": 10,
                "damage": 509655474,
                "uncertain": False,
                "discord_channel_name": "bear-2",
                "discord_guild_name": None,
                "discord_guild_id": "1461210419334090856",
            }
        ]

        chunks = _player_stats_chunks(
            summary,
            history,
            "all configured Discord servers",
            all_servers=True,
        )
        output = chunks[0]

        self.assertIn("Server", output)
        self.assertIn("Channel", output)
        self.assertIn("Date / Time", output)
        self.assertIn("1461210419334090856", output)
        self.assertIn("bear-2", output)
        self.assertIn("509,655,474", output)
        self.assertNotIn("Event **8**", output)
        self.assertIn("```text", output)


if __name__ == "__main__":
    unittest.main()
