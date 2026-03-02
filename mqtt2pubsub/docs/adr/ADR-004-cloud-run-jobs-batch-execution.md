# ADR-004: Cloud Run Jobs for Batch-Oriented Execution

**Date:** 2024-01-01
**Status:** Accepted

## Context

The bridge can run either as a long-lived streaming process or as a bounded job that runs for a fixed duration or processes a fixed number of messages. Google Cloud offers several compute options:

| Option | Characteristics |
|---|---|
| Cloud Run Service | Always-on HTTP endpoint; billed per request |
| Cloud Run Job | Task-based; exits on completion; billed per CPU-second used |
| GKE | Full Kubernetes; more operational overhead |
| Compute Engine VM | Persistent; manual lifecycle management |

MQTT connections are typically stateful and long-lived, but scheduling the bridge as a periodic Cloud Run Job (e.g., every 15 minutes for 14 minutes) avoids the cost of a perpetually running container.

## Decision

Deploy as a **Google Cloud Run Job** with configurable execution limits:

- `MAX_RUNTIME_SEC` — the process exits cleanly after this many seconds (default: unlimited).
- `MAX_MESSAGES` — the process exits after forwarding this many messages (default: unlimited).
- The Cloud Run Job task timeout (`task_timeout`) is set conservatively above `MAX_RUNTIME_SEC`.

The Terraform module provisions `google_cloud_run_v2_job` (not a service).

## Consequences

- **Positive:** No idle billing — compute costs only while the job executes.
- **Positive:** Natural retry policy (Cloud Run Job `max_retries`) handles transient failures.
- **Positive:** Clean process model — no long-running daemon to monitor for memory leaks.
- **Negative:** Small gap in message coverage between job invocations (acceptable for the target use case).
- **Negative:** MQTT QoS 1/2 guarantees apply only within a single job run — restarting loses in-flight unacknowledged messages.
- **Follow-up:** If continuous streaming is required, the same application can run on a VM or GKE without code changes — only the deployment target changes.
