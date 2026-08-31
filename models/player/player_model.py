class PlayerModel:
    def __init__(self, player_id=None, canonical_name=None, created_at=None, updated_at=None, event_count=0):
        self._player_id = player_id
        self._canonical_name = canonical_name
        self._created_at = created_at
        self._updated_at = updated_at
        self._event_count = event_count
    def get_player_id(self): return self._player_id
    def get_canonical_name(self): return self._canonical_name
    def get_created_at(self): return self._created_at
    def get_updated_at(self): return self._updated_at
    def get_event_count(self): return self._event_count
    def set_player_id(self, value): self._player_id = value
    def set_canonical_name(self, value): self._canonical_name = value
    def set_created_at(self, value): self._created_at = value
    def set_updated_at(self, value): self._updated_at = value
    def set_event_count(self, value): self._event_count = value
