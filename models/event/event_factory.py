import sqlite3

from .event_model import EventModel


class EventFactory:

    def __init__(self, connection_factory):
        self._connection_factory = connection_factory

    def setup_schema(self):
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
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
                    discord_channel_name TEXT,
                    discord_guild_id TEXT,
                    discord_guild_name TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            columns = {row[1] for row in cursor.execute("PRAGMA table_info(events)")}
            for name in ("event_time", "discord_message_id", "discord_channel_id", "discord_channel_name", "discord_guild_id", "discord_guild_name"):
                if name not in columns:
                    cursor.execute(f"ALTER TABLE events ADD COLUMN {name} TEXT")
            connection.commit()
        finally:
            connection.close()

    def _to_model(self, row):
        return EventModel(
            event_id=row["id"], event_type=row["event_type"],
            event_date=row["event_date"], event_time=row["event_time"],
            rallies=row["rallies"], alliance_damage=row["alliance_damage"],
            submitted_by=row["submitted_by"],
            discord_message_id=row["discord_message_id"],
            discord_channel_id=row["discord_channel_id"],
            discord_channel_name=row["discord_channel_name"],
            discord_guild_id=row["discord_guild_id"],
            discord_guild_name=row["discord_guild_name"],
            created_at=row["created_at"]
        )

    def get_event_model_by_event_id(self, event_id, connection=None):
        owns_connection = connection is None
        connection = connection or self._connection_factory()
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
            return self._to_model(row) if row else None
        finally:
            if owns_connection:
                connection.close()

    def get_latest_event_model(self, channel_id=None, guild_id=None):
        connection = self._connection_factory()
        connection.row_factory = sqlite3.Row
        try:
            clauses = []; params = []
            if guild_id is not None:
                clauses.append("discord_guild_id = ?"); params.append(str(guild_id))
            if channel_id is not None:
                clauses.append("discord_channel_id = ?"); params.append(str(channel_id))
            where = "WHERE " + " AND ".join(clauses) if clauses else ""
            row = connection.execute(
                f"SELECT * FROM events {where} ORDER BY created_at DESC, id DESC LIMIT 1",
                params
            ).fetchone()
            return self._to_model(row) if row else None
        finally:
            connection.close()

    def find_duplicate_event_model(self, data, source_message):
        connection = self._connection_factory()
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                """SELECT * FROM events
                   WHERE discord_message_id = ? AND discord_channel_id = ?
                   ORDER BY id DESC LIMIT 1""",
                (str(source_message.id), str(source_message.channel.id))
            ).fetchone()
            if row:
                return self._to_model(row)
            identity = (data.get("event_type"), data.get("event_date"), data.get("event_time"))
            if all(identity):
                row = connection.execute(
                    """SELECT * FROM events
                       WHERE event_type = ? AND event_date = ? AND event_time = ?
                         AND discord_channel_id = ?
                       ORDER BY id DESC LIMIT 1""",
                    identity + (str(source_message.channel.id),)
                ).fetchone()
                if row:
                    return self._to_model(row)
            return None
        finally:
            connection.close()

    def save_event_model(self, event_model, connection):
        values = (
            event_model.get_event_type(), event_model.get_event_date(),
            event_model.get_event_time(), event_model.get_rallies(),
            event_model.get_alliance_damage(), event_model.get_submitted_by(),
            event_model.get_discord_message_id(), event_model.get_discord_channel_id(),
            event_model.get_discord_channel_name(), event_model.get_created_at()
            , event_model.get_discord_guild_id(), event_model.get_discord_guild_name()
        )
        cursor = connection.cursor()
        if event_model.get_event_id() is None:
            cursor.execute(
                """INSERT INTO events (
                    event_type, event_date, event_time, rallies, alliance_damage,
                    submitted_by, discord_message_id, discord_channel_id,
                    discord_channel_name, created_at, discord_guild_id,
                    discord_guild_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values
            )
            event_model.set_event_id(cursor.lastrowid)
        else:
            cursor.execute(
                """UPDATE events SET event_type = ?, event_date = ?, event_time = ?,
                    rallies = ?, alliance_damage = ?, submitted_by = ?,
                    discord_message_id = ?, discord_channel_id = ?,
                    discord_channel_name = ?, created_at = ?,
                    discord_guild_id = ?, discord_guild_name = ? WHERE id = ?""",
                values + (event_model.get_event_id(),)
            )
            if cursor.rowcount != 1:
                raise ValueError("The existing report could not be found.")
        return event_model

    def get_event_trend_rows(self, channel_id, guild_id, since_date):
        connection = self._connection_factory(); connection.row_factory = sqlite3.Row
        try:
            where = "events.event_date >= ?"
            params = [since_date]
            if guild_id is not None:
                where = "events.discord_guild_id = ? AND " + where
                params.insert(0, str(guild_id))
            if channel_id is not None:
                where = "events.discord_channel_id = ? AND " + where
                params.insert(0, str(channel_id))
            return connection.execute(
                f"""SELECT events.event_date, events.event_time, events.rallies,
                    events.alliance_damage, events.discord_channel_name,
                    events.discord_guild_id, events.discord_guild_name,
                    COUNT(player_results.id) AS participant_count
                   FROM events
                   LEFT JOIN player_results ON player_results.event_id = events.id
                   WHERE {where}
                   GROUP BY events.id
                   ORDER BY events.event_date, events.event_time, events.id""",
                params
            ).fetchall()
        finally: connection.close()

    def get_event_models(self, channel_id=None, guild_id=None, limit=50):
        connection = self._connection_factory(); connection.row_factory = sqlite3.Row
        try:
            clauses = []; params = []
            if guild_id is not None:
                clauses.append("discord_guild_id = ?"); params.append(str(guild_id))
            if channel_id is not None:
                clauses.append("discord_channel_id = ?"); params.append(str(channel_id))
            where = "WHERE " + " AND ".join(clauses) if clauses else ""
            params.append(limit)
            rows = connection.execute(
                f"""SELECT * FROM events {where}
                    ORDER BY discord_guild_name ASC, discord_channel_name ASC,
                    event_date DESC, event_time DESC, id DESC LIMIT ?""",
                params
            ).fetchall()
            return [self._to_model(row) for row in rows]
        finally: connection.close()

    def delete_event_model_by_id(self, event_id, connection):
        cursor = connection.execute("DELETE FROM events WHERE id = ?", (event_id,))
        if cursor.rowcount != 1:
            raise ValueError("The event could not be found.")
