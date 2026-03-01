#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f ".env.local" ]]; then
  echo "Missing .env.local. Start from .env.local.example."
  exit 1
fi

set -a
source .env.local
set +a

exec python3 main.py
