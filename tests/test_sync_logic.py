# pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments,unused-argument
import unittest
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

        # Mock Sync Document
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
        # Needed because sync_calendar_logic calls db.collection('users').document(user_id)
        # We need to trace the exact calls or just make the chain return this.

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
        # Minimal iCal content with one event
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

        # Run Logic
        sync_calendar_logic("sync_123")

        # Verify Batch Add was called
        # We want to check that body['summary'] starts with "[TestPrefix]"
        self.assertTrue(mock_batch.add.called, "Batch add was not called")

        # Inspect arguments to batch.add
        # call_args_list[0] is (args, kwargs)
        # args[0] is the request object from service.events().import_
        # But we mocked service.events().import_, so we can check that call directly.
        import_call = mock_service.events.return_value.import_.call_args
        self.assertIsNotNone(import_call)
        _, kwargs = import_call
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
