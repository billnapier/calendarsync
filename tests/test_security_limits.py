import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest

os.environ["TESTING"] = "1"
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

import app.app as app_module
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
def _mock_validate_url():
    with patch("app.main.routes.validate_url") as mock:
        yield mock


@pytest.fixture
def _mock_sync_logic():
    with patch("app.main.routes.sync_calendar_logic") as mock:
        yield mock


def test_create_sync_excessive_sources_dos(
    _client, _mock_firestore, _mock_validate_url, _mock_sync_logic
):
    """
    Test that submitting a large number of sources is rejected (DoS protection).
    """
    with _client.session_transaction() as sess:
        sess["user"] = {"uid": "test_uid"}
        sess["calendars"] = [{"id": "dest_cal", "summary": "Destination"}]
        sess["csrf_token"] = "valid_token"

    # Mock Firestore
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_new_doc = MagicMock()
    mock_db.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_new_doc
    _mock_firestore.client.return_value = mock_db

    # Create 60 source URLs (Limit is 50)
    source_urls = [f"http://example.com/cal{i}.ics" for i in range(60)]
    source_types = ["ical"] * 60

    data = {
        "destination_calendar_id": "dest_cal",
        "csrf_token": "valid_token",
        "source_urls": source_urls,
        "source_types": source_types,
    }

    resp = _client.post("/create_sync", data=data)

    # Should redirect back to create_sync due to error
    assert resp.status_code == 302
    assert "/create_sync" in resp.headers["Location"]

    # validate_url should NOT be called because the check happens before iteration
    assert _mock_validate_url.call_count == 0

    # Verify flash message
    with _client.session_transaction() as sess:
        flashed = dict(sess["_flashes"])
        assert "danger" in flashed
        assert "Too many sources" in flashed["danger"]


def test_run_sync_rate_limit(_client, _mock_firestore, _mock_sync_logic):
    """
    Test that triggering a sync is rate-limited if last sync was recent.
    """
    with _client.session_transaction() as sess:
        sess["user"] = {"uid": "test_uid"}
        sess["csrf_token"] = "valid_token"

    # Mock Firestore
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_doc_ref = MagicMock()
    mock_doc = MagicMock()

    mock_db.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_doc_ref
    mock_doc_ref.get.return_value = mock_doc
    mock_doc.exists = True

    # Set last_synced_at to 1 minute ago
    recent_time = datetime.now(timezone.utc) - timedelta(minutes=1)
    mock_doc.to_dict.return_value = {
        "user_id": "test_uid",
        "last_synced_at": recent_time,
    }

    _mock_firestore.client.return_value = mock_db

    resp = _client.post("/sync/test_sync_id", data={"csrf_token": "valid_token"})

    # Should redirect (either success or failure, checking flash message for failure)
    assert resp.status_code == 302

    # Verify flash message
    with _client.session_transaction() as sess:
        flashed = dict(sess["_flashes"])
        # If rate limiting is implemented, it should be a danger or warning message
        # If not, it will be success (which proves the bug/missing feature)
        # We expect this assertion to FAIL initially if the feature is missing.
        # But for the test-first approach, I will assert "danger" is present.
        assert "danger" in flashed, "Expected rate limit warning not found"
        assert "wait" in flashed["danger"].lower()

    # Verify sync logic was NOT called
    assert _mock_sync_logic.call_count == 0
