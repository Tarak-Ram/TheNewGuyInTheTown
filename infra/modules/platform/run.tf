locals {
  # Settings every Python service shares.
  common_env = {
    # Real phone calls stay OFF. This is deliberately not a variable: turning it on needs the
    # compliance gate in the PRD, a code change, and a decision, not a setting.
    CALLING_ENABLED            = "false"
    DEMO_MODE                  = tostring(var.demo_mode)
    GOOGLE_CLOUD_PROJECT       = var.project_id
    GOOGLE_CLOUD_LOCATION      = var.region
    GOOGLE_CLIENT_ID           = var.google_client_id
    GEMINI_LIVE_MODEL          = var.gemini_live_model
    GEMINI_LIVE_FALLBACK_MODEL = var.gemini_live_fallback_model
    GEMINI_TEXT_MODEL          = var.gemini_text_model
    DOCUMENT_BUCKET            = google_storage_bucket.agreements.name
    AUDIO_BUCKET               = google_storage_bucket.audio.name
    WEB_ORIGINS                = local.service_url.web
    LOG_LEVEL                  = "INFO"
  }

  # Environment variable name -> secret name, per service.
  secret_env = {
    api = {
      DATABASE_URL         = "database-url"
      SESSION_SECRET       = "session-secret"
      PHONE_ENCRYPTION_KEY = "phone-encryption-key"
      MAPS_API_KEY         = "maps-api-key"
      GOOGLE_API_KEY       = "google-api-key"
    }
    gateway = {
      DATABASE_URL   = "database-url"
      SESSION_SECRET = "session-secret"
      GOOGLE_API_KEY = "google-api-key"
    }
    worker = {
      DATABASE_URL = "database-url"
    }
  }

}

# -- API -------------------------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "api" {
  project             = var.project_id
  name                = "${local.prefix}-api"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = local.labels

  template {
    service_account                  = local.sa["api"]
    timeout                          = "300s"
    max_instance_request_concurrency = 40

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }

    containers {
      image = local.images.api

      ports {
        container_port = 8000
      }

      resources {
        limits            = { cpu = "1", memory = "1Gi" } # PDF reading needs some headroom
        cpu_idle          = true
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.secret_env.api
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = local.secret_ids[env.value]
              version = "latest"
            }
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 2
        period_seconds        = 3
        failure_threshold     = 20
      }

      liveness_probe {
        http_get {
          path = "/health"
        }
        period_seconds = 30
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  # Deploys (canary and rollback) change the image and the traffic split outside Terraform,
  # so Terraform must not fight them.
  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      template[0].revision,
      template[0].labels,
      traffic,
      client,
      client_version,
    ]
  }

  # Everything a new revision needs must exist before it starts. Without these, the first
  # revision would fail on a missing secret version or a missing permission.
  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_version.generated,
    google_secret_manager_secret_version.manual_placeholder,
    google_secret_manager_secret_iam_member.access,
    google_project_iam_member.sql_client,
    google_storage_bucket_iam_member.agreements,
    google_storage_bucket_iam_member.audio_admin,
    google_storage_bucket_iam_member.audio_write,
    google_sql_database.app,
    google_sql_user.app,
  ]
}

# -- Voice gateway: WebSockets for live calls -----------------------------------------------------------
resource "google_cloud_run_v2_service" "gateway" {
  project             = var.project_id
  name                = "${local.prefix}-gateway"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = local.labels

  template {
    service_account = local.sa["gateway"]
    # A call is one long request. 3600 seconds is the most Cloud Run allows. The app ends a
    # call after 5 minutes by itself, so this is only a ceiling.
    timeout                          = "3600s"
    session_affinity                 = true # a reconnect should reach the same instance
    max_instance_request_concurrency = 40

    scaling {
      min_instance_count = var.gateway_min_instances
      max_instance_count = var.max_instances
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }

    containers {
      image = local.images.gateway

      ports {
        container_port = 8000
      }

      resources {
        limits            = { cpu = "1", memory = "1Gi" }
        cpu_idle          = false # audio must keep flowing between messages
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.secret_env.gateway
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = local.secret_ids[env.value]
              version = "latest"
            }
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 2
        period_seconds        = 3
        failure_threshold     = 20
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      template[0].revision,
      template[0].labels,
      traffic,
      client,
      client_version,
    ]
  }

  # Everything a new revision needs must exist before it starts. Without these, the first
  # revision would fail on a missing secret version or a missing permission.
  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_version.generated,
    google_secret_manager_secret_version.manual_placeholder,
    google_secret_manager_secret_iam_member.access,
    google_project_iam_member.sql_client,
    google_storage_bucket_iam_member.agreements,
    google_storage_bucket_iam_member.audio_admin,
    google_storage_bucket_iam_member.audio_write,
    google_sql_database.app,
    google_sql_user.app,
  ]
}

# -- Worker: scheduled and queued jobs. Not public. -------------------------------------------------------
resource "google_cloud_run_v2_service" "worker" {
  project             = var.project_id
  name                = "${local.prefix}-worker"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL" # Cloud Scheduler needs this, and IAM still blocks everyone else
  deletion_protection = false
  labels              = local.labels

  template {
    service_account                  = local.sa["worker"]
    timeout                          = "900s"
    max_instance_request_concurrency = 4

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }

    containers {
      image = local.images.worker

      ports {
        container_port = 8000
      }

      resources {
        limits            = { cpu = "1", memory = "512Mi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.secret_env.worker
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = local.secret_ids[env.value]
              version = "latest"
            }
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 2
        period_seconds        = 3
        failure_threshold     = 20
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      template[0].revision,
      template[0].labels,
      traffic,
      client,
      client_version,
    ]
  }

  # Everything a new revision needs must exist before it starts. Without these, the first
  # revision would fail on a missing secret version or a missing permission.
  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_version.generated,
    google_secret_manager_secret_version.manual_placeholder,
    google_secret_manager_secret_iam_member.access,
    google_project_iam_member.sql_client,
    google_storage_bucket_iam_member.agreements,
    google_storage_bucket_iam_member.audio_admin,
    google_storage_bucket_iam_member.audio_write,
    google_sql_database.app,
    google_sql_user.app,
  ]
}

# -- Web app --------------------------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "web" {
  project             = var.project_id
  name                = "${local.prefix}-web"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = local.labels

  template {
    service_account                  = local.sa["web"]
    timeout                          = "60s"
    max_instance_request_concurrency = 80

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }

    containers {
      image = local.images.web

      ports {
        container_port = 3000
      }

      resources {
        limits            = { cpu = "1", memory = "512Mi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      env {
        name  = "API_URL"
        value = local.service_url.api
      }
      env {
        name  = "GATEWAY_PUBLIC_URL"
        value = local.gateway_ws_url
      }
      env {
        name  = "GOOGLE_CLIENT_ID"
        value = var.google_client_id
      }
      env {
        name  = "DEMO_MODE"
        value = tostring(var.demo_mode)
      }

      startup_probe {
        http_get {
          path = "/api/health"
        }
        initial_delay_seconds = 2
        period_seconds        = 3
        failure_threshold     = 20
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      template[0].revision,
      template[0].labels,
      traffic,
      client,
      client_version,
    ]
  }

  depends_on = [google_project_service.apis]
}

# -- Database migrations run as a job, before a new version gets any traffic ---------------------------------
resource "google_cloud_run_v2_job" "migrate" {
  project             = var.project_id
  name                = "${local.prefix}-migrate"
  location            = var.region
  deletion_protection = false
  labels              = local.labels

  template {
    template {
      service_account = local.sa["api"]
      timeout         = "600s"
      max_retries     = 1

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.main.connection_name]
        }
      }

      containers {
        image   = local.images.api
        command = ["python", "-m", "relocation_api.migrate"]

        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = local.secret_ids["database-url"]
              version = "latest"
            }
          }
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  # Everything a new revision needs must exist before it starts. Without these, the first
  # revision would fail on a missing secret version or a missing permission.
  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_version.generated,
    google_secret_manager_secret_version.manual_placeholder,
    google_secret_manager_secret_iam_member.access,
    google_project_iam_member.sql_client,
    google_storage_bucket_iam_member.agreements,
    google_storage_bucket_iam_member.audio_admin,
    google_storage_bucket_iam_member.audio_write,
    google_sql_database.app,
    google_sql_user.app,
  ]
}

# -- Cloud Tasks: paces call jobs. One retry, as the PRD says. ---------------------------------------------------
resource "google_cloud_tasks_queue" "calls" {
  project  = var.project_id
  name     = "${local.prefix}-call-jobs"
  location = var.region

  rate_limits {
    max_dispatches_per_second = 1 # calls are spread out, never fired all at once
    max_concurrent_dispatches = 5
  }

  retry_config {
    max_attempts  = 2 # the first try plus one retry
    min_backoff   = "30s"
    max_backoff   = "300s"
    max_doublings = 2
  }

  stackdriver_logging_config {
    sampling_ratio = 1.0
  }

  depends_on = [google_project_service.apis]
}

# -- Cloud Scheduler: the daily retention run -------------------------------------------------------------------
resource "google_cloud_scheduler_job" "retention" {
  project          = var.project_id
  name             = "${local.prefix}-retention"
  region           = var.region
  description      = "Deletes agreements after 90 days and call audio after 30."
  schedule         = "30 3 * * *"
  time_zone        = "Asia/Kolkata"
  attempt_deadline = "600s"

  retry_config {
    retry_count = 2
  }

  http_target {
    http_method = "POST"
    uri         = "${local.service_url.worker}/internal/retention/run"

    oidc_token {
      service_account_email = local.sa["scheduler"]
      audience              = local.service_url.worker
    }
  }

  depends_on = [google_project_service.apis, google_cloud_run_v2_service.worker]
}
