variable "project_id" {
  type        = string
  description = "GCP project ID."
}

variable "region" {
  type        = string
  description = "GCP region for Cloud Run Job."
  default     = "us-central1"
}

variable "job_name" {
  type        = string
  description = "Cloud Run Job name."
  default     = "mqtt2pubsub-job"
}

variable "container_image" {
  type        = string
  description = "Container image URL (for example gcr.io/<project>/mqtt2pubsub:latest)."
}

variable "service_account_id" {
  type        = string
  description = "Service account ID (not email) used by Cloud Run Job."
  default     = "mqtt2pubsub-job-sa"
}

variable "pubsub_topic_name" {
  type        = string
  description = "Pub/Sub topic name where messages are forwarded."
  default     = "mqtt-ingest"
}

variable "task_timeout_seconds" {
  type        = number
  description = "Cloud Run task timeout in seconds."
  default     = 86400
}

variable "task_max_retries" {
  type        = number
  description = "Cloud Run task max retries."
  default     = 1
}

variable "task_count" {
  type        = number
  description = "Number of tasks per execution."
  default     = 1
}

variable "parallelism" {
  type        = number
  description = "Max tasks run in parallel."
  default     = 1
}

variable "cpu" {
  type        = string
  description = "CPU limit for container."
  default     = "1"
}

variable "memory" {
  type        = string
  description = "Memory limit for container."
  default     = "512Mi"
}

variable "log_level" {
  type        = string
  description = "Application log level."
  default     = "INFO"
}

variable "max_messages" {
  type        = number
  description = "Stop after forwarding this many messages; 0 means unlimited."
  default     = 0
}

variable "max_runtime_sec" {
  type        = number
  description = "Stop after this runtime in seconds; 0 means unlimited."
  default     = 0
}

variable "mqtt_host" {
  type        = string
  description = "MQTT broker host."
}

variable "mqtt_port" {
  type        = number
  description = "MQTT broker port."
  default     = 8883
}

variable "mqtt_topic" {
  type        = string
  description = "Single MQTT topic filter to subscribe to. Optional when device_identifiers is set."
  default     = ""
}

variable "device_identifiers" {
  type        = string
  description = "Comma-separated list of device identifiers. Each identifier expands via mqtt_topic_template."
  default     = ""
}

variable "mqtt_topic_template" {
  type        = string
  description = "Template used with device_identifiers. Must contain {identifier}."
  default     = "{identifier}/#"
}

variable "mqtt_consumer_clients" {
  type        = number
  description = "Number of parallel MQTT clients to consume topic filter groups."
  default     = 1
}

variable "mqtt_qos" {
  type        = number
  description = "MQTT QoS level (0, 1, or 2)."
  default     = 1
}

variable "mqtt_keepalive_sec" {
  type        = number
  description = "MQTT keepalive seconds."
  default     = 60
}

variable "mqtt_client_id" {
  type        = string
  description = "MQTT client identifier."
  default     = "mqtt2pubsub"
}

variable "mqtt_tls_enabled" {
  type        = bool
  description = "Enable TLS to MQTT broker."
  default     = true
}

variable "mqtt_tls_insecure" {
  type        = bool
  description = "Allow insecure TLS verification (not recommended)."
  default     = false
}

variable "mqtt_tls_ca_cert" {
  type        = string
  description = "Optional path inside the container to a CA cert file."
  default     = ""
}

variable "pubsub_publish_timeout_sec" {
  type        = number
  description = "Timeout for one Pub/Sub publish call."
  default     = 30
}

variable "pubsub_publish_retries" {
  type        = number
  description = "Application-level retries when publish fails."
  default     = 5
}

variable "event_type_topic_map" {
  type        = string
  description = "Semicolon-separated topic map '<mqtt_filter>=<event_type>;...'. First match wins."
  default     = ""
}

variable "event_type_json_fields" {
  type        = string
  description = "Comma-separated payload JSON fields checked for event type when no topic map match."
  default     = "event_type,type,kind"
}

variable "event_type_fallback" {
  type        = string
  description = "Fallback event type when no mapping/field is found."
  default     = "unknown"
}

variable "mqtt_username_secret" {
  type        = string
  description = "Secret Manager secret name for MQTT username. Leave empty to skip."
  default     = ""
}

variable "mqtt_username_secret_version" {
  type        = string
  description = "Secret version for MQTT username."
  default     = "latest"
}

variable "mqtt_password_secret" {
  type        = string
  description = "Secret Manager secret name for MQTT password. Leave empty to skip."
  default     = ""
}

variable "mqtt_password_secret_version" {
  type        = string
  description = "Secret version for MQTT password."
  default     = "latest"
}

variable "labels" {
  type        = map(string)
  description = "Labels applied to created resources where supported."
  default     = {}
}
