#!/usr/bin/env bash
# deploy.sh — pull and (re)start NIDP staging on the CloudPe NIDP VM.
#
# The steps of .github/workflows/deploy-nidp-staging.yml as one script, using
# the docker-compose.cloudpe.yml override. There is no image build: code is
# bind-mounted from the checkout, dependencies live in the host venv.
#
#   sudo bash deploy.sh [branch] [--migrate] [--install-cron]
#
#   branch          default dev
#   --migrate       run `python -m nidp.cli migrate` before restarting services
#   --install-cron  install the crontab staged by bootstrap.sh into /etc/cron.d
#                   (first deploy after a restore; feeds start running after this)
#
# Idempotent. Run nidp/bootstrap.sh once first.

set -euo pipefail

TAG="nidp-deploy"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../lib/common.sh
source "${HERE}/../lib/common.sh"

NIDP_HOME="/opt/nidp-staging"
SVC_USER="nidp-staging"
DEV_REPO="/opt/nidp/dev-repo/nivesh.ai"
ENV_FILE="${NIDP_HOME}/nidp.env"
CLOUDPE_ENV="${NIDP_HOME}/cloudpe.env"
DEPLOY_KEY="/opt/nidp/.ssh/id_ed25519"
BASE_COMPOSE="${DEV_REPO}/backend/nidp/deploy/vm/docker-compose.staging.yml"
OVERRIDE_COMPOSE="${DEV_REPO}/deploy/cloudpe/nidp/docker-compose.cloudpe.yml"
STAGED_CRON="${NIDP_HOME}/cron/nidp-staging.cron"
HOSTNAME_PUBLIC="staging-data.niveshcopilot.com"

BRANCH="dev"
RUN_MIGRATIONS=false
INSTALL_CRON=false
for arg in "$@"; do
    case "$arg" in
        --migrate)      RUN_MIGRATIONS=true ;;
        --install-cron) INSTALL_CRON=true ;;
        -h|--help)      sed -n '2,16p' "$0"; exit 0 ;;
        --*)            fail "Unknown flag: $arg" ;;
        *)              BRANCH="$arg" ;;
    esac
done

require_root
for f in "$ENV_FILE" "$CLOUDPE_ENV" "${NIDP_HOME}/query_api.env" "${NIDP_HOME}/venv/bin/python"; do
    [[ -e "$f" ]] || fail "Missing ${f}. Run nidp/bootstrap.sh first."
done
[[ -d "${DEV_REPO}/.git" ]] || fail "Missing ${DEV_REPO}. Run nidp/bootstrap.sh first."
require_compose_version

# ── Refresh the repo ─────────────────────────────────────────────────────────
if [[ -f "$DEPLOY_KEY" ]]; then
    GIT_SSH_COMMAND="$(git_ssh_command "$DEPLOY_KEY")"
    export GIT_SSH_COMMAND
fi
GIT=(git -c "safe.directory=${DEV_REPO}")
log "Refreshing repo at ${DEV_REPO} (branch=${BRANCH})..."
"${GIT[@]}" -C "$DEV_REPO" fetch --quiet origin "$BRANCH"
"${GIT[@]}" -C "$DEV_REPO" checkout --quiet "$BRANCH"
"${GIT[@]}" -C "$DEV_REPO" reset --hard --quiet "origin/${BRANCH}"
chown -R root:"$SVC_USER" "$DEV_REPO"
chmod -R g+rX "$DEV_REPO"
log "Deploying $("${GIT[@]}" -C "$DEV_REPO" log -1 --format='%h %s')"
[[ -f "$OVERRIDE_COMPOSE" ]] || fail "Missing ${OVERRIDE_COMPOSE} on branch ${BRANCH}."

PG_USER=$(env_get NIDP_PG_USER "$ENV_FILE")
PG_DB=$(env_get NIDP_PG_DB "$ENV_FILE")
dc() { docker compose --env-file "$ENV_FILE" --env-file "$CLOUDPE_ENV" -f "$BASE_COMPOSE" -f "$OVERRIDE_COMPOSE" "$@"; }

# ── Dependencies ─────────────────────────────────────────────────────────────
# pip is a no-op when nothing changed, so this runs on every deploy rather
# than trying to detect a requirements.txt change.
log "Installing NIDP requirements into the venv..."
sudo -u "$SVC_USER" "${NIDP_HOME}/venv/bin/pip" install --quiet \
    -r "${DEV_REPO}/backend/nidp/deploy/requirements.txt"

# ── Postgres ─────────────────────────────────────────────────────────────────
dc up -d postgres
wait_container_healthy nidp-postgres-staging 60 2

if $RUN_MIGRATIONS; then
    log "Running NIDP migrations (python -m nidp.cli migrate)..."
    # nidp.env is shell-sourced the same way run_service.sh and the existing workflow do.
    sudo -u "$SVC_USER" bash -c "
        set -euo pipefail
        set -a; source '${ENV_FILE}'; set +a
        cd '${DEV_REPO}/backend'
        '${NIDP_HOME}/venv/bin/python' -m nidp.cli migrate"
    log "Migrations done."
fi

# ── Services ─────────────────────────────────────────────────────────────────
# The DaaS container bind-mounts the checkout read-only, so recreating it is
# enough to pick up new code.
log "Starting nidp-daas-api-staging..."
dc up -d --force-recreate daas-api
log "Restarting nidp-staging-query-api..."
systemctl restart nidp-staging-query-api

log "Reloading nginx..."
install -m 644 "${DEV_REPO}/backend/nidp/deploy/vm/nginx.staging.conf" /etc/nginx/sites-available/nidp-staging
nginx -t
systemctl reload nginx

# ── Health ───────────────────────────────────────────────────────────────────
QUERY_PORT=$(env_get NIDP_QUERY_API_PORT "${NIDP_HOME}/query_api.env")
wait_http_ok "DaaS API :8084/health" 20 "http://127.0.0.1:8084/health"
wait_http_ok "Query API :${QUERY_PORT:-8091}/health" 20 "http://127.0.0.1:${QUERY_PORT:-8091}/health"

RESOLVE=(-k --resolve "${HOSTNAME_PUBLIC}:443:127.0.0.1")
wait_http_ok "nginx /health"       5 "${RESOLVE[@]}" "https://${HOSTNAME_PUBLIC}/health"
wait_http_ok "nginx /daas/health"  5 "${RESOLVE[@]}" "https://${HOSTNAME_PUBLIC}/daas/health"
wait_http_ok "nginx /query/health" 5 "${RESOLVE[@]}" "https://${HOSTNAME_PUBLIC}/query/health"

# ── Cron ─────────────────────────────────────────────────────────────────────
if $INSTALL_CRON; then
    [[ -s "$STAGED_CRON" ]] || fail "No staged crontab at ${STAGED_CRON}. Run nidp/bootstrap.sh first."
    # Feeds (reconciler, DLQ re-drive) must not be pointed at an empty or half-restored database.
    applied=$(docker exec nidp-postgres-staging psql -U "${PG_USER:-nidp_staging}" -d "${PG_DB:-nidp_staging}" -At \
                -c "SELECT count(*) FROM nidp.schema_migrations;" 2>/dev/null || echo 0)
    (( applied > 0 )) || fail "nidp.schema_migrations is empty or missing — restore (nidp/restore.sh) or migrate (--migrate) before --install-cron."
    install -m 644 -o root -g root "$STAGED_CRON" /etc/cron.d/nidp-staging
    log "Installed /etc/cron.d/nidp-staging ($(grep -cvE '^\s*(#|$|[A-Z_]+=)' "$STAGED_CRON" || true) active entries)."
elif [[ ! -f /etc/cron.d/nidp-staging ]]; then
    warn "No /etc/cron.d/nidp-staging yet — feeds are NOT scheduled. Re-run with --install-cron when ready."
fi

log "Done."
dc ps
systemctl --no-pager --lines=0 status nidp-staging-query-api || true
