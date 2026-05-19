#!/usr/bin/env bash
# install-positional-engine.sh — install the twice-daily positional engine
# cron on nivesh-app-vm.
#
# Run once as root on the VM:
#   sudo bash /opt/nivesh/repo/deploy/nivesh-app/install-positional-engine.sh
#
# Idempotent — only restarts cron if the cron file changed.
#
# Prereqs (already true on the prod VM):
#   - nivesh user exists and is in the `docker` group
#   - nivesh-backend container is up (docker compose -f
#     /opt/nivesh/repo/deploy/nivesh-app/docker-compose.prod.yml up -d)
#   - migrations/015_positional_engine.sql has been applied
#   - At least one Chartink scan saved (admin UI → Scans, or the engine
#     will run but the chartink step will report `no_scans_configured`)

set -euo pipefail

NIVESH_HOME=/opt/nivesh
LOG_DIR="$NIVESH_HOME/logs"
LOG_FILE="$LOG_DIR/positional-engine.log"
CRON_SRC="$NIVESH_HOME/repo/deploy/nivesh-app/positional-engine.cron"
CRON_DST=/etc/cron.d/positional-engine

log() { printf '\033[1;36m[positional-engine]\033[0m %s\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
    echo "must run as root (use sudo)" >&2
    exit 1
fi

[[ -f "$CRON_SRC" ]] || { echo "cron source not found at $CRON_SRC — is the repo checked out?" >&2; exit 1; }
[[ -x /usr/bin/docker ]] || { echo "docker not installed at /usr/bin/docker" >&2; exit 1; }

# ── 1. Log file + directory ──────────────────────────────────────────────────
install -d -m 0755 -o nivesh -g nivesh "$LOG_DIR"
touch "$LOG_FILE"
chown nivesh:nivesh "$LOG_FILE"
chmod 0640 "$LOG_FILE"

# ── 2. Logrotate ─────────────────────────────────────────────────────────────
cat > /etc/logrotate.d/positional-engine <<'EOF'
/opt/nivesh/logs/positional-engine.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    su nivesh nivesh
    create 0640 nivesh nivesh
}
EOF

# ── 3. Cron install (idempotent) ─────────────────────────────────────────────
if ! cmp -s "$CRON_SRC" "$CRON_DST"; then
    log "installing cron: $CRON_SRC → $CRON_DST"
    install -m 0644 -o root -g root "$CRON_SRC" "$CRON_DST"
    systemctl reload cron 2>/dev/null || service cron reload 2>/dev/null || true
else
    log "cron unchanged"
fi

# ── 4. Sanity check — confirm the cron user can reach docker ────────────────
if ! sudo -u nivesh /usr/bin/docker ps >/dev/null 2>&1; then
    log "⚠  user 'nivesh' cannot run 'docker ps' — add to docker group:"
    log "     sudo usermod -aG docker nivesh && newgrp docker"
fi

log "✅ installed. To test now:"
log "   sudo -u nivesh /usr/bin/docker exec nivesh-backend python -m scripts.run_positional_engine --skip-bhavcopy"
log "   tail -f $LOG_FILE"
