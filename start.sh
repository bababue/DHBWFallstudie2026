#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
git -C "$REPO" pull --ff-only
python3 "$REPO/deploy/migrate-config.py"
docker compose --project-directory "$REPO" -f "$REPO/compose.yaml" up -d --build --remove-orphans
