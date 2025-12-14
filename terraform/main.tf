terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 4.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 4.0"
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

resource "google_project_service" "artifact_registry_api" {
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "cloudbuild_api" {
  service            = "cloudbuild.googleapis.com"
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

# Cloud Run Service
resource "google_cloud_run_service" "default" {
  name     = var.service_name
  location = var.region

  template {
    spec {
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
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }

  depends_on = [google_project_service.run_api]
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
  project = var.project_id
  region  = var.region
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
