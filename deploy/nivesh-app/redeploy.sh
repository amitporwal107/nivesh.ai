#!/usr/bin/env bash
# redeploy.sh — Fast code-update deploy for nivesh-app-vm.
#
# Pulls the latest code from the current branch, rebuilds only changed
# images, and restarts the affected containers. Does NOT touch data stores.
#
# Run from any machine with gcloud configured:
#   bash deploy/nivesh-app/redeploy.sh
#
# Or from inside the VM as root/sudo:
#   bash /opt/nivesh/deploy/redeploy.sh
#
# Options:
#   --frontend-only   Skip backend rebuild (faster, CSS/JS change only)
#   --backend-only    Skip frontend rebuild
#   --branch <name>   Override branch (default: nivesh-v2-copilot)

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
VM_NAME="nivesh-app-vm"
VM_ZONE="asia-south1-a"
PROJECT="niveshdataintelligence"
SSH_USER="aporwal107_gmail_com"

REPO_DIR="/opt/nivesh/repo"
DEPLOY_DIR="/opt/nivesh/deploy"
ENV_FILE="/opt/nivesh/.env.prod"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.prod.yml"
BRANCH="${BRANCH:-nivesh-v2-copilot}"

BUILD_FRONTEND=true
BUILD_BACKEND=true

for arg in "$@"; do
  case "$arg" in
    --frontend-only) BUILD_BACKEND=false ;;
    --backend-only)  BUILD_FRONTEND=false ;;
    --branch)        shift; BRANCH="$1" ;;
  esac
done

log()  { printf '\033[1;36m[redeploy]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[redeploy]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[redeploy]\033[0m %s\n' "$*"; exit 1; }

# ── Detect execution context ──────────────────────────────────────────────────
# If running locally (not on the VM), SSH into the VM and re-run this script.
if [[ "$(hostname)" != "$VM_NAME"* ]] && [[ ! -d "$REPO_DIR" ]]; then
  log "Running remotely — forwarding to VM via gcloud SSH..."
  GCLOUD=$(command -v gcloud || echo "/root/google-cloud-sdk/bin/gcloud")
  REMOTE_ARGS="BUILD_FRONTEND=$BUILD_FRONTEND BUILD_BACKEND=$BUILD_BACKEND BRANCH=$BRANCH"
  "$GCLOUD" compute ssh "${SSH_USER}@${VM_NAME}" \
    --zone="$VM_ZONE" --project="$PROJECT" \
    --command="sudo $REMOTE_ARGS bash $DEPLOY_DIR/redeploy.sh"
  exit $?
fi

# ── Running on VM ─────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && exec sudo "$0" "$@"

[[ -f "$ENV_FILE" ]] || fail ".env.prod not found — run bootstrap.sh first"

# ── 1. Pull latest code ───────────────────────────────────────────────────────
log "Pulling branch '$BRANCH'..."
git config --global --add safe.directory "$REPO_DIR" 2>/dev/null || true
git -C "$REPO_DIR" fetch --quiet origin "$BRANCH"
git -C "$REPO_DIR" reset --hard "origin/$BRANCH"
ok "Code updated: $(git -C "$REPO_DIR" log -1 --oneline)"

# ── 2. Resolve external IP (needed for frontend build arg) ───────────────────
EXTERNAL_IP=$(curl -sf https://api.ipify.org 2>/dev/null || curl -sf http://ifconfig.me)
[[ -n "$EXTERNAL_IP" ]] || fail "Could not determine external IP"
log "External IP: $EXTERNAL_IP"

# ── 3. Build backend ──────────────────────────────────────────────────────────
if [[ "$BUILD_BACKEND" == "true" ]]; then
  log "Building backend image..."
  docker build \
    -f "$DEPLOY_DIR/Dockerfile.backend.prod" \
    -t nivesh/backend:prod \
    "$REPO_DIR"
  ok "Backend image built."
fi

# ── 4. Build frontend ─────────────────────────────────────────────────────────
if [[ "$BUILD_FRONTEND" == "true" ]]; then
  log "Building frontend image (REACT_APP_BACKEND_URL=http://$EXTERNAL_IP)..."
  docker build \
    -f "$DEPLOY_DIR/Dockerfile.frontend.prod" \
    --build-arg REACT_APP_BACKEND_URL="http://$EXTERNAL_IP" \
    -t nivesh/frontend:prod \
    "$REPO_DIR"
  ok "Frontend image built."
fi

# ── 5. Restart updated containers ─────────────────────────────────────────────
log "Restarting containers..."

if [[ "$BUILD_BACKEND" == "true" ]]; then
  docker rm -f nivesh-backend 2>/dev/null || true
fi
if [[ "$BUILD_FRONTEND" == "true" ]]; then
  docker rm -f nivesh-frontend 2>/dev/null || true
fi

docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d \
  $(${BUILD_BACKEND}  && echo "backend"  || true) \
  $(${BUILD_FRONTEND} && echo "frontend" || true)

# ── 6. Health check ───────────────────────────────────────────────────────────
log "Waiting for backend health..."
for i in $(seq 1 20); do
  if curl -sf "http://localhost:80/api/health" &>/dev/null; then
    ok "Backend healthy."
    break
  fi
  sleep 3
  [[ $i -eq 20 ]] && fail "Backend unhealthy after 60s — check: docker logs nivesh-backend"
done

# ── 7. Summary ────────────────────────────────────────────────────────────────
ok ""
ok "✅ Redeploy complete!"
ok "   App:    http://$EXTERNAL_IP"
ok "   V2:     http://$EXTERNAL_IP/v2"
ok "   Health: http://$EXTERNAL_IP/api/health"
ok ""
ok "   Tail logs:"
ok "   docker logs -f nivesh-backend"
ok "   docker logs -f nivesh-frontend"
