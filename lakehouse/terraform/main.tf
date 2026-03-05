provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "project" {
  project_id = var.project_id
}

locals {
  topic      = "projects/${var.project_id}/topics/${var.pubsub_topic}"
  bq_dataset = google_bigquery_dataset.mqtt.dataset_id
}

# ── BigQuery dataset ────────────────────────────────────────────────────────

resource "google_bigquery_dataset" "mqtt" {
  project     = var.project_id
  dataset_id  = "mqtt"
  location    = "EU"
  description = "MQTT message history from mqtt2pubsub via Pub/Sub BigQuery subscriptions."
}

# ── IAM: Pub/Sub service agent → BigQuery ───────────────────────────────────

resource "google_bigquery_dataset_iam_member" "pubsub_bq_writer" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.mqtt.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

# ── History table ───────────────────────────────────────────────────────────
# Single table receives every message via standard Pub/Sub BigQuery subscription
# schema (write_metadata = true). Views per event_type provide filtered access.

resource "google_bigquery_table" "history" {
  project             = var.project_id
  dataset_id          = local.bq_dataset
  table_id            = "history"
  description         = "All MQTT messages. Standard Pub/Sub subscription schema with write_metadata."
  deletion_protection = false

  time_partitioning {
    type  = "DAY"
    field = "publish_time"
  }
  clustering = ["publish_time"]

  schema = jsonencode([
    { name = "subscription_name", type = "STRING",    mode = "NULLABLE" },
    { name = "message_id",        type = "STRING",    mode = "NULLABLE" },
    { name = "publish_time",      type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "data",              type = "BYTES",     mode = "NULLABLE", description = "Raw Pub/Sub message payload." },
    { name = "attributes",        type = "JSON",      mode = "NULLABLE", description = "All message attributes." }
  ])

  depends_on = [google_bigquery_dataset.mqtt]
}

# ── History subscription ────────────────────────────────────────────────────

resource "google_pubsub_subscription" "history_bq" {
  project = var.project_id
  name    = "mqtt-history-bq"
  topic   = local.topic

  bigquery_config {
    table               = "${var.project_id}:${local.bq_dataset}.${google_bigquery_table.history.table_id}"
    use_table_schema    = false
    write_metadata      = true
    drop_unknown_fields = false
  }

  message_retention_duration = "604800s"
  expiration_policy { ttl = "" }

  depends_on = [google_bigquery_table.history]
}

# ── Views per event_type ────────────────────────────────────────────────────
# Each view filters the history table by event_type and extracts payload + meta
# from the raw data bytes.

resource "google_bigquery_table" "event_type_view" {
  for_each = toset(var.mqtt_event_types)

  project             = var.project_id
  dataset_id          = local.bq_dataset
  table_id            = each.key
  description         = "View: MQTT messages with event_type = ${each.key}."
  deletion_protection = false

  view {
    query          = <<-SQL
      SELECT
        message_id,
        publish_time,
        attributes,
        JSON_QUERY(SAFE_CONVERT_BYTES_TO_STRING(data), '$.payload') AS payload,
        JSON_QUERY(SAFE_CONVERT_BYTES_TO_STRING(data), '$._meta')   AS meta
      FROM `${var.project_id}.${local.bq_dataset}.${google_bigquery_table.history.table_id}`
      WHERE JSON_VALUE(attributes, '$.event_type') = '${each.key}'
    SQL
    use_legacy_sql = false
  }
}
