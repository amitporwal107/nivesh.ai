terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # Uncomment to store state in GCS:
  # backend "gcs" {
  #   bucket = "niveshdataintelligence-tf-state"
  #   prefix = "gcp-monitoring"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
