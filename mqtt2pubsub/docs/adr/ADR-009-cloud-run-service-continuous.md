# ADR-009: Cloud Run Service for continuous MQTT operation

**Date:** 2026-03-02
**Status:** Accepted (supersedes ADR-004)

## Context

ADR-004 chose Cloud Run Jobs for bounded, batch execution. MQTT is a persistent protocol: the client must maintain a long-lived TCP connection to the broker to receive messages. A Cloud Run Job terminates after its task completes, requiring a scheduled re-run and accepting message loss between runs.

## Decision

Replace the Cloud Run Job with a **Cloud Run Service** configured as a singleton worker:

- `min_instance_count = 1` — keeps one instance alive at all times
- `max_instance_count = 1` — prevents multiple competing MQTT consumers
- `cpu_idle = false` — keeps CPU allocated so the MQTT event loop runs continuously

The service exposes a minimal HTTP health endpoint (`/`) on `$PORT` (stdlib `http.server` in a daemon thread) so Cloud Run can report the instance as healthy without interfering with the MQTT loop.

The platform-owned worker service account (`mqtt2pubsub-worker-sa`) is passed in at deploy time via `TF_VAR_service_account_email`; the app's Terraform does not create a service account.

## Consequences

- Messages are forwarded in real time with no gaps between scheduled runs.
- Cloud Run Service billing is continuous (instance always running); cost is proportional to uptime rather than execution time.
- `MAX_MESSAGES` and `MAX_RUNTIME_SEC` limits remain in the codebase but are set to `0` (unlimited) by default for the Service deployment.
- A crashed instance is automatically restarted by Cloud Run.
