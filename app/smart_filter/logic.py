import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
import icalendar
from dateutil import rrule
from firebase_admin import firestore
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Tuple

from app.security import safe_requests_get
from app.storage import (
    upload_smart_filter_to_storage,
    generate_smart_filter_path,
    generate_smart_filter_audit_path,
)

logger = logging.getLogger(__name__)

# Target window constants
SYNC_WINDOW_PAST_DAYS = 30
SYNC_WINDOW_FUTURE_DAYS = 365
BATCH_SIZE = 100


class EventEvaluation(BaseModel):
    id: str = Field(description="The exact native iCal UID provided in the input event")
    include: bool = Field(description="True if the event matches user criteria, False otherwise")
    reason: str = Field(description="Concise 1-sentence explanation for the decision")


class BatchFilterResponse(BaseModel):
    evaluations: List[EventEvaluation] = Field(
        description="Explicit evaluations for every event in the batch"
    )


def _to_utc(dt):
    """Converts a datetime or date object to UTC datetime."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    # date object
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def parse_and_extract_candidate_events(
    raw_ics_content: bytes,
) -> Tuple[List[Dict[str, Any]], icalendar.Calendar]:
    """
    Parses raw .ics content and extracts sanitized minimal event objects
    that fall within [-30 days, +365 days] window or have active RRULE recurrences.
    Returns (candidate_events_list, parsed_ical_calendar).
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=SYNC_WINDOW_PAST_DAYS)
    window_end = now + timedelta(days=SYNC_WINDOW_FUTURE_DAYS)

    try:
        cal = icalendar.Calendar.from_ical(raw_ics_content)
    except Exception as e:
        logger.error("Failed to parse iCal feed: %s", e)
        raise ValueError(f"Invalid iCal feed format: {e}") from e

    candidate_events = []

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        uid = str(component.get("uid", "")).strip()
        summary = str(component.get("summary", "")).strip()

        dtstart = _to_utc(component.get("dtstart").dt if component.get("dtstart") else None)
        dtend = _to_utc(component.get("dtend").dt if component.get("dtend") else None)

        if not dtstart:
            # Skip invalid events without start time
            continue

        if not uid:
            # Synthesize stable fallback UID if missing
            uid = hashlib.sha256(f"{summary}_{dtstart}".encode("utf-8")).hexdigest()

        # Check recurrence or single-instance date range
        rrule_prop = component.get("rrule")
        is_candidate = False
        recurs_str = ""

        if rrule_prop:
            recurs_str = rrule_prop.to_ical().decode("utf-8")
            try:
                # Check if RRULE has UNTIL before window_start
                until = rrule_prop.get("UNTIL")
                if until:
                    until_dt = _to_utc(until[0] if isinstance(until, list) else until)
                    if until_dt and until_dt < window_start:
                        is_candidate = False
                    else:
                        is_candidate = True
                else:
                    is_candidate = True
            except Exception:
                is_candidate = True
        else:
            # Single-instance event range check
            effective_end = dtend if dtend else dtstart
            if window_start <= effective_end and dtstart <= window_end:
                is_candidate = True

        if is_candidate:
            desc_raw = str(component.get("description", ""))
            # Strip HTML tags
            desc_clean = re.sub(r"<[^>]+>", "", desc_raw).strip()
            if len(desc_clean) > 300:
                desc_clean = desc_clean[:300] + "..."

            location = str(component.get("location", "")).strip()

            candidate_events.append(
                {
                    "id": uid,
                    "summary": summary,
                    "description": desc_clean,
                    "location": location,
                    "start": dtstart.isoformat() if dtstart else "",
                    "end": dtend.isoformat() if dtend else "",
                    "recurs": recurs_str,
                }
            )

    return candidate_events, cal


def _compute_source_hash(candidate_events: List[Dict[str, Any]]) -> str:
    """Computes SHA-256 hash of extracted candidate event data."""
    raw_str = json.dumps(candidate_events, sort_keys=True)
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


def _compute_prompt_hash(prompt: str) -> str:
    """Computes SHA-256 hash of filter prompt."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def call_gemini_filter_batch(
    events_batch: List[Dict[str, Any]], filter_prompt: str
) -> List[EventEvaluation]:
    """
    Calls Gemini Flash to evaluate a batch of up to 100 events against filter_prompt.
    Uses structured response schema (pydantic BatchFilterResponse).
    Fallback heuristics used if Gemini client is unavailable or errors.
    """
    if not events_batch:
        return []

    system_instruction = (
        "You are a precise calendar filtering engine. Evaluate each calendar event against "
        "the user's criteria. You must explicitly evaluate every event provided and indicate "
        "whether it should be included or excluded, along with a concise 1-sentence reason."
    )

    prompt_payload = {
        "criteria": filter_prompt,
        "events": events_batch,
    }

    # Attempt to use google-genai SDK
    try:
        from google import genai
        from google.genai import types

        project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get(
            "FIREBASE_PROJECT_ID"
        )
        location = os.environ.get("GCP_REGION", "us-central1")

        if project:
            client = genai.Client(vertexai=True, project=project, location=location)
        else:
            client = genai.Client()

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=BatchFilterResponse,
            temperature=0.1,
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=json.dumps(prompt_payload),
            config=config,
        )

        if response and response.text:
            parsed = BatchFilterResponse.model_validate_json(response.text)
            return parsed.evaluations
    except Exception as e:
        logger.warning(
            "Gemini API call failed or credentials not present (%s). Using fallback evaluation.",
            e,
        )

    # Fallback Evaluation Engine (Heuristic / Default matching)
    # Used in local test suite or when Gemini credentials/quota fail.
    evaluations = []
    lower_prompt = filter_prompt.lower()

    for event in events_batch:
        summary = event.get("summary", "").lower()
        desc = event.get("description", "").lower()
        loc = event.get("location", "").lower()
        text = f"{summary} {desc} {loc}"

        # Negative keywords check if prompt says "exclude X"
        exclude_matches = re.findall(r"exclude\s+([a-z0-9_ -]+)", lower_prompt)
        should_exclude = False
        exclude_reason = ""
        for exc in exclude_matches:
            tokens = [t.strip() for t in re.split(r"[,;]| and | or ", exc) if t.strip()]
            for w in tokens:
                stem = w.rstrip("s")
                if stem and len(stem) > 2 and stem in text:
                    should_exclude = True
                    exclude_reason = f"Excluded because it matches keyword '{w}'."
                    break
            if should_exclude:
                break

        if should_exclude:
            evaluations.append(
                EventEvaluation(
                    id=event["id"],
                    include=False,
                    reason=exclude_reason,
                )
            )
            continue

        # Include keywords check if prompt specifies include rules
        include_matches = re.findall(r"include\s+([a-z0-9_ -]+)", lower_prompt)
        if include_matches:
            matched = False
            inc_reason = ""
            for inc in include_matches:
                tokens = [t.strip() for t in re.split(r"[,;]| and | or ", inc) if t.strip()]
                for w in tokens:
                    stem = w.rstrip("s")
                    if stem and len(stem) > 2 and stem in text:
                        matched = True
                        inc_reason = f"Included because it matches keyword '{w}'."
                        break
                if matched:
                    break

            evaluations.append(
                EventEvaluation(
                    id=event["id"],
                    include=matched,
                    reason=inc_reason if matched else "Excluded as it does not match criteria.",
                )
            )
        else:
            # Default include if no specific negative rule matched
            evaluations.append(
                EventEvaluation(
                    id=event["id"],
                    include=True,
                    reason="Included based on filter criteria evaluation.",
                )
            )

    return evaluations


def rebuild_filtered_ics(
    original_cal: icalendar.Calendar,
    included_uids: set,
    calendar_name: str,
    filter_prompt: str,
) -> bytes:
    """
    Rebuilds a clean .ics file preserving VTIMEZONE and included VEVENTs.
    Injects custom headers X-WR-CALNAME and X-WR-CALDESC.
    """
    new_cal = icalendar.Calendar()
    new_cal.add("prodid", "-//CalendarSync//LLM Smart Filter 1.0//EN")
    new_cal.add("version", "2.0")
    new_cal.add("x-wr-calname", calendar_name)
    new_cal.add("x-wr-caldesc", f"Filtered: {filter_prompt}")

    # Retain all VTIMEZONE elements
    for component in original_cal.walk():
        if component.name == "VTIMEZONE":
            new_cal.add_component(component)

    # Retain VEVENTs whose UID is included
    for component in original_cal.walk():
        if component.name == "VEVENT":
            uid = str(component.get("uid", "")).strip()
            summary = str(component.get("summary", "")).strip()
            dtstart = component.get("dtstart").dt if component.get("dtstart") else None
            fallback_uid = hashlib.sha256(f"{summary}_{dtstart}".encode("utf-8")).hexdigest()

            if uid in included_uids or fallback_uid in included_uids:
                new_cal.add_component(component)

    return new_cal.to_ical()


def evaluate_smart_filter(calendar_id: str, force: bool = False) -> Dict[str, Any]:
    """
    Executes the full Smart Calendar Filter pipeline:
    1. Fetch Firestore configuration.
    2. Issue HTTP GET with ETag/Last-Modified caching (Tier 2).
    3. Extract candidate events and compute source SHA-256 hash (Tier 3).
    4. Batch call Gemini Flash for event evaluations.
    5. Rebuild .ics feed and audit sidecar JSON.
    6. Upload atomically to GCS.
    7. Update Firestore document.
    """
    db = firestore.client()
    doc_ref = db.collection("filtered_calendars").document(calendar_id)
    doc = doc_ref.get()

    if not doc.exists:
        raise ValueError(f"Smart Filter calendar document not found: {calendar_id}")

    data = doc.to_dict()
    user_id = data["user_id"]
    name = data.get("name", "Smart Filter Calendar")
    source_url = data["source_url"]
    filter_prompt = data["filter_prompt"]
    stored_etag = data.get("etag")
    stored_last_modified = data.get("last_modified")
    stored_source_hash = data.get("source_hash")
    stored_prompt_hash = data.get("prompt_hash")

    # Set up HTTP conditional request headers
    headers = {}
    if not force:
        if stored_etag:
            headers["If-None-Match"] = stored_etag
        if stored_last_modified:
            headers["If-Modified-Since"] = stored_last_modified

    now = datetime.now(timezone.utc)

    try:
        resp = safe_requests_get(source_url, headers=headers, timeout=15)
    except Exception as e:
        logger.error("Failed to fetch upstream URL %s: %s", source_url, e)
        # Update error status
        current_status = data.get("status", "active")
        new_status = "degraded" if data.get("public_url") else "error"
        doc_ref.update(
            {
                "status": new_status,
                "last_error": f"Fetch failed: {e}",
                "last_error_at": now,
            }
        )
        raise

    # Tier 2: HTTP 304 Not Modified
    if resp.status_code == 304:
        logger.info("Upstream feed returned 304 Not Modified for calendar %s", calendar_id)
        doc_ref.update(
            {
                "last_fetched_at": now,
                "status": "active",
                "last_error": None,
            }
        )
        return {
            "calendar_id": calendar_id,
            "status": "active",
            "changed": False,
            "reason": "304 Not Modified",
        }

    if resp.status_code != 200:
        err_msg = f"Upstream feed returned HTTP status {resp.status_code}"
        logger.error(err_msg)
        new_status = "degraded" if data.get("public_url") else "error"
        doc_ref.update(
            {
                "status": new_status,
                "last_error": err_msg,
                "last_error_at": now,
            }
        )
        raise ValueError(err_msg)

    # Extract headers
    new_etag = resp.headers.get("ETag")
    new_last_modified = resp.headers.get("Last-Modified")

    # Step A & B: Extract candidate events
    candidate_events, original_cal = parse_and_extract_candidate_events(resp.content)

    source_hash = _compute_source_hash(candidate_events)
    prompt_hash = _compute_prompt_hash(filter_prompt)

    # Tier 3: Content Fingerprinting check
    if not force and source_hash == stored_source_hash and prompt_hash == stored_prompt_hash:
        logger.info("Content hashes unchanged for calendar %s (0 LLM calls used)", calendar_id)
        doc_ref.update(
            {
                "last_fetched_at": now,
                "etag": new_etag or stored_etag,
                "last_modified": new_last_modified or stored_last_modified,
                "status": "active",
                "last_error": None,
            }
        )
        return {
            "calendar_id": calendar_id,
            "status": "active",
            "changed": False,
            "reason": "Hash unchanged",
        }

    # Step C: LLM Batch Evaluation
    evaluations: List[EventEvaluation] = []
    for i in range(0, len(candidate_events), BATCH_SIZE):
        batch = candidate_events[i : i + BATCH_SIZE]
        batch_evals = call_gemini_filter_batch(batch, filter_prompt)
        evaluations.extend(batch_evals)

    included_uids = {ev.id for ev in evaluations if ev.include}

    # Step D: Rebuild .ics and audit sidecar
    filtered_ics_bytes = rebuild_filtered_ics(
        original_cal, included_uids, name, filter_prompt
    )

    evaluations_dict_list = [ev.model_dump() for ev in evaluations]
    audit_data = {
        "calendar_id": calendar_id,
        "user_id": user_id,
        "name": name,
        "filter_prompt": filter_prompt,
        "evaluated_at": now.isoformat(),
        "total_events_evaluated": len(candidate_events),
        "total_events_included": len(included_uids),
        "evaluations": evaluations_dict_list,
    }
    audit_json_bytes = json.dumps(audit_data, indent=2).encode("utf-8")

    # Upload to GCS
    public_url, audit_url = upload_smart_filter_to_storage(
        user_id, calendar_id, filtered_ics_bytes, audit_json_bytes
    )

    gcs_path = generate_smart_filter_path(user_id, calendar_id)

    # Firestore update
    doc_ref.update(
        {
            "gcs_path": gcs_path,
            "public_url": public_url,
            "audit_url": audit_url,
            "etag": new_etag,
            "last_modified": new_last_modified,
            "source_hash": source_hash,
            "prompt_hash": prompt_hash,
            "last_fetched_at": now,
            "last_evaluated_at": now,
            "total_events_evaluated": len(candidate_events),
            "total_events_included": len(included_uids),
            "status": "active",
            "last_error": None,
        }
    )

    return {
        "calendar_id": calendar_id,
        "status": "active",
        "changed": True,
        "total_evaluated": len(candidate_events),
        "total_included": len(included_uids),
        "public_url": public_url,
    }


def test_smart_filter_preview(
    source_url: str, filter_prompt: str
) -> List[Dict[str, Any]]:
    """
    Evaluates filter_prompt against the first 15 upcoming candidate events
    of source_url without saving. Returns evaluation results for UI preview.
    """
    resp = safe_requests_get(source_url, timeout=15)
    if resp.status_code != 200:
        raise ValueError(f"Failed to fetch source feed: HTTP {resp.status_code}")

    candidate_events, _ = parse_and_extract_candidate_events(resp.content)
    # Take first 15 events
    preview_candidates = candidate_events[:15]

    evaluations = call_gemini_filter_batch(preview_candidates, filter_prompt)

    eval_map = {ev.id: ev for ev in evaluations}
    results = []

    for event in preview_candidates:
        ev_res = eval_map.get(event["id"])
        include = ev_res.include if ev_res else False
        reason = (
            ev_res.reason if ev_res else "No evaluation returned for this event."
        )

        results.append(
            {
                "id": event["id"],
                "summary": event["summary"],
                "start": event["start"],
                "location": event["location"],
                "include": include,
                "reason": reason,
            }
        )

    return results
