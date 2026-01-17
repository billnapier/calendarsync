import sys
import os
from unittest.mock import MagicMock, patch
import pytest

# Add the app directory to the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

import app.app as app_module
from app.app import app as flask_app


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    flask_app.secret_key = "test_secret"
    with flask_app.test_client() as test_client:
        yield test_client


def test_index_empty_state_render(client):
    """Test that index renders the new empty state when user has no syncs."""

    # Mock firestore to return empty list of syncs
    with patch("app.main.routes.firestore") as mock_fs:
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_query = MagicMock()

        mock_fs.client.return_value = mock_db
        mock_db.collection.return_value = mock_collection
        mock_collection.where.return_value = mock_query
        mock_query.stream.return_value = []  # No syncs

        # Mock session to simulate logged in user
        with client.session_transaction() as sess:
            sess["user"] = {"uid": "test_uid", "name": "Test User"}

        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        # Verify new empty state elements are present
        assert "No syncs yet" in html
        assert "Create your first synchronization" in html
        assert 'aria-label="Calendar"' in html
        assert "dashboard-cta" in html
