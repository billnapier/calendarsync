import os
import sys
import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

os.environ["TESTING"] = "1"
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from app.app import app as flask_app
from app.smart_filter.logic import (
    parse_and_extract_candidate_events,
    call_gemini_filter_batch,
    rebuild_filtered_ics,
    _compute_source_hash,
    _compute_prompt_hash,
)

SAMPLE_ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test iCal//EN
X-WR-CALNAME:Test Feed
BEGIN:VEVENT
UID:event-1-exams
SUMMARY:CS 101 Midterm Exam
DESCRIPTION:<p>Important midterm exam in <b>Hall A</b>.</p>
LOCATION:Hall A
DTSTART:20260901T100000Z
DTEND:20260901T120000Z
END:VEVENT
BEGIN:VEVENT
UID:event-2-officehours
SUMMARY:CS 101 Office Hours
DESCRIPTION:Drop in office hours with TA.
LOCATION:Room 202
DTSTART:20260902T140000Z
DTEND:20260902T150000Z
END:VEVENT
BEGIN:VEVENT
UID:event-3-recurring
SUMMARY:Weekly Study Group
DESCRIPTION:Recurring study group.
DTSTART:20260903T180000Z
DTEND:20260903T190000Z
RRULE:FREQ=WEEKLY;UNTIL=20261231T235959Z
END:VEVENT
END:VCALENDAR
"""


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    flask_app.secret_key = "test_secret"
    os.environ["FIREBASE_PROJECT_ID"] = "test-project"
    with flask_app.test_client() as test_client:
        yield test_client


def test_parse_and_extract_candidate_events():
    candidates, cal = parse_and_extract_candidate_events(SAMPLE_ICS)
    assert len(candidates) == 3

    # Check first candidate fields & HTML stripping
    cand1 = next(c for c in candidates if c["id"] == "event-1-exams")
    assert cand1["summary"] == "CS 101 Midterm Exam"
    assert cand1["description"] == "Important midterm exam in Hall A."
    assert cand1["location"] == "Hall A"

    # Check recurring event candidate
    cand3 = next(c for c in candidates if c["id"] == "event-3-recurring")
    assert "FREQ=WEEKLY" in cand3["recurs"]


def test_call_gemini_filter_batch_fallback():
    candidates, _ = parse_and_extract_candidate_events(SAMPLE_ICS)

    # Test prompt that excludes office hours
    prompt = "Only include exams and midterms; exclude office hours."
    evaluations = call_gemini_filter_batch(candidates, prompt)

    assert len(evaluations) == 3
    eval_map = {ev.id: ev for ev in evaluations}

    assert eval_map["event-1-exams"].include is True
    assert eval_map["event-2-officehours"].include is False
    assert (
        "office hours" in eval_map["event-2-officehours"].reason.lower()
        or "excluded" in eval_map["event-2-officehours"].reason.lower()
    )


def test_rebuild_filtered_ics():
    candidates, cal = parse_and_extract_candidate_events(SAMPLE_ICS)
    included_uids = {"event-1-exams"}

    rebuilt_bytes = rebuild_filtered_ics(
        cal, included_uids, "Filtered CS 101", "Only exams"
    )

    rebuilt_str = rebuilt_bytes.decode("utf-8")
    assert "CS 101 Midterm Exam" in rebuilt_str
    assert "CS 101 Office Hours" not in rebuilt_str
    assert "X-WR-CALNAME:Filtered CS 101" in rebuilt_str


@patch("app.smart_filter.logic.safe_requests_get")
@patch("firebase_admin.firestore.client")
def test_evaluate_smart_filter_304_caching(mock_firestore_client, mock_get):
    from app.smart_filter.logic import evaluate_smart_filter

    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        "user_id": "test_user_1",
        "name": "Test Filter",
        "source_url": "https://example.com/cal.ics",
        "filter_prompt": "Only exams",
        "etag": '"etag123"',
        "last_modified": "Mon, 17 Aug 2026 00:00:00 GMT",
        "public_url": "https://storage.googleapis.com/bucket/path.ics",
    }

    mock_db = MagicMock()
    mock_firestore_client.return_value = mock_db
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    mock_resp = MagicMock()
    mock_resp.status_code = 304
    mock_get.return_value = mock_resp

    res = evaluate_smart_filter("cal_123", force=False)

    assert res["status"] == "active"
    assert res["changed"] is False
    assert res["reason"] == "304 Not Modified"

    # Verify HTTP request sent If-None-Match header
    mock_get.assert_called_once()
    _, kwargs = mock_get.call_args
    assert kwargs["headers"]["If-None-Match"] == '"etag123"'


def test_create_smart_filter_route_unauthorized(client):
    res = client.get("/smart_filter/create")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


def test_create_smart_filter_route_get(client):
    with client.session_transaction() as sess:
        sess["user"] = {"uid": "user_123", "name": "Test User"}

    res = client.get("/smart_filter/create")
    assert res.status_code == 200
    assert b"Create Smart Filter Calendar" in res.data
    assert b"Experimental" in res.data


@patch("app.smart_filter.routes.evaluate_smart_filter")
@patch("firebase_admin.firestore.client")
def test_create_smart_filter_route_post(mock_firestore_client, mock_eval, client):
    with client.session_transaction() as sess:
        sess["user"] = {"uid": "user_123", "name": "Test User"}
        sess["csrf_token"] = "valid_token"

    mock_db = MagicMock()
    mock_firestore_client.return_value = mock_db
    mock_eval.return_value = {"total_included": 5, "total_evaluated": 10}

    res = client.post(
        "/smart_filter/create",
        data={
            "csrf_token": "valid_token",
            "name": "My Filtered Cal",
            "source_url": "https://example.com/feed.ics",
            "filter_prompt": "Only exams",
        },
        follow_redirects=True,
    )

    assert res.status_code == 200
    assert b"Smart Filter calendar created successfully!" in res.data
    mock_eval.assert_called_once()


@patch("app.smart_filter.routes.test_smart_filter_preview")
def test_test_smart_filter_ajax(mock_preview, client):
    with client.session_transaction() as sess:
        sess["user"] = {"uid": "user_123", "name": "Test User"}
        sess["csrf_token"] = "valid_token"

    mock_preview.return_value = [
        {
            "id": "e1",
            "summary": "CS 101 Midterm",
            "start": "2026-09-01T10:00:00Z",
            "location": "Hall A",
            "include": True,
            "reason": "Matches exam keyword.",
        }
    ]

    res = client.post(
        "/smart_filter/test",
        json={
            "csrf_token": "valid_token",
            "source_url": "https://example.com/feed.ics",
            "filter_prompt": "Only exams",
        },
    )

    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["success"] is True
    assert len(data["evaluations"]) == 1
    assert data["evaluations"][0]["summary"] == "CS 101 Midterm"


@patch("firebase_admin.firestore.client")
def test_smart_filter_status_endpoint(mock_firestore_client, client):
    with client.session_transaction() as sess:
        sess["user"] = {"uid": "user_123", "name": "Test User"}

    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        "user_id": "user_123",
        "status": "active",
        "total_events_evaluated": 15,
        "total_events_included": 5,
        "last_error": None,
    }

    mock_db = MagicMock()
    mock_firestore_client.return_value = mock_db
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    res = client.get("/smart_filter/cal_123/status")
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["status"] == "active"
    assert data["total_events_evaluated"] == 15
    assert data["total_events_included"] == 5
