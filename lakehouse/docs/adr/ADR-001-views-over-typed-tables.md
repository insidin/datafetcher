# ADR-001: Views on history table instead of per-event-type BigQuery tables

**Date:** 2026-03-05
**Status:** Accepted (with open investigation)

## Context

The lakehouse originally created one BigQuery table per event_type (e.g.
`shellyhtg3_status_temperature_0`) with a structured schema (`payload JSON`,
`_meta JSON`, plus Pub/Sub metadata columns). Each table had a dedicated
Pub/Sub BigQuery subscription with `use_table_schema = true` and a filter on
`attributes.event_type`.

This approach **did not work**: the per-event-type subscriptions were ACTIVE
(no errors visible in Cloud Logging or Console monitoring) but never wrote a
single row to BigQuery. Extensive debugging confirmed:

- Messages ARE flowing (verified via temporary pull subscription)
- Message format is correct: `{"payload": {...}, "_meta": {...}}`
- Table schema uses correct reserved column names (`message_id`, `publish_time`,
  `attributes`, `subscription_name`) for `write_metadata = true`
- Subscription config is correct (`useTableSchema: true`, `writeMetadata: true`,
  `dropUnknownFields: true`, `state: ACTIVE`)
- No errors in Cloud Logging for the subscription or BigQuery
- Simplified test tables (without `_meta`, without filter, without
  `write_metadata`) also failed — `use_table_schema = true` simply does not
  write data for our messages

Meanwhile, the catch-all history subscription (`use_table_schema = false`,
`write_metadata = true`) works perfectly — all 5 standard fields are populated.

## Decision

Replace per-event-type tables and subscriptions with **views** on the single
history table. Each view filters by `event_type` attribute and extracts
`payload` and `_meta` from the raw `data` bytes using `JSON_QUERY()`.

## Consequences

### Positive
- Dramatically simpler Terraform (no per-event-type tables, subscriptions, or
  schema migration steps)
- Single subscription = single point of ingestion, easier to monitor
- Views are instant to create/modify, no data duplication
- History table already working and collecting data

### Negative
- Views scan the full history table (no partition pruning by event_type);
  acceptable at current data volumes
- `payload` and `_meta` are returned as JSON strings by `JSON_QUERY()`, not
  native JSON columns — minor ergonomic difference for queries
- Iceberg upgrade path is unclear: Iceberg tables need to be real tables, not
  views (see BACKLOG.md)

## Open investigation

**Root cause of `use_table_schema = true` failure is unknown.** This needs to
be investigated separately. Possible areas:

- BigQuery Storage Write API behaviour with `JSON` type columns
- Interaction between `use_table_schema` + `write_metadata` + `JSON` columns
- Region/location constraints (dataset is EU multi-region)
- Pub/Sub service agent permissions beyond `roles/bigquery.dataEditor`
- Undocumented requirements for `use_table_schema` with certain column types

If the root cause is found and fixed, we may revisit this decision and switch
back to per-event-type tables (which would also unblock the Iceberg path).
