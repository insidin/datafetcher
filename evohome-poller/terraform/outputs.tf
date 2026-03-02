output "cloud_run_job_name" {
  description = "Cloud Run Job name."
  value       = google_cloud_run_v2_job.poller.name
}

output "pubsub_topic_id" {
  description = "Pub/Sub topic ID (full resource path)."
  value       = google_pubsub_topic.evohome_status.id
}

output "cache_bucket" {
  description = "GCS bucket name for OAuth token cache."
  value       = local.cache_bucket_name
}

output "scheduler_name" {
  description = "Cloud Scheduler job name."
  value       = google_cloud_scheduler_job.poller.name
}
