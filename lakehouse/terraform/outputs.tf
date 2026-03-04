output "bq_dataset" {
  description = "BigQuery dataset ID."
  value       = google_bigquery_dataset.mqtt.dataset_id
}

output "history_subscription" {
  description = "Name of the catch-all history Pub/Sub subscription."
  value       = google_pubsub_subscription.history_bq.name
}

output "lakehouse_bucket" {
  description = "GCS bucket for BigLake Iceberg files (created by platform terraform)."
  value       = "${var.project_id}-lakehouse"
}
