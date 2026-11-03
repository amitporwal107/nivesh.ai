#!/usr/bin/env bash
# install-desk-alerts.sh — install the evening Smart trading desk check
# (paper-trade exits + price alerts) cron on the staging VM.
#
# Run once as root on the VM:
#   sudo bash /opt/nivesh-staging/repo/deploy/nivesh-staging/install-desk-alerts.sh
# Roll back (removes the schedule only; job_runs / job_locks history stays):
#   sudo bash /opt/nivesh-staging/repo/deploy/nivesh-staging/install-desk-alerts.sh --uninstall
#
# Idempotent — only reloads cron if the cron file changed.
#
# Prereqs:
#   - nivesh-staging-app-backend container is up and runs a build that
#     contains backend/scripts/check_desk_alerts.py WITH --require-bars and
#     --skip-if-done (checked below: an older build would exit 2 on argparse)
#   - the container can reach the data platform (NIDP_DAAS_BASE_URL + key)
#   - flock (util-linux) on the host

set -euo pipefail

STAGING_HOME=/opt/nivesh-staging
LOG_DIR="$STAGING_HOME/logs"
LOG_FILE="$LOG_DIR/desk-alerts.log"
CRON_SRC="$STAGING_HOME/repo/deploy/nivesh-staging/desk-alerts.cron"
CRON_DST=/etc/cron.d/nivesh-staging-desk-alerts

log() { printf '\033[1;36m[desk-alerts]\033[0m %s\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
    echo "must run as root (use sudo)" >&2
    exit 1
fi

if [[ "${1:-}" == "--uninstall" ]]; then
    if [[ -f "$CRON_DST" ]]; then
        rm -f "$CRON_DST"
        systemctl reload cron 2>/dev/null || service cron reload 2>/dev/null || true
        log "removed $CRON_DST (the log, job_runs and job_locks are kept)"
    else
        log "$CRON_DST not installed; nothing to remove"
    fi
    exit 0
fi

[[ -f "$CRON_SRC" ]] || { echo "cron source not found at $CRON_SRC — is the repo checked out?" >&2; exit 1; }
[[ -x /usr/bin/docker ]] || { echo "docker not installed at /usr/bin/docker" >&2; exit 1; }
[[ -x /usr/bin/flock ]] || { echo "flock not installed at /usr/bin/flock (util-linux)" >&2; exit 1; }
# The running backend must know the flags the cron line passes; --help reads nothing and writes nothing.
if ! /usr/bin/docker exec nivesh-staging-app-backend python -m scripts.check_desk_alerts --help | grep -q -- '--skip-if-done'; then
    echo "the running backend's check_desk_alerts has no --require-bars/--skip-if-done: deploy the branch first" >&2
    exit 1
fi

install -d -m 0755 -o nivesh-staging -g nivesh-staging "$LOG_DIR"
touch "$LOG_FILE"
chown nivesh-staging:nivesh-staging "$LOG_FILE"
chmod 0640 "$LOG_FILE"

cat > /etc/logrotate.d/nivesh-staging-desk-alerts <<'ROTATE'
/opt/nivesh-staging/logs/desk-alerts.log {
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
log "   /usr/bin/docker exec nivesh-staging-app-backend python -m scripts.check_desk_alerts --dry-run --require-bars"
log "   tail -f $LOG_FILE"
log "Last recorded run: GET /api/admin/risk/jobs/check_desk_alerts (admin)"
