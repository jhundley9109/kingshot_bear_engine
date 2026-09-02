import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from services.extraction_review_service import (
    BEAR_EXTRACTION_MODEL,
    DISCORD_MESSAGE_LIMIT,
    build_extraction_preview,
    extract_bear_data,
    find_image_attachments,
    find_missing_ranks,
    merge_players,
    player_match_name,
)


class ExtractionReviewServiceTests(unittest.TestCase):
    def test_player_match_name_normalizes_tags_case_and_spacing(self):
        self.assertEqual(
            player_match_name("  [XuX]  Capitano   Totti "),
            player_match_name("capitano totti"),
        )

    def test_merge_players_deduplicates_matches_and_reports_conflicts(self):
        first = {"rank": 1, "player_name": "Alpha", "damage": 100}
        harmless_duplicate = {
            "rank": 1,
            "player_name": "[XuX] alpha",
            "damage": 100,
        }
        conflict = {"rank": 2, "player_name": "Beta", "damage": 80}
        conflicting_duplicate = {
            "rank": 2,
            "player_name": "Gamma",
            "damage": 75,
        }

        players, conflicts = merge_players(
            [conflict, harmless_duplicate, conflicting_duplicate, first]
        )

        self.assertEqual([player["rank"] for player in players], [1, 2])
        self.assertEqual(conflicts[0]["first"], conflict)
        self.assertEqual(conflicts[0]["second"], conflicting_duplicate)

    def test_extract_bear_data_builds_multimodal_request_and_decodes_json(self):
        client = Mock()
        client.responses.create.return_value.output_text = (
            '{"event_type":"Bear Trap 2","players":[]}'
        )

        result = extract_bear_data(client, ["https://example.com/one.png"])

        self.assertEqual(result["event_type"], "Bear Trap 2")
        request = client.responses.create.call_args.kwargs
        self.assertEqual(request["model"], BEAR_EXTRACTION_MODEL)
        content = request["input"][0]["content"]
        self.assertEqual(content[0]["type"], "input_text")
        self.assertEqual(
            content[1],
            {
                "type": "input_image",
                "image_url": "https://example.com/one.png",
                "detail": "high",
            },
        )

    def test_find_image_attachments_prefers_discord_content_types(self):
        typed_image = SimpleNamespace(content_type="image/png", filename="one.png")
        extension_only = SimpleNamespace(content_type=None, filename="two.jpg")
        text_file = SimpleNamespace(content_type="text/plain", filename="notes.txt")

        self.assertEqual(
            find_image_attachments([typed_image, extension_only, text_file]),
            [typed_image],
        )

    def test_find_image_attachments_falls_back_to_case_insensitive_extensions(self):
        image = SimpleNamespace(content_type=None, filename="RESULT.WEBP")
        text_file = SimpleNamespace(content_type=None, filename="notes.txt")

        self.assertEqual(find_image_attachments([image, text_file]), [image])

    def test_find_missing_ranks_handles_gaps_and_empty_results(self):
        self.assertEqual(find_missing_ranks([]), [])
        self.assertEqual(
            find_missing_ranks([{"rank": 1}, {"rank": 3}, {"rank": 4}]),
            [2],
        )

    def test_build_extraction_preview_formats_review_details(self):
        data = {
            "event_type": "Bear Trap 2",
            "event_date": "2026-09-01",
            "event_time": "20:30:00",
            "rallies": 10,
            "alliance_damage": 400,
        }
        players = [
            {
                "rank": 1,
                "player_name": "Alpha",
                "damage": 250,
                "uncertain": False,
            },
            {
                "rank": 3,
                "player_name": "Beta",
                "damage": 100,
                "uncertain": True,
            },
        ]

        preview = build_extraction_preview(data, players, [], 2)

        self.assertIn("Screenshots processed: **2**", preview)
        self.assertIn("Difference: **50**", preview)
        self.assertIn("**3.** Beta — 100 ⚠️", preview)
        self.assertIn("Missing ranks:** 2", preview)
        self.assertIn("Review this preview before saving", preview)

    def test_build_extraction_preview_marks_conflicts_as_unsavable(self):
        player = {"rank": 1, "player_name": "Alpha", "damage": 100}
        conflict = {
            "rank": 1,
            "first": player,
            "second": {"rank": 1, "player_name": "Beta", "damage": 100},
        }

        preview = build_extraction_preview({}, [player], [conflict], 1)

        self.assertIn("Rank 1: Alpha vs Beta", preview)
        self.assertIn("Not saved", preview)

    def test_build_extraction_preview_respects_discord_message_limit(self):
        players = [
            {"rank": rank, "player_name": "x" * 100, "damage": rank}
            for rank in range(1, 50)
        ]

        preview = build_extraction_preview({}, players, [], 1)

        self.assertLessEqual(len(preview), DISCORD_MESSAGE_LIMIT)
        self.assertTrue(preview.endswith("Discord message."))


if __name__ == "__main__":
    unittest.main()
