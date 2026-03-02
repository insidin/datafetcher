#!/usr/bin/env bash
# set-evohome-credentials.sh — create or update Evohome credentials in GCP Secret Manager.
#
# Usage:
#   bash scripts/set-evohome-credentials.sh <username> <password>
#
# The GCP project is read from the GCP_PROJECT_ID environment variable or
# can be overridden with -p / --project.
#
# Examples:
#   GCP_PROJECT_ID=my-project bash scripts/set-evohome-credentials.sh user@example.com mypass
#   bash scripts/set-evohome-credentials.sh -p my-project user@example.com mypass

set -euo pipefail

usage() {
  echo "Usage: $0 [-p <project-id>] <username> <password>" >&2
  exit 1
}

PROJECT_ID="${GCP_PROJECT_ID:-}"

# Parse optional -p / --project flag
while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--project) PROJECT_ID="$2"; shift 2 ;;
    -h|--help)    usage ;;
    *)            break ;;
  esac
done

[[ $# -eq 2 ]] || usage
USERNAME="$1"
PASSWORD="$2"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Error: GCP project ID not set. Pass -p <project-id> or set GCP_PROJECT_ID." >&2
  exit 1
fi

upsert_secret() {
  local name="$1"
  local value="$2"

  if gcloud secrets describe "${name}" --project="${PROJECT_ID}" &>/dev/null; then
    echo "  Updating existing secret '${name}'..."
    printf '%s' "${value}" | gcloud secrets versions add "${name}" \
      --data-file=- --project="${PROJECT_ID}"
  else
    echo "  Creating secret '${name}'..."
    printf '%s' "${value}" | gcloud secrets create "${name}" \
      --data-file=- --project="${PROJECT_ID}" \
      --replication-policy=automatic
  fi
}

echo "Setting Evohome credentials in project '${PROJECT_ID}'..."
upsert_secret "evohome-username" "${USERNAME}"
upsert_secret "evohome-password" "${PASSWORD}"
echo "Done."
