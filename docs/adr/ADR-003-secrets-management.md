# ADR-010: Two-layer secrets management

**Date:** 2026-03-02
**Status:** Accepted

## Context

The application needs two categories of secrets:

1. **Credentials** — MQTT username and password. Sensitive values that must never appear in Terraform state, Cloud Run revision configuration, or GitHub Actions logs.
2. **Configuration** — MQTT broker hostname, topic filters, and other non-credential settings. Not sensitive enough to warrant Secret Manager overhead, but still unsuitable for source control.

A single approach does not serve both categories well: GitHub secrets alone would expose credential values in Cloud Run revision config (Terraform state); Secret Manager alone adds unnecessary complexity for plain config values.

## Decision

Use a **two-layer approach**:

**Layer 1 — GCP Secret Manager** (for credentials only)
- `mqtt-username` and `mqtt-password` secrets are created once manually via `gcloud secrets create`.
- Cloud Run mounts them as env vars (`MQTT_USERNAME`, `MQTT_PASSWORD`) using `secret_key_ref` in the Terraform resource.
- The worker SA (`mqtt2pubsub-worker-sa`) holds `secretmanager.secretAccessor`; no other principal can read them.
- Secret values never appear in Terraform state or Cloud Run revision metadata.
- The Secret Manager secret **names** are baked in as Terraform variable defaults (`mqtt-username`, `mqtt-password`) — the deploy workflow does not need to know them.

**Layer 2 — GitHub repository secrets** (for configuration)
- Plain config values (`MQTT_HOST`, `MQTT_TOPIC`, etc.) are stored as GitHub repository secrets.
- The deploy workflow passes them as `TF_VAR_*` environment variables to `terraform apply`.
- Terraform sets them as plain env vars on the Cloud Run Service revision.
- **Repository secrets** are used (not Environment secrets) — GitHub Environments add approval gates suited to multi-stage pipelines (dev/staging/prod) which this single-target deployment does not need.

## Consequences

- Credentials are never stored in Terraform state or visible in Cloud Run revision config.
- Rotating a credential requires only updating the Secret Manager secret version; no redeployment needed.
- Config values are visible in Cloud Run revision config (acceptable — not sensitive).
- The distinction between "credential" and "config" must be maintained: new sensitive values go to Secret Manager, new config values go to GitHub secrets.
