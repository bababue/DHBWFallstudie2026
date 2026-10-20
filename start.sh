#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runuser -u moos -- git -C "$REPO" pull --ff-only origin master
docker compose --project-directory "$REPO" -f "$REPO/compose.yaml" up -d --build
