import sys
import os
import pytest
from unittest.mock import MagicMock, patch

# Adjust path to import app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

# Patch sys.modules to prevent real init on import
mock_firestore_module_mock = MagicMock()
mock_firestore_module_mock.SERVER_TIMESTAMP = "TEST_TIMESTAMP"

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
    from app.app import app

@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.secret_key = "test_key"
    with app.test_client() as client:
        yield client

def test_logout_secure_success(client):
    """Test that POST /logout with valid CSRF token works."""
    with client.session_transaction() as sess:
        sess["user"] = {"uid": "user123"}
        sess["csrf_token"] = "valid_token"

    resp = client.post("/logout", data={"csrf_token": "valid_token"})
    assert resp.status_code == 302
    assert resp.location == "/"

    with client.session_transaction() as sess:
        assert "user" not in sess

def test_logout_get_method_not_allowed(client):
    """Test that GET /logout is not allowed."""
    resp = client.get("/logout")
    assert resp.status_code == 405

def test_logout_invalid_csrf(client):
    """Test that POST /logout with invalid CSRF token fails."""
    with client.session_transaction() as sess:
        sess["user"] = {"uid": "user123"}
        sess["csrf_token"] = "valid_token"

    resp = client.post("/logout", data={"csrf_token": "invalid_token"})
    assert resp.status_code == 400
    assert b"Invalid CSRF token" in resp.data
