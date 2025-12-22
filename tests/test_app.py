import sys
import os
from unittest.mock import MagicMock, patch
import pytest

# Add the app directory to the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../app')))

# Initial mocks for import safety
mock_firestore = MagicMock()
mock_firestore.SERVER_TIMESTAMP = "TEST_TIMESTAMP"

# Patch sys.modules BEFORE importing app to prevent real Firebase init if needed
# But we also rely on real imports for google libraries which are in venv.
# We'll just mock firebase_admin.
with patch.dict(sys.modules, {
    'firebase_admin': MagicMock(),
    'firebase_admin.credentials': MagicMock(),
    'firebase_admin.firestore': mock_firestore,
    'google.cloud': MagicMock(),
    'google.cloud.secretmanager': MagicMock(),
}):
    import app
    from app import app as flask_app

@pytest.fixture
def client(): # pylint: disable=redefined-outer-name
    flask_app.config['TESTING'] = True
    flask_app.secret_key = 'test_secret'
    # Mock get_client_config to avoid secret manager calls during login
    with patch('app.get_client_config') as mock_config:
        mock_config.return_value = {
            "web": {
                "client_id": "test_id",
                "client_secret": "test_secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        with flask_app.test_client() as test_client:
            yield test_client

def test_home_page(client): # pylint: disable=redefined-outer-name
    """Test that the home page returns 200 and contains the expected text."""
    with patch('app.session', {}): # just in case
        response = client.get('/')
        assert response.status_code == 200
        assert b"CalendarSync" in response.data
        assert b"Login with Google" in response.data

def test_login_redirect(client): # pylint: disable=redefined-outer-name
    """Test login route redirects to Google."""
    with patch('google_auth_oauthlib.flow.Flow.from_client_config') as mock_flow:
        mock_flow_instance = MagicMock()
        mock_flow.return_value = mock_flow_instance
        mock_flow_instance.authorization_url.return_value = ('https://accounts.google.com/auth', 'state')
        
        response = client.get('/login')
        assert response.status_code == 302
        assert 'accounts.google.com' in response.headers['Location']

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

def test_create_sync_unauthorized(client):
    """Test accessing create_sync without login redirects to login."""
    response = client.get('/create_sync')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']
