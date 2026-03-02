variable "project_id" {
  type        = string
  description = "GCP project ID."
}

variable "region" {
  type        = string
  description = "GCP region for Cloud Run Job and Cloud Scheduler."
  default     = "europe-west1"
}

variable "container_image" {
  type        = string
  description = "Container image URL (e.g., europe-west1-docker.pkg.dev/<project>/evohome-poller/evohome-poller:<sha>)."
}

variable "service_account_email" {
  type        = string
  description = "Worker service account email. Created by the platform app-deployer module; passed via TF_VAR_service_account_email in the deploy workflow."
}

variable "job_name" {
  type        = string
  description = "Cloud Run Job name."
  default     = "evohome-poller"
}

variable "job_timeout_sec" {
  type        = number
  description = "Maximum execution time for one Cloud Run Job run."
  default     = 300
}

variable "location_id" {
  type        = string
  description = "Evohome location ID to poll."
  default     = "7952144"
}

variable "pubsub_topic_name" {
  type        = string
  description = "Pub/Sub topic name for evohome status snapshots."
  default     = "evohome-status"
}

variable "pubsub_message_retention" {
  type        = string
  description = "How long the Pub/Sub topic retains published messages, even without a subscription. Format: duration with 's' suffix (e.g. '604800s' = 7 days). Range: 600s–2678400s."
  default     = "604800s" # 7 days
}

variable "scheduler_name" {
  type        = string
  description = "Cloud Scheduler job name."
  default     = "evohome-poller-schedule"
}

variable "scheduler_cron" {
  type        = string
  description = "Cron schedule for Cloud Scheduler."
  default     = "*/5 * * * *"
}

variable "secret_name_username" {
  type        = string
  description = "Secret Manager secret name for Evohome username. Must already exist."
  default     = "evohome-username"
}

variable "secret_name_password" {
  type        = string
  description = "Secret Manager secret name for Evohome password. Must already exist."
  default     = "evohome-password"
}

variable "log_level" {
  type        = string
  description = "Application log level."
  default     = "INFO"
}

variable "labels" {
  type        = map(string)
  description = "Labels applied to created resources where supported."
  default     = {}
}
