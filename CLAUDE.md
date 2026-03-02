# CLAUDE.md — datafetcher monorepo

## Overview

This monorepo contains data-fetching apps that collect data from external sources and forward it to Google Cloud Pub/Sub. Each app is an independent subdirectory with its own code, Terraform, and documentation.

| App | Directory | Description |
|---|---|---|
| mqtt2pubsub | `mqtt2pubsub/` | Subscribes to MQTT topics, forwards messages to Pub/Sub |
| evohome-poller | `evohome-poller/` | (in progress) |

## Repository Structure

```
.github/
  workflows/
    deploy-<app>.yml      # build image + terraform apply (push to main)
    release-<app>.yml     # semver tag + GitHub Release + deploy
    implement-<app>.yml   # Claude Code PR creation (claude label or /implement)
<app>/
  main.py / ...           # application source
  Dockerfile
  terraform/              # GCP infra for this app only
  docs/adr/               # app-specific Architecture Decision Records
  scripts/                # operational scripts (one-time setup, credential rotation)
  local/                  # local development utilities
  CLAUDE.md               # app-specific conventions and local dev guide
docs/
  adr/                    # cross-cutting Architecture Decision Records (see below)
```

## CI/CD Conventions

Each app has three workflows, all named `<action>-<app>.yml`:

| Workflow | Trigger | What it does |
|---|---|---|
| `deploy-<app>.yml` | push to `main` touching `<app>/**` | builds container image, runs `terraform apply` |
| `release-<app>.yml` | `workflow_dispatch` or `/release` comment | bumps semver tag, creates GitHub Release, triggers deploy |
| `implement-<app>.yml` | `claude` label on issue or `/implement` comment | Claude Code creates a branch + draft PR |

All workflows use **Workload Identity Federation** — no static GCP credentials stored anywhere (see ADR-001).

Terraform variables are passed as `TF_VAR_*` environment variables in the deploy workflow — never interpolated into shell strings (command injection risk).

## GitHub Secrets

All secrets are **repository secrets** (Settings → Secrets and variables → Actions). No GitHub Environments are used — a single deployment target per app does not need multi-stage approval gates.

| Secret | Set by | Used by |
|---|---|---|
| `GCP_PROJECT_ID` | platform `terraform apply` | all deploy workflows |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | platform `terraform apply` | all deploy workflows |
| `GCP_DEPLOYER_SERVICE_ACCOUNT` | platform `terraform apply` | all deploy workflows |
| `ANTHROPIC_API_KEY` | manually | all implement workflows |
| app-specific config | manually | per-app deploy workflow |

**Sensitive credentials** (passwords, API keys used at runtime) are stored in **GCP Secret Manager**, not as GitHub secrets. The Cloud Run service fetches them at runtime using the worker service account. See ADR-003.

## GCP Architecture

Each app gets its own pair of service accounts, provisioned by the platform repo (`insidin/data-platform-gcp`):

| SA | Purpose |
|---|---|
| `<app>-deployer-sa` | Used by GitHub Actions to deploy (build, terraform apply) |
| `<app>-worker-sa` | Attached to the Cloud Run Service at runtime |

The platform team manages these. App teams propose changes via PRs to `data-platform-gcp`.

## Adding a New App

1. Copy an existing app directory as a starting point.
2. Add three workflows to `.github/workflows/` following the naming convention.
3. Request platform provisioning: open a PR on `insidin/data-platform-gcp` adding a `<app>.tf` file.
4. After platform `terraform apply`, set app-specific GitHub secrets manually.

## Cross-Cutting Architecture Decision Records

Decisions that apply to all apps in this monorepo:

| ID | Title | Status |
|---|---|---|
| [ADR-001](docs/adr/ADR-001-workload-identity-federation.md) | Workload Identity Federation for CI/CD authentication | Accepted |
| [ADR-002](docs/adr/ADR-002-terraform-iac.md) | Terraform for infrastructure management | Accepted |
| [ADR-003](docs/adr/ADR-003-secrets-management.md) | Two-layer secrets: GCP Secret Manager + GitHub repository secrets | Accepted |

App-specific ADRs live in `<app>/docs/adr/`.
