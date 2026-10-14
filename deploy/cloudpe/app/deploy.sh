#!/usr/bin/env bash
# deploy.sh — pull, build and (re)start the Nivesh app staging stack on CloudPe.
#
# CloudPe counterpart of deploy/nivesh-staging/redeploy-staging.sh: same stack,
# same container names, plus the docker-compose.cloudpe.yml override.
#
#   sudo bash deploy.sh [branch] [--backend-only|--frontend-only] [--migrate]
#
#   branch            default dev
#   --backend-only    rebuild/restart only app-backend
#   --frontend-only   rebuild/restart only the two frontends
#   --migrate         run the app-migrate profile (backend/migrations/*.sql) after start
#
# Idempotent. Run app/bootstrap.sh once first.

set -euo pipefail

TAG="app-deploy"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../lib/common.sh
source "${HERE}/../lib/common.sh"

STAGING_ROOT="/opt/nivesh-staging"
REPO_DIR="${STAGING_ROOT}/repo"
ENV_FILE="${STAGING_ROOT}/.env.staging"
DEPLOY_KEY="${STAGING_ROOT}/.ssh/id_ed25519"
BASE_COMPOSE="${REPO_DIR}/deploy/nivesh-staging/docker-compose.staging.yml"
OVERRIDE_COMPOSE="${REPO_DIR}/deploy/cloudpe/app/docker-compose.cloudpe.yml"
HOSTNAME_PUBLIC="staging.niveshcopilot.com"
# A cold build of all three images writes ~4 GB.
MIN_FREE_MB="${MIN_FREE_MB_OVERRIDE:-6000}"

BRANCH="dev"
BUILD_FRONTEND=true
BUILD_BACKEND=true
RUN_MIGRATIONS=false

for arg in "$@"; do
    case "$arg" in
        --frontend-only) BUILD_BACKEND=false ;;
        --backend-only)  BUILD_FRONTEND=false ;;
        --migrate)       RUN_MIGRATIONS=true ;;
        -h|--help)       sed -n '2,15p' "$0"; exit 0 ;;
        --*)             fail "Unknown flag: $arg" ;;
        *)               BRANCH="$arg" ;;
    esac
done
$BUILD_BACKEND || $BUILD_FRONTEND || fail "--backend-only and --frontend-only are mutually exclusive."

require_root
[[ -f "$ENV_FILE" ]]        || fail "Missing ${ENV_FILE}. Run app/bootstrap.sh first."
[[ -d "${REPO_DIR}/.git" ]] || fail "Missing ${REPO_DIR}. Run app/bootstrap.sh first."
for f in "${STAGING_ROOT}/ssl/cert.pem" "${STAGING_ROOT}/ssl/key.pem" "${STAGING_ROOT}/nginx/cloudflare-only.conf"; do
    [[ -s "$f" ]] || fail "Missing ${f}. Run app/bootstrap.sh first."
done
require_compose_version

# ── Disk precheck ────────────────────────────────────────────────────────────
# A full root disk stops mongo opening WiredTiger (staging was 502 for ~50 min
# on the old VM for exactly this reason), so refuse before building.
FREE_MB=$(df -Pm / | awk 'NR==2{print $4}')
log "Disk: ${FREE_MB} MB free (need ${MIN_FREE_MB} MB)"
if (( FREE_MB < MIN_FREE_MB )); then
    log "Reclaiming build cache and dangling images..."
    docker builder prune -af >/dev/null 2>&1 || true
    docker image prune -f    >/dev/null 2>&1 || true
    FREE_MB=$(df -Pm / | awk 'NR==2{print $4}')
    (( FREE_MB >= MIN_FREE_MB )) || fail "Only ${FREE_MB} MB free on / after reclaim (need ${MIN_FREE_MB})."
fi

# ── Refresh the repo ─────────────────────────────────────────────────────────
if [[ -f "$DEPLOY_KEY" ]]; then
    GIT_SSH_COMMAND="$(git_ssh_command "$DEPLOY_KEY")"
    export GIT_SSH_COMMAND
fi
GIT=(git -c "safe.directory=${REPO_DIR}")
log "Refreshing repo at ${REPO_DIR} (branch=${BRANCH})..."
"${GIT[@]}" -C "$REPO_DIR" fetch --quiet origin "$BRANCH"
"${GIT[@]}" -C "$REPO_DIR" checkout --quiet "$BRANCH"
"${GIT[@]}" -C "$REPO_DIR" reset --hard --quiet "origin/${BRANCH}"
log "Deploying $("${GIT[@]}" -C "$REPO_DIR" log -1 --format='%h %s')"
[[ -f "$OVERRIDE_COMPOSE" ]] || fail "Missing ${OVERRIDE_COMPOSE} on branch ${BRANCH}."

# No `source` of the env file: compose reads it via --env-file, and sourcing
# breaks on unquoted values such as SMTP_FROM=Name <addr>.
dc() { docker compose --env-file "$ENV_FILE" -f "$BASE_COMPOSE" -f "$OVERRIDE_COMPOSE" "$@"; }

log "Mode: backend=${BUILD_BACKEND} frontend=${BUILD_FRONTEND} migrate=${RUN_MIGRATIONS}"

# ── Build + start ────────────────────────────────────────────────────────────
if $BUILD_BACKEND && $BUILD_FRONTEND; then
    log "Building all images..."
    dc build --pull
    dc up -d --remove-orphans
elif $BUILD_BACKEND; then
    log "Building backend image only..."
    dc build --pull app-backend
    dc up -d --force-recreate app-backend
else
    log "Building frontend images only (v2 + v5)..."
    dc build --pull app-frontend app-frontend-v5
    dc up -d --force-recreate --remove-orphans app-frontend app-frontend-v5
fi

# The build cache stays on this VM (no registry cache here), so only entries
# unused for a week are dropped. Never fatal.
docker builder prune -f --filter until=168h >/dev/null 2>&1 || warn "builder prune failed (continuing)"
log "Disk after build: $(df -h / | awk 'NR==2{print $4" free ("$5" used)"}')"

if $BUILD_BACKEND; then
    log "Waiting for nivesh-staging-app-backend to report healthy..."
    wait_container_healthy nivesh-staging-app-backend 90 2
fi

if $RUN_MIGRATIONS; then
    log "Running app-migrate..."
    dc --profile migrate run --rm app-migrate
fi

# ── Edge nginx ───────────────────────────────────────────────────────────────
# Reload so config changes land and stale upstream IPs are dropped; if the new
# config is broken, recreate (fails fast with the error) rather than keep the old one.
if docker ps --format '{{.Names}}' | grep -q '^nivesh-staging-nginx$'; then
    log "Reloading edge nginx..."
    if docker exec nivesh-staging-nginx nginx -t >/dev/null 2>&1; then
        docker exec nivesh-staging-nginx nginx -s reload
    else
        dc up -d --force-recreate nginx
    fi
else
    dc up -d nginx
fi

# ── Smoke checks through the edge, on loopback ───────────────────────────────
RESOLVE=(-k --resolve "${HOSTNAME_PUBLIC}:443:127.0.0.1")
wait_http_ok "/api/healthz via edge :443" 10 "${RESOLVE[@]}" "https://${HOSTNAME_PUBLIC}/api/healthz"
wait_http_ok "/api/readyz via edge :443"  10 "${RESOLVE[@]}" "https://${HOSTNAME_PUBLIC}/api/readyz"
for path in /v2/ /v5/; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${RESOLVE[@]}" "https://${HOSTNAME_PUBLIC}${path}")
    [[ "$code" == "200" ]] || fail "Frontend ${path} returned HTTP ${code}."
    log "OK  ${path} → 200"
done

log "Done. Running services:"
dc ps
