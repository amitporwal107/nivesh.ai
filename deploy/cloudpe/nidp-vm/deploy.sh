#!/usr/bin/env bash
#
# deploy.sh — NIDP (staging stack) on the CloudPe NIDP VM (cloudpe2).
#
# Runs backend/nidp/deploy/vm/docker-compose.staging.yml (TimescaleDB + DaaS API)
# plus the CloudPe override (adds the Query API, drops GCP VPC binds). Feeds run
# on host cron through run_service.sh with the staging venv. No GCP dependency.
#
# One-time host setup (interactive, needs sudo):
#   sudo bash deploy/cloudpe/nidp-vm/deploy.sh --setup [--install-cron]
#
# Deploy (as the deploy user — this is what GitHub Actions runs; no sudo needed):
#   bash /opt/nidp/dev-repo/nivesh.ai/deploy/cloudpe/nidp-vm/deploy.sh \
#        [--branch dev] [--migrate] [--no-sync]
#
# Layout (same paths as GCP NIDP staging, so the repo's cron/compose files work):
#   /opt/nidp/dev-repo/nivesh.ai   git checkout (owned by the deploy user)
#   /opt/nidp-staging/venv         Python 3.11 venv (feeds on host + mounted into containers)
#   /opt/nidp-staging/nidp.env     secrets/config (mode 640, nidp-staging:<deploy group>)
#   /opt/nidp-staging/data/        TimescaleDB volume
#   /opt/nidp-staging/logs/        feed logs

set -euo pipefail

NIDP_HOME=/opt/nidp-staging
NIDP_USER=nidp-staging
REPO_DIR=/opt/nidp/dev-repo/nivesh.ai
ENV_FILE="$NIDP_HOME/nidp.env"
VENV="$NIDP_HOME/venv"
REPO_URL="${REPO_URL:-git@github.com:amitporwal107/nivesh.ai.git}"
BASE_COMPOSE="$REPO_DIR/backend/nidp/deploy/vm/docker-compose.staging.yml"
OVERRIDE_COMPOSE="$REPO_DIR/deploy/cloudpe/nidp-vm/docker-compose.override.yml"
REQS="$REPO_DIR/backend/nidp/deploy/requirements.txt"
MIN_FREE_MB="${MIN_FREE_MB:-3000}"

BRANCH=dev
MIGRATE=false
SYNC=true
SETUP=false
INSTALL_CRON=false

for arg in "$@"; do
  case "$arg" in
    --setup)          SETUP=true ;;
    --install-cron)   INSTALL_CRON=true ;;
    --migrate)        MIGRATE=true ;;
    --no-sync)        SYNC=false ;;
    --branch=*)       BRANCH="${arg#--branch=}" ;;
    -h|--help)        sed -n '2,24p' "$0"; exit 0 ;;
    *)                echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

log()  { printf '\033[1;35m[cloudpe-nidp]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[cloudpe-nidp]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[cloudpe-nidp] FATAL:\033[0m %s\n' "$*" >&2; exit 1; }

# ── One-time setup (root) ─────────────────────────────────────────────────────
if [[ "$SETUP" == "true" ]]; then
  [[ $EUID -eq 0 ]] || fail "--setup must run with sudo."
  DEPLOY_USER="${SUDO_USER:-}"
  [[ -n "$DEPLOY_USER" && "$DEPLOY_USER" != "root" ]] || fail "Run --setup via sudo from the deploy user."

  if ! command -v docker >/dev/null 2>&1; then
    log "Installing Docker Engine + Compose plugin (get.docker.com)..."
    curl -fsSL https://get.docker.com | sh
  fi
  systemctl enable --now docker
  usermod -aG docker "$DEPLOY_USER"

  # Python 3.11: the containers are python:3.11-slim and load the venv's
  # site-packages, so the venv must be 3.11 (Ubuntu 24.04 ships 3.12).
  if ! command -v python3.11 >/dev/null 2>&1; then
    log "Installing Python 3.11 (deadsnakes PPA)..."
    apt-get install -y -qq software-properties-common >/dev/null
    add-apt-repository -y ppa:deadsnakes/ppa >/dev/null
  fi
  apt-get update -qq
  apt-get install -y -qq python3.11 python3.11-venv python3.11-dev build-essential \
    libpq-dev postgresql-client git curl openssl jq cron tzdata \
    tesseract-ocr poppler-utils >/dev/null

  id -u "$NIDP_USER" >/dev/null 2>&1 || \
    useradd --system --create-home --home-dir "$NIDP_HOME" --shell /bin/bash "$NIDP_USER"
  mkdir -p "$NIDP_HOME"/{logs,run,data/postgres,raw_archives} /opt/nidp/dev-repo
  chown -R "$NIDP_USER:$NIDP_USER" "$NIDP_HOME"/{logs,run,raw_archives}
  chmod 755 "$NIDP_HOME"
  chown "$DEPLOY_USER:$DEPLOY_USER" /opt/nidp/dev-repo

  if [[ ! -d "$REPO_DIR/.git" ]]; then
    log "Cloning $BRANCH into $REPO_DIR as $DEPLOY_USER..."
    sudo -H -u "$DEPLOY_USER" git clone --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
  fi

  # venv owned by the deploy user (CI updates it); world-readable for the cron user.
  mkdir -p "$VENV" && chown "$DEPLOY_USER:$DEPLOY_USER" "$VENV"

  if [[ ! -f "$ENV_FILE" ]]; then
    log "Creating $ENV_FILE from the staging template with a fresh DB password..."
    PW=$(openssl rand -hex 24)
    sed -e "s#^NIDP_PG_PASSWORD=.*#NIDP_PG_PASSWORD=$PW#" \
        -e "s#^NIDP_POSTGRES_URL=.*#NIDP_POSTGRES_URL=postgresql://nidp_staging:$PW@localhost:5434/nidp_staging#" \
        -e "s#^NIVESH_POSTGRES_URL=.*#\# NIVESH_POSTGRES_URL= (app DB lives on the app VM — set only if reachable)#" \
        -e "s#^NIDP_QUERY_API_TOKEN=.*#NIDP_QUERY_API_TOKEN=$(openssl rand -hex 24)#" \
        "$REPO_DIR/backend/nidp/deploy/vm/nidp.env.staging.example" > "$ENV_FILE"
  fi
  # Cron runs feeds as nidp-staging; compose (deploy user) reads it via --env-file.
  chown "$NIDP_USER:$DEPLOY_USER" "$ENV_FILE"
  chmod 640 "$ENV_FILE"

  docker network inspect nidp-staging-bridge >/dev/null 2>&1 || docker network create nidp-staging-bridge >/dev/null

  cat > /etc/logrotate.d/nidp-staging <<'EOF'
/opt/nidp-staging/logs/*.log /opt/nidp-staging/logs/*/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    copytruncate
}
EOF

  if [[ "$INSTALL_CRON" == "true" ]]; then
    install -m 644 "$REPO_DIR/backend/nidp/deploy/vm/nidp.staging.cron" /etc/cron.d/nidp-staging
    log "Installed /etc/cron.d/nidp-staging (only its default-enabled lines run)."
  else
    log "Cron not installed. When ready: sudo bash $0 --setup --install-cron"
  fi

  ok "Setup done. Log out and back in (docker group), then run without --setup to deploy."
  exit 0
fi

# ── Deploy (deploy user) ──────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] || fail "Deploy as the deploy user, not root (use --setup for root steps)."
docker info >/dev/null 2>&1 || fail "Cannot reach Docker as $(id -un). Run --setup, then log in again."
[[ -r "$ENV_FILE" ]] || fail "Missing or unreadable $ENV_FILE. Run: sudo bash $0 --setup"
command -v python3.11 >/dev/null 2>&1 || fail "python3.11 missing. Run: sudo bash $0 --setup"

log "Branch=$BRANCH migrate=$MIGRATE"

FREE_MB=$(df -Pm / | awk 'NR==2{print $4}')
(( FREE_MB >= MIN_FREE_MB )) || fail "Only ${FREE_MB}MB free on / (need ${MIN_FREE_MB}MB)."
log "Disk: ${FREE_MB}MB free"

if [[ "$SYNC" == "true" ]]; then
  log "Syncing $REPO_DIR to origin/$BRANCH..."
  git -C "$REPO_DIR" fetch --quiet origin "$BRANCH"
  git -C "$REPO_DIR" checkout --quiet "$BRANCH"
  git -C "$REPO_DIR" reset --hard --quiet "origin/$BRANCH"
fi
log "Code: $(git -C "$REPO_DIR" log -1 --oneline)"
[[ -f "$OVERRIDE_COMPOSE" ]] || fail "Missing $OVERRIDE_COMPOSE on $BRANCH — merge deploy/cloudpe into it first."

# venv: create once; reinstall only when requirements.txt changes.
[[ -x "$VENV/bin/python" ]] || { log "Creating venv $VENV (python3.11)..."; python3.11 -m venv "$VENV"; }
REQ_HASH=$(sha256sum "$REQS" | cut -d' ' -f1)
if [[ "$(cat "$VENV/.requirements.sha256" 2>/dev/null)" != "$REQ_HASH" ]]; then
  log "Installing requirements into $VENV..."
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$REQS"
  echo "$REQ_HASH" > "$VENV/.requirements.sha256"
else
  log "Requirements unchanged — venv kept."
fi

docker network inspect nidp-staging-bridge >/dev/null 2>&1 || docker network create nidp-staging-bridge >/dev/null

COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$BASE_COMPOSE" -f "$OVERRIDE_COMPOSE")
"${COMPOSE[@]}" config -q
"${COMPOSE[@]}" up -d --remove-orphans
# Code is mounted read-only, so a restart picks up the new checkout.
"${COMPOSE[@]}" restart daas-api query-api

if [[ "$MIGRATE" == "true" ]]; then
  log "Running NIDP migrations against the staging DB..."
  # shellcheck disable=SC1090  # env file path is only known at runtime
  ( set -a; source "$ENV_FILE"; set +a
    cd "$REPO_DIR/backend" && "$VENV/bin/python" -m nidp.cli migrate )
fi

FAILED=0
for svc in "daas:8084" "query:8091"; do
  name="${svc%%:*}"; port="${svc##*:}"; code=000
  for _ in $(seq 1 20); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$port/health" || true)
    [[ "$code" == "200" ]] && break
    sleep 3
  done
  echo "  $name /health -> HTTP $code  $(curl -s --max-time 5 "http://127.0.0.1:$port/health" | head -c 200)"
  [[ "$code" == "200" ]] || FAILED=1
done

"${COMPOSE[@]}" ps --format 'table {{.Name}}\t{{.Status}}'
(( FAILED == 0 )) || fail "Health checks failed."
ok "NIDP deploy complete: $(git -C "$REPO_DIR" log -1 --oneline)"
