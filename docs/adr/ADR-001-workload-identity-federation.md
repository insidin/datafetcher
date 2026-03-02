# ADR-007: Workload Identity Federation for CI/CD Authentication

**Date:** 2024-01-01
**Status:** Accepted

## Context

CI/CD pipelines (GitHub Actions) need GCP credentials to:
1. Build and push container images to Google Container Registry.
2. Run `terraform apply` to update infrastructure.

The traditional approach — creating a service account key, downloading the JSON file, and storing it as a GitHub Secret — has significant security risks: long-lived credentials that are hard to rotate, broad blast radius if leaked, and no audit trail per workflow run.

## Decision

Use **Workload Identity Federation** (WIF) so GitHub Actions authenticates to GCP using short-lived OIDC tokens, eliminating static service account key files.

- A GCP Workload Identity Pool and Provider are configured to trust GitHub's OIDC issuer.
- GitHub Actions uses `google-github-actions/auth` to exchange the OIDC token for a short-lived GCP access token.
- The CI service account is granted only the IAM roles it needs (Container Registry write, Cloud Run Job updater, Terraform state access).
- No GCP credentials are stored in GitHub Secrets — only the Workload Identity Provider resource name and service account email.

## Consequences

- **Positive:** No long-lived credentials to rotate or leak.
- **Positive:** Each workflow run receives a token scoped to that run's OIDC claims (repo, branch, workflow).
- **Positive:** GCP audit logs record the exact GitHub workflow that performed each action.
- **Negative:** Initial setup is more involved than generating a key file.
- **Negative:** WIF requires GCP's `iam.googleapis.com` and `sts.googleapis.com` APIs to be enabled.
- **Rule:** Never store GCP service account key JSON in GitHub Secrets, `.env` files, or the repository. If a key is accidentally committed, treat it as compromised and rotate immediately.
