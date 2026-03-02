output "cloud_run_service_name" {
  description = "Cloud Run Service name."
  value       = google_cloud_run_v2_service.mqtt2pubsub.name
}

output "cloud_run_service_location" {
  description = "Cloud Run Service region."
  value       = google_cloud_run_v2_service.mqtt2pubsub.location
}

output "pubsub_topic_id" {
  description = "Pub/Sub topic ID (projects/.../topics/...)."
  value       = google_pubsub_topic.mqtt_ingest.id
}
