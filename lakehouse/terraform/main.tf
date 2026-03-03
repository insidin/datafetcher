provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  topic       = "projects/${var.project_id}/topics/${var.pubsub_topic}"
  bq_dataset  = google_bigquery_dataset.mqtt.dataset_id
  bucket_name = "${var.project_id}-lakehouse"
}

# ── BigQuery dataset ────────────────────────────────────────────────────────

resource "google_bigquery_dataset" "mqtt" {
  project    = var.project_id
  dataset_id = "mqtt"
  location   = "EU"
  description = "MQTT message history from mqtt2pubsub via Pub/Sub BigQuery subscriptions."
}

# ── BigQuery tables ─────────────────────────────────────────────────────────
# Tables use standard BigQuery partitioning + clustering for query efficiency.
# For BigLake Iceberg format (enabling DuckDB iceberg_scan), run the DDL in
# docs/iceberg_ddl.sql after first terraform apply — Terraform provider v5
# does not yet expose native managed-Iceberg table creation.
#
# Pub/Sub BigQuery subscriptions with use_table_schema=true map JSON payload
# fields to columns by name. The underscore-prefixed columns (_message_id,
# _publish_time, _attributes) are populated automatically by Pub/Sub.

resource "google_bigquery_table" "shelly_temperature" {
  project    = var.project_id
  dataset_id = local.bq_dataset
  table_id   = "shelly_temperature"
  description = "Shelly H&T temperature readings. Payload: {id, tC, tF}."

  time_partitioning {
    type  = "DAY"
    field = "_publish_time"
  }
  clustering = ["_publish_time"]

  schema = jsonencode([
    { name = "_message_id",   type = "STRING",    mode = "NULLABLE", description = "Pub/Sub message ID." },
    { name = "_publish_time", type = "TIMESTAMP", mode = "NULLABLE", description = "Pub/Sub publish timestamp." },
    { name = "_attributes",   type = "JSON",      mode = "NULLABLE", description = "All Pub/Sub message attributes." },
    { name = "id",            type = "INTEGER",   mode = "NULLABLE", description = "Shelly sensor index (always 0)." },
    { name = "tC",            type = "FLOAT",     mode = "NULLABLE", description = "Temperature in Celsius." },
    { name = "tF",            type = "FLOAT",     mode = "NULLABLE", description = "Temperature in Fahrenheit." }
  ])

  depends_on = [google_bigquery_dataset.mqtt]
}

resource "google_bigquery_table" "shelly_humidity" {
  project    = var.project_id
  dataset_id = local.bq_dataset
  table_id   = "shelly_humidity"
  description = "Shelly H&T humidity readings. Payload: {id, rh}."

  time_partitioning {
    type  = "DAY"
    field = "_publish_time"
  }
  clustering = ["_publish_time"]

  schema = jsonencode([
    { name = "_message_id",   type = "STRING",    mode = "NULLABLE" },
    { name = "_publish_time", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "_attributes",   type = "JSON",      mode = "NULLABLE" },
    { name = "id",            type = "INTEGER",   mode = "NULLABLE" },
    { name = "rh",            type = "FLOAT",     mode = "NULLABLE", description = "Relative humidity %." }
  ])

  depends_on = [google_bigquery_dataset.mqtt]
}

resource "google_bigquery_table" "shelly_battery" {
  project    = var.project_id
  dataset_id = local.bq_dataset
  table_id   = "shelly_battery"
  description = "Shelly H&T battery status. Payload: {id, battery:{V, percent}, external:{present}}."

  time_partitioning {
    type  = "DAY"
    field = "_publish_time"
  }
  clustering = ["_publish_time"]

  schema = jsonencode([
    { name = "_message_id",   type = "STRING",    mode = "NULLABLE" },
    { name = "_publish_time", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "_attributes",   type = "JSON",      mode = "NULLABLE" },
    { name = "id",            type = "INTEGER",   mode = "NULLABLE" },
    { name = "battery",       type = "JSON",      mode = "NULLABLE", description = "{V, percent}" },
    { name = "external",      type = "JSON",      mode = "NULLABLE", description = "{present}" }
  ])

  depends_on = [google_bigquery_dataset.mqtt]
}

resource "google_bigquery_table" "shelly_switch" {
  project    = var.project_id
  dataset_id = local.bq_dataset
  table_id   = "shelly_switch"
  description = "Shelly Plug S switch state + power metrics. Payload: {id, output, apower, voltage, current, freq, temperature, aenergy}."

  time_partitioning {
    type  = "DAY"
    field = "_publish_time"
  }
  clustering = ["_publish_time"]

  schema = jsonencode([
    { name = "_message_id",   type = "STRING",    mode = "NULLABLE" },
    { name = "_publish_time", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "_attributes",   type = "JSON",      mode = "NULLABLE" },
    { name = "id",            type = "INTEGER",   mode = "NULLABLE" },
    { name = "output",        type = "BOOLEAN",   mode = "NULLABLE", description = "Switch on/off." },
    { name = "apower",        type = "FLOAT",     mode = "NULLABLE", description = "Active power W." },
    { name = "voltage",       type = "FLOAT",     mode = "NULLABLE", description = "Voltage V." },
    { name = "current",       type = "FLOAT",     mode = "NULLABLE", description = "Current A." },
    { name = "freq",          type = "FLOAT",     mode = "NULLABLE", description = "Frequency Hz." },
    { name = "temperature",   type = "JSON",      mode = "NULLABLE", description = "Device internal temp {tC, tF}." },
    { name = "aenergy",       type = "JSON",      mode = "NULLABLE", description = "Energy {total Wh, by_minute, minute_ts}." }
  ])

  depends_on = [google_bigquery_dataset.mqtt]
}

resource "google_bigquery_table" "history" {
  project    = var.project_id
  dataset_id = local.bq_dataset
  table_id   = "history"
  description = "Catch-all: every message on the topic. Standard Pub/Sub subscription schema (no use_table_schema)."

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

# ── Pub/Sub → BigQuery subscriptions ────────────────────────────────────────
# Each typed subscription filters by event_type attribute and maps the JSON
# payload to the table schema. The catch-all uses the standard Pub/Sub schema.
#
# The EVENT_TYPE_TOPIC_MAP for mqtt2pubsub must be configured as:
#   +/status/temperature:0=shelly_temperature
#   +/status/humidity:0=shelly_humidity
#   +/status/devicepower:0=shelly_battery
#   +/status/switch:0=shelly_switch
#   +/events/rpc=shelly_rpc
#   +/online=shelly_online
# (shelly_rpc and shelly_online land in history — no typed table needed yet)

resource "google_pubsub_subscription" "shelly_temperature_bq" {
  project = var.project_id
  name    = "shelly-temperature-bq"
  topic   = local.topic
  filter  = "attributes.event_type = \"shelly_temperature\""

  bigquery_config {
    table               = "${var.project_id}:${local.bq_dataset}.${google_bigquery_table.shelly_temperature.table_id}"
    use_table_schema    = true
    drop_unknown_fields = true
  }

  # Retain undelivered messages for the full topic retention window.
  message_retention_duration = "604800s"
  expiration_policy { ttl = "" } # never expire the subscription itself

  depends_on = [google_bigquery_table.shelly_temperature]
}

resource "google_pubsub_subscription" "shelly_humidity_bq" {
  project = var.project_id
  name    = "shelly-humidity-bq"
  topic   = local.topic
  filter  = "attributes.event_type = \"shelly_humidity\""

  bigquery_config {
    table               = "${var.project_id}:${local.bq_dataset}.${google_bigquery_table.shelly_humidity.table_id}"
    use_table_schema    = true
    drop_unknown_fields = true
  }

  message_retention_duration = "604800s"
  expiration_policy { ttl = "" }

  depends_on = [google_bigquery_table.shelly_humidity]
}

resource "google_pubsub_subscription" "shelly_battery_bq" {
  project = var.project_id
  name    = "shelly-battery-bq"
  topic   = local.topic
  filter  = "attributes.event_type = \"shelly_battery\""

  bigquery_config {
    table               = "${var.project_id}:${local.bq_dataset}.${google_bigquery_table.shelly_battery.table_id}"
    use_table_schema    = true
    drop_unknown_fields = true
  }

  message_retention_duration = "604800s"
  expiration_policy { ttl = "" }

  depends_on = [google_bigquery_table.shelly_battery]
}

resource "google_pubsub_subscription" "shelly_switch_bq" {
  project = var.project_id
  name    = "shelly-switch-bq"
  topic   = local.topic
  filter  = "attributes.event_type = \"shelly_switch\""

  bigquery_config {
    table               = "${var.project_id}:${local.bq_dataset}.${google_bigquery_table.shelly_switch.table_id}"
    use_table_schema    = true
    drop_unknown_fields = true
  }

  message_retention_duration = "604800s"
  expiration_policy { ttl = "" }

  depends_on = [google_bigquery_table.shelly_switch]
}

resource "google_pubsub_subscription" "history_bq" {
  project = var.project_id
  name    = "mqtt-history-bq"
  topic   = local.topic
  # No filter — catches everything, including event types without a typed table.

  bigquery_config {
    table               = "${var.project_id}:${local.bq_dataset}.${google_bigquery_table.history.table_id}"
    use_table_schema    = false # standard Pub/Sub schema: subscription_name, message_id, publish_time, data, attributes
    drop_unknown_fields = false
  }

  message_retention_duration = "604800s"
  expiration_policy { ttl = "" }

  depends_on = [google_bigquery_table.history]
}
