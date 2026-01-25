import sys
import os
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


def test_create_sync_max_syncs_limit(
    _client, _mock_firestore, _mock_validate_url, _mock_sync_logic
):
    """
    Test that creating a sync is rejected if user already has MAX_SYNCS_PER_USER.
    """
    with _client.session_transaction() as sess:
        sess["user"] = {"uid": "test_uid"}
        sess["calendars"] = [{"id": "dest_cal", "summary": "Destination"}]
        sess["csrf_token"] = "valid_token"

    # Mock Firestore
    mock_db = MagicMock()
    mock_collection = MagicMock()

    # Mock the query result to simulate 10 existing syncs
    mock_query = MagicMock()
    mock_query.get.return_value = [MagicMock() for _ in range(10)]

    # Chain: db.collection("syncs").where(...).get()
    mock_db.collection.return_value = mock_collection
    # Handle the 'where' call which returns the query object
    mock_collection.where.return_value = mock_query

    _mock_firestore.client.return_value = mock_db

    data = {
        "destination_calendar_id": "dest_cal",
        "csrf_token": "valid_token",
        "source_urls": ["http://example.com/cal.ics"],
        "source_types": ["ical"],
    }

    resp = _client.post("/create_sync", data=data)

    # Expect redirect to index
    assert resp.status_code == 302

    # We verify flash message in the session
    with _client.session_transaction() as sess:
        flashed = dict(sess["_flashes"])
        # Check for the expected failure
        assert "danger" in flashed
        assert "maximum number of syncs" in flashed["danger"]
