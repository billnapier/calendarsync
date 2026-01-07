# pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments,unused-argument,wrong-import-position
import unittest
import os

os.environ["TESTING"] = "1"
from unittest.mock import patch, MagicMock
import requests
from app.app import sync_calendar_logic


class TestSyncLogic(unittest.TestCase):

    @patch("app.app.firestore.client")
    @patch("app.app.get_client_config")
    @patch("app.app.Credentials")
    @patch("app.app.build")
    @patch("app.app.requests.get")
    def test_sync_calendar_logic_with_prefix(
        self, mock_get, mock_build, mock_creds, mock_config, mock_firestore
    ):
        # Setup Mocks
        mock_db = MagicMock()
        mock_firestore.return_value = mock_db

        # Mock Sync Document (Legacy Structure)
        mock_sync_ref = MagicMock()
        mock_sync_doc = MagicMock()
        mock_sync_doc.exists = True
        mock_sync_doc.to_dict.return_value = {
            "user_id": "test_user",
            "destination_calendar_id": "dest_cal",
            "source_icals": ["http://test.com/cal.ics"],
            "event_prefix": "TestPrefix",
        }
        mock_db.collection.return_value.document.return_value = mock_sync_ref
        mock_sync_ref.get.return_value = mock_sync_doc

        # Mock User Document
        mock_user_ref = MagicMock()
        mock_user_doc = MagicMock()
        mock_user_doc.to_dict.return_value = {"refresh_token": "dummy_token"}

        mock_sync_col = MagicMock()
        mock_sync_col.document.return_value = mock_sync_ref

        mock_user_col = MagicMock()
        mock_user_col.document.return_value = mock_user_ref

        def collection_side_effect(name):
            if name == "syncs":
                return mock_sync_col
            if name == "users":
                return mock_user_col
            return MagicMock()

        mock_db.collection.side_effect = collection_side_effect

        # Mock requests.get for iCal
        mock_response = MagicMock()
        mock_response.status_code = 200
        # Minimal iCal content with one event (UID 12345)
        mock_response.content = (
            b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//\r\n"
            b"BEGIN:VEVENT\r\nUID:12345\r\nDTSTART:20230101T120000Z\r\n"
            b"DTEND:20230101T130000Z\r\nSUMMARY:Meeting\r\n"
            b"DESCRIPTION:Discuss stuff\r\nLOCATION:Office\r\n"
            b"END:VEVENT\r\nEND:VCALENDAR"
        )
        mock_get.return_value = mock_response

        # Mock Google Calendar Service
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_batch = MagicMock()
        mock_service.new_batch_http_request.return_value = mock_batch

        # Mock events().list() to return NO existing events -> Should trigger import
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }

        # Run Logic
        sync_calendar_logic("sync_123")

        # Verify Batch Add was called
        self.assertTrue(mock_batch.add.called, "Batch add was not called")

        # Inspect arguments to batch.add (Should be import_)
        import_call_args = mock_service.events.return_value.import_.call_args
        self.assertIsNotNone(import_call_args, "Should call import_ for new event")
        _, kwargs = import_call_args
        body = kwargs["body"]

        self.assertEqual(body["iCalUID"], "12345")
        self.assertEqual(body["summary"], "[TestPrefix] Meeting")
        self.assertEqual(body["description"], "Discuss stuff")
        self.assertEqual(body["location"], "Office")

    @patch("app.app.firestore.client")
    @patch("app.app.get_client_config")
    @patch("app.app.Credentials")
    @patch("app.app.build")
    @patch("app.app.requests.get")
    def test_sync_calendar_logic_existing_update(
        self, mock_get, mock_build, mock_creds, mock_config, mock_firestore
    ):
        """Test that existing events trigger an update() call."""
        # Setup Mocks
        mock_db = MagicMock()
        mock_firestore.return_value = mock_db

        mock_sync_doc = MagicMock()
        mock_sync_doc.exists = True
        mock_sync_doc.to_dict.return_value = {
            "user_id": "test_user",
            "destination_calendar_id": "dest_cal",
            "source_icals": ["http://test.com/cal.ics"],
            "event_prefix": "TestPrefix",
        }
        mock_sync_ref = MagicMock()
        mock_sync_ref.get.return_value = mock_sync_doc

        mock_user_doc = MagicMock()
        mock_user_doc.to_dict.return_value = {"refresh_token": "dummy_token"}

        # Collection Side Effects
        mock_sync_col = MagicMock()
        mock_sync_col.document.return_value = mock_sync_ref
        mock_user_col = MagicMock()
        mock_user_col.document.return_value = MagicMock()  # user ref
        mock_user_col.document.return_value.get.return_value = mock_user_doc

        def collection_side_effect(name):
            if name == "syncs":
                return mock_sync_col
            if name == "users":
                return mock_user_col
            return MagicMock()

        mock_db.collection.side_effect = collection_side_effect

        # Mock requests.get for iCal (UID 12345)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = (
            b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            b"BEGIN:VEVENT\r\nUID:12345\r\nDTSTART:20230101T120000Z\r\n"
            b"DTEND:20230101T130000Z\r\nSUMMARY:New Summary\r\n"
            b"END:VEVENT\r\nEND:VCALENDAR"
        )
        mock_get.return_value = mock_response

        # Mock Service
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_batch = MagicMock()
        mock_service.new_batch_http_request.return_value = mock_batch

        # Mock events().list() to return EXISTING event with iCalUID 12345
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "google_event_id_xyz", "iCalUID": "12345"}]
        }

        # Run Logic
        sync_calendar_logic("sync_update")

        # Verify: Should call update(), NOT import_()
        self.assertFalse(mock_service.events.return_value.import_.called)
        self.assertTrue(mock_service.events.return_value.update.called)

        # Check call args
        update_call = mock_service.events.return_value.update.call_args
        _, kwargs = update_call
        self.assertEqual(kwargs["calendarId"], "dest_cal")
        self.assertEqual(kwargs["eventId"], "google_event_id_xyz")
        self.assertEqual(kwargs["body"]["summary"], "[TestPrefix] New Summary")
        self.assertNotIn("iCalUID", kwargs["body"])  # Should be removed for update

    @patch("app.app.firestore.client")
    @patch("app.app.get_client_config")
    @patch("app.app.Credentials")
    @patch("app.app.build")
    @patch("app.app.requests.get")
    def test_sync_calendar_logic_multiple_sources(
        self, mock_get, mock_build, mock_creds, mock_config, mock_firestore
    ):
        """Test with new data structure: multiple sources and different prefixes."""
        # Setup Mocks
        mock_db = MagicMock()
        mock_firestore.return_value = mock_db

        # Mock Sync Document (New Structure)
        mock_sync_ref = MagicMock()
        mock_sync_doc = MagicMock()
        mock_sync_doc.exists = True
        mock_sync_doc.to_dict.return_value = {
            "user_id": "test_user_2",
            "destination_calendar_id": "dest_cal_2",
            "sources": [
                {"url": "http://site1.com/cal.ics", "prefix": "P1"},
                {"url": "http://site2.com/cal.ics", "prefix": "P2"},
            ],
        }
        mock_db.collection.return_value.document.return_value = mock_sync_ref
        mock_sync_ref.get.return_value = mock_sync_doc

        # User Mock
        mock_user_doc = MagicMock()
        mock_user_doc.to_dict.return_value = {"refresh_token": "dummy_token"}

        mock_sync_col = MagicMock()
        mock_sync_col.document.return_value = mock_sync_ref

        mock_user_col = MagicMock()
        # Mock the chain: db.collection("users").document(...).get()
        mock_user_col.document.return_value.get.return_value = mock_user_doc

        def collection_side_effect(name):
            if name == "syncs":
                return mock_sync_col
            if name == "users":
                return mock_user_col
            return MagicMock()

        mock_db.collection.side_effect = collection_side_effect

        # Mock requests.get
        def get_side_effect(url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "site1" in url:
                resp.content = (
                    b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
                    b"BEGIN:VEVENT\r\nUID:one\r\nDTSTART:20230101T090000Z\r\n"
                    b"DTEND:20230101T100000Z\r\nSUMMARY:Event One\r\n"
                    b"END:VEVENT\r\nEND:VCALENDAR"
                )
            else:
                resp.content = (
                    b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
                    b"BEGIN:VEVENT\r\nUID:two\r\nDTSTART:20230101T110000Z\r\n"
                    b"DTEND:20230101T120000Z\r\nSUMMARY:Event Two\r\n"
                    b"END:VEVENT\r\nEND:VCALENDAR"
                )
            return resp

        mock_get.side_effect = get_side_effect

        # Mock Service
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_batch = MagicMock()
        mock_service.new_batch_http_request.return_value = mock_batch

        # Mock list() -> Empty (trigger imports)
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }

        # Run
        sync_calendar_logic("sync_multi")

        # Verify
        self.assertEqual(mock_batch.add.call_count, 2)

        # Check calls
        calls = mock_service.events.return_value.import_.call_args_list
        summaries = []
        for call_args in calls:
            _, kwargs = call_args
            summaries.append(kwargs["body"]["summary"])

        self.assertIn("[P1] Event One", summaries)
        self.assertIn("[P2] Event Two", summaries)

    @patch("app.app.firestore.client")
    @patch("app.app.get_client_config")
    @patch("app.app.Credentials")
    @patch("app.app.build")
    @patch("app.app.requests.get")
    def test_sync_calendar_logic_failure(
        self, mock_get, mock_build, mock_creds, mock_config, mock_firestore
    ):
        # Mock Exception on Fetch
        mock_get.side_effect = requests.exceptions.RequestException("Fetch failed")

        mock_db = MagicMock()
        mock_firestore.return_value = mock_db

        # Mock Sync Document (No prefix this time)
        mock_sync_doc = MagicMock()
        mock_sync_doc.exists = True
        mock_sync_doc.to_dict.return_value = {
            "user_id": "test_user",
            "destination_calendar_id": "dest_cal",
            "source_icals": ["http://fail.com/cal.ics"],
        }

        # Simplify mocking for failure case using side_effect logic from above
        mock_sync_ref = MagicMock()
        mock_sync_ref.get.return_value = mock_sync_doc

        mock_user_ref = MagicMock()
        mock_user_doc = MagicMock()
        mock_user_doc.to_dict.return_value = {"refresh_token": "dummy_token"}
        mock_user_ref.get.return_value = mock_user_doc

        mock_sync_col = MagicMock()
        mock_sync_col.document.return_value = mock_sync_ref

        mock_user_col = MagicMock()
        mock_user_col.document.return_value = mock_user_ref

        def collection_effect(name):
            if name == "syncs":
                return mock_sync_col
            if name == "users":
                return mock_user_col
            return MagicMock()

        mock_db.collection.side_effect = collection_effect

        # Mock Service (needed for list() call before failure?)
        # Fetching sources happens BEFORE fetching existing events to optimize.
        # Wait, if sources fail, do we proceed?
        # Code:
        # all_events_items, source_names = _fetch_source_events(sources, user_id)
        # sync_ref.update(...)
        # existing_map = _get_existing_events_map(...)

        # So yes, we need to mock service creation at least
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        # Mocking list is important now too
        mock_service.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }

        # Run
        sync_calendar_logic("sync_fail")

        # Verify update was called with failure message
        args, _ = mock_sync_ref.update.call_args
        # args[0] is the dict
        update_data = args[0]
        self.assertIn(
            "http://fail.com/cal.ics (Failed)", update_data["source_names"].values()
        )


if __name__ == "__main__":
    unittest.main()
