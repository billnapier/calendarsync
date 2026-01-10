import os
import secrets
from datetime import datetime, timedelta, timezone
from flask import session, current_app
from google.cloud import secretmanager

# Constants moved from app.py
SYNC_WINDOW_PAST_DAYS = 30
SYNC_WINDOW_FUTURE_DAYS = 365


def get_sync_window_dates():
    """Returns the start and end datetimes for the sync window."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=SYNC_WINDOW_PAST_DAYS)
    end = now + timedelta(days=SYNC_WINDOW_FUTURE_DAYS)
    return start, end


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
            # If all parses fail, log a warning and return an empty string
            current_app.logger.warning("Could not parse date string: %s", dt)
            return ""

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
            current_app.logger.warning(
                "Cannot fetch secret %s: GOOGLE_CLOUD_PROJECT not set.", secret_name
            )
            return None

        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{pid}/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:  # pylint: disable=broad-exception-caught
        current_app.logger.error("Failed to fetch secret %s: %s", secret_name, e)
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


def get_base_url():
    """Returns the base serving URL based on the environment."""
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get(
        "FIREBASE_PROJECT_ID"
    )

    url_mapping = {
        "calendarsync-napier-dev": "https://calendarsync-dev.billnapier.com",
        "calendarsync-napier": "https://calendarsync.billnapier.com",
    }
    return url_mapping.get(project_id, "https://calendarsync.billnapier.com")
