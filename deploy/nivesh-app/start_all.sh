#!/usr/bin/env bash
# start_all.sh — Clean startup of all Docker containers on nivesh-app-vm.
#
# START ORDER (dependency-gated, waits for each health check before proceeding):
#   1. Prod Docker stack    — data stores (postgres, mongo, redis) → backend → frontend
#   2. Staging Docker stack — data stores → backend → frontend + nginx
#
# Health-check gates prevent starting dependent services against a not-yet-ready DB,
# which causes startup failures and broken state in prod.
#
# Usage (from the dev pod / local machine):
#   bash deploy/nivesh-app/start_all.sh
#
# Or run directly on the VM (as root):
#   sudo bash /opt/nivesh/deploy/start_all.sh

set -euo pipefail

VM_NAME="nivesh-app-vm"
VM_ZONE="asia-south1-a"
PROJECT="niveshdataintelligence"
SSH_USER="aporwal107_gmail_com"

REPO_DIR="/opt/nivesh/repo"
DEPLOY_DIR="/opt/nivesh/deploy"

log()  { printf '\n\033[1;36m[nivesh-start]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[nivesh-start]\033[0m ✅ %s\n' "$*"; }
warn() { printf '\033[1;33m[nivesh-start]\033[0m ⚠  %s\n' "$*"; }
fail() { printf '\033[1;31m[nivesh-start]\033[0m ❌ %s\n' "$*" >&2; exit 1; }

# ── If running locally, SSH to VM and re-run this script ─────────────────────
if [[ "$(hostname)" != "$VM_NAME"* ]] && [[ ! -d "$REPO_DIR" ]]; then
  log "Running locally — SSH-forwarding to $VM_NAME..."
  GCLOUD=$(command -v gcloud || echo "/root/google-cloud-sdk/bin/gcloud")
  "$GCLOUD" compute ssh "${SSH_USER}@${VM_NAME}" \
    --zone="$VM_ZONE" --project="$PROJECT" \
    --command="sudo bash $DEPLOY_DIR/start_all.sh"
  exit $?
fi

# ── Escalate to root ──────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || exec sudo "$0" "$@"

# Wait until a Docker container's health check reports "healthy".
# Usage: wait_healthy <container_name> <max_seconds>
wait_healthy() {
  local name="$1" timeout="$2" elapsed=0
  log "  Waiting for $name (up to ${timeout}s)..."
  while [[ $elapsed -lt $timeout ]]; do
    status=$(docker inspect --format='{{.State.Health.Status}}' "$name" 2>/dev/null || echo "missing")
    [[ "$status" == "healthy" ]] && { ok "  $name is healthy."; return 0; }
    sleep 3; (( elapsed += 3 ))
  done
  fail "$name did not become healthy within ${timeout}s (last status: $status)."
}

STAGING_REPO="/opt/nivesh-staging/repo"
STAGING_ENV="/opt/nivesh-staging/.env.staging"
STAGING_COMPOSE="$STAGING_REPO/deploy/nivesh-staging/docker-compose.staging.yml"

PROD_ENV="/opt/nivesh/.env.prod"
PROD_COMPOSE="$DEPLOY_DIR/docker-compose.prod.yml"

# ── Step 1: prod stack ────────────────────────────────────────────────────────
log "Step 1 — starting prod Docker stack..."
[[ -f "$PROD_COMPOSE" ]] || fail "$PROD_COMPOSE not found. Run bootstrap.sh first."

docker compose --env-file "$PROD_ENV" -f "$PROD_COMPOSE" up -d

# Data store health gates — backend will not connect until all three are ready
wait_healthy nivesh-postgres 60
wait_healthy nivesh-mongo     60
wait_healthy nivesh-redis     30

# Backend health gate — nginx/frontend must not start against a broken backend
wait_healthy nivesh-backend 120

ok "Prod Docker stack fully healthy."

# ── Step 2: staging stack ─────────────────────────────────────────────────────
log "Step 2 — starting staging Docker stack..."
if [[ ! -f "$STAGING_COMPOSE" ]]; then
  warn "$STAGING_COMPOSE not found — skipping staging stack."
else
  docker compose --env-file "$STAGING_ENV" -f "$STAGING_COMPOSE" up -d

  wait_healthy nivesh-staging-postgres 60
  wait_healthy nivesh-staging-mongo    60
  wait_healthy nivesh-staging-redis    30
  wait_healthy nivesh-staging-app-backend 120

  ok "Staging Docker stack fully healthy."
fi

echo ""
ok "All Nivesh services started cleanly on $(hostname)."
echo ""
echo "Running Docker containers:"
docker ps --filter "name=nivesh" \
  --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "(none)"
