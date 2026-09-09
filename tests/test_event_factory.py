import os
import sqlite3
import tempfile
import unittest

from models.event import EventFactory


class EventFactoryTrendTests(unittest.TestCase):
    def setUp(self):
        handle, self.database_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        self.factory = EventFactory(lambda: sqlite3.connect(self.database_path))
        self.factory.setup_schema()
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(
                """CREATE TABLE player_results (
                    id INTEGER PRIMARY KEY,
                    event_id INTEGER NOT NULL
                )"""
            )
            connection.executemany(
                """INSERT INTO events (
                    id, event_type, event_date, event_time, rallies,
                    alliance_damage, discord_channel_id, discord_channel_name,
                    discord_guild_id, discord_guild_name, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (1, "Bear Trap 2", "2026-08-20", "20:00:00", 60,
                     400000000, "10", "bear-2", "20", "Test Server",
                     "2026-08-20T20:00:00"),
                    (2, "Hunting Trap 2", "2026-09-01", "20:30:00", 70,
                     500000000, "10", "bear-2", "20", "Test Server",
                     "2026-09-01T20:30:00"),
                ],
            )
            connection.executemany(
                "INSERT INTO player_results (event_id) VALUES (?)",
                [(1,), (2,), (2,)],
            )
            connection.commit()
        finally:
            connection.close()

    def tearDown(self):
        os.unlink(self.database_path)

    def test_event_trend_rows_include_event_identity_and_participants(self):
        rows = self.factory.get_event_trend_rows("10", "20", "2026-08-01")

        self.assertEqual([row["event_id"] for row in rows], [1, 2])
        self.assertEqual([row["participant_count"] for row in rows], [1, 2])
        self.assertEqual(rows[1]["event_type"], "Hunting Trap 2")
        self.assertEqual(rows[1]["alliance_damage"], 500000000)


if __name__ == "__main__":
    unittest.main()
