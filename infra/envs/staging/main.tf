terraform {
  required_version = ">= 1.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State holds generated secrets, so it must live in a private bucket you create first.
  # Fill in backend.hcl (see backend.hcl.example) and run: terraform init -backend-config=backend.hcl
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}

module "platform" {
  source = "../../modules/platform"

  project_id  = var.project_id
  region      = var.region
  environment = "staging"
  alert_email = var.alert_email

  billing_account = var.billing_account
  budget_amount   = var.budget_amount
  budget_currency = var.budget_currency
  github_repo     = var.github_repo

  # Staging is small and cheap. The database is the main fixed cost.
  db_tier                = "db-f1-micro"
  db_availability        = "ZONAL"
  db_deletion_protection = var.db_deletion_protection
  max_instances          = 3
  gateway_min_instances  = 1

  google_client_id           = var.google_client_id
  gemini_live_model          = var.gemini_live_model
  gemini_live_fallback_model = var.gemini_live_fallback_model
  gemini_text_model          = var.gemini_text_model
  image_tag                  = var.image_tag

  # Staging uses real sign-in. Demo mode is for laptops and rehearsals.
  demo_mode = false
}
