import unittest

from services.discord_formatting import (
    code_table_chunks,
    discord_text_chunks,
    guild_scope_line,
    line_chunks,
    player_result_context,
    table_name_cell,
    table_text,
)


class DiscordFormattingTests(unittest.TestCase):
    def test_code_table_chunks_repeats_headers_and_marks_continuations(self):
        chunks = code_table_chunks(
            "Column",
            "------",
            ["first row", "second row", "third row"],
            title="**Report**",
            max_length=55,
        )

        self.assertGreater(len(chunks), 1)
        self.assertTrue(chunks[0].startswith("**Report**\n```text\nColumn"))
        self.assertTrue(chunks[1].startswith("**Report** **(continued)**"))
        self.assertTrue(all(chunk.endswith("```") for chunk in chunks))

    def test_discord_text_chunks_prefers_readable_boundaries(self):
        chunks = discord_text_chunks("alpha beta\ngamma delta", max_length=12)

        self.assertEqual(chunks, ["alpha beta", "gamma delta"])

    def test_line_chunks_uses_a_smaller_continuation_header(self):
        chunks = line_chunks(
            ["Full report", "Summary"],
            ["first result", "second result", "third result"],
            continued_lines=["Report continued"],
            max_length=40,
        )

        self.assertGreater(len(chunks), 1)
        self.assertTrue(chunks[0].startswith("Full report\nSummary"))
        self.assertTrue(chunks[1].startswith("Report continued"))

    def test_table_helpers_sanitize_and_support_rtl_names(self):
        self.assertEqual(table_text("a`long-value", 8), "a'lon...")

        cell = table_name_cell("مرحبا", 10)

        self.assertIn("\u2067مرحبا\u2069", cell)

    def test_player_result_context_formats_scope_and_uncertainty(self):
        result = {
            "event_date": "2026-09-01",
            "event_time": "20:30:00",
            "discord_channel_name": "bear-trap-2",
            "discord_guild_name": "Alliance",
            "discord_guild_id": "123",
            "uncertain": True,
        }

        context, uncertain = player_result_context(
            result, all_channels=True, all_servers=True
        )

        self.assertEqual(
            context,
            "Alliance (123) / #bear-trap-2 — 2026-09-01 20:30:00",
        )
        self.assertEqual(uncertain, " ⚠️")

    def test_guild_scope_line_deduplicates_and_sorts_guilds(self):
        rows = [
            {"discord_guild_name": "Zulu", "discord_guild_id": "2"},
            {"discord_guild_name": "Alpha", "discord_guild_id": "1"},
            {"discord_guild_name": "Zulu", "discord_guild_id": "2"},
        ]

        self.assertEqual(
            guild_scope_line(rows),
            "Guilds: **Alpha (1)**, **Zulu (2)**",
        )


if __name__ == "__main__":
    unittest.main()
