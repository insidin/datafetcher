output "cloud_run_job_name" {
  description = "Cloud Run Job name."
  value       = google_cloud_run_v2_job.mqtt2pubsub.name
}

output "cloud_run_job_location" {
  description = "Cloud Run Job region."
  value       = google_cloud_run_v2_job.mqtt2pubsub.location
}

output "pubsub_topic_id" {
  description = "Pub/Sub topic ID (projects/.../topics/...)."
  value       = google_pubsub_topic.mqtt_ingest.id
}

output "service_account_email" {
  description = "Service account used by the Cloud Run Job."
  value       = google_service_account.job.email
}
