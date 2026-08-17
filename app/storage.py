import os
import logging
from firebase_admin import storage

logger = logging.getLogger(__name__)


def get_bucket_name():
    """Get the default Firebase Storage bucket name based on the project ID."""
    bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET")
    if bucket_name:
        return bucket_name

    project_id = os.environ.get("FIREBASE_PROJECT_ID") or os.environ.get(
        "GOOGLE_CLOUD_PROJECT"
    )
    if not project_id:
        logger.error(
            "FIREBASE_PROJECT_ID or GOOGLE_CLOUD_PROJECT environment variable not set."
        )
        raise ValueError("Could not determine Firebase Project ID.")

    return f"{project_id}.appspot.com"


def delete_ics_from_storage(user_id, calendar_id):
    """Deletes the ICS file from Firebase Storage."""
    bucket_name = get_bucket_name()
    path = generate_easycloud_path(user_id, calendar_id)
    try:
        bucket = storage.bucket(bucket_name)
        blob = bucket.blob(path)
        if blob.exists():
            blob.delete()
            logger.info("Deleted ICS from storage: %s", path)
    except Exception as e:
        logger.error("Failed to delete ICS from storage for path %s: %s", path, e)


def generate_easycloud_path(user_id, calendar_id):
    """Generate the storage path for an EasyCloud calendar."""
    return f"easycloud/{user_id}/{calendar_id}.ics"


def upload_ics_to_storage(user_id, calendar_id, ics_content):
    """
    Uploads the provided ICS content to Firebase Storage and makes it public.
    Returns the public URL.
    """
    bucket_name = get_bucket_name()
    bucket = storage.bucket(bucket_name)

    path = generate_easycloud_path(user_id, calendar_id)
    blob = bucket.blob(path)

    # Upload from string with correct content type
    blob.upload_from_string(ics_content, content_type="text/calendar")

    try:
        # Attempt to make it public.
        # If Uniform Bucket-Level Access is enabled, this might raise an error,
        # but the bucket might already be public.
        blob.make_public()
    except Exception as e:
        logger.warning(
            "Could not make blob public, this is expected if uniform bucket level access is enabled: %s",
            e,
        )

    # Construct the public URL explicitly to avoid issues with some Firebase Storage configurations
    public_url = f"https://storage.googleapis.com/{bucket_name}/{path}"

    return public_url


def get_ics_from_storage(user_id, calendar_id):
    """
    Retrieves the raw ICS content from Firebase Storage.
    Returns None if it doesn't exist.
    """
    bucket_name = get_bucket_name()
    try:
        bucket = storage.bucket(bucket_name)

        path = generate_easycloud_path(user_id, calendar_id)
        blob = bucket.blob(path)

        if not blob.exists():
            return None

        return blob.download_as_string()
    except Exception as e:
        logger.error("Failed to fetch ICS from storage: %s", e)
        return None


def generate_smart_filter_path(user_id, calendar_id):
    """Generate the storage path for a smart filter calendar .ics file."""
    return f"filtered_calendars/{user_id}/{calendar_id}.ics"


def generate_smart_filter_audit_path(user_id, calendar_id):
    """Generate the storage path for a smart filter calendar _audit.json file."""
    return f"filtered_calendars/{user_id}/{calendar_id}_audit.json"


def upload_smart_filter_to_storage(user_id, calendar_id, ics_content, audit_content):
    """
    Uploads the filtered ICS content and audit JSON sidecar to GCS.
    Returns (public_url, audit_url).
    """
    bucket_name = get_bucket_name()
    bucket = storage.bucket(bucket_name)

    ics_path = generate_smart_filter_path(user_id, calendar_id)
    blob_ics = bucket.blob(ics_path)
    if isinstance(ics_content, str):
        ics_content = ics_content.encode("utf-8")
    blob_ics.upload_from_string(ics_content, content_type="text/calendar")
    try:
        blob_ics.make_public()
    except Exception as e:
        logger.warning("Could not make ICS blob public: %s", e)
    public_url = f"https://storage.googleapis.com/{bucket_name}/{ics_path}"

    audit_path = generate_smart_filter_audit_path(user_id, calendar_id)
    blob_audit = bucket.blob(audit_path)
    if isinstance(audit_content, str):
        audit_content = audit_content.encode("utf-8")
    blob_audit.upload_from_string(audit_content, content_type="application/json")
    try:
        blob_audit.make_public()
    except Exception as e:
        logger.warning("Could not make audit blob public: %s", e)
    audit_url = f"https://storage.googleapis.com/{bucket_name}/{audit_path}"

    return public_url, audit_url


def delete_smart_filter_from_storage(user_id, calendar_id):
    """Deletes smart filter .ics and _audit.json files from storage."""
    bucket_name = get_bucket_name()
    bucket = storage.bucket(bucket_name)

    for path in [
        generate_smart_filter_path(user_id, calendar_id),
        generate_smart_filter_audit_path(user_id, calendar_id),
    ]:
        try:
            blob = bucket.blob(path)
            if blob.exists():
                blob.delete()
                logger.info("Deleted smart filter file from storage: %s", path)
        except Exception as e:
            logger.error("Failed to delete smart filter file from storage %s: %s", path, e)

