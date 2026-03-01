locals {
  plain_env = [
    { name = "FORWARD_MODE", value = "pubsub" },
    { name = "LOG_LEVEL", value = var.log_level },
    { name = "MQTT_HOST", value = var.mqtt_host },
    { name = "MQTT_PORT", value = tostring(var.mqtt_port) },
    { name = "MQTT_TOPIC", value = var.mqtt_topic },
    { name = "DEVICE_IDENTIFIERS", value = var.device_identifiers },
    { name = "MQTT_TOPIC_TEMPLATE", value = var.mqtt_topic_template },
    { name = "MQTT_CONSUMER_CLIENTS", value = tostring(var.mqtt_consumer_clients) },
    { name = "MQTT_QOS", value = tostring(var.mqtt_qos) },
    { name = "MQTT_KEEPALIVE_SEC", value = tostring(var.mqtt_keepalive_sec) },
    { name = "MQTT_CLIENT_ID", value = var.mqtt_client_id },
    { name = "MQTT_TLS_ENABLED", value = var.mqtt_tls_enabled ? "true" : "false" },
    { name = "MQTT_TLS_INSECURE", value = var.mqtt_tls_insecure ? "true" : "false" },
    { name = "MQTT_TLS_CA_CERT", value = var.mqtt_tls_ca_cert },
    { name = "PUBSUB_TOPIC", value = google_pubsub_topic.mqtt_ingest.id },
    { name = "GCP_PROJECT_ID", value = var.project_id },
    { name = "PUBSUB_PUBLISH_TIMEOUT_SEC", value = tostring(var.pubsub_publish_timeout_sec) },
    { name = "PUBSUB_PUBLISH_RETRIES", value = tostring(var.pubsub_publish_retries) },
    { name = "EVENT_TYPE_TOPIC_MAP", value = var.event_type_topic_map },
    { name = "EVENT_TYPE_JSON_FIELDS", value = var.event_type_json_fields },
    { name = "EVENT_TYPE_FALLBACK", value = var.event_type_fallback },
    { name = "MAX_MESSAGES", value = tostring(var.max_messages) },
    { name = "MAX_RUNTIME_SEC", value = tostring(var.max_runtime_sec) },
  ]

  secret_env = merge(
    var.mqtt_username_secret == "" ? {} : {
      MQTT_USERNAME = {
        secret  = var.mqtt_username_secret
        version = var.mqtt_username_secret_version
      }
    },
    var.mqtt_password_secret == "" ? {} : {
      MQTT_PASSWORD = {
        secret  = var.mqtt_password_secret
        version = var.mqtt_password_secret_version
      }
    }
  )
}

resource "google_pubsub_topic" "mqtt_ingest" {
  name   = var.pubsub_topic_name
  labels = var.labels
}

resource "google_service_account" "job" {
  account_id   = var.service_account_id
  display_name = "mqtt2pubsub Cloud Run Job"
}

resource "google_project_iam_member" "pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.job.email}"
}

resource "google_cloud_run_v2_job" "mqtt2pubsub" {
  name                = var.job_name
  location            = var.region
  deletion_protection = false
  labels              = var.labels

  template {
    task_count  = var.task_count
    parallelism = var.parallelism

    template {
      service_account = google_service_account.job.email
      max_retries     = var.task_max_retries
      timeout         = "${var.task_timeout_seconds}s"

      containers {
        image = var.container_image

        resources {
          limits = {
            cpu    = var.cpu
            memory = var.memory
          }
        }

        dynamic "env" {
          for_each = local.plain_env
          content {
            name  = env.value.name
            value = env.value.value
          }
        }

        dynamic "env" {
          for_each = local.secret_env
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = env.value.secret
                version = env.value.version
              }
            }
          }
        }
      }
    }
  }

  depends_on = [
    google_project_iam_member.pubsub_publisher,
  ]
}
