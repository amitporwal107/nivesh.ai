#!/usr/bin/env bash
# restore.sh — load a GCP staging capture bundle into the CloudPe app VM.
#
#   sudo bash restore.sh <bundle-dir> [--force]
#
# Restores app Postgres, Mongo and /opt/nivesh-staging/data/app from a bundle
# produced by migrate/capture-gcp-app.sh, then compares row/document counts
# with the counts recorded at the source.
#
# Refuses to touch a store that already holds data unless --force is given;
# --force DROPS the existing Postgres database and Mongo collections first.
#
# Run after app/bootstrap.sh and before the first app/deploy.sh. Redis is a
# cache and is not migrated.

set -euo pipefail

TAG="app-restore"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../lib/common.sh
source "${HERE}/../lib/common.sh"
# shellcheck source=../lib/counts.sh
source "${HERE}/../lib/counts.sh"

STAGING_ROOT="/opt/nivesh-staging"
REPO_DIR="${STAGING_ROOT}/repo"
ENV_FILE="${STAGING_ROOT}/.env.staging"
BASE_COMPOSE="${REPO_DIR}/deploy/nivesh-staging/docker-compose.staging.yml"
OVERRIDE_COMPOSE="${REPO_DIR}/deploy/cloudpe/app/docker-compose.cloudpe.yml"
PG_CONTAINER="nivesh-staging-postgres"
MONGO_CONTAINER="nivesh-staging-mongo"

BUNDLE=""
FORCE=false
for arg in "$@"; do
    case "$arg" in
        --force)   FORCE=true ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        --*)       fail "Unknown flag: $arg" ;;
        *)         BUNDLE="$arg" ;;
    esac
done
[[ -n "$BUNDLE" && -d "$BUNDLE" ]] || fail "usage: $0 <bundle-dir> [--force]"
BUNDLE="$(cd "$BUNDLE" && pwd)"

require_root
[[ -f "$ENV_FILE" ]] || fail "Missing ${ENV_FILE}. Run app/bootstrap.sh first."
[[ -f "$OVERRIDE_COMPOSE" ]] || fail "Missing ${OVERRIDE_COMPOSE}. Run app/bootstrap.sh first."
verify_bundle "$BUNDLE"

PG_DUMP="${BUNDLE}/postgres/app.dump"
MONGO_ARCHIVE="${BUNDLE}/mongo/app.archive.gz"
APP_DATA_TAR="${BUNDLE}/data/app.tar.gz"
[[ -s "$PG_DUMP" ]]       || fail "Missing ${PG_DUMP}"
[[ -s "$MONGO_ARCHIVE" ]] || fail "Missing ${MONGO_ARCHIVE}"

PG_USER=$(env_get PI_POSTGRES_USER "$ENV_FILE")
PG_DB=$(env_get PI_POSTGRES_DB "$ENV_FILE")
MONGO_USER=$(env_get PI_MONGO_USER "$ENV_FILE")
MONGO_PW=$(env_get PI_MONGO_PASSWORD "$ENV_FILE")
[[ -n "$PG_USER" && -n "$PG_DB" && -n "$MONGO_USER" && -n "$MONGO_PW" ]] \
    || fail "PI_POSTGRES_USER / PI_POSTGRES_DB / PI_MONGO_USER / PI_MONGO_PASSWORD must be set in ${ENV_FILE}."

dc() { docker compose --env-file "$ENV_FILE" -f "$BASE_COMPOSE" -f "$OVERRIDE_COMPOSE" "$@"; }
psql_db()    { docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 "$@"; }
psql_admin() { docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 "$@"; }
mongo_eval() {
    MONGO_U="$MONGO_USER" MONGO_PW="$MONGO_PW" JS="$1" docker exec -e MONGO_U -e MONGO_PW -e JS "$MONGO_CONTAINER" \
        sh -c 'mongosh --quiet -u "$MONGO_U" -p "$MONGO_PW" --authenticationDatabase admin --eval "$JS"'
}

# ── Stop writers, start the data stores ──────────────────────────────────────
log "Stopping app containers (if running) so nothing writes during the restore..."
dc stop nginx app-frontend app-frontend-v5 app-backend >/dev/null 2>&1 || true
log "Starting postgres + mongo + redis..."
dc up -d postgres mongo redis
wait_container_healthy "$PG_CONTAINER" 60 2
wait_container_healthy "$MONGO_CONTAINER" 60 2

# ── Postgres ─────────────────────────────────────────────────────────────────
# Everything that can be checked is checked before anything is dropped.
log "Checking the Postgres archive is readable..."
entries=$(docker exec -i "$PG_CONTAINER" pg_restore --list < "$PG_DUMP" | grep -cE '^[0-9]+;' || true)
(( entries >= 10 )) || fail "Postgres archive has only ${entries} TOC entries — looks empty or corrupt."
log "Archive has ${entries} TOC entries."

existing=$(psql_db -At -c "SELECT count(*) FROM information_schema.tables
                           WHERE table_type='BASE TABLE'
                             AND table_schema NOT IN ('pg_catalog','information_schema');")
mongo_existing=$(mongo_eval '
    let n = 0;
    db.getMongo().getDBNames().filter(d => !["admin","config","local"].includes(d)).forEach(d => {
      n += db.getSiblingDB(d).getCollectionNames().filter(c => c !== "_init" && !c.startsWith("system.")).length;
    });
    print(n);' | tail -1)
if ! $FORCE; then
    (( existing == 0 )) || fail "Postgres database ${PG_DB} already has ${existing} tables. Re-run with --force to DROP and replace it."
    (( mongo_existing == 0 )) || fail "Mongo already has ${mongo_existing} collections. Re-run with --force to DROP and replace them."
fi

if (( existing > 0 )); then
    warn "--force: dropping database ${PG_DB} (${existing} tables)."
    psql_admin -c "DROP DATABASE \"${PG_DB}\" WITH (FORCE);" >/dev/null
    psql_admin -c "CREATE DATABASE \"${PG_DB}\" OWNER \"${PG_USER}\";" >/dev/null
fi

log "pg_restore → ${PG_DB}..."
docker exec -i "$PG_CONTAINER" pg_restore -U "$PG_USER" -d "$PG_DB" \
    --no-owner --no-privileges --exit-on-error < "$PG_DUMP"
log "pg_restore finished."

# ── Mongo ────────────────────────────────────────────────────────────────────
# admin/config/local are excluded: users on this instance come from this VM's
# own env + mongo-init.js, not from the source instance.
MONGO_DROP=()
if (( mongo_existing > 0 )); then
    warn "--force: existing Mongo collections present in the archive will be dropped."
    MONGO_DROP=(--drop)
fi

log "mongorestore..."
MONGO_U="$MONGO_USER" MONGO_PW="$MONGO_PW" docker exec -i -e MONGO_U -e MONGO_PW "$MONGO_CONTAINER" \
    sh -c 'mongorestore --quiet -u "$MONGO_U" -p "$MONGO_PW" --authenticationDatabase admin \
             --archive --gzip --nsExclude "admin.*" --nsExclude "config.*" --nsExclude "local.*" "$@"' \
    sh "${MONGO_DROP[@]}" < "$MONGO_ARCHIVE"
log "mongorestore finished."

# ── /app/data ────────────────────────────────────────────────────────────────
APP_DATA_DIR="${STAGING_ROOT}/data/app"
if [[ -s "$APP_DATA_TAR" ]]; then
    if [[ -n "$(ls -A "$APP_DATA_DIR" 2>/dev/null)" ]] && ! $FORCE; then
        fail "${APP_DATA_DIR} is not empty. Re-run with --force to overwrite files from the bundle."
    fi
    log "Extracting app data → ${APP_DATA_DIR}"
    tar -xzf "$APP_DATA_TAR" -C "$APP_DATA_DIR"
else
    log "No data/app.tar.gz in the bundle; skipping app data."
fi

# ── Verify against the source counts ─────────────────────────────────────────
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
rc=0

log "Counting restored Postgres rows..."
pg_table_counts "$PG_CONTAINER" "$PG_USER" "$PG_DB" > "${WORK}/postgres.tsv"
compare_counts "postgres" "${BUNDLE}/counts/postgres.tsv" "${WORK}/postgres.tsv" || rc=4

log "Counting restored Mongo documents..."
mongo_coll_counts "$MONGO_CONTAINER" "$MONGO_USER" "$MONGO_PW" > "${WORK}/mongo.tsv"
compare_counts "mongo" "${BUNDLE}/counts/mongo.tsv" "${WORK}/mongo.tsv" || rc=4

if (( rc != 0 )); then
    warn "Counts differ from the source. A small drift is expected if the source was still"
    warn "taking writes while it was captured; anything else needs investigating before deploy."
    exit "$rc"
fi
log "Restore complete and counts match. Next: sudo bash ${REPO_DIR}/deploy/cloudpe/app/deploy.sh"
