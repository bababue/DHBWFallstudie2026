#!/usr/bin/env bash
set -euo pipefail

REPO="/home/moos/DHBWFallstudie2026"
BRANCH="master"
PYTHON="$REPO/.venv/bin/python"
REQUIREMENTS_STAMP="$REPO/.venv/.requirements.sha256"

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
PACKAGES_UPDATED=0

# Pakete in derselben virtuellen Umgebung installieren, die der Dienst nutzt.
# Der Hash merkt erfolgreiche Installationen auch ueber fehlgeschlagene Deployments hinweg.
REQUIREMENTS_HASH=$(sha256sum "$REPO/src/requirements.txt" | cut -d ' ' -f 1)
if [ ! -f "$REQUIREMENTS_STAMP" ] || [ "$(cat "$REQUIREMENTS_STAMP")" != "$REQUIREMENTS_HASH" ]; then
    echo "Requirements changed; updating Python packages in .venv"
    "$PYTHON" -m pip install -r "$REPO/src/requirements.txt"
    printf '%s\n' "$REQUIREMENTS_HASH" > "$REQUIREMENTS_STAMP"
    PACKAGES_UPDATED=1
fi

if [ "$OLD_COMMIT" != "$NEW_COMMIT" ] || [ "$PACKAGES_UPDATED" -eq 1 ]; then
    echo "Deployment update: $NEW_COMMIT"
    echo "Restarting systemd service"
    systemctl restart moos.service
else
    echo "No updates found"
fi

