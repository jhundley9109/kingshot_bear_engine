import unittest

from services.troop_calculator import (
    calculate_bear_deployment,
    troop_count_value,
    troop_ratio_value,
)


class TroopCalculatorTests(unittest.TestCase):
    def test_input_parsers_accept_commas_and_validate_ratio(self):
        self.assertEqual(troop_count_value("Infantry")("350,000"), 350000)
        self.assertEqual(troop_ratio_value("1 / 9 / 90"), (1, 9, 90))

        with self.assertRaisesRegex(ValueError, "must total 100%"):
            troop_ratio_value("10/10/10")

    def test_calculation_reserves_lead_and_builds_joiner_options(self):
        calculation = calculate_bear_deployment(
            infantry=350000,
            cavalry=320000,
            archers=400000,
            march_capacity=100000,
            lead_ratio=(1, 9, 90),
        )

        self.assertEqual(
            calculation["lead"],
            {
                "infantry": 1000,
                "cavalry": 9000,
                "archers": 90000,
                "total": 100000,
                "ratio": (1, 9, 90),
            },
        )
        self.assertEqual(calculation["remaining"]["archers"], 310000)
        self.assertEqual(
            [option["joiner_count"] for option in calculation["options"]],
            [2, 3, 4, 5],
        )
        self.assertTrue(all(option["full"] for option in calculation["options"]))
        self.assertEqual(calculation["options"][0]["total_used"], 200000)

    def test_calculation_reports_joiner_shortage_and_minimum_failure(self):
        calculation = calculate_bear_deployment(
            infantry=500,
            cavalry=500,
            archers=1000,
            march_capacity=1000,
            lead_ratio=(0, 0, 100),
            joiner_counts=(2,),
        )
        option = calculation["options"][0]

        self.assertFalse(option["full"])
        self.assertFalse(option["minimum_met"])
        self.assertEqual(option["missing_minimums"], ["archers"])
        self.assertEqual(option["shortage"], 1000)

    def test_calculation_rejects_unavailable_lead_troops(self):
        with self.assertRaisesRegex(ValueError, "Not enough troops"):
            calculate_bear_deployment(
                infantry=0,
                cavalry=0,
                archers=100,
                march_capacity=1000,
                lead_ratio=(10, 10, 80),
            )

    def test_calculation_rejects_capacity_too_small_for_three_troop_types(self):
        with self.assertRaisesRegex(ValueError, "at least 3"):
            calculate_bear_deployment(
                infantry=10,
                cavalry=10,
                archers=10,
                march_capacity=2,
                lead_ratio=(0, 0, 100),
            )


if __name__ == "__main__":
    unittest.main()
