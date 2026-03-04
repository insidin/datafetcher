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
# The Google-managed Pub/Sub service agent needs dataEditor on the dataset
# to write messages from BigQuery subscriptions into tables.

resource "google_bigquery_dataset_iam_member" "pubsub_bq_writer" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.mqtt.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

# ── BigQuery tables (per event_type) ────────────────────────────────────────
# Generic schema: payload and _meta are JSON columns so the schema never needs
# changing as device firmware evolves or new devices are added.
# For BigLake Iceberg format (enabling DuckDB iceberg_scan), run the DDL in
# docs/iceberg_ddl.sql after first terraform apply — Terraform provider v5
# does not yet expose native managed-Iceberg table creation.

resource "google_bigquery_table" "event_type" {
  for_each = toset(var.mqtt_event_types)

  project     = var.project_id
  dataset_id  = local.bq_dataset
  table_id    = each.key
  description = "MQTT messages with event_type = ${each.key}."

  time_partitioning {
    type  = "DAY"
    field = "_publish_time"
  }
  clustering = ["_publish_time"]

  schema = jsonencode([
    { name = "_message_id",   type = "STRING",    mode = "NULLABLE", description = "Pub/Sub message ID." },
    { name = "_publish_time", type = "TIMESTAMP", mode = "NULLABLE", description = "Pub/Sub publish timestamp." },
    { name = "_attributes",   type = "JSON",      mode = "NULLABLE", description = "All Pub/Sub message attributes." },
    { name = "payload",       type = "JSON",      mode = "NULLABLE", description = "MQTT payload (unwrapped inner payload)." },
    { name = "_meta",         type = "JSON",      mode = "NULLABLE", description = "Routing metadata: event_type, device_uid, device_type, device_id, message_type." }
  ])

  depends_on = [google_bigquery_dataset.mqtt]
}

# ── History table (catch-all) ────────────────────────────────────────────────
# Receives every message on the topic regardless of event_type.
# Uses standard Pub/Sub subscription schema (no use_table_schema).

resource "google_bigquery_table" "history" {
  project     = var.project_id
  dataset_id  = local.bq_dataset
  table_id    = "history"
  description = "Catch-all: every message on the topic. Standard Pub/Sub subscription schema."

  time_partitioning {
    type  = "DAY"
    field = "publish_time"
  }
  clustering = ["publish_time"]

  schema = jsonencode([
    { name = "subscription_name", type = "STRING",    mode = "NULLABLE" },
    { name = "message_id",        type = "STRING",    mode = "NULLABLE" },
    { name = "publish_time",      type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "data",              type = "BYTES",     mode = "NULLABLE", description = "Raw payload bytes." },
    { name = "attributes",        type = "JSON",      mode = "NULLABLE", description = "All message attributes." }
  ])

  depends_on = [google_bigquery_dataset.mqtt]
}

# ── Pub/Sub → BigQuery subscriptions (per event_type) ───────────────────────
# Each subscription filters by event_type attribute and maps the JSON payload
# to the generic table schema.

resource "google_pubsub_subscription" "event_type_bq" {
  for_each = toset(var.mqtt_event_types)

  project = var.project_id
  name    = "${replace(each.key, "_", "-")}-bq"
  topic   = local.topic
  filter  = "attributes.event_type = \"${each.key}\""

  bigquery_config {
    table               = "${var.project_id}:${local.bq_dataset}.${each.key}"
    use_table_schema    = true
    drop_unknown_fields = true
  }

  message_retention_duration = "604800s"
  expiration_policy { ttl = "" }

  depends_on = [google_bigquery_table.event_type]
}

# ── History subscription (catch-all) ────────────────────────────────────────

resource "google_pubsub_subscription" "history_bq" {
  project = var.project_id
  name    = "mqtt-history-bq"
  topic   = local.topic
  # No filter — catches everything, including event types without a typed table.

  bigquery_config {
    table               = "${var.project_id}:${local.bq_dataset}.${google_bigquery_table.history.table_id}"
    use_table_schema    = false
    drop_unknown_fields = false
  }

  message_retention_duration = "604800s"
  expiration_policy { ttl = "" }

  depends_on = [google_bigquery_table.history]
}
