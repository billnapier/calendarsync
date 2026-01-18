import sys
import os
from unittest.mock import MagicMock, patch
import pytest

os.environ["TESTING"] = "1"
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from app.app import app as flask_app

@pytest.fixture
def _client():
    flask_app.config["TESTING"] = True
    flask_app.secret_key = "test_secret"
    with flask_app.test_client() as test_client:
        yield test_client

@pytest.fixture
def _mock_firestore():
    with patch("app.main.routes.firestore") as mock_fs:
        yield mock_fs

@pytest.fixture
def _mock_fetch_calendars():
    with patch("app.main.routes.fetch_user_calendars") as mock:
        yield mock

def test_delete_sync_flash_message_presence(_client, _mock_firestore):
    """Test that a flash message IS set on delete."""
    with _client.session_transaction() as sess:
        sess["user"] = {"uid": "test_uid"}
        sess["csrf_token"] = "valid_token"

    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_doc_ref = MagicMock()
    mock_doc_snapshot = MagicMock()

    mock_db.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_doc_ref
    mock_doc_ref.get.return_value = mock_doc_snapshot

    mock_doc_snapshot.exists = True
    mock_doc_snapshot.to_dict.return_value = {"user_id": "test_uid"}

    _mock_firestore.client.return_value = mock_db

    _client.post("/delete_sync/sync123", data={"csrf_token": "valid_token"})

    # Check flash messages - should contain success message
    with _client.session_transaction() as sess:
        assert "_flashes" in sess
        flashes = sess["_flashes"]
        assert len(flashes) > 0
        assert flashes[0][0] == "success"
        assert "Sync deleted successfully" in flashes[0][1]

def test_create_sync_flash_message_presence(_client, _mock_firestore, _mock_fetch_calendars):
    """Test that a flash message IS set on create."""
    with _client.session_transaction() as sess:
        sess["user"] = {"uid": "test_uid"}
        sess["csrf_token"] = "valid_token"

    _mock_fetch_calendars.return_value = [{"id": "dest_cal", "summary": "Destination Cal"}]

    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_new_doc = MagicMock()

    mock_db.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_new_doc
    _mock_firestore.client.return_value = mock_db

    _client.post(
        "/create_sync",
        data={
            "destination_calendar_id": "dest_cal",
            "ical_urls": ["http://example.com/cal.ics"],
            "csrf_token": "valid_token",
        },
    )

    with _client.session_transaction() as sess:
        assert "_flashes" in sess
        flashes = sess["_flashes"]
        assert len(flashes) > 0
        assert flashes[0][0] == "success"
        assert "Sync created successfully" in flashes[0][1]
