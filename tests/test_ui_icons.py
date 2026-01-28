import sys
import os
from unittest.mock import MagicMock, patch
import pytest

# Add the app directory to the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

import app.app as app_module
from app.app import app as flask_app


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    flask_app.secret_key = "test_secret"
    with flask_app.test_client() as test_client:
        yield test_client

def test_create_sync_render_icons(client):
    """Test that create_sync renders the remove button with icon and correct classes."""
    with patch("app.main.routes.fetch_user_calendars") as mock_fetch:
        mock_fetch.return_value = [] # No calendars needed for this test

        # Mock session to simulate logged in user
        with client.session_transaction() as sess:
            sess["user"] = {"uid": "test_uid", "name": "Test User"}

        resp = client.get("/create_sync")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        # Check for .btn-icon class
        assert "btn-icon" in html
        # Check for SVG
        assert "<svg" in html
        assert "bi-trash" in html or "path d=" in html # I used inline SVG path
        # Check title
        assert 'title="Remove Source"' in html
        # Check aria-label
        assert 'aria-label="Remove Source"' in html

def test_edit_sync_render_icons(client):
    """Test that edit_sync renders the remove button with icon and correct classes."""
    with patch("app.main.routes.fetch_user_calendars") as mock_fetch, \
         patch("app.main.routes.firestore") as mock_fs:

        mock_fetch.return_value = []

        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_doc = MagicMock()
        mock_snapshot = MagicMock()

        mock_fs.client.return_value = mock_db
        mock_db.collection.return_value = mock_collection
        mock_collection.document.return_value = mock_doc
        mock_doc.get.return_value = mock_snapshot

        # Mock existing sync
        mock_snapshot.exists = True
        mock_snapshot.to_dict.return_value = {
            "user_id": "test_uid",
            "destination_calendar_id": "dest_cal",
            "sources": [{"url": "http://example.com/cal.ics", "type": "ical"}]
        }
        # Mock ID
        mock_snapshot.id = "sync123"

        # Mock session
        with client.session_transaction() as sess:
            sess["user"] = {"uid": "test_uid", "name": "Test User"}

        resp = client.get("/edit_sync/sync123")

        # Debugging
        if resp.status_code != 200:
            print(f"Status Code: {resp.status_code}")
            print(f"Response: {resp.data.decode('utf-8')}")

        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        # Check for .btn-icon class
        assert "btn-icon" in html
        # Check for SVG
        assert "<svg" in html
        assert 'title="Remove Source"' in html
