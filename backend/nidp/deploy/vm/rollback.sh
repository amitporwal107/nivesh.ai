#!/usr/bin/env bash
# rollback.sh — pin the VM to a specific git SHA.
#
# Usage (as nidp user):
#   sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/rollback.sh <sha>
#
# Logs the rollback to /opt/nidp/logs/deploy.log alongside deploys so
# you have one timeline of "what was running when".

set -euo pipefail

NIDP_HOME=/opt/nidp
TARGET="${1:-}"

if [[ -z "$TARGET" ]]; then
    echo "usage: $0 <git-sha-or-tag>" >&2
    echo
    echo "recent deploys:" >&2
    tail -10 "$NIDP_HOME/logs/deploy.log" 2>/dev/null || echo "  (no deploy log yet)" >&2
    exit 2
fi

if [[ "$(whoami)" != "nidp" ]]; then
    echo "must run as user 'nidp'" >&2
    exit 1
fi

cd "$NIDP_HOME/repo"
OLD_SHA=$(git rev-parse --short HEAD)

git fetch --quiet --tags origin
git checkout --quiet --detach "$TARGET"
NEW_SHA=$(git rev-parse --short HEAD)

# Reinstall deps (rollback may downgrade them).
"$NIDP_HOME/venv/bin/pip" install --quiet --upgrade \
    -r "$NIDP_HOME/repo/backend/nidp/deploy/requirements.txt"

echo "$(date -Iseconds)  ROLLBACK $OLD_SHA → $NEW_SHA  (target=$TARGET)" \
    >> "$NIDP_HOME/logs/deploy.log"
echo "✅ rolled back to $NEW_SHA"
