import logging
import concurrent.futures
from datetime import datetime, timezone
import requests
import icalendar
from firebase_admin import firestore
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import google.api_core.exceptions
from flask import current_app

from app.utils import get_client_config, get_sync_window_dates
from app.security import safe_requests_get

# Constants
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar",
]

CALENDAR_LIST_FIELDS = "items(id,summary)"
EVENT_LIST_FIELDS = (
    "summary,nextPageToken,items(id,summary,description,location,start,end)"
)

logger = logging.getLogger(__name__)


def fetch_user_calendars(user_uid):
    """Fetch user's Google Calendars using stored refresh token."""
    calendars = []
    try:
        db = firestore.client()
        user_ref = db.collection("users").document(user_uid)
        user_doc = user_ref.get()

        if user_doc.exists:
            user_data = user_doc.to_dict()
            refresh_token = user_data.get("refresh_token")

            if refresh_token:
                client_config = get_client_config()
                creds = Credentials(
                    None,  # No access token initially
                    refresh_token=refresh_token,
                    token_uri=client_config["web"]["token_uri"],
                    client_id=client_config["web"]["client_id"],
                    client_secret=client_config["web"]["client_secret"],
                    scopes=SCOPES,
                )

                service = build("calendar", "v3", credentials=creds)
                # pylint: disable=no-member
                # Optimization: Request only necessary fields to reduce payload size
                calendar_list = (
                    service.calendarList().list(fields=CALENDAR_LIST_FIELDS).execute()
                )

                for cal in calendar_list.get("items", []):
                    calendars.append(
                        {"id": cal["id"], "summary": cal.get("summary", cal["id"])}
                    )

    except google.api_core.exceptions.GoogleAPICallError as e:
        logger.error("Error fetching calendars: %s", e)

    # Sort calendars alphabetically by summary
    calendars.sort(key=lambda x: x["summary"].lower())

    return calendars


def get_calendar_name_from_ical(url):
    """
    Fetches the iCal URL and attempts to extract the calendar name (X-WR-CALNAME).
    Returns the URL if extraction fails or name is not present.
    """
    try:
        response = safe_requests_get(url, timeout=10)
        response.raise_for_status()
        cal = icalendar.Calendar.from_ical(response.content)
        name = cal.get("X-WR-CALNAME")
        if name:
            return str(name)
    except (requests.exceptions.RequestException, ValueError) as e:
        logger.warning("Failed to extract name from %s: %s", url, e)
    return url


def resolve_source_names(sources, calendars):
    """
    Efficiently resolve friendly names for sources.
    - sources: list of source dicts
    - calendars: list of Google Calendar dicts (id, summary)
    """
    source_names = {}
    cal_map = {cal["id"]: cal["summary"] for cal in calendars} if calendars else {}

    ical_sources = []

    try:
        for source in sources:
            url = source["url"]
            if source.get("type") == "google":
                # Use map for O(1) lookup
                source_names[url] = cal_map.get(source["id"], source["id"])
            else:
                ical_sources.append(url)

        if ical_sources:
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_to_url = {
                    executor.submit(get_calendar_name_from_ical, url): url
                    for url in ical_sources
                }
                for future in concurrent.futures.as_completed(future_to_url):
                    url = future_to_url[future]
                    try:
                        source_names[url] = future.result()
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.warning("Error fetching name for %s: %s", url, e)
                        source_names[url] = url

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("Failed to resolve source names: %s", e)

    return source_names


def _parse_event_dt(dt_prop):
    """Helper to parse datetime from iCal property."""
    if dt_prop is None:
        return None
    dt = dt_prop.dt
    if hasattr(dt, "tzinfo") and dt.tzinfo:
        return {"dateTime": dt.isoformat()}

    # All day event or naive datetime
    if isinstance(dt, datetime):
        # Naive datetime: assume UTC
        dt = dt.replace(tzinfo=timezone.utc)
        return {"dateTime": dt.isoformat()}

    # Date object (all day)
    return {"date": dt.isoformat()}


def _calculate_end_time(start_dt_prop, duration_prop):
    """Calculate end time from start and duration."""
    if not start_dt_prop or not duration_prop:
        return None

    start_dt_obj = start_dt_prop.dt
    duration_td = duration_prop.dt
    end_dt_obj = start_dt_obj + duration_td

    if hasattr(end_dt_obj, "tzinfo") and end_dt_obj.tzinfo:
        return {"dateTime": end_dt_obj.isoformat()}
    if isinstance(end_dt_obj, datetime):
        end_dt_obj = end_dt_obj.replace(tzinfo=timezone.utc)
        return {"dateTime": end_dt_obj.isoformat()}
    return {"date": end_dt_obj.isoformat()}


def _fetch_all_google_events(
    service, calendar_id, url, time_min=None, time_max=None
):  # pylint: disable=too-many-arguments
    """Fetch all events from Google Calendar with pagination."""
    events = []
    page_token = None
    name = url  # Default name

    # Build kwargs for list()
    list_kwargs = {
        "calendarId": calendar_id,
        "singleEvents": True,
        "orderBy": "startTime",
        "maxResults": 2500,
        "fields": EVENT_LIST_FIELDS,
    }
    if time_min:
        list_kwargs["timeMin"] = time_min
    if time_max:
        list_kwargs["timeMax"] = time_max

    while True:
        list_kwargs["pageToken"] = page_token
        events_result = (
            service.events().list(**list_kwargs).execute()  # pylint: disable=no-member
        )

        items = events_result.get("items", [])
        events.extend(items)

        if page_token is None:
            # The summary is the same for all pages, so we can get it from the first response.
            name = events_result.get("summary", url)

        page_token = events_result.get("nextPageToken")
        if not page_token:
            break

    return events, name


def _map_google_event_to_ical(gevent):
    """
    Helper to map a single Google API event resource to an icalendar Event.
    """
    ievent = icalendar.Event()

    # Map fields
    if "summary" in gevent:
        ievent.add("summary", gevent["summary"])
    if "description" in gevent:
        ievent.add("description", gevent["description"])
    if "location" in gevent:
        ievent.add("location", gevent["location"])
    if "id" in gevent:
        ievent.add("uid", gevent["id"])

    # Handle Dates
    start = gevent.get("start")
    end = gevent.get("end")

    if start:
        if "dateTime" in start:
            dt = datetime.fromisoformat(start["dateTime"])
            ievent.add("dtstart", dt)
        elif "date" in start:
            ievent.add("dtstart", datetime.strptime(start["date"], "%Y-%m-%d").date())

    if end:
        if "dateTime" in end:
            dt = datetime.fromisoformat(end["dateTime"])
            ievent.add("dtend", dt)
        elif "date" in end:
            ievent.add("dtend", datetime.strptime(end["date"], "%Y-%m-%d").date())

    return ievent


def _get_google_service(db, user_id):
    """Refreshes credentials and returns a Google Calendar service."""
    user_ref = db.collection("users").document(user_id)
    user_data = user_ref.get().to_dict()
    refresh_token = user_data.get("refresh_token")

    if not refresh_token:
        raise ValueError("User has no refresh token")

    client_config = get_client_config()
    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri=client_config["web"]["token_uri"],
        client_id=client_config["web"]["client_id"],
        client_secret=client_config["web"]["client_secret"],
        scopes=SCOPES,
    )
    return build("calendar", "v3", credentials=creds)


def _fetch_google_source(source, user_id):  # pylint: disable=too-many-locals
    """
    Fetch events from a Google Calendar and convert to iCal components.
    """
    url = source.get("url", source.get("id"))
    prefix = source.get("prefix", "")
    events_items = []

    try:
        db = firestore.client()
        service = _get_google_service(db, user_id)
        calendar_id = source.get("id")

        # Define sync window: 30 days past -> 365 days future
        start, end = get_sync_window_dates()
        time_min = start.isoformat()
        time_max = end.isoformat()

        events, name = _fetch_all_google_events(
            service, calendar_id, url, time_min=time_min, time_max=time_max
        )

        for gevent in events:
            ievent = _map_google_event_to_ical(gevent)
            events_items.append({"component": ievent, "prefix": prefix})

        return events_items, url, name

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to fetch Google Calendar %s: %s", url, e)
        return [], url, f"{url} (Failed)"


def _fetch_single_source(source, user_id):
    """
    Helper to fetch a single source.
    Returns (events_list, url, name) or ([], url, failed_name)
    """
    if source.get("type") == "google":
        return _fetch_google_source(source, user_id)

    url = source["url"]
    prefix = source.get("prefix", "")
    events_items = []

    try:
        response = safe_requests_get(url, timeout=10)
        response.raise_for_status()
        cal = icalendar.Calendar.from_ical(response.content)

        # Extract name
        cal_name = cal.get("X-WR-CALNAME")
        name = str(cal_name) if cal_name else url

        for component in cal.walk():
            if component.name == "VEVENT":
                events_items.append({"component": component, "prefix": prefix})

        return events_items, url, name

    except (
        requests.exceptions.RequestException,
        ValueError,
    ) as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to fetch/parse %s: %s", url, e)
        return [], url, f"{url} (Failed)"


def _fetch_source_events(sources, user_id):
    """
    Fetch and parse events from source iCal URLs in parallel.
    Returns:
        events_items: list of dicts: {'component': event, 'prefix': prefix}
        source_names: dict of {url: friendly_name}
    """
    all_events_items = []
    source_names = {}

    # Use ThreadPoolExecutor for parallel fetching
    # Limit max_workers to avoid hitting system limits or DOSing the network
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        # Submit all tasks
        future_to_source = {
            executor.submit(_fetch_single_source, source, user_id): source
            for source in sources
        }

        # Process results as they complete
        for future in concurrent.futures.as_completed(future_to_source):
            try:
                events, url, name = future.result()
                all_events_items.extend(events)
                source_names[url] = name
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error("Unexpected error in fetch thread: %s", exc)

    return all_events_items, source_names


def _get_existing_events_map(service, destination_id):
    """
    Fetch all existing events from the destination calendar to support updates.
    Returns a dict mapping iCalUID -> eventId.
    """
    existing_map = {}
    page_token = None
    try:
        while True:
            events_result = (
                service.events()
                .list(
                    calendarId=destination_id,
                    pageToken=page_token,
                    singleEvents=False,  # We want the master recurring events, not instances
                    fields="nextPageToken,items(id,iCalUID)",
                )
                .execute()
            )
            for event in events_result.get("items", []):
                ical_uid = event.get("iCalUID")
                event_id = event.get("id")
                if ical_uid and event_id:
                    existing_map[ical_uid] = event_id
            page_token = events_result.get("nextPageToken")
            if not page_token:
                break
    except google.api_core.exceptions.GoogleAPICallError as e:
        logger.error("Failed to list existing events: %s", e)
    return existing_map


def _build_event_body(event, prefix):
    """
    Helper to construct Google Calendar event body.
    """
    uid = event.get("UID")
    if not uid:
        return None, None

    uid = str(uid)
    start = _parse_event_dt(event.get("DTSTART"))
    end = _parse_event_dt(event.get("DTEND"))

    if not end and start:
        end = _calculate_end_time(event.get("DTSTART"), event.get("DURATION"))

    if not start:
        return None, None

    summary = str(event.get("SUMMARY", ""))
    if prefix:
        summary = f"[{prefix}] {summary}"

    body = {
        "summary": summary,
        "description": str(event.get("DESCRIPTION", "")),
        "location": str(event.get("LOCATION", "")),
        "start": start,
        "end": end,
        "iCalUID": uid,
    }

    # Clean None values
    body = {k: v for k, v in body.items() if v is not None}
    return body, uid


def _batch_upsert_events(service, destination_id, events_items, existing_map=None):
    """
    Batch upsert events to Google Calendar.
    events_items: list of {'component': event_obj, 'prefix': str}
    existing_map: dict of {iCalUID: eventId} for existing events
    """
    if existing_map is None:
        existing_map = {}

    # pylint: disable=no-member
    batch = service.new_batch_http_request()

    def batch_callback(request_id, _response, exception):
        if exception:
            logger.error("Failed to upsert event %s: %s", request_id, exception)

    for item in events_items:
        body, uid = _build_event_body(item["component"], item["prefix"])
        if not body:
            continue

        existing_event_id = existing_map.get(uid)

        if existing_event_id:
            # Update existing event
            body_for_update = body.copy()
            del body_for_update["iCalUID"]
            batch.add(
                service.events().update(
                    calendarId=destination_id,
                    eventId=existing_event_id,
                    body=body_for_update,
                    fields="id",
                ),
                request_id=uid,
                callback=batch_callback,
            )
        else:
            # Import new event
            batch.add(
                service.events().import_(
                    calendarId=destination_id, body=body, fields="id"
                ),
                request_id=uid,
                callback=batch_callback,
            )

    try:
        batch.execute()
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Batch execution failed: %s", e)


def sync_calendar_logic(sync_id):  # pylint: disable=too-many-locals
    """
    Core logic to sync events from source iFals to destination Google Calendar.
    """
    db = firestore.client()
    sync_ref = db.collection("syncs").document(sync_id)
    sync_doc = sync_ref.get()
    if not sync_doc.exists:
        logger.error("Sync logic called for non-existent sync_id: %s", sync_id)
        return
    sync_data = sync_doc.to_dict()

    user_id = sync_data["user_id"]
    destination_id = sync_data["destination_calendar_id"]

    # Backward compatibility: Construct sources if missing
    sources = sync_data.get("sources")
    if not sources:
        sources = []
        old_icals = sync_data.get("source_icals", [])
        old_prefix = sync_data.get("event_prefix", "").strip()
        for url in old_icals:
            sources.append({"url": url, "prefix": old_prefix})

    # 1. Get User Credentials
    service = _get_google_service(db, user_id)

    # 2. Fetch and Parse
    all_events_items, source_names = _fetch_source_events(sources, user_id)

    # Update source names and last sync time
    sync_ref.update(
        {
            "source_names": source_names,
            "last_synced_at": firestore.SERVER_TIMESTAMP,  # pylint: disable=no-member
        }
    )

    # 3. Process Events
    # Define sync window: 30 days past -> 365 days future
    window_start, window_end = get_sync_window_dates()

    # Filter source events to ensure we only sync within the window
    # This handles iCal sources that returned everything, and serves as a safety check
    filtered_events = []
    for item in all_events_items:
        event = item["component"]
        # Simple check on DTSTART. Recurring rules (RRULE) are complex,
        # but for a basic sync, checking the start date is a good first approximation.
        # Note: Google Source events are already filtered by the API call in _fetch_google_source
        if "dtstart" in event:
            dt = event["dtstart"].dt
            # Normalize to UTC for comparison
            if isinstance(dt, datetime):
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            else:
                # Date object (all day) - convert to datetime at start of day
                dt = datetime.combine(dt, datetime.min.time()).replace(
                    tzinfo=timezone.utc
                )

            # Check if event is within window OR if it is a recurring rule master (RRULE).
            # We must preserve RRULE masters even if they started long ago,
            # otherwise the entire series will disappear.
            if (window_start <= dt <= window_end) or "rrule" in event:
                filtered_events.append(item)
        else:
            # Event without start? Include just in case or skip.
            # Safe to skip as it won't display anyway.
            pass

    # Fetch existing events map for reliable updates
    # We do NOT filter here to ensure we know about all existing UIDs (especially recurring masters)
    # This prevents creating duplicates of events that started before the window.
    existing_map = _get_existing_events_map(service, destination_id)
    _batch_upsert_events(service, destination_id, filtered_events, existing_map)
