#!/usr/bin/env bash
set -euo pipefail

REPO="/home/moos/DHBWFallstudie2026"
BRANCH="master"

echo "Checking github for updates"

# Git-Befehle als Benutzer moos ausfuehren
git_moos() {
    runuser -u moos -- git -C "$REPO" "$@"
}

# Aktuelle Version merken
OLD_COMMIT=$(git_moos rev-parse HEAD)

# Neueste Version herunterladen
git_moos pull --ff-only origin "$BRANCH"

# Neue Version pruefen
NEW_COMMIT=$(git_moos rev-parse HEAD)

if [ "$OLD_COMMIT" != "$NEW_COMMIT" ]; then
    echo "New version found: $NEW_COMMIT"

    if ! git_moos diff --quiet "$OLD_COMMIT" "$NEW_COMMIT" -- src/requirements.txt; then
        echo "Requirements changed; updating Python packages"
        python3 -m pip install -r "$REPO/src/requirements.txt"
    fi

    echo "Restarting systemd service"
    systemctl restart moos.service
else
    echo "No updates found"
fi

