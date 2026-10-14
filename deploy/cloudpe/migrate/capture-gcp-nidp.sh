#!/usr/bin/env bash
# capture-gcp-nidp.sh — capture the NIDP STAGING state on the GCP NIDP VM into
# a bundle that deploy/cloudpe/nidp/{bootstrap,restore}.sh consume.
#
# Run as root on the GCP NIDP VM (nidp-stack-vm). Copy the whole deploy/cloudpe/
# directory there first — this script sources ../lib.
#
#   sudo bash capture-gcp-nidp.sh --out DIR
#   sudo bash capture-gcp-nidp.sh --stream-to user@host:/abs/dir
#
#   --out DIR         write the bundle into DIR (must be empty or not exist)
#   --stream-to DEST  pipe every artifact over ssh to DEST instead of writing
#                     it here — use this when the local disk is nearly full.
#                     The remote directory must be empty or not exist.
#   --with-raw        also capture /opt/nidp-staging/raw_archives (its size is
#                     always reported; it is only archived with this flag)
#
# Exactly one of --out / --stream-to is required.
#
# Env: CAPTURE_SSH_OPTS  extra ssh options for --stream-to (word-split), e.g.
#        CAPTURE_SSH_OPTS="-i /root/.ssh/cloudpe -o ControlMaster=auto -o ControlPath=/root/.ssh/cm-%C -o ControlPersist=60"
#      ssh runs as root here, so the key must be readable by root (or keep
#      your agent with `sudo --preserve-env=SSH_AUTH_SOCK`).
#
# READ-ONLY against the source: pg_dump, SELECTs and file reads. Nothing is
# stopped, restarted or modified, and no secret value is printed. The bundle
# itself CONTAINS secrets (nidp.env, query_api.env, TLS key) — it is written
# mode 700/600; keep it that way.

set -euo pipefail

TAG="capture-nidp"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../lib/common.sh
source "${HERE}/../lib/common.sh"
# shellcheck source=../lib/counts.sh
source "${HERE}/../lib/counts.sh"

NIDP_HOME="/opt/nidp-staging"
ENV_FILE="${NIDP_HOME}/nidp.env"
VENV="${NIDP_HOME}/venv"
RAW_DIR="${NIDP_HOME}/raw_archives"
PG_DATA_DIR="${NIDP_HOME}/data/postgres"
DEV_REPO="/opt/nidp/dev-repo/nivesh.ai"
PG_CONTAINER="nidp-postgres-staging"
QUERY_UNIT="nidp-staging-query-api"

OUT_DIR=""
STREAM_TO=""
WITH_RAW=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --out)       OUT_DIR="${2:-}"; shift 2 ;;
        --stream-to) STREAM_TO="${2:-}"; shift 2 ;;
        --with-raw)  WITH_RAW=true; shift ;;
        -h|--help)   sed -n '2,/^$/p' "$0"; exit 0 ;;
        *)           fail "Unknown argument: $1" ;;
    esac
done

if [[ -n "$OUT_DIR" && -n "$STREAM_TO" ]] || [[ -z "$OUT_DIR" && -z "$STREAM_TO" ]]; then
    fail "Exactly one of --out DIR / --stream-to user@host:/abs/dir is required."
fi

require_root
umask 077
command -v docker >/dev/null 2>&1 || fail "docker not found — is this the GCP NIDP VM?"

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
# (pg_dump, tar) or a failing ssh fails the whole script.
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
[[ -r "$ENV_FILE" ]] || warn "Cannot read ${ENV_FILE} — using the default DB user/name; the bundle will have no config/nidp.env."
PG_USER=$(env_get NIDP_PG_USER "$ENV_FILE"); PG_USER="${PG_USER:-nidp_staging}"
PG_DB=$(env_get NIDP_PG_DB "$ENV_FILE");     PG_DB="${PG_DB:-nidp_staging}"

docker ps --format '{{.Names}}' | grep -qx "$PG_CONTAINER" \
    || fail "Container ${PG_CONTAINER} is not running — nothing to dump."

psql_val() {        # <sql> — single value, read-only
    docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -At -v ON_ERROR_STOP=1 -c "$1"
}
ext_version() {     # <extension-name> — empty if not installed
    psql_val "SELECT extversion FROM pg_extension WHERE extname = '$1';" | tr -d '[:space:]'
}

CAPTURED_AT=$(date -Iseconds)
SOURCE_HOST=$(hostname)
PG_VERSION=$(psql_val "SHOW server_version;")
DB_SIZE_BYTES=$(psql_val "SELECT pg_database_size(current_database());")
[[ "$DB_SIZE_BYTES" =~ ^[0-9]+$ ]] || fail "Could not read the size of database ${PG_DB}."
TSDB_VERSION=$(ext_version timescaledb)
# The restore pins the image to "<TSDB_VERSION>-pg16"; a bundle without it is unusable.
[[ -n "$TSDB_VERSION" ]] || fail "timescaledb extension not found in ${PG_DB} — cannot record TSDB_VERSION."
PGVECTOR_VERSION=$(ext_version vector)
POSTGRES_FDW_VERSION=$(ext_version postgres_fdw)
[[ -n "$PGVECTOR_VERSION" ]]     || warn "pgvector (extension 'vector') is not installed in ${PG_DB}."
[[ -n "$POSTGRES_FDW_VERSION" ]] || warn "postgres_fdw is not installed in ${PG_DB}."
[[ "$PG_VERSION" == 16.* ]] || warn "Postgres is ${PG_VERSION}, not 16.x — the CloudPe image tag <TSDB_VERSION>-pg16 will not match."

PYTHON_VERSION=""
if [[ -x "${VENV}/bin/python" ]]; then
    PYTHON_VERSION=$(PYTHONDONTWRITEBYTECODE=1 "${VENV}/bin/python" -c 'import platform; print(platform.python_version())' 2>/dev/null) || PYTHON_VERSION=""
fi
[[ -n "$PYTHON_VERSION" ]] || warn "Could not determine the venv Python version (${VENV}/bin/python)."
GIT_HEAD=$(git -c "safe.directory=${DEV_REPO}" -C "$DEV_REPO" rev-parse HEAD 2>/dev/null) || GIT_HEAD=""

log "Source: ${SOURCE_HOST}  postgres=${PG_VERSION} timescaledb=${TSDB_VERSION} db=${PG_DB} ($(( DB_SIZE_BYTES / 1048576 )) MiB)"

# Not captured, only reported: where the live data directory really lives.
if [[ -L "$PG_DATA_DIR" ]]; then
    log "${PG_DATA_DIR} is a SYMLINK → $(readlink -f "$PG_DATA_DIR" 2>/dev/null || readlink "$PG_DATA_DIR")"
elif [[ -d "$PG_DATA_DIR" ]]; then
    log "${PG_DATA_DIR} is a real directory (not a symlink)."
else
    warn "${PG_DATA_DIR} does not exist."
fi
if [[ -e "$PG_DATA_DIR" ]]; then
    log "  filesystem: $(timeout 15 df -PT "$PG_DATA_DIR" 2>/dev/null | awk 'NR==2{print $1" ("$2")"}' || true)"
fi

RAW_BYTES=0
if [[ -d "$RAW_DIR" ]]; then
    log "Raw archives: $(du -sh "$RAW_DIR" | cut -f1) in ${RAW_DIR}"
    if $WITH_RAW; then
        RAW_BYTES=$(du -sb "$RAW_DIR" | cut -f1)
    else
        log "  not captured (re-run with --with-raw to include them as raw/raw_archives.tar.gz)."
    fi
else
    warn "${RAW_DIR} does not exist — no raw archives to capture."
    WITH_RAW=false
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

    # Dump size is roughly a quarter of the database; the raw archive tarball
    # (--with-raw only) is budgeted at its uncompressed size.
    NEED_BYTES=$(( DB_SIZE_BYTES / 4 + 1073741824 + RAW_BYTES ))
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
log "NOTE: nothing on this VM is stopped. Row counts are taken right after the dump; on tables"
log "      written during the capture (cron feeds) they can drift from the dump unless writers"
log "      are stopped first (your call — this script will not do it)."

# ── Postgres ─────────────────────────────────────────────────────────────────
# pg_dump of a TimescaleDB database warns on stderr about circular foreign keys
# on the hypertable/chunk catalogs. That is expected (the restore runs under
# timescaledb_pre_restore/post_restore); only a non-zero exit is a failure.
log "pg_dump ${PG_DB} (custom format) — this takes a while; circular-foreign-key WARNINGs below are expected..."
docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" \
    -Fc --no-owner --no-privileges | emit postgres/nidp_staging.dump
log "pg_dump finished."

log "Recording hypertables..."
docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -At -F $'\t' -v ON_ERROR_STOP=1 \
    -c "SELECT hypertable_schema || '.' || hypertable_name, num_chunks FROM timescaledb_information.hypertables ORDER BY 1;" \
    | LC_ALL=C sort | emit counts/hypertables.tsv
HYPERTABLE_COUNT=$(psql_val "SELECT count(*) FROM timescaledb_information.hypertables;")
log "Hypertables at the source: ${HYPERTABLE_COUNT}"

log "Counting Postgres rows (every table; several minutes on a large database)..."
pg_table_counts "$PG_CONTAINER" "$PG_USER" "$PG_DB" </dev/null | emit counts/postgres.tsv

# ── Raw archives (opt-in) ────────────────────────────────────────────────────
if $WITH_RAW; then
    log "Archiving ${RAW_DIR}..."
    tar_dir "$RAW_DIR" | emit raw/raw_archives.tar.gz
fi

# ── Config ───────────────────────────────────────────────────────────────────
log "Copying config..."
emit_file "$ENV_FILE" config/nidp.env

# The Query API unit and its service-specific EnvironmentFile (the one that is
# not nidp.env). `systemctl cat` includes drop-ins.
unit_path=$(systemctl show -p FragmentPath "$QUERY_UNIT" 2>/dev/null) || unit_path=""
unit_path="${unit_path#FragmentPath=}"
if [[ -n "$unit_path" && -f "$unit_path" ]]; then
    emit_file "$unit_path" "config/${QUERY_UNIT}.service"
else
    warn "systemd unit ${QUERY_UNIT} not found — bundle will have no config/${QUERY_UNIT}.service."
fi

query_env=""
extra_envs=0
while IFS= read -r envf; do
    envf="${envf#-}"
    [[ -n "$envf" && "$(basename "$envf")" != "nidp.env" ]] || continue
    if [[ -z "$query_env" ]]; then query_env="$envf"; else extra_envs=$((extra_envs + 1)); fi
done < <(systemctl cat "$QUERY_UNIT" 2>/dev/null | sed -n 's/^[[:space:]]*EnvironmentFile=[[:space:]]*//p' || true)
if [[ -n "$query_env" ]]; then
    (( extra_envs == 0 )) || warn "${QUERY_UNIT} has ${extra_envs} more EnvironmentFile(s) besides ${query_env}; only the first is captured."
    emit_file "$query_env" config/query_api.env
else
    warn "${QUERY_UNIT} has no EnvironmentFile other than nidp.env — bundle will have no config/query_api.env."
fi

emit_file /etc/cron.d/nidp-staging                 config/cron/nidp-staging
emit_file "${NIDP_HOME}/run_service.sh"            config/run_service.sh
emit_file /etc/nginx/sites-available/nidp-staging  config/nginx/nidp-staging
emit_file /etc/nginx/ssl/data.crt                  config/ssl/data.crt
emit_file /etc/nginx/ssl/data.key                  config/ssl/data.key

# The live venv has packages that are not in requirements.txt; bootstrap.sh
# reinstalls from this list.
if [[ -x "${VENV}/bin/pip" ]] \
        && freeze=$(PYTHONDONTWRITEBYTECODE=1 "${VENV}/bin/pip" --disable-pip-version-check --no-cache-dir freeze 2>/dev/null) \
        && [[ -n "$freeze" ]]; then
    printf '%s\n' "$freeze" | emit config/pip-freeze.txt
else
    warn "pip freeze failed or ${VENV}/bin/pip is missing — bundle will have no config/pip-freeze.txt."
fi

# ── Metadata ─────────────────────────────────────────────────────────────────
{
    echo "CAPTURED_AT=${CAPTURED_AT}"
    echo "SOURCE_HOST=${SOURCE_HOST}"
    echo "PG_VERSION=${PG_VERSION}"
    echo "TSDB_VERSION=${TSDB_VERSION}"
    echo "PGVECTOR_VERSION=${PGVECTOR_VERSION}"
    echo "POSTGRES_FDW_VERSION=${POSTGRES_FDW_VERSION}"
    echo "DB_SIZE_BYTES=${DB_SIZE_BYTES}"
    echo "HYPERTABLE_COUNT=${HYPERTABLE_COUNT}"
    echo "PYTHON_VERSION=${PYTHON_VERSION}"
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
  1. Copy the bundle to the CloudPe NIDP VM, e.g.
       rsync -a --chmod=D700,F600 ${OUT_DIR}/ root@<cloudpe-nidp-vm>:/root/nidp-bundle/
  2. On the CloudPe NIDP VM:
       sudo bash deploy/cloudpe/nidp/bootstrap.sh --bundle /root/nidp-bundle
       sudo bash deploy/cloudpe/nidp/restore.sh /root/nidp-bundle
EOF
else
    log "Verifying the bundle on ${REMOTE_HOST} against its manifest..."
    remote_run "cd '${REMOTE_DIR}' && sha256sum --quiet -c MANIFEST.sha256" </dev/null \
        || fail "Bundle checksum mismatch on ${REMOTE_HOST}:${REMOTE_DIR}."
    COMPLETE=true
    log "Bundle: ${REMOTE_HOST}:${REMOTE_DIR}"
    cat <<EOF

[${TAG}] Capture finished. The bundle contains secrets — keep it mode 700/600.

Next, on the CloudPe NIDP VM (bundle is at ${REMOTE_DIR} on ${REMOTE_HOST}):
       sudo bash deploy/cloudpe/nidp/bootstrap.sh --bundle ${REMOTE_DIR}
       sudo bash deploy/cloudpe/nidp/restore.sh ${REMOTE_DIR}
EOF
fi
