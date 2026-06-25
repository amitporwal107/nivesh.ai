#!/usr/bin/env bash
# deploy.sh — one-shot deploy of the staging stack to nivesh-app-vm via GitHub.
#
# Flow:
#   1. (local)  stage explicit paths   → commit on STAGING_BRANCH → push
#   2. (remote) git clone (first run) or fetch/checkout/reset
#   3. (remote) sudo bash bootstrap-staging.sh   (idempotent, one-time setup)
#   4. (remote) sudo bash redeploy-staging.sh    (build + up + healthcheck)
#
# Never rsync, never scp. Working-tree promotion is always: stage → commit →
# push to GitHub → pull on the box. The remote URL contains a PAT — this
# script never echoes `git remote -v` and never logs the token.
#
# Usage:
#   bash deploy/nivesh-staging/deploy.sh                         # default
#   bash deploy/nivesh-staging/deploy.sh --skip-push             # only redeploy
#   bash deploy/nivesh-staging/deploy.sh --dry-run               # nothing remote
#   STAGING_BRANCH=feat/foo bash deploy/nivesh-staging/deploy.sh # custom branch
#
# Env overrides:
#   STAGING_BRANCH   default feat/portfolio-ingestion-staging
#   VM_HOST          default 34.47.250.214
#   VM_USER          default aporwal107_gmail_com
#   SSH_KEY          default ~/.ssh/google_compute_engine
#   REPO_PATHS       default "deploy/nivesh-staging backend/portfolio_ingestion"

set -euo pipefail

# ── Defaults / config ────────────────────────────────────────────────────────
STAGING_BRANCH="${STAGING_BRANCH:-feat/portfolio-ingestion-staging}"
VM_HOST="${VM_HOST:-34.47.250.214}"
VM_USER="${VM_USER:-aporwal107_gmail_com}"
SSH_KEY="${SSH_KEY:-${HOME:-/root}/.ssh/google_compute_engine}"
REMOTE_REPO_DIR="/opt/nivesh-staging/repo"
REPO_PATHS="${REPO_PATHS:-deploy/nivesh-staging backend/portfolio_ingestion}"

SKIP_PUSH=0
DRY_RUN=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-push) SKIP_PUSH=1; shift ;;
        --dry-run)   DRY_RUN=1;  shift ;;
        -h|--help)
            sed -n '2,40p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────
log()  { printf "\033[1;34m[deploy]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[deploy]\033[0m %s\n" "$*" >&2; }
fail() { printf "\033[1;31m[deploy] FATAL:\033[0m %s\n" "$*" >&2; exit 1; }
run()  { if [[ $DRY_RUN -eq 1 ]]; then echo "  (dry-run) $*"; else eval "$@"; fi }

# Resolve repo root regardless of CWD
REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel 2>/dev/null || true)"
[[ -n "${REPO_ROOT}" ]] || fail "Not inside a git repository."
cd "${REPO_ROOT}"

# ── Phase 1: local stage / commit / push ────────────────────────────────────
if [[ $SKIP_PUSH -eq 0 ]]; then
    log "Repo root: ${REPO_ROOT}"

    # Sanity: make sure the GitHub remote exists, but never print its URL (PAT inside).
    git remote get-url origin >/dev/null 2>&1 || fail "No 'origin' remote configured."

    log "Checking explicit paths exist: ${REPO_PATHS}"
    for p in $REPO_PATHS; do
        [[ -e "$p" ]] || fail "Missing path: $p"
    done

    log "Staging only explicit paths (no 'git add -A')..."
    run "git add -- ${REPO_PATHS}"

    # Now that we've staged, refuse if any sensitive pattern landed in the
    # staged set. This catches accidental nesting like REPO_PATHS containing
    # a .env or .token file.
    SENSITIVE_REGEX='(^|/)(\.cas-password|\.gh-token|\.env(\.[^/]*)?|.*\.token|.*\.pem|.*\.key|tests/.*\.PDF)$'
    STAGED_BAD="$(git diff --cached --name-only | grep -E "${SENSITIVE_REGEX}" || true)"
    if [[ -n "${STAGED_BAD}" ]]; then
        fail "Refusing to deploy: sensitive paths staged:
${STAGED_BAD}"
    fi

    if git diff --cached --quiet; then
        log "Nothing to commit — staged tree matches HEAD."
    else
        COMMIT_MSG=$(cat <<'EOF'
feat(portfolio-ingestion): bootstrap staging stack + service skeleton

Adds an isolated staging environment on nivesh-app-vm for the new
portfolio_ingestion FastAPI service:

  - deploy/nivesh-staging/  : docker-compose, nginx vhost (8443),
                              Dockerfile.ingestion, bootstrap + redeploy
                              scripts, README, one-shot deploy.sh
  - backend/portfolio_ingestion/
                              package skeleton with GET /api/healthz,
                              dataclass-based Settings, structured-logging
                              wrapper over core.logging_config, three
                              passing unit tests

No existing file is modified. Subsequent iterations land Postgres
migrations + snapshot engine + SDK callback per PRD §6-§10.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)
        log "Creating commit on branch ${STAGING_BRANCH}..."
        # Land the commit on a dedicated branch but keep HEAD where it was.
        current_branch="$(git rev-parse --abbrev-ref HEAD)"
        run "git checkout -B ${STAGING_BRANCH}"
        run "git commit -m \"${COMMIT_MSG}\""
        log "Pushing to origin/${STAGING_BRANCH} (force-with-lease)..."
        # Quiet + redact: push output may include the URL; pipe to suppressor
        run "git push --force-with-lease --set-upstream origin ${STAGING_BRANCH} 2>&1 | sed 's#https://[^@]*@#https://***@#g'"
        # Return to where the dev was, leave their working tree alone
        run "git checkout ${current_branch}"
    fi
else
    log "--skip-push: leaving git untouched."
fi

# ── Phase 2: remote bootstrap + deploy ──────────────────────────────────────

if [[ $DRY_RUN -eq 1 ]]; then
    log "--dry-run: skipping remote phase."
    exit 0
fi

log "Connecting to ${VM_USER}@${VM_HOST}..."
[[ -f "${SSH_KEY}" ]] || fail "SSH key not found at ${SSH_KEY}"

# Pull the remote URL once locally so we can hand it to the VM without it
# living in the VM's persistent shell history.
ORIGIN_URL="$(git -C "${REPO_ROOT}" remote get-url origin)"

ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
    "${VM_USER}@${VM_HOST}" \
    "STAGING_BRANCH='${STAGING_BRANCH}' ORIGIN_URL='${ORIGIN_URL}' bash -s" <<'REMOTE_EOF'
set -euo pipefail

REMOTE_ROOT="/opt/nivesh-staging"
REMOTE_REPO="${REMOTE_ROOT}/repo"
log()  { printf "  [remote] %s\n" "$*"; }
fail() { printf "  [remote] FATAL: %s\n" "$*" >&2; exit 1; }

sudo mkdir -p "${REMOTE_ROOT}"
sudo chown "${USER}:${USER}" "${REMOTE_ROOT}"

# Pass safe.directory INLINE (-c) so git never has to write ~/.gitconfig — a
# global-config write fails when HOME is non-writable/root-owned ("could not
# lock config file /home/<user>/.gitconfig: Permission denied").
GIT=(git -c "safe.directory=${REMOTE_REPO}")
if [[ ! -d "${REMOTE_REPO}/.git" ]]; then
    log "First-time clone of branch ${STAGING_BRANCH} into ${REMOTE_REPO}..."
    git clone --branch "${STAGING_BRANCH}" --quiet "${ORIGIN_URL}" "${REMOTE_REPO}"
else
    log "Fetching branch ${STAGING_BRANCH}..."
    "${GIT[@]}" -C "${REMOTE_REPO}" remote set-url origin "${ORIGIN_URL}" >/dev/null
    "${GIT[@]}" -C "${REMOTE_REPO}" fetch --quiet origin "${STAGING_BRANCH}"
    "${GIT[@]}" -C "${REMOTE_REPO}" checkout --quiet "${STAGING_BRANCH}"
    "${GIT[@]}" -C "${REMOTE_REPO}" reset --hard --quiet "origin/${STAGING_BRANCH}"
fi
# Scrub the PAT-bearing URL so it isn't sitting in .git/config on disk
"${GIT[@]}" -C "${REMOTE_REPO}" remote set-url origin "https://github.com/amitporwal107/nivesh.ai.git" >/dev/null

log "HEAD on VM: $("${GIT[@]}" -C ${REMOTE_REPO} log -1 --oneline)"

log "Running bootstrap-staging.sh..."
sudo bash "${REMOTE_REPO}/deploy/nivesh-staging/bootstrap-staging.sh"

log "Running redeploy-staging.sh..."
sudo bash "${REMOTE_REPO}/deploy/nivesh-staging/redeploy-staging.sh" "${STAGING_BRANCH}" || {
    # First time, the redeploy script's smoke check may race startup; show
    # container status before failing out so we can diagnose.
    sudo docker ps --filter "name=nivesh-staging" --format "{{.Names}}\t{{.Status}}"
    fail "redeploy-staging.sh failed"
}

log "Done. Local healthz probe:"
curl -ksS --resolve "staging.niveshcopilot.com:8443:127.0.0.1" \
    "https://staging.niveshcopilot.com:8443/api/healthz" || true
echo
REMOTE_EOF

log "Local + remote deploy complete."
log "Next: open GCP firewall for 8443 + add Cloudflare DNS record. See deploy/nivesh-staging/README.md §'Going public'."
