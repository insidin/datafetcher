# evohome-poller

Cloud Run Job that polls Evohome location status and publishes snapshots to Pub/Sub.

## What is included

- `poller.py`: single Python script with
  - Evohome OAuth (password + refresh)
  - optional token cache persisted to GCS (`gs://.../token_cache.json`)
  - status polling (`/location/{id}/status`)
  - Pub/Sub publishing
- `Dockerfile` + `requirements.txt`: container build for Cloud Run Job
- `cloudbuild.yaml`: image build/push via Cloud Build
- `terraform/main.tf`: infra for
  - Secret Manager secret containers
  - service account + IAM
  - cache bucket
  - Cloud Run Job
  - Cloud Scheduler trigger

Legacy implementation is archived in `old/` and excluded from Git by `.gitignore`.

## Secrets handling

Terraform creates secret objects only. Secret values are not stored in Terraform code/state by this setup.

After `terraform apply`, add secret versions:

```bash
gcloud secrets versions add evohome-username --data-file=- <<<"your-evohome-username"
gcloud secrets versions add evohome-password --data-file=- <<<"your-evohome-password"
```

## Build image

```bash
gcloud builds submit --config cloudbuild.yaml
```

## Pub/Sub topic

The topic is treated as external infrastructure in this repo.
Set `var.pubsub_topic` in Terraform to an existing topic path:

```text
projects/<project-id>/topics/<topic-name>
```

## Deploy infra

```bash
cd terraform
terraform init
terraform apply
```

## Pub/Sub payload

Message data is JSON:

```json
{
  "timestamp": "2026-02-16T22:00:00+00:00",
  "location_id": "7952144",
  "status": {"...": "Evohome status payload"}
}
```
