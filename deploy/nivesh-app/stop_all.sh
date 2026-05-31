#!/usr/bin/env bash
# stop_all.sh — Graceful shutdown of all Docker containers on nivesh-app-vm.
#
# STOP ORDER (dependency-safe, drains app layers before data stores):
#   1. Staging Docker stack  (all nivesh-staging-* containers — isolated, stop first)
#   2. Prod Docker stack     (nivesh-frontend → nivesh-backend → data stores)
#
# Graceful shutdown details:
#   • docker compose stop --timeout 30 sends SIGTERM and gives containers 30s to
#     finish in-flight requests / flush writes before SIGKILL.
#   • docker compose down --remove-orphans removes stopped containers cleanly.
#   • Postgres (both prod and staging) checkpoints on SIGTERM — no data loss.
#
# Usage (from the dev pod / local machine):
#   bash deploy/nivesh-app/stop_all.sh
#
# Or run directly on the VM (as root):
#   sudo bash /opt/nivesh/deploy/stop_all.sh

set -euo pipefail

VM_NAME="nivesh-app-vm"
VM_ZONE="asia-south1-a"
PROJECT="niveshdataintelligence"
SSH_USER="aporwal107_gmail_com"

REPO_DIR="/opt/nivesh/repo"
DEPLOY_DIR="/opt/nivesh/deploy"

GRACEFUL_TIMEOUT=30   # seconds before SIGKILL

log()  { printf '\n\033[1;36m[nivesh-stop]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[nivesh-stop]\033[0m ✅ %s\n' "$*"; }
warn() { printf '\033[1;33m[nivesh-stop]\033[0m ⚠  %s\n' "$*"; }

# ── If running locally, SSH to VM and re-run this script ─────────────────────
if [[ "$(hostname)" != "$VM_NAME"* ]] && [[ ! -d "$REPO_DIR" ]]; then
  log "Running locally — SSH-forwarding to $VM_NAME..."
  GCLOUD=$(command -v gcloud || echo "/root/google-cloud-sdk/bin/gcloud")
  "$GCLOUD" compute ssh "${SSH_USER}@${VM_NAME}" \
    --zone="$VM_ZONE" --project="$PROJECT" \
    --command="sudo bash $DEPLOY_DIR/stop_all.sh"
  exit $?
fi

# ── Escalate to root ──────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || exec sudo "$0" "$@"

STAGING_REPO="/opt/nivesh-staging/repo"
STAGING_ENV="/opt/nivesh-staging/.env.staging"
STAGING_COMPOSE="$STAGING_REPO/deploy/nivesh-staging/docker-compose.staging.yml"

PROD_ENV="/opt/nivesh/.env.prod"
PROD_COMPOSE="$DEPLOY_DIR/docker-compose.prod.yml"

# Step 1 — gracefully stop staging stack first (isolated; stops nginx → backend → stores)
log "Step 1 — gracefully stopping staging Docker stack (timeout=${GRACEFUL_TIMEOUT}s)..."
if [[ -f "$STAGING_COMPOSE" ]]; then
  docker compose --env-file "$STAGING_ENV" -f "$STAGING_COMPOSE" \
    stop --timeout "$GRACEFUL_TIMEOUT"
  docker compose --env-file "$STAGING_ENV" -f "$STAGING_COMPOSE" down --remove-orphans
  ok "Staging Docker stack stopped."
else
  warn "$STAGING_COMPOSE not found — skipping staging stack."
fi

# Step 2 — gracefully stop prod stack (nginx/frontend drains before backend; backend before DBs)
log "Step 2 — gracefully stopping prod Docker stack (timeout=${GRACEFUL_TIMEOUT}s)..."
if [[ -f "$PROD_COMPOSE" ]]; then
  docker compose --env-file "$PROD_ENV" -f "$PROD_COMPOSE" \
    stop --timeout "$GRACEFUL_TIMEOUT"
  docker compose --env-file "$PROD_ENV" -f "$PROD_COMPOSE" down --remove-orphans
  ok "Prod Docker stack stopped."
else
  warn "$PROD_COMPOSE not found — skipping prod stack."
fi

echo ""
ok "All Nivesh services stopped cleanly on $(hostname)."
echo ""
echo "Remaining Nivesh containers (should be none):"
docker ps --filter "name=nivesh" --format "table {{.Names}}\t{{.Status}}" 2>/dev/null || echo "(none)"
