import asyncio
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

from commands.support import prepare_report_scope, prepare_trend_since_date


def interaction(user_id=1, channel_name="bear-1", guild_name="Alliance"):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        channel=SimpleNamespace(id=10, name=channel_name),
        channel_id=10,
        guild=SimpleNamespace(name=guild_name),
        guild_id=20,
        response=SimpleNamespace(send_message=AsyncMock()),
    )


class CommandSupportTests(unittest.TestCase):
    def test_prepare_report_scope_defaults_to_current_channel(self):
        current = interaction()

        scope = asyncio.run(prepare_report_scope(current, {1}))

        self.assertEqual(scope.channel_id, 10)
        self.assertEqual(scope.guild_id, 20)
        self.assertEqual(scope.label, "#bear-1")

    def test_prepare_report_scope_resolves_server_and_global_scopes(self):
        current = interaction()

        server_scope = asyncio.run(
            prepare_report_scope(current, {1}, all_channels=True)
        )
        global_scope = asyncio.run(
            prepare_report_scope(current, {1}, all_servers=True)
        )

        self.assertIsNone(server_scope.channel_id)
        self.assertEqual(server_scope.guild_id, 20)
        self.assertIsNone(global_scope.channel_id)
        self.assertIsNone(global_scope.guild_id)

    def test_prepare_report_scope_rejects_conflicts_and_non_owner_global_scope(self):
        conflicting = interaction()
        unauthorized = interaction(user_id=2)

        conflicting_scope = asyncio.run(
            prepare_report_scope(
                conflicting,
                {1},
                channel=SimpleNamespace(id=30, name="bear-2"),
                all_channels=True,
            )
        )
        unauthorized_scope = asyncio.run(
            prepare_report_scope(unauthorized, {1}, all_servers=True)
        )

        self.assertIsNone(conflicting_scope)
        self.assertIsNone(unauthorized_scope)
        conflicting.response.send_message.assert_awaited_once()
        unauthorized.response.send_message.assert_awaited_once()

    def test_prepare_trend_since_date_validates_and_calculates_cutoff(self):
        current = interaction()

        cutoff = asyncio.run(
            prepare_trend_since_date(current, 3, today=date(2026, 9, 2))
        )
        invalid = asyncio.run(
            prepare_trend_since_date(current, 2, today=date(2026, 9, 2))
        )

        self.assertEqual(cutoff, "2026-06-04")
        self.assertIsNone(invalid)
        current.response.send_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
