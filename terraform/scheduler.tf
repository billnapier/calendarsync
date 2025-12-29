resource "google_cloud_scheduler_job" "sync_all" {
  name        = "sync-all-users"
  description = "Trigger sync for all users"
  schedule    = var.sync_schedule
  time_zone   = "Etc/UTC"
  region      = var.region

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_service.default.status[0].url}/tasks/sync_all"

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }
}

resource "google_service_account" "scheduler_invoker" {
  account_id   = "scheduler-invoker"
  display_name = "Cloud Scheduler Invoker"
}

resource "google_cloud_run_service_iam_member" "scheduler_invoker" {
  location = google_cloud_run_service.default.location
  project  = google_cloud_run_service.default.project
  service  = google_cloud_run_service.default.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

resource "google_project_service" "cloudscheduler_api" {
  service            = "cloudscheduler.googleapis.com"
  disable_on_destroy = false
}

# App Engine Application is often required for Cloud Scheduler
resource "google_app_engine_application" "app" {
  project     = var.project_id
  location_id = var.region
}
