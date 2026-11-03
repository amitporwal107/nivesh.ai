#!/usr/bin/env bash
# Install (or --uninstall) the nightly Closing Bell job on the staging app VM. See closing-bell.cron for what it does.
#   sudo bash /opt/nivesh-staging/repo/deploy/nivesh-staging/install-closing-bell.sh [--uninstall]
set -euo pipefail

STAGING_HOME=/opt/nivesh-staging
CB_ROOT="$STAGING_HOME/closing-bell"
DEST="$STAGING_HOME/downloads/closing-bell"
LOG_FILE="$STAGING_HOME/logs/closing-bell.log"
CRON_SRC="$STAGING_HOME/repo/deploy/nivesh-staging/closing-bell.cron"
CRON_DST=/etc/cron.d/nivesh-staging-closing-bell

log() { printf '\033[1;36m[closing-bell]\033[0m %s\n' "$*"; }

[[ $EUID -eq 0 ]] || { echo "must run as root (use sudo)" >&2; exit 1; }

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -f "$CRON_DST"
    systemctl reload cron 2>/dev/null || service cron reload 2>/dev/null || true
    log "removed $CRON_DST (published editions, state and logs are kept)"
    exit 0
fi

[[ -f "$CRON_SRC" ]] || { echo "cron source not found at $CRON_SRC — is the repo checked out?" >&2; exit 1; }
[[ -f "$STAGING_HOME/repo/tools/closing_bell/pipeline.py" ]] || { echo "tools/closing_bell missing — deploy the branch first" >&2; exit 1; }
if ! /usr/bin/docker exec nivesh-staging-app-backend python -m scripts.closing_bell --help >/dev/null 2>&1; then
    echo "the running backend has no scripts.closing_bell: deploy the branch first" >&2
    exit 1
fi

install -d -m 0755 "$CB_ROOT" "$CB_ROOT/state" "$CB_ROOT/logs" "$CB_ROOT/work" "$CB_ROOT/assets" "$DEST"
touch "$LOG_FILE"
/usr/bin/docker exec nivesh-staging-app-backend python -m scripts.closing_bell ensure-bot
install -m 0644 "$CRON_SRC" "$CRON_DST"
systemctl reload cron 2>/dev/null || service cron reload 2>/dev/null || true
log "installed $CRON_DST; first run tonight from 22:00 IST. Log: $LOG_FILE"
log "dry run any date: sudo python3 $STAGING_HOME/repo/tools/closing_bell/pipeline.py --date YYYY-MM-DD --force --dry-run"
