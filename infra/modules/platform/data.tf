# -- Cloud SQL (PostgreSQL with PostGIS) ----------------------------------------------------
resource "random_password" "db" {
  length  = 32
  special = false # keeps the connection URL simple, with nothing to escape
}

resource "google_sql_database_instance" "main" {
  project             = var.project_id
  name                = "${local.prefix}-db"
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = var.db_deletion_protection

  settings {
    tier              = var.db_tier
    availability_type = var.db_availability
    edition           = "ENTERPRISE"
    disk_type         = "PD_SSD"
    disk_autoresize   = true
    user_labels       = local.labels

    # Cloud Run connects through the Cloud SQL connector over a private channel. There are no
    # authorised networks, so nothing on the internet can reach the database port.
    ip_configuration {
      ipv4_enabled = true
      ssl_mode     = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "21:30" # 03:00 in India
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 7
      }
    }

    maintenance_window {
      day          = 7 # Sunday
      hour         = 21
      update_track = "stable"
    }

    insights_config {
      query_insights_enabled = true
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_sql_database" "app" {
  project  = var.project_id
  instance = google_sql_database_instance.main.name
  name     = "relocation"
}

resource "google_sql_user" "app" {
  project  = var.project_id
  instance = google_sql_database_instance.main.name
  name     = "app"
  password = random_password.db.result
}

# -- Cloud Storage: two private buckets ---------------------------------------------------------
# No public access, and soft delete is off. Soft delete would keep "deleted" files for 7 more
# days, which breaks the promise that agreements and audio really are deleted.
resource "google_storage_bucket" "agreements" {
  project                     = var.project_id
  name                        = "${var.project_id}-${local.prefix}-agreements"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.labels

  soft_delete_policy {
    retention_duration_seconds = 0
  }

  # A backstop. The retention job deletes agreements at 90 days. This catches anything it missed.
  lifecycle_rule {
    condition {
      age = 100
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket" "audio" {
  project                     = var.project_id
  name                        = "${var.project_id}-${local.prefix}-audio"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.labels

  soft_delete_policy {
    retention_duration_seconds = 0
  }

  # A backstop. The retention job deletes audio 30 days after the call.
  lifecycle_rule {
    condition {
      age = 32
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.apis]
}

# -- Secret Manager -------------------------------------------------------------------------------
# Generated secrets. Their values live in Terraform state, so keep the state bucket private.
resource "random_password" "session" {
  length  = 64
  special = false
}

resource "random_bytes" "phone_key" {
  length = 32
}

locals {
  # A Fernet key is 32 random bytes in URL-safe base64.
  phone_key = replace(replace(random_bytes.phone_key.base64, "+", "-"), "/", "_")

  # The app reaches the database through the Cloud SQL connector's unix socket.
  database_url = "postgresql://${google_sql_user.app.name}:${random_password.db.result}@/${google_sql_database.app.name}?host=/cloudsql/${google_sql_database_instance.main.connection_name}"

  generated_secrets = {
    "database-url"         = local.database_url
    "session-secret"       = random_password.session.result
    "phone-encryption-key" = local.phone_key
  }

  # Secrets a person fills in by hand: `gcloud secrets versions add NAME --data-file=-`.
  manual_secrets = toset(["maps-api-key", "google-api-key"])

  secret_ids = merge(
    { for k, s in google_secret_manager_secret.generated : k => s.secret_id },
    { for k, s in google_secret_manager_secret.manual : k => s.secret_id },
  )
}

resource "google_secret_manager_secret" "generated" {
  for_each  = local.generated_secrets
  project   = var.project_id
  secret_id = "${local.prefix}-${each.key}"
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "generated" {
  for_each    = local.generated_secrets
  secret      = google_secret_manager_secret.generated[each.key].id
  secret_data = each.value
}

resource "google_secret_manager_secret" "manual" {
  for_each  = local.manual_secrets
  project   = var.project_id
  secret_id = "${local.prefix}-${each.key}"
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

# A placeholder, so services can start before the real value is added. Add the real key as a
# new version. Terraform will not overwrite it.
resource "google_secret_manager_secret_version" "manual_placeholder" {
  for_each    = local.manual_secrets
  secret      = google_secret_manager_secret.manual[each.key].id
  secret_data = "unset"

  lifecycle {
    ignore_changes = [secret_data, enabled]
  }
}
