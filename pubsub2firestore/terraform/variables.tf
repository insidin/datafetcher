variable "project_id" {
  type        = string
  description = "GCP project ID."
}

variable "region" {
  type        = string
  description = "GCP region for Cloud Run service."
  default     = "europe-west1"
}

variable "container_image" {
  type        = string
  description = "Fully-qualified container image URL (e.g. europe-west1-docker.pkg.dev/…/pubsub2firestore:sha)."
}

variable "service_account_email" {
  type        = string
  description = "Worker service account email to attach to the Cloud Run service."
}

variable "pubsub_topic" {
  type        = string
  description = "Pub/Sub topic name to subscribe to."
  default     = "mqtt-ingest"
}

variable "subscription_filter" {
  type        = string
  description = "Optional Pub/Sub filter expression to limit which messages this service processes. Leave empty for all messages."
  default     = ""
}

variable "ttl_days" {
  type        = number
  description = "Number of days to retain time-series readings in Firestore before they expire."
  default     = 30
}

variable "log_level" {
  type        = string
  description = "Python log level (DEBUG, INFO, WARNING, ERROR)."
  default     = "INFO"
}
