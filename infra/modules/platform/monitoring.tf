resource "google_monitoring_notification_channel" "email" {
  project      = var.project_id
  display_name = "${local.prefix} alerts"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }

  depends_on = [google_project_service.apis]
}

locals {
  channels = [google_monitoring_notification_channel.email.id]

  uptime_targets = {
    web     = { host = replace(local.service_url.web, "https://", ""), path = "/api/health" }
    api     = { host = replace(local.service_url.api, "https://", ""), path = "/health/ready" }
    gateway = { host = replace(local.service_url.gateway, "https://", ""), path = "/health/ready" }
  }
}

# -- Is it up? -----------------------------------------------------------------------------------------
resource "google_monitoring_uptime_check_config" "up" {
  for_each     = local.uptime_targets
  project      = var.project_id
  display_name = "${local.prefix} ${each.key} is up"
  timeout      = "10s"
  period       = "300s"

  http_check {
    path           = each.value.path
    port           = 443
    use_ssl        = true
    validate_ssl   = true
    request_method = "GET"
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = each.value.host
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_monitoring_alert_policy" "down" {
  for_each     = local.uptime_targets
  project      = var.project_id
  display_name = "${local.prefix}: ${each.key} is down"
  combiner     = "OR"

  conditions {
    display_name = "${each.key} failed its uptime check"
    condition_threshold {
      filter          = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND metric.label.check_id=\"${google_monitoring_uptime_check_config.up[each.key].uptime_check_id}\" AND resource.type=\"uptime_url\""
      comparison      = "COMPARISON_GT"
      threshold_value = 1
      duration        = "300s"

      aggregations {
        alignment_period     = "1200s"
        per_series_aligner   = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
        group_by_fields      = ["resource.label.*"]
      }
      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.channels
  documentation {
    mime_type = "text/markdown"
    content   = "What to do is in `infra/RUNBOOK.md`, under the heading for this alert. If calls are involved and you are unsure, pause calling first (see the runbook), then investigate."
  }
  alert_strategy {
    auto_close = "1800s"
  }
  user_labels = local.labels
}

# -- Errors and speed ------------------------------------------------------------------------------------
resource "google_monitoring_alert_policy" "errors" {
  project      = var.project_id
  display_name = "${local.prefix}: server errors"
  combiner     = "OR"

  conditions {
    display_name = "More than 10 server errors in 5 minutes"
    condition_threshold {
      filter          = "metric.type=\"run.googleapis.com/request_count\" AND resource.type=\"cloud_run_revision\" AND metric.label.response_code_class=\"5xx\" AND resource.label.service_name=starts_with(\"${local.prefix}-\")"
      comparison      = "COMPARISON_GT"
      threshold_value = 10
      duration        = "0s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["resource.label.service_name"]
      }
      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.channels
  documentation {
    mime_type = "text/markdown"
    content   = "What to do is in `infra/RUNBOOK.md`, under the heading for this alert. If calls are involved and you are unsure, pause calling first (see the runbook), then investigate."
  }
  alert_strategy {
    auto_close = "1800s"
  }
  user_labels = local.labels
}

resource "google_monitoring_alert_policy" "slow_api" {
  project      = var.project_id
  display_name = "${local.prefix}: API is slow"
  combiner     = "OR"

  conditions {
    display_name = "API 95th percentile latency above 3 seconds"
    condition_threshold {
      filter          = "metric.type=\"run.googleapis.com/request_latencies\" AND resource.type=\"cloud_run_revision\" AND resource.label.service_name=\"${google_cloud_run_v2_service.api.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 3000
      duration        = "600s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_PERCENTILE_95"
      }
      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.channels
  documentation {
    mime_type = "text/markdown"
    content   = "What to do is in `infra/RUNBOOK.md`, under the heading for this alert. If calls are involved and you are unsure, pause calling first (see the runbook), then investigate."
  }
  alert_strategy {
    auto_close = "1800s"
  }
  user_labels = local.labels
}

# -- Database --------------------------------------------------------------------------------------------
resource "google_monitoring_alert_policy" "database" {
  project      = var.project_id
  display_name = "${local.prefix}: database under pressure"
  combiner     = "OR"

  conditions {
    display_name = "Database CPU above 80% for 10 minutes"
    condition_threshold {
      filter          = "metric.type=\"cloudsql.googleapis.com/database/cpu/utilization\" AND resource.type=\"cloudsql_database\" AND resource.label.database_id=\"${var.project_id}:${google_sql_database_instance.main.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0.8
      duration        = "600s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }

  conditions {
    display_name = "Database disk above 85% full"
    condition_threshold {
      filter          = "metric.type=\"cloudsql.googleapis.com/database/disk/utilization\" AND resource.type=\"cloudsql_database\" AND resource.label.database_id=\"${var.project_id}:${google_sql_database_instance.main.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0.85
      duration        = "300s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }

  notification_channels = local.channels
  documentation {
    mime_type = "text/markdown"
    content   = "What to do is in `infra/RUNBOOK.md`, under the heading for this alert. If calls are involved and you are unsure, pause calling first (see the runbook), then investigate."
  }
  alert_strategy {
    auto_close = "3600s"
  }
  user_labels = local.labels
}

# -- Metrics read from the structured logs the app writes ------------------------------------------------------------
# The voice gateway logs one JSON line when a call ends, with its outcome, and one line for
# each opt-out. Phone numbers are masked before logging, so these lines hold no personal data.
resource "google_logging_metric" "call_outcomes" {
  project = var.project_id
  name    = "${local.prefix}_call_outcomes"
  filter  = "resource.type=\"cloud_run_revision\" AND jsonPayload.event=\"call_ended\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    labels {
      key         = "status"
      value_type  = "STRING"
      description = "completed, opted_out, failed, ended_by_owner"
    }
  }
  label_extractors = {
    status = "EXTRACT(jsonPayload.status)"
  }

  depends_on = [google_project_service.apis]
}

resource "google_logging_metric" "call_failures" {
  project = var.project_id
  name    = "${local.prefix}_call_failures"
  filter  = "resource.type=\"cloud_run_revision\" AND jsonPayload.event=\"call_ended\" AND jsonPayload.status=\"failed\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }

  depends_on = [google_project_service.apis]
}

resource "google_logging_metric" "opt_outs" {
  project = var.project_id
  name    = "${local.prefix}_opt_outs"
  filter  = "resource.type=\"cloud_run_revision\" AND jsonPayload.event=\"owner_opt_out\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }

  depends_on = [google_project_service.apis]
}

resource "google_logging_metric" "missing_disclosure" {
  project = var.project_id
  name    = "${local.prefix}_missing_disclosure"
  filter  = "resource.type=\"cloud_run_revision\" AND jsonPayload.event=\"call_ended\" AND jsonPayload.reason=\"disclosure_missing\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }

  depends_on = [google_project_service.apis]
}

resource "google_logging_metric" "retention_problems" {
  project = var.project_id
  name    = "${local.prefix}_retention_problems"
  filter  = "resource.type=\"cloud_run_revision\" AND (jsonPayload.event=\"retention_file_failed\" OR jsonPayload.event=\"account_file_pending\")"

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }

  depends_on = [google_project_service.apis]
}

locals {
  log_alerts = {
    call_failures = {
      name      = "calls are failing"
      detail    = "More than 3 failed calls in 15 minutes"
      metric    = google_logging_metric.call_failures.name
      threshold = 3
      window    = "900s"
    }
    opt_outs = {
      name      = "owners are opting out"
      detail    = "More than 5 opt-outs in an hour. Check what the agent is saying."
      metric    = google_logging_metric.opt_outs.name
      threshold = 5
      window    = "3600s"
    }
    missing_disclosure = {
      name      = "a call did not say it is an AI"
      detail    = "A call was ended because the agent never disclosed that it is an AI"
      metric    = google_logging_metric.missing_disclosure.name
      threshold = 0
      window    = "300s"
    }
    retention_problems = {
      name      = "files were not deleted on time"
      detail    = "A stored file could not be deleted. The next daily run retries it."
      metric    = google_logging_metric.retention_problems.name
      threshold = 0
      window    = "3600s"
    }
  }
}

resource "google_monitoring_alert_policy" "from_logs" {
  for_each     = local.log_alerts
  project      = var.project_id
  display_name = "${local.prefix}: ${each.value.name}"
  combiner     = "OR"

  conditions {
    display_name = each.value.detail
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${each.value.metric}\" AND resource.type=\"cloud_run_revision\""
      comparison      = "COMPARISON_GT"
      threshold_value = each.value.threshold
      duration        = "0s"

      aggregations {
        alignment_period     = each.value.window
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
      }
      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.channels
  documentation {
    mime_type = "text/markdown"
    content   = "What to do is in `infra/RUNBOOK.md`, under the heading for this alert. If calls are involved and you are unsure, pause calling first (see the runbook), then investigate."
  }
  alert_strategy {
    auto_close = "3600s"
  }
  user_labels = local.labels
}

# -- Dashboard: latency, errors, call outcomes, database --------------------------------------------------------------
locals {
  tile = { width = 6, height = 4 }

  dashboard_tiles = [
    {
      title   = "Requests per second, by service"
      filter  = "metric.type=\"run.googleapis.com/request_count\" resource.type=\"cloud_run_revision\" resource.label.service_name=starts_with(\"${local.prefix}-\")"
      aligner = "ALIGN_RATE"
      reducer = "REDUCE_SUM"
      group   = ["resource.label.service_name"]
    },
    {
      title   = "Server errors (5xx), by service"
      filter  = "metric.type=\"run.googleapis.com/request_count\" resource.type=\"cloud_run_revision\" metric.label.response_code_class=\"5xx\" resource.label.service_name=starts_with(\"${local.prefix}-\")"
      aligner = "ALIGN_RATE"
      reducer = "REDUCE_SUM"
      group   = ["resource.label.service_name"]
    },
    {
      title   = "API latency, 95th percentile (ms)"
      filter  = "metric.type=\"run.googleapis.com/request_latencies\" resource.type=\"cloud_run_revision\" resource.label.service_name=\"${local.prefix}-api\""
      aligner = "ALIGN_PERCENTILE_95"
      reducer = "REDUCE_NONE"
      group   = []
    },
    {
      title   = "Call outcomes (completed, opted out, failed)"
      filter  = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.call_outcomes.name}\""
      aligner = "ALIGN_SUM"
      reducer = "REDUCE_SUM"
      group   = ["metric.label.status"]
    },
    {
      title   = "Owner opt-outs"
      filter  = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.opt_outs.name}\""
      aligner = "ALIGN_SUM"
      reducer = "REDUCE_SUM"
      group   = []
    },
    {
      title   = "Running instances, by service"
      filter  = "metric.type=\"run.googleapis.com/container/instance_count\" resource.type=\"cloud_run_revision\" resource.label.service_name=starts_with(\"${local.prefix}-\")"
      aligner = "ALIGN_MEAN"
      reducer = "REDUCE_SUM"
      group   = ["resource.label.service_name"]
    },
    {
      title   = "Database CPU"
      filter  = "metric.type=\"cloudsql.googleapis.com/database/cpu/utilization\" resource.type=\"cloudsql_database\""
      aligner = "ALIGN_MEAN"
      reducer = "REDUCE_NONE"
      group   = []
    },
    {
      title   = "Database connections"
      filter  = "metric.type=\"cloudsql.googleapis.com/database/postgresql/num_backends\" resource.type=\"cloudsql_database\""
      aligner = "ALIGN_MEAN"
      reducer = "REDUCE_SUM"
      group   = []
    },
  ]
}

resource "google_monitoring_dashboard" "main" {
  project = var.project_id

  dashboard_json = jsonencode({
    displayName = "${local.prefix} overview"
    mosaicLayout = {
      columns = 12
      tiles = concat(
        [
          for i, t in local.dashboard_tiles : {
            xPos   = (i % 2) * 6
            yPos   = floor(i / 2) * 4
            width  = 6
            height = 4
            widget = {
              title = t.title
              xyChart = {
                dataSets = [{
                  plotType = "LINE"
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = t.filter
                      aggregation = {
                        alignmentPeriod    = "60s"
                        perSeriesAligner   = t.aligner
                        crossSeriesReducer = t.reducer
                        groupByFields      = t.group
                      }
                    }
                  }
                }]
              }
            }
          }
        ],
        [{
          # Cost is tracked with the budget alerts and the Billing reports, because per-plan
          # cost needs a billing export to BigQuery, which is not set up here.
          xPos   = 0
          yPos   = 16
          width  = 12
          height = 2
          widget = {
            title = "Cost"
            text = {
              format  = "MARKDOWN"
              content = "Spend is watched by the budget alerts (50%, 90%, 100% and forecast). Open **Billing > Reports** for detail. Cost per completed move plan needs a billing export to BigQuery, which is a pilot task."
            }
          }
        }]
      )
    }
  })

  depends_on = [google_project_service.apis]
}
