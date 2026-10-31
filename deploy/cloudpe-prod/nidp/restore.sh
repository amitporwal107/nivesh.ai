#!/usr/bin/env bash
# restore.sh — load a pg_dump -Fc archive of the NIDP warehouse into the prod TimescaleDB.
#
#   sudo bash restore.sh <dump-file> [--force] [--jobs N]
#
# <dump-file> must be inside /opt/nidp/dumps (mounted read-only at /dumps in the container).
# Used for the first load, which was a fresh `pg_dump -Fc` of the staging warehouse:
#   docker exec nidp-postgres-staging pg_dump -U nidp_staging -d nidp_staging -Fc --compress=zstd:3
# streamed to /opt/nidp/dumps/ on this VM.
#
# Refuses a database that already has tables unless --force is given; --force DROPS the
# existing database first.
#
# This is not a plain pg_restore. The source has hypertables whose chunk tables live under
# _timescaledb_internal; replaying that DDL with the extension active produces duplicate-chunk
# and catalog errors. The supported path is
#     SELECT timescaledb_pre_restore();  pg_restore ...;  SELECT timescaledb_post_restore();
# against the SAME TimescaleDB version the dump came from (the image tag is pinned in cloudpe.env).
# Same procedure as deploy/cloudpe/nidp/restore.sh (staging).
#
# Run after bootstrap.sh and before the first `deploy-nidp.sh --install-cron`.

set -euo pipefail

TAG="prod-nidp-restore"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../lib.sh
source "${HERE}/../lib.sh"

PG_CONTAINER="nidp-postgres"
DUMPS_DIR="${NIDP_ROOT}/dumps"

DUMP=""
FORCE=false
JOBS=2
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)   FORCE=true; shift ;;
        --jobs)    JOBS="$2"; shift 2 ;;
        -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
        --*)       fail "Unknown flag: $1" ;;
        *)         DUMP="$1"; shift ;;
    esac
done
[[ -n "$DUMP" && -s "$DUMP" ]] || fail "usage: $0 <dump-file> [--force] [--jobs N]"
DUMP="$(readlink -f "$DUMP")"
[[ "$DUMP" == "${DUMPS_DIR}/"* ]] || fail "Dump must be inside ${DUMPS_DIR} (it is mounted at /dumps in the container)."
IN_CONTAINER="/dumps/${DUMP#"${DUMPS_DIR}/"}"

require_root
[[ -f "$NIDP_ENV_FILE" ]] || fail "Missing ${NIDP_ENV_FILE}."
PG_USER=$(env_get NIDP_PG_USER "$NIDP_ENV_FILE"); PG_USER="${PG_USER:-nidp}"
PG_DB=$(env_get NIDP_PG_DB "$NIDP_ENV_FILE");     PG_DB="${PG_DB:-nidp}"

psql_db()    { docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 "$@"; }
psql_admin() { docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 "$@"; }

docker exec "$PG_CONTAINER" pg_isready -U "$PG_USER" -d "$PG_DB" >/dev/null \
    || fail "${PG_CONTAINER} is not accepting connections. Run deploy-nidp.sh (or compose up postgres) first."

# ── Stop writers ─────────────────────────────────────────────────────────────
log "Stopping DaaS API, Query API and cron feeds (if present)..."
docker stop nidp-daas-api >/dev/null 2>&1 || true
systemctl stop nidp-query-api 2>/dev/null || true
if [[ -f /etc/cron.d/nidp ]]; then
    rm -f /etc/cron.d/nidp
    warn "Removed /etc/cron.d/nidp — re-enable with: deploy-nidp.sh --install-cron"
fi

# ── Target must be empty ─────────────────────────────────────────────────────
existing=$(psql_db -At -c "SELECT count(*) FROM information_schema.tables
                           WHERE table_type='BASE TABLE'
                             AND table_schema !~ '^(pg_|_timescaledb_|timescaledb_|information_schema\$)';")
if (( existing > 0 )) && ! $FORCE; then
    fail "Database ${PG_DB} already has ${existing} tables. Re-run with --force to DROP and replace it."
fi

# ── Archive sanity ───────────────────────────────────────────────────────────
for ext in timescaledb vector postgres_fdw; do
    [[ -n "$(psql_db -At -c "SELECT 1 FROM pg_available_extensions WHERE name='${ext}';")" ]] \
        || fail "Extension ${ext} is not available in this image; the dump needs it."
done
log "timescaledb $(psql_db -At -c "SELECT default_version FROM pg_available_extensions WHERE name='timescaledb';" | tr -d '[:space:]') available."
entries=$(docker exec "$PG_CONTAINER" pg_restore --list "$IN_CONTAINER" | grep -cE '^[0-9]+;' || true)
(( entries >= 10 )) || fail "Archive has only ${entries} TOC entries — looks empty or corrupt."
log "Archive has ${entries} TOC entries."

POST_NEEDED=false
cleanup() {
    # post_restore must run even if pg_restore dies, or the database is left with the extension off.
    if $POST_NEEDED; then
        POST_NEEDED=false
        log "timescaledb_post_restore()"
        psql_db -qAt -c "SELECT timescaledb_post_restore();" >/dev/null \
            || warn "timescaledb_post_restore() FAILED — the database may still be in restore mode."
    fi
}
trap cleanup EXIT

# ── Replace the database, create extensions ──────────────────────────────────
if (( existing > 0 )); then
    warn "--force: dropping database ${PG_DB} (${existing} tables)."
    psql_admin -c "DROP DATABASE \"${PG_DB}\" WITH (FORCE);" >/dev/null
    psql_admin -c "CREATE DATABASE \"${PG_DB}\" OWNER \"${PG_USER}\";" >/dev/null
fi
psql_db -qc "CREATE EXTENSION IF NOT EXISTS timescaledb;"
# pgvector backs document_chunks.embedding; postgres_fdw exists on the source.
psql_db -qc "CREATE EXTENSION IF NOT EXISTS vector;"
psql_db -qc "CREATE EXTENSION IF NOT EXISTS postgres_fdw;"

# ── Restore ──────────────────────────────────────────────────────────────────
log "timescaledb_pre_restore()"
psql_db -qAt -c "SELECT timescaledb_pre_restore();" >/dev/null
POST_NEEDED=true

# Mode 600: failed statements are logged verbatim.
RESTORE_LOG="${NIDP_ROOT}/logs/pg_restore_$(date +%Y%m%d_%H%M%S).log"
( umask 077; : > "$RESTORE_LOG" )
log "pg_restore --jobs ${JOBS} (log: ${RESTORE_LOG}) — this takes a while..."
# No --exit-on-error: a TimescaleDB restore legitimately reports some errors (objects the
# extension already owns). The pass/fail is the verification below.
set +e
docker exec "$PG_CONTAINER" pg_restore -U "$PG_USER" -d "$PG_DB" \
    --no-owner --no-privileges --jobs "$JOBS" "$IN_CONTAINER" > "$RESTORE_LOG" 2>&1
RESTORE_RC=$?
set -e
log "pg_restore exit code ${RESTORE_RC}; $(grep -c 'error:' "$RESTORE_LOG" || true) error lines logged."

POST_NEEDED=false
log "timescaledb_post_restore()"
psql_db -qAt -c "SELECT timescaledb_post_restore();" >/dev/null \
    || fail "timescaledb_post_restore() failed — the database is still in restore mode."
log "ANALYZE..."
psql_db -qc "ANALYZE;" || warn "ANALYZE failed (statistics will fill in over time)."

log "Hypertables restored: $(psql_db -At -c "SELECT count(*) FROM timescaledb_information.hypertables;")"
log "Restore finished. Compare row counts with the source before enabling cron."
log "Next: sudo bash ${HERE}/../deploy-nidp.sh <branch> --install-cron"
