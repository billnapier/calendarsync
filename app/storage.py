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
        logger.error("FIREBASE_PROJECT_ID or GOOGLE_CLOUD_PROJECT environment variable not set.")
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
