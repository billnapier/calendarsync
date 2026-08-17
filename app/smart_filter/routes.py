import logging
import uuid
from flask import (
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
)
from firebase_admin import firestore

from app.security import validate_url
from app.utils import generate_csrf_token, verify_csrf_token
from app.storage import (
    get_bucket_name,
    generate_smart_filter_path,
    generate_smart_filter_audit_path,
    delete_smart_filter_from_storage,
)
from . import smart_filter_bp
from .logic import (
    evaluate_smart_filter,
    test_smart_filter_preview,
    _compute_prompt_hash,
)

logger = logging.getLogger(__name__)


@smart_filter_bp.route("/create", methods=["GET", "POST"])
def create_smart_filter():
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.login"))

    if request.method == "GET":
        csrf_token = generate_csrf_token()
        return render_template(
            "create_smart_filter.html", user=user, csrf_token=csrf_token
        )

    # POST
    if not verify_csrf_token(request.form.get("csrf_token")):
        return "Invalid CSRF token", 403

    name = request.form.get("name", "").strip()
    source_url = request.form.get("source_url", "").strip()
    filter_prompt = request.form.get("filter_prompt", "").strip()

    if not name or not source_url or not filter_prompt:
        flash("All fields are required.", "danger")
        return redirect(url_for("smart_filter.create_smart_filter"))

    try:
        validate_url(source_url)
    except ValueError as e:
        flash(f"Invalid Source URL: {e}", "danger")
        return redirect(url_for("smart_filter.create_smart_filter"))

    calendar_id = str(uuid.uuid4())
    bucket_name = get_bucket_name()
    gcs_path = generate_smart_filter_path(user["uid"], calendar_id)
    audit_path = generate_smart_filter_audit_path(user["uid"], calendar_id)
    public_url = f"https://storage.googleapis.com/{bucket_name}/{gcs_path}"
    audit_url = f"https://storage.googleapis.com/{bucket_name}/{audit_path}"

    db = firestore.client()
    doc_ref = db.collection("filtered_calendars").document(calendar_id)
    doc_ref.set(
        {
            "id": calendar_id,
            "user_id": user["uid"],
            "name": name,
            "source_url": source_url,
            "filter_prompt": filter_prompt,
            "prompt_hash": _compute_prompt_hash(filter_prompt),
            "gcs_path": gcs_path,
            "public_url": public_url,
            "audit_url": audit_url,
            "status": "syncing",
            "created_at": firestore.SERVER_TIMESTAMP,
        }
    )

    # Execute evaluation pipeline
    try:
        res = evaluate_smart_filter(calendar_id, force=True)
        tot_inc = res.get("total_included", 0)
        tot_eval = res.get("total_evaluated", 0)
        if tot_inc == 0:
            flash(
                f"Smart Filter created! Warning: Your filter prompt matched 0 of {tot_eval} events. Adjust prompt if needed.",
                "warning",
            )
        else:
            flash("Smart Filter calendar created successfully!", "success")
    except Exception as e:
        logger.error("Initial evaluation for calendar %s failed: %s", calendar_id, e)
        flash(
            f"Smart Filter calendar created, but initial evaluation failed: {e}",
            "warning",
        )

    return redirect(url_for("main.index"))


@smart_filter_bp.route("/test", methods=["POST"])
def test_smart_filter():
    user = session.get("user")
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    # Support JSON or form payload
    if request.is_json:
        data = request.get_json() or {}
        csrf_token = data.get("csrf_token")
        source_url = data.get("source_url", "").strip()
        filter_prompt = data.get("filter_prompt", "").strip()
    else:
        csrf_token = request.form.get("csrf_token")
        source_url = request.form.get("source_url", "").strip()
        filter_prompt = request.form.get("filter_prompt", "").strip()

    if not verify_csrf_token(csrf_token):
        return jsonify({"success": False, "error": "Invalid CSRF token"}), 403

    if not source_url or not filter_prompt:
        return (
            jsonify({"success": False, "error": "Source URL and prompt are required"}),
            400,
        )

    try:
        validate_url(source_url)
        evaluations = test_smart_filter_preview(source_url, filter_prompt)
        return jsonify({"success": True, "evaluations": evaluations})
    except Exception as e:
        logger.error("Test prompt evaluation failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 400


@smart_filter_bp.route("/edit/<calendar_id>", methods=["GET", "POST"])
def edit_smart_filter(calendar_id):
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.login"))

    db = firestore.client()
    doc_ref = db.collection("filtered_calendars").document(calendar_id)
    doc = doc_ref.get()

    if not doc.exists:
        return "Smart Filter not found", 404

    data = doc.to_dict()
    if data["user_id"] != user["uid"]:
        return "Unauthorized", 403

    if request.method == "GET":
        csrf_token = generate_csrf_token()
        return render_template(
            "edit_smart_filter.html",
            user=user,
            calendar=data,
            csrf_token=csrf_token,
        )

    # POST
    if not verify_csrf_token(request.form.get("csrf_token")):
        return "Invalid CSRF token", 403

    name = request.form.get("name", "").strip()
    source_url = request.form.get("source_url", "").strip()
    filter_prompt = request.form.get("filter_prompt", "").strip()

    if not name or not source_url or not filter_prompt:
        flash("All fields are required.", "danger")
        return redirect(
            url_for("smart_filter.edit_smart_filter", calendar_id=calendar_id)
        )

    try:
        validate_url(source_url)
    except ValueError as e:
        flash(f"Invalid Source URL: {e}", "danger")
        return redirect(
            url_for("smart_filter.edit_smart_filter", calendar_id=calendar_id)
        )

    # Mark status as re-evaluating without deleting existing GCS file
    doc_ref.update(
        {
            "name": name,
            "source_url": source_url,
            "filter_prompt": filter_prompt,
            "prompt_hash": _compute_prompt_hash(filter_prompt),
            "status": "reevaluating",
        }
    )

    try:
        res = evaluate_smart_filter(calendar_id, force=True)
        tot_inc = res.get("total_included", 0)
        tot_eval = res.get("total_evaluated", 0)
        if tot_inc == 0:
            flash(
                f"Smart Filter updated! Warning: Your prompt matched 0 of {tot_eval} events.",
                "warning",
            )
        else:
            flash("Smart Filter updated successfully!", "success")
    except Exception as e:
        logger.error("Re-evaluation for calendar %s failed: %s", calendar_id, e)
        flash(f"Smart Filter updated, but re-evaluation failed: {e}", "warning")

    return redirect(url_for("main.index"))


@smart_filter_bp.route("/delete/<calendar_id>", methods=["POST"])
def delete_smart_filter(calendar_id):
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.login"))

    if not verify_csrf_token(request.form.get("csrf_token")):
        return "Invalid CSRF token", 403

    db = firestore.client()
    doc_ref = db.collection("filtered_calendars").document(calendar_id)
    doc = doc_ref.get()

    if not doc.exists:
        return "Smart Filter not found", 404

    data = doc.to_dict()
    if data["user_id"] != user["uid"]:
        return "Unauthorized", 403

    try:
        delete_smart_filter_from_storage(user["uid"], calendar_id)
        doc_ref.delete()
        flash("Smart Filter calendar deleted successfully.", "success")
    except Exception as e:
        logger.error("Error deleting smart filter %s: %s", calendar_id, e)
        flash("Failed to delete Smart Filter calendar.", "danger")

    return redirect(url_for("main.index"))


@smart_filter_bp.route("/sync/<calendar_id>", methods=["POST"])
def sync_smart_filter(calendar_id):
    user = session.get("user")
    if not user:
        return redirect(url_for("auth.login"))

    if not verify_csrf_token(request.form.get("csrf_token")):
        return "Invalid CSRF token", 403

    db = firestore.client()
    doc_ref = db.collection("filtered_calendars").document(calendar_id)
    doc = doc_ref.get()

    if not doc.exists:
        return "Smart Filter not found", 404

    data = doc.to_dict()
    if data["user_id"] != user["uid"]:
        return "Unauthorized", 403

    try:
        res = evaluate_smart_filter(calendar_id, force=False)
        if res.get("changed"):
            tot_inc = res.get("total_included", 0)
            tot_eval = res.get("total_evaluated", 0)
            flash(
                f"Sync complete! Evaluated {tot_eval} events ({tot_inc} included).",
                "success",
            )
        else:
            flash(
                "Calendar is already up to date. Upstream feed hasn't changed (0 LLM calls used).",
                "info",
            )
    except Exception as e:
        logger.error("Manual sync failed for smart filter %s: %s", calendar_id, e)
        flash(f"Sync failed: {e}", "danger")

    return redirect(url_for("main.index"))


@smart_filter_bp.route("/<calendar_id>/status", methods=["GET"])
@smart_filter_bp.route("/smart_filters/<calendar_id>/status", methods=["GET"])
def smart_filter_status(calendar_id):
    user = session.get("user")
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    db = firestore.client()
    doc_ref = db.collection("filtered_calendars").document(calendar_id)
    doc = doc_ref.get()

    if not doc.exists:
        return jsonify({"error": "Not found"}), 404

    data = doc.to_dict()
    if data["user_id"] != user["uid"]:
        return jsonify({"error": "Unauthorized"}), 403

    last_fetched = data.get("last_fetched_at")
    last_fetched_str = last_fetched.isoformat() if last_fetched else None

    return jsonify(
        {
            "id": calendar_id,
            "status": data.get("status", "active"),
            "total_events_evaluated": data.get("total_events_evaluated", 0),
            "total_events_included": data.get("total_events_included", 0),
            "last_fetched_at": last_fetched_str,
            "last_error": data.get("last_error"),
        }
    )
