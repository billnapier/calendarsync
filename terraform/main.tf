terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.0"
    }
  }
  backend "gcs" {
    bucket = "calendarsync-napier-tfstate"
    prefix = "terraform/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Enable necessary APIs
resource "google_project_service" "run_api" {
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "calendar_api" {
  service            = "calendar-json.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "artifact_registry_api" {
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "cloudbuild_api" {
  service            = "cloudbuild.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "iam_api" {
  service            = "iam.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "cloudresourcemanager_api" {
  service            = "cloudresourcemanager.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "iamcredentials_api" {
  service            = "iamcredentials.googleapis.com"
  disable_on_destroy = false
}

# Artifact Registry Repository
resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = var.service_name
  description   = "Docker repository for ${var.service_name}"
  format        = "DOCKER"
  depends_on    = [google_project_service.artifact_registry_api]
}



resource "google_service_account" "app_runner" {
  account_id   = "app-runner"
  display_name = "Cloud Run Service Account"
}

# Grant necessary permissions to the App Runner SA
resource "google_project_iam_member" "app_runner_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.app_runner.email}"
}

resource "google_project_iam_member" "app_runner_secrets" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.app_runner.email}"
}

resource "google_project_iam_member" "app_runner_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.app_runner.email}"
}

# Cloud Run Service
resource "google_cloud_run_service" "default" {
  name     = var.service_name
  location = var.region

  template {
    spec {
      service_account_name = google_service_account.app_runner.email
      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}/${var.service_name}:${var.image_tag}"

        env {
          name  = "FIREBASE_API_KEY"
          value = data.google_firebase_web_app_config.default.api_key
        }
        env {
          name  = "FIREBASE_AUTH_DOMAIN"
          value = data.google_firebase_web_app_config.default.auth_domain
        }
        env {
          name  = "FIREBASE_PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "FIREBASE_STORAGE_BUCKET"
          value = data.google_firebase_web_app_config.default.storage_bucket
        }
        env {
          name  = "FIREBASE_MESSAGING_SENDER_ID"
          value = data.google_firebase_web_app_config.default.messaging_sender_id
        }
        env {
          name  = "FIREBASE_APP_ID"
          value = google_firebase_web_app.default.app_id
        }
        env {
          name = "GOOGLE_CLIENT_ID"
          value_from {
            secret_key_ref {
              name = "google_client_id"
              key  = "1"
            }
          }
        }
        env {
          name = "GOOGLE_CLIENT_SECRET"
          value_from {
            secret_key_ref {
              name = "google_client_secret"
              key  = "1"
            }
          }
        }
        env {
          name = "SECRET_KEY"
          value_from {
            secret_key_ref {
              name = "flask_secret_key"
              key  = "1"
            }
          }
        }
        env {
          name  = "GCP_REGION"
          value = var.region
        }
        env {
          name  = "SCHEDULER_INVOKER_EMAIL"
          value = google_service_account.scheduler_invoker.email
        }
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }

  depends_on = [
    google_project_service.run_api,
    google_project_iam_member.app_runner_secrets,
    google_project_iam_member.app_runner_firestore,
    google_project_iam_member.app_runner_logging
  ]

  lifecycle {
    ignore_changes = [
      template[0].spec[0].containers[0].image,
      traffic
    ]
  }
}

# Domain Mapping
# Firebase Hosting Custom Domain
resource "google_firebase_hosting_custom_domain" "default" {
  provider = google-beta
  project  = var.project_id
  site_id  = var.project_id
  custom_domain = var.domain_name

  depends_on = [google_firebase_web_app.default]
}

# Allow unauthenticated invocations (public access)
data "google_iam_policy" "noauth" {
  binding {
    role = "roles/run.invoker"
    members = [
      "allUsers",
    ]
  }
}

resource "google_cloud_run_service_iam_policy" "noauth" {
  location = google_cloud_run_service.default.location
  project  = google_cloud_run_service.default.project
  service  = google_cloud_run_service.default.name

  policy_data = data.google_iam_policy.noauth.policy_data
}

# Grant Cloud Build Service Account permissions to deploy to Cloud Run and access Artifact Registry
# The default Cloud Build Service Account is [PROJECT_NUMBER]@cloudbuild.gserviceaccount.com
data "google_project" "project" {}

resource "google_project_iam_member" "cloudbuild_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${data.google_project.project.number}@cloudbuild.gserviceaccount.com"
}

# --- Firebase & Firestore Configuration ---

provider "google-beta" {
  project               = var.project_id
  region                = var.region
  user_project_override = true
}

resource "google_project_service" "firestore_api" {
  service            = "firestore.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "firebase_api" {
  service            = "firebase.googleapis.com"
  disable_on_destroy = false
  depends_on         = [google_project_service.cloudbuild_api]
}

resource "google_project_service" "identitytoolkit_api" {
  service            = "identitytoolkit.googleapis.com"
  disable_on_destroy = false
  depends_on         = [google_project_service.serviceusage_api]
}

resource "google_project_service" "secretmanager_api" {
  service            = "secretmanager.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "serviceusage_api" {
  service            = "serviceusage.googleapis.com"
  disable_on_destroy = false
}

resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"
  depends_on  = [google_project_service.firestore_api]
}

resource "google_firebase_project" "default" {
  provider = google-beta
  project  = var.project_id

  # Wait for Firebase API to be enabled
  depends_on = [google_project_service.firebase_api, google_project_service.serviceusage_api]
}

resource "google_firebase_web_app" "default" {
  provider     = google-beta
  project      = var.project_id
  display_name = "CalendarSync"
  depends_on   = [google_firebase_project.default]
}


locals {
  firebase_authorized_domains = [
    "localhost",
    "127.0.0.1",
    "${var.project_id}.firebaseapp.com",
    "${var.project_id}.web.app",
    try(replace(google_cloud_run_service.default.status[0].url, "https://", ""), ""),
    var.domain_name
  ]
}

resource "google_identity_platform_config" "default" {
  provider = google-beta
  project  = var.project_id

  authorized_domains = local.firebase_authorized_domains

  depends_on = [google_project_service.identitytoolkit_api]
}

data "google_firebase_web_app_config" "default" {
  provider   = google-beta
  web_app_id = google_firebase_web_app.default.app_id
}

output "firebase_config" {
  value = {
    apiKey            = data.google_firebase_web_app_config.default.api_key
    authDomain        = data.google_firebase_web_app_config.default.auth_domain
    projectId         = var.project_id
    storageBucket     = data.google_firebase_web_app_config.default.storage_bucket
    messagingSenderId = data.google_firebase_web_app_config.default.messaging_sender_id
    appId             = google_firebase_web_app.default.app_id
  }
  sensitive = true
}

output "dns_records" {
  value = google_firebase_hosting_custom_domain.default.certs
}
