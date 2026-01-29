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
def _mock_sync_logic():
    with patch("app.main.routes.sync_calendar_logic") as mock:
        yield mock


def test_manual_sync_rate_limit_bypass(_client, _mock_firestore, _mock_sync_logic):
    """
    Test that manual sync currently allows rapid requests (reproducing missing rate limit).
    """
    with _client.session_transaction() as sess:
        sess["user"] = {"uid": "test_uid"}
        sess["csrf_token"] = "valid_token"

    # Mock Firestore
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_doc_ref = MagicMock()
    mock_doc_snap = MagicMock()

    mock_db.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_doc_ref
    mock_doc_ref.get.return_value = mock_doc_snap

    # Simulate a sync that just finished (now)
    now = datetime.now(timezone.utc)
    mock_doc_snap.exists = True
    mock_doc_snap.to_dict.return_value = {
        "user_id": "test_uid",
        "last_synced_at": now  # Synced just now
    }

    _mock_firestore.client.return_value = mock_db

    # Attempt to sync again immediately
    resp = _client.post("/sync/sync_123", data={"csrf_token": "valid_token"})

    # CURRENT BEHAVIOR: It succeeds (redirects to index with success flash)
    # DESIRED BEHAVIOR: It fails (redirects to index with warning flash)

    assert resp.status_code == 302

    # Logic should NOT be called due to rate limit
    assert not _mock_sync_logic.called

    # Verify flash message
    with _client.session_transaction() as sess:
        flashed = dict(sess["_flashes"])
        assert "warning" in flashed
        assert "Please wait 5 minutes" in flashed["warning"]
