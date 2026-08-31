import sqlite3
from .player_result_model import PlayerResultModel
class PlayerResultFactory:
    def __init__(self, connection_factory): self._connection_factory = connection_factory
    def setup_schema(self):
        connection = self._connection_factory()
        try:
            connection.execute("""CREATE TABLE IF NOT EXISTS player_results (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, player_id INTEGER, rank INTEGER NOT NULL, player_name TEXT NOT NULL, damage INTEGER NOT NULL, uncertain INTEGER NOT NULL DEFAULT 0, FOREIGN KEY (event_id) REFERENCES events(id), FOREIGN KEY (player_id) REFERENCES players(id))""")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(player_results)")}
            if "player_id" not in columns: connection.execute("ALTER TABLE player_results ADD COLUMN player_id INTEGER")
            if "uncertain" not in columns: connection.execute("ALTER TABLE player_results ADD COLUMN uncertain INTEGER NOT NULL DEFAULT 0")
            connection.commit()
        finally: connection.close()
    def get_player_result_models_by_event_id(self, event_id):
        connection = self._connection_factory(); connection.row_factory = sqlite3.Row
        try:
            return [PlayerResultModel(row["id"], row["event_id"], row["player_id"], row["rank"], row["player_name"], row["damage"], row["uncertain"]) for row in connection.execute("SELECT * FROM player_results WHERE event_id = ? ORDER BY rank", (event_id,))]
        finally: connection.close()
    def replace_player_result_models_by_event_id(self, event_id, models, connection):
        connection.execute("DELETE FROM player_results WHERE event_id = ?", (event_id,))
        connection.executemany("INSERT INTO player_results (event_id, player_id, rank, player_name, damage, uncertain) VALUES (?, ?, ?, ?, ?, ?)", [(event_id, model.get_player_id(), model.get_rank(), model.get_raw_player_name(), model.get_damage(), int(model.get_uncertain())) for model in models])
    def get_leaderboard_rows(self, channel_id, limit):
        connection = self._connection_factory(); connection.row_factory = sqlite3.Row
        try: return connection.execute("""SELECT players.canonical_name AS player_name, COUNT(*) AS appearances, SUM(damage) AS total_damage, AVG(damage) AS average_damage, MAX(damage) AS best_damage FROM player_results JOIN events ON events.id = player_results.event_id JOIN players ON players.id = player_results.player_id WHERE events.discord_channel_id = ? GROUP BY players.id ORDER BY total_damage DESC, average_damage DESC, player_name ASC LIMIT ?""", (str(channel_id), limit)).fetchall()
        finally: connection.close()
    def get_player_search_rows(self, channel_id, search_text):
        connection = self._connection_factory(); connection.row_factory = sqlite3.Row; pattern = f"%{search_text}%"
        try:
            names = connection.execute("""SELECT players.canonical_name AS player_name, COUNT(*) AS appearances, AVG(damage) AS average_damage, MAX(damage) AS best_damage FROM player_results JOIN events ON events.id = player_results.event_id JOIN players ON players.id = player_results.player_id WHERE events.discord_channel_id = ? AND players.canonical_name LIKE ? COLLATE NOCASE GROUP BY players.id ORDER BY appearances DESC, player_name ASC LIMIT 10""", (str(channel_id), pattern)).fetchall()
            history = connection.execute("""SELECT events.event_type, events.event_date, events.event_time, players.canonical_name AS player_name, player_results.rank, player_results.damage, player_results.uncertain FROM player_results JOIN events ON events.id = player_results.event_id JOIN players ON players.id = player_results.player_id WHERE events.discord_channel_id = ? AND players.canonical_name LIKE ? COLLATE NOCASE ORDER BY events.created_at DESC, events.id DESC, player_results.rank ASC LIMIT 10""", (str(channel_id), pattern)).fetchall(); return names, history
        finally: connection.close()
