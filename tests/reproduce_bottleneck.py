
import time
import pytest
from unittest.mock import patch, MagicMock
from app.app import _fetch_source_events

# Mock response object
class MockResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code != 200:
            raise Exception("Status code error")

# Mock safe_requests_get with a delay
def mock_delayed_get(url, timeout=10):
    time.sleep(0.5)  # Simulate 500ms network latency
    return MockResponse(b"BEGIN:VCALENDAR\nEND:VCALENDAR")

def test_sequential_fetch_performance():
    sources = [
        {"url": "http://example.com/1", "prefix": "1"},
        {"url": "http://example.com/2", "prefix": "2"},
        {"url": "http://example.com/3", "prefix": "3"},
        {"url": "http://example.com/4", "prefix": "4"}
    ]

    with patch('app.app.safe_requests_get', side_effect=mock_delayed_get):
        start_time = time.time()
        _fetch_source_events(sources)
        end_time = time.time()

        duration = end_time - start_time
        print(f"\nTime taken for 4 sources (sequential): {duration:.2f}s")

        # Expect ~2.0s (4 * 0.5s)
        assert duration >= 2.0
