#!/usr/bin/env bash
# install.sh — install the weekly DB snapshot job on one CloudPe VM.
#
# Run as root ON the VM being set up. Idempotent: re-running updates the
# scripts, the config and the cron entry in place.
#
#   sudo bash install.sh --target app|nidp \
#        --pubkey-file /path/to/recipient-public-key.asc \
#        [--compress zstd:12] [--no-encrypt] \
#        [--destination github --repo owner/private-repo --token-file /path/to/token]
#
# --pubkey-file   the recipient's ASCII-armored OpenPGP PUBLIC key. Only the
#                 public key belongs on these VMs — a compromised VM must not be
#                 able to decrypt its own backups. Required unless --no-encrypt.
# --recipient     which fingerprint to encrypt to, if the key file holds more
#                 than one key. Defaults to the only key in the file.
# --compress      pg_dump compression, METHOD[:LEVEL] (default zstd:12).
#                 Measured on the 882 MB app DB: zstd:12 = 6.5x in 48s,
#                 zstd:3 = 5.5x in 7s, gzip:6 = 5.5x in 20s, none = 1.3x.
# --no-encrypt    store the dump unencrypted (root-only, mode 600). Sane ONLY
#                 while the dump never leaves the VM, and it removes the risk of
#                 an undecryptable backup if the private key is ever lost.
# --destination   local (default) or github. Local writes to /opt/<stack>/dumps
#                 and uploads nothing. github additionally publishes release
#                 assets to a PRIVATE repo and needs --repo and --token-file.
# --token-file    file whose first line is a GitHub token with contents:write.
#                 Read from a FILE, never from the command line, so it never
#                 reaches the process list or shell history.
#
# Installs:
#   /opt/<stack>/bin/db-snapshot.sh         the job (700)
#   /opt/<stack>/bin/restore-snapshot.sh    the restore path (700)
#   /etc/nivesh/db-snapshot.env             config (600)
#   /etc/nivesh/snapshot-recipient.gpg      recipient public keyring (644)
#   /etc/cron.d/<stack>-db-snapshot         weekly schedule (644)
#
# Finishes by running the job's own --preflight, so a bad install fails here
# rather than silently at 02:30 on Sunday.

set -euo pipefail

TAG="install-db-snapshot"
HERE="$(cd "$(dirname "$0")" && pwd)"
log()  { printf '[%s] %s\n' "$TAG" "$*"; }
warn() { printf '[%s] WARN: %s\n' "$TAG" "$*" >&2; }
fail() { printf '[%s] FATAL: %s\n' "$TAG" "$*" >&2; exit 1; }

TARGET=""; REPO=""; TOKEN_FILE=""; PUBKEY_FILE=""; RECIPIENT=""
COMPRESS="zstd:12"; ENCRYPT=true; DESTINATION="local"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)      TARGET="${2:-}"; shift 2 ;;
        --repo)        REPO="${2:-}"; shift 2 ;;
        --token-file)  TOKEN_FILE="${2:-}"; shift 2 ;;
        --pubkey-file) PUBKEY_FILE="${2:-}"; shift 2 ;;
        --recipient)   RECIPIENT="${2:-}"; shift 2 ;;
        --compress)    COMPRESS="${2:-}"; shift 2 ;;
        --destination) DESTINATION="${2:-}"; shift 2 ;;
        --no-encrypt)  ENCRYPT=false; shift ;;
        -h|--help)     sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)             echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

[[ $EUID -eq 0 ]] || fail "Run as root (sudo)."
umask 077

case "$TARGET" in
    app)  STACK="/opt/nivesh-staging"; CRON_DEST="/etc/cron.d/nivesh-staging-db-snapshot"; CRON_SRC="db-snapshot-app.cron" ;;
    nidp) STACK="/opt/nidp-staging";   CRON_DEST="/etc/cron.d/nidp-staging-db-snapshot";   CRON_SRC="db-snapshot-nidp.cron" ;;
    *)    fail "--target must be app or nidp" ;;
esac
[[ -d "$STACK" ]] || fail "${STACK} does not exist — is --target ${TARGET} right for this VM?"
case "$DESTINATION" in local|github) ;; *) fail "--destination must be local or github" ;; esac
[[ -n "$COMPRESS" && "$COMPRESS" != none* ]] || fail "--compress none would write an uncompressed dump."

if [[ "$DESTINATION" == "github" ]]; then
    [[ -n "$REPO" && "$REPO" == */* ]] || fail "--destination github needs --repo owner/repo."
    [[ -r "${TOKEN_FILE:-}" ]]         || fail "--destination github needs a readable --token-file."
fi
if $ENCRYPT; then
    [[ -r "${PUBKEY_FILE:-}" ]] || fail "--pubkey-file is required (or pass --no-encrypt)."
fi

# ── Recipient keyring ────────────────────────────────────────────────────────
install -d -m 700 /etc/nivesh
KEYRING="/etc/nivesh/snapshot-recipient.gpg"

if $ENCRYPT; then
    GNUPG_TMP="$(mktemp -d)"
    trap 'rm -rf "$GNUPG_TMP"' EXIT

    grep -q 'BEGIN PGP PUBLIC KEY BLOCK' "$PUBKEY_FILE" \
        || fail "${PUBKEY_FILE} is not an ASCII-armored PGP PUBLIC KEY BLOCK."
    # `if`, not `grep && fail`: as a bare statement that aborts the installer
    # under `set -e` on the normal case, where the pattern is absent.
    if grep -q 'BEGIN PGP PRIVATE KEY BLOCK' "$PUBKEY_FILE"; then
        fail "${PUBKEY_FILE} contains a PRIVATE key. Never put a private key on these VMs."
    fi

    rm -f "$KEYRING"
    gpg --batch --no-tty --homedir "$GNUPG_TMP" --no-default-keyring --keyring "$KEYRING" \
        --import "$PUBKEY_FILE" 2>&1 | sed "s/^/[${TAG}] gpg: /"
    [[ -s "$KEYRING" ]] || fail "Importing ${PUBKEY_FILE} produced no keyring."
    chmod 644 "$KEYRING"
    # gpg leaves a mode-600 backup keybox beside the one it wrote; it serves no
    # purpose here and only confuses an audit of /etc/nivesh.
    rm -f "${KEYRING}~"

    mapfile -t FPRS < <(gpg --batch --no-tty --homedir "$GNUPG_TMP" --no-default-keyring \
        --keyring "$KEYRING" --with-colons --list-keys | awk -F: '$1=="fpr"{print $10}' | sort -u)
    if [[ -z "$RECIPIENT" ]]; then
        (( ${#FPRS[@]} >= 1 )) || fail "No key found in ${KEYRING}."
        # A key plus its subkeys share one primary fingerprint; several
        # primaries means the operator must choose.
        PRIMARIES="$(gpg --batch --no-tty --homedir "$GNUPG_TMP" --no-default-keyring --keyring "$KEYRING" \
            --with-colons --list-keys | awk -F: '$1=="pub"{p=1;next} $1=="fpr"&&p{print $10;p=0}')"
        mapfile -t PRIM_ARR <<<"$PRIMARIES"
        (( ${#PRIM_ARR[@]} == 1 )) \
            || fail "${PUBKEY_FILE} holds ${#PRIM_ARR[@]} keys — pass --recipient <fingerprint>."
        RECIPIENT="${PRIM_ARR[0]}"
    fi
    printf '%s\n' "${FPRS[@]}" | grep -qix "$RECIPIENT" \
        || fail "Fingerprint ${RECIPIENT} is not in ${PUBKEY_FILE}."
    log "recipient: ${RECIPIENT}"
    log "  uid(s): $(gpg --batch --no-tty --homedir "$GNUPG_TMP" --no-default-keyring --keyring "$KEYRING" \
        --with-colons --list-keys "$RECIPIENT" | awk -F: '$1=="uid"{print $10}' | paste -sd'; ')"
else
    warn "--no-encrypt: snapshots will be UNENCRYPTED database content, root-only in ${STACK}/dumps."
fi

# ── Scripts ──────────────────────────────────────────────────────────────────
install -d -m 700 "${STACK}/bin"
install -m 700 "${HERE}/db-snapshot.sh"      "${STACK}/bin/db-snapshot.sh"
install -m 700 "${HERE}/restore-snapshot.sh" "${STACK}/bin/restore-snapshot.sh"
log "installed ${STACK}/bin/db-snapshot.sh"

install -d -m 700 "${STACK}/dumps"
install -d -m 755 "${STACK}/logs"

# ── Config ───────────────────────────────────────────────────────────────────
CONFIG="/etc/nivesh/db-snapshot.env"
umask 177
{
    echo "# Written by deploy/cloudpe/backup/install.sh on $(date -Is). NOT in git."
    echo "SNAPSHOT_COMPRESS=${COMPRESS}"
    echo "SNAPSHOT_ENCRYPT=${ENCRYPT}"
    echo "SNAPSHOT_DESTINATION=${DESTINATION}"
    if $ENCRYPT; then
        echo "SNAPSHOT_GPG_RECIPIENT=${RECIPIENT}"
        echo "SNAPSHOT_GPG_KEYRING=${KEYRING}"
    fi
    if [[ "$DESTINATION" == "github" ]]; then
        echo "# Holds a GitHub token — this file must stay mode 600."
        echo "SNAPSHOT_REPO=${REPO}"
        echo "SNAPSHOT_GITHUB_TOKEN=$(head -1 "$TOKEN_FILE" | tr -d '\r\n[:space:]')"
    fi
} > "$CONFIG"
umask 077
chmod 600 "$CONFIG"
log "wrote ${CONFIG} (mode 600, no value echoed)"

# ── Cron ─────────────────────────────────────────────────────────────────────
install -m 644 "${HERE}/${CRON_SRC}" "$CRON_DEST"
log "installed ${CRON_DEST}:"
grep -vE '^\s*#|^\s*$' "$CRON_DEST" | sed "s/^/[${TAG}]   /"

# ── Preflight ────────────────────────────────────────────────────────────────
log "running the job's own preflight..."
"${STACK}/bin/db-snapshot.sh" --target "$TARGET" --preflight \
    || fail "Preflight FAILED — the cron entry is installed but the job would not work. Fix the above."

cat <<EOF

[${TAG}] Installed on $(hostname) for --target ${TARGET}.
  schedule   : $(grep -vE '^\s*#|^\s*$|=' "$CRON_DEST" | awk '{print $1,$2,$3,$4,$5}') (Asia/Kolkata), latest-only
  compression: ${COMPRESS}
  encryption : ${ENCRYPT}
  destination: ${DESTINATION}$([[ "$DESTINATION" == github ]] && echo " (${REPO})")
  snapshots  : ${STACK}/dumps
  log        : ${STACK}/logs/db-snapshot.log

Take one now instead of waiting for Sunday:
  sudo ${STACK}/bin/db-snapshot.sh --target ${TARGET}
EOF
