# pubsub2firestore — CLAUDE.md

## What this app is

Always-on Cloud Run service. Pulls from a Pub/Sub subscription and writes
messages to Firestore for live dashboard consumption.

No MQTT, no automation logic — pure Pub/Sub → Firestore bridge.

## Firestore data model

```
/state/{topic_key}                        overwrite — current state per MQTT topic
/readings/{event_type}/messages/{id}      append    — time-series, TTL-based cleanup
```

`topic_key` = `mqtt_topic` attribute with `/` and `:` replaced by `_`.
`expires_at` field on readings documents is used with a Firestore TTL policy.

## Local development

```bash
# Install dependencies
pip install -r requirements.txt

# Run against real Firestore (uses application default credentials)
export PUBSUB_SUBSCRIPTION="projects/<project>/subscriptions/pubsub2firestore"
export GCP_PROJECT_ID="<project>"
python main.py

# Run tests (no GCP required)
pytest tests/ -v
```

## Environment variables

| Variable             | Required | Default  | Notes                                      |
|----------------------|----------|----------|--------------------------------------------|
| `PUBSUB_SUBSCRIPTION`| yes      | —        | Full subscription resource path            |
| `GCP_PROJECT_ID`     | yes      | —        | GCP project ID for Firestore client        |
| `TTL_DAYS`           | no       | `30`     | Days before readings documents expire      |
| `LOG_LEVEL`          | no       | `INFO`   | Python logging level                       |
| `PORT`               | no       | `8080`   | Health check HTTP server port              |

## Conventions

- Single-file Python app (`main.py`), Python 3.12.
- Ruff for linting + formatting (`pyproject.toml`).
- Unit tests in `tests/` — no GCP credentials required.
- NACKs on Firestore errors so Pub/Sub retries with backoff.
- Graceful SIGTERM/SIGINT shutdown.
