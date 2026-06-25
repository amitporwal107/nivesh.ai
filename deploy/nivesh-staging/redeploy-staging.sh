#!/usr/bin/env bash
# redeploy-staging.sh — pull, rebuild and (re)start the staging stack.
#
# Runs on nivesh-app-vm as root. Mirrors the spirit of deploy/nivesh-app/redeploy.sh
# but operates against /opt/nivesh-staging/repo and the staging docker-compose file.
#
# Usage:
#   sudo bash redeploy-staging.sh [branch] [--frontend-only|--backend-only]
#
# Idempotent. Safe to re-run.

set -euo pipefail

STAGING_ROOT="/opt/nivesh-staging"
REPO_DIR="${STAGING_ROOT}/repo"
COMPOSE_FILE="${REPO_DIR}/deploy/nivesh-staging/docker-compose.staging.yml"
ENV_FILE="${STAGING_ROOT}/.env.staging"

# ── Argument parsing ──────────────────────────────────────────────────────────
BRANCH="dev"
BUILD_FRONTEND=true
BUILD_BACKEND=true

for arg in "$@"; do
  case "$arg" in
    --frontend-only) BUILD_BACKEND=false  ;;
    --backend-only)  BUILD_FRONTEND=false ;;
    --*)             ;;            # ignore unknown flags
    *)               BRANCH="$arg" ;;   # first non-flag = branch name
  esac
done

log() { echo "[redeploy-staging] $*"; }
fail() { echo "[redeploy-staging] FATAL: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "Run as root (sudo)."
[[ -f "${ENV_FILE}" ]] || fail "Missing ${ENV_FILE}. Run bootstrap-staging.sh first."
[[ -d "${REPO_DIR}/.git" ]] || fail "Missing ${REPO_DIR}. Clone the repo there first."

# Git ≥2.35.2 refuses to operate on repos owned by a different user.
# Running as root (sudo) on a repo owned by another user triggers this. Pass
# safe.directory INLINE (-c) on every command instead of writing the global
# config — writing ~/.gitconfig fails when HOME is non-writable or root-owned
# ("could not lock config file /home/<user>/.gitconfig: Permission denied").
GIT=(git -c "safe.directory=${REPO_DIR}")
[[ -f "${COMPOSE_FILE}" ]] || fail "Missing ${COMPOSE_FILE}."

log "Refreshing repo at ${REPO_DIR} (branch=${BRANCH})..."
"${GIT[@]}" -C "${REPO_DIR}" fetch --quiet origin
"${GIT[@]}" -C "${REPO_DIR}" checkout --quiet "${BRANCH}"
"${GIT[@]}" -C "${REPO_DIR}" reset --hard --quiet "origin/${BRANCH}"

log "Mode: backend=${BUILD_BACKEND} frontend=${BUILD_FRONTEND}"

log "Loading staging env..."
set -a; source "${ENV_FILE}"; set +a

# ── Build only the services that changed ─────────────────────────────────────
if [[ "${BUILD_BACKEND}" == "true" && "${BUILD_FRONTEND}" == "true" ]]; then
    log "Building all images..."
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" build --pull
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d --remove-orphans
elif [[ "${BUILD_BACKEND}" == "true" ]]; then
    log "Building backend image only..."
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" build --pull app-backend
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d --force-recreate app-backend
elif [[ "${BUILD_FRONTEND}" == "true" ]]; then
    log "Building frontend images only (v2 + v5)..."
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" build --pull app-frontend app-frontend-v5
    # --force-recreate --remove-orphans: services pin a fixed container_name, so a
    # stale container left by an interrupted recreate (Docker auto-renames it with a
    # hex prefix) otherwise blocks plain `up -d` with a name-conflict error. The full
    # and backend-only branches already pass these flags; the frontend path must too.
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d --force-recreate --remove-orphans app-frontend app-frontend-v5
fi

# ── Backend health check (skip for frontend-only deploys) ────────────────────
if [[ "${BUILD_BACKEND}" == "true" ]]; then
    log "Waiting for nivesh-staging-app-backend to report healthy..."
    for i in {1..30}; do
        status=$(docker inspect --format='{{.State.Health.Status}}' nivesh-staging-app-backend 2>/dev/null || echo "unknown")
        if [[ "${status}" == "healthy" ]]; then
            log "Healthy after ${i} checks."
            break
        fi
        sleep 2
    done
    [[ "$(docker inspect --format='{{.State.Health.Status}}' nivesh-staging-app-backend 2>/dev/null)" == "healthy" ]] \
        || fail "nivesh-staging-app-backend did not become healthy."
fi

# Reload the edge nginx so any nginx-staging.conf change lands and stale
# upstream resolutions are cleared. (The config also uses dynamic DNS via
# 127.0.0.11 resolver so even without this, fresh container IPs are picked
# up within ~10s — but reload is cheap and avoids the 502 race window.)
if docker ps --format '{{.Names}}' | grep -q '^nivesh-staging-nginx$'; then
    log "Reloading edge nginx..."
    # If the new config is syntactically broken, recreate the container
    # (which will fail fast with a clear error) instead of leaving us in a
    # half-state where nginx kept the old config.
    docker exec nivesh-staging-nginx nginx -t > /dev/null 2>&1 \
        && docker exec nivesh-staging-nginx nginx -s reload \
        || docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d --force-recreate nginx
fi

# Smoke check always probes via the loopback interface — the bind address
# (0.0.0.0 once we go public) is not a valid connect target.
SMOKE_PORT="${PI_NGINX_PORT:-8443}"
log "Smoke check via nginx on 127.0.0.1:${SMOKE_PORT}..."
curl -k -fsS --resolve "staging.niveshcopilot.com:${SMOKE_PORT}:127.0.0.1" \
    "https://staging.niveshcopilot.com:${SMOKE_PORT}/api/healthz" | head -200 \
    || fail "Healthz check via nginx failed."

log "Done. Running services:"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" ps
