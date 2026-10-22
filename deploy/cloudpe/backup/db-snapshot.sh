#!/usr/bin/env bash
# db-snapshot.sh — weekly encrypted PostgreSQL/TimescaleDB snapshot of a CloudPe
# staging VM, published as a GitHub release asset in a PRIVATE repo.
#
# Runs as root, from cron, on EITHER VM. Self-contained on purpose: it sources
# nothing from the repo checkout, so a snapshot keeps working even when
# /opt/nidp/dev-repo or /opt/nivesh-staging/repo is mid-deploy or broken.
#
#   sudo bash db-snapshot.sh --target app      # nivesh-app-vm   45.64.105.88
#   sudo bash db-snapshot.sh --target nidp     # nidp-staging-vm 45.64.105.224
#   sudo bash db-snapshot.sh --target app --no-upload   # dump+encrypt, keep local
#   sudo bash db-snapshot.sh --target app --preflight   # checks only, no dump
#
# WHAT IT PRODUCES
#   pg_dump -Fc  (custom format = zlib-compressed, schema AND data, the whole
#   database) → GPG public-key encrypted → split into <2 GiB parts if needed →
#   uploaded to the release tagged app-latest / nidp-latest.
#
# RETENTION: latest only. Each run deletes the previous run's release assets
# before uploading the new ones, and deletes the previous local copy after a
# successful upload. There is no history — by design (see README.md).
#
# ENCRYPTION: public-key only. These VMs hold the recipient's PUBLIC key, so a
# compromised VM cannot read its own backups, and this script CANNOT verify a
# restore end to end — it has no private key. It therefore verifies the
# PLAINTEXT archive (with the same pg_restore binary that would restore it)
# before encrypting, and checks the ciphertext is a well-formed OpenPGP message
# for the expected key. A real restore drill needs the private key and a human:
# run restore-snapshot.sh quarterly. See README.md §Restore drill.
#
# Config: /etc/nivesh/db-snapshot.env (mode 600, NOT in git) must define
#   SNAPSHOT_REPO           owner/repo of the PRIVATE snapshots repo
#   SNAPSHOT_GITHUB_TOKEN   token with contents:write on that repo
#   SNAPSHOT_GPG_RECIPIENT  key fingerprint to encrypt to
#   SNAPSHOT_GPG_KEYRING    keyring file holding that public key
#
# Exit codes: 0 ok · 1 failure (cron mails/logs it) · 2 usage.

set -euo pipefail

TAG="db-snapshot"
CONFIG_FILE="${SNAPSHOT_CONFIG:-/etc/nivesh/db-snapshot.env}"
# GitHub refuses a release asset over 2 GiB. Overridable only so the split and
# rejoin path can be exercised on a small dump — leave it alone in production.
GITHUB_ASSET_LIMIT_MB="${GITHUB_ASSET_LIMIT_MB:-1800}"
MIN_FREE_MARGIN_MB=1024

log()  { printf '[%s] %s %s\n' "$TAG" "$(date -Is)" "$*"; }
warn() { printf '[%s] %s WARN: %s\n' "$TAG" "$(date -Is)" "$*" >&2; }
fail() { printf '[%s] %s FATAL: %s\n' "$TAG" "$(date -Is)" "$*" >&2; exit 1; }

TARGET=""
DO_UPLOAD=true
PREFLIGHT_ONLY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)     TARGET="${2:-}"; shift 2 ;;
        --no-upload)  DO_UPLOAD=false; shift ;;
        --preflight)  PREFLIGHT_ONLY=true; shift ;;
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
    *)  echo "usage: $0 --target app|nidp [--no-upload] [--preflight]" >&2; exit 2 ;;
esac

# ── Config ───────────────────────────────────────────────────────────────────
[[ -r "$CONFIG_FILE" ]] || fail "Cannot read ${CONFIG_FILE} — run install.sh first."
if [[ "$(stat -c '%a' "$CONFIG_FILE")" != "600" ]]; then
    fail "${CONFIG_FILE} must be mode 600 (it holds a token); it is $(stat -c '%a' "$CONFIG_FILE")."
fi
# shellcheck disable=SC1090
set -a; source "$CONFIG_FILE"; set +a

: "${SNAPSHOT_REPO:?SNAPSHOT_REPO missing from $CONFIG_FILE}"
: "${SNAPSHOT_GPG_RECIPIENT:?SNAPSHOT_GPG_RECIPIENT missing from $CONFIG_FILE}"
: "${SNAPSHOT_GPG_KEYRING:?SNAPSHOT_GPG_KEYRING missing from $CONFIG_FILE}"
if $DO_UPLOAD; then
    : "${SNAPSHOT_GITHUB_TOKEN:?SNAPSHOT_GITHUB_TOKEN missing from $CONFIG_FILE}"
fi

for bin in docker gpg curl jq split sha256sum numfmt; do
    command -v "$bin" >/dev/null 2>&1 || fail "${bin} not found on this VM."
done

# ── Preflight ────────────────────────────────────────────────────────────────
docker ps --format '{{.Names}}' | grep -qx "$PG_CONTAINER" \
    || fail "Container ${PG_CONTAINER} is not running — refusing to report a snapshot that does not exist."

[[ -r "$SNAPSHOT_GPG_KEYRING" ]] || fail "Keyring ${SNAPSHOT_GPG_KEYRING} is missing or unreadable."
GPG_BASE=(gpg --batch --no-tty --no-default-keyring --keyring "$SNAPSHOT_GPG_KEYRING")
"${GPG_BASE[@]}" --list-keys "$SNAPSHOT_GPG_RECIPIENT" >/dev/null 2>&1 \
    || fail "Public key ${SNAPSHOT_GPG_RECIPIENT} is not in ${SNAPSHOT_GPG_KEYRING}."

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

log "VM=${VM_LABEL} container=${PG_CONTAINER} db=${PG_DB} postgres=${PG_VERSION}"
log "  size=$(numfmt --to=iec "$DB_SIZE_BYTES") timescaledb=${TSDB_VERSION:-none} hypertables=${HYPERTABLES}"
log "  repo=${SNAPSHOT_REPO} tag=${RELEASE_TAG} recipient=${SNAPSHOT_GPG_RECIPIENT}"

mkdir -p "$DUMP_DIR" "$LOG_DIR"
chmod 700 "$DUMP_DIR"

# Peak disk = previous encrypted copy + new plaintext dump + new ciphertext.
# A -Fc dump of this data runs about a quarter of the database; budget a third
# and keep a margin so a snapshot can never be the thing that fills the disk.
NEED_MB=$(( DB_SIZE_BYTES / 1048576 * 2 / 3 + MIN_FREE_MARGIN_MB ))
FREE_MB=$(( $(df -Pk "$DUMP_DIR" | awk 'NR==2{print $4}') / 1024 ))
log "  free at ${DUMP_DIR}: ${FREE_MB} MiB (need ~${NEED_MB} MiB)"
(( FREE_MB >= NEED_MB )) \
    || fail "Only ${FREE_MB} MiB free at ${DUMP_DIR}, need ~${NEED_MB} MiB. Not dumping — a full disk takes the stack down."

if $DO_UPLOAD; then
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
        || fail "Cannot reach ${SNAPSHOT_REPO} with the configured token."
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

# The plaintext dump is unencrypted database content: remove it on every exit
# path, not just the happy one.
cleanup_plain() { [[ -f "$PLAIN" ]] && rm -f "$PLAIN"; return 0; }
trap cleanup_plain EXIT

rm -f "$PLAIN" "$CIPHER"

# The container's own pg_dump (16.x), NOT the host's 18.x: the archive has to be
# readable by the pg_restore inside this image, and a newer pg_dump can write an
# archive version that older pg_restore refuses.
# On TimescaleDB, pg_dump warns on stderr about circular foreign keys on the
# chunk catalogs. That is expected (the restore wraps pg_restore in
# timescaledb_pre_restore/post_restore); only a non-zero exit is a failure.
log "pg_dump -Fc ${PG_DB} (schema + data, compressed) → ${PLAIN}"
docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" \
    -Fc --no-owner --no-privileges > "$PLAIN" \
    || fail "pg_dump failed — no snapshot was produced."
PLAIN_BYTES="$(stat -c %s "$PLAIN")"
(( PLAIN_BYTES > 0 )) || fail "pg_dump produced an empty file."
log "  dump: $(numfmt --to=iec "$PLAIN_BYTES")"

# ── Verify the archive BEFORE encrypting ─────────────────────────────────────
# Same binary that would restore it, reading the archive over stdin.
log "pg_restore --list (verifying the archive is readable and non-trivial)"
TOC_ENTRIES="$(docker exec -i "$PG_CONTAINER" pg_restore --list < "$PLAIN" 2>/dev/null | grep -cE '^[0-9]+;' || true)"
log "  TOC entries: ${TOC_ENTRIES}"
(( TOC_ENTRIES >= 10 )) \
    || fail "Archive lists only ${TOC_ENTRIES} TOC entries — it is empty or corrupt. Not uploading it."

# ── Encrypt ──────────────────────────────────────────────────────────────────
# The archive is already zlib-compressed, so --compress-algo none: a second
# compression pass costs CPU and gains nothing.
log "gpg --encrypt → ${CIPHER}"
"${GPG_BASE[@]}" --trust-model always --compress-algo none \
    --recipient "$SNAPSHOT_GPG_RECIPIENT" --output "$CIPHER" --encrypt "$PLAIN" \
    || fail "gpg encryption failed."
CIPHER_BYTES="$(stat -c %s "$CIPHER")"
chmod 600 "$CIPHER"
log "  encrypted: $(numfmt --to=iec "$CIPHER_BYTES")"

# Confirm the ciphertext really is an OpenPGP message addressed to the expected
# key. Without the private key this is as far as verification can go here.
# Every substitution below is `|| true`: `gpg --list-packets` on a message we
# cannot decrypt exits 2 ("No secret key") even though it prints the recipient
# keyid we want, and under `set -o pipefail` that status would abort the job
# silently, right after a dump that actually succeeded.
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
$MATCHED || fail "${CIPHER} is not encrypted to ${SNAPSHOT_GPG_RECIPIENT} — refusing to publish it."
log "  ciphertext is an OpenPGP message for the expected key."

rm -f "$PLAIN"
trap - EXIT

# ── Split, if GitHub would refuse the asset ──────────────────────────────────
PARTS=()
if (( CIPHER_BYTES > GITHUB_ASSET_LIMIT_MB * 1048576 )); then
    log "split -b ${GITHUB_ASSET_LIMIT_MB}M (GitHub refuses a release asset over 2 GiB)"
    split -b "${GITHUB_ASSET_LIMIT_MB}M" -d -a 2 "$CIPHER" "${CIPHER}.part"
    while IFS= read -r p; do PARTS+=("$p"); done < <(ls -1 "${CIPHER}".part* | sort)
    rm -f "$CIPHER"
    log "  ${#PARTS[@]} parts: $(printf '%s ' "${PARTS[@]##*/}")"
else
    PARTS=("$CIPHER")
fi

# ── Checksums ────────────────────────────────────────────────────────────────
MANIFEST="${DUMP_DIR}/${BASENAME}.sha256"
( cd "$DUMP_DIR" && sha256sum "${PARTS[@]##*/}" > "${MANIFEST##*/}" )
chmod 600 "$MANIFEST"
log "  manifest: ${MANIFEST}"

if ! $DO_UPLOAD; then
    log "DONE (local only, --no-upload). Snapshot: ${PARTS[*]}"
    exit 0
fi

# ── Publish: replace the previous assets on the single 'latest' release ──────
release_json="$(api GET "/repos/${SNAPSHOT_REPO}/releases/tags/${RELEASE_TAG}" 2>/dev/null || true)"
RELEASE_ID="$(jq -r '.id // empty' <<<"${release_json:-}" 2>/dev/null || true)"
if [[ -z "$RELEASE_ID" ]]; then
    log "creating release ${RELEASE_TAG}"
    RELEASE_ID="$(api POST "/repos/${SNAPSHOT_REPO}/releases" -d "$(jq -n \
        --arg t "$RELEASE_TAG" --arg n "${VM_LABEL} — latest DB snapshot" \
        '{tag_name:$t, name:$n, draft:false, prerelease:false}')" | jq -r '.id')"
    [[ -n "$RELEASE_ID" && "$RELEASE_ID" != "null" ]] || fail "Could not create release ${RELEASE_TAG}."
else
    # Retention = latest only: the previous snapshot's assets go before the new
    # ones land. Done first so a part count that shrinks cannot leave a stale
    # .part02 behind that a restore would silently concatenate.
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
for p in "${PARTS[@]}"; do upload_asset "$p"; done
upload_asset "$MANIFEST"

# Confirm from the API that what we expect is actually there — an upload that
# 200s but leaves a partial asset must not be reported as a good snapshot.
EXPECTED=$(( ${#PARTS[@]} + 1 ))
assets_json="$(api GET "/repos/${SNAPSHOT_REPO}/releases/${RELEASE_ID}/assets?per_page=100")"
ACTUAL="$(jq -r '[.[] | select(.state=="uploaded")] | length' <<<"$assets_json")"
log "  assets uploaded: ${ACTUAL}/${EXPECTED}"
(( ACTUAL == EXPECTED )) || fail "Expected ${EXPECTED} assets on ${RELEASE_TAG}, found ${ACTUAL}."
for p in "${PARTS[@]}"; do
    n="$(basename "$p")"; want="$(stat -c %s "$p")"
    got="$(jq -r --arg n "$n" '.[] | select(.name==$n) | .size' <<<"$assets_json")"
    [[ "$got" == "$want" ]] || fail "Asset ${n} is ${got} bytes on GitHub, ${want} locally."
done
log "  every asset matches its local size."

# Release notes double as the restore header: enough to know what this is and
# how to open it, with no secret in it.
NOTES="$(cat <<EOF
Automated weekly snapshot — **latest only, no history**.

| | |
|---|---|
| VM | \`${VM_LABEL}\` |
| Database | \`${PG_DB}\` ($(numfmt --to=iec "$DB_SIZE_BYTES")) |
| PostgreSQL | ${PG_VERSION} |
| TimescaleDB | ${TSDB_VERSION:-none} (${HYPERTABLES} hypertables) |
| Taken | ${STARTED_AT} |
| Finished | $(date -Is) |
| Format | \`pg_dump -Fc\` (schema + data, zlib) → GPG public-key encrypted |
| Encrypted to | \`${SNAPSHOT_GPG_RECIPIENT}\` |
| Archive TOC entries | ${TOC_ENTRIES} |
| Ciphertext | $(numfmt --to=iec "$CIPHER_BYTES") in ${#PARTS[@]} part(s) |

Restore needs the private key for the fingerprint above. Nothing on either VM
can decrypt this.

\`\`\`
deploy/cloudpe/backup/restore-snapshot.sh --target ${TARGET} --from-github
\`\`\`
EOF
)"
api PATCH "/repos/${SNAPSHOT_REPO}/releases/${RELEASE_ID}" \
    -d "$(jq -n --arg b "$NOTES" '{body:$b}')" >/dev/null \
    || warn "Could not update the release notes (the assets are uploaded and verified)."

# ── Local retention: latest only ─────────────────────────────────────────────
# Only now that the upload is verified is the previous local copy expendable.
find "$DUMP_DIR" -maxdepth 1 -type f \
     \( -name "${PG_DB}_*.dump.gpg" -o -name "${PG_DB}_*.dump.gpg.part*" -o -name "${PG_DB}_*.sha256" \) \
     ! -name "${BASENAME}.*" -print -delete | sed "s/^/[${TAG}] pruned local /" || true

log "DONE — ${VM_LABEL} ${PG_DB} snapshot verified on ${SNAPSHOT_REPO} tag ${RELEASE_TAG}"
