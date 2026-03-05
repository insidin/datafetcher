# Lakehouse — Backlog

Open items, investigations, and future work.

## Investigate: `use_table_schema = true` does not write to BigQuery

**Priority:** High
**Context:** [ADR-001](docs/adr/ADR-001-views-over-typed-tables.md)

Pub/Sub BigQuery subscriptions with `use_table_schema = true` never wrote a
single row, despite subscriptions being ACTIVE and messages flowing. No errors
visible anywhere. The workaround is views on the history table.

**What was tried:**
- Correct reserved column names (`message_id`, `publish_time`, `attributes`)
- `write_metadata = true`
- `drop_unknown_fields = true`
- Simplified table without `_meta` column (underscore prefix theory) — still fails
- Simplified table with only `payload: JSON` column — still fails
- No filter on subscription — still fails
- No `write_metadata` — still fails
- IAM: `roles/bigquery.dataEditor` granted to Pub/Sub service agent on dataset

**What to investigate next:**
- [ ] Try with non-JSON column types (e.g. `payload STRING`) to rule out JSON type issue
- [ ] Try with a topic schema + `use_topic_schema` instead of `use_table_schema`
- [ ] Check if BigQuery dataset location (EU) matters
- [ ] Open a GCP support case if all else fails
- [ ] Check if there are quota/billing restrictions affecting Storage Write API

## Feature: Iceberg tables for DuckDB access

**Priority:** Medium
**Blocked by:** `use_table_schema` investigation (partially)

Goal: enable `DuckDB iceberg_scan()` on the lakehouse data via GCS.

**Options:**
1. **Fix `use_table_schema`** → per-event-type tables → `ALTER TABLE ... SET OPTIONS (table_format='ICEBERG')` on each
2. **Materialized views or scheduled queries** → create real tables from the history table, partitioned by event_type, then Iceberg-ify those
3. **BigQuery export to Parquet on GCS** → scheduled `EXPORT DATA` to `gs://...-lakehouse/exports/` → DuckDB reads Parquet directly (no Iceberg needed)
4. **BigQuery OMNI / BigLake external tables** → read GCS Parquet from DuckDB without Iceberg

**Decision:** Deferred until `use_table_schema` investigation is complete or a
clear alternative is chosen.

## Cleanup: orphaned GCP resources

**Priority:** Low

Old BigQuery tables and Pub/Sub subscriptions that were removed from Terraform
state but still exist in GCP:

**Tables (from original hardcoded schema):**
- `mqtt.shelly_temperature`
- `mqtt.shelly_humidity`
- `mqtt.shelly_battery`
- `mqtt.shelly_switch`

**Tables (from `for_each` with `use_table_schema` — empty, can delete):**
- `mqtt.shellyhtg3_status_temperature_0`
- `mqtt.shellyhtg3_status_humidity_0`
- `mqtt.shellyhtg3_status_devicepower_0`
- `mqtt.shellyplugsg3_status_switch_0`

**Subscriptions (from `for_each` — not writing, can delete):**
- `shellyhtg3-status-temperature-0-bq`
- `shellyhtg3-status-humidity-0-bq`
- `shellyhtg3-status-devicepower-0-bq`
- `shellyplugsg3-status-switch-0-bq`

**Test resources (if not already cleaned up):**
- `mqtt.test_no_meta` table + `test-no-meta-bq` subscription
- `mqtt.test_minimal` table + `test-minimal-bq` subscription
