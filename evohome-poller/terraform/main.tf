# Bucket name is derived from project_id — deterministic and globally unique.
# The bucket is created by the platform terraform (data-platform-gcp); the same
# formula is used there so both sides always reference the same bucket.
locals {
  cache_bucket_name = "${var.project_id}-evohome-token-cache"
}

# ── Pub/Sub topic ──────────────────────────────────────────────────────────────

resource "google_pubsub_topic" "evohome_status" {
  name                       = var.pubsub_topic_name
  labels                     = var.labels
  message_retention_duration = var.pubsub_message_retention
}

# Scoped to this topic only — not project-wide.
resource "google_pubsub_topic_iam_member" "worker_publisher" {
  topic  = google_pubsub_topic.evohome_status.id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${var.service_account_email}"
}

# ── GCS token cache bucket IAM ───────────────────────────────────────────────
# The bucket is created by the platform terraform. This block grants the worker
# SA write access to store and retrieve the OAuth token cache between runs.
# The deployer SA has storage.admin scoped to this bucket (granted in the
# platform terraform), which allows it to apply this IAM binding.

resource "google_storage_bucket_iam_member" "worker_cache_access" {
  bucket = local.cache_bucket_name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.service_account_email}"
}

# ── Cloud Run Job ─────────────────────────────────────────────────────────────

resource "google_cloud_run_v2_job" "poller" {
  name     = var.job_name
  location = var.region
  labels   = var.labels

  template {
    template {
      service_account = var.service_account_email
      timeout         = "${var.job_timeout_sec}s"
      max_retries     = 0 # fail fast; Cloud Scheduler will retry on the next tick

      containers {
        image = var.container_image

        args = [
          "--location-id", var.location_id,
          "--pubsub-topic", google_pubsub_topic.evohome_status.id,
          "--cache", "gs://${local.cache_bucket_name}/token_cache.json",
          "--log-level", var.log_level,
        ]

        env {
          name = "EVOHOME_USERNAME"
          value_source {
            secret_key_ref {
              secret  = var.secret_name_username
              version = "latest"
            }
          }
        }

        env {
          name = "EVOHOME_PASSWORD"
          value_source {
            secret_key_ref {
              secret  = var.secret_name_password
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [
    google_pubsub_topic_iam_member.worker_publisher,
    google_storage_bucket_iam_member.worker_cache_access,
  ]
}

# ── Cloud Scheduler ───────────────────────────────────────────────────────────
# The worker SA is also the scheduler's OAuth identity. run.invoker is granted
# project-wide to the worker SA by the platform app-deployer module
# (worker_extra_roles = ["roles/run.invoker"]), so no job-level IAM binding is
# needed here. This avoids requiring roles/run.admin for the deployer SA.

resource "google_cloud_scheduler_job" "poller" {
  name     = var.scheduler_name
  region   = var.region
  schedule = var.scheduler_cron

  http_target {
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.poller.name}:run"
    http_method = "POST"

    headers = {
      "Content-Type" = "application/json"
    }

    oauth_token {
      service_account_email = var.service_account_email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

}
