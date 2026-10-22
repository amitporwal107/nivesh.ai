#!/usr/bin/env bash
# set-github-secrets.sh — store the snapshot encryption key as GitHub Actions
# secrets on the private snapshots repo.
#
#   ./set-github-secrets.sh --repo owner/repo \
#       --token-file  /path/to/github-token \
#       --private-key /path/to/private.asc \
#       --passphrase-file /path/to/passphrase.txt \
#       [--fingerprint <fpr>]
#
# Secrets written:
#   SNAPSHOT_GPG_PRIVATE_KEY   the ASCII-armored, passphrase-protected private key
#   SNAPSHOT_GPG_PASSPHRASE    its passphrase
#   SNAPSHOT_GPG_FINGERPRINT   the key fingerprint (not secret; stored for convenience)
#
# ⚠️  GitHub Actions secrets are WRITE-ONLY. Once stored, no one — including the
#     repo owner — can read a value back through the UI or the API. Only a
#     workflow run can decrypt one into its environment. That is why
#     .github/workflows/export-snapshot-key.yml exists: it is the ONLY way to
#     get the key back out. Keep your own copy as well.
#
# ⚠️  Storing BOTH the key and its passphrase here means the GitHub account
#     alone can decrypt the snapshots, which sit in the same account. If you
#     would rather hold the passphrase yourself, skip --passphrase-file and
#     keep it in a password manager instead.
#
# Values are read from FILES, never from argv, so nothing lands in the process
# list or the shell history. Nothing is echoed.

set -euo pipefail

TAG="set-github-secrets"
log()  { printf '[%s] %s\n' "$TAG" "$*"; }
fail() { printf '[%s] FATAL: %s\n' "$TAG" "$*" >&2; exit 1; }

REPO=""; TOKEN_FILE=""; PRIVATE_KEY=""; PASSPHRASE_FILE=""; FINGERPRINT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)            REPO="${2:-}"; shift 2 ;;
        --token-file)      TOKEN_FILE="${2:-}"; shift 2 ;;
        --private-key)     PRIVATE_KEY="${2:-}"; shift 2 ;;
        --passphrase-file) PASSPHRASE_FILE="${2:-}"; shift 2 ;;
        --fingerprint)     FINGERPRINT="${2:-}"; shift 2 ;;
        -h|--help)         sed -n '2,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)                 echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

[[ -n "$REPO" && "$REPO" == */* ]] || fail "--repo owner/repo is required."
[[ -r "${TOKEN_FILE:-}" ]]  || fail "--token-file is required and must be readable."
[[ -r "${PRIVATE_KEY:-}" ]] || fail "--private-key is required and must be readable."
command -v python3 >/dev/null 2>&1 || fail "python3 not found."
python3 -c 'import nacl' 2>/dev/null || fail "PyNaCl not installed (pip install pynacl) — needed to seal secrets."

grep -q 'BEGIN PGP PRIVATE KEY BLOCK' "$PRIVATE_KEY" \
    || fail "${PRIVATE_KEY} is not an ASCII-armored PGP PRIVATE KEY BLOCK."

TOKEN="$(head -1 "$TOKEN_FILE" | tr -d '\r\n[:space:]')"
[[ -n "$TOKEN" ]] || fail "${TOKEN_FILE} is empty."

api() {
    local method="$1" path="$2"; shift 2
    curl -sS --fail-with-body -X "$method" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: 2022-11-28" \
        "https://api.github.com${path}" "$@"
}

repo_json="$(api GET "/repos/${REPO}")" || fail "Cannot reach ${REPO} with this token.
The token must list ${REPO} under its repository access. For a fine-grained PAT:
  GitHub → Settings → Developer settings → Personal access tokens → Fine-grained
  → your token → Repository access → add ${REPO}
  → Permissions: Contents=Read and write, Secrets=Read and write.
A 404 here means 'no access', not 'no such repo'."
[[ "$(jq -r '.private' <<<"$repo_json")" == "true" ]] \
    || fail "${REPO} is PUBLIC. Refusing to store a backup private key in a public repo's secrets."
log "${REPO} is private."

pk_json="$(api GET "/repos/${REPO}/actions/secrets/public-key")" \
    || fail "Cannot read the Actions public key for ${REPO} (token needs Secrets: Read and write)."
KEY_ID="$(jq -r '.key_id' <<<"$pk_json")"
REPO_PUBKEY="$(jq -r '.key' <<<"$pk_json")"
[[ -n "$KEY_ID" && -n "$REPO_PUBKEY" ]] || fail "Malformed Actions public-key response."

# libsodium sealed box, which is what GitHub requires for secret values.
seal() {    # <plaintext-file> → base64 sealed value on stdout
    REPO_PUBKEY="$REPO_PUBKEY" SECRET_FILE="$1" python3 -I -c '
import base64, os, sys
from nacl.public import PublicKey, SealedBox
pub = PublicKey(base64.b64decode(os.environ["REPO_PUBKEY"]))
with open(os.environ["SECRET_FILE"], "rb") as fh:
    value = fh.read()
sys.stdout.write(base64.b64encode(SealedBox(pub).encrypt(value)).decode())
'
}

put_secret() {  # <name> <plaintext-file>
    local name="$1" file="$2" sealed
    sealed="$(seal "$file")" || fail "Could not seal ${name}."
    api PUT "/repos/${REPO}/actions/secrets/${name}" \
        -d "$(jq -n --arg v "$sealed" --arg k "$KEY_ID" '{encrypted_value:$v, key_id:$k}')" \
        >/dev/null || fail "Could not write secret ${name}."
    log "  set ${name} ($(stat -c %s "$file") bytes, value not echoed)"
}

put_secret SNAPSHOT_GPG_PRIVATE_KEY "$PRIVATE_KEY"

if [[ -n "$PASSPHRASE_FILE" ]]; then
    [[ -r "$PASSPHRASE_FILE" ]] || fail "--passphrase-file is not readable."
    put_secret SNAPSHOT_GPG_PASSPHRASE "$PASSPHRASE_FILE"
else
    log "  (no --passphrase-file: keep the passphrase in your password manager)"
fi

if [[ -n "$FINGERPRINT" ]]; then
    tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
    printf '%s' "$FINGERPRINT" > "$tmp"
    put_secret SNAPSHOT_GPG_FINGERPRINT "$tmp"
fi

# The API lists secret NAMES only — never values. That is the strongest
# confirmation available, and the reason the export workflow exists.
log "secrets now on ${REPO}:"
api GET "/repos/${REPO}/actions/secrets" | jq -r '.secrets[] | "  \(.name)  (updated \(.updated_at))"'

cat <<EOF

[${TAG}] Stored. Remember: these values CANNOT be read back.
  Recover the key with the 'Export snapshot key' workflow in ${REPO},
  or from your own copy. Verify you can decrypt a snapshot before you
  delete any local copy of the key.
EOF
