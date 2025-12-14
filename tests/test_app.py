"""
Tests for the Flask application.
"""
# pylint: disable=redefined-outer-name
import pytest
from app import app

# Add the app directory to the path so we can import the app
# sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../app')))

@pytest.fixture
def client():
    """Create a test client."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_home_page(client):
    """Test that the home page returns 200 and contains the expected text."""
    response = client.get('/')
    assert response.status_code == 200
    assert b"Hello Cloud Run!" in response.data
