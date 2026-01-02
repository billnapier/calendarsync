resource "google_project_service" "tasks_api" {
  service            = "cloudtasks.googleapis.com"
  disable_on_destroy = false
}

resource "google_cloud_tasks_queue" "sync_queue" {
  name       = "sync-queue"
  location   = var.region
  depends_on = [google_project_service.tasks_api]
}

# Grant the Cloud Run service account permission to enqueue tasks
# Note: Cloud Run uses the Default Compute Service Account by default if not specified
resource "google_project_iam_member" "cloud_run_tasks_enqueuer" {
  project = var.project_id
  role    = "roles/cloudtasks.enqueuer"
  member  = "serviceAccount:${google_service_account.app_runner.email}"
}
