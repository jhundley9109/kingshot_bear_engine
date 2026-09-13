import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from data_access import BearTrapRepository


class BearTrapRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(
            self.temp_directory.name,
            "nested",
            "beartrap.sqlite3",
        )
        self.repository = BearTrapRepository(self.database_path)

    def tearDown(self):
        self.repository.close()
        self.temp_directory.cleanup()

    def test_setup_creates_final_schema_without_backfills(self):
        self.repository.setup()

        connection = self.repository.connect()
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

        self.assertTrue(
            {"events", "players", "player_aliases", "player_results", "bear_recap_cache"}
            <= tables
        )
        connection.close()
        self.assertFalse(hasattr(self.repository, "_backfill_event_guilds"))
        self.assertFalse(hasattr(self.repository, "_backfill_player_ids"))

    def test_connection_is_reused_until_repository_is_closed(self):
        self.repository.setup()
        first = self.repository.connect()
        underlying_connection = first._connection
        first.close()

        # Factory methods still call close(), but that now releases an
        # operation without discarding the repository-owned connection.
        self.repository.fetch_events()
        second = self.repository.connect()

        self.assertIs(underlying_connection, second._connection)
        self.assertEqual(1, second.execute("PRAGMA foreign_keys").fetchone()[0])
        self.assertEqual(30000, second.execute("PRAGMA busy_timeout").fetchone()[0])
        self.assertEqual("wal", second.execute("PRAGMA journal_mode").fetchone()[0])
        second.close()

        self.repository.close()
        replacement = self.repository.connect()
        self.assertIsNot(underlying_connection, replacement._connection)
        self.assertEqual(1, replacement.execute("SELECT 1").fetchone()[0])
        replacement.close()

    def test_connection_can_be_used_from_a_worker_thread(self):
        self.repository.setup()

        with ThreadPoolExecutor(max_workers=1) as executor:
            players = executor.submit(self.repository.fetch_players, "guild").result()

        self.assertEqual([], players)

    def test_operation_close_rolls_back_uncommitted_work(self):
        self.repository.setup()
        connection = self.repository.connect()
        connection.execute(
            """INSERT INTO events (
                event_type, event_date, event_time, rallies, alliance_damage,
                submitted_by, discord_message_id, discord_channel_id,
                discord_channel_name, discord_guild_id, discord_guild_name,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "test", "2026-09-13", "12:00:00", 1, 1, "tester",
                "message", "channel", "Channel", "guild", "Guild",
                "2026-09-13T12:00:00+00:00",
            ),
        )

        connection.close()

        verification = self.repository.connect()
        count = verification.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        verification.close()
        self.assertEqual(0, count)

    def test_new_and_renamed_canonical_names_exclude_alliance_tags(self):
        self.repository.setup()
        connection = self.repository.connect()

        player = self.repository.player_factory.resolve_player_model(
            "[XuX] Example Player",
            connection,
            "guild",
        )
        connection.commit()

        self.assertEqual("Example Player", player.get_canonical_name())
        alias = connection.execute(
            "SELECT alias_name, normalized_name FROM player_aliases WHERE player_id = ?",
            (player.get_player_id(),),
        ).fetchone()
        self.assertEqual("[XuX] Example Player", alias["alias_name"])
        self.assertEqual("example player", alias["normalized_name"])
        connection.close()

        renamed = self.repository.rename_player(
            "Example Player",
            "[XuX] Renamed Player",
            "guild",
        )
        self.assertEqual("Renamed Player", renamed.get_canonical_name())

    def test_player_name_cannot_consist_only_of_alliance_tags(self):
        self.repository.setup()
        connection = self.repository.connect()

        try:
            with self.assertRaisesRegex(ValueError, "only of alliance tags"):
                self.repository.player_factory.resolve_player_model(
                    "[XuX]",
                    connection,
                    "guild",
                )
        finally:
            connection.close()

    def test_setup_rejects_an_outdated_schema_instead_of_migrating_it(self):
        os.makedirs(os.path.dirname(self.database_path), exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            """CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        connection.commit()
        connection.close()

        with self.assertRaisesRegex(
            RuntimeError,
            "Database schema is not current; missing columns: events:",
        ):
            self.repository.setup()


if __name__ == "__main__":
    unittest.main()
