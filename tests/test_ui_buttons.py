import sys
import os
from unittest.mock import MagicMock, patch
import pytest

# Add the app directory to the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from app.app import app as flask_app

@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    flask_app.secret_key = "test_secret"
    with flask_app.test_client() as test_client:
        yield test_client

def test_create_sync_remove_button_ux(client):
    """Test that the create sync page renders the remove button with correct UX attributes."""

    # Mock firestore and fetch_user_calendars
    with patch("app.main.routes.firestore") as mock_fs, \
         patch("app.main.routes.fetch_user_calendars", return_value=[]):

        # Mock session to simulate logged in user
        with client.session_transaction() as sess:
            sess["user"] = {"uid": "test_uid", "name": "Test User"}

        resp = client.get("/create_sync")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        # Verify attributes for accessibility and UX
        # We expect to find the new class 'btn-icon' and 'btn-remove' eventually
        # But for now, we just check if we can find the button.
        # This test is expected to FAIL on specific class checks until I implement them.

        # We want to check for the new classes and aria-label
        assert 'aria-label="Remove Source"' in html
        assert 'title="Remove Source"' in html
        assert 'btn-icon' in html
        assert 'btn-remove' in html
        assert '<svg' in html  # Ensure we have an SVG icon
