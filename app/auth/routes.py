from flask import request, session, redirect, url_for, current_app
from firebase_admin import firestore
import google_auth_oauthlib.flow
import google.auth.transport.requests
from google.oauth2 import id_token
from app.auth import auth_bp
from app.utils import get_client_config

# Constants (should match app.py until potential further refactor)
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar",
]

@auth_bp.route("/auth/google/callback", methods=["POST"])
def google_auth_callback():
    """Handle Google Identity Services (GIS) Sign-In Callback."""
    try:
        credential = request.form.get("credential")
        if not credential:
            return "Missing credential", 400

        # Verify CSRF token (g_csrf_token)
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
            "last_login": firestore.SERVER_TIMESTAMP,
        }
        # We do NOT set refresh_token here because ID Token flow doesn't give one.
        user_ref.set(user_data, merge=True)

        session["user"] = {"uid": uid, "name": name, "email": email, "picture": picture}

        # Check if user needs to authorize Calendar access
        doc = user_ref.get()
        current_data = doc.to_dict()

        if "refresh_token" not in current_data:
            return redirect(url_for("auth.login", login_hint=email))

        return redirect(url_for("main.index"))

    except Exception as e:
        current_app.logger.error("GIS callback error: %s", e)
        return "Authentication failed. Please try again.", 400


@auth_bp.route("/login")
def login():
    """Initiate Google OAuth2 Flow for Calendar Authorization."""
    try:
        client_config = get_client_config()
        login_hint = request.args.get("login_hint")

        # dynamic redirect_uri
        redirect_uri = url_for("auth.oauth2callback", _external=True)
        if request.headers.get("X-Forwarded-Proto") == "https":
            redirect_uri = redirect_uri.replace("http:", "https:")

        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            client_config, scopes=SCOPES
        )
        flow.redirect_uri = redirect_uri

        kwargs = {
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
        }

        if login_hint:
            kwargs["login_hint"] = login_hint

        authorization_url, state = flow.authorization_url(**kwargs)

        session["state"] = state
        return redirect(authorization_url)
    except Exception as e:
        current_app.logger.error("Login init error: %s", e)
        return "Error initializing login. Please try again.", 500


@auth_bp.route("/oauth2callback")
def oauth2callback():
    """Handle OAuth2 callback."""
    state = session.get("state")
    if not state:
        return redirect(url_for("main.index"))

    try:
        client_config = get_client_config()
        redirect_uri = url_for("auth.oauth2callback", _external=True)
        if request.headers.get("X-Forwarded-Proto") == "https":
            redirect_uri = redirect_uri.replace("http:", "https:")

        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            client_config, scopes=SCOPES, state=state
        )
        flow.redirect_uri = redirect_uri

        flow.fetch_token(authorization_response=request.url)
        credentials = flow.credentials

        session_request = google.auth.transport.requests.Request()

        id_info = id_token.verify_oauth2_token(
            credentials.id_token, session_request, client_config["web"]["client_id"]
        )

        uid = id_info["sub"]
        email = id_info.get("email")
        name = id_info.get("name")
        picture = id_info.get("picture")

        db = firestore.client()
        user_ref = db.collection("users").document(uid)

        user_data = {
            "name": name,
            "email": email,
            "picture": picture,
            "last_login": firestore.SERVER_TIMESTAMP,
        }

        if credentials.refresh_token:
            user_data["refresh_token"] = credentials.refresh_token

        user_ref.set(user_data, merge=True)

        session["user"] = {"uid": uid, "name": name, "email": email, "picture": picture}
        session.pop("state", None)

        return redirect(url_for("main.index"))

    except Exception as e:
        current_app.logger.error("OAuth callback error: %s", e)
        return "Authentication failed. Please try again.", 400
