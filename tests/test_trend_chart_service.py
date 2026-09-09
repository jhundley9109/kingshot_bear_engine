import unittest

from services.trend_chart_service import (
    build_event_trend_data,
    create_event_trend_chart,
)


class EventTrendChartTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {
                "event_id": 7,
                "event_date": "2026-08-28",
                "event_time": "20:30:05",
                "alliance_damage": 458822876,
                "participant_count": 91,
                "rallies": 70,
            },
            {
                "event_id": 8,
                "event_date": "2026-09-01",
                "event_time": "20:30:05",
                "alliance_damage": None,
                "participant_count": 95,
                "rallies": None,
            },
        ]

    def test_build_event_trend_data_preserves_missing_values(self):
        trend = build_event_trend_data(self.rows)

        self.assertEqual(trend["labels"], ["Aug 28\nEvent 7", "Sep 01\nEvent 8"])
        self.assertEqual(trend["damage"], [458822876, None])
        self.assertEqual(trend["participants"], [91, 95])
        self.assertEqual(trend["rallies"], [70, None])

    def test_create_event_trend_chart_returns_png(self):
        chart = create_event_trend_chart(self.rows, 1)

        self.assertEqual(chart.read(8), b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
