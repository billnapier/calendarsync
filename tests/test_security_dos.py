import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone
from app.sync import logic

class TestSecurityDoS(unittest.TestCase):

    @patch("app.sync.logic.safe_requests_get")
    def test_fetch_source_data_size_limit(self, mock_get):
        """Test that fetching a source larger than limit raises an error."""

        # Mock response behavior
        mock_response = MagicMock()
        mock_response.status_code = 200

        # IMPORTANT: When using a mock in a `with` statement, we must configure __enter__
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None

        # Simulate 11MB of data (11 chunks of 1MB)
        chunk_size = 1024 * 1024  # 1MB
        chunks = [b"A" * chunk_size] * 11
        mock_response.iter_content.return_value = iter(chunks)

        mock_get.return_value = mock_response

        source = {"url": "http://malicious.com/large.ics", "type": "ical"}
        user_id = "test_user"
        window_start = datetime.now(timezone.utc)
        window_end = datetime.now(timezone.utc)

        # Execute
        components, name = logic._fetch_source_data(source, user_id, window_start, window_end)

        # Assertions

        # 1. Verify safe_requests_get was called with stream=True
        mock_get.assert_called_with("http://malicious.com/large.ics", timeout=10, stream=True)

        # 2. Verify iter_content was called
        mock_response.iter_content.assert_called()

        # 3. Verify result indicates failure
        self.assertEqual(components, [])
        self.assertIn("(Failed)", name)

if __name__ == "__main__":
    unittest.main()
