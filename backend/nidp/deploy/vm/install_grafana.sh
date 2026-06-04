#!/usr/bin/env bash
# install_grafana.sh — provision NIDP Grafana: datasources, dashboards, alert rules.
#
# Idempotent: re-running refreshes all JSON files and restarts Grafana once to
# pick up any datasource/alerting changes (dashboards hot-reload in 30s).
#
# Usage (run on nidp-stack-vm):
#   sudo bash /opt/nidp/repo/backend/nidp/deploy/vm/install_grafana.sh

set -euo pipefail

NIDP_HOME=/opt/nidp
SRC="$NIDP_HOME/repo/backend/nidp/deploy/vm/grafana"
DST="$NIDP_HOME/grafana/provisioning"

log() { printf '\033[1;36m[install_grafana]\033[0m %s\n' "$*"; }

# ── 1. Provisioning directories ────────────────────────────────────────────────
mkdir -p \
  "$DST/datasources" \
  "$DST/dashboards/prod" \
  "$DST/dashboards/staging" \
  "$DST/alerting"

# ── 2. Datasources (TimescaleDB + Loki) ────────────────────────────────────────
log "Installing datasources (TimescaleDB + Loki)"
cp "$SRC/datasources.yml" "$DST/datasources/datasources.yml"

# ── 3. Dashboard provider config ───────────────────────────────────────────────
log "Installing dashboard providers (NIDP Prod + NIDP Staging)"
cp "$SRC/dashboards.yml"  "$DST/dashboards/dashboards.yml"

# ── 4. Dashboards — prod + staging (hot-reload; no restart needed) ────────────
DASHBOARDS="job_health infra dq_chain dq_analytics feed_sched environment_overview app_logs"
for dash in $DASHBOARDS; do
    if [[ -f "$SRC/dashboards/prod/$dash.json" ]]; then
        log "  prod/$dash.json"
        cp "$SRC/dashboards/prod/$dash.json" "$DST/dashboards/prod/$dash.json"
    fi
    if [[ -f "$SRC/dashboards/staging/$dash.json" ]]; then
        log "  staging/$dash.json"
        cp "$SRC/dashboards/staging/$dash.json" "$DST/dashboards/staging/$dash.json"
    fi
done

# ── 5. Alerting rules + contact points ────────────────────────────────────────
log "Installing Grafana alerting rules and contact points"
if [[ -d "$SRC/alerting" ]]; then
    cp "$SRC/alerting/"*.yaml "$DST/alerting/" 2>/dev/null || true
fi

# ── 6. Permissions ─────────────────────────────────────────────────────────────
chmod -R a+rX "$DST"

# ── 7. Restart Grafana (required for datasource + alerting changes) ────────────
# Use `docker compose up -d` (not `docker restart`) so any env-var changes
# (e.g. GCP_LOG_TRIAGE_PRIVATE_KEY) are picked up by recreating the container.
INFRA_COMPOSE="$NIDP_HOME/repo/backend/nidp/deploy/vm/docker-compose.infra.yml"

if [[ -z "${GCP_LOG_TRIAGE_PRIVATE_KEY:-}" ]]; then
    log "⚠ GCP_LOG_TRIAGE_PRIVATE_KEY is not set — Cloud Logging datasource will have no credentials."
    log "  Export it before running this script:"
    log "    export GCP_LOG_TRIAGE_PRIVATE_KEY=\"\$(jq -r .private_key /opt/nidp/secrets/log-triage-sa.json)\""
fi

log "Recreating nidp-grafana to apply datasource/env/alerting changes..."
sudo -E docker compose -f "$INFRA_COMPOSE" up -d grafana
sleep 8
if curl -sf http://127.0.0.1:3000/api/health >/dev/null 2>&1; then
    log "✓ Grafana is healthy at https://data.niveshcopilot.com/grafana"
    log "  Login: admin / admin (change on first login)"
    log "  Dashboards:"
    log "    NIDP Prod    → 'NIDP Prod — Environment Overview'"
    log "    NIDP Prod    → 'NIDP Prod — Job Health'"
    log "    NIDP Prod    → 'NIDP Prod — Feed Schedule & Status'"
    log "    NIDP Staging → 'NIDP Staging — Environment Overview'"
    log "    Both envs    → 'Centralized Application Logs' (GCP Cloud Logging)"
else
    log "✗ Grafana didn't come back up. Check: sudo docker logs nidp-grafana --tail 50"
    exit 1
fi

log "Done."
