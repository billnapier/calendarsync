"""
CalendarSync Flask Application.
Handles Google OAuth2, session management, and Firestore integration.
"""
import os
import logging
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
    print(f"DEBUG: Starting fetch_user_calendars for {user_uid}")
    try:
        db = firestore.client()
        user_ref = db.collection('users').document(user_uid)
        user_doc = user_ref.get()
        
        if user_doc.exists:
            user_data = user_doc.to_dict()
            refresh_token = user_data.get('refresh_token')
            
            if refresh_token:
                print(f"DEBUG: Found refresh token for {user_uid}, building credentials...")
                client_config = get_client_config()
                creds = Credentials(
                    None, # No access token initially
                    refresh_token=refresh_token,
                    token_uri=client_config['web']['token_uri'],
                    client_id=client_config['web']['client_id'],
                    client_secret=client_config['web']['client_secret'],
                    scopes=SCOPES
                )
                
                print("DEBUG: Calling Google Calendar API...")
                service = build('calendar', 'v3', credentials=creds)
                calendar_list = service.calendarList().list().execute()
                
                items = calendar_list.get('items', [])
                print(f"DEBUG: Calendar API response items count: {len(items)}")
                
                for cal in items:
                    calendars.append({
                        'id': cal['id'],
                        'summary': cal.get('summary', cal['id'])
                    })
            else:
                print(f"DEBUG: No refresh token found for user {user_uid}")
        else:
             print(f"DEBUG: User document not found for {user_uid}")
                    
    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"DEBUG: Error fetching calendars: {e}")
        app.logger.error("Error fetching calendars: %s", e)
    
    return calendars

@app.route('/create_sync', methods=['GET', 'POST'])
def create_sync():
    user = session.get('user')
    if not user:
        return redirect(url_for('login'))

    if request.method == 'GET':
        calendars = fetch_user_calendars(user['uid'])
        return render_template('create_sync.html', user=user, calendars=calendars)

    if request.method == 'POST':
        destination_id = request.form.get('destination_calendar_id')
        ical_urls = request.form.getlist('ical_urls')
        # Filter empty URLs
        ical_urls = [url for url in ical_urls if url.strip()]

        if not destination_id:
            return "Destination Calendar ID is required", 400

        db = firestore.client()
        new_sync_ref = db.collection('syncs').document()
        new_sync_ref.set({
            'user_id': user['uid'],
            'destination_calendar_id': destination_id,
            'source_icals': ical_urls,
            'created_at': firestore.SERVER_TIMESTAMP # pylint: disable=no-member
        })

        return redirect(url_for('home'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=True, host='0.0.0.0', port=port)


