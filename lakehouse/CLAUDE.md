# lakehouse — CLAUDE.md

## What this app is

Terraform-only app. No running service. Manages a BigQuery dataset with a
single history table and per-event-type views, plus one Pub/Sub BigQuery
subscription that feeds all MQTT messages into the history table.

## Directory layout

```
lakehouse/
├── terraform/          # All Terraform — the only artefact this app produces
│   ├── main.tf         # BigQuery dataset + history table + subscription + views
│   ├── variables.tf
│   ├── outputs.tf
│   └── versions.tf
├── docs/adr/           # Architecture decisions
├── BACKLOG.md          # Open items and investigations
└── CLAUDE.md           # This file
```

## Architecture

- **One history table** (`mqtt.history`) — standard Pub/Sub subscription schema
  with `write_metadata = true`. Columns: `subscription_name`, `message_id`,
  `publish_time`, `data` (BYTES), `attributes` (JSON).
- **One subscription** (`mqtt-history-bq`) — catch-all, no filter, writes every
  message from the `mqtt-ingest` topic.
- **Views per event_type** — filtered views on the history table that extract
  `payload` and `meta` from the raw `data` bytes using `JSON_QUERY()`.

See [ADR-001](docs/adr/ADR-001-views-over-typed-tables.md) for why views were
chosen over per-event-type tables.

## Deploying

```bash
cd lakehouse/terraform
terraform init -backend-config="bucket=<project>-tfstate" -backend-config="prefix=lakehouse"
terraform apply
```

Required GitHub secret: `LAKEHOUSE_GCP_DEPLOYER_SERVICE_ACCOUNT`
Optional GitHub secrets:
- `LAKEHOUSE_PUBSUB_TOPIC` (default: `mqtt-ingest`)
- `MQTT_EVENT_TYPES` (comma-separated list — drives view creation)

## Adding a new event type view

Add the event type to the `MQTT_EVENT_TYPES` GitHub secret (comma-separated).
The next deploy creates the view automatically via `for_each`.

## Querying

```sql
-- Via view
SELECT * FROM `<project>.mqtt.shellyhtg3_status_temperature_0`
ORDER BY publish_time DESC LIMIT 10;

-- Direct from history with payload extraction
SELECT
  publish_time,
  JSON_QUERY(SAFE_CONVERT_BYTES_TO_STRING(data), '$.payload') AS payload,
  attributes
FROM `<project>.mqtt.history`
WHERE JSON_VALUE(attributes, '$.event_type') = 'shellyhtg3_status_temperature_0'
ORDER BY publish_time DESC LIMIT 10;
```

## Conventions

- Partition history table by `DAY` on `publish_time`.
- Use `JSON` type for `attributes` — keeps all Pub/Sub metadata queryable.
- View names match event_type names exactly.
