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
        self.event_factory.setup_schema(); self.player_factory.setup_schema(); self.player_result_factory.setup_schema(); self._backfill_player_ids()
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
    def fetch_latest_summary(self, channel_id):
        event=self.event_factory.get_latest_event_model_by_channel_id(channel_id)
        return (event, self.player_result_factory.get_player_result_models_by_event_id(event.get_event_id())) if event else (None, [])
    def fetch_leaderboard(self, channel_id, limit): return self.player_result_factory.get_leaderboard_rows(channel_id, limit)
    def fetch_event_trend(self, channel_id, since_date): return self.event_factory.get_event_trend_rows(channel_id, since_date)
    def fetch_player_history(self, channel_id, search_text): return self.player_result_factory.get_player_search_rows(channel_id, search_text)
    def fetch_player_trend(self, channel_id, search_text, since_date): return self.player_result_factory.get_player_trend_rows(channel_id, search_text, since_date)
