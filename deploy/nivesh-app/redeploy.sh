#!/usr/bin/env bash
# redeploy.sh — Canonical redeployment script for nivesh-app-vm.
#
# WHAT THIS SCRIPT DOES (in order):
#   1. Pull latest code from git
#   2. Sync ALL deploy files (Dockerfiles, nginx.conf, compose) from repo → /opt/nivesh/deploy/
#      *** This is the critical step that prevents stale-file failures ***
#   3. Detect the VM's external IP (baked into the frontend build at compile time)
#   4. Build the backend Docker image (skippable with --frontend-only)
#   5. Build the frontend Docker image with PUBLIC_URL=/v2 (skippable with --backend-only)
#   6. Replace and restart the updated containers
#   7. Wait for the backend health check to pass
#
# ROOT CAUSE OF PAST FAILURES:
#   The VM's /opt/nivesh/deploy/ directory holds Dockerfiles, nginx.conf, and
#   docker-compose.prod.yml. These are operational files copied once during
#   bootstrap and NOT automatically updated when the repo changes. Every time
#   a Dockerfile or nginx.conf was improved in the repo, the VM kept using the
#   stale version — causing SSL errors, missing PUBLIC_URL, pip failures, etc.
#   Step 2 above (the rsync) eliminates this class of failure permanently.
#
# USAGE:
#   # From your local machine (SSH-forwards to VM automatically):
#   bash deploy/nivesh-app/redeploy.sh
#
#   # From inside the VM:
#   bash /opt/nivesh/deploy/redeploy.sh
#
# OPTIONS:
#   --frontend-only    Skip backend rebuild (JS/CSS change only — much faster)
#   --backend-only     Skip frontend rebuild
#   --branch <name>    Override git branch (default: main)
#   --skip-sync        Skip the deploy-dir sync (emergency use only)

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
VM_NAME="nivesh-app-vm"
VM_ZONE="asia-south1-a"
PROJECT="niveshdataintelligence"
SSH_USER="aporwal107_gmail_com"

REPO_DIR="/opt/nivesh/repo"
DEPLOY_DIR="/opt/nivesh/deploy"
ENV_FILE="/opt/nivesh/.env.prod"
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.prod.yml"
BRANCH="${BRANCH:-main}"

BUILD_FRONTEND=true
BUILD_BACKEND=true
SKIP_SYNC=false

for arg in "$@"; do
  case "$arg" in
    --frontend-only) BUILD_BACKEND=false ;;
    --backend-only)  BUILD_FRONTEND=false ;;
    --skip-sync)     SKIP_SYNC=true ;;
    --branch)        shift; BRANCH="$1" ;;
  esac
done

log()  { printf '\n\033[1;36m[redeploy]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[redeploy]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[redeploy]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[redeploy]\033[0m %s\n' "$*"; exit 1; }

# ── Detect execution context ──────────────────────────────────────────────────
# If running locally (not on the VM), SSH into the VM and re-run this script.
if [[ "$(hostname)" != "$VM_NAME"* ]] && [[ ! -d "$REPO_DIR" ]]; then
  log "Running locally — SSH-forwarding to VM..."
  GCLOUD=$(command -v gcloud || echo "/root/google-cloud-sdk/bin/gcloud")
  REMOTE_ARGS="BUILD_FRONTEND=$BUILD_FRONTEND BUILD_BACKEND=$BUILD_BACKEND BRANCH=$BRANCH"
  "$GCLOUD" compute ssh "${SSH_USER}@${VM_NAME}" \
    --zone="$VM_ZONE" --project="$PROJECT" \
    --command="sudo $REMOTE_ARGS bash $DEPLOY_DIR/redeploy.sh $*"
  exit $?
fi

# ── Escalate to root ──────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && exec sudo "$0" "$@"

[[ -f "$ENV_FILE" ]] || fail ".env.prod not found at $ENV_FILE — run bootstrap.sh first"

log "========================================================"
log " nivesh-app-vm redeploy  branch=$BRANCH"
log " backend=$BUILD_BACKEND  frontend=$BUILD_FRONTEND"
log "========================================================"

# ── Step 1: Pull latest code ──────────────────────────────────────────────────
log "Step 1/7 — Pulling latest code from branch '$BRANCH'..."
git config --global --add safe.directory "$REPO_DIR" 2>/dev/null || true
git -C "$REPO_DIR" fetch --quiet origin "$BRANCH"
git -C "$REPO_DIR" reset --hard "origin/$BRANCH"
ok "Code updated → $(git -C "$REPO_DIR" log -1 --oneline)"

# ── Step 2: Sync deploy files from repo ──────────────────────────────────────
# This is the step that prevents all stale-file failures.
# Every Dockerfile, nginx.conf, docker-compose.prod.yml in the repo is
# the authoritative version. The VM's /opt/nivesh/deploy/ is a mirror.
#
# Files synced: Dockerfile.*.prod, nginx.conf, docker-compose.prod.yml
# Files NOT synced: bootstrap.sh, create-vm.sh (one-time setup scripts)
#                   mongo-init.js (data — only run at first-start)
if [[ "$SKIP_SYNC" == "true" ]]; then
  warn "Step 2/7 — Skipping deploy-dir sync (--skip-sync passed)."
  warn "          Using existing files in $DEPLOY_DIR/"
else
  log "Step 2/7 — Syncing deploy files: repo → $DEPLOY_DIR/"
  REPO_DEPLOY="$REPO_DIR/deploy/nivesh-app"

  [[ -d "$REPO_DEPLOY" ]] || fail "Deploy source not found: $REPO_DEPLOY"

  mkdir -p "$DEPLOY_DIR"

  for f in \
    Dockerfile.backend.prod \
    Dockerfile.frontend.prod \
    Dockerfile.frontend-v5.prod \
    nginx.conf \
    docker-compose.prod.yml; do
    src="$REPO_DEPLOY/$f"
    dst="$DEPLOY_DIR/$f"
    if [[ -f "$src" ]]; then
      cp -f "$src" "$dst"
      ok "  synced: $f"
    else
      warn "  missing in repo: $f — keeping existing $dst"
    fi
  done

  # Self-update: also replace this script with the repo version so the VM
  # always runs the latest redeploy.sh without a manual copy step.
  #
  # ATOMIC replace (write temp + mv), NOT in-place cp. `cp -f` truncates and
  # rewrites the SAME inode this bash process is still reading from; when the
  # new file differs in length, our read offset shifts mid-run and the script
  # dies with garbage like "line N: x: command not found" (status 127). `mv`
  # is a rename to a NEW inode, so the running shell keeps reading the original
  # (now-unlinked but still-open) inode and is never corrupted.
  if [[ -f "$REPO_DEPLOY/redeploy.sh" ]]; then
    cp -f "$REPO_DEPLOY/redeploy.sh" "$DEPLOY_DIR/redeploy.sh.tmp"
    chmod +x "$DEPLOY_DIR/redeploy.sh.tmp"
    mv -f "$DEPLOY_DIR/redeploy.sh.tmp" "$DEPLOY_DIR/redeploy.sh"
    ok "  synced: redeploy.sh (self-updated, atomic)"
  fi

  ok "Deploy files synced."
fi

# ── Step 3: Resolve external IP ──────────────────────────────────────────────
# The frontend build bakes REACT_APP_BACKEND_URL into the JS bundle at compile
# time. For HTTPS (Cloudflare), we use the domain; for plain HTTP, the IP.
log "Step 3/7 — Resolving external IP..."
EXTERNAL_IP=$(curl -sf https://api.ipify.org 2>/dev/null || curl -sf http://ifconfig.me)
[[ -n "$EXTERNAL_IP" ]] || fail "Could not determine external IP"
ok "External IP: $EXTERNAL_IP"

# Backend URL: prefer HTTPS domain when deploying to Cloudflare-proxied domain.
# Override by setting BACKEND_URL env before running this script.
BACKEND_URL="${BACKEND_URL:-https://niveshcopilot.com}"
ok "Backend URL for frontend build: $BACKEND_URL"

# ── Step 4: Build backend ─────────────────────────────────────────────────────
if [[ "$BUILD_BACKEND" == "true" ]]; then
  log "Step 4/7 — Building backend image (this installs Python deps)..."
  docker build \
    -f "$DEPLOY_DIR/Dockerfile.backend.prod" \
    -t nivesh/backend:prod \
    "$REPO_DIR"
  ok "Backend image built."
else
  ok "Step 4/7 — Skipping backend build (--frontend-only)."
fi

# ── Step 5: Build frontend ────────────────────────────────────────────────────
# PUBLIC_URL=/v2 is MANDATORY — without it webpack bakes /static/... paths
# into index.html and nginx's /v2/ routing causes MIME type errors in browsers.
if [[ "$BUILD_FRONTEND" == "true" ]]; then
  log "Step 5/7 — Building frontend image..."
  log "         PUBLIC_URL=/v2  REACT_APP_BACKEND_URL=$BACKEND_URL"
  docker build \
    -f "$DEPLOY_DIR/Dockerfile.frontend.prod" \
    --build-arg PUBLIC_URL="/v2" \
    --build-arg REACT_APP_BACKEND_URL="$BACKEND_URL" \
    -t nivesh/frontend:prod \
    "$REPO_DIR"
  ok "Frontend image built."

  # frontend-v5 (Vite/React 18) — served at /v5/ via the edge nginx proxy.
  # VITE_API_URL is baked into the bundle at build time → use the prod apex.
  log "Step 5b/7 — Building frontend-v5 image..."
  log "         VITE_BASE=/v5/  VITE_API_URL=$BACKEND_URL"
  docker build \
    -f "$DEPLOY_DIR/Dockerfile.frontend-v5.prod" \
    --build-arg VITE_BASE="/v5/" \
    --build-arg VITE_API_URL="$BACKEND_URL" \
    --build-arg VITE_USE_MOCK_API="false" \
    -t nivesh/frontend-v5:prod \
    "$REPO_DIR"
  ok "frontend-v5 image built."
else
  ok "Step 5/7 — Skipping frontend build (--backend-only)."
fi

# ── Step 6: Restart updated containers ───────────────────────────────────────
log "Step 6/7 — Replacing containers..."

# Stop containers first so compose recreates them with the new image.
if [[ "$BUILD_BACKEND" == "true" ]]; then
  docker rm -f nivesh-backend  2>/dev/null && ok "  removed: nivesh-backend" || true
fi
if [[ "$BUILD_FRONTEND" == "true" ]]; then
  docker rm -f nivesh-frontend    2>/dev/null && ok "  removed: nivesh-frontend"    || true
  docker rm -f nivesh-frontend-v5 2>/dev/null && ok "  removed: nivesh-frontend-v5" || true
fi

# Compose up only the services that were rebuilt (data stores are unaffected).
SERVICES=""
[[ "$BUILD_BACKEND"  == "true" ]] && SERVICES="$SERVICES backend"
[[ "$BUILD_FRONTEND" == "true" ]] && SERVICES="$SERVICES frontend frontend-v5"

docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d $SERVICES
ok "Containers started."

# ── Step 7: Health check ──────────────────────────────────────────────────────
log "Step 7/7 — Waiting for backend to become healthy (up to 60s)..."
for i in $(seq 1 20); do
  if curl -sf "http://localhost:80/api/health" &>/dev/null; then
    ok "Backend healthy (attempt $i/20)."
    break
  fi
  if [[ $i -eq 20 ]]; then
    fail "Backend unhealthy after 60s.
  Diagnose with:
    docker logs --tail 50 nivesh-backend
    docker logs --tail 20 nivesh-frontend"
  fi
  sleep 3
done

# ── Summary ───────────────────────────────────────────────────────────────────
ok ""
ok "╔════════════════════════════════════════╗"
ok "║  Redeploy complete                     ║"
ok "╠════════════════════════════════════════╣"
ok "║  App:     https://niveshcopilot.com    ║"
ok "║  V2:      https://niveshcopilot.com/v2 ║"
ok "║  Health:  http://$EXTERNAL_IP/api/health  ║"
ok "╠════════════════════════════════════════╣"
ok "║  Commit:  $(git -C "$REPO_DIR" log -1 --oneline | head -c 38)  ║"
ok "╠════════════════════════════════════════╣"
ok "║  Tail logs:                            ║"
ok "║    docker logs -f nivesh-backend       ║"
ok "║    docker logs -f nivesh-frontend      ║"
ok "╚════════════════════════════════════════╝"
