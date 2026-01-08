import sys
import os
import time
from unittest.mock import MagicMock, patch
import pytest

os.environ["TESTING"] = "1"

# Add the app directory to the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

# Initial mocks for import safety
mock_firestore_module_mock = MagicMock()
mock_firestore_module_mock.SERVER_TIMESTAMP = "TEST_TIMESTAMP"

# Patch sys.modules to prevent real init on import
with patch.dict(
    sys.modules,
    {
        "firebase_admin": MagicMock(),
        "firebase_admin.credentials": MagicMock(),
        "firebase_admin.firestore": mock_firestore_module_mock,
        "google.cloud": MagicMock(),
        "google.cloud.secretmanager": MagicMock(),
    },
):
    import app.app as app_module
    from app.app import app as flask_app


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    flask_app.secret_key = "test_secret"
    with flask_app.test_client() as test_client:
        yield test_client


@pytest.fixture
def mock_fetch_calendars():
    # Force patch on the imported module object to be sure
    with patch.object(app_module, "fetch_user_calendars") as mock:
        yield mock


@pytest.fixture
def mock_firestore():
    original_firestore = app_module.firestore
    mock_fs = MagicMock(name="manual_fs")
    app_module.firestore = mock_fs
    yield mock_fs
    app_module.firestore = original_firestore


def test_edit_sync_post_refreshes_stale_cache(
    client, mock_fetch_calendars, mock_firestore
):  # pylint: disable=redefined-outer-name
    """Test that POST to edit_sync refreshes cache if stale."""
    # Setup - mocked user and stale cache
    with client.session_transaction() as sess:
        sess["user"] = {"uid": "test_uid"}
        sess["calendars"] = [{"id": "old_cal", "summary": "Old Cal"}]
        sess["calendars_timestamp"] = time.time() - 301  # Stale
        sess["csrf_token"] = "valid_token"

    mock_fetch_calendars.return_value = [{"id": "new_cal", "summary": "New Cal"}]

    # Mock return values
    mock_db = MagicMock(name="mock_db")
    mock_collection = MagicMock(name="mock_collection")
    mock_doc_ref = MagicMock(name="mock_doc_ref")
    mock_doc_snapshot = MagicMock(name="mock_doc_snapshot")

    mock_db.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_doc_ref
    mock_doc_ref.get.return_value = mock_doc_snapshot

    mock_doc_snapshot.exists = True
    mock_doc_snapshot.to_dict.return_value = {
        "user_id": "test_uid",
        "destination_calendar_id": "dest_id",
    }

    mock_firestore.client.return_value = mock_db

    resp = client.post(
        "/edit_sync/sync123",
        data={
            "destination_calendar_id": "new_cal",
            "ical_urls": ["http://example.com/cal.ics"],
            "csrf_token": "valid_token",
        },
    )
    assert resp.status_code == 302  # Redirects home

    # Asserts
    mock_fetch_calendars.assert_called_once_with("test_uid")


def test_create_sync_post_fetches_if_missing(
    client, mock_fetch_calendars, mock_firestore
):  # pylint: disable=redefined-outer-name
    """Test that POST to create_sync fetches calendars if missing from session."""
    with client.session_transaction() as sess:
        sess["user"] = {"uid": "test_uid"}
        sess["csrf_token"] = "valid_token"
        # No 'calendars' in session

    mock_fetch_calendars.return_value = [
        {"id": "dest_cal", "summary": "Destination Cal"}
    ]

    mock_db = MagicMock(name="mock_db")
    mock_collection = MagicMock(name="mock_collection")
    mock_new_doc = MagicMock(name="mock_new_doc")

    mock_db.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_new_doc

    mock_firestore.client.return_value = mock_db

    resp = client.post(
        "/create_sync",
        data={
            "destination_calendar_id": "dest_cal",
            "ical_urls": ["http://example.com/cal.ics"],
            "csrf_token": "valid_token",
        },
    )
    assert resp.status_code == 302

    mock_fetch_calendars.assert_called_once_with("test_uid")

    # Verify the summary was used in the set call
    assert mock_new_doc.set.called
    args, _ = mock_new_doc.set.call_args
    assert args[0]["destination_calendar_summary"] == "Destination Cal"


def test_delete_sync_success(
    client, mock_firestore
):  # pylint: disable=redefined-outer-name
    """Test that POST to delete_sync deletes the document."""
    with client.session_transaction() as sess:
        sess["user"] = {"uid": "test_uid"}

    mock_db = MagicMock(name="mock_db")
    mock_collection = MagicMock(name="mock_collection")
    mock_doc_ref = MagicMock(name="mock_doc_ref")
    mock_doc_snapshot = MagicMock(name="mock_doc_snapshot")

    mock_db.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_doc_ref
    mock_doc_ref.get.return_value = mock_doc_snapshot

    # Simulate existing sync owned by user
    mock_doc_snapshot.exists = True
    mock_doc_snapshot.to_dict.return_value = {"user_id": "test_uid"}

    mock_firestore.client.return_value = mock_db

    resp = client.post("/delete_sync/sync123")

    assert resp.status_code == 302  # redirect home
    mock_collection.document.assert_called_with("sync123")
    mock_doc_ref.delete.assert_called_once()


def test_delete_sync_not_found(
    client, mock_firestore
):  # pylint: disable=redefined-outer-name
    """Test delete_sync returns 404 if sync does not exist."""
    with client.session_transaction() as sess:
        sess["user"] = {"uid": "test_uid"}

    mock_db = MagicMock(name="mock_db")
    mock_collection = MagicMock(name="mock_collection")
    mock_doc_ref = MagicMock(name="mock_doc_ref")
    mock_doc_snapshot = MagicMock(name="mock_doc_snapshot")

    mock_db.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_doc_ref
    mock_doc_ref.get.return_value = mock_doc_snapshot

    mock_doc_snapshot.exists = False  # Does not exist

    mock_firestore.client.return_value = mock_db

    resp = client.post("/delete_sync/missing_sync")
    assert resp.status_code == 404
    assert b"Sync not found" in resp.data


def test_delete_sync_unauthorized(
    client, mock_firestore
):  # pylint: disable=redefined-outer-name
    """Test delete_sync returns 403 if user does not own sync."""
    with client.session_transaction() as sess:
        sess["user"] = {"uid": "test_uid"}

    mock_db = MagicMock(name="mock_db")
    mock_collection = MagicMock(name="mock_collection")
    mock_doc_ref = MagicMock(name="mock_doc_ref")
    mock_doc_snapshot = MagicMock(name="mock_doc_snapshot")

    mock_db.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_doc_ref
    mock_doc_ref.get.return_value = mock_doc_snapshot

    mock_doc_snapshot.exists = True
    mock_doc_snapshot.to_dict.return_value = {"user_id": "other_user"}  # Different user

    mock_firestore.client.return_value = mock_db

    resp = client.post("/delete_sync/sync123")
    assert resp.status_code == 403
    assert b"Unauthorized" in resp.data


def test_delete_sync_not_logged_in(client):  # pylint: disable=redefined-outer-name
    """Test delete_sync redirects to login if not logged in."""
    resp = client.post("/delete_sync/sync123")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
