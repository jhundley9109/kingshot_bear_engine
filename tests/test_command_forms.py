import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from views.command_forms import (
    CommandFormModal,
    SelectField,
    TextField,
    command_form,
    integer_value,
)


class CommandFormTests(unittest.IsolatedAsyncioTestCase):
    async def test_modal_parses_fields_and_optional_channel_scope(self):
        submit_handler = AsyncMock()
        modal = CommandFormModal(
            title="Test command",
            submit_handler=submit_handler,
            fields=(
                TextField(
                    name="limit",
                    label="Limit",
                    parser=integer_value("Limit", default=0),
                ),
                SelectField(
                    name="months",
                    label="Months",
                    options=(("1 month", "1", True), ("3 months", "3", False)),
                    parser=int,
                ),
            ),
            include_scope=True,
        )
        modal.form_fields[0][1]._value = "25"
        modal.form_fields[1][1]._values = ["3"]
        modal.scope_select._values = ["channel"]
        selected_channel = SimpleNamespace(id=123, name="bear-2")
        modal.channel_select._values = [selected_channel]
        interaction = SimpleNamespace(
            response=SimpleNamespace(send_message=AsyncMock())
        )

        await modal.on_submit(interaction)

        submit_handler.assert_awaited_once_with(
            interaction,
            limit=25,
            months=3,
            channel=selected_channel,
            all_channels=False,
            all_servers=False,
        )

    async def test_modal_reports_invalid_integer_ephemerally(self):
        submit_handler = AsyncMock()
        modal = CommandFormModal(
            title="Test command",
            submit_handler=submit_handler,
            fields=(
                TextField(
                    name="event_id",
                    label="Event ID",
                    parser=integer_value("Event ID", minimum=1),
                ),
            ),
        )
        modal.form_fields[0][1]._value = "not-a-number"
        response = SimpleNamespace(send_message=AsyncMock())
        interaction = SimpleNamespace(response=response)

        await modal.on_submit(interaction)

        submit_handler.assert_not_awaited()
        response.send_message.assert_awaited_once_with(
            "❌ Event ID must be a whole number.", ephemeral=True
        )

    async def test_optional_integer_returns_none_when_left_blank(self):
        submit_handler = AsyncMock()
        modal = CommandFormModal(
            title="Event details",
            submit_handler=submit_handler,
            fields=(
                TextField(
                    name="event_id",
                    label="Event ID (optional)",
                    parser=integer_value("Event ID", minimum=1),
                ),
            ),
        )
        interaction = SimpleNamespace(
            response=SimpleNamespace(send_message=AsyncMock())
        )

        await modal.on_submit(interaction)

        submit_handler.assert_awaited_once_with(interaction, event_id=None)

    async def test_command_form_exposes_only_the_interaction_parameter(self):
        @command_form("Test command", include_scope=True)
        async def callback(
            interaction,
            channel=None,
            all_channels=False,
            all_servers=False,
        ):
            return None

        response = SimpleNamespace(send_modal=AsyncMock())
        interaction = SimpleNamespace(response=response)

        await callback(interaction)

        self.assertEqual(list(inspect.signature(callback).parameters), ["interaction"])
        response.send_modal.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
