"""
CalendarSync Flask Application.
Handles Google OAuth2, session management, and Firestore integration.
"""
import os
import logging
import time
from datetime import datetime, timezone
# Third-party libraries
from flask import Flask, render_template, request, session, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
import firebase_admin
from firebase_admin import firestore
import google_auth_oauthlib.flow
from google.cloud import secretmanager
import google.auth.transport.requests
from google.oauth2 import id_token
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import requests
import icalendar





# Initialize Firebase Admin SDK
if not firebase_admin._apps: # pylint: disable=protected-access
    project_id = os.environ.get('FIREBASE_PROJECT_ID') or os.environ.get('GOOGLE_CLOUD_PROJECT')
    if project_id:
        firebase_admin.initialize_app(options={'projectId': project_id})
    else:
        firebase_admin.initialize_app()

app = Flask(__name__)
# Fix for Cloud Run (HTTPS behind proxy)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

logging.basicConfig(level=logging.INFO)

# Configuration
# Allow OAuthlib to use HTTP for local testing
if os.environ.get('FLASK_ENV') == 'development' or os.environ.get('FLASK_DEBUG') == '1':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# Secret Key
if 'SECRET_KEY' in os.environ:
    app.secret_key = os.environ['SECRET_KEY']
elif os.environ.get('FLASK_ENV') == 'development' or os.environ.get('FLASK_DEBUG') == '1':
    app.secret_key = 'dev_key_for_testing_only'
else:
    raise ValueError("No SECRET_KEY set for Flask application")

# OAuth2 Configuration
SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/calendar'
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
        pid = os.environ.get('GOOGLE_CLOUD_PROJECT') or os.environ.get('FIREBASE_PROJECT_ID')
        if not pid:
            app.logger.warning("Cannot fetch secret %s: GOOGLE_CLOUD_PROJECT not set.", secret_name)
            return None

        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{pid}/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e: # pylint: disable=broad-exception-caught
        app.logger.error("Failed to fetch secret %s: %s", secret_name, e)
        return None

def get_client_config():
    """Construct client config for OAuth flow."""
    client_id = get_secret('google_client_id')
    client_secret = get_secret('google_client_secret')

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

@app.route('/')
def home():
    user = session.get('user')
    syncs = []
    if user:
        db = firestore.client()
        # Fetch user's syncs
        try:
            docs = db.collection('syncs').where('user_id', '==', user['uid']).stream()
            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id
                syncs.append(data)
        except Exception as e: # pylint: disable=broad-exception-caught
            app.logger.error("Error fetching syncs: %s", e)

    return render_template('index.html', user=user, syncs=syncs)

@app.route('/login')
def login():
    """Initiate Google OAuth2 Flow."""
    try:
        client_config = get_client_config()

        # dynamic redirect_uri based on request (handles localhost vs prod)
        redirect_uri = url_for('oauth2callback', _external=True)
        # Ensure HTTPS for prod if behind proxy/load balancer (Cloud Run usually handles this, but good to ensure)
        if request.headers.get('X-Forwarded-Proto') == 'https':
            redirect_uri = redirect_uri.replace('http:', 'https:')

        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            client_config,
            scopes=SCOPES)
        flow.redirect_uri = redirect_uri

        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent' # Enforce consent to ensure we get refresh token
        )

        session['state'] = state
        return redirect(authorization_url)
    except Exception as e: # pylint: disable=broad-exception-caught
        app.logger.error("Login init error: %s", e)
        return f"Error initializing login: {e}", 500

@app.route('/oauth2callback')
def oauth2callback():
    """Handle OAuth2 callback."""
    state = session.get('state')
    if not state:
        return redirect(url_for('home'))

    try:
        client_config = get_client_config()
        redirect_uri = url_for('oauth2callback', _external=True)
        if request.headers.get('X-Forwarded-Proto') == 'https':
            redirect_uri = redirect_uri.replace('http:', 'https:')

        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            state=state)
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
            credentials.id_token, session_request, client_config['web']['client_id']
        )

        uid = id_info['sub']
        email = id_info.get('email')
        name = id_info.get('name')
        picture = id_info.get('picture')

        # Store user & tokens in Firestore
        db = firestore.client()
        user_ref = db.collection('users').document(uid)

        user_data = {
            'name': name,
            'email': email,
            'picture': picture,
            'last_login': firestore.SERVER_TIMESTAMP, # pylint: disable=no-member
        }

        # IMPORTANT: Store Refresh Token if available
        if credentials.refresh_token:
            user_data['refresh_token'] = credentials.refresh_token

        user_ref.set(user_data, merge=True)

        session['user'] = {
            'uid': uid,
            'name': name,
            'email': email,
            'picture': picture
        }
        # Clear state
        session.pop('state', None)

        # Store credentials in session for short-term use if needed
        # session['credentials'] = credentials_to_dict(credentials)

        return redirect(url_for('home'))

    except Exception as e: # pylint: disable=broad-exception-caught
        app.logger.error("OAuth callback error: %s", e)
        return f"Authentication failed: {e}", 400

def fetch_user_calendars(user_uid):
    """Fetch user's Google Calendars using stored refresh token."""
    calendars = []
    try:
        db = firestore.client()
        user_ref = db.collection('users').document(user_uid)
        user_doc = user_ref.get()

        if user_doc.exists:
            user_data = user_doc.to_dict()
            refresh_token = user_data.get('refresh_token')

            if refresh_token:
                client_config = get_client_config()
                creds = Credentials(
                    None, # No access token initially
                    refresh_token=refresh_token,
                    token_uri=client_config['web']['token_uri'],
                    client_id=client_config['web']['client_id'],
                    client_secret=client_config['web']['client_secret'],
                    scopes=SCOPES
                )

                service = build('calendar', 'v3', credentials=creds)
                calendar_list = service.calendarList().list().execute()

                for cal in calendar_list.get('items', []):
                    calendars.append({
                        'id': cal['id'],
                        'summary': cal.get('summary', cal['id'])
                    })

    except Exception as e: # pylint: disable=broad-exception-caught
        app.logger.error("Error fetching calendars: %s", e)

    # Sort calendars alphabetically by summary
    calendars.sort(key=lambda x: x['summary'].lower())

    return calendars

def get_calendar_name_from_ical(url):
    """
    Fetches the iCal URL and attempts to extract the calendar name (X-WR-CALNAME).
    Returns the URL if extraction fails or name is not present.
    """
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        cal = icalendar.Calendar.from_ical(response.content)
        name = cal.get('X-WR-CALNAME')
        if name:
            return str(name)
    except Exception as e: # pylint: disable=broad-exception-caught
        app.logger.warning("Failed to extract name from %s: %s", url, e)
    return url

@app.route('/sync/<sync_id>', methods=['POST'])
def run_sync(sync_id):
    """
    Trigger a sync for a specific sync_id.
    """
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))

    db = firestore.client()
    sync_ref = db.collection('syncs').document(sync_id)
    sync_doc = sync_ref.get()

    if not sync_doc.exists:
        return "Sync not found", 404

    sync_data = sync_doc.to_dict()
    if sync_data['user_id'] != user['uid']:
        return "Unauthorized", 403

    try:
        sync_calendar_logic(sync_id)
        return redirect(url_for('home'))
    except Exception as e: # pylint: disable=broad-exception-caught
        app.logger.error("Sync failed: %s", e)
        return f"Sync failed: {e}", 500

@app.route('/edit_sync/<sync_id>', methods=['GET', 'POST'])
def edit_sync(sync_id):
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))

    db = firestore.client()
    sync_ref = db.collection('syncs').document(sync_id)
    sync_doc = sync_ref.get()

    if not sync_doc.exists:
        return "Sync not found", 404

    sync_data = sync_doc.to_dict()
    sync_data['id'] = sync_doc.id
    if sync_data['user_id'] != user['uid']:
        return "Unauthorized", 403

    if request.method == 'GET':
        # Refresh calendars cache if needed
        if 'calendars' not in session or time.time() - session.get('calendars_timestamp', 0) > 300:
            calendars = fetch_user_calendars(user['uid'])
            session['calendars'] = calendars
            session['calendars_timestamp'] = time.time()
        else:
            calendars = session.get('calendars')

        return render_template('edit_sync.html', user=user, sync=sync_data, calendars=calendars)

    if request.method == 'POST':
        destination_id = request.form.get('destination_calendar_id')
        ical_urls = request.form.getlist('ical_urls')
        event_prefix = request.form.get('event_prefix', '').strip()

        ical_urls = [url for url in ical_urls if url.strip()]

        if not destination_id:
            return "Destination Calendar ID is required", 400

        # Lookup friendly name
        destination_summary = destination_id
        if 'calendars' in session:
            for cal in session['calendars']:
                if cal['id'] == destination_id:
                    destination_summary = cal['summary']
                    break

        # Re-fetch source names
        source_names = {}
        try:
            for url in ical_urls:
                source_names[url] = get_calendar_name_from_ical(url)
        except Exception as e: # pylint: disable=broad-exception-caught
            app.logger.warning("Failed to refresh names on edit: %s", e)

        sync_ref.update({
            'destination_calendar_id': destination_id,
            'destination_calendar_summary': destination_summary,
            'source_icals': ical_urls,
            'source_names': source_names,
            'event_prefix': event_prefix,
            'updated_at': firestore.SERVER_TIMESTAMP # pylint: disable=no-member
        })

        return redirect(url_for('home'))

def sync_calendar_logic(sync_id):
    """
    Core logic to sync events from source iFals to destination Google Calendar.
    """
    db = firestore.client()
    sync_ref = db.collection('syncs').document(sync_id)
    sync_doc = sync_ref.get()
    sync_data = sync_doc.to_dict()

    user_id = sync_data['user_id']
    destination_id = sync_data['destination_calendar_id']
    source_icals = sync_data['source_icals']
    event_prefix = sync_data.get('event_prefix', '').strip()

    # 1. Get User Credentials
    user_ref = db.collection('users').document(user_id)
    user_data = user_ref.get().to_dict()
    refresh_token = user_data.get('refresh_token')

    if not refresh_token:
        raise ValueError("User has no refresh token")

    client_config = get_client_config()
    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri=client_config['web']['token_uri'],
        client_id=client_config['web']['client_id'],
        client_secret=client_config['web']['client_secret'],
        scopes=SCOPES
    )
    service = build('calendar', 'v3', credentials=creds)

    # 2. Fetch and Parse parsed sources
    all_events = []
    source_names = {}

    for url in source_icals:
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            cal = icalendar.Calendar.from_ical(response.content)

            # Extract name
            cal_name = cal.get('X-WR-CALNAME')
            if cal_name:
                source_names[url] = str(cal_name)
            else:
                source_names[url] = url

            for component in cal.walk():
                if component.name == "VEVENT":
                    all_events.append(component)
        except Exception as e: # pylint: disable=broad-exception-caught
            app.logger.error("Failed to fetch/parse %s: %s", url, e)
            source_names[url] = f"{url} (Failed)"

    # Update source names and last sync time
    sync_ref.update({
        'source_names': source_names,
        'last_synced_at': firestore.SERVER_TIMESTAMP # pylint: disable=no-member
    })

    # 3. Process Events
    # Google Calendar events are keyed by 'iCalUID'.
    # We will iterate through extracted events and upsert them to Google Calendar.

    # Batching would be ideal here, but for simplicity we'll do one-by-one for now
    # or use simple iteration.

    # Batching for performance
    batch = service.new_batch_http_request()

    def batch_callback(request_id, _response, exception):
        if exception:
            app.logger.error("Failed to import event %s: %s", request_id, exception)
        # else: success

    for event in all_events:
        uid = event.get('UID')
        if not uid:
            continue

        # Convert ical output to string
        uid = str(uid)

        # Basic fields
        summary = str(event.get('SUMMARY', ''))
        description = str(event.get('DESCRIPTION', ''))
        location = str(event.get('LOCATION', ''))

        # Apply Prefix
        if event_prefix:
            summary = f"[{event_prefix}] {summary}"

        # Date parsing helper
        def parse_dt(dt_prop):
            if dt_prop is None:
                return None
            dt = dt_prop.dt
            if hasattr(dt, 'tzinfo') and dt.tzinfo:
                return {'dateTime': dt.isoformat()}

            # All day event or naive datetime
            if isinstance(dt, datetime):
                # Naive datetime, assume it's floating time but Google Calendar needs a timezone or UTC.
                # Best effort: assume UTC or use 'Z' suffix if pure naive.
                # Or better: set it to UTC.
                dt = dt.replace(tzinfo=timezone.utc)
                return {'dateTime': dt.isoformat()}

            # Date object (all day)
            return {'date': dt.isoformat()}

        start = parse_dt(event.get('DTSTART'))
        end = parse_dt(event.get('DTEND'))

        # Fallback for end time if missing
        if not end and start:
            # logic to calculate end from duration could go here
            pass

        if not start:
            continue

        body = {
            'summary': summary,
            'description': description,
            'location': location,
            'start': start,
            'end': end,
            'iCalUID': uid
        }

        # Clean None values
        body = {k: v for k, v in body.items() if v is not None}

        batch.add(
            service.events().import_(
                calendarId=destination_id,
                body=body
            ),
            request_id=uid,
            callback=batch_callback
        )

    try:
        batch.execute()
    except Exception as e: # pylint: disable=broad-exception-caught
        app.logger.error("Batch execution failed: %s", e)


@app.route('/create_sync', methods=['GET', 'POST'])
def create_sync():
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))

    if request.method == 'GET':
        # Cache calendars in session for 5 minutes to avoid repeated API calls.
        if 'calendars' not in session or time.time() - session.get('calendars_timestamp', 0) > 300:
            app.logger.info("Fetching calendars from API (cache miss or expired)")
            calendars = fetch_user_calendars(user['uid'])
            session['calendars'] = calendars
            session['calendars_timestamp'] = time.time()
        else:
            app.logger.info("Using cached calendars")
            calendars = session.get('calendars')

        return render_template('create_sync.html', user=user, calendars=calendars)

    if request.method == 'POST':
        destination_id = request.form.get('destination_calendar_id')
        ical_urls = request.form.getlist('ical_urls')
        # Filter empty URLs
        ical_urls = [url for url in ical_urls if url.strip()]

        if not destination_id:
            return "Destination Calendar ID is required", 400

        event_prefix = request.form.get('event_prefix', '').strip()

        # Lookup destination summary from cached calendars
        # Note: 'calendars' might not be in session if user came directly to POST?
        # Ideally we should fetch again if not in session, or just store ID if fetch fails.
        # For robustness, let's try to get it from session, else unknown.
        # But wait, we just fetched or checked cache in GET, but this is POST.
        # Let's check session.
        destination_summary = destination_id
        if 'calendars' in session:
            for cal in session['calendars']:
                if cal['id'] == destination_id:
                    destination_summary = cal['summary']
                    break
        else:
            # Fallback: could fetch again, but for now defaults to ID.
            pass

        db = firestore.client()
        new_sync_ref = db.collection('syncs').document()
        new_sync_ref.set({
            'user_id': user['uid'],
            'destination_calendar_id': destination_id,
            'destination_calendar_summary': destination_summary,
            'source_icals': ical_urls,
            'event_prefix': event_prefix,
            'created_at': firestore.SERVER_TIMESTAMP # pylint: disable=no-member
        })

        # Populate source names asynchronously (or just do it now for simplicity)
        try:
            source_names = {}
            for url in ical_urls:
                source_names[url] = get_calendar_name_from_ical(url)
            new_sync_ref.update({'source_names': source_names})
        except Exception as e: # pylint: disable=broad-exception-caught
            app.logger.warning("Failed to populate initial source names: %s", e)


        return redirect(url_for('home'))

    return "Method not allowed", 405

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=True, host='0.0.0.0', port=port)
