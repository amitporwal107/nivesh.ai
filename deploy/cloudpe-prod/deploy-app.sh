#!/usr/bin/env bash
# deploy-app.sh — pull, build and (re)start the production app stack on the CloudPe prod VM.
#
# CloudPe-prod counterpart of deploy/cloudpe/app/deploy.sh (staging).
#
#   sudo bash deploy-app.sh [branch] [--backend-only|--frontend-only] [--migrate]
#
#   branch            default main
#   --backend-only    rebuild/restart only app-backend
#   --frontend-only   rebuild/restart only the two frontends
#   --migrate         run the app-migrate profile (backend/migrations/*.sql) after start
#
# Idempotent. Run bootstrap.sh once first.

set -euo pipefail

TAG="prod-app-deploy"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "${HERE}/lib.sh"

# A cold build of all three images writes ~4 GB.
MIN_FREE_MB="${MIN_FREE_MB_OVERRIDE:-6000}"

BRANCH="main"
BUILD_FRONTEND=true
BUILD_BACKEND=true
RUN_MIGRATIONS=false

for arg in "$@"; do
    case "$arg" in
        --frontend-only) BUILD_BACKEND=false ;;
        --backend-only)  BUILD_FRONTEND=false ;;
        --migrate)       RUN_MIGRATIONS=true ;;
        -h|--help)       sed -n '2,14p' "$0"; exit 0 ;;
        --*)             fail "Unknown flag: $arg" ;;
        *)               BRANCH="$arg" ;;
    esac
done
$BUILD_BACKEND || $BUILD_FRONTEND || fail "--backend-only and --frontend-only are mutually exclusive."

require_root
[[ -f "$APP_ENV_FILE" ]]    || fail "Missing ${APP_ENV_FILE}."
[[ -d "${REPO_DIR}/.git" ]] || fail "Missing ${REPO_DIR}. Run bootstrap.sh first."
[[ -s /etc/nginx/ssl/prod.crt && -s /etc/nginx/ssl/prod.key ]] || fail "Missing /etc/nginx/ssl/prod.{crt,key}. Run bootstrap.sh first."
require_compose_version

# ── Disk precheck ────────────────────────────────────────────────────────────
# A full root disk stops mongo opening WiredTiger, so refuse before building.
FREE_MB=$(df -Pm / | awk 'NR==2{print $4}')
log "Disk: ${FREE_MB} MB free (need ${MIN_FREE_MB} MB)"
if (( FREE_MB < MIN_FREE_MB )); then
    log "Reclaiming build cache and dangling images..."
    docker builder prune -af >/dev/null 2>&1 || true
    docker image prune -f    >/dev/null 2>&1 || true
    FREE_MB=$(df -Pm / | awk 'NR==2{print $4}')
    (( FREE_MB >= MIN_FREE_MB )) || fail "Only ${FREE_MB} MB free on / after reclaim (need ${MIN_FREE_MB})."
fi

refresh_repo "$BRANCH"
[[ -f "$APP_COMPOSE" ]] || fail "Missing ${APP_COMPOSE} on branch ${BRANCH}."

# No `source` of the env file: compose reads it via --env-file, and sourcing breaks on
# unquoted values such as SMTP_FROM=Name <addr>.
dc() { docker compose --env-file "$APP_ENV_FILE" -f "$APP_COMPOSE" "$@"; }

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

# The build cache stays on this VM, so only entries unused for a week are dropped. Never fatal.
docker builder prune -f --filter until=168h >/dev/null 2>&1 || warn "builder prune failed (continuing)"
log "Disk after build: $(df -h / | awk 'NR==2{print $4" free ("$5" used)"}')"

if $BUILD_BACKEND; then
    log "Waiting for nivesh-backend to report healthy..."
    wait_container_healthy nivesh-backend 90 2
fi

if $RUN_MIGRATIONS; then
    log "Running app-migrate..."
    dc --profile migrate run --rm app-migrate
fi

# ── Edge nginx (container) ───────────────────────────────────────────────────
# Reload so config changes land and stale upstream IPs are dropped; if the new config
# is broken, recreate (fails fast with the error) rather than keep the old one.
if docker ps --format '{{.Names}}' | grep -q '^nivesh-edge$'; then
    log "Reloading edge nginx..."
    if docker exec nivesh-edge nginx -t >/dev/null 2>&1; then
        docker exec nivesh-edge nginx -s reload
    else
        dc up -d --force-recreate nginx
    fi
else
    dc up -d nginx
fi

# ── Host nginx + cron ────────────────────────────────────────────────────────
install -m 644 "${REPO_DIR}/deploy/cloudpe-prod/edge/nginx-prod.conf" /etc/nginx/sites-available/nivesh-prod
nginx -t
systemctl reload nginx
install -m 644 -o root -g root "${REPO_DIR}/deploy/cloudpe-prod/app/nivesh-prod.cron" /etc/cron.d/nivesh-prod

# ── Smoke checks through the host nginx, on loopback ─────────────────────────
RESOLVE=(-k --resolve "${HOSTNAME_APP}:443:127.0.0.1")
wait_http_ok "/api/healthz via host nginx :443" 10 "${RESOLVE[@]}" "https://${HOSTNAME_APP}/api/healthz"
wait_http_ok "/api/readyz via host nginx :443"  10 "${RESOLVE[@]}" "https://${HOSTNAME_APP}/api/readyz"
for path in /v2/ /v5/; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${RESOLVE[@]}" "https://${HOSTNAME_APP}${path}")
    [[ "$code" == "200" ]] || fail "Frontend ${path} returned HTTP ${code}."
    log "OK  ${path} → 200"
done

log "Done. Running services:"
dc ps
