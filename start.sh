#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runuser -u moos -- rpicam-jpeg --camera 0 --nopreview --timeout 1000 --output "$REPO/camera.jpg"
runuser -u moos -- git -C "$REPO" pull --ff-only origin master
docker compose --project-directory "$REPO" -f "$REPO/compose.yaml" up -d --build --remove-orphans
