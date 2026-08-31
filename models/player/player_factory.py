import difflib
import sqlite3
import unicodedata
from datetime import datetime, timezone
from .player_model import PlayerModel

class PlayerFactory:
    def __init__(self, connection_factory): self._connection_factory = connection_factory
    @staticmethod
    def normalize_name(name): return " ".join(unicodedata.normalize("NFKC", name).casefold().split())
    @classmethod
    def visual_key(cls, name):
        return cls.normalize_name(name).translate(str.maketrans({"o":"0", "i":"1", "l":"1"}))
    def setup_schema(self):
        connection = self._connection_factory()
        try:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS players (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS player_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER NOT NULL,
                    alias_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL UNIQUE,
                    visual_key TEXT NOT NULL,
                    FOREIGN KEY (player_id) REFERENCES players(id)
                );
            """)
            connection.commit()
        finally: connection.close()
    def _to_model(self, row): return PlayerModel(row["id"], row["canonical_name"], row["created_at"], row["updated_at"])
    def _lookup(self, connection, sql, values):
        connection.row_factory = sqlite3.Row
        row = connection.execute(sql, values).fetchone()
        return self._to_model(row) if row else None
    def resolve_player_model(self, parsed_name, connection):
        normalized = self.normalize_name(parsed_name)
        player = self._lookup(connection, """SELECT players.* FROM players JOIN player_aliases ON player_aliases.player_id = players.id WHERE player_aliases.normalized_name = ?""", (normalized,))
        if player: return player
        key = self.visual_key(parsed_name)
        rows = connection.execute("SELECT DISTINCT player_id FROM player_aliases WHERE visual_key = ?", (key,)).fetchall()
        if len(rows) == 1:
            player = self.get_player_model_by_player_id(rows[0][0], connection)
            self._add_alias(player.get_player_id(), parsed_name, connection)
            return player
        candidates = connection.execute("SELECT player_id, alias_name FROM player_aliases").fetchall()
        scores = [(difflib.SequenceMatcher(None, key, self.visual_key(row[1])).ratio(), row[0]) for row in candidates]
        scores.sort(reverse=True)
        if scores and scores[0][0] >= 0.92 and (len(scores) == 1 or scores[0][0] - scores[1][0] >= 0.04):
            player = self.get_player_model_by_player_id(scores[0][1], connection)
            self._add_alias(player.get_player_id(), parsed_name, connection)
            return player
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cursor = connection.execute("INSERT INTO players (canonical_name, created_at, updated_at) VALUES (?, ?, ?)", (parsed_name, now, now))
        player = PlayerModel(cursor.lastrowid, parsed_name, now, now)
        self._add_alias(player.get_player_id(), parsed_name, connection)
        return player
    def _add_alias(self, player_id, alias_name, connection):
        connection.execute("INSERT OR IGNORE INTO player_aliases (player_id, alias_name, normalized_name, visual_key) VALUES (?, ?, ?, ?)", (player_id, alias_name, self.normalize_name(alias_name), self.visual_key(alias_name)))
    def get_player_model_by_player_id(self, player_id, connection=None):
        own = connection is None; connection = connection or self._connection_factory()
        try: return self._lookup(connection, "SELECT * FROM players WHERE id = ?", (player_id,))
        finally:
            if own: connection.close()
    def rename_player(self, old_name, new_name):
        connection = self._connection_factory()
        try:
            player = self._lookup(connection, """SELECT players.* FROM players JOIN player_aliases ON player_aliases.player_id = players.id WHERE player_aliases.normalized_name = ?""", (self.normalize_name(old_name),))
            if not player: raise ValueError(f"No player identity found for {old_name}.")
            existing = self._lookup(connection, """SELECT players.* FROM players JOIN player_aliases ON player_aliases.player_id = players.id WHERE player_aliases.normalized_name = ?""", (self.normalize_name(new_name),))
            if existing and existing.get_player_id() != player.get_player_id(): raise ValueError("The new name already belongs to a different player.")
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            connection.execute("UPDATE players SET canonical_name = ?, updated_at = ? WHERE id = ?", (new_name, now, player.get_player_id()))
            self._add_alias(player.get_player_id(), new_name, connection)
            connection.commit(); player.set_canonical_name(new_name); player.set_updated_at(now); return player
        finally: connection.close()

    def get_player_models(self, limit=100):
        connection = self._connection_factory(); connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                "SELECT * FROM players ORDER BY canonical_name ASC LIMIT ?",
                (limit,)
            ).fetchall()
            return [self._to_model(row) for row in rows]
        finally: connection.close()
