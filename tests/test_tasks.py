import sys
import os
from unittest.mock import MagicMock, patch
import pytest

# Add the app directory to the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../app')))

from app.app import app as flask_app
from app import app

@pytest.fixture
def client_with_mocks():
    flask_app.config['TESTING'] = True
    flask_app.secret_key = 'test_secret'
    
    with flask_app.test_client() as test_client:
        yield test_client

@patch('app.app.tasks_v2.CloudTasksClient')
@patch('app.app.firestore.client')
def test_sync_all_users_dispatch(mock_firestore_client, mock_tasks_client, client_with_mocks):
    """Test the dispatch behavior of sync_all_users."""
    
    # Mock mocks
    mock_db = MagicMock()
    mock_firestore_client.return_value = mock_db
    
    mock_sync_doc1 = MagicMock()
    mock_sync_doc1.id = "sync_1"
    mock_sync_doc2 = MagicMock()
    mock_sync_doc2.id = "sync_2"
    
    mock_db.collection.return_value.stream.return_value = [mock_sync_doc1, mock_sync_doc2]
    
    # Mock Env vars used in dispatch
    with patch.dict(os.environ, {
        'GOOGLE_CLOUD_PROJECT': 'test-project',
        'GCP_REGION': 'us-central1',
        'SCHEDULER_INVOKER_EMAIL': 'invoker@example.com'
    }):
        response = client_with_mocks.post('/tasks/sync_all')
    
    assert response.status_code == 200
    assert b"Dispatched 2 tasks" in response.data
    
    # Verify create_task called twice
    assert mock_tasks_client.return_value.create_task.call_count == 2


@patch('app.app.sync_calendar_logic')
def test_sync_one_user_worker(mock_sync_logic, client_with_mocks):
    """Test the worker endpoint."""
    
    # Test success
    response = client_with_mocks.post('/tasks/sync_one', json={'sync_id': 'sync_123'})
    assert response.status_code == 200
    mock_sync_logic.assert_called_with('sync_123')
    
    # Test failure (should return 500)
    mock_sync_logic.side_effect = RuntimeError("Sync fail")
    response_fail = client_with_mocks.post('/tasks/sync_one', json={'sync_id': 'sync_123'})
    assert response_fail.status_code == 500
