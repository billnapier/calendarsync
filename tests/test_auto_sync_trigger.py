import unittest
from unittest.mock import patch, MagicMock
import sys
import os


# Add app to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.app import app


class TestAutoSync(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    @patch("app.app.sync_calendar_logic")
    @patch("app.app.firestore")
    @patch("app.app.fetch_user_calendars")
    def test_create_sync_triggers_sync(
        self, mock_fetch_cals, mock_firestore, mock_sync_logic
    ):
        """Test POST /create_sync triggers auto-sync."""

        # Mock Session
        with self.app.session_transaction() as sess:
            sess["user"] = {"uid": "test_user", "name": "Test User"}
            sess["calendars"] = [{"id": "dest_cal", "summary": "Destination"}]
            sess["csrf_token"] = "token"

        # Mock Firestore
        mock_db = MagicMock()
        mock_firestore.client.return_value = mock_db
        mock_sync_ref = MagicMock()
        mock_sync_ref.id = "new_sync_id"
        mock_db.collection.return_value.document.return_value = mock_sync_ref

        # Submit Form
        response = self.app.post(
            "/create_sync",
            data={
                "destination_calendar_id": "dest_cal",
                "source_urls": ["http://example.com/ics"],
                "csrf_token": "token",
            },
        )

        self.assertEqual(response.status_code, 302)
        # Verify sync_calendar_logic was called with new sync ID
        mock_sync_logic.assert_called_once_with("new_sync_id")

    @patch("app.app.sync_calendar_logic")
    @patch("app.app.firestore")
    def test_edit_sync_triggers_sync(self, mock_firestore, mock_sync_logic):
        """Test POST /edit_sync triggers auto-sync."""

        with self.app.session_transaction() as sess:
            sess["user"] = {"uid": "test_user"}
            sess["calendars"] = [{"id": "dest_cal", "summary": "Destination"}]
            sess["csrf_token"] = "token"

        mock_db = MagicMock()
        mock_firestore.client.return_value = mock_db
        mock_sync_ref = MagicMock()
        mock_sync_ref.id = "existing_sync_id"
        mock_db.collection.return_value.document.return_value = mock_sync_ref

        # We need verify_owner to pass, usually handled via getting the doc
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"user_id": "test_user"}
        mock_sync_ref.get.return_value = mock_doc

        response = self.app.post(
            "/edit_sync/existing_sync_id",
            data={
                "destination_calendar_id": "dest_cal",
                "source_urls": ["http://example.com/new_ics"],
                "csrf_token": "token",
            },
        )

        self.assertEqual(response.status_code, 302)
        mock_sync_logic.assert_called_once_with("existing_sync_id")


if __name__ == "__main__":
    unittest.main()
