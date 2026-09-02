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
    def get_leaderboard_rows(self, channel_id, guild_id, limit=None):
        connection = self._connection_factory(); connection.row_factory = sqlite3.Row
        try:
            event_total_where = ""
            result_where = ""
            params = []
            event_clauses = []; result_clauses = []; scope_params = []
            if guild_id is not None:
                event_clauses.append("discord_guild_id = ?")
                result_clauses.append("events.discord_guild_id = ?")
                scope_params.append(str(guild_id))
            if channel_id is not None:
                event_clauses.append("discord_channel_id = ?")
                result_clauses.append("events.discord_channel_id = ?")
                scope_params.append(str(channel_id))
            if event_clauses:
                event_total_where = "WHERE " + " AND ".join(event_clauses)
                result_where = "WHERE " + " AND ".join(result_clauses)
                params.extend(scope_params + scope_params)
            sql = """SELECT players.canonical_name AS player_name,
                COUNT(DISTINCT player_results.event_id) AS appearances,
                SUM(damage) AS total_damage,
                AVG(damage) AS average_damage,
                MAX(damage) AS best_damage,
                event_totals.total_events AS total_events
                FROM player_results
                JOIN events ON events.id = player_results.event_id
                JOIN players ON players.id = player_results.player_id
                CROSS JOIN (
                    SELECT COUNT(*) AS total_events
                    FROM events
                    {event_total_where}
                ) event_totals
                {result_where}
                GROUP BY players.id
                ORDER BY total_damage DESC, average_damage DESC, player_name ASC""".format(
                    event_total_where=event_total_where,
                    result_where=result_where
                )
            if limit is not None:
                sql += " LIMIT ?"
                params.append(limit)
            return connection.execute(sql, params).fetchall()
        finally: connection.close()
    def get_player_search_rows(self, channel_id, guild_id, search_text):
        connection = self._connection_factory(); connection.row_factory = sqlite3.Row; pattern = f"%{search_text}%"
        try:
            where = "players.canonical_name LIKE ? COLLATE NOCASE"
            params = [pattern]
            if guild_id is not None:
                where = "events.discord_guild_id = ? AND " + where
                params.insert(0, str(guild_id))
            if channel_id is not None:
                where = "events.discord_channel_id = ? AND " + where
                params.insert(0, str(channel_id))
            names = connection.execute(f"""SELECT players.canonical_name AS player_name,
                COUNT(DISTINCT player_results.event_id) AS appearances,
                AVG(damage) AS average_damage, MAX(damage) AS best_damage
                FROM player_results
                JOIN events ON events.id = player_results.event_id
                JOIN players ON players.id = player_results.player_id
                WHERE {where}
                GROUP BY players.id
                ORDER BY appearances DESC, player_name ASC LIMIT 10""", params).fetchall()
            history = connection.execute(f"""SELECT events.event_type,
                events.event_date, events.event_time, events.discord_channel_name,
                events.discord_guild_id, events.discord_guild_name,
                players.canonical_name AS player_name, player_results.rank,
                player_results.damage, player_results.uncertain
                FROM player_results
                JOIN events ON events.id = player_results.event_id
                JOIN players ON players.id = player_results.player_id
                WHERE {where}
                ORDER BY events.created_at DESC, events.id DESC,
                player_results.rank ASC LIMIT 10""", params).fetchall(); return names, history
        finally: connection.close()

    def get_player_stats_rows(self, channel_id, guild_id, player_name):
        connection = self._connection_factory(); connection.row_factory = sqlite3.Row
        try:
            normalized_name = self._normalize_player_name(player_name)
            match_where = """(player_aliases.normalized_name = ?
                      OR players.canonical_name = ? COLLATE NOCASE)"""
            match_params = [normalized_name, player_name.strip()]
            if guild_id is not None:
                match_where = "player_aliases.guild_id = ? AND " + match_where
                match_params.insert(0, str(guild_id))
            matches = connection.execute(
                """SELECT DISTINCT players.id, players.canonical_name
                   FROM players
                   JOIN player_aliases ON player_aliases.player_id = players.id
                   WHERE {match_where}
                   ORDER BY players.canonical_name ASC""".format(match_where=match_where),
                match_params
            ).fetchall()
            if not matches:
                return None, []

            player_ids = [match["id"] for match in matches]
            placeholders = ",".join("?" for _ in player_ids)
            where = f"player_results.player_id IN ({placeholders})"
            params = list(player_ids)
            if guild_id is not None:
                where += " AND events.discord_guild_id = ?"
                params.append(str(guild_id))
            if channel_id is not None:
                where += " AND events.discord_channel_id = ?"
                params.append(str(channel_id))

            summary = connection.execute(
                f"""SELECT players.canonical_name AS player_name,
                    COUNT(DISTINCT player_results.event_id) AS appearances,
                    COALESCE(SUM(player_results.damage), 0) AS total_damage,
                    COALESCE(AVG(player_results.damage), 0) AS average_damage,
                    COALESCE(MAX(player_results.damage), 0) AS best_damage,
                    COALESCE(MIN(player_results.rank), 0) AS best_rank
                    FROM player_results
                    JOIN events ON events.id = player_results.event_id
                    JOIN players ON players.id = player_results.player_id
                    WHERE {where}
                    """,
                params
            ).fetchone()
            if summary is None:
                return None, []

            history = connection.execute(
                f"""SELECT events.id AS event_id, events.event_type,
                    events.event_date, events.event_time,
                    events.discord_channel_name, events.discord_guild_id,
                    events.discord_guild_name, player_results.rank,
                    player_results.damage, player_results.uncertain
                    FROM player_results
                    JOIN events ON events.id = player_results.event_id
                    WHERE {where}
                    ORDER BY events.event_date DESC, events.event_time DESC,
                    events.id DESC""",
                params
            ).fetchall()
            return summary, history
        finally: connection.close()

    @staticmethod
    def _normalize_player_name(name):
        # Kept in sync with PlayerFactory.normalize_name without coupling the
        # result factory to the player factory instance.
        import re
        import unicodedata
        normalized = unicodedata.normalize("NFKC", name).casefold()
        normalized = re.sub(r"^\s*(\[[^\]]{1,12}\]\s*)+", "", normalized)
        return " ".join(normalized.split())

    def get_player_trend_rows(self, channel_id, guild_id, search_text, since_date):
        connection = self._connection_factory(); connection.row_factory = sqlite3.Row
        try:
            pattern = f"%{search_text}%"
            where = """players.canonical_name LIKE ? COLLATE NOCASE
                  AND events.event_date >= ?"""
            params = [pattern, since_date]
            if guild_id is not None:
                where = "events.discord_guild_id = ? AND " + where
                params.insert(0, str(guild_id))
            if channel_id is not None:
                where = "events.discord_channel_id = ? AND " + where
                params.insert(0, str(channel_id))
            return connection.execute(f"""SELECT players.canonical_name AS player_name,
                events.event_date, events.event_time, events.discord_channel_name,
                player_results.damage
                FROM player_results JOIN events ON events.id = player_results.event_id
                JOIN players ON players.id = player_results.player_id
                WHERE {where}
                ORDER BY players.canonical_name, events.event_date, events.event_time, events.id""",
                params).fetchall()
        finally: connection.close()

    def delete_player_result_models_by_event_id(self, event_id, connection):
        connection.execute("DELETE FROM player_results WHERE event_id = ?", (event_id,))
