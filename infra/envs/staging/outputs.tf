output "urls" {
  value = module.platform.urls
}

output "computed_urls_match" {
  value = module.platform.computed_urls_match
}

output "artifact_registry" {
  value = module.platform.artifact_registry
}

output "database_connection_name" {
  value = module.platform.database_connection_name
}

output "buckets" {
  value = module.platform.buckets
}

output "migrate_job" {
  value = module.platform.migrate_job
}

output "deployer" {
  value = module.platform.deployer
}

output "secrets_to_fill" {
  value = module.platform.secrets_to_fill
}
