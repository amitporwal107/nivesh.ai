#!/usr/bin/env bash
# capture-gcp-app.sh — capture the Nivesh app STAGING state on the GCP app VM
# into a bundle that deploy/cloudpe/app/{bootstrap,restore}.sh consume.
#
# Run as root on the GCP app VM (nivesh-app-vm). Copy the whole deploy/cloudpe/
# directory there first — this script sources ../lib.
#
#   sudo bash capture-gcp-app.sh --out DIR
#   sudo bash capture-gcp-app.sh --stream-to user@host:/abs/dir
#
#   --out DIR         write the bundle into DIR (must be empty or not exist)
#   --stream-to DEST  pipe every artifact over ssh to DEST instead of writing
#                     it here — use this when the local disk is nearly full.
#                     The remote directory must be empty or not exist.
#   --no-app-data     skip /opt/nivesh-staging/data/app
#
# Exactly one of --out / --stream-to is required.
#
# Env: CAPTURE_SSH_OPTS  extra ssh options for --stream-to (word-split), e.g.
#        CAPTURE_SSH_OPTS="-i /root/.ssh/cloudpe -o ControlMaster=auto -o ControlPath=/root/.ssh/cm-%C -o ControlPersist=60"
#      ssh runs as root here, so the key must be readable by root (or keep
#      your agent with `sudo --preserve-env=SSH_AUTH_SOCK`).
#
# READ-ONLY against the source: pg_dump, mongodump, SELECTs and file reads.
# Nothing is stopped, restarted or modified, and no secret value is printed.
# The bundle itself CONTAINS secrets (.env.staging, TLS key) — it is written
# mode 700/600; keep it that way.

set -euo pipefail

TAG="capture-app"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../lib/common.sh
source "${HERE}/../lib/common.sh"
# shellcheck source=../lib/counts.sh
source "${HERE}/../lib/counts.sh"

STAGING_ROOT="/opt/nivesh-staging"
ENV_FILE="${STAGING_ROOT}/.env.staging"
APP_DATA_DIR="${STAGING_ROOT}/data/app"
REPO_DIR="${STAGING_ROOT}/repo"
SSL_SRC="/opt/nivesh/ssl"
PG_CONTAINER="nivesh-staging-postgres"
MONGO_CONTAINER="nivesh-staging-mongo"

OUT_DIR=""
STREAM_TO=""
WITH_APP_DATA=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --out)         OUT_DIR="${2:-}"; shift 2 ;;
        --stream-to)   STREAM_TO="${2:-}"; shift 2 ;;
        --no-app-data) WITH_APP_DATA=false; shift ;;
        -h|--help)     sed -n '2,/^$/p' "$0"; exit 0 ;;
        *)             fail "Unknown argument: $1" ;;
    esac
done

if [[ -n "$OUT_DIR" && -n "$STREAM_TO" ]] || [[ -z "$OUT_DIR" && -z "$STREAM_TO" ]]; then
    fail "Exactly one of --out DIR / --stream-to user@host:/abs/dir is required."
fi

require_root
umask 077
command -v docker >/dev/null 2>&1 || fail "docker not found — is this the GCP app VM?"

# ── Bundle writer ────────────────────────────────────────────────────────────
# Every artifact goes through emit(), which writes it (locally or over ssh) and
# checksums the same stream, so nothing is read twice and nothing needs local
# scratch space. Only the manifest (a few KB) is staged locally.

SAFE_PATH_RE='^[A-Za-z0-9._/@+-]+$'
SSH_OPTS="${CAPTURE_SSH_OPTS:-}"
REMOTE_HOST=""
REMOTE_DIR=""
LAST_HASH=""
COMPLETE=false

WORK=$(mktemp -d)
MANIFEST="${WORK}/MANIFEST.sha256"
: > "$MANIFEST"
on_exit() {
    rm -rf "$WORK"
    $COMPLETE || warn "Capture did NOT complete — the bundle has no valid MANIFEST.sha256 and must not be used."
}
trap on_exit EXIT

remote_run() {      # <remote-command>  (stdin is whatever the caller provides)
    # shellcheck disable=SC2086  # CAPTURE_SSH_OPTS is word-split on purpose
    ssh $SSH_OPTS "$REMOTE_HOST" "$1"
}

# _write <relative-name> — store stdin as that artifact; sets LAST_HASH.
# The checksum is written to fd 3, which is the command substitution's pipe, so
# the substitution only returns once sha256sum has finished.
_write() {
    local rel="$1" dest hash
    [[ "$rel" =~ $SAFE_PATH_RE ]] || fail "Unsafe artifact name: ${rel}"
    if [[ -n "$OUT_DIR" ]]; then
        dest="${OUT_DIR}/${rel}"
        install -d -m 700 "$(dirname "$dest")"
        hash=$( { tee >(sha256sum >&3) > "$dest"; } 3>&1 ) \
            || fail "Writing ${dest} failed."
        chmod 600 "$dest"
    else
        dest="${REMOTE_DIR}/${rel}"
        # ssh gets fd 3 closed so a persistent ControlMaster cannot hold the pipe open.
        hash=$( { tee >(sha256sum >&3) \
                    | remote_run "umask 077; mkdir -p '$(dirname "$dest")' && cat > '${dest}'" >&2 3>&-; } 3>&1 ) \
            || fail "Streaming ${rel} to ${REMOTE_HOST} failed."
    fi
    hash="${hash%% *}"
    [[ "$hash" =~ ^[0-9a-f]{64}$ ]] || fail "Could not checksum ${rel}."
    LAST_HASH="$hash"
}

# emit <relative-name> — artifact on stdin; written and recorded in the manifest.
# Usable as the last stage of a pipeline: with pipefail, a failing producer
# (pg_dump, mongodump, tar) or a failing ssh fails the whole script.
emit() {
    _write "$1"
    printf '%s  %s\n' "$LAST_HASH" "$1" >> "$MANIFEST"
    log "  + $1"
}

# emit_file <source-path> <relative-name> — optional input: missing is a warning.
emit_file() {
    if [[ -f "$1" && -r "$1" ]]; then
        emit "$2" < "$1"
    else
        warn "Not found, skipped: $1 (bundle will have no $2)"
    fi
}

# tar_dir <dir> — gzip'd tar of the directory on stdout. The source keeps
# running, so "file changed as we read it" (tar exit 1) is only a warning.
tar_dir() {
    local rc=0
    tar -czf - -C "$1" . || rc=$?
    if (( rc == 1 )); then
        warn "tar: some files under $1 changed while being read."
    elif (( rc != 0 )); then
        return "$rc"
    fi
}

# ── Source checks ────────────────────────────────────────────────────────────
[[ -r "$ENV_FILE" ]] || fail "Cannot read ${ENV_FILE} — is this the GCP app VM?"
PG_USER=$(env_get PI_POSTGRES_USER "$ENV_FILE")
PG_DB=$(env_get PI_POSTGRES_DB "$ENV_FILE")
MONGO_USER=$(env_get PI_MONGO_USER "$ENV_FILE")
MONGO_PW=$(env_get PI_MONGO_PASSWORD "$ENV_FILE")
[[ -n "$PG_USER" && -n "$PG_DB" && -n "$MONGO_USER" && -n "$MONGO_PW" ]] \
    || fail "PI_POSTGRES_USER / PI_POSTGRES_DB / PI_MONGO_USER / PI_MONGO_PASSWORD must be set in ${ENV_FILE}."

RUNNING=$(docker ps --format '{{.Names}}')
for c in "$PG_CONTAINER" "$MONGO_CONTAINER"; do
    grep -qx "$c" <<< "$RUNNING" || fail "Container ${c} is not running — nothing to dump."
done

psql_val() {        # <sql> — single value, read-only
    docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -At -v ON_ERROR_STOP=1 -c "$1"
}

CAPTURED_AT=$(date -Iseconds)
SOURCE_HOST=$(hostname)
PG_VERSION=$(psql_val "SHOW server_version;")
DB_SIZE_BYTES=$(psql_val "SELECT pg_database_size(current_database());")
[[ "$DB_SIZE_BYTES" =~ ^[0-9]+$ ]] || fail "Could not read the size of database ${PG_DB}."
MONGO_VERSION=$(docker exec "$MONGO_CONTAINER" mongod --version 2>/dev/null | sed -n 's/^db version v//p' | head -1) || true
[[ -n "$MONGO_VERSION" ]] || warn "Could not determine the MongoDB version."
GIT_HEAD=$(git -c "safe.directory=${REPO_DIR}" -C "$REPO_DIR" rev-parse HEAD 2>/dev/null) || GIT_HEAD=""

log "Source: ${SOURCE_HOST}  postgres=${PG_VERSION} db=${PG_DB} ($(( DB_SIZE_BYTES / 1048576 )) MiB)  mongo=${MONGO_VERSION:-unknown}"

APP_DATA_BYTES=0
if ! $WITH_APP_DATA; then
    log "--no-app-data: ${APP_DATA_DIR} will not be captured."
elif [[ -d "$APP_DATA_DIR" && -n "$(ls -A "$APP_DATA_DIR" 2>/dev/null)" ]]; then
    log "App data: $(du -sh "$APP_DATA_DIR" | cut -f1) in ${APP_DATA_DIR}"
    APP_DATA_BYTES=$(du -sb "$APP_DATA_DIR" | cut -f1)
else
    warn "${APP_DATA_DIR} is missing or empty — no data/app.tar.gz will be captured."
    WITH_APP_DATA=false
fi

# ── Destination ──────────────────────────────────────────────────────────────
if [[ -n "$OUT_DIR" ]]; then
    if [[ -e "$OUT_DIR" && -n "$(ls -A "$OUT_DIR" 2>/dev/null)" ]]; then
        fail "${OUT_DIR} is not empty — use a fresh directory so stale files cannot end up in the bundle."
    fi
    install -d -m 700 "$OUT_DIR"
    chmod 700 "$OUT_DIR"
    OUT_DIR="$(cd "$OUT_DIR" && pwd)"
    [[ "$OUT_DIR" =~ $SAFE_PATH_RE ]] || fail "Unsupported characters in --out path: ${OUT_DIR}"

    # Dump size is roughly a quarter of the database; the app data tarball is
    # budgeted at its uncompressed size.
    NEED_BYTES=$(( DB_SIZE_BYTES / 4 + 1073741824 + APP_DATA_BYTES ))
    FREE_BYTES=$(( $(df -Pk "$OUT_DIR" | awk 'NR==2{print $4}') * 1024 ))
    log "Free space at ${OUT_DIR}: $(( FREE_BYTES / 1048576 )) MiB (need $(( NEED_BYTES / 1048576 )) MiB)"
    (( FREE_BYTES >= NEED_BYTES )) \
        || fail "Not enough free space at ${OUT_DIR}. Do not fill this disk — re-run with --stream-to user@host:/abs/dir."
    BUNDLE_DESC="$OUT_DIR"
else
    REMOTE_HOST="${STREAM_TO%%:*}"
    REMOTE_DIR="${STREAM_TO#*:}"
    [[ "$STREAM_TO" == *:/* && -n "$REMOTE_HOST" ]] || fail "--stream-to must be user@host:/abs/dir (got: ${STREAM_TO})"
    REMOTE_DIR="${REMOTE_DIR%/}"
    [[ -n "$REMOTE_DIR" && "$REMOTE_DIR" =~ $SAFE_PATH_RE ]] \
        || fail "Unsupported remote directory: ${REMOTE_DIR:-/} (allowed: letters, digits, . _ / @ + -)"
    command -v ssh >/dev/null 2>&1 || fail "ssh not found."
    log "Checking ${REMOTE_HOST}:${REMOTE_DIR} ..."
    remote_entries=$(remote_run "umask 077; mkdir -p '${REMOTE_DIR}' && chmod 700 '${REMOTE_DIR}' && ls -A '${REMOTE_DIR}' | wc -l" </dev/null) \
        || fail "Cannot reach ${REMOTE_HOST} or create ${REMOTE_DIR} (ssh options come from CAPTURE_SSH_OPTS)."
    [[ "${remote_entries//[[:space:]]/}" == "0" ]] \
        || fail "${REMOTE_HOST}:${REMOTE_DIR} is not empty — use a fresh directory so stale files cannot end up in the bundle."
    BUNDLE_DESC="${REMOTE_HOST}:${REMOTE_DIR}"
fi

log "Capturing to ${BUNDLE_DESC}"
log "NOTE: nothing on this VM is stopped. Row/document counts are taken right after each dump;"
log "      on tables written during the capture they can drift from the dump unless writers are"
log "      stopped first (your call — this script will not do it)."

# ── Postgres ─────────────────────────────────────────────────────────────────
log "pg_dump ${PG_DB} (custom format)..."
docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" \
    -Fc --no-owner --no-privileges | emit postgres/app.dump
log "Counting Postgres rows..."
pg_table_counts "$PG_CONTAINER" "$PG_USER" "$PG_DB" </dev/null | emit counts/postgres.tsv

# ── Mongo ────────────────────────────────────────────────────────────────────
# The credentials reach the container through the docker client's environment
# (`-e NAME` without a value), so they are not on this host's command line.
log "mongodump (all databases, gzip archive)..."
MONGO_U="$MONGO_USER" MONGO_PW="$MONGO_PW" \
    docker exec -e MONGO_U -e MONGO_PW "$MONGO_CONTAINER" \
    sh -c 'mongodump --quiet -u "$MONGO_U" -p "$MONGO_PW" --authenticationDatabase admin --archive --gzip' \
    | emit mongo/app.archive.gz
log "Counting Mongo documents..."
mongo_coll_counts "$MONGO_CONTAINER" "$MONGO_USER" "$MONGO_PW" </dev/null | emit counts/mongo.tsv

# ── App data ─────────────────────────────────────────────────────────────────
if $WITH_APP_DATA; then
    log "Archiving ${APP_DATA_DIR}..."
    tar_dir "$APP_DATA_DIR" | emit data/app.tar.gz
fi

# ── Config ───────────────────────────────────────────────────────────────────
log "Copying config..."
emit config/.env.staging < "$ENV_FILE"
emit_file "${SSL_SRC}/cert.pem" config/ssl/cert.pem
emit_file "${SSL_SRC}/key.pem"  config/ssl/key.pem

cron_found=0
shopt -s nullglob
for f in /etc/cron.d/nivesh-staging-*; do
    name=$(basename "$f")
    if [[ ! -f "$f" || ! "$name" =~ ^[A-Za-z0-9._-]+$ ]]; then
        warn "Skipping unexpected cron entry: ${f}"
        continue
    fi
    emit_file "$f" "config/cron/${name}"
    cron_found=$((cron_found + 1))
done
shopt -u nullglob
(( cron_found > 0 )) || warn "No /etc/cron.d/nivesh-staging-* files found."

# ── Metadata ─────────────────────────────────────────────────────────────────
{
    echo "CAPTURED_AT=${CAPTURED_AT}"
    echo "SOURCE_HOST=${SOURCE_HOST}"
    echo "PG_VERSION=${PG_VERSION}"
    echo "MONGO_VERSION=${MONGO_VERSION}"
    echo "DB_SIZE_BYTES=${DB_SIZE_BYTES}"
    echo "GIT_HEAD=${GIT_HEAD}"
} | emit meta/versions.env

# ── Manifest ─────────────────────────────────────────────────────────────────
_write MANIFEST.sha256 < "$MANIFEST"
log "  + MANIFEST.sha256 ($(wc -l < "$MANIFEST") artifacts)"

if [[ -n "$OUT_DIR" ]]; then
    log "Verifying the bundle against its manifest..."
    ( cd "$OUT_DIR" && sha256sum --quiet -c MANIFEST.sha256 ) || fail "Bundle checksum mismatch in ${OUT_DIR}."
    COMPLETE=true
    log "Bundle: ${OUT_DIR}"
    log "Total size: $(du -sh "$OUT_DIR" | cut -f1)"
    cat <<EOF

[${TAG}] Capture finished. The bundle contains secrets — move it over ssh only.

Next:
  1. Copy the bundle to the CloudPe app VM, e.g.
       rsync -a --chmod=D700,F600 ${OUT_DIR}/ root@<cloudpe-app-vm>:/root/app-bundle/
  2. On the CloudPe app VM:
       sudo bash deploy/cloudpe/app/bootstrap.sh --bundle /root/app-bundle
       sudo bash deploy/cloudpe/app/restore.sh /root/app-bundle
EOF
else
    log "Verifying the bundle on ${REMOTE_HOST} against its manifest..."
    remote_run "cd '${REMOTE_DIR}' && sha256sum --quiet -c MANIFEST.sha256" </dev/null \
        || fail "Bundle checksum mismatch on ${REMOTE_HOST}:${REMOTE_DIR}."
    COMPLETE=true
    log "Bundle: ${REMOTE_HOST}:${REMOTE_DIR}"
    cat <<EOF

[${TAG}] Capture finished. The bundle contains secrets — keep it mode 700/600.

Next, on the CloudPe app VM (bundle is at ${REMOTE_DIR} on ${REMOTE_HOST}):
       sudo bash deploy/cloudpe/app/bootstrap.sh --bundle ${REMOTE_DIR}
       sudo bash deploy/cloudpe/app/restore.sh ${REMOTE_DIR}
EOF
fi
