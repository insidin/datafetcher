variable "project_id" {
  type        = string
  description = "GCP project ID."
}

variable "region" {
  type        = string
  description = "GCP region for BigQuery dataset location."
  default     = "europe-west1"
}

variable "pubsub_topic" {
  type        = string
  description = "Pub/Sub topic name to create BigQuery subscriptions on."
  default     = "mqtt-ingest"
}

variable "mqtt_event_types" {
  type        = list(string)
  description = "Event types to create individual BigQuery tables and subscriptions for. Each value becomes a table_id and subscription filter."
  default     = []
}
