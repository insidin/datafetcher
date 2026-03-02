# CLAUDE.md — mqtt2pubsub

## Overview

`mqtt2pubsub` subscribes to one or more MQTT topics and forwards messages to Google Cloud Pub/Sub, enriching each with MQTT metadata as Pub/Sub attributes.

Runs as a **Google Cloud Run Service** with `min_instance_count=1` so the MQTT loop runs continuously.

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| MQTT client | paho-mqtt 2.1.0 |
| GCP messaging | google-cloud-pubsub 2.31.1 |
| Infrastructure | Terraform (GCP: Cloud Run Service, Pub/Sub, IAM) |
| Containerisation | Docker (python:3.12-slim) |
| CI/CD | GitHub Actions + Workload Identity Federation (see root ADR-001) |

## Directory Layout

```
mqtt2pubsub/
  main.py           # entire application: Settings, MqttToPubSubForwarder, PublishSink
  requirements.txt
  Dockerfile
  terraform/        # GCP infra: Cloud Run Service, Pub/Sub topic, IAM
  scripts/          # operational scripts (credential setup, rotation)
  local/            # local dev: Mosquitto broker, test publisher, run script
  docs/adr/         # app-specific Architecture Decision Records
```

Workflows live at the **monorepo root** `.github/workflows/`, not here. See root `CLAUDE.md`.

## App-Specific GitHub Secrets

In addition to the shared `GCP_*` secrets (see root `CLAUDE.md`):

| Secret | Purpose |
|---|---|
| `MQTT_HOST` | MQTT broker hostname |
| `MQTT_TOPIC` | MQTT topic filter (e.g. `sensors/#`); or use `DEVICE_IDENTIFIERS` |
| `ANTHROPIC_API_KEY` | Claude Code implement workflow |
| other `TF_VAR_*` overrides | any non-default Terraform variable (see `terraform/variables.tf`) |

**MQTT credentials are NOT GitHub secrets** — they live in GCP Secret Manager:

| Secret Manager secret | Mounted as | Default name (in `variables.tf`) |
|---|---|---|
| `mqtt-username` | `MQTT_USERNAME` env var | `mqtt-username` |
| `mqtt-password` | `MQTT_PASSWORD` env var | `mqtt-password` |

One-time setup:
```bash
bash scripts/set-mqtt-credentials.sh -p <PROJECT_ID> "username" "password"
```

## Local Development

### Fully offline (Mosquitto + stdout sink)
```bash
docker compose -f local/docker-compose.mqtt.yml up -d
# Set FORWARD_MODE=stdout and MQTT_HOST=localhost in .env.local
bash local/run_forwarder_local.sh
python local/publish_test_message.py
```

### Against real GCP services
```bash
cp local/.env.local.example local/.env.local   # fill in values
bash local/run_forwarder_local.sh
```
Requires `gcloud auth application-default login`.

## Key Conventions

### Configuration
- All config is read from **environment variables** at startup via the `Settings` frozen dataclass.
- Never read `os.environ` outside `Settings`.
- Document every new variable in `README.md` and as an ADR if it represents an architectural choice.

### Output abstraction
- `PublishSink` protocol: `publish(topic, payload, attributes)`.
- `PubSubSink` = production; `StdoutSink` = local/debug.
- No GCP-specific logic outside `PubSubSink`.

### Threading
- MQTT clients run in background threads via `paho-mqtt`'s `loop_start()`.
- Shared mutable state protected by `threading.Lock`.
- Main thread polls the stop event and runtime limits.

### Error handling
- Pub/Sub publishes retry with exponential backoff (2^n seconds, capped at 30s).
- Fatal exceptions set `_fatal_exception` flag, re-raised on shutdown.
- Never swallow exceptions silently in message callbacks.

### Naming
- Python: `snake_case`. Env vars: `UPPER_SNAKE_CASE`. Terraform resources: match `variables.tf` names.

## Architecture Decision Records

App-specific decisions only. Cross-cutting decisions (WIF, Terraform, Secrets) are in `../docs/adr/`.

| ID | Title | Status |
|---|---|---|
| [ADR-001](docs/adr/ADR-001-python-runtime.md) | Python as implementation language | Accepted |
| [ADR-002](docs/adr/ADR-002-publishsink-protocol.md) | PublishSink protocol for output abstraction | Accepted |
| [ADR-003](docs/adr/ADR-003-frozen-settings-dataclass.md) | Frozen dataclass for configuration | Accepted |
| [ADR-004](docs/adr/ADR-004-cloud-run-jobs-batch-execution.md) | Cloud Run Jobs for batch-oriented execution | Superseded by ADR-009 |
| [ADR-005](docs/adr/ADR-005-multi-client-parallelism.md) | Multi-client MQTT parallelism | Accepted |
| [ADR-006](docs/adr/ADR-006-event-type-derivation.md) | Priority-based event type derivation | Accepted |
| [ADR-009](docs/adr/ADR-009-cloud-run-service-continuous.md) | Cloud Run Service for continuous MQTT operation | Accepted |

### ADR template
```markdown
# ADR-NNN: Title

**Date:** YYYY-MM-DD
**Status:** Proposed | Accepted | Deprecated | Superseded by ADR-NNN

## Context
## Decision
## Consequences
```
