#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
docker compose --project-directory "$REPO" -f "$REPO/compose.yaml" up -d --build --remove-orphans
