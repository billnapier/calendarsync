import sys
import os
from unittest.mock import MagicMock, patch
import pytest

# Add the app directory to the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../app')))

# Initial mocks for import safety
mock_params = MagicMock()
mock_params.SERVER_TIMESTAMP = "TEST_TIMESTAMP"

# Patch sys.modules BEFORE importing app to prevent real Firebase init
with patch.dict(sys.modules, {
    'firebase_admin': MagicMock(),
    'firebase_admin.credentials': MagicMock(),
    'firebase_admin.firestore': mock_params,
    'firebase_admin.auth': MagicMock()
}):
    import app
    from app import app as flask_app

@pytest.fixture
def client(): # pylint: disable=redefined-outer-name
    flask_app.config['TESTING'] = True
    flask_app.secret_key = 'test_secret'
    with flask_app.test_client() as test_client:
        yield test_client

def test_home_page(client): # pylint: disable=redefined-outer-name
    """Test that the home page returns 200 and contains the expected text."""
    with patch('app.session', {}): # just in case
        response = client.get('/')
        assert response.status_code == 200
        assert b"CalendarSync" in response.data
        assert b"Login with Google" in response.data

def test_login_missing_token(client): # pylint: disable=redefined-outer-name
    """Test login without token."""
    response = client.post('/login', json={})
    assert response.status_code == 400
    assert b"Missing ID token" in response.data

def test_login_success(client): # pylint: disable=redefined-outer-name
    """Test successful login."""
    user_data = {
        'uid': 'test_uid',
        'name': 'Test User',
        'email': 'test@example.com',
        'picture': 'http://example.com/pic.jpg'
    }

    # app.auth is ALREADY a mock due to sys.modules patching at import time.
    # We configure it directly.
    app.auth.verify_id_token.return_value = user_data

    # Same for firestore
    mock_db = MagicMock()
    mock_user_ref = MagicMock()
    app.firestore.client.return_value = mock_db
    mock_db.collection.return_value.document.return_value = mock_user_ref

    # Ensure SERVER_TIMESTAMP is preserved
    app.firestore.SERVER_TIMESTAMP = "TEST_TIMESTAMP"

    # Execute
    response = client.post('/login', json={'idToken': 'valid_token'})

    # Assertions
    assert response.status_code == 200, f"Response status: {response.status_code}, data: {response.data}"
    assert response.json['success'] is True

    # Verify interactions
    app.auth.verify_id_token.assert_called_with('valid_token', check_revoked=True) # pylint: disable=no-member
    mock_db.collection.assert_called_with('users')
    mock_user_ref.set.assert_called()

    # Check session
    with client.session_transaction() as sess:
        assert sess['user']['uid'] == 'test_uid'

def test_logout(client): # pylint: disable=redefined-outer-name
    """Test logout clears session."""
    with client.session_transaction() as sess:
        sess['user'] = {
            'uid': 'test_uid',
            'name': 'Test User',
            'email': 'test@example.com',
            'picture': 'http://example.com/pic.jpg'
        }

    response = client.get('/logout', follow_redirects=True)
    assert response.status_code == 200

    with client.session_transaction() as sess:
        assert 'user' not in sess
