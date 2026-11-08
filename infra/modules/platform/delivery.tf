# -- Budget alerts -------------------------------------------------------------------------------------------------
resource "google_billing_budget" "main" {
  count           = var.billing_account == "" ? 0 : 1
  billing_account = var.billing_account
  display_name    = "${local.prefix} monthly budget"

  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }

  amount {
    specified_amount {
      currency_code = var.budget_currency
      units         = tostring(var.budget_amount)
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }

  all_updates_rule {
    monitoring_notification_channels = local.channels
  }

  depends_on = [google_project_service.apis]
}

# -- Deploying from GitHub without any stored key -----------------------------------------------------------------------
# GitHub proves who it is with a short-lived token. Only the main branch of the named
# repository can act as the deployer account.
resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "${local.prefix}-github"
  display_name              = "GitHub Actions"

  depends_on = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  attribute_condition = "assertion.repository == \"${var.github_repo}\" && assertion.ref == \"refs/heads/main\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_deploys" {
  service_account_id = google_service_account.sa["deployer"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}

# What the deployer may do: push images, deploy services and run the migration job.
resource "google_project_iam_member" "deployer" {
  for_each = toset(["roles/run.developer", "roles/artifactregistry.writer"])
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${local.sa["deployer"]}"
}

# Deploying a revision means acting as that service's account.
resource "google_service_account_iam_member" "deployer_acts_as" {
  for_each           = toset(["api", "gateway", "worker", "web"])
  service_account_id = google_service_account.sa[each.value].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${local.sa["deployer"]}"
}
