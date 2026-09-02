import unittest
from types import SimpleNamespace

from services.extraction_review_service import (
    DISCORD_MESSAGE_LIMIT,
    build_extraction_preview,
    find_image_attachments,
    find_missing_ranks,
)


class ExtractionReviewServiceTests(unittest.TestCase):
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
