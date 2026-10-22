#!/usr/bin/env bash
# install-chartink.sh — install the Chartink scan refresh (twice-daily) cron on the staging VM.
#
# Run once as root on the VM:
#   sudo bash /opt/nivesh-staging/repo/deploy/nivesh-staging/install-chartink.sh
#
# Idempotent — only reloads cron if the cron file changed.
#
# Prereqs:
#   - nivesh-staging-app-backend container is up and runs a build that
#     contains backend/scripts/refresh_chartink.py
#   - the container can reach https://chartink.com (outbound HTTPS)

set -euo pipefail

STAGING_HOME=/opt/nivesh-staging
LOG_DIR="$STAGING_HOME/logs"
LOG_FILE="$LOG_DIR/chartink.log"
CRON_SRC="$STAGING_HOME/repo/deploy/nivesh-staging/chartink.cron"
CRON_DST=/etc/cron.d/nivesh-staging-chartink

log() { printf '\033[1;36m[chartink]\033[0m %s\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
    echo "must run as root (use sudo)" >&2
    exit 1
fi

[[ -f "$CRON_SRC" ]] || { echo "cron source not found at $CRON_SRC — is the repo checked out?" >&2; exit 1; }
[[ -x /usr/bin/docker ]] || { echo "docker not installed at /usr/bin/docker" >&2; exit 1; }

install -d -m 0755 -o nivesh-staging -g nivesh-staging "$LOG_DIR"
touch "$LOG_FILE"
chown nivesh-staging:nivesh-staging "$LOG_FILE"
chmod 0640 "$LOG_FILE"

cat > /etc/logrotate.d/nivesh-staging-chartink <<'ROTATE'
/opt/nivesh-staging/logs/chartink.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    su nivesh-staging nivesh-staging
    create 0640 nivesh-staging nivesh-staging
}
ROTATE

if ! cmp -s "$CRON_SRC" "$CRON_DST"; then
    log "installing cron: $CRON_SRC → $CRON_DST"
    install -m 0644 -o root -g root "$CRON_SRC" "$CRON_DST"
    systemctl reload cron 2>/dev/null || service cron reload 2>/dev/null || true
else
    log "cron unchanged"
fi

log "✅ installed. To try it now without writing anything:"
log "   /usr/bin/docker exec nivesh-staging-app-backend python -m scripts.refresh_chartink --dry-run"
log "   tail -f $LOG_FILE"
