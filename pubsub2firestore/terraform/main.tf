provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  topic = "projects/${var.project_id}/topics/${var.pubsub_topic}"
}

# ── Pub/Sub pull subscription ────────────────────────────────────────────────
# Filter is optional — leave empty to receive all messages on the topic.

resource "google_pubsub_subscription" "pubsub2firestore" {
  project = var.project_id
  name    = "pubsub2firestore"
  topic   = local.topic
  filter  = var.subscription_filter

  # Retain undelivered messages for up to 7 days (matches topic retention).
  message_retention_duration = "604800s"
  expiration_policy { ttl = "" } # subscription never expires

  ack_deadline_seconds = 60

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}

# Worker SA may subscribe and ACK messages on this specific subscription only.
resource "google_pubsub_subscription_iam_member" "worker_subscriber" {
  project      = var.project_id
  subscription = google_pubsub_subscription.pubsub2firestore.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${var.service_account_email}"
}

# ── Cloud Run service ────────────────────────────────────────────────────────

resource "google_cloud_run_v2_service" "pubsub2firestore" {
  project  = var.project_id
  name     = "pubsub2firestore"
  location = var.region

  template {
    service_account = var.service_account_email

    scaling {
      min_instance_count = 1 # always-on: Pub/Sub streaming pull needs a persistent connection
      max_instance_count = 1 # singleton: no need to fan out pull subscribers
    }

    containers {
      image = var.container_image

      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "PUBSUB_SUBSCRIPTION"
        value = "projects/${var.project_id}/subscriptions/${google_pubsub_subscription.pubsub2firestore.name}"
      }
      env {
        name  = "TTL_DAYS"
        value = tostring(var.ttl_days)
      }
      env {
        name  = "LOG_LEVEL"
        value = var.log_level
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "256Mi"
        }
      }

      startup_probe {
        http_get { path = "/" }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 10
        timeout_seconds       = 3
      }

      liveness_probe {
        http_get { path = "/" }
        period_seconds    = 30
        failure_threshold = 3
        timeout_seconds   = 3
      }
    }
  }

  depends_on = [google_pubsub_subscription.pubsub2firestore]
}
