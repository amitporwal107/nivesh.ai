#!/usr/bin/env bash
# deploy-nidp.sh — pull and (re)start the production NIDP stack on the CloudPe prod VM.
#
# CloudPe-prod counterpart of deploy/cloudpe/nidp/deploy.sh (staging). There is no image
# build: code is bind-mounted from the checkout, dependencies live in the host venv.
#
#   sudo bash deploy-nidp.sh [branch] [--migrate] [--install-cron]
#
#   branch          default main
#   --migrate       run `python -m nidp.cli migrate` before restarting services
#   --install-cron  install the feed crontab into /etc/cron.d/nidp (first deploy after a
#                   restore). Once installed, later deploys keep it in sync automatically.
#
# Idempotent. Run bootstrap.sh once first.

set -euo pipefail

TAG="prod-nidp-deploy"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "${HERE}/lib.sh"

STAGED_CRON="${NIDP_ROOT}/cron/nidp.cron"
CRON_DST="/etc/cron.d/nidp"

BRANCH="main"
RUN_MIGRATIONS=false
INSTALL_CRON=false
for arg in "$@"; do
    case "$arg" in
        --migrate)      RUN_MIGRATIONS=true ;;
        --install-cron) INSTALL_CRON=true ;;
        -h|--help)      sed -n '2,15p' "$0"; exit 0 ;;
        --*)            fail "Unknown flag: $arg" ;;
        *)              BRANCH="$arg" ;;
    esac
done

require_root
for f in "$NIDP_ENV_FILE" "$NIDP_CLOUDPE_ENV" "$NIDP_QUERY_ENV" "${NIDP_ROOT}/venv/bin/python"; do
    [[ -e "$f" ]] || fail "Missing ${f}. Run bootstrap.sh (and create nidp.env) first."
done
[[ -d "${REPO_DIR}/.git" ]] || fail "Missing ${REPO_DIR}. Run bootstrap.sh first."
require_compose_version

refresh_repo "$BRANCH"
[[ -f "$NIDP_COMPOSE" ]] || fail "Missing ${NIDP_COMPOSE} on branch ${BRANCH}."

PG_USER=$(env_get NIDP_PG_USER "$NIDP_ENV_FILE"); PG_USER="${PG_USER:-nidp}"
PG_DB=$(env_get NIDP_PG_DB "$NIDP_ENV_FILE");     PG_DB="${PG_DB:-nidp}"
dc() { docker compose --env-file "$NIDP_ENV_FILE" --env-file "$NIDP_CLOUDPE_ENV" -f "$NIDP_COMPOSE" "$@"; }

# ── Dependencies + cron wrapper ──────────────────────────────────────────────
# pip is a no-op when nothing changed, so this runs on every deploy rather than trying
# to detect a requirements.txt change.
log "Installing NIDP requirements into the venv..."
sudo -u "$SVC_USER" "${NIDP_ROOT}/venv/bin/pip" install --quiet \
    -r "${REPO_DIR}/backend/nidp/deploy/requirements.txt"
# The repo's prod wrapper (flock + bounded retry); cron calls it by this stable path.
install -m 755 -o "$SVC_USER" -g "$SVC_USER" \
    "${REPO_DIR}/backend/nidp/deploy/vm/run_service.sh" "${NIDP_ROOT}/run_service.sh"

# ── Postgres ─────────────────────────────────────────────────────────────────
dc up -d postgres
wait_container_healthy nidp-postgres 60 2

if $RUN_MIGRATIONS; then
    log "Running NIDP migrations (python -m nidp.cli migrate)..."
    # nidp.env is shell-sourced the same way run_service.sh does.
    sudo -u "$SVC_USER" bash -c "
        set -euo pipefail
        set -a; source '${NIDP_ENV_FILE}'; set +a
        cd '${REPO_DIR}/backend'
        '${NIDP_ROOT}/venv/bin/python' -m nidp.cli migrate"
    log "Migrations done."
fi

# ── Services ─────────────────────────────────────────────────────────────────
# The DaaS container bind-mounts the checkout read-only, so recreating it picks up new code.
log "Starting nidp-daas-api..."
dc up -d --force-recreate daas-api
log "Restarting nidp-query-api..."
install -m 644 "${REPO_DIR}/deploy/cloudpe-prod/nidp/nidp-query-api.service" /etc/systemd/system/nidp-query-api.service
systemctl daemon-reload
systemctl restart nidp-query-api

log "Reloading nginx..."
install -m 644 "${REPO_DIR}/deploy/cloudpe-prod/edge/nginx-prod.conf" /etc/nginx/sites-available/nivesh-prod
nginx -t
systemctl reload nginx

# ── Health ───────────────────────────────────────────────────────────────────
QUERY_PORT=$(env_get NIDP_QUERY_API_PORT "$NIDP_QUERY_ENV")
wait_http_ok "DaaS API :8083/health" 20 "http://127.0.0.1:8083/health"
wait_http_ok "Query API :${QUERY_PORT:-8090}/health" 20 "http://127.0.0.1:${QUERY_PORT:-8090}/health"

RESOLVE=(-k --resolve "${HOSTNAME_DATA}:443:127.0.0.1")
wait_http_ok "nginx /health"       5 "${RESOLVE[@]}" "https://${HOSTNAME_DATA}/health"
wait_http_ok "nginx /daas/health"  5 "${RESOLVE[@]}" "https://${HOSTNAME_DATA}/daas/health"
wait_http_ok "nginx /query/health" 5 "${RESOLVE[@]}" "https://${HOSTNAME_DATA}/query/health"

# ── Cron ─────────────────────────────────────────────────────────────────────
# Same feeds as staging (deploy/cloudpe/nidp/nidp-staging.cron), renamed for prod. The gate4
# replication check compares against a second DB that does not exist here, so it is dropped.
sed -e 's#/opt/nidp-staging#/opt/nidp#g' \
    -e 's#nidp-staging#nidp#g' \
    -e 's#NIDP STAGING#NIDP PRODUCTION#g' \
    "${REPO_DIR}/deploy/cloudpe/nidp/nidp-staging.cron" \
    | grep -v 'gate4_replication_check' > "$STAGED_CRON"
chown "$SVC_USER":"$SVC_USER" "$STAGED_CRON"; chmod 644 "$STAGED_CRON"
active=$(grep -cvE '^\s*(#|$|[A-Z_]+=)' "$STAGED_CRON" || true)
if $INSTALL_CRON || [[ -f "$CRON_DST" ]]; then
    # Feeds (reconciler, DLQ re-drive) must not be pointed at an empty or half-restored database.
    applied=$(docker exec nidp-postgres psql -U "$PG_USER" -d "$PG_DB" -At \
                -c "SELECT count(*) FROM nidp.schema_migrations;" 2>/dev/null || echo 0)
    (( applied > 0 )) || fail "nidp.schema_migrations is empty or missing — restore or --migrate before installing cron."
    install -m 644 -o root -g root "$STAGED_CRON" "$CRON_DST"
    log "Installed ${CRON_DST} (${active} active entries)."
else
    warn "${CRON_DST} not installed — feeds are NOT scheduled (${active} entries staged in ${STAGED_CRON}). Re-run with --install-cron when ready."
fi

log "Done."
dc ps
systemctl --no-pager --lines=0 status nidp-query-api || true
