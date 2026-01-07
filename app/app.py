# pylint: disable=too-many-lines
import os
import logging
import time
import concurrent.futures
from datetime import datetime, timedelta, timezone
import json
import re
import secrets

import requests
import icalendar
from flask import Flask, render_template, request, session, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
import firebase_admin
from firebase_admin import firestore
import google_auth_oauthlib.flow
from google.cloud import tasks_v2
from google.cloud import secretmanager
import google.api_core.exceptions
import google.auth.transport.requests
from google.oauth2 import id_token
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

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

# Firebase Hosting requires the session cookie to be named '__session'
app.config["SESSION_COOKIE_NAME"] = "__session"
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


@app.after_request
def add_security_headers(response):
    """Add security headers to all responses."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # A basic CSP to enhance security. This should be tailored to your app's needs.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://accounts.google.com/gsi/client; "
        "style-src 'self' 'unsafe-inline'; "
        "object-src 'none'; "
        "frame-ancestors 'self';"
    )
    # Disable features that are not needed.
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # Strict-Transport-Security is often handled by the load balancer, but good to have.
    # The 'preload' directive can be added for enhanced security, but requires commitment to HTTPS.
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains; preload"
    )
    return response


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

CALENDAR_LIST_FIELDS = "items(id,summary)"
EVENT_LIST_FIELDS = (
    "summary,nextPageToken,items(id,summary,description,location,start,end)"
)


def generate_csrf_token():
    """Generate a CSRF token and store it in the session."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


def verify_csrf_token(form_token):
    """Verify the CSRF token from the form against the session."""
    session_token = session.get("csrf_token")
    if not session_token or not form_token or session_token != form_token:
        return False
    return True


@app.template_filter("time_ago")
def time_ago_filter(dt):
    """Returns a relative time string (e.g., '2 hours ago')."""
    if not dt:
        return ""
    if isinstance(dt, str):
        # Try parsing various formats
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
        ):
            try:
                dt = datetime.strptime(dt, fmt)
                break
            except ValueError:
                continue
        else:
            # If all parses fail, return duplicate original string
            return dt

    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    diff = now - dt
    seconds = diff.total_seconds()

    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        minutes = int(seconds // 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"

    days = int(seconds // 86400)
    return f"{days} day{'s' if days != 1 else ''} ago"


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
def index():
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

    try:
        client_config = get_client_config()
        google_client_id = client_config["web"]["client_id"]
    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.warning("Failed to load client config: %s", e)
        google_client_id = None

    return render_template(
        "index.html", user=user, syncs=syncs, google_client_id=google_client_id
    )


@app.route("/auth/google/callback", methods=["POST"])
def google_auth_callback():  # pylint: disable=too-many-locals
    """Handle Google Identity Services (GIS) Sign-In Callback."""
    try:
        credential = request.form.get("credential")
        if not credential:
            return "Missing credential", 400

        # Verify CSRF token (g_csrf_token)
        # GIS sets a cookie 'g_csrf_token' and sends a body param 'g_csrf_token'
        # They must match.
        cookie_csrf = request.cookies.get("g_csrf_token")
        body_csrf = request.form.get("g_csrf_token")

        if not cookie_csrf or not body_csrf or cookie_csrf != body_csrf:
            return "Invalid CSRF token", 400

        client_config = get_client_config()
        client_id = client_config["web"]["client_id"]

        # Verify ID Token
        id_info = id_token.verify_oauth2_token(
            credential, google.auth.transport.requests.Request(), client_id
        )

        uid = id_info["sub"]
        email = id_info.get("email")
        name = id_info.get("name")
        picture = id_info.get("picture")

        # Store user in Firestore
        db = firestore.client()
        user_ref = db.collection("users").document(uid)

        # Update basic info
        user_data = {
            "name": name,
            "email": email,
            "picture": picture,
            "last_login": firestore.SERVER_TIMESTAMP,  # pylint: disable=no-member
        }
        # We do NOT set refresh_token here because ID Token flow doesn't give one.
        # We merge so we don't overwrite existing refresh token if it exists.
        user_ref.set(user_data, merge=True)

        session["user"] = {"uid": uid, "name": name, "email": email, "picture": picture}

        # Check if user needs to authorize Calendar access (i.e. missing refresh token)
        # We fetch the document we just updated/merged to check existing fields
        doc = user_ref.get()
        current_data = doc.to_dict()

        if "refresh_token" not in current_data:
            # User is authenticated but not authorized for offline access (Calendar API)
            # Redirect to the full OAuth flow to get permissions
            # Pass login_hint to pre-fill email
            return redirect(url_for("login", login_hint=email))

        return redirect(url_for("index"))

    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.error("GIS callback error: %s", e)
        return "Authentication failed. Please try again.", 400


@app.route("/login")
def login():
    """Initiate Google OAuth2 Flow for Calendar Authorization."""
    try:
        client_config = get_client_config()
        login_hint = request.args.get("login_hint")

        # dynamic redirect_uri based on request (handles localhost vs prod)
        redirect_uri = url_for("oauth2callback", _external=True)
        # Ensure HTTPS for prod if behind proxy/load balancer (Cloud Run usually handles this, but good to ensure)
        if request.headers.get("X-Forwarded-Proto") == "https":
            redirect_uri = redirect_uri.replace("http:", "https:")

        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            client_config, scopes=SCOPES
        )
        flow.redirect_uri = redirect_uri

        kwargs = {
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",  # Enforce consent to ensure we get refresh token
        }

        if login_hint:
            kwargs["login_hint"] = login_hint

        authorization_url, state = flow.authorization_url(**kwargs)

        session["state"] = state
        return redirect(authorization_url)
    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.error("Login init error: %s", e)
        return "Error initializing login. Please try again.", 500


@app.route("/oauth2callback")
def oauth2callback():
    """Handle OAuth2 callback."""
    state = session.get("state")
    if not state:
        return redirect(url_for("index"))

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

        return redirect(url_for("index"))

    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.error("OAuth callback error: %s", e)
        return "Authentication failed. Please try again.", 400


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
        return redirect(url_for("index"))
    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.error("Sync failed: %s", e)
        return "Sync failed. Please check logs for details.", 500


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

    if request.method == "POST":
        if not verify_csrf_token(request.form.get("csrf_token")):
            return "Invalid CSRF token", 403

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

    return _handle_edit_sync_get(user, sync_data)


def _handle_edit_sync_get(user, sync_data):
    """Handle GET request for edit_sync."""
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

    csrf_token = generate_csrf_token()
    return render_template(
        "edit_sync.html",
        user=user,
        sync=sync_data,
        calendars=calendars,
        csrf_token=csrf_token,
    )


@app.route("/delete_sync/<sync_id>", methods=["POST"])
def delete_sync(sync_id):
    """
    Delete a specific sync configuration.
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
        # We only remove the configuration, as requested ("remove a sync and all of it's sources").
        sync_ref.delete()
        app.logger.info("Deleted sync %s for user %s", sync_id, user["uid"])
        return redirect(url_for("index"))
    except google.api_core.exceptions.GoogleAPICallError as e:
        app.logger.error("Firestore API error deleting sync %s: %s", sync_id, e)
        return f"Firestore error: {e}", 503
    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.error("Error deleting sync %s: %s", sync_id, e)
        return f"Error deleting sync: {e}", 500


def _get_sources_from_form(form):
    """Helper to extract sources from form data and sanitize them."""
    urls = form.getlist("source_urls")
    prefixes = form.getlist("source_prefixes")
    types = form.getlist("source_types")
    ids = form.getlist("source_ids")

    sources = []

    # Handle legacy/mixed inputs.
    # We iterate based on the maximum length of the lists, but really they should be aligned in the UI.
    # The UI will submit:
    # source_types[], source_urls[] (for ical), source_ids[] (for google), source_prefixes[]

    count = max(len(urls), len(ids), len(types))

    for i in range(count):
        # Default to ical if type is missing (legacy)
        s_type = types[i] if i < len(types) else "ical"
        prefix = ""
        if i < len(prefixes):
            raw_prefix = prefixes[i].strip()
            prefix = re.sub(r"[^a-zA-Z0-9 \-_\[\]\(\)]", "", raw_prefix)

        if s_type == "google":
            if i < len(ids):
                cal_id = ids[i].strip()
                if cal_id:
                    sources.append(
                        {
                            "type": "google",
                            "id": cal_id,
                            "url": cal_id,
                            "prefix": prefix,
                        }
                    )
        else:
            # iCal
            if i < len(urls):
                url = urls[i].strip()
                if url:
                    sources.append({"type": "ical", "url": url, "prefix": prefix})

    return sources


def _resolve_source_names(sources, calendars):
    """
    Efficiently resolve friendly names for sources.
    - sources: list of source dicts
    - calendars: list of Google Calendar dicts (id, summary)
    """
    source_names = {}

    # Create a lookup map for calendar names for efficiency
    cal_map = {cal["id"]: cal["summary"] for cal in calendars} if calendars else {}

    try:
        for source in sources:
            url = source["url"]
            if source.get("type") == "google":
                # Use map for O(1) lookup
                source_names[url] = cal_map.get(source["id"], source["id"])
            else:
                source_names[url] = get_calendar_name_from_ical(url)
    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.warning("Failed to resolve source names: %s", e)

    return source_names


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
    source_names = _resolve_source_names(sources, calendars)

    sync_ref.update(
        {
            "destination_calendar_id": destination_id,
            "destination_calendar_summary": destination_summary,
            "sources": sources,
            "source_names": source_names,
        }
    )

    # Auto-sync immediately after edit
    try:
        sync_calendar_logic(sync_ref.id)
    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.warning("Auto-sync on edit failed: %s", e)

    return redirect(url_for("index"))


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


def _fetch_google_source(source, user_id):
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
        now = datetime.now(timezone.utc)
        time_min = (now - timedelta(days=30)).isoformat()
        time_max = (now + timedelta(days=365)).isoformat()

        events, name = _fetch_all_google_events(
            service, calendar_id, url, time_min=time_min, time_max=time_max
        )

        for gevent in events:
            ievent = _map_google_event_to_ical(gevent)
            events_items.append({"component": ievent, "prefix": prefix})

        return events_items, url, name

    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.error("Failed to fetch Google Calendar %s: %s", url, e)
        return [], url, f"{url} (Failed)"


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
            service.events()  # pylint: disable=no-member
            .list(**list_kwargs)
            .execute()
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
        app.logger.error("Failed to fetch/parse %s: %s", url, e)
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
                app.logger.error("Unexpected error in fetch thread: %s", exc)

    return all_events_items, source_names


def _get_existing_events_map(service, destination_id, time_min=None, time_max=None):
    """
    Fetch all existing events from the destination calendar to support updates.
    Returns a dict mapping iCalUID -> eventId.
    """
    existing_map = {}
    page_token = None

    # Build kwargs
    list_kwargs = {
        "calendarId": destination_id,
        "singleEvents": False,  # We want the master recurring events, not instances
        "fields": "nextPageToken,items(id,iCalUID)",
    }
    if time_min:
        list_kwargs["timeMin"] = time_min
    if time_max:
        list_kwargs["timeMax"] = time_max

    try:
        while True:
            list_kwargs["pageToken"] = page_token
            events_result = (
                service.events()
                .list(**list_kwargs)
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
        app.logger.error("Failed to list existing events: %s", e)
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
            app.logger.error("Failed to upsert event %s: %s", request_id, exception)

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
    # Note: If sources are iCal, we have already fetched everything, but we can still
    # optimize the destination fetch.
    # Ideally we should also filter the parsed iCal events here if we want to be strict,
    # but the biggest win is avoiding fetching thousands of existing events from Google.
    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=30)).isoformat()
    time_max = (now + timedelta(days=365)).isoformat()

    # Fetch existing events map for reliable updates
    existing_map = _get_existing_events_map(
        service, destination_id, time_min=time_min, time_max=time_max
    )
    _batch_upsert_events(service, destination_id, all_events_items, existing_map)


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
    # Populate source names asynchronously (or just do it now for simplicity)
    source_names = _resolve_source_names(sources, user_calendars)
    new_sync_ref.update({"source_names": source_names})

    # Auto-sync immediately after creation
    try:
        sync_calendar_logic(new_sync_ref.id)
    except Exception as e:  # pylint: disable=broad-exception-caught
        app.logger.warning("Auto-sync on create failed: %s", e)

    return redirect(url_for("index"))


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

        csrf_token = generate_csrf_token()
        return render_template(
            "create_sync.html", user=user, calendars=calendars, csrf_token=csrf_token
        )

    if request.method == "POST":
        if not verify_csrf_token(request.form.get("csrf_token")):
            return "Invalid CSRF token", 403
        return _handle_create_sync_post(user)

    return "Method not allowed", 405


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


def verify_task_auth():
    """Verifies that the request is authorized by a service account."""
    if os.environ.get("FLASK_ENV") == "development":
        return

    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise ValueError("Missing Authorization header")

    parts = auth_header.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ValueError("Invalid Authorization header format")

    token = parts[1]

    try:
        request_obj = google.auth.transport.requests.Request()
        # Verify the token.
        # Note: We are not verifying audience here because it depends on the
        # dynamic service URL which is not always known in this context.
        # However, we rely on strict allow-listing of the invoker email.
        id_info = id_token.verify_oauth2_token(token, request_obj)

        email = id_info.get("email")
        allowed_email = os.environ.get("SCHEDULER_INVOKER_EMAIL")

        # Fail closed: If no allow-list email is configured, deny everything.
        if not allowed_email:
            app.logger.error("SCHEDULER_INVOKER_EMAIL not set. Denying task access.")
            raise ValueError("Configuration error: SCHEDULER_INVOKER_EMAIL not set")

        if email != allowed_email:
            raise ValueError(f"Unauthorized email: {email}")

    except Exception as e:
        raise ValueError(f"Invalid token: {e}") from e


@app.route("/tasks/sync_one", methods=["POST"])
def sync_one_user():
    """
    Worker endpoint to sync a single user.
    Called by Cloud Tasks.
    """
    try:
        verify_task_auth()
    except ValueError as e:
        app.logger.warning("Auth failed: %s", e)
        return "Unauthorized", 403

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
        return "Worker failed. Please check logs for details.", 500


@app.route("/tasks/sync_all", methods=["POST"])
def sync_all_users():
    """
    Dispatcher endpoint.
    Triggered by Cloud Scheduler, enqueues tasks for all users.
    """
    try:
        verify_task_auth()
    except ValueError as e:
        app.logger.warning("Auth failed: %s", e)
        return "Unauthorized", 403

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
        return "Internal failure. Please check logs for details.", 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=True, host="0.0.0.0", port=port)
