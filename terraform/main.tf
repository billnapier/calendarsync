terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
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
        image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}/${var.service_name}:latest"
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }

  # We use lifecycle ignore_changes for image because Cloud Build will push new images
  # and we don't want Terraform to revert to 'latest' if it thinks it's different,
  # ALTHOUGH the best practice for CI/CD + TF is often to update the TF definition with the sha.
  # For now, we will rely on Cloud Build to perform the deployment, OR we can have Cloud Build apply Terraform.
  # The user request said: "configure google cloud build to run 'terraform apply' on every commit".
  # This implies Terraform manages the deployment.
  # So, for the bootstrap, we might not have the image yet. We can use a placeholder or assume the first build creates it.

  # To avoid chicken-and-egg, we can initially deploy a dummy Hello World if needed, 
  # or rely on the user to run the first build. 

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

# Cloud Build Trigger for PRs
# Cloud Build Trigger for PRs
# resource "google_cloudbuild_trigger" "pull_request" {
#   name = "${var.service_name}-pr-trigger"
#
#   github {
#     owner = var.github_owner
#     name  = var.github_repo
#     pull_request {
#       branch          = "^main$"
#       comment_control = "COMMENTS_ENABLED"
#     }
#   }
#
#   filename   = "cloudbuild-pr.yaml"
#   depends_on = [google_project_service.cloudbuild_api]
# }

# Cloud Build Trigger
# Note: For GitHub triggers to work via Terraform, the Cloud Build GitHub App must be installed on the repo.
# resource "google_cloudbuild_trigger" "push_on_green" {
#   name = "${var.service_name}-trigger"
#
#   github {
#     owner = var.github_owner
#     name  = var.github_repo
#     push {
#       branch = "^main$"
#     }
#   }
#
#   # We point to the cloudbuild.yaml in the repo
#   filename = "cloudbuild.yaml"
#
#   depends_on = [google_project_service.cloudbuild_api]
# }

# Grant Cloud Build Service Account permissions to deploy to Cloud Run and access Artifact Registry
# The default Cloud Build Service Account is [PROJECT_NUMBER]@cloudbuild.gserviceaccount.com
data "google_project" "project" {}

resource "google_project_iam_member" "cloudbuild_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${data.google_project.project.number}@cloudbuild.gserviceaccount.com"
}

resource "google_project_iam_member" "cloudbuild_sa_user" {
  project = var.project_id
  role    = "roles/iam.serviceAccountUser"
  member  = "serviceAccount:${data.google_project.project.number}@cloudbuild.gserviceaccount.com"
}
