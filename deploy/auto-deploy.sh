#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

git fetch origin master:refs/remotes/origin/master
target=$(git rev-parse refs/remotes/origin/master)
deployed=$(cat "${STATE_DIRECTORY:?}/deployed-commit" 2>/dev/null || true)

if [[ "$(git branch --show-current)" != master ]]; then
    echo "Der Checkout muss auf master stehen; Deployment abgebrochen." >&2
    exit 1
fi

if [[ "$target" == "$deployed" && "$(git rev-parse HEAD)" == "$target" ]]; then
    exit 0
fi

# Do not build uncommitted changes or deploy a branch ahead of the remote.
git diff --quiet
git diff --cached --quiet
git merge --ff-only "$target"
if [[ "$(git rev-parse HEAD)" != "$target" ]]; then
    echo "Lokaler Stand entspricht nicht origin/master; Deployment abgebrochen." >&2
    exit 1
fi

docker compose up -d --build --remove-orphans
printf '%s\n' "$target" > "$STATE_DIRECTORY/deployed-commit"
