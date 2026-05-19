#!/usr/bin/env bash
# deploy.sh — Pull code and start/update all services on the VM.
# Run as root (or sudo) on the nivesh-app-vm.
#
# Usage:
#   sudo EXTERNAL_IP=<vm-external-ip> bash /opt/nivesh/deploy/deploy.sh
#
# On subsequent deploys (code changes only):
#   sudo bash /opt/nivesh/deploy/deploy.sh
#   → pulls latest code, restarts backend in ~5s (no image rebuild)
#   → rebuilds images only when requirements.txt or frontend source changes

set -euo pipefail

APP_HOME="/opt/nivesh"
REPO_DIR="$APP_HOME/repo"
DEPLOY_DIR="$APP_HOME/deploy"
ENV_FILE="$APP_HOME/.env.prod"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.prod.yml"
REPO_URL="https://github.com/amitporwal107/nivesh.ai.git"
REPO_BRANCH="${REPO_BRANCH:-main}"

log()  { printf '\033[1;36m[deploy]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[deploy]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[deploy]\033[0m %s\n' "$*"; exit 1; }

[[ -f "$ENV_FILE" ]] || fail ".env.prod not found at $ENV_FILE. Run bootstrap.sh first."

# ── 0. Resolve external IP ───────────────────────────────────────────────────
if [[ -z "${EXTERNAL_IP:-}" ]]; then
    EXTERNAL_IP=$(curl -sf https://api.ipify.org || curl -sf http://ifconfig.me)
fi
[[ -n "$EXTERNAL_IP" ]] || fail "Could not determine external IP. Pass EXTERNAL_IP=<ip>"
log "External IP: $EXTERNAL_IP"

# ── 1. Patch __VM_IP__ placeholders in .env.prod ─────────────────────────────
log "Patching VM IP into .env.prod..."
sed -i "s|__VM_IP__|$EXTERNAL_IP|g" "$ENV_FILE"

# ── 2. Pull latest code ───────────────────────────────────────────────────────
log "Pulling latest code from $REPO_BRANCH..."
PREV_REQ_HASH=""
PREV_FRONTEND_HASH=""
if [[ -d "$REPO_DIR/.git" ]]; then
    PREV_REQ_HASH=$(git -C "$REPO_DIR" rev-parse HEAD:backend/requirements.txt 2>/dev/null || echo "")
    PREV_FRONTEND_HASH=$(git -C "$REPO_DIR" rev-parse HEAD:frontend/src 2>/dev/null || echo "")
    git -C "$REPO_DIR" fetch --quiet origin "$REPO_BRANCH"
    git -C "$REPO_DIR" reset --hard "origin/$REPO_BRANCH"
else
    git clone --depth=50 --branch="$REPO_BRANCH" "$REPO_URL" "$REPO_DIR"
fi
if id -u nivesh &>/dev/null; then
    chown -R nivesh:nivesh "$REPO_DIR"
fi

NEW_REQ_HASH=$(git -C "$REPO_DIR" rev-parse HEAD:backend/requirements.txt 2>/dev/null || echo "")
NEW_FRONTEND_HASH=$(git -C "$REPO_DIR" rev-parse HEAD:frontend/src 2>/dev/null || echo "")

# ── 3. Rebuild backend image only if requirements.txt changed ─────────────────
# Source code is mounted as a volume — image only carries OS libs + Python deps.
if [[ "$PREV_REQ_HASH" != "$NEW_REQ_HASH" ]] || ! docker image inspect nivesh/backend:prod &>/dev/null; then
    log "requirements.txt changed (or image missing) — rebuilding backend image..."
    docker build \
        -f "$REPO_DIR/deploy/nivesh-app/Dockerfile.backend.prod" \
        -t nivesh/backend:prod \
        "$REPO_DIR"
    ok "Backend image rebuilt."
else
    ok "requirements.txt unchanged — skipping backend image rebuild."
fi

# ── 4. Build frontend image only if frontend source changed ──────────────────
# The frontend bundle bakes REACT_APP_BACKEND_URL at build time. We pin
# the canonical production hostname here so the SDK widget's token mint
# and other XHRs work from https://niveshcopilot.com without mixed-content
# (HTTP nip.io URL from HTTPS page) or CORS errors. Override with
# `PUBLIC_BACKEND_URL=...` in the env if a different domain is needed.
PUBLIC_BACKEND_URL="${PUBLIC_BACKEND_URL:-https://niveshcopilot.com}"
if [[ "$PREV_FRONTEND_HASH" != "$NEW_FRONTEND_HASH" ]] || ! docker image inspect nivesh/frontend:prod &>/dev/null; then
    log "Frontend source changed (or image missing) — rebuilding frontend image with backend URL: $PUBLIC_BACKEND_URL"
    docker build \
        -f "$REPO_DIR/deploy/nivesh-app/Dockerfile.frontend.prod" \
        --build-arg REACT_APP_BACKEND_URL="$PUBLIC_BACKEND_URL" \
        -t nivesh/frontend:prod \
        "$REPO_DIR"
    ok "Frontend image rebuilt."
else
    ok "Frontend source unchanged — skipping frontend image rebuild."
fi

# ── 5. Run DB migrations (first deploy only; idempotent) ─────────────────────
log "Running PostgreSQL migrations..."
docker compose -f "$COMPOSE_FILE" \
    --env-file "$ENV_FILE" \
    --profile migrate \
    up migrate --no-log-prefix 2>&1 | tail -20
ok "Migrations done."

# ── 6. Start / restart all services ──────────────────────────────────────────
log "Starting all services..."
docker compose -f "$COMPOSE_FILE" \
    --env-file "$ENV_FILE" \
    up -d --remove-orphans

# ── 7. Wait for backend health ────────────────────────────────────────────────
log "Waiting for backend to become healthy..."
for i in $(seq 1 30); do
    if curl -sf "http://localhost:80/health" &>/dev/null; then
        ok "Backend is healthy."
        break
    fi
    sleep 3
    [[ $i -eq 30 ]] && fail "Backend did not become healthy after 90s — check: docker logs nivesh-backend"
done

# ── 8. Summary ────────────────────────────────────────────────────────────────
ok ""
ok "✅ Deploy complete!"
ok "   App:     http://$EXTERNAL_IP.nip.io"
ok "   Health:  http://$EXTERNAL_IP.nip.io/health"
ok ""
ok "   For code-only changes (no image rebuild):"
ok "   sudo git -C $REPO_DIR pull && docker compose -f $COMPOSE_FILE restart backend"
ok ""
ok "   Useful commands:"
ok "   docker compose -f $COMPOSE_FILE ps"
ok "   docker logs -f nivesh-backend"
ok "   docker logs -f nivesh-frontend"
