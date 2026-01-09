# pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments,unused-argument,wrong-import-position
import unittest
import os
from datetime import datetime, timedelta

os.environ["TESTING"] = "1"
from unittest.mock import patch, MagicMock
import requests
from app.sync import sync_calendar_logic


class TestSyncLogic(unittest.TestCase):

    def _get_ical_content(self, uid, summary, days_offset=0, rrule=None):
        """Helper to generate iCal content with current dates."""
        now = datetime.utcnow()
        dtstart = (now + timedelta(days=days_offset)).strftime("%Y%m%dT%H%M%SZ")
        dtend = (now + timedelta(days=days_offset, hours=1)).strftime("%Y%m%dT%H%M%SZ")

        content = (
            f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//\r\n"
            f"BEGIN:VEVENT\r\nUID:{uid}\r\nDTSTART:{dtstart}\r\n"
            f"DTEND:{dtend}\r\nSUMMARY:{summary}\r\n"
        )
        if rrule:
            content += f"RRULE:{rrule}\r\n"

        content += "DESCRIPTION:Desc\r\nLOCATION:Loc\r\nEND:VEVENT\r\nEND:VCALENDAR"
        return content.encode("utf-8")

    def _setup_common_mocks(self, mock_firestore, sync_data, user_data=None):
        """Helper to setup reliable firestore mocks."""
        if user_data is None:
            user_data = {"refresh_token": "dummy_token"}

        mock_db = MagicMock()
        mock_firestore.return_value = mock_db

        # Syncs Collection
        mock_sync_col = MagicMock()
        mock_sync_doc_ref = MagicMock()
        mock_sync_snap = MagicMock()
        mock_sync_snap.exists = True
        mock_sync_snap.to_dict.return_value = sync_data

        mock_sync_col.document.return_value = mock_sync_doc_ref
        mock_sync_doc_ref.get.return_value = mock_sync_snap

        # Users Collection
        mock_user_col = MagicMock()
        mock_user_doc_ref = MagicMock()
        mock_user_snap = MagicMock()
        mock_user_snap.to_dict.return_value = user_data

        mock_user_col.document.return_value = mock_user_doc_ref
        mock_user_doc_ref.get.return_value = mock_user_snap

        def side_effect(name):
            if name == "syncs":
                return mock_sync_col
            if name == "users":
                return mock_user_col
            return MagicMock()

        mock_db.collection.side_effect = side_effect

        return mock_sync_doc_ref

    @patch("app.sync.logic.firestore.client")
    @patch("app.sync.logic.get_client_config")
    @patch("app.sync.logic.Credentials")
    @patch("app.sync.logic.build")
    @patch("app.sync.logic.requests.get")
    def test_sync_calendar_logic_with_prefix(
        self, mock_get, mock_build, mock_creds, mock_config, mock_firestore
    ):
        sync_data = {
            "user_id": "test_user",
            "destination_calendar_id": "dest_cal",
            "source_icals": ["http://test.com/cal.ics"],
            "event_prefix": "TestPrefix",
        }
        self._setup_common_mocks(mock_firestore, sync_data)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = self._get_ical_content("12345", "Meeting")
        mock_get.return_value = mock_response

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_batch = MagicMock()
        mock_service.new_batch_http_request.return_value = mock_batch
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }

        sync_calendar_logic("sync_123")

        self.assertTrue(mock_batch.add.called, "Batch add was not called")
        _, kwargs = mock_service.events.return_value.import_.call_args
        self.assertEqual(kwargs["body"]["summary"], "[TestPrefix] Meeting")

    @patch("app.sync.logic.firestore.client")
    @patch("app.sync.logic.get_client_config")
    @patch("app.sync.logic.Credentials")
    @patch("app.sync.logic.build")
    @patch("app.sync.logic.requests.get")
    def test_sync_calendar_logic_existing_update(
        self, mock_get, mock_build, mock_creds, mock_config, mock_firestore
    ):
        sync_data = {
            "user_id": "test_user",
            "destination_calendar_id": "dest_cal",
            "source_icals": ["http://test.com/cal.ics"],
            "event_prefix": "TestPrefix",
        }
        self._setup_common_mocks(mock_firestore, sync_data)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = self._get_ical_content("12345", "New Summary")
        mock_get.return_value = mock_response

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_batch = MagicMock()
        mock_service.new_batch_http_request.return_value = mock_batch
        # Return existing event
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "google_event_id_xyz", "iCalUID": "12345"}]
        }

        sync_calendar_logic("sync_update")

        self.assertFalse(mock_service.events.return_value.import_.called)
        self.assertTrue(mock_service.events.return_value.update.called)

    @patch("app.sync.logic.firestore.client")
    @patch("app.sync.logic.get_client_config")
    @patch("app.sync.logic.Credentials")
    @patch("app.sync.logic.build")
    @patch("app.sync.logic.requests.get")
    def test_sync_calendar_logic_multiple_sources(
        self, mock_get, mock_build, mock_creds, mock_config, mock_firestore
    ):
        sync_data = {
            "user_id": "test_user_2",
            "destination_calendar_id": "dest_cal_2",
            "sources": [
                {"url": "http://site1.com", "prefix": "P1"},
                {"url": "http://site2.com", "prefix": "P2"},
            ],
        }
        self._setup_common_mocks(mock_firestore, sync_data)

        def get_side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "site1" in url:
                resp.content = self._get_ical_content("one", "Event One")
            else:
                resp.content = self._get_ical_content("two", "Event Two")
            return resp

        mock_get.side_effect = get_side_effect

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_batch = MagicMock()
        mock_service.new_batch_http_request.return_value = mock_batch
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }

        sync_calendar_logic("sync_multi")
        self.assertEqual(mock_batch.add.call_count, 2)

    @patch("app.sync.logic.firestore.client")
    @patch("app.sync.logic.get_client_config")
    @patch("app.sync.logic.Credentials")
    @patch("app.sync.logic.build")
    @patch("app.sync.logic.requests.get")
    def test_sync_calendar_logic_failure(
        self, mock_get, mock_build, mock_creds, mock_config, mock_firestore
    ):
        sync_data = {
            "user_id": "test_user",
            "destination_calendar_id": "dest_cal",
            "source_icals": ["http://fail.com/cal.ics"],
        }
        mock_sync_ref = self._setup_common_mocks(mock_firestore, sync_data)

        mock_get.side_effect = requests.exceptions.RequestException("Fetch failed")

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }

        sync_calendar_logic("sync_fail")

        args, _ = mock_sync_ref.update.call_args
        update_data = args[0]
        self.assertIn(
            "http://fail.com/cal.ics (Failed)", update_data["source_names"].values()
        )

    @patch("app.sync.logic.firestore.client")
    @patch("app.sync.logic.get_client_config")
    @patch("app.sync.logic.Credentials")
    @patch("app.sync.logic.build")
    @patch("app.sync.logic.requests.get")
    def test_sync_filters_old_events(
        self, mock_get, mock_build, mock_creds, mock_config, mock_firestore
    ):
        """Test that events older than 30 days are filtered out."""
        sync_data = {
            "user_id": "test_user",
            "destination_calendar_id": "dest_cal",
            "source_icals": ["http://test.com/cal.ics"],
        }
        self._setup_common_mocks(mock_firestore, sync_data)

        # Generate event 40 days in the past
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = self._get_ical_content(
            "old_event", "Old Event", days_offset=-40
        )
        mock_get.return_value = mock_response

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_batch = MagicMock()
        mock_service.new_batch_http_request.return_value = mock_batch
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }

        sync_calendar_logic("sync_filter")

        # Verify NO batch add calls (filtered out)
        self.assertFalse(mock_batch.add.called)

    @patch("app.sync.logic.firestore.client")
    @patch("app.sync.logic.get_client_config")
    @patch("app.sync.logic.Credentials")
    @patch("app.sync.logic.build")
    @patch("app.sync.logic.requests.get")
    def test_sync_keeps_old_recurring_events(
        self, mock_get, mock_build, mock_creds, mock_config, mock_firestore
    ):
        """Test that events with RRULE are KEPT even if start date is old."""
        sync_data = {
            "user_id": "test_user",
            "destination_calendar_id": "dest_cal",
            "source_icals": ["http://test.com/cal.ics"],
        }
        self._setup_common_mocks(mock_firestore, sync_data)

        # Generate event 100 days in the past BUT with RRULE
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = self._get_ical_content(
            "recurring_event", "Recurring Event", days_offset=-100, rrule="FREQ=WEEKLY"
        )
        mock_get.return_value = mock_response

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_batch = MagicMock()
        mock_service.new_batch_http_request.return_value = mock_batch
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }

        sync_calendar_logic("sync_recurring_keep")

        # Verify batch add WAS called (kept)
        self.assertTrue(mock_batch.add.called)


if __name__ == "__main__":
    unittest.main()
