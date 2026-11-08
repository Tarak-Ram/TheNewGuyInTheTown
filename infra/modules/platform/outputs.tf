output "urls" {
  description = "Where each service answers."
  value = {
    web     = google_cloud_run_v2_service.web.uri
    api     = google_cloud_run_v2_service.api.uri
    gateway = google_cloud_run_v2_service.gateway.uri
    worker  = google_cloud_run_v2_service.worker.uri
  }
}

output "computed_urls_match" {
  description = "The web app and gateway use computed addresses. This must be true, or the services cannot find each other."
  value = {
    web     = local.service_url.web == google_cloud_run_v2_service.web.uri
    api     = local.service_url.api == google_cloud_run_v2_service.api.uri
    gateway = local.service_url.gateway == google_cloud_run_v2_service.gateway.uri
    worker  = local.service_url.worker == google_cloud_run_v2_service.worker.uri
  }
}

# Warns (does not block) if Cloud Run's real addresses differ from the ones computed in main.tf.
# If this warns after the first apply, set the correct format in local.service_url.
check "service_urls_match" {
  assert {
    condition = alltrue([
      local.service_url.web == google_cloud_run_v2_service.web.uri,
      local.service_url.api == google_cloud_run_v2_service.api.uri,
      local.service_url.gateway == google_cloud_run_v2_service.gateway.uri,
      local.service_url.worker == google_cloud_run_v2_service.worker.uri,
    ])
    error_message = "A Cloud Run address differs from the computed one. The web app and the gateway may not find each other. See infra/README.md."
  }
}

output "artifact_registry" {
  description = "Push images here."
  value       = local.registry
}

output "images" {
  value = local.images
}

output "database_connection_name" {
  value = google_sql_database_instance.main.connection_name
}

output "buckets" {
  value = {
    agreements = google_storage_bucket.agreements.name
    audio      = google_storage_bucket.audio.name
  }
}

output "migrate_job" {
  value = google_cloud_run_v2_job.migrate.name
}

output "deployer" {
  description = "Put these two values in the GitHub repository's variables."
  value = {
    service_account            = local.sa["deployer"]
    workload_identity_provider = google_iam_workload_identity_pool_provider.github.name
  }
}

output "secrets_to_fill" {
  description = "Add the real value of each, as a new version. Until then the features that need them show a clear error."
  value       = [for n in local.manual_secrets : "${local.prefix}-${n}"]
}
