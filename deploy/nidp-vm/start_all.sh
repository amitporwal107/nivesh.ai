#!/usr/bin/env bash
# start_all.sh — Clean startup of all services on nidp-stack-vm.
#
# START ORDER (dependency-gated, waits for each health check before proceeding):
#   1. Prod Docker stack    (nidp-postgres / TimescaleDB) — wait healthy
#   2. Staging Docker stack (nidp-postgres-staging, nidp-daas-api-staging) — wait healthy
#   3. nidp-daas-api        (systemd prod DaaS API, port 8083)
#   4. nidp-query-api       (systemd prod Query API)
#
# Usage (from the dev pod / local machine):
#   bash deploy/nidp-vm/start_all.sh
#
# Or run directly on the VM (as root):
#   sudo bash /opt/nidp/repo/backend/nidp/deploy/vm/start_all.sh

set -euo pipefail

VM_IP="34.93.60.254"
VM_NAME="nidp-stack-vm"
SSH_USER="aporwal107_gmail_com"
SSH_KEY="/root/.ssh/nidp_gcp"

log()  { printf '\033[1;36m[nidp-start]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[nidp-start]\033[0m ✅ %s\n' "$*"; }
warn() { printf '\033[1;33m[nidp-start]\033[0m ⚠  %s\n' "$*"; }
fail() { printf '\033[1;31m[nidp-start]\033[0m ❌ %s\n' "$*" >&2; exit 1; }

# ── If running locally, SSH to VM and execute the remote block ─────────────────
if [[ ! -d "/opt/nidp/repo" ]]; then
  log "Not on VM — SSHing to $VM_NAME ($VM_IP)..."
  SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=30"
  ssh $SSH_OPTS "$SSH_USER@$VM_IP" 'sudo bash -s' <<'REMOTE'
set -euo pipefail
log()  { printf '\033[1;36m[nidp-start]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[nidp-start]\033[0m ✅ %s\n' "$*"; }
warn() { printf '\033[1;33m[nidp-start]\033[0m ⚠  %s\n' "$*"; }
fail() { printf '\033[1;31m[nidp-start]\033[0m ❌ %s\n' "$*" >&2; exit 1; }

# Wait until a Docker container's health check reports "healthy".
# Usage: wait_healthy <container_name> <max_seconds>
wait_healthy() {
  local name="$1" timeout="$2" elapsed=0
  log "  Waiting for $name to be healthy (up to ${timeout}s)..."
  while [[ $elapsed -lt $timeout ]]; do
    status=$(docker inspect --format='{{.State.Health.Status}}' "$name" 2>/dev/null || echo "missing")
    [[ "$status" == "healthy" ]] && { ok "  $name is healthy."; return 0; }
    sleep 3; (( elapsed += 3 ))
  done
  fail "$name did not become healthy within ${timeout}s (last status: $status)."
}

NIDP_HOME=/opt/nidp
REPO_DIR="$NIDP_HOME/repo"
PROD_COMPOSE="$REPO_DIR/backend/nidp/deploy/vm/docker-compose.prod.yml"
STAGING_COMPOSE="$REPO_DIR/backend/nidp/deploy/vm/docker-compose.staging.yml"
ENV_FILE="$NIDP_HOME/nidp.env"

# Step 1 — start prod Postgres (TimescaleDB)
log "Step 1 — starting prod Docker stack (TimescaleDB)..."
[[ -f "$PROD_COMPOSE" ]] || fail "$PROD_COMPOSE not found."
docker compose --env-file "$ENV_FILE" -f "$PROD_COMPOSE" up -d
wait_healthy nidp-postgres 60

# Step 2 — start staging stack (depends on staging postgres being ready)
log "Step 2 — starting staging Docker stack..."
if [[ -f "$STAGING_COMPOSE" ]]; then
  docker compose --env-file "$ENV_FILE" -f "$STAGING_COMPOSE" up -d
  wait_healthy nidp-postgres-staging 60
  # DaaS staging waits for its own postgres (compose depends_on handles ordering);
  # verify it comes up too.
  if docker ps --format '{{.Names}}' | grep -q '^nidp-daas-api-staging$'; then
    wait_healthy nidp-daas-api-staging 90
  fi
  ok "Staging Docker stack ready."
else
  warn "$STAGING_COMPOSE not found — skipping staging stack."
fi

# Step 3 — start systemd services (prod DaaS and Query APIs)
log "Step 3 — starting systemd services..."
for svc in nidp-daas-api nidp-query-api; do
  if systemctl list-unit-files --quiet "$svc.service" &>/dev/null; then
    systemctl start "$svc"
    # Give it a moment to settle before checking
    sleep 2
    if systemctl is-active --quiet "$svc"; then
      ok "$svc started and active."
    else
      fail "$svc failed to start. Check: journalctl -u $svc -n 50"
    fi
  else
    warn "$svc.service not installed — skipping."
  fi
done

echo ""
ok "All NIDP services started cleanly on $(hostname)."
echo ""
echo "Running Docker containers:"
docker ps --filter "name=nidp" --format "table {{.Names}}\t{{.Status}}" 2>/dev/null || echo "(none)"
echo ""
echo "Systemd service status:"
for svc in nidp-daas-api nidp-query-api; do
  systemctl is-active --quiet "$svc" 2>/dev/null \
    && echo "  $svc: active" \
    || echo "  $svc: inactive"
done
REMOTE
  exit $?
fi

# ── Running on VM — start everything ──────────────────────────────────────────
[[ $EUID -eq 0 ]] || exec sudo "$0" "$@"

wait_healthy() {
  local name="$1" timeout="$2" elapsed=0
  log "  Waiting for $name to be healthy (up to ${timeout}s)..."
  while [[ $elapsed -lt $timeout ]]; do
    status=$(docker inspect --format='{{.State.Health.Status}}' "$name" 2>/dev/null || echo "missing")
    [[ "$status" == "healthy" ]] && { ok "  $name is healthy."; return 0; }
    sleep 3; (( elapsed += 3 ))
  done
  fail "$name did not become healthy within ${timeout}s (last status: $status)."
}

NIDP_HOME=/opt/nidp
REPO_DIR="$NIDP_HOME/repo"
PROD_COMPOSE="$REPO_DIR/backend/nidp/deploy/vm/docker-compose.prod.yml"
STAGING_COMPOSE="$REPO_DIR/backend/nidp/deploy/vm/docker-compose.staging.yml"
ENV_FILE="$NIDP_HOME/nidp.env"

log "Step 1 — starting prod Docker stack (TimescaleDB)..."
[[ -f "$PROD_COMPOSE" ]] || fail "$PROD_COMPOSE not found."
docker compose --env-file "$ENV_FILE" -f "$PROD_COMPOSE" up -d
wait_healthy nidp-postgres 60

log "Step 2 — starting staging Docker stack..."
if [[ -f "$STAGING_COMPOSE" ]]; then
  docker compose --env-file "$ENV_FILE" -f "$STAGING_COMPOSE" up -d
  wait_healthy nidp-postgres-staging 60
  if docker ps --format '{{.Names}}' | grep -q '^nidp-daas-api-staging$'; then
    wait_healthy nidp-daas-api-staging 90
  fi
  ok "Staging Docker stack ready."
else
  warn "$STAGING_COMPOSE not found — skipping staging stack."
fi

log "Step 3 — starting systemd services..."
for svc in nidp-daas-api nidp-query-api; do
  if systemctl list-unit-files --quiet "$svc.service" &>/dev/null; then
    systemctl start "$svc"
    sleep 2
    if systemctl is-active --quiet "$svc"; then
      ok "$svc started and active."
    else
      fail "$svc failed to start. Check: journalctl -u $svc -n 50"
    fi
  else
    warn "$svc.service not installed — skipping."
  fi
done

echo ""
ok "All NIDP services started cleanly on $(hostname)."
echo ""
echo "Running Docker containers:"
docker ps --filter "name=nidp" --format "table {{.Names}}\t{{.Status}}" 2>/dev/null || echo "(none)"
echo ""
echo "Systemd service status:"
for svc in nidp-daas-api nidp-query-api; do
  systemctl is-active --quiet "$svc" 2>/dev/null \
    && echo "  $svc: active" \
    || echo "  $svc: inactive"
done
