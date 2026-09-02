import asyncio

import discord


class RequesterOnlyView(discord.ui.View):
    def __init__(self, requested_by, unauthorized_message, timeout=900):
        super().__init__(timeout=timeout)
        self.requested_by = requested_by
        self.unauthorized_message = unauthorized_message

    async def interaction_check(self, interaction):
        if interaction.user.id != self.requested_by:
            await interaction.response.send_message(
                self.unauthorized_message,
                ephemeral=True,
            )
            return False
        return True

    def disable_buttons(self):
        for child in self.children:
            child.disabled = True

    async def on_timeout(self):
        self.disable_buttons()


class BearTrapReviewView(RequesterOnlyView):
    def __init__(
        self,
        repository,
        data,
        players,
        source_message,
        submitted_by,
        submitted_at,
        existing_event_id=None,
    ):
        super().__init__(
            requested_by=submitted_by,
            unauthorized_message=(
                "❌ Only the person who requested this preview can approve or "
                "reject it."
            ),
        )
        self.repository = repository
        self.data = data
        self.players = players
        self.source_message = source_message
        self.submitted_at = submitted_at
        self.existing_event_id = existing_event_id
        self.completed = False
        self.replace_existing.disabled = existing_event_id is None

    async def save_review(self, interaction, replace_existing=False):
        if self.completed:
            await interaction.response.send_message(
                "This review has already been completed.", ephemeral=True
            )
            return
        if self.existing_event_id and not replace_existing:
            await interaction.response.send_message(
                "⚠️ This matches an existing saved report. Use **Replace existing report** "
                "to overwrite it, or Reject to discard this preview.",
                ephemeral=True,
            )
            return

        self.completed = True
        self.disable_buttons()
        try:
            if replace_existing:
                event_id = await asyncio.to_thread(
                    self.repository.replace_result,
                    self.existing_event_id,
                    self.data,
                    self.players,
                    self.source_message,
                    interaction.user.id,
                    self.submitted_at,
                )
                action = "replaced"
            else:
                event_id = await asyncio.to_thread(
                    self.repository.save_result,
                    self.data,
                    self.players,
                    self.source_message,
                    interaction.user.id,
                    self.submitted_at,
                )
                action = "saved"
        except Exception as error:
            self.completed = False
            for child in self.children:
                child.disabled = False
            self.replace_existing.disabled = self.existing_event_id is None
            print("Error saving Bear Trap result:")
            print(error)
            await interaction.response.edit_message(
                content=(
                    "❌ I couldn't save this result. No data was written; "
                    "check the bot's terminal and try again."
                ),
                view=self,
            )
            return

        await interaction.response.edit_message(
            content=(
                f"✅ **Bear Trap result {action}!**\n"
                f"Event ID: **{event_id}**\n"
                f"Player rankings saved: **{len(self.players)}**"
            ),
            view=self,
        )

    @discord.ui.button(label="Approve & Save", style=discord.ButtonStyle.success)
    async def approve(self, interaction, button):
        await self.save_review(interaction)

    @discord.ui.button(
        label="Replace existing report", style=discord.ButtonStyle.secondary
    )
    async def replace_existing(self, interaction, button):
        await self.save_review(interaction, replace_existing=True)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger)
    async def reject(self, interaction, button):
        if self.completed:
            await interaction.response.send_message(
                "This review has already been completed.", ephemeral=True
            )
            return
        self.completed = True
        self.disable_buttons()
        await interaction.response.edit_message(
            content="🗑️ **Bear Trap result rejected.** Nothing was saved.",
            view=self,
        )


class EventDeleteView(RequesterOnlyView):
    def __init__(
        self, repository, event_id, channel_id, guild_id, requested_by
    ):
        super().__init__(
            requested_by=requested_by,
            unauthorized_message=(
                "❌ Only the user who requested this deletion can confirm it."
            ),
        )
        self.repository = repository
        self.event_id = event_id
        self.channel_id = channel_id
        self.guild_id = guild_id

    @discord.ui.button(label="Confirm delete", style=discord.ButtonStyle.danger)
    async def confirm_delete(self, interaction, button):
        self.disable_buttons()
        try:
            event = await asyncio.to_thread(
                self.repository.delete_event,
                self.event_id,
                self.channel_id,
                self.guild_id,
            )
        except ValueError as error:
            for child in self.children:
                child.disabled = False
            await interaction.response.edit_message(content=f"❌ {error}", view=self)
            return
        await interaction.response.edit_message(
            content=(
                f"🗑️ Deleted Event ID **{event.get_event_id()}** "
                f"({event.get_event_date()} {event.get_event_time()})."
            ),
            view=self,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_delete(self, interaction, button):
        self.disable_buttons()
        await interaction.response.edit_message(
            content="Deletion cancelled. Nothing was changed.",
            view=self,
        )
