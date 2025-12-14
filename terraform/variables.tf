variable "project_id" {
  description = "Google Cloud Project ID"
  type        = string
}

variable "region" {
  description = "Google Cloud Region"
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Name of the Cloud Run service"
  type        = string
  default     = "python-cloudrun-app"
}

variable "github_owner" {
  description = "GitHub repository owner"
  type        = string
}


variable "github_repo" {
  description = "GitHub repository name"
  type        = string
}

variable "image_tag" {
  description = "The tag of the container image to deploy"
  type        = string
}
