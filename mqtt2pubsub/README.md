# mqtt2pubsub

MQTT consumer that forwards each received MQTT message to Google Pub/Sub.

## Terminology and mapping

- MQTT side: this app subscribes to one **topic filter** (`MQTT_TOPIC`), which can include wildcards.
- Pub/Sub side: this app publishes into one **Pub/Sub topic** (`PUBSUB_TOPIC`).
- Pub/Sub consumers read from a **Pub/Sub subscription** attached to that topic.

Important mapping behavior:
- It does **not** create one Pub/Sub topic per MQTT topic.
- It forwards all matched MQTT messages into the configured Pub/Sub topic and includes the original MQTT topic in message attributes (`mqtt_topic`).
- It also adds `event_type` and `event_type_source` attributes for downstream routing.
- You can subscribe using one filter (`MQTT_TOPIC`) or a list of device identifiers (`DEVICE_IDENTIFIERS`) expanded with `MQTT_TOPIC_TEMPLATE` (default `{identifier}/#`).

## Repository layout

- `main.py`: app entrypoint.
- `terraform/`: infrastructure deployment for Pub/Sub topic + service account + Cloud Run Job.
- `local/`: local MQTT broker and local test publisher.
- `ci/github-actions-deploy.yml`: GitHub Actions deployment template.

## Runtime modes

- `FORWARD_MODE=pubsub` (default): forwards to Google Pub/Sub. Use this in Cloud Run Job and when running locally against cloud systems.
- `FORWARD_MODE=stdout`: optional debug/test mode, no GCP publish. Messages are logged and can be written to `LOCAL_OUTPUT_PATH`.

## Environment variables

Required in all modes:
- `MQTT_HOST`
- One of:
  - `MQTT_TOPIC` (single filter mode), or
  - `DEVICE_IDENTIFIERS` (identifier mode)

If both are set, `DEVICE_IDENTIFIERS` mode is used.

Required in `pubsub` mode:
- `PUBSUB_TOPIC`
- `GCP_PROJECT_ID` (or `GOOGLE_CLOUD_PROJECT`) when `PUBSUB_TOPIC` is not full `projects/.../topics/...`

Common optional:
- `MQTT_PORT` (default `8883`)
- `MQTT_TOPIC_TEMPLATE` (default `{identifier}/#`, used with `DEVICE_IDENTIFIERS`)
- `MQTT_CONSUMER_CLIENTS` (default `1`, splits filter list across this many MQTT clients)
- `MQTT_QOS` (default `1`)
- `MQTT_USERNAME`, `MQTT_PASSWORD`
- `MQTT_TLS_ENABLED` (default `true`)
- `MQTT_TLS_CA_CERT`
- `MQTT_TLS_INSECURE` (default `false`)
- `PUBSUB_PUBLISH_TIMEOUT_SEC` (default `30`)
- `PUBSUB_PUBLISH_RETRIES` (default `5`)
- `EVENT_TYPE_TOPIC_MAP` (for example `devices/+/telemetry=telemetry;devices/+/state=state`)
- `EVENT_TYPE_JSON_FIELDS` (default `event_type,type,kind`)
- `EVENT_TYPE_FALLBACK` (default `unknown`)
- `MAX_MESSAGES` (default `0`, unlimited)
- `MAX_RUNTIME_SEC` (default `0`, unlimited)
- `LOCAL_OUTPUT_PATH` (local stdout mode only)

## Event type derivation (exact order)

`event_type` is derived per message in this order:

1. First matching rule in `EVENT_TYPE_TOPIC_MAP` (`<mqtt_filter>=<event_type>`; first match wins).
2. If no topic-map hit and `DEVICE_IDENTIFIERS` is used: from MQTT topic segment right after identifier.
3. If still not found: first available payload JSON field in `EVENT_TYPE_JSON_FIELDS`.
4. If not found: `EVENT_TYPE_FALLBACK`.

Examples:
- Topic map: `devices/+/telemetry=telemetry;devices/+/state=state`
- JSON fields: `event_type,type,kind`
- Identifier translation example:
  - identifier mode has `DEVICE_IDENTIFIERS=device-a` and default template `{identifier}/#`
  - message topic `device-a/telemetry/temp`
  - derived `event_type=telemetry`
  - `event_type_source=topic_after_identifier:device-a`

## Local run against cloud MQTT + cloud Pub/Sub

1. Install dependencies:

```bash
cd /Users/juyttenh/codexapp/datafetcher/mqtt2pubsub
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Authenticate your local machine to GCP (ADC):

```bash
gcloud auth application-default login
```

3. Prepare local env (cloud endpoints):

```bash
cp .env.local.example .env.local
```

Then edit `.env.local` with your real `MQTT_HOST`, and either:
- `MQTT_TOPIC` (single filter), or
- `DEVICE_IDENTIFIERS` (identifier mode),
plus `PUBSUB_TOPIC`.

4. Run the worker locally:

```bash
./local/run_forwarder_local.sh
```

This runs the same Python entrypoint as Cloud Run Job, but on your machine.

## Optional local MQTT broker for automated tests (future use)

If you later want hermetic tests without cloud MQTT:

```bash
docker compose -f local/docker-compose.mqtt.yml up -d
python local/publish_test_message.py --topic "devices/test/telemetry" --message '{"temperature":21.8}'
docker compose -f local/docker-compose.mqtt.yml down
```

## Cloud build (container image)

```bash
cd /Users/juyttenh/codexapp/datafetcher/mqtt2pubsub
gcloud builds submit --config cloudbuild.yaml .
```

## Deploy with Terraform

1. Prepare vars:

```bash
cd /Users/juyttenh/codexapp/datafetcher/mqtt2pubsub/terraform
cp terraform.tfvars.example terraform.tfvars
```

2. Edit `terraform.tfvars` values (`project_id`, `container_image`, `mqtt_host`, and either `mqtt_topic` or `device_identifiers`, etc.).

3. Apply:

```bash
gcloud services enable run.googleapis.com pubsub.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com
terraform init
terraform apply
```

4. Execute the Cloud Run Job:

```bash
gcloud run jobs execute mqtt2pubsub-job --region us-central1 --wait
```

## GitHub deployment flow (recommended)

Use Workload Identity Federation with GitHub Actions (no static service account key):

1. Copy `ci/github-actions-deploy.yml` to `.github/workflows/deploy-mqtt2pubsub.yml` in your repo.
Adjust `APP_DIR` and `TF_DIR` inside the workflow if your folder path is different.
2. Configure GitHub repository secrets:
- `GCP_PROJECT_ID`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_DEPLOYER_SERVICE_ACCOUNT`
- `MQTT_HOST`
- `MQTT_TOPIC`
- `DEVICE_IDENTIFIERS` (optional alternative to `MQTT_TOPIC`)
- `MQTT_TOPIC_TEMPLATE` (optional)
- `MQTT_CONSUMER_CLIENTS` (optional)
- `EVENT_TYPE_TOPIC_MAP` (optional)
- `EVENT_TYPE_JSON_FIELDS` (optional)
- `EVENT_TYPE_FALLBACK` (optional)
- `MQTT_USERNAME_SECRET` (optional)
- `MQTT_PASSWORD_SECRET` (optional)
3. Push to `main`. The workflow builds the image and runs Terraform apply.

## Notes

- Cloud Run **Job** is batch-oriented. For continuously running ingestion, consider Cloud Run Service, GKE, or VM.
- Original MQTT metadata is added to Pub/Sub attributes:
  - `mqtt_topic`
  - `mqtt_qos`
  - `mqtt_retain`
  - `mqtt_mid`
  - `received_at_utc`
  - `event_type`
  - `event_type_source`
