import sys
import os
from unittest.mock import MagicMock, patch
import pytest

# Add the app directory to the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../app')))

# Initial mocks for import safety - same as test_app.py
mock_firestore = MagicMock()
mock_firestore.SERVER_TIMESTAMP = "TEST_TIMESTAMP"

with patch.dict(sys.modules, {
    'firebase_admin': MagicMock(),
    'firebase_admin.credentials': MagicMock(),
    'firebase_admin.firestore': mock_firestore,
    'google.cloud': MagicMock(),
    'google.cloud.secretmanager': MagicMock(),
}):
    import app
    from app.app import app as flask_app

@pytest.fixture
def client_with_mocks():
    flask_app.config['TESTING'] = True
    flask_app.secret_key = 'test_secret'
    
    with flask_app.test_client() as test_client:
        yield test_client

def test_sync_all_users_success(client_with_mocks):
    """Test the synchronous execution of sync_all_users."""
    
    # Mock Firestore streaming
    mock_db = MagicMock()
    mock_sync_doc1 = MagicMock()
    mock_sync_doc1.id = "sync_1"
    mock_sync_doc2 = MagicMock()
    mock_sync_doc2.id = "sync_2"
    
    view_func = flask_app.view_functions['sync_all_users']
    firestore_used = view_func.__globals__['firestore']
    
    firestore_used.client.return_value = mock_db
    
    mock_db.collection.return_value.stream.return_value = [mock_sync_doc1, mock_sync_doc2]

    with patch.dict(view_func.__globals__, {'sync_calendar_logic': MagicMock()}) as mock_sync_logic_dict:
        mock_sync_logic = view_func.__globals__['sync_calendar_logic']
        
        response = client_with_mocks.post('/tasks/sync_all')
        
        assert response.status_code == 200
        assert b"Success: 2" in response.data
        
        # Verify calls
        assert mock_sync_logic.call_count == 2
        mock_sync_logic.assert_any_call("sync_1")
        mock_sync_logic.assert_any_call("sync_2")

def test_sync_all_users_partial_failure(client_with_mocks):
    """Test sync_all_users behavior when individual syncs fail."""
    
    mock_db = MagicMock()
    mock_sync_doc1 = MagicMock()
    mock_sync_doc1.id = "sync_1" # Success
    mock_sync_doc2 = MagicMock()
    mock_sync_doc2.id = "sync_2" # Fail
    
    view_func = flask_app.view_functions['sync_all_users']
    firestore_used = view_func.__globals__['firestore']
    firestore_used.client.return_value = mock_db
    
    mock_db.collection.return_value.stream.return_value = [mock_sync_doc1, mock_sync_doc2]

    with patch.dict(view_func.__globals__, {'sync_calendar_logic': MagicMock()}) as mock_sync_logic_dict:
        mock_sync_logic = view_func.__globals__['sync_calendar_logic']
        # Side effect: first call success, second call raises exception
        mock_sync_logic.side_effect = [None, RuntimeError("Sync failed")]
        
        response = client_with_mocks.post('/tasks/sync_all')
        
        assert response.status_code == 200
        # Should report 1 success, 1 error
        assert b"Success: 1" in response.data
        assert b"Errors: 1" in response.data
