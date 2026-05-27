#!/usr/bin/env bash
# install_grafana.sh — provision the NIDP-TimescaleDB datasource and
# the "NIDP Job Health" dashboard into the running Grafana container.
#
# Idempotent: re-running just refreshes the JSON files; Grafana picks
# them up via its 30-second filesystem watcher.
#
# Usage (run on the VM):
#   sudo bash /opt/nidp/repo/backend/nidp/deploy/vm/install_grafana.sh

set -euo pipefail

NIDP_HOME=/opt/nidp
SRC="$NIDP_HOME/repo/backend/nidp/deploy/vm/grafana"
DST="$NIDP_HOME/grafana/provisioning"

log() { printf '\033[1;36m[install_grafana]\033[0m %s\n' "$*"; }

# ── 1. Ensure provisioning dirs exist ──────────────────────────────
mkdir -p "$DST/datasources" "$DST/dashboards"

# ── 2. Copy datasources + dashboard provider configs ───────────────
log "Installing datasource: NIDP-TimescaleDB"
cp "$SRC/datasources.yml" "$DST/datasources/datasources.yml"

log "Installing dashboard provider: NIDP"
cp "$SRC/dashboards.yml"  "$DST/dashboards/dashboards.yml"

# ── 3. Copy dashboards ─────────────────────────────────────────────
log "Installing dashboard JSON: NIDP Job Health"
cp "$SRC/dashboards/nidp_job_health.json" "$DST/dashboards/nidp_job_health.json"

log "Installing dashboard JSON: NIDP DQ Chain Status"
cp "$SRC/dashboards/dq_chain_status.json" "$DST/dashboards/dq_chain_status.json"

# Ensure the grafana container can read everything
chmod -R a+rX "$DST"

# ── 4. Restart grafana to pick up the new datasource (provisioned ──
#       datasources are loaded at boot only; dashboards hot-reload). ─
if sudo docker ps --format '{{.Names}}' | grep -q '^nidp-grafana$'; then
  log "Restarting nidp-grafana container..."
  sudo docker restart nidp-grafana >/dev/null
  sleep 3
  if curl -sf http://127.0.0.1:3000/api/health >/dev/null 2>&1; then
    log "✓ Grafana is healthy at https://data.niveshcopilot.com/grafana"
    log "  Login: admin / admin (change on first login)"
    log "  Dashboard: → NIDP folder → 'NIDP Job Health'"
  else
    log "✗ Grafana didn't come back up — check: sudo docker logs nidp-grafana --tail 50"
  fi
else
  log "⚠ nidp-grafana container not running — start docker-compose first"
fi
