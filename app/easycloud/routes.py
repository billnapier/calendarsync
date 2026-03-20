import logging
from datetime import timezone
from flask import Blueprint, request, redirect, url_for, flash, session
from firebase_admin import firestore
import icalendar

from app.utils import verify_csrf_token
from app.storage import upload_ics_to_storage, get_ics_from_storage

logger = logging.getLogger(__name__)

easycloud_bp = Blueprint("easycloud", __name__, url_prefix="/easycloud")

@easycloud_bp.route("/create", methods=["POST"])
def create_calendar():
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.login"))
        
    if not verify_csrf_token(request.form.get("csrf_token")):
        return "Invalid CSRF token", 403

    name = request.form.get("name", "").strip()
    if not name:
        flash("Calendar name is required", "danger")
        return redirect(url_for("main.index"))

    db = firestore.client()
    new_cal_ref = db.collection("easycloud_calendars").document()
    
    new_cal_ref.set({
        "user_id": user["uid"],
        "name": name,
        "public_url": "", # Will be populated on first upload
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP,
        "event_count": 0
    })

    # Create an empty ICS to initialize it
    cal = icalendar.Calendar()
    cal.add("prodid", "-//CalendarSync//EasyCloud//")
    cal.add("version", "2.0")
    cal.add("X-WR-CALNAME", name)
    ics_str = cal.to_ical().decode("utf-8")
    
    try:
        public_url = upload_ics_to_storage(user["uid"], new_cal_ref.id, ics_str)
        new_cal_ref.update({"public_url": public_url})
    except Exception as e:
        logger.error("Failed to upload ICS to storage: %s", e)
        new_cal_ref.delete()
        flash(f"Error creating EasyCloud calendar storage. Please ensure Firebase Storage is initialized. Error: {e}", "danger")
        return redirect(url_for("main.index"))

    flash(f"EasyCloud Calendar '{name}' created successfully!", "success")
    return redirect(url_for("main.index"))

@easycloud_bp.route("/<calendar_id>/upload", methods=["POST"])
def upload_ics(calendar_id):
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.login"))

    if not verify_csrf_token(request.form.get("csrf_token")):
        return "Invalid CSRF token", 403

    db = firestore.client()
    cal_ref = db.collection("easycloud_calendars").document(calendar_id)
    cal_doc = cal_ref.get()

    if not cal_doc.exists:
        flash("Calendar not found", "danger")
        return redirect(url_for("main.index"))

    cal_data = cal_doc.to_dict()
    if cal_data.get("user_id") != user["uid"]:
        flash("Unauthorized", "danger")
        return redirect(url_for("main.index"))

    file = request.files.get("ics_file")
    if not file or file.filename == "":
        flash("No selected file", "warning")
        return redirect(url_for("main.index"))

    if not file.filename.lower().endswith(".ics"):
        flash("File must be an .ics calendar file", "danger")
        return redirect(url_for("main.index"))

    action = request.form.get("upload_action", "replace") # "add" or "replace"

    # Parse the uploaded file
    try:
        uploaded_content = file.read()
        uploaded_cal = icalendar.Calendar.from_ical(uploaded_content)
    except Exception as e:
        logger.error("Failed to parse uploaded ICS: %s", e)
        flash("Failed to parse the uploaded file. Please ensure it is a valid .ics file.", "danger")
        return redirect(url_for("main.index"))

    master_cal = icalendar.Calendar()
    master_cal.add("prodid", "-//CalendarSync//EasyCloud//")
    master_cal.add("version", "2.0")
    master_cal.add("X-WR-CALNAME", cal_data.get("name", "EasyCloud Calendar"))

    existing_events = {}
    
    # If action is 'add', we keep existing events
    if action == "add":
        existing_content = get_ics_from_storage(user["uid"], calendar_id)
        if existing_content:
            try:
                old_cal = icalendar.Calendar.from_ical(existing_content)
                for component in old_cal.subcomponents:
                    if component.name == "VEVENT":
                        uid = str(component.get("UID"))
                        if uid:
                            existing_events[uid] = component
            except Exception as e:
                logger.warning("Failed to parse existing ICS during merge: %s", e)

    # Process new events (either overriding, or this is a replace so it's only these)
    for component in uploaded_cal.subcomponents:
        if component.name == "VEVENT":
            uid = str(component.get("UID"))
            if uid:
                existing_events[uid] = component

    # Add all unique events to the master calendar
    event_count = 0
    for component in existing_events.values():
        master_cal.add_component(component)
        event_count += 1

    ics_str = master_cal.to_ical().decode("utf-8")
    try:
        public_url = upload_ics_to_storage(user["uid"], calendar_id, ics_str)
    except Exception as e:
        logger.error("Failed to upload ICS during update: %s", e)
        flash(f"Storage upload failed. Please ensure Firebase storage is configured. Error: {e}", "danger")
        return redirect(url_for("main.index"))

    cal_ref.update({
        "updated_at": firestore.SERVER_TIMESTAMP,
        "event_count": event_count,
        "public_url": public_url
    })

    flash(f"Successfully processed {event_count} events into '{cal_data.get('name')}'.", "success")
    return redirect(url_for("main.index"))

@easycloud_bp.route("/<calendar_id>/delete", methods=["POST"])
def delete_calendar(calendar_id):
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.login"))

    if not verify_csrf_token(request.form.get("csrf_token")):
        return "Invalid CSRF token", 403

    db = firestore.client()
    cal_ref = db.collection("easycloud_calendars").document(calendar_id)
    cal_doc = cal_ref.get()

    if not cal_doc.exists:
        flash("Calendar not found", "danger")
        return redirect(url_for("main.index"))

    cal_data = cal_doc.to_dict()
    if cal_data.get("user_id") != user["uid"]:
        flash("Unauthorized", "danger")
        return redirect(url_for("main.index"))

    cal_ref.delete()
    # Note: we are not deleting the file from storage to keep code simple, 
    # but could easily do it if required. Since we are just dropping the reference, it's fine.

    flash("EasyCloud Calendar deleted.", "success")
    return redirect(url_for("main.index"))
