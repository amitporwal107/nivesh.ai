#!/usr/bin/env bash
# restore.sh — load the GCP nidp_staging dump into the CloudPe TimescaleDB.
#
#   sudo bash restore.sh <bundle-dir> [--force] [--jobs N]
#
# Takes a bundle produced by migrate/capture-gcp-nidp.sh, restores it, then
# compares hypertables and row counts with what was recorded at the source.
#
# Refuses a database that already has tables unless --force is given;
# --force DROPS the existing nidp_staging database first.
#
# This is not a plain pg_restore. The source has hypertables whose chunk tables
# live under _timescaledb_internal; replaying that DDL with the extension
# active produces duplicate-chunk and catalog errors. The supported path is
#     SELECT timescaledb_pre_restore();  pg_restore ...;  SELECT timescaledb_post_restore();
# against the SAME TimescaleDB version the dump came from. Same procedure as
# deploy/dev-laptops/laptop2-nidp/restore.sh.
#
# Run after nidp/bootstrap.sh and before the first nidp/deploy.sh.

set -euo pipefail

TAG="nidp-restore"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../lib/common.sh
source "${HERE}/../lib/common.sh"
# shellcheck source=../lib/counts.sh
source "${HERE}/../lib/counts.sh"

NIDP_HOME="/opt/nidp-staging"
ENV_FILE="${NIDP_HOME}/nidp.env"
DUMPS_DIR="${NIDP_HOME}/dumps"
PG_CONTAINER="nidp-postgres-staging"

BUNDLE=""
FORCE=false
# 2 is what deploy/dev-laptops/laptop2-nidp/restore.sh uses for this dump.
JOBS=2
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)   FORCE=true; shift ;;
        --jobs)    JOBS="$2"; shift 2 ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        --*)       fail "Unknown flag: $1" ;;
        *)         BUNDLE="$1"; shift ;;
    esac
done
[[ -n "$BUNDLE" && -d "$BUNDLE" ]] || fail "usage: $0 <bundle-dir> [--force] [--jobs N]"
BUNDLE="$(cd "$BUNDLE" && pwd)"

require_root
[[ -f "$ENV_FILE" ]] || fail "Missing ${ENV_FILE}. Run nidp/bootstrap.sh first."
verify_bundle "$BUNDLE"

DUMP="${BUNDLE}/postgres/nidp_staging.dump"
[[ -s "$DUMP" ]] || fail "Missing ${DUMP}"
EXPECTED_TSDB=$(env_get TSDB_VERSION "${BUNDLE}/meta/versions.env")
[[ -n "$EXPECTED_TSDB" ]] || fail "TSDB_VERSION missing from ${BUNDLE}/meta/versions.env"

PG_USER=$(env_get NIDP_PG_USER "$ENV_FILE"); PG_USER="${PG_USER:-nidp_staging}"
PG_DB=$(env_get NIDP_PG_DB "$ENV_FILE");     PG_DB="${PG_DB:-nidp_staging}"

psql_db()    { docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 "$@"; }
psql_admin() { docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 "$@"; }

docker exec "$PG_CONTAINER" pg_isready -U "$PG_USER" -d "$PG_DB" >/dev/null \
    || fail "${PG_CONTAINER} is not accepting connections. Run nidp/bootstrap.sh first."

# ── Stop writers ─────────────────────────────────────────────────────────────
log "Stopping DaaS API, Query API and cron feeds (if present)..."
docker stop nidp-daas-api-staging >/dev/null 2>&1 || true
systemctl stop nidp-staging-query-api 2>/dev/null || true
if [[ -f /etc/cron.d/nidp-staging ]]; then
    rm -f /etc/cron.d/nidp-staging
    warn "Removed /etc/cron.d/nidp-staging — re-enable with: deploy.sh --install-cron"
fi

# ── Target must be empty ─────────────────────────────────────────────────────
existing=$(psql_db -At -c "SELECT count(*) FROM information_schema.tables
                           WHERE table_type='BASE TABLE'
                             AND table_schema !~ '^(pg_|_timescaledb_|timescaledb_|information_schema\$)';")
if (( existing > 0 )) && ! $FORCE; then
    fail "Database ${PG_DB} already has ${existing} tables. Re-run with --force to DROP and replace it."
fi

# ── Versions (read-only — nothing is dropped until these and the archive pass) ─
AVAILABLE_TSDB=$(psql_db -At -c "SELECT default_version FROM pg_available_extensions WHERE name='timescaledb';" | tr -d '[:space:]')
if [[ "$AVAILABLE_TSDB" != "$EXPECTED_TSDB" ]]; then
    fail "TimescaleDB version mismatch: dump is from ${EXPECTED_TSDB}, this container ships ${AVAILABLE_TSDB:-none}.
       Set NIDP_TSDB_TAG=${EXPECTED_TSDB}-pg16 in ${NIDP_HOME}/cloudpe.env and recreate the container
       (on an EMPTY data directory), or take a fresh dump from a source running ${AVAILABLE_TSDB:-that version}."
fi
log "timescaledb ${AVAILABLE_TSDB} matches the source."
for ext in vector postgres_fdw; do
    [[ -n "$(psql_db -At -c "SELECT 1 FROM pg_available_extensions WHERE name='${ext}';")" ]] \
        || fail "Extension ${ext} is not available in this image; the dump needs it."
done

# ── Make the dump visible inside the container ───────────────────────────────
# A parallel pg_restore needs a seekable file, not stdin. ${DUMPS_DIR} is
# mounted at /dumps by the override compose file.
install -d -m 700 "$DUMPS_DIR"
IN_HOST="${DUMPS_DIR}/nidp_staging.dump"
STAGED=false
if [[ "$DUMP" != "$IN_HOST" ]]; then
    log "Staging dump → ${IN_HOST}"
    if ! ln -f "$DUMP" "$IN_HOST" 2>/dev/null; then
        need_kb=$(du -k "$DUMP" | cut -f1)
        free_kb=$(df -Pk "$DUMPS_DIR" | awk 'NR==2{print $4}')
        (( free_kb > need_kb + 1048576 )) || fail "Not enough free space in ${DUMPS_DIR} to copy the dump."
        cp -f "$DUMP" "$IN_HOST"
    fi
    STAGED=true
fi
WORK=$(mktemp -d)
POST_NEEDED=false
cleanup() {
    # post_restore must run even if pg_restore dies, or the database is left
    # with the extension switched off.
    if $POST_NEEDED; then
        POST_NEEDED=false
        log "timescaledb_post_restore()"
        psql_db -qAt -c "SELECT timescaledb_post_restore();" >/dev/null \
            || warn "timescaledb_post_restore() FAILED — the database may still be in restore mode."
    fi
    if $STAGED; then rm -f "$IN_HOST"; fi
    rm -rf "$WORK"
}
trap cleanup EXIT

docker exec "$PG_CONTAINER" test -r /dumps/nidp_staging.dump \
    || fail "/dumps/nidp_staging.dump is not readable inside ${PG_CONTAINER} — was it started with the CloudPe override?"

entries=$(docker exec "$PG_CONTAINER" pg_restore --list /dumps/nidp_staging.dump | grep -cE '^[0-9]+;' || true)
(( entries >= 10 )) || fail "Archive has only ${entries} TOC entries — looks empty or corrupt."
log "Archive has ${entries} TOC entries."

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

# Mode 600: failed statements are logged verbatim, and the dump carries a
# foreign-server user mapping.
RESTORE_LOG="${NIDP_HOME}/logs/pg_restore_$(date +%Y%m%d_%H%M%S).log"
( umask 077; : > "$RESTORE_LOG" )
log "pg_restore --jobs ${JOBS} (log: ${RESTORE_LOG}) — this takes a while..."
# No --exit-on-error: a TimescaleDB restore legitimately reports some errors
# (objects the extension already owns). The pass/fail is the verification below.
set +e
docker exec "$PG_CONTAINER" pg_restore -U "$PG_USER" -d "$PG_DB" \
    --no-owner --no-privileges --jobs "$JOBS" /dumps/nidp_staging.dump > "$RESTORE_LOG" 2>&1
RESTORE_RC=$?
set -e
log "pg_restore exit code ${RESTORE_RC}; $(grep -c 'error:' "$RESTORE_LOG" || true) error lines logged."

POST_NEEDED=false
log "timescaledb_post_restore()"
psql_db -qAt -c "SELECT timescaledb_post_restore();" >/dev/null \
    || fail "timescaledb_post_restore() failed — the database is still in restore mode."
log "ANALYZE..."
psql_db -qc "ANALYZE;" || warn "ANALYZE failed (statistics will fill in over time)."

# ── Verify against the source ────────────────────────────────────────────────
rc=0

psql_db -At -F $'\t' -c "SELECT hypertable_schema || '.' || hypertable_name, num_chunks
                         FROM timescaledb_information.hypertables ORDER BY 1;" \
    | LC_ALL=C sort > "${WORK}/hypertables.tsv"
log "Hypertables restored: $(wc -l < "${WORK}/hypertables.tsv")"
compare_counts "hypertables (name, chunks)" "${BUNDLE}/counts/hypertables.tsv" "${WORK}/hypertables.tsv" || rc=4

log "Counting restored rows (every table; several minutes on a large database)..."
pg_table_counts "$PG_CONTAINER" "$PG_USER" "$PG_DB" > "${WORK}/postgres.tsv"
compare_counts "postgres" "${BUNDLE}/counts/postgres.tsv" "${WORK}/postgres.tsv" || rc=4

if (( rc != 0 )); then
    warn "Restored data differs from the source record. A small drift on tables the feeds were"
    warn "writing during capture is expected; missing hypertables or tables are NOT — check ${RESTORE_LOG}."
    exit "$rc"
fi
log "Restore complete; hypertables and row counts match the source."
log "Next: sudo bash ${HERE}/deploy.sh dev --install-cron"
