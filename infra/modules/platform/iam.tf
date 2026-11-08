# One service account per service, each with only what it needs.
locals {
  service_accounts = toset(["api", "gateway", "worker", "web", "scheduler", "tasks", "deployer"])
}

resource "google_service_account" "sa" {
  for_each     = local.service_accounts
  project      = var.project_id
  account_id   = "${local.prefix}-${each.key}"
  display_name = "${local.prefix} ${each.key}"

  depends_on = [google_project_service.apis]
}

locals {
  sa = { for k, v in google_service_account.sa : k => v.email }

  # Which secrets each service may read.
  secret_access = {
    api     = ["database-url", "session-secret", "phone-encryption-key", "maps-api-key", "google-api-key"]
    gateway = ["database-url", "session-secret", "google-api-key"]
    worker  = ["database-url"]
  }

  secret_bindings = merge([
    for svc, names in local.secret_access : {
      for n in names : "${svc}/${n}" => { service = svc, secret = n }
    }
  ]...)
}

resource "google_secret_manager_secret_iam_member" "access" {
  for_each  = local.secret_bindings
  project   = var.project_id
  secret_id = local.secret_ids[each.value.secret]
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.sa[each.value.service]}"
}

# Database connections.
resource "google_project_iam_member" "sql_client" {
  for_each = toset(["api", "gateway", "worker"])
  project  = var.project_id
  role     = "roles/cloudsql.client"
  member   = "serviceAccount:${local.sa[each.value]}"
}

# Files. The API and the worker read and delete agreements. The gateway may only add audio.
resource "google_storage_bucket_iam_member" "agreements" {
  for_each = toset(["api", "worker"])
  bucket   = google_storage_bucket.agreements.name
  role     = "roles/storage.objectAdmin"
  member   = "serviceAccount:${local.sa[each.value]}"
}

resource "google_storage_bucket_iam_member" "audio_admin" {
  for_each = toset(["api", "worker"])
  bucket   = google_storage_bucket.audio.name
  role     = "roles/storage.objectAdmin"
  member   = "serviceAccount:${local.sa[each.value]}"
}

resource "google_storage_bucket_iam_member" "audio_write" {
  bucket = google_storage_bucket.audio.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${local.sa["gateway"]}"
}

# Logs and metrics.
resource "google_project_iam_member" "observability" {
  for_each = {
    for pair in setproduct(["api", "gateway", "worker", "web"], ["roles/logging.logWriter", "roles/monitoring.metricWriter"]) :
    "${pair[0]}/${pair[1]}" => { sa = pair[0], role = pair[1] }
  }
  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${local.sa[each.value.sa]}"
}

# Who may call what.
# The web app, the API and the voice gateway are public on the internet, because browsers
# connect to them. Every request to the API still needs a signed-in session, and a call link
# is single-use. The worker is NOT public: only Cloud Scheduler and Cloud Tasks can call it.
resource "google_cloud_run_v2_service_iam_member" "public" {
  for_each = {
    web     = google_cloud_run_v2_service.web.name
    api     = google_cloud_run_v2_service.api.name
    gateway = google_cloud_run_v2_service.gateway.name
  }
  project  = var.project_id
  location = var.region
  name     = each.value
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "worker_invokers" {
  for_each = toset(["scheduler", "tasks"])
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.worker.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${local.sa[each.value]}"
}

# The API may queue jobs, signing them as the tasks account.
resource "google_project_iam_member" "api_enqueues_tasks" {
  project = var.project_id
  role    = "roles/cloudtasks.enqueuer"
  member  = "serviceAccount:${local.sa["api"]}"
}

resource "google_service_account_iam_member" "api_acts_as_tasks" {
  service_account_id = google_service_account.sa["tasks"].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${local.sa["api"]}"
}
