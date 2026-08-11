#!/usr/bin/env bash
# Sync only changed files to production from WSL/Linux/macOS.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f deploy/sync_config.env ]]; then
  echo "Copy deploy/sync_config.example.env to deploy/sync_config.env and edit it first." >&2
  exit 1
fi

python3 deploy/sync_release.py "$@"
