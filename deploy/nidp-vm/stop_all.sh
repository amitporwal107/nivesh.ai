#!/usr/bin/env bash
# stop_all.sh — Graceful shutdown of all services on nidp-stack-vm.
#
# STOP ORDER (dependency-safe):
#   1. nidp-daas-api, nidp-query-api  (systemd — drain API consumers before DB)
#   2. Staging Docker stack            (nidp-daas-api-staging, nidp-postgres-staging)
#   3. Prod Docker stack               (nidp-postgres / TimescaleDB — last out)
#
# Graceful shutdown details:
#   • systemctl stop waits for the unit to reach the "stopped" state (SIGTERM + drain)
#   • docker compose stop --timeout 30 sends SIGTERM and gives containers 30s to exit
#     cleanly before SIGKILL. TimescaleDB uses this window to run a checkpoint.
#   • docker compose down removes the (already stopped) containers cleanly.
#
# Usage (from the dev pod / local machine):
#   bash deploy/nidp-vm/stop_all.sh
#
# Or run directly on the VM (as root):
#   sudo bash /opt/nidp/repo/backend/nidp/deploy/vm/stop_all.sh

set -euo pipefail

VM_IP="34.93.60.254"
VM_NAME="nidp-stack-vm"
SSH_USER="aporwal107_gmail_com"
SSH_KEY="/root/.ssh/nidp_gcp"

GRACEFUL_TIMEOUT=30   # seconds before SIGKILL

log()  { printf '\033[1;36m[nidp-stop]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[nidp-stop]\033[0m ✅ %s\n' "$*"; }
warn() { printf '\033[1;33m[nidp-stop]\033[0m ⚠  %s\n' "$*"; }

# ── If running locally, SSH to VM and execute the remote block ─────────────────
if [[ ! -d "/opt/nidp/repo" ]]; then
  log "Not on VM — SSHing to $VM_NAME ($VM_IP)..."
  SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=30"
  ssh $SSH_OPTS "$SSH_USER@$VM_IP" 'sudo bash -s' <<'REMOTE'
set -euo pipefail
GRACEFUL_TIMEOUT=30
log()  { printf '\033[1;36m[nidp-stop]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[nidp-stop]\033[0m ✅ %s\n' "$*"; }
warn() { printf '\033[1;33m[nidp-stop]\033[0m ⚠  %s\n' "$*"; }

NIDP_HOME=/opt/nidp
REPO_DIR="$NIDP_HOME/repo"
PROD_COMPOSE="$REPO_DIR/backend/nidp/deploy/vm/docker-compose.prod.yml"
STAGING_COMPOSE="$REPO_DIR/backend/nidp/deploy/vm/docker-compose.staging.yml"
ENV_FILE="$NIDP_HOME/nidp.env"

# Step 1 — gracefully stop systemd services (SIGTERM, waits for clean exit)
log "Step 1 — stopping systemd services (graceful, waits for clean exit)..."
for svc in nidp-daas-api nidp-query-api; do
  if systemctl is-active --quiet "$svc" 2>/dev/null; then
    systemctl stop "$svc"
    ok "$svc stopped."
  else
    warn "$svc was not running — skipping."
  fi
done

# Step 2 — gracefully stop staging Docker stack
log "Step 2 — gracefully stopping staging Docker stack (timeout=${GRACEFUL_TIMEOUT}s)..."
if [[ -f "$STAGING_COMPOSE" ]]; then
  # stop sends SIGTERM + waits; down removes containers
  docker compose --env-file "$ENV_FILE" -f "$STAGING_COMPOSE" \
    stop --timeout "$GRACEFUL_TIMEOUT"
  docker compose --env-file "$ENV_FILE" -f "$STAGING_COMPOSE" down --remove-orphans
  ok "Staging Docker stack stopped."
else
  warn "$STAGING_COMPOSE not found — skipping staging stack."
fi

# Step 3 — gracefully stop prod Docker stack (TimescaleDB checkpoints on SIGTERM)
log "Step 3 — gracefully stopping prod Docker stack (timeout=${GRACEFUL_TIMEOUT}s)..."
if [[ -f "$PROD_COMPOSE" ]]; then
  docker compose --env-file "$ENV_FILE" -f "$PROD_COMPOSE" \
    stop --timeout "$GRACEFUL_TIMEOUT"
  docker compose --env-file "$ENV_FILE" -f "$PROD_COMPOSE" down --remove-orphans
  ok "Prod Docker stack (nidp-postgres) stopped."
else
  warn "$PROD_COMPOSE not found — skipping prod stack."
fi

echo ""
ok "All NIDP services stopped cleanly on $(hostname)."
echo ""
echo "Remaining NIDP containers (should be none):"
docker ps --filter "name=nidp" --format "table {{.Names}}\t{{.Status}}" 2>/dev/null || echo "(none)"
REMOTE
  exit $?
fi

# ── Running on VM — stop everything ───────────────────────────────────────────
[[ $EUID -eq 0 ]] || exec sudo "$0" "$@"

NIDP_HOME=/opt/nidp
REPO_DIR="$NIDP_HOME/repo"
PROD_COMPOSE="$REPO_DIR/backend/nidp/deploy/vm/docker-compose.prod.yml"
STAGING_COMPOSE="$REPO_DIR/backend/nidp/deploy/vm/docker-compose.staging.yml"
ENV_FILE="$NIDP_HOME/nidp.env"

log "Step 1 — stopping systemd services (graceful, waits for clean exit)..."
for svc in nidp-daas-api nidp-query-api; do
  if systemctl is-active --quiet "$svc" 2>/dev/null; then
    systemctl stop "$svc"
    ok "$svc stopped."
  else
    warn "$svc was not running — skipping."
  fi
done

log "Step 2 — gracefully stopping staging Docker stack (timeout=${GRACEFUL_TIMEOUT}s)..."
if [[ -f "$STAGING_COMPOSE" ]]; then
  docker compose --env-file "$ENV_FILE" -f "$STAGING_COMPOSE" \
    stop --timeout "$GRACEFUL_TIMEOUT"
  docker compose --env-file "$ENV_FILE" -f "$STAGING_COMPOSE" down --remove-orphans
  ok "Staging Docker stack stopped."
else
  warn "$STAGING_COMPOSE not found — skipping staging stack."
fi

log "Step 3 — gracefully stopping prod Docker stack (timeout=${GRACEFUL_TIMEOUT}s)..."
if [[ -f "$PROD_COMPOSE" ]]; then
  docker compose --env-file "$ENV_FILE" -f "$PROD_COMPOSE" \
    stop --timeout "$GRACEFUL_TIMEOUT"
  docker compose --env-file "$ENV_FILE" -f "$PROD_COMPOSE" down --remove-orphans
  ok "Prod Docker stack (nidp-postgres) stopped."
else
  warn "$PROD_COMPOSE not found — skipping prod stack."
fi

echo ""
ok "All NIDP services stopped cleanly on $(hostname)."
echo ""
echo "Remaining NIDP containers (should be none):"
docker ps --filter "name=nidp" --format "table {{.Names}}\t{{.Status}}" 2>/dev/null || echo "(none)"
