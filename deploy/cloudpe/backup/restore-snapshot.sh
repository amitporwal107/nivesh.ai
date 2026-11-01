#!/usr/bin/env bash
# restore-snapshot.sh — fetch, decrypt and restore a snapshot written by
# db-snapshot.sh.
#
# RUN THIS WHERE THE PRIVATE KEY IS (your laptop), not on the VMs: they hold
# only the public key and cannot decrypt their own backups. That is deliberate.
#
#   # 1. fetch + verify + decrypt (asks your GPG passphrase)
#   ./restore-snapshot.sh --target nidp --fetch --out ./snap
#
#   # 2. restore the decrypted archive into a Postgres container
#   ./restore-snapshot.sh --restore ./snap/nidp_staging_20261022.dump \
#       --container nidp-postgres-staging
#
#   --target app|nidp     which release tag to fetch (app-latest / nidp-latest; prod-* snapshots are local files)
#   --fetch               download the assets, check sha256, join parts, decrypt
#   --out DIR             where --fetch writes (default: ./db-snapshot-restore)
#   --restore FILE        pg_restore a decrypted .dump into --container
#   --container NAME      target Postgres container for --restore
#   --jobs N              parallel restore jobs (default 2)
#
# Env: SNAPSHOT_REPO, SNAPSHOT_GITHUB_TOKEN (or /etc/nivesh/db-snapshot.env).
#
# ⚠️  --restore DROPS AND RECREATES the target database's contents. It refuses
#     to run without --container and prints what it is about to overwrite.

set -euo pipefail

TAG="restore-snapshot"
log()  { printf '[%s] %s\n' "$TAG" "$*"; }
warn() { printf '[%s] WARN: %s\n' "$TAG" "$*" >&2; }
fail() { printf '[%s] FATAL: %s\n' "$TAG" "$*" >&2; exit 1; }

TARGET=""; DO_FETCH=false; OUT_DIR="./db-snapshot-restore"
RESTORE_FILE=""; PG_CONTAINER=""; JOBS=2

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)    TARGET="${2:-}"; shift 2 ;;
        --fetch)     DO_FETCH=true; shift ;;
        --out)       OUT_DIR="${2:-}"; shift 2 ;;
        --restore)   RESTORE_FILE="${2:-}"; shift 2 ;;
        --container) PG_CONTAINER="${2:-}"; shift 2 ;;
        --jobs)      JOBS="${2:-}"; shift 2 ;;
        -h|--help)   sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)           echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

$DO_FETCH || [[ -n "$RESTORE_FILE" ]] || { echo "nothing to do: pass --fetch and/or --restore (see --help)" >&2; exit 2; }

if [[ -r /etc/nivesh/db-snapshot.env ]]; then
    # shellcheck disable=SC1091
    set -a; source /etc/nivesh/db-snapshot.env; set +a
fi

# ── Fetch, verify, decrypt ───────────────────────────────────────────────────
if $DO_FETCH; then
    case "$TARGET" in
        app)  RELEASE_TAG="app-latest" ;;
        nidp) RELEASE_TAG="nidp-latest" ;;
        *)    fail "--fetch needs --target app|nidp" ;;
    esac
    : "${SNAPSHOT_REPO:?set SNAPSHOT_REPO}"
    : "${SNAPSHOT_GITHUB_TOKEN:?set SNAPSHOT_GITHUB_TOKEN}"
    for bin in curl jq gpg sha256sum; do
        command -v "$bin" >/dev/null 2>&1 || fail "${bin} not found."
    done

    mkdir -p "$OUT_DIR"; chmod 700 "$OUT_DIR"
    api() {
        local url="$1"; shift
        case "$url" in https://*) ;; *) url="https://api.github.com${url}" ;; esac
        curl -sS --fail-with-body --retry 3 -H "Authorization: Bearer ${SNAPSHOT_GITHUB_TOKEN}" \
            -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28" "$url" "$@"
    }
    log "release ${SNAPSHOT_REPO}@${RELEASE_TAG}"
    rel="$(api "/repos/${SNAPSHOT_REPO}/releases/tags/${RELEASE_TAG}")" \
        || fail "No release tagged ${RELEASE_TAG} in ${SNAPSHOT_REPO}."
    log "  taken: $(jq -r '.published_at' <<<"$rel")"

    mapfile -t ASSETS < <(jq -r '.assets[] | "\(.id)\t\(.name)\t\(.size)"' <<<"$rel")
    (( ${#ASSETS[@]} > 0 )) || fail "The release has no assets."

    for row in "${ASSETS[@]}"; do
        IFS=$'\t' read -r aid aname asize <<<"$row"
        log "  downloading ${aname} (${asize} bytes)"
        # The asset API needs Accept: octet-stream and follows a signed redirect
        # to a CDN host, which must NOT receive the Authorization header.
        curl -sS --fail-with-body --retry 3 -L --no-progress-meter \
            -H "Authorization: Bearer ${SNAPSHOT_GITHUB_TOKEN}" \
            -H "Accept: application/octet-stream" \
            -H "X-GitHub-Api-Version: 2022-11-28" \
            -o "${OUT_DIR}/${aname}" \
            "https://api.github.com/repos/${SNAPSHOT_REPO}/releases/assets/${aid}" \
            || fail "Download of ${aname} failed."
        got="$(stat -c %s "${OUT_DIR}/${aname}")"
        [[ "$got" == "$asize" ]] || fail "${aname}: got ${got} bytes, expected ${asize}."
    done

    manifest="$(ls -1 "${OUT_DIR}"/*.sha256 2>/dev/null | head -1 || true)"
    [[ -n "$manifest" ]] || fail "No .sha256 manifest in the release — cannot verify the payload."
    log "verifying checksums against $(basename "$manifest")"
    ( cd "$OUT_DIR" && sha256sum -c "$(basename "$manifest")" ) \
        || fail "Checksum mismatch — the download is corrupt, do not restore it."

    cipher="$(ls -1 "${OUT_DIR}"/*.dump.gpg 2>/dev/null | head -1 || true)"
    if [[ -z "$cipher" ]]; then
        first_part="$(ls -1 "${OUT_DIR}"/*.dump.gpg.part* 2>/dev/null | sort | head -1 || true)"
        [[ -n "$first_part" ]] || fail "No .dump.gpg or .dump.gpg.part* found."
        cipher="${first_part%.part*}"
        log "joining $(ls -1 "${OUT_DIR}"/*.dump.gpg.part* | wc -l) parts → $(basename "$cipher")"
        # Lexical order is the split order (split -d -a 2 → .part00, .part01…).
        cat $(ls -1 "${OUT_DIR}"/*.dump.gpg.part* | sort) > "$cipher"
    fi

    plain="${cipher%.gpg}"
    log "gpg --decrypt → $(basename "$plain")  (your private key + passphrase)"
    gpg --output "$plain" --decrypt "$cipher" || fail "Decryption failed."
    log "verifying the decrypted archive"
    entries="$(pg_restore --list "$plain" | grep -cE '^[0-9]+;' || true)"
    log "  TOC entries: ${entries}"
    (( entries >= 10 )) || fail "The decrypted archive lists only ${entries} entries."
    log "READY: ${plain}"
    [[ -n "$RESTORE_FILE" ]] || { log "Restore it with: $0 --restore ${plain} --container <name>"; exit 0; }
fi

# ── Restore ──────────────────────────────────────────────────────────────────
[[ -n "$RESTORE_FILE" ]] || exit 0
[[ -f "$RESTORE_FILE" ]] || fail "No such file: ${RESTORE_FILE}"
[[ -n "$PG_CONTAINER" ]] || fail "--restore needs --container NAME (refusing to guess which database to overwrite)."
command -v docker >/dev/null 2>&1 || fail "docker not found."
docker ps --format '{{.Names}}' | grep -qx "$PG_CONTAINER" || fail "Container ${PG_CONTAINER} is not running."

cenv() { docker inspect "$PG_CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n "s/^$1=//p" | head -1; }
PG_USER="$(cenv POSTGRES_USER)"; PG_DB="$(cenv POSTGRES_DB)"
[[ -n "$PG_USER" && -n "$PG_DB" ]] || fail "Could not read POSTGRES_USER/POSTGRES_DB from ${PG_CONTAINER}."
psql_db() { docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 "$@"; }

TSDB="$(psql_db -At -c "SELECT coalesce(max(extversion),'') FROM pg_extension WHERE extname='timescaledb';" | tr -d '[:space:]')"
cat <<EOF

  ⚠️  About to restore into a LIVE database.
      container : ${PG_CONTAINER}
      database  : ${PG_DB} ($(psql_db -At -c "SELECT pg_size_pretty(pg_database_size(current_database()));"))
      tables now: $(psql_db -At -c "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema') AND table_schema !~ '^(pg_|_timescaledb_|timescaledb_)';")
      archive   : ${RESTORE_FILE}
      timescaledb: ${TSDB:-none}

  Existing objects will be overwritten (pg_restore --clean --if-exists).
EOF
read -r -p "  Type the database name to continue: " confirm
[[ "$confirm" == "$PG_DB" ]] || fail "Not confirmed — nothing was changed."

# A parallel pg_restore needs a seekable file inside the container.
log "copying the archive into ${PG_CONTAINER}:/tmp/restore.dump"
docker cp "$RESTORE_FILE" "${PG_CONTAINER}:/tmp/restore.dump"
cleanup() { docker exec "$PG_CONTAINER" rm -f /tmp/restore.dump >/dev/null 2>&1 || true; }

# Restoring into a brand-new empty database (the disaster case): the archive came from a TimescaleDB
# database but the target has no extension yet, so pre/post_restore below would be skipped and the
# chunk tables would be replayed against nothing. Create it first, as Timescale's own procedure says.
if [[ -z "$TSDB" ]] && docker exec "$PG_CONTAINER" pg_restore --list /tmp/restore.dump 2>/dev/null | grep -q ' EXTENSION - timescaledb'; then
    log "the archive is from a TimescaleDB database and the target has no timescaledb extension — creating it"
    psql_db -qc "CREATE EXTENSION IF NOT EXISTS timescaledb;"
    TSDB="$(psql_db -At -c "SELECT coalesce(max(extversion),'') FROM pg_extension WHERE extname='timescaledb';" | tr -d '[:space:]')"
    log "  timescaledb ${TSDB} (the image must match the version the dump came from)"
fi

if [[ -n "$TSDB" ]]; then
    # Chunk DDL under _timescaledb_internal cannot be replayed with the
    # extension active; pre/post_restore brackets it. post_restore MUST run even
    # if pg_restore dies, or the database is left in restore mode.
    log "timescaledb_pre_restore()"
    psql_db -qAt -c "SELECT timescaledb_pre_restore();" >/dev/null
    restore_done() {
        psql_db -qAt -c "SELECT timescaledb_post_restore();" >/dev/null \
            || warn "timescaledb_post_restore() FAILED — the database may still be in restore mode."
        cleanup
    }
    trap restore_done EXIT
else
    trap cleanup EXIT
fi

log "pg_restore --jobs ${JOBS} (this takes a while)"
rc=0
docker exec "$PG_CONTAINER" pg_restore -U "$PG_USER" -d "$PG_DB" \
    --clean --if-exists --no-owner --no-privileges --jobs "$JOBS" \
    /tmp/restore.dump || rc=$?
log "pg_restore exit code ${rc} (non-zero with --clean is often only 'does not exist' notices)"

if [[ -n "$TSDB" ]]; then
    # A parallel pg_restore can lose the TimescaleDB chunk catalog: dimension_slice / chunk /
    # chunk_constraint have circular foreign keys, so their COPY fails. The chunk tables themselves
    # restore, but every hypertable then reads as EMPTY although the database is full size (seen on
    # 2026-10-31 restoring the 23 GB NIDP warehouse with --jobs 3). Compare, repair, and refuse to
    # call it restored if it still does not add up.
    catalog_counts() {
        CHUNKS="$(psql_db -At -c "SELECT count(*) FROM _timescaledb_catalog.chunk;")"
        PHYSICAL="$(psql_db -At -c "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='_timescaledb_internal' AND c.relname ~ '^_hyper_.*_chunk\$' AND c.relkind='r';")"
    }
    catalog_counts
    log "chunk catalog rows: ${CHUNKS}; physical chunk tables: ${PHYSICAL}"
    if (( CHUNKS != PHYSICAL )); then
        warn "catalog does not match — reloading _timescaledb_catalog.{dimension_slice,chunk,chunk_constraint} (data-only, triggers off)"
        docker exec "$PG_CONTAINER" pg_restore -U "$PG_USER" -d "$PG_DB" --data-only --disable-triggers --no-owner \
            -n _timescaledb_catalog -t dimension_slice -t chunk -t chunk_constraint /tmp/restore.dump || true
        catalog_counts
        log "after repair — chunk catalog rows: ${CHUNKS}; physical chunk tables: ${PHYSICAL}"
        (( CHUNKS == PHYSICAL )) || fail "chunk catalog (${CHUNKS}) still does not match the ${PHYSICAL} restored chunk tables — the hypertables would read as empty. NOT a usable restore."
    fi
fi

trap - EXIT
if [[ -n "$TSDB" ]]; then
    log "timescaledb_post_restore()"
    psql_db -qAt -c "SELECT timescaledb_post_restore();" >/dev/null \
        || fail "timescaledb_post_restore() failed — the database is still in restore mode."
fi
cleanup

log "post-restore state:"
psql_db -c "SELECT count(*) AS tables FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema') AND table_schema !~ '^(pg_|_timescaledb_|timescaledb_)';"
[[ -z "$TSDB" ]] || psql_db -c "SELECT hypertable_schema||'.'||hypertable_name AS hypertable, num_chunks FROM timescaledb_information.hypertables ORDER BY 1;"
log "DONE — verify the application against this database before calling it restored."
