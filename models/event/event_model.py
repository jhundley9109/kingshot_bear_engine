class EventModel:

    def __init__(
        self,
        event_id=None,
        event_type=None,
        event_date=None,
        event_time=None,
        rallies=None,
        alliance_damage=None,
        submitted_by=None,
        discord_message_id=None,
        discord_channel_id=None,
        discord_channel_name=None,
        discord_guild_id=None,
        discord_guild_name=None,
        created_at=None
    ):
        self._event_id = event_id
        self._event_type = event_type
        self._event_date = event_date
        self._event_time = event_time
        self._rallies = rallies
        self._alliance_damage = alliance_damage
        self._submitted_by = submitted_by
        self._discord_message_id = discord_message_id
        self._discord_channel_id = discord_channel_id
        self._discord_channel_name = discord_channel_name
        self._discord_guild_id = discord_guild_id
        self._discord_guild_name = discord_guild_name
        self._created_at = created_at

    def get_event_id(self): return self._event_id
    def get_event_type(self): return self._event_type
    def get_event_date(self): return self._event_date
    def get_event_time(self): return self._event_time
    def get_rallies(self): return self._rallies
    def get_alliance_damage(self): return self._alliance_damage
    def get_submitted_by(self): return self._submitted_by
    def get_discord_message_id(self): return self._discord_message_id
    def get_discord_channel_id(self): return self._discord_channel_id
    def get_discord_channel_name(self): return self._discord_channel_name
    def get_discord_guild_id(self): return self._discord_guild_id
    def get_discord_guild_name(self): return self._discord_guild_name
    def get_created_at(self): return self._created_at

    def set_event_id(self, value): self._event_id = value
    def set_event_type(self, value): self._event_type = value
    def set_event_date(self, value): self._event_date = value
    def set_event_time(self, value): self._event_time = value
    def set_rallies(self, value): self._rallies = value
    def set_alliance_damage(self, value): self._alliance_damage = value
    def set_submitted_by(self, value): self._submitted_by = value
    def set_discord_message_id(self, value): self._discord_message_id = value
    def set_discord_channel_id(self, value): self._discord_channel_id = value
    def set_discord_channel_name(self, value): self._discord_channel_name = value
    def set_discord_guild_id(self, value): self._discord_guild_id = value
    def set_discord_guild_name(self, value): self._discord_guild_name = value
    def set_created_at(self, value): self._created_at = value
