# lakehouse — CLAUDE.md

## What this app is

Terraform-only app. No running service. Manages BigQuery datasets, tables, and
Pub/Sub BigQuery subscriptions that form the historical data lakehouse for all
datafetcher sources.

## Directory layout

```
lakehouse/
├── terraform/          # All Terraform — the only artefact this app produces
│   ├── main.tf         # BigQuery datasets + tables + Pub/Sub subscriptions
│   ├── variables.tf
│   ├── outputs.tf
│   └── versions.tf
└── docs/adr/           # Architecture decisions
```

## Deploying

```bash
cd lakehouse/terraform
terraform init -backend-config="bucket=<project>-tfstate" -backend-config="prefix=lakehouse"
terraform apply
```

Required GitHub secret: `LAKEHOUSE_GCP_DEPLOYER_SERVICE_ACCOUNT`
Optional GitHub secret: `LAKEHOUSE_PUBSUB_TOPIC` (default: `mqtt-ingest`)

## BigLake Iceberg upgrade

The tables are currently standard BigQuery partitioned tables. To upgrade to
managed BigLake Iceberg format (enables `DuckDB iceberg_scan`), run:

```bash
# One-time, after terraform apply has created the tables:
bq query --use_legacy_sql=false "
  ALTER TABLE \`<project>.mqtt.shelly_temperature\`
  SET OPTIONS (file_format='PARQUET', table_format='ICEBERG',
               storage_uri='gs://<project>-lakehouse/iceberg/mqtt/shelly_temperature/');
"
# Repeat for each table: shelly_humidity, shelly_battery, shelly_switch, history
```

This is tracked in ADR-001.

## Adding a new event type

1. Add a `google_bigquery_table` resource to `main.tf` with the correct schema.
2. Add a `google_pubsub_subscription` resource with a `filter` on `attributes.event_type`.
3. Update `EVENT_TYPE_TOPIC_MAP` in the `mqtt2pubsub` Cloud Run env (GitHub secret).
4. Run `terraform apply`.

## Conventions

- Partition all tables by `DAY` on the timestamp column.
- Use `JSON` type for nested payload objects rather than flattening — keeps the
  schema stable as device firmware evolves.
- Subscription names: `{event_type}-bq` for typed, `mqtt-history-bq` for catch-all.
