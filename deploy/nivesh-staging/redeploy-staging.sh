#!/usr/bin/env bash
# redeploy-staging.sh — pull, rebuild and (re)start the staging stack.
#
# Runs on nivesh-app-vm as root. Mirrors the spirit of deploy/nivesh-app/redeploy.sh
# but operates against /opt/nivesh-staging/repo and the staging docker-compose file.
#
# Usage:
#   sudo bash /opt/nivesh-staging/repo/deploy/nivesh-staging/redeploy-staging.sh [branch]
#
# Idempotent. Safe to re-run.

set -euo pipefail

STAGING_ROOT="/opt/nivesh-staging"
REPO_DIR="${STAGING_ROOT}/repo"
COMPOSE_FILE="${REPO_DIR}/deploy/nivesh-staging/docker-compose.staging.yml"
ENV_FILE="${STAGING_ROOT}/.env.staging"
BRANCH="${1:-hotfix/v3-catchall-loop}"   # current working branch; override with arg

log() { echo "[redeploy-staging] $*"; }
fail() { echo "[redeploy-staging] FATAL: $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "Run as root (sudo)."
[[ -f "${ENV_FILE}" ]] || fail "Missing ${ENV_FILE}. Run bootstrap-staging.sh first."
[[ -d "${REPO_DIR}/.git" ]] || fail "Missing ${REPO_DIR}. Clone the repo there first."
[[ -f "${COMPOSE_FILE}" ]] || fail "Missing ${COMPOSE_FILE}."

log "Refreshing repo at ${REPO_DIR} (branch=${BRANCH})..."
git -C "${REPO_DIR}" fetch --quiet origin
git -C "${REPO_DIR}" checkout --quiet "${BRANCH}"
git -C "${REPO_DIR}" reset --hard --quiet "origin/${BRANCH}"

log "Loading staging env..."
set -a; source "${ENV_FILE}"; set +a

log "Building images..."
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" build --pull

log "Bringing the stack up..."
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d --remove-orphans

log "Waiting for nivesh-staging-ingestion to report healthy..."
for i in {1..30}; do
    status=$(docker inspect --format='{{.State.Health.Status}}' nivesh-staging-ingestion 2>/dev/null || echo "unknown")
    if [[ "${status}" == "healthy" ]]; then
        log "Healthy after ${i} checks."
        break
    fi
    sleep 2
done
[[ "$(docker inspect --format='{{.State.Health.Status}}' nivesh-staging-ingestion 2>/dev/null)" == "healthy" ]] \
    || fail "nivesh-staging-ingestion did not become healthy."

log "Smoke check via nginx on ${PI_NGINX_BIND_ADDR:-127.0.0.1}:${PI_NGINX_PORT:-8443}..."
curl -k -fsS --resolve "staging.niveshcopilot.com:${PI_NGINX_PORT:-8443}:${PI_NGINX_BIND_ADDR:-127.0.0.1}" \
    "https://staging.niveshcopilot.com:${PI_NGINX_PORT:-8443}/api/healthz" | head -200 \
    || fail "Healthz check via nginx failed."

log "Done. Running services:"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" ps
