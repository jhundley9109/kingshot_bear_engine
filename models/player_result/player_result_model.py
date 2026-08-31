class PlayerResultModel:
    def __init__(self, player_result_id=None, event_id=None, player_id=None, rank=None, raw_player_name=None, damage=None, uncertain=False):
        self._player_result_id, self._event_id, self._player_id = player_result_id, event_id, player_id
        self._rank, self._raw_player_name, self._damage, self._uncertain = rank, raw_player_name, damage, bool(uncertain)
    def get_player_result_id(self): return self._player_result_id
    def get_event_id(self): return self._event_id
    def get_player_id(self): return self._player_id
    def get_rank(self): return self._rank
    def get_raw_player_name(self): return self._raw_player_name
    def get_damage(self): return self._damage
    def get_uncertain(self): return self._uncertain
    def set_event_id(self, value): self._event_id = value
    def set_player_id(self, value): self._player_id = value
