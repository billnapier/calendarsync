import unittest
from unittest.mock import patch, MagicMock
import requests
from datetime import datetime
from app.sync import logic


class TestLogLeak(unittest.TestCase):
    @patch("app.sync.logic.logger")
    @patch("app.sync.logic.safe_requests_get")
    def test_fetch_source_data_logs_credentials(self, mock_get, mock_logger):
        # Setup
        url_with_creds = "https://user:secretpass@example.com/cal.ics"
        source = {"url": url_with_creds, "type": "ical"}
        user_id = "test_user"
        window_start = datetime.now()
        window_end = datetime.now()

        # Simulate failure
        mock_get.side_effect = requests.exceptions.RequestException("Connection failed")

        # Execute
        logic._fetch_source_data(source, user_id, window_start, window_end)

        # Verify leak
        # We expect logger.error to be called with the CLEANED URL
        args, _ = mock_logger.error.call_args
        # args[0] is format string, args[1] is url, args[2] is exception

        # Verify password IS NOT present
        self.assertNotIn("secretpass", args[1])

        # Verify sanitized URL IS present
        self.assertIn("example.com", args[1])

    @patch("app.sync.logic.logger")
    @patch("app.sync.logic.safe_requests_get")
    def test_get_calendar_name_logs_credentials(self, mock_get, mock_logger):
        # Setup
        url_with_creds = "https://user:secretpass@example.com/cal.ics"

        # Simulate failure
        mock_get.side_effect = requests.exceptions.RequestException("Connection failed")

        # Execute
        logic.get_calendar_name_from_ical(url_with_creds)

        # Verify leak
        args, _ = mock_logger.warning.call_args

        # Verify password IS NOT present
        self.assertNotIn("secretpass", args[1])

        # Verify sanitized URL IS present
        self.assertIn("example.com", args[1])


if __name__ == "__main__":
    unittest.main()
