# pylint: disable=redefined-outer-name,wrong-import-position
import os

os.environ["TESTING"] = "True"
import sys
from unittest.mock import MagicMock, patch
import pytest

# Add the app directory to the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from app.app import app as flask_app


@pytest.fixture
def client_with_mocks():
    flask_app.config["TESTING"] = True
    flask_app.secret_key = "test_secret"

    with flask_app.test_client() as test_client:
        yield test_client


@patch("app.app.verify_task_auth")
@patch("app.app.tasks_v2.CloudTasksClient")
@patch("app.app.firestore.client")
def test_sync_all_users_dispatch(
    mock_firestore_client, mock_tasks_client, mock_verify_auth, client_with_mocks
):
    """Test the dispatch behavior of sync_all_users."""

    # Mock auth to succeed
    mock_verify_auth.return_value = None

    # Mock mocks
    mock_db = MagicMock()
    mock_firestore_client.return_value = mock_db

    mock_sync_doc1 = MagicMock()
    mock_sync_doc1.id = "sync_1"
    mock_sync_doc2 = MagicMock()
    mock_sync_doc2.id = "sync_2"

    mock_db.collection.return_value.stream.return_value = [
        mock_sync_doc1,
        mock_sync_doc2,
    ]

    # Mock Env vars used in dispatch
    with patch.dict(
        os.environ,
        {
            "GOOGLE_CLOUD_PROJECT": "test-project",
            "GCP_REGION": "us-central1",
            "SCHEDULER_INVOKER_EMAIL": "invoker@example.com",
        },
    ):
        response = client_with_mocks.post("/tasks/sync_all")

    assert response.status_code == 200
    assert b"Dispatched 2 tasks" in response.data

    # Verify create_task called twice
    assert mock_tasks_client.return_value.create_task.call_count == 2


@patch("app.app.verify_task_auth")
@patch("app.app.sync_calendar_logic")
def test_sync_one_user_worker(mock_sync_logic, mock_verify_auth, client_with_mocks):
    """Test the worker endpoint."""

    # Mock auth to succeed
    mock_verify_auth.return_value = None

    # Test success
    response = client_with_mocks.post("/tasks/sync_one", json={"sync_id": "sync_123"})
    assert response.status_code == 200
    mock_sync_logic.assert_called_with("sync_123")

    # Test failure (should return 500)
    mock_sync_logic.side_effect = RuntimeError("Sync fail")
    response_fail = client_with_mocks.post(
        "/tasks/sync_one", json={"sync_id": "sync_123"}
    )
    assert response_fail.status_code == 500


@patch("app.app.verify_task_auth")
def test_sync_one_user_worker_invalid_payload(mock_verify_auth, client_with_mocks):
    """Test the worker endpoint with an invalid payload."""
    mock_verify_auth.return_value = None
    response = client_with_mocks.post(
        "/tasks/sync_one", json={"wrong_key": "some_value"}
    )
    assert response.status_code == 400
    assert b"Invalid payload" in response.data


def test_sync_one_user_worker_no_auth(client_with_mocks):
    """Test that the worker endpoint rejects unauthenticated requests."""
    # Note: We do NOT mock verify_task_auth here, so it runs the real code.
    # The real code checks headers, which are missing.
    response = client_with_mocks.post("/tasks/sync_one", json={"sync_id": "sync_123"})
    assert response.status_code == 403
    assert b"Unauthorized" in response.data


def test_sync_one_user_worker_missing_config(client_with_mocks):
    """Test that the worker endpoint fails if SCHEDULER_INVOKER_EMAIL is missing."""
    # We clear os.environ to simulate missing config
    with patch.dict(os.environ, {}, clear=True):

        # Mock id_token.verify_oauth2_token so it proceeds to check email
        with patch("app.app.id_token.verify_oauth2_token") as mock_verify:
            # Token is valid, but config is missing
            mock_verify.return_value = {"email": "attacker@example.com"}

            # Mock google.auth.transport.requests.Request to avoid network
            with patch("app.app.google.auth.transport.requests.Request"):

                # Send request with valid header
                response = client_with_mocks.post(
                    "/tasks/sync_one",
                    json={"sync_id": "sync_123"},
                    headers={"Authorization": "Bearer mock_token"},
                )

                # Should be 403 because it raises ValueError("Configuration error...")
                assert response.status_code == 403
