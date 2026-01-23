import logging
import concurrent.futures
from datetime import datetime, timezone
import contextlib
import requests
import icalendar
from firebase_admin import firestore
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import google.api_core.exceptions

from app.utils import get_client_config, get_sync_window_dates, get_base_url
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
    Fetches the iCal URL and attempts to extract the calendar name (X-WR-CALNAME) efficiently.
    Streams the response and stops after finding the name or reading a limit.
    Returns the URL if extraction fails or name is not present.
    """
    try:
        # Stream the response to avoid downloading large files just for the name
        # Use contextlib.closing to ensure response is closed (connection returned to pool)
        # even if we return early.
        with contextlib.closing(
            safe_requests_get(url, timeout=10, stream=True)
        ) as response:
            response.raise_for_status()

            # Read line by line, looking for X-WR-CALNAME
            # Limit to 50KB to avoid excessive processing
            max_bytes = 50 * 1024
            bytes_read = 0

            for line in response.iter_lines(decode_unicode=True):
                if line:
                    bytes_read += len(line)
                    # Normalize line to handle case insensitivity
                    line_upper = line.upper()

                    if line_upper.startswith("X-WR-CALNAME"):
                        # Handle potential parameters (e.g. X-WR-CALNAME;LANGUAGE=en:Name)
                        # Split by first colon
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            return parts[1].strip()

                    # Stop if we hit the limit or see the start of events (name usually comes before)
                    if bytes_read > max_bytes or line_upper.startswith("BEGIN:VEVENT"):
                        break

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


class GoogleEventAdapter:
    """
    Adapts a Google Calendar Event resource to behave like an icalendar.Event
    for read operations needed by sync logic, while retaining the raw dict
    for efficient write operations.
    """

    def __init__(self, google_event):
        self.google_event = google_event
        self._dtstart_prop = None

    def get(self, key, default=None):
        """Mock icalendar.Event.get() for essential keys."""
        key = key.upper()
        if key == "DTSTART":
            if "dtstart" in self:
                return self["dtstart"]
            return default
        if key == "DTEND":
            # Used in _build_event_body if we fallback
            start = self.google_event.get("end")
            if not start:
                return default
            return self._make_prop(start)
        if key == "DURATION":
            return default
        if key == "UID":
            return self.google_event.get("id")
        if key == "SUMMARY":
            return self.google_event.get("summary", "")
        if key == "DESCRIPTION":
            return self.google_event.get("description", "")
        if key == "LOCATION":
            return self.google_event.get("location", "")
        if key == "RRULE":
            if "recurrence" in self.google_event:
                return self.google_event["recurrence"]
            return default
        return default

    def _make_prop(self, date_dict):
        """Creates a dummy object with .dt attribute matching icalendar behavior."""

        class DateProp:  # pylint: disable=too-few-public-methods
            def __init__(self, dt_val):
                self.dt = dt_val

        if "dateTime" in date_dict:
            return DateProp(datetime.fromisoformat(date_dict["dateTime"]))
        if "date" in date_dict:
            return DateProp(datetime.strptime(date_dict["date"], "%Y-%m-%d").date())
        return None

    def __contains__(self, key):
        key = key.lower()
        if key == "dtstart":
            return "start" in self.google_event
        if key == "rrule":
            return "recurrence" in self.google_event
        return False

    def __getitem__(self, key):
        key = key.lower()
        if key == "dtstart":
            if self._dtstart_prop:
                return self._dtstart_prop
            start = self.google_event.get("start")
            if not start:
                raise KeyError(key)
            self._dtstart_prop = self._make_prop(start)
            return self._dtstart_prop
        raise KeyError(key)

    def to_google_body(self, prefix, source_title=None, base_url=None):
        """Fast path to construct Google Calendar body from raw dict."""
        ge = self.google_event
        summary = ge.get("summary", "")
        if prefix:
            summary = f"[{prefix}] {summary}"

        body = {
            "summary": summary,
            "description": ge.get("description", ""),
            "location": ge.get("location", ""),
            "start": ge.get("start"),
            "end": ge.get("end"),
            "iCalUID": ge.get("id"),
        }

        if source_title and base_url:
            body["source"] = {"title": source_title, "url": base_url}

        # Clean None values (though .get() usually returns defaults)
        body = {k: v for k, v in body.items() if v is not None}
        return body, ge.get("id")


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
    return build("calendar", "v3", credentials=creds), creds


def _fetch_google_source_data(
    source, user_id, window_start, window_end
):  # pylint: disable=too-many-locals
    """
    Fetch events from a Google Calendar and convert to iCal components.
    Returns (components, name)
    """
    url = source.get("url", source.get("id"))
    components = []

    try:
        db = firestore.client()
        service, _ = _get_google_service(db, user_id)
        calendar_id = source.get("id")

        time_min = window_start.isoformat()
        time_max = window_end.isoformat()

        events, name = _fetch_all_google_events(
            service, calendar_id, url, time_min=time_min, time_max=time_max
        )

        for gevent in events:
            # Optimization: Use Adapter instead of converting to icalendar object
            adapter = GoogleEventAdapter(gevent)
            components.append(adapter)

        return components, name

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to fetch Google Calendar %s: %s", url, e)
        return [], f"{url} (Failed)"


def _fetch_source_data(source, user_id, window_start, window_end):
    """
    Helper to fetch a single source data (components only).
    Returns (components, name)
    """
    if source.get("type") == "google":
        return _fetch_google_source_data(source, user_id, window_start, window_end)

    url = source["url"]
    components_list = []

    try:
        response = safe_requests_get(url, timeout=10)
        response.raise_for_status()
        cal = icalendar.Calendar.from_ical(response.content)

        # Extract name
        cal_name = cal.get("X-WR-CALNAME")
        name = str(cal_name) if cal_name else url

        # Optimization: Use subcomponents instead of walk() to avoid recursive traversal
        # of children (like VALARM) when we only need top-level VEVENTs.
        for component in cal.subcomponents:
            if component.name != "VEVENT":
                continue

            # FILTERING LOGIC
            # We do filtering here to avoid accumulating huge lists of irrelevant events.
            should_include = False

            # Recurring events (RRULE) are always included to preserve the master series.
            if component.get("RRULE"):
                should_include = True
            elif "dtstart" in component:
                # Check start date against sync window
                dt = component["dtstart"].dt
                # Normalize to UTC for comparison
                if isinstance(dt, datetime):
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                else:
                    # Date object (all day) - convert to datetime at start of day
                    dt = datetime.combine(dt, datetime.min.time()).replace(
                        tzinfo=timezone.utc
                    )

                if window_start <= dt <= window_end:
                    should_include = True

            if should_include:
                components_list.append(component)

        return components_list, name

    except (
        requests.exceptions.RequestException,
        ValueError,
    ) as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to fetch/parse %s: %s", url, e)
        return [], f"{url} (Failed)"


def _fetch_source_events(
    sources, user_id, window_start, window_end
):  # pylint: disable=too-many-locals
    """
    Fetch and parse events from source iCal URLs in parallel.
    Returns:
        events_items: list of dicts: {'component': event, 'prefix': prefix}
        source_names: dict of {url: friendly_name}
    """
    all_events_items = []
    source_names = {}

    # 1. Deduplicate sources by (type, url) to avoid redundant fetching
    unique_sources = {}  # (type, url) -> source
    for source in sources:
        # Use URL as key. For Google sources, url should be same as id usually.
        # Fallback to id if url missing (legacy data?)
        url_key = source.get("url", source.get("id"))
        key = (source.get("type", "ical"), url_key)
        if key not in unique_sources:
            unique_sources[key] = source

    # 2. Fetch unique sources in parallel
    results_map = {}  # key -> (components, name)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_key = {
            executor.submit(
                _fetch_source_data, source, user_id, window_start, window_end
            ): key
            for key, source in unique_sources.items()
        }

        for future in concurrent.futures.as_completed(future_to_key):
            key = future_to_key[future]
            try:
                components, name = future.result()
                results_map[key] = (components, name)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error("Unexpected error in fetch thread for %s: %s", key, exc)
                results_map[key] = ([], "Error")

    # 3. Reconstruct events with prefixes
    for source in sources:
        url_key = source.get("url", source.get("id"))
        key = (source.get("type", "ical"), url_key)

        if key in results_map:
            components, name = results_map[key]
            prefix = source.get("prefix", "")

            # Map source name
            # If multiple sources share URL, the name will be same (last write wins)
            if source.get("url"):
                source_names[source["url"]] = name
            elif source.get("id"):
                source_names[source["id"]] = name

            for component in components:
                all_events_items.append(
                    {"component": component, "prefix": prefix, "source_title": name}
                )

    return all_events_items, source_names


def _create_batch_callback(result_map):
    """Creates a callback function for batch requests that populates result_map."""

    def batch_callback(request_id, response, exception):
        if exception:
            logger.debug(
                "Error fetching existing event UID %s: %s", request_id, exception
            )
            return

        items = response.get("items", [])
        if items:
            event = items[0]
            ical_uid = event.get("iCalUID")
            event_id = event.get("id")
            if ical_uid and event_id:
                result_map[ical_uid] = event_id

    return batch_callback


def _execute_batch_request(service, uids, destination_id, callback):
    """Executes a batch request for a list of UIDs."""
    # pylint: disable=no-member
    batch = service.new_batch_http_request()
    for uid in uids:
        batch.add(
            service.events().list(
                calendarId=destination_id,
                iCalUID=uid,
                fields="items(id,iCalUID)",
            ),
            request_id=uid,
            callback=callback,
        )
    batch.execute()


def _fetch_existing_events_chunk(uids, creds, destination_id):
    """
    Worker function to fetch a chunk of existing events using a dedicated service instance.
    """
    local_map = {}
    try:
        service = build("calendar", "v3", credentials=creds, cache_discovery=True)
        callback = _create_batch_callback(local_map)
        _execute_batch_request(service, uids, destination_id, callback)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error in existing events chunk fetch: %s", e)

    return local_map


def _get_existing_events_map(
    service, destination_id, known_uids=None, creds=None
):  # pylint: disable=too-many-locals,too-many-branches
    """
    Fetch existing events from the destination calendar to support updates.
    Returns a dict mapping iCalUID -> eventId.

    Optimization: If known_uids is provided, fetches only those specific events
    using batch requests. If creds is provided, runs batches in parallel.
    """
    existing_map = {}

    if known_uids is not None:
        # Deduplicate UIDs
        uids_to_fetch = list(set(known_uids))
        if not uids_to_fetch:
            return existing_map

        # Batch limit is 50 for Google Calendar API
        batch_limit = 50

        if creds:
            # Parallel Execution
            chunks = [
                uids_to_fetch[i : i + batch_limit]
                for i in range(0, len(uids_to_fetch), batch_limit)
            ]
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                future_to_chunk = {
                    executor.submit(
                        _fetch_existing_events_chunk, chunk, creds, destination_id
                    ): chunk
                    for chunk in chunks
                }

                for future in concurrent.futures.as_completed(future_to_chunk):
                    try:
                        result_map = future.result()
                        existing_map.update(result_map)
                    except Exception as exc:  # pylint: disable=broad-exception-caught
                        logger.error("Chunk fetch generated an exception: %s", exc)
        else:
            # Sequential Execution (Fallback)
            callback = _create_batch_callback(existing_map)

            for i in range(0, len(uids_to_fetch), batch_limit):
                chunk = uids_to_fetch[i : i + batch_limit]
                try:
                    _execute_batch_request(service, chunk, destination_id, callback)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.error(
                        "Batch execution failed in _get_existing_events_map: %s", e
                    )

        return existing_map

    # Fallback: Fetch ALL events (slow path for backward compatibility or bulk ops)
    page_token = None
    try:
        while True:
            events_result = (
                service.events()
                .list(
                    calendarId=destination_id,
                    pageToken=page_token,
                    singleEvents=False,  # We want the master recurring events, not instances
                    maxResults=2500,  # Optimization: Fetch max allowed events per page
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


def _build_event_body(event, prefix, source_title=None, base_url=None):
    """
    Helper to construct Google Calendar event body.
    """
    # Fast path for Google Sources to avoid re-parsing
    if isinstance(event, GoogleEventAdapter):
        return event.to_google_body(prefix, source_title, base_url)

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

    if source_title and base_url:
        body["source"] = {"title": source_title, "url": base_url}

    # Clean None values
    body = {k: v for k, v in body.items() if v is not None}
    return body, uid


def _batch_upsert_events(
    service, destination_id, events_items, existing_map=None, base_url=None
):
    """
    Batch upsert events to Google Calendar.
    events_items: list of {'component': event_obj, 'prefix': str}
    existing_map: dict of {iCalUID: eventId} for existing events
    """
    if existing_map is None:
        existing_map = {}

    # pylint: disable=no-member
    batch = service.new_batch_http_request()
    batch_count = 0
    BATCH_LIMIT = 50

    def batch_callback(request_id, _response, exception):
        if exception:
            logger.error("Failed to upsert event %s: %s", request_id, exception)

    for item in events_items:
        body, uid = _build_event_body(
            item["component"],
            item["prefix"],
            item.get("source_title"),
            base_url=base_url,
        )
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

        batch_count += 1

        if batch_count >= BATCH_LIMIT:
            try:
                batch.execute()
                # Start a new batch
                batch = service.new_batch_http_request()
                batch_count = 0
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Batch execution failed: %s", e)
                # Depending on failure mode, we might want to continue or stop.
                # Here we continue to try next chunk.
                batch = service.new_batch_http_request()
                batch_count = 0

    if batch_count > 0:
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
    service, creds = _get_google_service(db, user_id)
    base_url = get_base_url()

    # Define sync window: 30 days past -> 365 days future
    window_start, window_end = get_sync_window_dates()

    # 2. Fetch and Parse
    # Pass window dates to filter early and reduce memory/processing
    all_events_items, source_names = _fetch_source_events(
        sources, user_id, window_start, window_end
    )

    # Update source names and last sync time
    sync_ref.update(
        {
            "source_names": source_names,
            "last_synced_at": firestore.SERVER_TIMESTAMP,  # pylint: disable=no-member
        }
    )

    # 3. Process Events
    # Events are now already filtered by _fetch_source_events, so we can skip
    # the second filtering pass.

    # Fetch existing events map for reliable updates
    # Optimization: Only fetch events we plan to sync to avoid listing entire calendar history
    event_uids = []
    for item in all_events_items:
        uid = item["component"].get("UID")
        if uid:
            event_uids.append(str(uid))

    # Ensure credentials are fresh before potentially using them in threads
    if creds and creds.expired:
        try:
            creds.refresh(Request())
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to refresh credentials: %s", e)

    existing_map = _get_existing_events_map(
        service, destination_id, known_uids=event_uids, creds=creds
    )
    _batch_upsert_events(
        service, destination_id, all_events_items, existing_map, base_url=base_url
    )
