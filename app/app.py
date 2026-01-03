"""
CalendarSync Flask Application.
Handles Google OAuth2, session management, and Firestore integration.
"""

import os
import logging
import time
from datetime import datetime, timezone
import json
import re
from flask import Flask, render_template, request, session, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
import firebase_admin
from firebase_admin import firestore
from google.cloud import tasks_v2
from google.cloud import secretmanager
import google_auth_oauthlib.flow
import google.auth.transport.requests
from google.oauth2 import id_token
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

import requests
import icalendar


try:
    from app.security import safe_requests_get
except ImportError:
    from security import safe_requests_get


# Initialize Firebase Admin SDK
# Initialize Firebase Admin SDK
# Skip initialization in development/testing environments to avoid credential errors
if os.environ.get("FLASK_ENV") != "development" and not os.environ.get("TESTING"):
    if not firebase_admin._apps:  # pylint: disable=protected-access
        project_id = os.environ.get("FIREBASE_PROJECT_ID") or os.environ.get(
            "GOOGLE_CLOUD_PROJECT"
        )
        if project_id:
            firebase_admin.initialize_app(options={"projectId": project_id})
        else:
            firebase_admin.initialize_app()

app = Flask(__name__)
# Fix for Cloud Run (HTTPS behind proxy)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

logging.basicConfig(level=logging.INFO)

# Configuration
# Allow OAuthlib to use HTTP for local testing
if os.environ.get("FLASK_ENV") == "development" or os.environ.get("FLASK_DEBUG") == "1":
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# Secret Key
if "SECRET_KEY" in os.environ:
    app.secret_key = os.environ["SECRET_KEY"]
elif (
    os.environ.get("FLASK_ENV") == "development"
    or os.environ.get("FLASK_DEBUG") == "1"
    or os.environ.get("TESTING")
):
    app.secret_key = "dev_key_for_testing_only"
else:
    raise ValueError("No SECRET_KEY set for Flask application")

# OAuth2 Configuration
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar",
]


def get_secret(secret_name):
    """
    Retrieve secret from Environment Variable or Google Secret Manager.
    """
    # 1. Try Environment Variable (Prod / Cloud Run)
    env_val = os.environ.get(secret_name.upper())
    if env_val:
        return env_val
    # 2. Try Secret Manager (Local Dev)
    try:
        pid = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get(
            "FIREBASE_PROJECT_ID"
        )
        if not pid:
            app.logger.warning(
                "Cannot fetch secret %s: GOOGLE_CLOUD_PROJECT not set.", secret_name
            )
            return None

        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{pid}/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.error("Failed to fetch secret %s: %s", secret_name, e)
        return None


def get_client_config():
    """Construct client config for OAuth flow."""
    client_id = get_secret("google_client_id")
    client_secret = get_secret("google_client_secret")

    if not client_id or not client_secret:
        raise ValueError("Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET")

    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


@app.route("/")
def home():
    user = session.get("user")
    syncs = []
    if user:
        db = firestore.client()
        # Fetch user's syncs
        try:
            docs = db.collection("syncs").where("user_id", "==", user["uid"]).stream()
            for doc in docs:
                data = doc.to_dict()
                data["id"] = doc.id
                syncs.append(data)
        except Exception as e:  # pylint: disable=broad-exception-caught
            app.logger.error("Error fetching syncs: %s", e)

    return render_template("index.html", user=user, syncs=syncs)


@app.route("/login")
def login():
    """Initiate Google OAuth2 Flow."""
    try:
        client_config = get_client_config()

        # dynamic redirect_uri based on request (handles localhost vs prod)
        redirect_uri = url_for("oauth2callback", _external=True)
        # Ensure HTTPS for prod if behind proxy/load balancer (Cloud Run usually handles this, but good to ensure)
        if request.headers.get("X-Forwarded-Proto") == "https":
            redirect_uri = redirect_uri.replace("http:", "https:")

        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            client_config, scopes=SCOPES
        )
        flow.redirect_uri = redirect_uri

        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",  # Enforce consent to ensure we get refresh token
        )

        session["state"] = state
        return redirect(authorization_url)
    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.error("Login init error: %s", e)
        return f"Error initializing login: {e}", 500


@app.route("/oauth2callback")
def oauth2callback():
    """Handle OAuth2 callback."""
    state = session.get("state")
    if not state:
        return redirect(url_for("home"))

    try:
        client_config = get_client_config()
        redirect_uri = url_for("oauth2callback", _external=True)
        if request.headers.get("X-Forwarded-Proto") == "https":
            redirect_uri = redirect_uri.replace("http:", "https:")

        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            client_config, scopes=SCOPES, state=state
        )
        flow.redirect_uri = redirect_uri

        flow.fetch_token(authorization_response=request.url)
        credentials = flow.credentials

        # Get user info
        session_request = google.auth.transport.requests.Request()

        # Actually, simpler to just use the token to get user info via an API call or id_token
        # But 'credentials' object has id_token if 'openid' scope was requested

        # Verify ID Token
        # We need the Request object to verify
        id_info = id_token.verify_oauth2_token(
            credentials.id_token, session_request, client_config["web"]["client_id"]
        )

        uid = id_info["sub"]
        email = id_info.get("email")
        name = id_info.get("name")
        picture = id_info.get("picture")

        # Store user & tokens in Firestore
        db = firestore.client()
        user_ref = db.collection("users").document(uid)

        user_data = {
            "name": name,
            "email": email,
            "picture": picture,
            "last_login": firestore.SERVER_TIMESTAMP,  # pylint: disable=no-member
        }

        # IMPORTANT: Store Refresh Token if available
        if credentials.refresh_token:
            user_data["refresh_token"] = credentials.refresh_token

        user_ref.set(user_data, merge=True)

        session["user"] = {"uid": uid, "name": name, "email": email, "picture": picture}
        # Clear state
        session.pop("state", None)

        # Store credentials in session for short-term use if needed
        # session['credentials'] = credentials_to_dict(credentials)

        return redirect(url_for("home"))

    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.error("OAuth callback error: %s", e)
        return f"Authentication failed: {e}", 400


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
                calendar_list = service.calendarList().list().execute()

                for cal in calendar_list.get("items", []):
                    calendars.append(
                        {"id": cal["id"], "summary": cal.get("summary", cal["id"])}
                    )

    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.error("Error fetching calendars: %s", e)

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
    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.warning("Failed to extract name from %s: %s", url, e)
    return url


@app.route("/sync/<sync_id>", methods=["POST"])
def run_sync(sync_id):
    """
    Trigger a sync for a specific sync_id.
    """
    user = session.get("user")
    if not user:
        return redirect(url_for("login"))

    db = firestore.client()
    sync_ref = db.collection("syncs").document(sync_id)
    sync_doc = sync_ref.get()

    if not sync_doc.exists:
        return "Sync not found", 404

    sync_data = sync_doc.to_dict()
    if sync_data["user_id"] != user["uid"]:
        return "Unauthorized", 403

    try:
        sync_calendar_logic(sync_id)
        return redirect(url_for("home"))
    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.error("Sync failed: %s", e)
        return f"Sync failed: {e}", 500


@app.route("/edit_sync/<sync_id>", methods=["GET", "POST"])
def edit_sync(sync_id):
    user = session.get("user")
    if not user:
        return redirect(url_for("login"))

    db = firestore.client()
    sync_ref = db.collection("syncs").document(sync_id)
    sync_doc = sync_ref.get()

    if not sync_doc.exists:
        return "Sync not found", 404

    sync_data = sync_doc.to_dict()
    sync_data["id"] = sync_doc.id
    if sync_data["user_id"] != user["uid"]:
        return "Unauthorized", 403

    if request.method == "GET":
        # Refresh calendars cache if needed
        if (
            "calendars" not in session
            or time.time() - session.get("calendars_timestamp", 0) > 300
        ):
            calendars = fetch_user_calendars(user["uid"])
            session["calendars"] = calendars
            session["calendars_timestamp"] = time.time()
        else:
            calendars = session.get("calendars")

        if "sources" not in sync_data:
            # Backward compatibility: Construct sources if missing
            sources = []
            old_icals = sync_data.get("source_icals", [])
            old_prefix = sync_data.get("event_prefix", "").strip()
            for url in old_icals:
                sources.append({"url": url, "prefix": old_prefix})
            sync_data["sources"] = sources

        return render_template(
            "edit_sync.html", user=user, sync=sync_data, calendars=calendars
        )

    if request.method == "POST":
        app.logger.info("DEBUG: Handling POST for edit_sync")
        # Refresh calendars cache if needed
        if (
            "calendars" not in session
            or time.time() - session.get("calendars_timestamp", 0) > 300
        ):

            try:
                calendars = fetch_user_calendars(user["uid"])
                session["calendars"] = calendars
                session["calendars_timestamp"] = time.time()
            except Exception as e:  # pylint: disable=broad-exception-caught
                app.logger.error("Failed to fetch calendars on edit POST: %s", e)
                calendars = session.get("calendars")
        else:
            # calendars = session.get("calendars") # Optimized out
            pass

        return _handle_edit_sync_post(request, sync_ref, session.get("calendars"))

    return "Method not allowed", 405


def _get_sources_from_form(form):
    """Helper to extract sources from form data and sanitize them."""
    urls = form.getlist("source_urls")
    prefixes = form.getlist("source_prefixes")
    sources = []

    for i, url in enumerate(urls):
        url = url.strip()
        if not url:
            continue
        prefix = ""
        if i < len(prefixes):
            raw_prefix = prefixes[i].strip()
            # Allow alphanumerics, spaces, dashes, underscores, brackets
            # Remove anything else to prevent HTML injection etc.
            prefix = re.sub(r"[^a-zA-Z0-9 \-_\[\]\(\)]", "", raw_prefix)

        sources.append({"url": url, "prefix": prefix})
    return sources


def _handle_edit_sync_post(req, sync_ref, calendars):
    """Handle POST request for edit_sync."""
    destination_id = req.form.get("destination_calendar_id")
    sources = _get_sources_from_form(req.form)

    if not destination_id:
        return "Destination Calendar ID is required", 400

    # Lookup friendly name
    destination_summary = destination_id
    if calendars:
        for cal in calendars:
            if cal["id"] == destination_id:
                destination_summary = cal["summary"]
                break

    # Re-fetch source names
    source_names = {}
    try:
        for source in sources:
            url = source["url"]
            source_names[url] = get_calendar_name_from_ical(url)
    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.warning("Failed to refresh names on edit: %s", e)

    sync_ref.update(
        {
            "destination_calendar_id": destination_id,
            "destination_calendar_summary": destination_summary,
            "sources": sources,
            "source_names": source_names,
            "updated_at": firestore.SERVER_TIMESTAMP,  # pylint: disable=no-member
        }
    )

    return redirect(url_for("home"))


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


def _fetch_source_events(sources):
    """
    Fetch and parse events from source iCal URLs.
    Returns a list of dicts: {'component': event, 'prefix': prefix}
    """
    all_events_items = []
    source_names = {}

    for source in sources:
        url = source["url"]
        prefix = source.get("prefix", "")

        try:
            response = safe_requests_get(url, timeout=10)
            response.raise_for_status()
            cal = icalendar.Calendar.from_ical(response.content)

            # Extract name
            cal_name = cal.get("X-WR-CALNAME")
            source_names[url] = str(cal_name) if cal_name else url

            for component in cal.walk():
                if component.name == "VEVENT":
                    all_events_items.append({"component": component, "prefix": prefix})
        except (
            requests.exceptions.RequestException,
            ValueError,
        ) as e:  # pylint: disable=broad-exception-caught
            app.logger.error("Failed to fetch/parse %s: %s", url, e)
            source_names[url] = f"{url} (Failed)"

    return all_events_items, source_names


def _batch_upsert_events(service, destination_id, events_items):
    """
    Batch upsert events to Google Calendar.
    events_items: list of {'component': event_obj, 'prefix': str}
    """
    # pylint: disable=no-member
    batch = service.new_batch_http_request()

    def batch_callback(request_id, _response, exception):
        if exception:
            app.logger.error("Failed to import event %s: %s", request_id, exception)

    for item in events_items:
        event = item["component"]
        prefix = item["prefix"]

        uid = event.get("UID")
        if not uid:
            continue
        uid = str(uid)

        start = _parse_event_dt(event.get("DTSTART"))
        end = _parse_event_dt(event.get("DTEND"))

        if not end and start:
            end = _calculate_end_time(event.get("DTSTART"), event.get("DURATION"))

        if not start:
            continue

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

        batch.add(
            service.events().import_(calendarId=destination_id, body=body),
            request_id=uid,
            callback=batch_callback,
        )

    try:
        batch.execute()
    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.error("Batch execution failed: %s", e)


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


def sync_calendar_logic(sync_id):
    """
    Core logic to sync events from source iFals to destination Google Calendar.
    """
    db = firestore.client()
    sync_ref = db.collection("syncs").document(sync_id)
    sync_doc = sync_ref.get()
    if not sync_doc.exists:
        app.logger.error("Sync logic called for non-existent sync_id: %s", sync_id)
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
    all_events_items, source_names = _fetch_source_events(sources)

    # Update source names and last sync time
    sync_ref.update(
        {
            "source_names": source_names,
            "last_synced_at": firestore.SERVER_TIMESTAMP,  # pylint: disable=no-member
        }
    )

    # 3. Process Events
    _batch_upsert_events(service, destination_id, all_events_items)


def _handle_create_sync_post(user):
    destination_id = request.form.get("destination_calendar_id")
    sources = _get_sources_from_form(request.form)

    if not destination_id:
        return "Destination Calendar ID is required", 400

    # Lookup destination summary from cached calendars
    destination_summary = destination_id
    user_calendars = session.get("calendars")

    # If calendars are missing from the session.
    # We check for the *absence* of the key to avoid re-fetching if the user
    # legitimately has an empty list of calendars.
    if "calendars" not in session:
        try:
            user_calendars = fetch_user_calendars(user["uid"])
            if user_calendars:
                session["calendars"] = user_calendars
                session["calendars_timestamp"] = time.time()
        except Exception as e:  # pylint: disable=broad-exception-caught
            app.logger.error("Failed to fetch calendars on create POST: %s", e)

    if user_calendars:
        for cal in user_calendars:
            if cal["id"] == destination_id:
                destination_summary = cal["summary"]
                break

    db = firestore.client()
    new_sync_ref = db.collection("syncs").document()
    new_sync_ref.set(
        {
            "user_id": user["uid"],
            "destination_calendar_id": destination_id,
            "destination_calendar_summary": destination_summary,
            "sources": sources,
            "created_at": firestore.SERVER_TIMESTAMP,  # pylint: disable=no-member
        }
    )

    # Populate source names asynchronously (or just do it now for simplicity)
    try:
        source_names = {}
        for source in sources:
            url = source["url"]
            source_names[url] = get_calendar_name_from_ical(url)
        new_sync_ref.update({"source_names": source_names})
    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.warning("Failed to populate initial source names: %s", e)

    return redirect(url_for("home"))


@app.route("/create_sync", methods=["GET", "POST"])
def create_sync():
    user = session.get("user")
    if not user:
        return redirect(url_for("login"))

    if request.method == "GET":
        # Cache calendars in session for 5 minutes to avoid repeated API calls.
        if (
            "calendars" not in session
            or time.time() - session.get("calendars_timestamp", 0) > 300
        ):
            app.logger.info("Fetching calendars from API (cache miss or expired)")
            calendars = fetch_user_calendars(user["uid"])
            session["calendars"] = calendars
            session["calendars_timestamp"] = time.time()
        else:
            app.logger.info("Using cached calendars")
            calendars = session.get("calendars")

        return render_template("create_sync.html", user=user, calendars=calendars)

    if request.method == "POST":
        return _handle_create_sync_post(user)

    return "Method not allowed", 405


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# ... (rest of imports removed from here)

# ... (existing code)


@app.route("/tasks/sync_one", methods=["POST"])
def sync_one_user():
    """
    Worker endpoint to sync a single user.
    Called by Cloud Tasks.
    """
    sync_id = None
    try:
        payload = request.get_json()
        if not payload or "sync_id" not in payload:
            app.logger.error("Invalid payload for sync_one: %s", payload)
            return "Invalid payload", 400

        sync_id = payload["sync_id"]
        app.logger.info("Worker starting sync for sync_id: %s", sync_id)

        sync_calendar_logic(sync_id)

        return "Sync successful", 200
    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.error("Worker failed for sync_id %s: %s", sync_id, e)
        # Return 500 to trigger Cloud Tasks retry
        return f"Worker failed: {e}", 500


@app.route("/tasks/sync_all", methods=["POST"])
def sync_all_users():
    """
    Dispatcher endpoint.
    Triggered by Cloud Scheduler, enqueues tasks for all users.
    """
    app.logger.info("Starting global sync dispatch...")

    db = firestore.client()
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get(
        "FIREBASE_PROJECT_ID"
    )
    location = os.environ.get("GCP_REGION", "us-central1")
    queue = "sync-queue"
    invoker_email = os.environ.get("SCHEDULER_INVOKER_EMAIL")

    if not project or not invoker_email:
        app.logger.error("Missing required env vars for Cloud Tasks dispatch")
        return "Configuration error", 500

    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(project, location, queue)

    try:
        syncs = db.collection("syncs").stream()
        count = 0

        for sync_doc in syncs:
            sync_id = sync_doc.id

            # Construct Task
            task = {
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": url_for("sync_one_user", _external=True),
                    "headers": {"Content-Type": "application/json"},
                    "oidc_token": {
                        "service_account_email": invoker_email,
                    },
                }
            }

            payload = {"sync_id": sync_id}
            task["http_request"]["body"] = json.dumps(payload).encode()

            try:
                client.create_task(request={"parent": parent, "task": task})
                count += 1
            except Exception as e:  # pylint: disable=broad-exception-caught
                app.logger.error(
                    "Failed to enqueue task for sync_id %s: %s", sync_id, e
                )

        app.logger.info("Dispatched %d sync tasks.", count)
        return f"Dispatched {count} tasks", 200

    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.error("Critical error in dispatcher: %s", e)
        return f"Internal failure: {e}", 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=True, host="0.0.0.0", port=port)
