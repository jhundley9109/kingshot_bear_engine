import os
import sqlite3
import threading
from datetime import datetime, timezone

from models.event import EventFactory, EventModel
from models.player import PlayerFactory
from models.player_result import PlayerResultFactory, PlayerResultModel


FINAL_SCHEMA_COLUMNS = {
    "events": {
        "id", "event_type", "event_date", "event_time", "rallies",
        "alliance_damage", "submitted_by", "discord_message_id",
        "discord_channel_id", "discord_channel_name", "discord_guild_id",
        "discord_guild_name", "created_at",
    },
    "players": {"id", "canonical_name", "guild_id", "created_at", "updated_at"},
    "player_aliases": {
        "id", "player_id", "alias_name", "normalized_name", "visual_key",
        "guild_id",
    },
    "player_results": {
        "id", "event_id", "player_id", "rank", "player_name", "damage",
        "uncertain",
    },
    "bear_recap_cache": {
        "cache_key", "model", "event_count", "recap_text", "created_at",
    },
}


class _ConnectionLease:
    """Serialize one complete operation on a shared SQLite connection."""

    def __init__(self, connection, lock):
        self._connection = connection
        self._lock = lock
        self._released = False

    @property
    def row_factory(self):
        self._ensure_open()
        return self._connection.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._ensure_open()
        self._connection.row_factory = value

    def __getattr__(self, name):
        self._ensure_open()
        return getattr(self._connection, name)

    def _ensure_open(self):
        if self._released:
            raise sqlite3.ProgrammingError("Cannot use a released database connection.")

    def close(self):
        if self._released:
            return
        try:
            # Preserve the old per-operation connection behavior when an
            # operation exits without committing its transaction.
            if self._connection.in_transaction:
                self._connection.rollback()
        finally:
            self._released = True
            self._lock.release()


class BearTrapRepository:
    def __init__(self, database_path):
        self.database_path = database_path
        self._connection = None
        self._connection_lock = threading.RLock()
        self.event_factory = EventFactory(self.connect)
        self.player_factory = PlayerFactory(self.connect)
        self.player_result_factory = PlayerResultFactory(self.connect)

    def connect(self):
        self._connection_lock.acquire()
        try:
            if self._connection is None:
                connection = sqlite3.connect(
                    self.database_path,
                    timeout=30,
                    check_same_thread=False,
                )
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("PRAGMA busy_timeout = 30000")
                connection.execute("PRAGMA journal_mode = WAL")
                self._connection = connection
            return _ConnectionLease(self._connection, self._connection_lock)
        except Exception:
            self._connection_lock.release()
            raise

    def close(self):
        with self._connection_lock:
            if self._connection is not None:
                if self._connection.in_transaction:
                    self._connection.rollback()
                self._connection.close()
                self._connection = None

    def setup(self):
        directory = os.path.dirname(self.database_path)
        if directory: os.makedirs(directory, exist_ok=True)
        self.event_factory.setup_schema()
        self.player_factory.setup_schema()
        self.player_result_factory.setup_schema()
        self._setup_recap_cache_schema()
        self._validate_schema()

    def _validate_schema(self):
        connection = self.connect()
        try:
            problems = []
            for table, required_columns in FINAL_SCHEMA_COLUMNS.items():
                actual_columns = {
                    row["name"]
                    for row in connection.execute(f"PRAGMA table_info({table})")
                }
                missing_columns = sorted(required_columns - actual_columns)
                if missing_columns:
                    problems.append(f"{table}: {', '.join(missing_columns)}")
            if problems:
                raise RuntimeError(
                    "Database schema is not current; missing columns: "
                    + "; ".join(problems)
                )
        finally:
            connection.close()

    def _setup_recap_cache_schema(self):
        connection = self.connect()
        try:
            connection.execute("""CREATE TABLE IF NOT EXISTS bear_recap_cache (
                cache_key TEXT PRIMARY KEY,
                model TEXT NOT NULL,
                event_count INTEGER NOT NULL,
                recap_text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""")
            connection.commit()
        finally: connection.close()
    def find_existing_report(self, data, source_message):
        event=self.event_factory.find_duplicate_event_model(data, source_message)
        return event.get_event_id() if event else None
    def _event_model(self, data, source_message, submitted_by, submitted_at, event_id=None):
        submitted_at=submitted_at or datetime.now(timezone.utc)
        guild = getattr(source_message, "guild", None)
        return EventModel(event_id=event_id, event_type=data.get("event_type") or "Unknown Bear Trap", event_date=data.get("event_date") or submitted_at.date().isoformat(), event_time=data.get("event_time") or submitted_at.time().replace(microsecond=0).isoformat(), rallies=data.get("rallies"), alliance_damage=data.get("alliance_damage"), submitted_by=str(submitted_by), discord_message_id=str(source_message.id), discord_channel_id=str(source_message.channel.id), discord_channel_name=getattr(source_message.channel, "name", None), discord_guild_id=str(guild.id) if guild else None, discord_guild_name=getattr(guild, "name", None), created_at=submitted_at.isoformat(timespec="seconds"))
    def write_result(self, data, players, source_message, submitted_by, submitted_at=None, existing_event_id=None):
        if not players: raise ValueError("Cannot save a result with no player rankings.")
        connection=self.connect()
        try:
            event=self.event_factory.save_event_model(self._event_model(data, source_message, submitted_by, submitted_at, existing_event_id), connection)
            results=[]
            for player in players:
                identity=self.player_factory.resolve_player_model(player["player_name"], connection, event.get_discord_guild_id())
                results.append(PlayerResultModel(event_id=event.get_event_id(), player_id=identity.get_player_id(), rank=player["rank"], raw_player_name=player["player_name"], damage=player["damage"], uncertain=player.get("uncertain", False)))
            self.player_result_factory.replace_player_result_models_by_event_id(event.get_event_id(), results, connection)
            connection.commit(); return event.get_event_id()
        except Exception:
            connection.rollback(); raise
        finally: connection.close()
    def save_result(self, data, players, source_message, submitted_by, submitted_at=None): return self.write_result(data, players, source_message, submitted_by, submitted_at)
    def replace_result(self, existing_event_id, data, players, source_message, submitted_by, submitted_at=None): return self.write_result(data, players, source_message, submitted_by, submitted_at, existing_event_id)
    def rename_player(self, old_name, new_name, guild_id): return self.player_factory.rename_player(old_name, new_name, guild_id)
    def fetch_players(self, guild_id, limit=100): return self.player_factory.get_player_models(guild_id, limit)
    def fetch_latest_summary(self, channel_id=None, guild_id=None):
        event=self.event_factory.get_latest_event_model(channel_id, guild_id)
        return (event, self.player_result_factory.get_player_result_models_by_event_id(event.get_event_id())) if event else (None, [])
    def fetch_leaderboard(self, channel_id, guild_id, limit): return self.player_result_factory.get_leaderboard_rows(channel_id, guild_id, limit)
    def fetch_event_trend(self, channel_id, guild_id, since_date): return self.event_factory.get_event_trend_rows(channel_id, guild_id, since_date)
    def fetch_events(self, channel_id=None, guild_id=None, limit=50): return self.event_factory.get_event_models(channel_id, guild_id, limit)
    def fetch_event_details(self, event_id, channel_id=None, guild_id=None):
        event = self.event_factory.get_event_model_by_event_id(event_id)
        if event is None or (guild_id is not None and event.get_discord_guild_id() != str(guild_id)) or (channel_id is not None and event.get_discord_channel_id() != str(channel_id)): return None, []
        return event, self.player_result_factory.get_player_result_models_by_event_id(event_id)
    def delete_event(self, event_id, channel_id=None, guild_id=None):
        connection = self.connect()
        try:
            event = self.event_factory.get_event_model_by_event_id(event_id, connection)
            if event is None or (guild_id is not None and event.get_discord_guild_id() != str(guild_id)) or (channel_id is not None and event.get_discord_channel_id() != str(channel_id)):
                raise ValueError("No event with that ID exists in this channel.")
            self.player_result_factory.delete_player_result_models_by_event_id(event_id, connection)
            self.event_factory.delete_event_model_by_id(event_id, connection)
            connection.commit(); return event
        except Exception:
            connection.rollback(); raise
        finally: connection.close()
    def fetch_player_history(self, channel_id, guild_id, search_text): return self.player_result_factory.get_player_search_rows(channel_id, guild_id, search_text)
    def fetch_player_stats(self, channel_id, guild_id, player_name): return self.player_result_factory.get_player_stats_rows(channel_id, guild_id, player_name)
    def fetch_player_trend(self, channel_id, guild_id, search_text, since_date): return self.player_result_factory.get_player_trend_rows(channel_id, guild_id, search_text, since_date)
    def fetch_recap_source(self, channel_id, guild_id, event_count=5):
        connection = self.connect(); connection.row_factory = sqlite3.Row
        try:
            where = ""
            params = []
            clauses = []
            if guild_id is not None:
                clauses.append("discord_guild_id = ?")
                params.append(str(guild_id))
            if channel_id is not None:
                clauses.append("discord_channel_id = ?")
                params.append(str(channel_id))
            if clauses:
                where = "WHERE " + " AND ".join(clauses)
            params.append(event_count)
            events = connection.execute(f"""SELECT id AS event_id, event_type,
                event_date, event_time, alliance_damage, discord_channel_name,
                discord_guild_id, discord_guild_name
                FROM events {where}
                ORDER BY event_date DESC, event_time DESC, id DESC LIMIT ?""",
                params).fetchall()
            if not events:
                return [], []
            event_ids = [event["event_id"] for event in events]
            placeholders = ",".join("?" for _ in event_ids)
            results = connection.execute(f"""SELECT player_results.event_id,
                players.canonical_name AS player_name, player_results.rank,
                player_results.damage, events.discord_guild_id,
                events.discord_guild_name
                FROM player_results
                JOIN players ON players.id = player_results.player_id
                JOIN events ON events.id = player_results.event_id
                WHERE player_results.event_id IN ({placeholders})
                ORDER BY player_results.event_id DESC, player_results.rank""",
                event_ids).fetchall()
            return events, results
        finally: connection.close()
    def fetch_cached_recap(self, cache_key):
        connection = self.connect(); connection.row_factory = sqlite3.Row
        try:
            return connection.execute(
                "SELECT * FROM bear_recap_cache WHERE cache_key = ?",
                (cache_key,)
            ).fetchone()
        finally: connection.close()
    def save_cached_recap(self, cache_key, model, event_count, recap_text):
        connection = self.connect()
        try:
            connection.execute("""INSERT OR REPLACE INTO bear_recap_cache
                (cache_key, model, event_count, recap_text, created_at)
                VALUES (?, ?, ?, ?, ?)""", (
                cache_key, model, event_count, recap_text,
                datetime.now(timezone.utc).isoformat(timespec="seconds")
            ))
            connection.commit()
        finally: connection.close()
