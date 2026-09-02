import difflib
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from .player_model import PlayerModel

class PlayerFactory:
    def __init__(self, connection_factory): self._connection_factory = connection_factory
    @staticmethod
    def normalize_name(name):
        normalized = unicodedata.normalize("NFKC", name).casefold()
        normalized = re.sub(r"^\s*(\[[^\]]{1,12}\]\s*)+", "", normalized)
        return " ".join(normalized.split())
    @staticmethod
    def legacy_normalize_name(name):
        return " ".join(unicodedata.normalize("NFKC", name).casefold().split())
    @classmethod
    def visual_key(cls, name):
        return cls.normalize_name(name).translate(str.maketrans({"o":"0", "i":"1", "l":"1"}))
    @classmethod
    def legacy_visual_key(cls, name):
        return cls.legacy_normalize_name(name).translate(str.maketrans({"o":"0", "i":"1", "l":"1"}))
    def setup_schema(self, legacy_guild_id=None):
        connection = self._connection_factory()
        try:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS players (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_name TEXT NOT NULL,
                    guild_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS player_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_id INTEGER NOT NULL,
                    alias_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    visual_key TEXT NOT NULL,
                    guild_id TEXT NOT NULL,
                    FOREIGN KEY (player_id) REFERENCES players(id),
                    UNIQUE(guild_id, normalized_name)
                );
            """)
            player_columns = {row[1] for row in connection.execute("PRAGMA table_info(players)")}
            alias_columns = {row[1] for row in connection.execute("PRAGMA table_info(player_aliases)")}
            if "guild_id" not in player_columns:
                connection.execute("ALTER TABLE players ADD COLUMN guild_id TEXT")
            if "guild_id" not in alias_columns:
                connection.execute("ALTER TABLE player_aliases ADD COLUMN guild_id TEXT")
            if legacy_guild_id is not None:
                connection.execute("UPDATE players SET guild_id = ? WHERE guild_id IS NULL", (str(legacy_guild_id),))
                connection.execute("""UPDATE player_aliases SET guild_id = (
                    SELECT guild_id FROM players WHERE players.id = player_aliases.player_id
                ) WHERE guild_id IS NULL""")
            alias_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'player_aliases'"
            ).fetchone()[0]
            compact_sql = "".join(alias_sql.lower().split())
            if "unique(guild_id,normalized_name)" not in compact_sql:
                connection.executescript("""
                    ALTER TABLE player_aliases RENAME TO player_aliases_legacy;
                    CREATE TABLE player_aliases (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        player_id INTEGER NOT NULL,
                        alias_name TEXT NOT NULL,
                        normalized_name TEXT NOT NULL,
                        visual_key TEXT NOT NULL,
                        guild_id TEXT NOT NULL,
                        FOREIGN KEY (player_id) REFERENCES players(id),
                        UNIQUE(guild_id, normalized_name)
                    );
                    INSERT INTO player_aliases
                        (id, player_id, alias_name, normalized_name, visual_key, guild_id)
                    SELECT id, player_id, alias_name, normalized_name, visual_key, guild_id
                    FROM player_aliases_legacy;
                    DROP TABLE player_aliases_legacy;
                """)
            connection.commit()
        finally: connection.close()
    def _to_model(self, row):
        event_count = row["event_count"] if "event_count" in row.keys() else 0
        return PlayerModel(
            row["id"],
            row["canonical_name"],
            row["created_at"],
            row["updated_at"],
            event_count
        )
    def _lookup(self, connection, sql, values):
        connection.row_factory = sqlite3.Row
        row = connection.execute(sql, values).fetchone()
        return self._to_model(row) if row else None
    def resolve_player_model(self, parsed_name, connection, guild_id):
        guild_id = str(guild_id)
        normalized = self.normalize_name(parsed_name)
        player = self._lookup(connection, """SELECT players.* FROM players JOIN player_aliases ON player_aliases.player_id = players.id WHERE player_aliases.guild_id = ? AND player_aliases.normalized_name = ?""", (guild_id, normalized))
        if player: return player
        legacy_normalized = self.legacy_normalize_name(parsed_name)
        if legacy_normalized != normalized:
            player = self._lookup(connection, """SELECT players.* FROM players JOIN player_aliases ON player_aliases.player_id = players.id WHERE player_aliases.guild_id = ? AND player_aliases.normalized_name = ?""", (guild_id, legacy_normalized))
            if player:
                self._add_alias(player.get_player_id(), parsed_name, guild_id, connection)
                return player
        key = self.visual_key(parsed_name)
        rows = connection.execute("SELECT DISTINCT player_id FROM player_aliases WHERE guild_id = ? AND visual_key = ?", (guild_id, key)).fetchall()
        if len(rows) == 1:
            player = self.get_player_model_by_player_id(rows[0][0], connection)
            self._add_alias(player.get_player_id(), parsed_name, guild_id, connection)
            return player
        legacy_key = self.legacy_visual_key(parsed_name)
        if legacy_key != key:
            rows = connection.execute("SELECT DISTINCT player_id FROM player_aliases WHERE guild_id = ? AND visual_key = ?", (guild_id, legacy_key)).fetchall()
            if len(rows) == 1:
                player = self.get_player_model_by_player_id(rows[0][0], connection)
                self._add_alias(player.get_player_id(), parsed_name, guild_id, connection)
                return player
        candidates = connection.execute("SELECT player_id, alias_name FROM player_aliases WHERE guild_id = ?", (guild_id,)).fetchall()
        scores = [(difflib.SequenceMatcher(None, key, self.visual_key(row[1])).ratio(), row[0]) for row in candidates]
        scores.sort(reverse=True)
        if scores and scores[0][0] >= 0.92 and (len(scores) == 1 or scores[0][0] - scores[1][0] >= 0.04):
            player = self.get_player_model_by_player_id(scores[0][1], connection)
            self._add_alias(player.get_player_id(), parsed_name, guild_id, connection)
            return player
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cursor = connection.execute("INSERT INTO players (canonical_name, guild_id, created_at, updated_at) VALUES (?, ?, ?, ?)", (parsed_name, guild_id, now, now))
        player = PlayerModel(cursor.lastrowid, parsed_name, now, now)
        self._add_alias(player.get_player_id(), parsed_name, guild_id, connection)
        return player
    def _add_alias(self, player_id, alias_name, guild_id, connection):
        connection.execute("INSERT OR IGNORE INTO player_aliases (player_id, alias_name, normalized_name, visual_key, guild_id) VALUES (?, ?, ?, ?, ?)", (player_id, alias_name, self.normalize_name(alias_name), self.visual_key(alias_name), str(guild_id)))
    def get_player_model_by_player_id(self, player_id, connection=None):
        own = connection is None; connection = connection or self._connection_factory()
        try: return self._lookup(connection, "SELECT * FROM players WHERE id = ?", (player_id,))
        finally:
            if own: connection.close()
    def rename_player(self, old_name, new_name, guild_id):
        connection = self._connection_factory()
        try:
            player = self._lookup(connection, """SELECT players.* FROM players JOIN player_aliases ON player_aliases.player_id = players.id WHERE player_aliases.guild_id = ? AND player_aliases.normalized_name = ?""", (str(guild_id), self.normalize_name(old_name)))
            if not player: raise ValueError(f"No player identity found for {old_name}.")
            existing = self._lookup(connection, """SELECT players.* FROM players JOIN player_aliases ON player_aliases.player_id = players.id WHERE player_aliases.guild_id = ? AND player_aliases.normalized_name = ?""", (str(guild_id), self.normalize_name(new_name)))
            if existing and existing.get_player_id() != player.get_player_id(): raise ValueError("The new name already belongs to a different player.")
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            connection.execute("UPDATE players SET canonical_name = ?, updated_at = ? WHERE id = ?", (new_name, now, player.get_player_id()))
            self._add_alias(player.get_player_id(), new_name, guild_id, connection)
            connection.commit(); player.set_canonical_name(new_name); player.set_updated_at(now); return player
        finally: connection.close()

    def get_player_models(self, guild_id, limit=100):
        connection = self._connection_factory(); connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """SELECT players.*, COUNT(DISTINCT player_results.event_id) AS event_count
                   FROM players
                   LEFT JOIN player_results ON player_results.player_id = players.id
                   WHERE players.guild_id = ?
                   GROUP BY players.id
                   ORDER BY players.canonical_name ASC
                   LIMIT ?""",
                (str(guild_id), limit)
            ).fetchall()
            return [self._to_model(row) for row in rows]
        finally: connection.close()
