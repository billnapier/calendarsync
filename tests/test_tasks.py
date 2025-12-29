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

@patch('app.app.firestore.client')
@patch('app.app.sync_calendar_logic')
def test_sync_all_users_success(mock_sync_logic, mock_firestore_client, client_with_mocks):
    """Test the synchronous execution of sync_all_users."""
    
    # Mock Firestore streaming
    mock_db = MagicMock()
    mock_firestore_client.return_value = mock_db
    
    # Mock sync docs
    mock_sync_doc1 = MagicMock()
    mock_sync_doc1.id = "sync_1"
    mock_sync_doc2 = MagicMock()
    mock_sync_doc2.id = "sync_2"
    
    mock_db.collection.return_value.stream.return_value = [mock_sync_doc1, mock_sync_doc2]

    response = client_with_mocks.post('/tasks/sync_all')
    
    assert response.status_code == 200
    assert b"Success: 2" in response.data
    
    # Verify calls
    assert mock_sync_logic.call_count == 2
    mock_sync_logic.assert_any_call("sync_1")
    mock_sync_logic.assert_any_call("sync_2")

@patch('app.app.firestore.client')
@patch('app.app.sync_calendar_logic')
def test_sync_all_users_partial_failure(mock_sync_logic, mock_firestore_client, client_with_mocks):
    """Test sync_all_users behavior when individual syncs fail."""
    
    mock_db = MagicMock()
    mock_firestore_client.return_value = mock_db
    
    mock_sync_doc1 = MagicMock()
    mock_sync_doc1.id = "sync_1" 
    mock_sync_doc2 = MagicMock()
    mock_sync_doc2.id = "sync_2"
    
    mock_db.collection.return_value.stream.return_value = [mock_sync_doc1, mock_sync_doc2]
    
    # Side effect: first call success, second call raises exception
    mock_sync_logic.side_effect = [None, RuntimeError("Sync failed")]
    
    response = client_with_mocks.post('/tasks/sync_all')
    
    assert response.status_code == 200
    # Should report 1 success, 1 error
    assert b"Success: 1" in response.data
    assert b"Errors: 1" in response.data
