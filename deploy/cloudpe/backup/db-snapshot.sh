#!/usr/bin/env bash
# db-snapshot.sh — weekly compressed PostgreSQL/TimescaleDB snapshot of a CloudPe
# staging VM, written to that VM's own disk.
#
# Runs as root, from cron, on EITHER VM. Self-contained on purpose: it sources
# nothing from the repo checkout, so a snapshot keeps working even when
# /opt/nidp/dev-repo or /opt/nivesh-staging/repo is mid-deploy or broken.
#
#   sudo bash db-snapshot.sh --target app      # nivesh-app-vm   45.64.105.88
#   sudo bash db-snapshot.sh --target nidp     # nidp-staging-vm 45.64.105.224
#   sudo bash db-snapshot.sh --target prod-nidp  # PRODUCTION warehouse, nivesh-prod-vm 45.64.105.249
#   sudo bash db-snapshot.sh --target prod-app   # PRODUCTION app Postgres, same VM
#   sudo bash db-snapshot.sh --target app --preflight   # checks only, no dump
#
# WHAT IT PRODUCES, in /opt/<stack>/dumps (mode 700, root-only):
#   <db>_<YYYYMMDD>.dump[.gpg]  pg_dump -Fc, explicitly compressed, schema AND
#                               data, the whole database
#   <db>_<YYYYMMDD>.sha256      checksum of the above
#
# RETENTION: latest only. Each run deletes the previous run's files once the new
# snapshot is complete and verified. There is no history — by design.
#
# DESTINATION: local disk. This VM only. Nothing is uploaded anywhere.
# SNAPSHOT_DESTINATION=github in the config switches on the GitHub release-asset
# path instead (see README.md §Publishing elsewhere); it is OFF by default and
# the user has deliberately not chosen it.
#
# Config: /etc/nivesh/db-snapshot.env (mode 600, NOT in git). All optional
# except as noted:
#   SNAPSHOT_COMPRESS       pg_dump compression, METHOD[:LEVEL] (default zstd:12)
#   SNAPSHOT_ENCRYPT        true|false (default true)
#   SNAPSHOT_GPG_RECIPIENT  key fingerprint to encrypt to   (required if true)
#   SNAPSHOT_GPG_KEYRING    keyring holding that public key (required if true)
#   SNAPSHOT_DESTINATION    local|github (default local)
#   SNAPSHOT_REPO           owner/repo       (required if destination=github)
#   SNAPSHOT_GITHUB_TOKEN   contents:write   (required if destination=github)
#
# ENCRYPTION, when on, is public-key only: the VM holds no private key, so a
# compromised VM cannot read its own backups — and this script CANNOT verify a
# restore, having nothing to decrypt with. It therefore verifies the PLAINTEXT
# archive (with the same pg_restore binary that would restore it) before
# encrypting, and checks the ciphertext is addressed to the expected key.
# ⚠️  An encrypted snapshot is worthless without the private key. Confirm the
#     key is in safe custody before relying on any of this, and do a restore
#     drill — see README.md §Restore drill.
#
# Exit codes: 0 ok · 1 failure (cron logs it) · 2 usage.

set -euo pipefail

TAG="db-snapshot"
CONFIG_FILE="${SNAPSHOT_CONFIG:-/etc/nivesh/db-snapshot.env}"
# GitHub refuses a release asset over 2 GiB. Only used when publishing there;
# a local snapshot is never split. Overridable so the split/rejoin path can be
# exercised on a small dump — leave it alone otherwise.
GITHUB_ASSET_LIMIT_MB="${GITHUB_ASSET_LIMIT_MB:-1800}"
MIN_FREE_MARGIN_MB=1024

log()  { printf '[%s] %s %s\n' "$TAG" "$(date -Is)" "$*"; }
warn() { printf '[%s] %s WARN: %s\n' "$TAG" "$(date -Is)" "$*" >&2; }
fail() { printf '[%s] %s FATAL: %s\n' "$TAG" "$(date -Is)" "$*" >&2; exit 1; }

TARGET=""
PREFLIGHT_ONLY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)     TARGET="${2:-}"; shift 2 ;;
        --preflight)  PREFLIGHT_ONLY=true; shift ;;
        --no-upload)  shift ;;   # accepted for compatibility; local is the default now
        -h|--help)    sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)            echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

[[ $EUID -eq 0 ]] || fail "Run as root (needs the docker socket and /etc/nivesh)."
umask 077

# ── Target ───────────────────────────────────────────────────────────────────
case "$TARGET" in
    app)
        PG_CONTAINER="nivesh-staging-postgres"
        DUMP_DIR="/opt/nivesh-staging/dumps"
        LOG_DIR="/opt/nivesh-staging/logs"
        RELEASE_TAG="app-latest"
        VM_LABEL="nivesh-app-vm"
        ;;
    nidp)
        PG_CONTAINER="nidp-postgres-staging"
        DUMP_DIR="/opt/nidp-staging/dumps"
        LOG_DIR="/opt/nidp-staging/logs"
        RELEASE_TAG="nidp-latest"
        VM_LABEL="nidp-staging-vm"
        ;;
    # PRODUCTION — both stacks live on the one CloudPe prod VM (45.64.105.249), see
    # deploy/cloudpe-prod/README.md. The snapshot therefore sits on the same disk as the
    # database it protects: it guards against bad data, a bad migration or a dropped table,
    # NOT against losing the VM. Copy it off the VM for that.
    prod-app)
        PG_CONTAINER="nivesh-postgres"
        DUMP_DIR="/opt/nivesh/dumps"
        LOG_DIR="/opt/nivesh/logs"
        RELEASE_TAG="prod-app-latest"
        VM_LABEL="nivesh-prod-vm"
        ;;
    prod-nidp)
        PG_CONTAINER="nidp-postgres"
        DUMP_DIR="/opt/nidp/dumps"
        LOG_DIR="/opt/nidp/logs"
        RELEASE_TAG="prod-nidp-latest"
        VM_LABEL="nivesh-prod-vm"
        ;;
    *)  echo "usage: $0 --target app|nidp|prod-app|prod-nidp [--preflight]" >&2; exit 2 ;;
esac

# ── Config ───────────────────────────────────────────────────────────────────
[[ -r "$CONFIG_FILE" ]] || fail "Cannot read ${CONFIG_FILE} — run install.sh first."
if [[ "$(stat -c '%a' "$CONFIG_FILE")" != "600" ]]; then
    fail "${CONFIG_FILE} must be mode 600; it is $(stat -c '%a' "$CONFIG_FILE")."
fi
# shellcheck disable=SC1090
set -a; source "$CONFIG_FILE"; set +a

COMPRESS="${SNAPSHOT_COMPRESS:-zstd:12}"
ENCRYPT="${SNAPSHOT_ENCRYPT:-true}"
DESTINATION="${SNAPSHOT_DESTINATION:-local}"

case "$DESTINATION" in local|github) ;; *) fail "SNAPSHOT_DESTINATION must be local or github (got: ${DESTINATION})." ;; esac
case "$ENCRYPT"    in true|false)    ;; *) fail "SNAPSHOT_ENCRYPT must be true or false (got: ${ENCRYPT})." ;; esac
# Guard the config against a silent own-goal: "none" would write the database out
# uncompressed, which on the warehouse is ~10x the disk.
[[ "$COMPRESS" != "none" && "$COMPRESS" != "none:"* ]] \
    || fail "SNAPSHOT_COMPRESS=none would write an uncompressed dump. Refusing."

for bin in docker curl jq sha256sum numfmt; do
    command -v "$bin" >/dev/null 2>&1 || fail "${bin} not found on this VM."
done
if [[ "$ENCRYPT" == "true" ]]; then
    command -v gpg >/dev/null 2>&1 || fail "gpg not found but SNAPSHOT_ENCRYPT=true."
    : "${SNAPSHOT_GPG_RECIPIENT:?SNAPSHOT_GPG_RECIPIENT missing from $CONFIG_FILE}"
    : "${SNAPSHOT_GPG_KEYRING:?SNAPSHOT_GPG_KEYRING missing from $CONFIG_FILE}"
fi
if [[ "$DESTINATION" == "github" ]]; then
    : "${SNAPSHOT_REPO:?SNAPSHOT_REPO missing from $CONFIG_FILE}"
    : "${SNAPSHOT_GITHUB_TOKEN:?SNAPSHOT_GITHUB_TOKEN missing from $CONFIG_FILE}"
    command -v split >/dev/null 2>&1 || fail "split not found but SNAPSHOT_DESTINATION=github."
fi

# ── Preflight ────────────────────────────────────────────────────────────────
docker ps --format '{{.Names}}' | grep -qx "$PG_CONTAINER" \
    || fail "Container ${PG_CONTAINER} is not running — refusing to report a snapshot that does not exist."

if [[ "$ENCRYPT" == "true" ]]; then
    [[ -r "$SNAPSHOT_GPG_KEYRING" ]] || fail "Keyring ${SNAPSHOT_GPG_KEYRING} is missing or unreadable."
    GPG_BASE=(gpg --batch --no-tty --no-default-keyring --keyring "$SNAPSHOT_GPG_KEYRING")
    "${GPG_BASE[@]}" --list-keys "$SNAPSHOT_GPG_RECIPIENT" >/dev/null 2>&1 \
        || fail "Public key ${SNAPSHOT_GPG_RECIPIENT} is not in ${SNAPSHOT_GPG_KEYRING}."
fi

# Credentials come from the container's own env: no secret in this script, in
# the process list, or in the log.
container_env() {   # <VAR>
    docker inspect "$PG_CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}' \
        | sed -n "s/^$1=//p" | head -1
}
PG_USER="$(container_env POSTGRES_USER)"
PG_DB="$(container_env POSTGRES_DB)"
[[ -n "$PG_USER" && -n "$PG_DB" ]] \
    || fail "Could not read POSTGRES_USER/POSTGRES_DB from ${PG_CONTAINER}."

psql_val() {        # <sql> — one value, read-only
    docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -At -v ON_ERROR_STOP=1 -c "$1"
}
PG_VERSION="$(psql_val 'SHOW server_version;')"
DB_SIZE_BYTES="$(psql_val 'SELECT pg_database_size(current_database());')"
[[ "$DB_SIZE_BYTES" =~ ^[0-9]+$ ]] || fail "Could not read the size of ${PG_DB}."
TSDB_VERSION="$(psql_val "SELECT coalesce(max(extversion),'') FROM pg_extension WHERE extname='timescaledb';" | tr -d '[:space:]')"
HYPERTABLES=0
if [[ -n "$TSDB_VERSION" ]]; then
    HYPERTABLES="$(psql_val 'SELECT count(*) FROM timescaledb_information.hypertables;')"
fi

# Fail now, not after a 16 GB dump, if this build cannot do the configured
# compression — pg_dump only rejects the algorithm once it starts writing.
docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" \
    -Fc --compress="$COMPRESS" --schema-only -t pg_catalog.pg_class >/dev/null 2>&1 \
    || fail "pg_dump in ${PG_CONTAINER} rejects --compress=${COMPRESS}. Supported here: gzip, zstd, lz4, none."

log "VM=${VM_LABEL} container=${PG_CONTAINER} db=${PG_DB} postgres=${PG_VERSION}"
log "  size=$(numfmt --to=iec "$DB_SIZE_BYTES") timescaledb=${TSDB_VERSION:-none} hypertables=${HYPERTABLES}"
log "  compress=${COMPRESS} encrypt=${ENCRYPT} destination=${DESTINATION} retention=latest-only"
[[ "$ENCRYPT" != "true" ]] || log "  recipient=${SNAPSHOT_GPG_RECIPIENT}"

mkdir -p "$DUMP_DIR" "$LOG_DIR"
chmod 700 "$DUMP_DIR"

# Peak disk = previous snapshot + new dump (+ its ciphertext). A compressed dump
# of this data runs well under a quarter of the database; budget a third and
# keep a margin so a snapshot can never be the thing that fills the disk.
NEED_MB=$(( DB_SIZE_BYTES / 1048576 * 2 / 3 + MIN_FREE_MARGIN_MB ))
FREE_MB=$(( $(df -Pk "$DUMP_DIR" | awk 'NR==2{print $4}') / 1024 ))
log "  free at ${DUMP_DIR}: ${FREE_MB} MiB (need ~${NEED_MB} MiB)"
(( FREE_MB >= NEED_MB )) \
    || fail "Only ${FREE_MB} MiB free at ${DUMP_DIR}, need ~${NEED_MB} MiB. Not dumping — a full disk takes the stack down."

if [[ "$DESTINATION" == "github" ]]; then
    api() {         # <method> <path-or-url> [curl args...]
        local method="$1" url="$2"; shift 2
        case "$url" in https://*) ;; *) url="https://api.github.com${url}" ;; esac
        curl -sS --fail-with-body --retry 3 --retry-delay 5 -X "$method" \
            -H "Authorization: Bearer ${SNAPSHOT_GITHUB_TOKEN}" \
            -H "Accept: application/vnd.github+json" \
            -H "X-GitHub-Api-Version: 2022-11-28" \
            "$url" "$@"
    }
    repo_json="$(api GET "/repos/${SNAPSHOT_REPO}")" \
        || fail "Cannot reach ${SNAPSHOT_REPO} with the configured token.
For a fine-grained PAT, 404 means the repo is not in that token's repository access."
    if [[ "$(jq -r '.private' <<<"$repo_json")" != "true" ]]; then
        fail "${SNAPSHOT_REPO} is PUBLIC. Refusing to upload a database snapshot to a public repo."
    fi
    [[ "$(jq -r '.permissions.push' <<<"$repo_json")" == "true" ]] \
        || fail "The token cannot push to ${SNAPSHOT_REPO}."
    log "  github: ${SNAPSHOT_REPO} is private and writable."
fi

if $PREFLIGHT_ONLY; then
    log "PREFLIGHT OK — nothing dumped (--preflight)."
    exit 0
fi

# ── Dump ─────────────────────────────────────────────────────────────────────
STAMP="$(date +%Y%m%d)"
BASENAME="${PG_DB}_${STAMP}"
PLAIN="${DUMP_DIR}/${BASENAME}.dump"
CIPHER="${PLAIN}.gpg"
STARTED_AT="$(date -Is)"
DUMP_BEGAN=$SECONDS

if [[ "$ENCRYPT" == "true" ]]; then
    # The plaintext dump is unencrypted database content and only an
    # intermediate: remove it on every exit path, not just the happy one.
    cleanup_plain() { [[ -f "$PLAIN" ]] && rm -f "$PLAIN"; return 0; }
    trap cleanup_plain EXIT
fi

rm -f "$PLAIN" "$CIPHER"

# The container's own pg_dump, NOT the host's (18.x here vs 16.x servers): the
# archive has to be readable by the pg_restore inside this image, and a newer
# pg_dump can write an archive version that an older pg_restore refuses.
# On TimescaleDB, pg_dump warns on stderr about circular foreign keys on the
# chunk catalogs. That is expected (the restore wraps pg_restore in
# timescaledb_pre_restore/post_restore); only a non-zero exit is a failure.
log "pg_dump -Fc --compress=${COMPRESS} ${PG_DB} (schema + data) → ${PLAIN}"
docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" \
    -Fc --compress="$COMPRESS" --no-owner --no-privileges > "$PLAIN" \
    || fail "pg_dump failed — no snapshot was produced."
PLAIN_BYTES="$(stat -c %s "$PLAIN")"
(( PLAIN_BYTES > 0 )) || fail "pg_dump produced an empty file."
chmod 600 "$PLAIN"
log "  dump: $(numfmt --to=iec "$PLAIN_BYTES") in $(( SECONDS - DUMP_BEGAN ))s"
log "  compressed $(awk -v d="$DB_SIZE_BYTES" -v p="$PLAIN_BYTES" 'BEGIN{printf "%.1f", d/p}')x vs the live database"

# ── Verify the archive ───────────────────────────────────────────────────────
# Same binary that would restore it, reading the archive over stdin. This also
# proves the compression method is one this pg_restore can decompress.
log "pg_restore --list (verifying the archive is readable and non-trivial)"
TOC_ENTRIES="$(docker exec -i "$PG_CONTAINER" pg_restore --list < "$PLAIN" 2>/dev/null | grep -cE '^[0-9]+;' || true)"
log "  TOC entries: ${TOC_ENTRIES}"
(( TOC_ENTRIES >= 10 )) \
    || fail "Archive lists only ${TOC_ENTRIES} TOC entries — it is empty or corrupt. Keeping nothing."

# ── Encrypt (optional) ───────────────────────────────────────────────────────
ARTIFACTS=()
if [[ "$ENCRYPT" == "true" ]]; then
    # The archive is already compressed, so --compress-algo none: a second pass
    # costs CPU and gains nothing.
    log "gpg --encrypt → ${CIPHER}"
    "${GPG_BASE[@]}" --trust-model always --compress-algo none \
        --recipient "$SNAPSHOT_GPG_RECIPIENT" --output "$CIPHER" --encrypt "$PLAIN" \
        || fail "gpg encryption failed."
    chmod 600 "$CIPHER"
    log "  encrypted: $(numfmt --to=iec "$(stat -c %s "$CIPHER")")"

    # Confirm the ciphertext really is an OpenPGP message addressed to the
    # expected key. Without the private key this is as far as verification goes.
    # Every substitution is `|| true`: `gpg --list-packets` on a message we
    # cannot decrypt exits 2 ("No secret key") even though it prints the keyid
    # we want, and under `set -o pipefail` that would abort the job silently,
    # right after a dump that actually succeeded.
    RECIPIENT_KEYIDS="$("${GPG_BASE[@]}" --with-colons --list-keys "$SNAPSHOT_GPG_RECIPIENT" 2>/dev/null \
        | awk -F: '$1=="pub"||$1=="sub"{print tolower($5)}' || true)"
    PACKET_KEYIDS="$(gpg --batch --list-packets "$CIPHER" 2>/dev/null \
        | sed -n 's/.*keyid \([0-9A-Fa-f]\{16\}\).*/\1/p' | tr 'A-F' 'a-f' | sort -u || true)"
    [[ -n "$RECIPIENT_KEYIDS" ]] || fail "Could not list the key ids of ${SNAPSHOT_GPG_RECIPIENT}."
    [[ -n "$PACKET_KEYIDS" ]]    || fail "${CIPHER} carries no OpenPGP recipient packet — it is not an encrypted message."
    MATCHED=false
    while read -r kid; do
        [[ -n "$kid" ]] || continue
        if grep -qix "$kid" <<<"$RECIPIENT_KEYIDS"; then MATCHED=true; fi
    done <<<"$PACKET_KEYIDS"
    $MATCHED || fail "${CIPHER} is not encrypted to ${SNAPSHOT_GPG_RECIPIENT} — discarding it."
    log "  ciphertext is an OpenPGP message for the expected key."

    rm -f "$PLAIN"
    trap - EXIT
    ARTIFACTS=("$CIPHER")
else
    warn "SNAPSHOT_ENCRYPT=false — this snapshot is UNENCRYPTED database content."
    warn "  It is root-only in ${DUMP_DIR}; encrypt it before it leaves this VM."
    ARTIFACTS=("$PLAIN")
fi

# ── Split, only when GitHub would refuse the asset ───────────────────────────
if [[ "$DESTINATION" == "github" ]] \
        && (( $(stat -c %s "${ARTIFACTS[0]}") > GITHUB_ASSET_LIMIT_MB * 1048576 )); then
    WHOLE="${ARTIFACTS[0]}"
    log "split -b ${GITHUB_ASSET_LIMIT_MB}M (GitHub refuses a release asset over 2 GiB)"
    split -b "${GITHUB_ASSET_LIMIT_MB}M" -d -a 2 "$WHOLE" "${WHOLE}.part"
    ARTIFACTS=()
    while IFS= read -r p; do ARTIFACTS+=("$p"); done < <(ls -1 "${WHOLE}".part* | sort)
    rm -f "$WHOLE"
    log "  ${#ARTIFACTS[@]} parts: $(printf '%s ' "${ARTIFACTS[@]##*/}")"
fi

# ── Checksums ────────────────────────────────────────────────────────────────
MANIFEST="${DUMP_DIR}/${BASENAME}.sha256"
( cd "$DUMP_DIR" && sha256sum "${ARTIFACTS[@]##*/}" > "${MANIFEST##*/}" )
chmod 600 "$MANIFEST"
log "  manifest: ${MANIFEST}"

# ── Publish, only if asked to ────────────────────────────────────────────────
if [[ "$DESTINATION" == "github" ]]; then
    release_json="$(api GET "/repos/${SNAPSHOT_REPO}/releases/tags/${RELEASE_TAG}" 2>/dev/null || true)"
    RELEASE_ID="$(jq -r '.id // empty' <<<"${release_json:-}" 2>/dev/null || true)"
    if [[ -z "$RELEASE_ID" ]]; then
        log "creating release ${RELEASE_TAG}"
        RELEASE_ID="$(api POST "/repos/${SNAPSHOT_REPO}/releases" -d "$(jq -n \
            --arg t "$RELEASE_TAG" --arg n "${VM_LABEL} — latest DB snapshot" \
            '{tag_name:$t, name:$n, draft:false, prerelease:false}')" | jq -r '.id')"
        [[ -n "$RELEASE_ID" && "$RELEASE_ID" != "null" ]] || fail "Could not create release ${RELEASE_TAG}."
    else
        # Retention = latest only: the previous snapshot's assets go before the
        # new ones land. Done first so a part count that shrinks cannot leave a
        # stale .part02 that a restore would silently concatenate.
        while read -r aid aname; do
            [[ -n "$aid" ]] || continue
            api DELETE "/repos/${SNAPSHOT_REPO}/releases/assets/${aid}" >/dev/null \
                && log "  deleted previous asset ${aname}"
        done < <(jq -r '.assets[]? | "\(.id) \(.name)"' <<<"$release_json")
    fi

    upload_asset() {    # <file>
        local f="$1" name; name="$(basename "$f")"
        log "  uploading ${name} ($(numfmt --to=iec "$(stat -c %s "$f")"))"
        curl -sS --fail-with-body --retry 3 --retry-delay 10 -X POST \
            -H "Authorization: Bearer ${SNAPSHOT_GITHUB_TOKEN}" \
            -H "Accept: application/vnd.github+json" \
            -H "X-GitHub-Api-Version: 2022-11-28" \
            -H "Content-Type: application/octet-stream" \
            --data-binary "@${f}" \
            "https://uploads.github.com/repos/${SNAPSHOT_REPO}/releases/${RELEASE_ID}/assets?name=${name}" \
            >/dev/null || fail "Upload of ${name} failed."
    }
    for p in "${ARTIFACTS[@]}"; do upload_asset "$p"; done
    upload_asset "$MANIFEST"

    # Confirm from the API that what we expect is actually there — an upload
    # that 200s but leaves a partial asset must not pass as a good snapshot.
    EXPECTED=$(( ${#ARTIFACTS[@]} + 1 ))
    assets_json="$(api GET "/repos/${SNAPSHOT_REPO}/releases/${RELEASE_ID}/assets?per_page=100")"
    ACTUAL="$(jq -r '[.[] | select(.state=="uploaded")] | length' <<<"$assets_json")"
    log "  assets uploaded: ${ACTUAL}/${EXPECTED}"
    (( ACTUAL == EXPECTED )) || fail "Expected ${EXPECTED} assets on ${RELEASE_TAG}, found ${ACTUAL}."
    for p in "${ARTIFACTS[@]}"; do
        n="$(basename "$p")"; want="$(stat -c %s "$p")"
        got="$(jq -r --arg n "$n" '.[] | select(.name==$n) | .size' <<<"$assets_json")"
        [[ "$got" == "$want" ]] || fail "Asset ${n} is ${got} bytes on GitHub, ${want} locally."
    done
    log "  every asset matches its local size."
fi

# ── Retention: latest only ───────────────────────────────────────────────────
# Only now that the new snapshot is complete and verified is the previous one
# expendable.
find "$DUMP_DIR" -maxdepth 1 -type f \
     \( -name "${PG_DB}_*.dump" -o -name "${PG_DB}_*.dump.gpg" \
        -o -name "${PG_DB}_*.dump.gpg.part*" -o -name "${PG_DB}_*.dump.part*" \
        -o -name "${PG_DB}_*.sha256" \) \
     ! -name "${BASENAME}.*" -print -delete | sed "s/^/[${TAG}] pruned previous /" || true

log "kept in ${DUMP_DIR}:"
for f in "${ARTIFACTS[@]}" "$MANIFEST"; do log "  $(basename "$f")  $(numfmt --to=iec "$(stat -c %s "$f")")"; done
log "DONE — ${VM_LABEL} ${PG_DB} snapshot on this VM's disk (started ${STARTED_AT}, took $(( SECONDS - DUMP_BEGAN ))s)"
