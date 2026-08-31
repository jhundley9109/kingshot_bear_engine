import os
import sqlite3
from datetime import datetime, timezone


class BearTrapRepository:

    def __init__(self, database_path):
        self.database_path = database_path

    def connect(self, row_factory=False):
        connection = sqlite3.connect(self.database_path)
        if row_factory:
            connection.row_factory = sqlite3.Row
        return connection

    def setup(self):
        directory = os.path.dirname(self.database_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        connection = self.connect()
        cursor = connection.cursor()

        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    event_date TEXT,
                    event_time TEXT,
                    rallies INTEGER,
                    alliance_damage INTEGER,
                    submitted_by TEXT,
                    discord_message_id TEXT,
                    discord_channel_id TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS player_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    rank INTEGER NOT NULL,
                    player_name TEXT NOT NULL,
                    damage INTEGER NOT NULL,
                    uncertain INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (event_id) REFERENCES events(id)
                )
            """)

            event_columns = {
                row[1]
                for row in cursor.execute("PRAGMA table_info(events)")
            }
            for name, definition in (
                ("event_time", "TEXT"),
                ("discord_message_id", "TEXT"),
                ("discord_channel_id", "TEXT"),
            ):
                if name not in event_columns:
                    cursor.execute(
                        f"ALTER TABLE events ADD COLUMN {name} {definition}"
                    )

            result_columns = {
                row[1]
                for row in cursor.execute("PRAGMA table_info(player_results)")
            }
            if "uncertain" not in result_columns:
                cursor.execute(
                    "ALTER TABLE player_results "
                    "ADD COLUMN uncertain INTEGER NOT NULL DEFAULT 0"
                )

            connection.commit()
        finally:
            connection.close()

    def find_existing_report(self, data, source_message):
        connection = self.connect()

        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT id FROM events
                WHERE discord_message_id = ? AND discord_channel_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (str(source_message.id), str(source_message.channel.id))
            )
            row = cursor.fetchone()
            if row:
                return row[0]

            event_identity = (
                data.get("event_type"),
                data.get("event_date"),
                data.get("event_time")
            )
            if all(event_identity):
                cursor.execute(
                    """
                    SELECT id FROM events
                    WHERE event_type = ? AND event_date = ? AND event_time = ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    event_identity
                )
                row = cursor.fetchone()
                if row:
                    return row[0]

            return None
        finally:
            connection.close()

    def write_result(
        self,
        data,
        players,
        source_message,
        submitted_by,
        existing_event_id=None
    ):
        if not players:
            raise ValueError("Cannot save a result with no player rankings.")

        connection = self.connect()
        try:
            cursor = connection.cursor()
            event_values = (
                data.get("event_type") or "Unknown Bear Trap",
                data.get("event_date"),
                data.get("event_time"),
                data.get("rallies"),
                data.get("alliance_damage"),
                str(submitted_by),
                str(source_message.id),
                str(source_message.channel.id),
                datetime.now(timezone.utc).isoformat(timespec="seconds")
            )

            if existing_event_id is None:
                cursor.execute(
                    """
                    INSERT INTO events (
                        event_type, event_date, event_time, rallies,
                        alliance_damage, submitted_by, discord_message_id,
                        discord_channel_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    event_values
                )
                event_id = cursor.lastrowid
            else:
                cursor.execute(
                    """
                    UPDATE events SET
                        event_type = ?, event_date = ?, event_time = ?,
                        rallies = ?, alliance_damage = ?, submitted_by = ?,
                        discord_message_id = ?, discord_channel_id = ?,
                        created_at = ?
                    WHERE id = ?
                    """,
                    event_values + (existing_event_id,)
                )
                if cursor.rowcount != 1:
                    raise ValueError("The existing report could not be found.")
                cursor.execute(
                    "DELETE FROM player_results WHERE event_id = ?",
                    (existing_event_id,)
                )
                event_id = existing_event_id

            cursor.executemany(
                """
                INSERT INTO player_results (
                    event_id, rank, player_name, damage, uncertain
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        event_id,
                        player["rank"],
                        player["player_name"],
                        player["damage"],
                        int(player.get("uncertain", False))
                    )
                    for player in players
                ]
            )
            connection.commit()
            return event_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save_result(self, data, players, source_message, submitted_by):
        return self.write_result(
            data,
            players,
            source_message,
            submitted_by
        )

    def replace_result(
        self,
        existing_event_id,
        data,
        players,
        source_message,
        submitted_by
    ):
        return self.write_result(
            data,
            players,
            source_message,
            submitted_by,
            existing_event_id
        )

    def fetch_latest_summary(self):
        connection = self.connect(row_factory=True)
        try:
            event = connection.execute(
                """
                SELECT
                    events.*,
                    COUNT(player_results.id) AS player_count,
                    SUM(player_results.uncertain) AS uncertain_count
                FROM events
                LEFT JOIN player_results
                    ON player_results.event_id = events.id
                GROUP BY events.id
                ORDER BY events.created_at DESC, events.id DESC
                LIMIT 1
                """
            ).fetchone()
            if event is None:
                return None, []
            leaders = connection.execute(
                """
                SELECT rank, player_name, damage, uncertain
                FROM player_results
                WHERE event_id = ?
                ORDER BY rank ASC
                LIMIT 5
                """,
                (event["id"],)
            ).fetchall()
            return event, leaders
        finally:
            connection.close()

    def fetch_leaderboard(self, limit):
        connection = self.connect(row_factory=True)
        try:
            return connection.execute(
                """
                SELECT
                    player_name,
                    COUNT(*) AS appearances,
                    SUM(damage) AS total_damage,
                    AVG(damage) AS average_damage,
                    MAX(damage) AS best_damage
                FROM player_results
                GROUP BY player_name
                ORDER BY total_damage DESC, average_damage DESC, player_name ASC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
        finally:
            connection.close()

    def fetch_player_history(self, search_text):
        connection = self.connect(row_factory=True)
        try:
            pattern = f"%{search_text}%"
            matching_names = connection.execute(
                """
                SELECT
                    player_name,
                    COUNT(*) AS appearances,
                    AVG(damage) AS average_damage,
                    MAX(damage) AS best_damage
                FROM player_results
                WHERE player_name LIKE ? COLLATE NOCASE
                GROUP BY player_name
                ORDER BY appearances DESC, player_name ASC
                LIMIT 10
                """,
                (pattern,)
            ).fetchall()
            history = connection.execute(
                """
                SELECT
                    events.event_type,
                    events.event_date,
                    events.event_time,
                    player_results.player_name,
                    player_results.rank,
                    player_results.damage,
                    player_results.uncertain
                FROM player_results
                JOIN events ON events.id = player_results.event_id
                WHERE player_results.player_name LIKE ? COLLATE NOCASE
                ORDER BY events.created_at DESC, events.id DESC,
                    player_results.rank ASC
                LIMIT 10
                """,
                (pattern,)
            ).fetchall()
            return matching_names, history
        finally:
            connection.close()
