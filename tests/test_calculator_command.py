import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from discord import app_commands

from commands.calculator_command import (
    _calculator_embed,
    register_calculator_command,
)
from services.troop_calculator import calculate_bear_deployment


class CalculatorCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_calculator_command_opens_five_field_form(self):
        group = app_commands.Group(name="test", description="Test commands")
        log_messages = []
        register_calculator_command(group, log_messages.append)
        command = group.get_command("calculator")
        response = SimpleNamespace(send_modal=AsyncMock())
        interaction = SimpleNamespace(
            response=response,
            user=SimpleNamespace(id=1),
            guild_id=2,
            channel_id=3,
        )

        await command.callback(interaction)

        response.send_modal.assert_awaited_once()
        modal = response.send_modal.await_args.args[0]
        self.assertEqual(len(modal.form_fields), 5)
        self.assertIn("command=/bear calculator", log_messages[0])

    def test_calculator_embed_contains_lead_and_joiner_scenarios(self):
        calculation = calculate_bear_deployment(
            infantry=350000,
            cavalry=320000,
            archers=400000,
            march_capacity=100000,
            lead_ratio=(1, 9, 90),
        )
        interaction = SimpleNamespace(
            user=SimpleNamespace(mention="<@1>")
        )

        embed = _calculator_embed(interaction, calculation)

        self.assertEqual(embed.fields[0].name, "Lead march")
        self.assertEqual(
            [field.name for field in embed.fields[1:]],
            ["2 joiners", "3 joiners", "4 joiners", "5 joiners"],
        )
        self.assertIn("1 / 9 / 90", embed.fields[0].value)


if __name__ == "__main__":
    unittest.main()
