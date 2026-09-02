import json
import unittest
from unittest.mock import Mock

from services.recap_service import (
    RECAP_INSTRUCTIONS,
    RECAP_MODEL,
    generate_bear_recap,
)


class RecapServiceTests(unittest.TestCase):
    def test_generate_bear_recap_builds_request_and_strips_response(self):
        client = Mock()
        client.responses.create.return_value.output_text = "  Great event!  \n"
        recap_data = {"events": [{"event_id": 1}], "players": []}

        result = generate_bear_recap(client, recap_data)

        self.assertEqual(result, "Great event!")
        request = client.responses.create.call_args.kwargs
        self.assertEqual(request["model"], RECAP_MODEL)
        self.assertEqual(request["instructions"], RECAP_INSTRUCTIONS)
        self.assertEqual(json.loads(request["input"]), recap_data)
        self.assertEqual(request["reasoning"], {"effort": "minimal"})
        self.assertEqual(request["max_output_tokens"], 400)
        self.assertFalse(request["store"])


if __name__ == "__main__":
    unittest.main()
