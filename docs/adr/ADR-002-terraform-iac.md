# ADR-008: Terraform for Infrastructure Management

**Date:** 2024-01-01
**Status:** Accepted

## Context

The application requires several GCP resources: Cloud Run Job, Pub/Sub topic, service account, IAM bindings, and (optionally) Secret Manager secrets. These can be created manually via `gcloud` or the Cloud Console, but manual provisioning is error-prone, not reproducible across environments, and leaves no audit trail of infrastructure changes.

## Decision

Manage all GCP infrastructure with **Terraform**, using the official `hashicorp/google` provider.

- All resources are defined in `terraform/main.tf`.
- All tuneable parameters are exposed as Terraform variables (`terraform/variables.tf`) with defaults.
- Sensitive values (MQTT credentials) are injected via `-var` flags at `apply` time — never stored in `terraform.tfvars` committed to the repository.
- Terraform state is stored remotely (GCS bucket) for team access and locking.
- The CI/CD pipeline runs `terraform apply -auto-approve` after a successful image build.

## Consequences

- **Positive:** Infrastructure is reproducible, reviewable (PRs on `.tf` files), and version-controlled.
- **Positive:** `terraform plan` previews changes before apply, reducing risk.
- **Positive:** Variables file (`variables.tf`) documents every infrastructure parameter and its default.
- **Negative:** Terraform requires its own state management (GCS bucket must be pre-created).
- **Negative:** Drift can occur if resources are modified outside Terraform — all infra changes must go through `terraform apply`.
- **Rule:** Do not create or modify GCP resources manually. All infrastructure changes must be made via Terraform and reviewed as code. If a resource is created manually for experimentation, import it with `terraform import` or destroy and re-create via Terraform before merging.
