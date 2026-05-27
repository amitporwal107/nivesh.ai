#!/usr/bin/env bash
# deploy.sh — pull latest code into the VM and reinstall deps.
#
# Run as the `nidp` user:
#   sudo -u nidp /opt/nidp/repo/backend/nidp/deploy/vm/deploy.sh [--branch=main]
#
# Idempotent. Does NOT touch /opt/nidp/nidp.env (secrets) or
# /etc/cron.d/nidp (cron schedule). Touching cron requires root, so a
# schedule change is an explicit operator action, not part of deploy.

set -euo pipefail

NIDP_HOME=/opt/nidp
BRANCH="main"

for arg in "$@"; do
    case "$arg" in
        --branch=*) BRANCH="${arg#*=}" ;;
        -h|--help)  sed -n '2,12p' "$0"; exit 0 ;;
    esac
done

CYAN="\033[1;36m"; GREEN="\033[1;32m"; RESET="\033[0m"
log() { echo -e "${CYAN}[deploy]${RESET} $*"; }
ok()  { echo -e "${GREEN}[deploy] ✅${RESET} $*"; }

if [[ "$(whoami)" != "nidp" ]]; then
    echo "must run as user 'nidp' (use: sudo -u nidp $0)" >&2
    exit 1
fi

cd "$NIDP_HOME/repo"

OLD_SHA=$(git rev-parse --short HEAD)
log "current HEAD: $OLD_SHA"

log "git fetch + checkout $BRANCH"
git fetch --quiet origin "$BRANCH"
git checkout --quiet "$BRANCH"
git reset --hard --quiet "origin/$BRANCH"

NEW_SHA=$(git rev-parse --short HEAD)

if [[ "$OLD_SHA" == "$NEW_SHA" ]]; then
    ok "already up to date at $NEW_SHA — nothing to do"
    exit 0
fi

log "updated $OLD_SHA → $NEW_SHA"

# Re-install deps only if requirements.txt changed.
if git diff --name-only "$OLD_SHA" "$NEW_SHA" | \
        grep -q 'backend/nidp/deploy/requirements.txt'; then
    log "requirements changed — reinstalling"
    "$NIDP_HOME/venv/bin/pip" install --quiet --upgrade \
        -r "$NIDP_HOME/repo/backend/nidp/deploy/requirements.txt"
else
    log "requirements unchanged — skipping pip"
fi

# Cron file is dropped via /etc/cron.d/nidp (root). If it changed, warn.
if git diff --name-only "$OLD_SHA" "$NEW_SHA" | \
        grep -q 'backend/nidp/deploy/vm/nidp.cron'; then
    echo "⚠  nidp.cron changed in this commit — root must run:" >&2
    echo "   sudo install -m 644 /opt/nidp/repo/backend/nidp/deploy/vm/nidp.cron /etc/cron.d/nidp" >&2
fi

# Refresh Cloud Logging Ops Agent config if it changed. Needs root, so this
# is a no-op unless the operator re-runs deploy.sh with sudo (or wires it as
# a post-deploy root hook). Failure here is non-fatal.
if git diff --name-only "$OLD_SHA" "$NEW_SHA" | \
        grep -q 'backend/nidp/deploy/vm/ops-agent-config.yaml'; then
    echo "⚠  ops-agent-config.yaml changed in this commit — root must run:" >&2
    echo "   sudo bash $NIDP_HOME/repo/backend/nidp/deploy/vm/install-ops-agent.sh" >&2
fi

# Run pending SQL migrations (idempotent — each file self-registers in
# nidp.schema_migrations, so re-running is a no-op for applied files).
log "running pending DB migrations"
"$NIDP_HOME/venv/bin/python" -m nidp.cli migrate && \
    log "migrations complete" || \
    { echo "❌ migrations FAILED — aborting deploy" >&2; exit 1; }

ok "deploy complete: $NEW_SHA"
echo "$(date -Iseconds)  $OLD_SHA → $NEW_SHA" >> "$NIDP_HOME/logs/deploy.log"
