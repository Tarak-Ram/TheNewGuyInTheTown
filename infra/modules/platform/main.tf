data "google_project" "this" {
  project_id = var.project_id
}

locals {
  prefix = "${var.name}-${var.environment}"

  registry = "${var.region}-docker.pkg.dev/${var.project_id}/${local.prefix}"
  images = {
    api     = "${local.registry}/api:${var.image_tag}"
    gateway = "${local.registry}/voice-gateway:${var.image_tag}"
    worker  = "${local.registry}/worker:${var.image_tag}"
    web     = "${local.registry}/web:${var.image_tag}"
  }

  # Cloud Run gives every service a fixed address built from its name and the project number.
  # Computing it avoids a loop: the web app needs the gateway's address, and the gateway
  # needs the web app's address (to check where browsers connect from).
  service_url = { for s in ["web", "api", "gateway", "worker"] :
    s => "https://${local.prefix}-${s}-${data.google_project.this.number}.${var.region}.run.app"
  }
  gateway_ws_url = replace(local.service_url.gateway, "https://", "wss://")

  labels = {
    app         = var.name
    environment = var.environment
    managed_by  = "terraform"
  }
}

# Every API this setup uses. Services are not switched off if this module is removed.
resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudtasks.googleapis.com",
    "cloudscheduler.googleapis.com",
    "artifactregistry.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "billingbudgets.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "cloudresourcemanager.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# Where the container images live.
resource "google_artifact_registry_repository" "main" {
  project       = var.project_id
  location      = var.region
  repository_id = local.prefix
  format        = "DOCKER"
  description   = "Images for ${local.prefix}"
  labels        = local.labels

  # Keep the last 10 tagged versions, and clear untagged leftovers after a week.
  cleanup_policies {
    id     = "delete-untagged"
    action = "DELETE"
    condition {
      tag_state  = "UNTAGGED"
      older_than = "604800s"
    }
  }
  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }

  depends_on = [google_project_service.apis]
}
