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
    { name = "MQTT_KEEPALIVE_SEC", value = var.mqtt_keepalive_sec },
    { name = "MQTT_CLIENT_ID", value = var.mqtt_client_id },
    { name = "MQTT_TLS_ENABLED", value = var.mqtt_tls_enabled ? "true" : "false" },
    { name = "MQTT_TLS_INSECURE", value = var.mqtt_tls_insecure ? "true" : "false" },
    { name = "MQTT_TLS_CA_CERT", value = var.mqtt_tls_ca_cert },
    { name = "PUBSUB_TOPIC", value = google_pubsub_topic.mqtt_ingest.id },
    { name = "GCP_PROJECT_ID", value = var.project_id },
    { name = "PUBSUB_PUBLISH_TIMEOUT_SEC", value = tostring(var.pubsub_publish_timeout_sec) },
    { name = "PUBSUB_PUBLISH_RETRIES", value = tostring(var.pubsub_publish_retries) },
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
  name                       = var.pubsub_topic_name
  labels                     = var.labels
  message_retention_duration = var.pubsub_message_retention
}

# Scoped to this topic only — not the entire project.
resource "google_pubsub_topic_iam_member" "job_publisher" {
  topic  = google_pubsub_topic.mqtt_ingest.id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${var.service_account_email}"
}

resource "google_cloud_run_v2_service" "mqtt2pubsub" {
  name                = var.service_name
  location            = var.region
  deletion_protection = false
  labels              = var.labels

  template {
    service_account = var.service_account_email

    scaling {
      min_instance_count = var.min_instance_count
      max_instance_count = 1 # singleton worker — MQTT state is not shareable across instances
    }

    containers {
      image = var.container_image

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
        cpu_idle = false # keep CPU allocated so the MQTT loop runs continuously
      }

      ports {
        container_port = 8080
      }

      dynamic "env" {
        for_each = local.plain_env
        content {
          name  = env.value.name
          value = tostring(env.value.value)
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

      # Startup probe: give the process time to bind the port and connect to MQTT.
      # Budget = initial_delay_seconds + (period_seconds × failure_threshold) = 5 + 10×18 = 185s.
      startup_probe {
        http_get {
          path = "/"
        }
        initial_delay_seconds = 5
        timeout_seconds       = 5
        period_seconds        = 10
        failure_threshold     = 18
      }

      # Liveness probe: restart the container if it stops responding (e.g. crashed MQTT loop).
      liveness_probe {
        http_get {
          path = "/"
        }
        initial_delay_seconds = 30
        timeout_seconds       = 5
        period_seconds        = 30
        failure_threshold     = 3
      }
    }
  }

  depends_on = [
    google_pubsub_topic_iam_member.job_publisher,
  ]
}
