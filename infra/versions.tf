terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # No backend block on purpose -- this is a from-scratch, single-maintainer
  # deployment with no existing IaC or CI in this repo. State defaults to
  # local (terraform.tfstate next to these files, already .gitignore'd).
  # If this grows beyond one operator, move to a GCS backend:
  #
  #   backend "gcs" {
  #     bucket = "<some-tfstate-bucket>"
  #     prefix = "story-graph/targeted-research"
  #   }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
