import os
import sqlite3
from datetime import datetime, timezone

from models.event import EventFactory, EventModel
from models.player import PlayerFactory
from models.player_result import PlayerResultFactory, PlayerResultModel

class BearTrapRepository:
    def __init__(self, database_path):
        self.database_path = database_path
        self.event_factory = EventFactory(self.connect)
        self.player_factory = PlayerFactory(self.connect)
        self.player_result_factory = PlayerResultFactory(self.connect)
    def connect(self): return sqlite3.connect(self.database_path)
    def setup(self):
        directory = os.path.dirname(self.database_path)
        if directory: os.makedirs(directory, exist_ok=True)
        self.event_factory.setup_schema(); self.player_factory.setup_schema(); self.player_result_factory.setup_schema(); self._setup_recap_cache_schema(); self._backfill_player_ids()
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
    def _backfill_player_ids(self):
        connection = self.connect(); connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute("SELECT id, player_name FROM player_results WHERE player_id IS NULL").fetchall()
            for row in rows:
                player = self.player_factory.resolve_player_model(row["player_name"], connection)
                connection.execute("UPDATE player_results SET player_id = ? WHERE id = ?", (player.get_player_id(), row["id"]))
            connection.commit()
        finally: connection.close()
    def find_existing_report(self, data, source_message):
        event=self.event_factory.find_duplicate_event_model(data, source_message)
        return event.get_event_id() if event else None
    def _event_model(self, data, source_message, submitted_by, submitted_at, event_id=None):
        submitted_at=submitted_at or datetime.now(timezone.utc)
        return EventModel(event_id=event_id, event_type=data.get("event_type") or "Unknown Bear Trap", event_date=data.get("event_date") or submitted_at.date().isoformat(), event_time=data.get("event_time") or submitted_at.time().replace(microsecond=0).isoformat(), rallies=data.get("rallies"), alliance_damage=data.get("alliance_damage"), submitted_by=str(submitted_by), discord_message_id=str(source_message.id), discord_channel_id=str(source_message.channel.id), discord_channel_name=getattr(source_message.channel, "name", None), created_at=submitted_at.isoformat(timespec="seconds"))
    def write_result(self, data, players, source_message, submitted_by, submitted_at=None, existing_event_id=None):
        if not players: raise ValueError("Cannot save a result with no player rankings.")
        connection=self.connect()
        try:
            event=self.event_factory.save_event_model(self._event_model(data, source_message, submitted_by, submitted_at, existing_event_id), connection)
            results=[]
            for player in players:
                identity=self.player_factory.resolve_player_model(player["player_name"], connection)
                results.append(PlayerResultModel(event_id=event.get_event_id(), player_id=identity.get_player_id(), rank=player["rank"], raw_player_name=player["player_name"], damage=player["damage"], uncertain=player.get("uncertain", False)))
            self.player_result_factory.replace_player_result_models_by_event_id(event.get_event_id(), results, connection)
            connection.commit(); return event.get_event_id()
        except Exception:
            connection.rollback(); raise
        finally: connection.close()
    def save_result(self, data, players, source_message, submitted_by, submitted_at=None): return self.write_result(data, players, source_message, submitted_by, submitted_at)
    def replace_result(self, existing_event_id, data, players, source_message, submitted_by, submitted_at=None): return self.write_result(data, players, source_message, submitted_by, submitted_at, existing_event_id)
    def rename_player(self, old_name, new_name): return self.player_factory.rename_player(old_name, new_name)
    def fetch_players(self, limit=100): return self.player_factory.get_player_models(limit)
    def fetch_latest_summary(self, channel_id=None):
        event=self.event_factory.get_latest_event_model_by_channel_id(channel_id)
        return (event, self.player_result_factory.get_player_result_models_by_event_id(event.get_event_id())) if event else (None, [])
    def fetch_leaderboard(self, channel_id, limit): return self.player_result_factory.get_leaderboard_rows(channel_id, limit)
    def fetch_event_trend(self, channel_id, since_date): return self.event_factory.get_event_trend_rows(channel_id, since_date)
    def fetch_events(self, channel_id=None, limit=50): return self.event_factory.get_event_models_by_channel_id(channel_id, limit)
    def fetch_event_details(self, event_id, channel_id=None):
        event = self.event_factory.get_event_model_by_event_id(event_id)
        if event is None or (channel_id is not None and event.get_discord_channel_id() != str(channel_id)): return None, []
        return event, self.player_result_factory.get_player_result_models_by_event_id(event_id)
    def delete_event(self, event_id, channel_id=None):
        connection = self.connect()
        try:
            event = self.event_factory.get_event_model_by_event_id(event_id, connection)
            if event is None or (channel_id is not None and event.get_discord_channel_id() != str(channel_id)):
                raise ValueError("No event with that ID exists in this channel.")
            self.player_result_factory.delete_player_result_models_by_event_id(event_id, connection)
            self.event_factory.delete_event_model_by_id(event_id, connection)
            connection.commit(); return event
        except Exception:
            connection.rollback(); raise
        finally: connection.close()
    def fetch_player_history(self, channel_id, search_text): return self.player_result_factory.get_player_search_rows(channel_id, search_text)
    def fetch_player_stats(self, channel_id, player_name): return self.player_result_factory.get_player_stats_rows(channel_id, player_name)
    def fetch_player_trend(self, channel_id, search_text, since_date): return self.player_result_factory.get_player_trend_rows(channel_id, search_text, since_date)
    def fetch_recap_source(self, channel_id, event_count=5):
        connection = self.connect(); connection.row_factory = sqlite3.Row
        try:
            where = ""
            params = []
            if channel_id is not None:
                where = "WHERE discord_channel_id = ?"
                params.append(str(channel_id))
            params.append(event_count)
            events = connection.execute(f"""SELECT id AS event_id, event_type,
                event_date, event_time, alliance_damage, discord_channel_name
                FROM events {where}
                ORDER BY event_date DESC, event_time DESC, id DESC LIMIT ?""",
                params).fetchall()
            if not events:
                return [], []
            event_ids = [event["event_id"] for event in events]
            placeholders = ",".join("?" for _ in event_ids)
            results = connection.execute(f"""SELECT player_results.event_id,
                players.canonical_name AS player_name, player_results.rank,
                player_results.damage
                FROM player_results
                JOIN players ON players.id = player_results.player_id
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
