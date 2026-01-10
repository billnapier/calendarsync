import logging
import time
import os
import re
import json
from flask import (
    Blueprint,
    render_template,
    session,
    request,
    redirect,
    url_for,
    current_app,
)
from firebase_admin import firestore
import google.api_core.exceptions
from google.cloud import tasks_v2

from app.utils import get_client_config, generate_csrf_token, verify_csrf_token
from app.sync import sync_calendar_logic, fetch_user_calendars, resolve_source_names
from app.security import verify_task_auth

from . import main_bp

logger = logging.getLogger(__name__)


@main_bp.route("/")
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
        except Exception as e:
            logger.error("Error fetching syncs: %s", e)

    try:
        client_config = get_client_config()
        google_client_id = client_config["web"]["client_id"]
    except Exception as e:
        logger.warning("Failed to load client config: %s", e)
        google_client_id = None

    return render_template(
        "index.html", user=user, syncs=syncs, google_client_id=google_client_id
    )


@main_bp.route("/sync/<sync_id>", methods=["POST"])
def run_sync(sync_id):
    """
    Trigger a sync for a specific sync_id.
    """
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.login"))

    # CSRF Protection
    if not verify_csrf_token(request.form.get("csrf_token")):
        logger.warning("Sync failed: Invalid CSRF token")
        return "Invalid CSRF token", 403

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
        return redirect(url_for("main.index"))
    except Exception as e:
        logger.error("Sync failed: %s", e)
        return "Sync failed. Please check logs for details.", 500


def _get_sources_from_form(form):
    """Helper to extract sources from form data and sanitize them."""
    urls = form.getlist("source_urls")
    prefixes = form.getlist("source_prefixes")
    types = form.getlist("source_types")
    ids = form.getlist("source_ids")

    sources = []
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
    source_names = resolve_source_names(sources, calendars)

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
    except Exception as e:
        logger.warning("Auto-sync on edit failed: %s", e)

    return redirect(url_for("main.index"))


def _handle_edit_sync_get(user, sync_data):
    """Handle GET request for edit_sync."""
    # Refresh calendars cache if needed
    if (
        "calendars" not in session
        or time.time() - session.get("calendars_timestamp", 0) > 300
    ):
        try:
            calendars = fetch_user_calendars(user["uid"])
            session["calendars"] = calendars
            session["calendars_timestamp"] = time.time()
        except Exception as e:
            logger.error("Failed to fetch calendars on edit GET: %s", e)
            # Fallback to using potentially stale cache if fetch fails
            calendars = session.get("calendars", [])
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


@main_bp.route("/edit_sync/<sync_id>", methods=["GET", "POST"])
def edit_sync(sync_id):
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.login"))

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

        logger.info("DEBUG: Handling POST for edit_sync")
        # Refresh calendars cache if needed
        if (
            "calendars" not in session
            or time.time() - session.get("calendars_timestamp", 0) > 300
        ):
            try:
                calendars = fetch_user_calendars(user["uid"])
                session["calendars"] = calendars
                session["calendars_timestamp"] = time.time()
            except Exception as e:
                logger.error("Failed to fetch calendars on edit POST: %s", e)
                calendars = session.get("calendars")
        else:
            calendars = session.get("calendars")

        return _handle_edit_sync_post(request, sync_ref, calendars)

    return _handle_edit_sync_get(user, sync_data)


@main_bp.route("/delete_sync/<sync_id>", methods=["POST"])
def delete_sync(sync_id):
    """
    Delete a specific sync configuration.
    """
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.login"))

    # CSRF Protection
    if not verify_csrf_token(request.form.get("csrf_token")):
        logger.warning("Delete sync failed: Invalid CSRF token")
        return "Invalid CSRF token", 403

    db = firestore.client()
    sync_ref = db.collection("syncs").document(sync_id)
    sync_doc = sync_ref.get()

    if not sync_doc.exists:
        return "Sync not found", 404

    sync_data = sync_doc.to_dict()
    if sync_data["user_id"] != user["uid"]:
        return "Unauthorized", 403

    try:
        # We only remove the configuration, as requested.
        sync_ref.delete()
        logger.info("Deleted sync %s for user %s", sync_id, user["uid"])
        return redirect(url_for("main.index"))
    except google.api_core.exceptions.GoogleAPICallError as e:
        logger.error("Firestore API error deleting sync %s: %s", sync_id, e)
        return f"Firestore error: {e}", 503
    except Exception as e:
        logger.error("Error deleting sync %s: %s", sync_id, e)
        return f"Error deleting sync: {e}", 500


def _handle_create_sync_post(user):
    destination_id = request.form.get("destination_calendar_id")
    sources = _get_sources_from_form(request.form)

    if not destination_id:
        return "Destination Calendar ID is required", 400

    # Lookup destination summary from cached calendars
    destination_summary = destination_id
    user_calendars = session.get("calendars")

    # Refresh calendars if missing or stale
    if (
        "calendars" not in session
        or time.time() - session.get("calendars_timestamp", 0) > 300
    ):
        try:
            user_calendars = fetch_user_calendars(user["uid"])
            if user_calendars:
                session["calendars"] = user_calendars
                session["calendars_timestamp"] = time.time()
        except Exception as e:
            logger.error("Failed to fetch calendars on create POST: %s", e)
            # Fallback to using potentially stale cache if available
            user_calendars = session.get("calendars", [])
    else:
        user_calendars = session.get("calendars")

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
            "created_at": firestore.SERVER_TIMESTAMP,
        }
    )

    source_names = resolve_source_names(sources, user_calendars)
    new_sync_ref.update({"source_names": source_names})

    # Auto-sync immediately after creation
    try:
        sync_calendar_logic(new_sync_ref.id)
    except Exception as e:
        logger.warning("Auto-sync on create failed: %s", e)

    return redirect(url_for("main.index"))


@main_bp.route("/create_sync", methods=["GET", "POST"])
def create_sync():
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.login"))

    if request.method == "GET":
        # Cache calendars in session for 5 minutes
        if (
            "calendars" not in session
            or time.time() - session.get("calendars_timestamp", 0) > 300
        ):
            logger.info("Fetching calendars from API (cache miss or expired)")
            calendars = fetch_user_calendars(user["uid"])
            session["calendars"] = calendars
            session["calendars_timestamp"] = time.time()
        else:
            logger.info("Using cached calendars")
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


@main_bp.route("/logout", methods=["POST"])
def logout():
    """Secure logout endpoint (POST only, CSRF protected)."""
    if not verify_csrf_token(request.form.get("csrf_token")):
        logger.warning("Logout failed: Invalid CSRF token")
        return "Invalid CSRF token", 400

    session.clear()
    return redirect(url_for("main.index"))


@main_bp.route("/tasks/sync_one", methods=["POST"])
def sync_one_user():
    """
    Worker endpoint to sync a single user.
    Called by Cloud Tasks.
    """
    try:
        verify_task_auth()
    except ValueError as e:
        logger.warning("Auth failed: %s", e)
        return "Unauthorized", 403

    sync_id = None
    try:
        payload = request.get_json()
        if not payload or "sync_id" not in payload:
            logger.error("Invalid payload for sync_one: %s", payload)
            return "Invalid payload", 400

        sync_id = payload["sync_id"]
        logger.info("Worker starting sync for sync_id: %s", sync_id)

        sync_calendar_logic(sync_id)

        return "Sync successful", 200
    except Exception as e:
        logger.error("Worker failed for sync_id %s: %s", sync_id, e)
        # Return 500 to trigger Cloud Tasks retry
        return "Worker failed. Please check logs for details.", 500


@main_bp.route("/tasks/sync_all", methods=["POST"])
def sync_all_users():
    """
    Dispatcher endpoint.
    Triggered by Cloud Scheduler, enqueues tasks for all users.
    """
    try:
        verify_task_auth()
    except ValueError as e:
        logger.warning("Auth failed: %s", e)
        return "Unauthorized", 403

    logger.info("Starting global sync dispatch...")

    db = firestore.client()
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get(
        "FIREBASE_PROJECT_ID"
    )
    location = os.environ.get("GCP_REGION", "us-central1")
    queue = "sync-queue"
    invoker_email = os.environ.get("SCHEDULER_INVOKER_EMAIL")

    if not project or not invoker_email:
        logger.error("Missing required env vars for Cloud Tasks dispatch")
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
                    "url": url_for("main.sync_one_user", _external=True),
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
            except Exception as e:
                logger.error("Failed to enqueue task for sync_id %s: %s", sync_id, e)

        logger.info("Dispatched %d sync tasks.", count)
        return f"Dispatched {count} tasks", 200

    except Exception as e:
        logger.error("Critical error in dispatcher: %s", e)
        return "Internal failure. Please check logs for details.", 500
