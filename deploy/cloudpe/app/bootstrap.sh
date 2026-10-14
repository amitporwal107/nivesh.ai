#!/usr/bin/env bash
# bootstrap.sh — one-time setup of the Nivesh app staging VM on CloudPe.
#
# Run as root on the app VM. Idempotent: safe to re-run.
#
#   sudo bash deploy/cloudpe/app/bootstrap.sh [options]
#
#   --bundle DIR      capture bundle from migrate/capture-gcp-app.sh; supplies
#                     .env.staging and the Cloudflare origin cert
#   --cert F --key F  origin cert/key files (override the bundle's)
#   --self-signed     generate a throwaway cert (origin testing only)
#   --repo-url URL    default git@github.com:amitporwal107/nivesh.ai.git
#   --branch NAME     default dev
#   --open-origin     skip the Cloudflare-only allow-list (origin reachable by anyone)
#
# Creates /opt/nivesh-staging/{repo,data,logs,ssl,nginx,dumps,.env.staging},
# the nivesh-staging user, and the staging cron entries. Does NOT build or
# start the stack — that is app/deploy.sh (after app/restore.sh if restoring).

set -euo pipefail

TAG="app-bootstrap"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../lib/common.sh
source "${HERE}/../lib/common.sh"

STAGING_ROOT="/opt/nivesh-staging"
REPO_DIR="${STAGING_ROOT}/repo"
ENV_FILE="${STAGING_ROOT}/.env.staging"
SSL_DIR="${STAGING_ROOT}/ssl"
DEPLOY_KEY="${STAGING_ROOT}/.ssh/id_ed25519"
SVC_USER="nivesh-staging"
HOSTNAME_PUBLIC="staging.niveshcopilot.com"

REPO_URL="git@github.com:amitporwal107/nivesh.ai.git"
BRANCH="dev"
BUNDLE=""
CERT=""
KEY=""
SELF_SIGNED=false
OPEN_ORIGIN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bundle)      BUNDLE="$2"; shift 2 ;;
        --cert)        CERT="$2"; shift 2 ;;
        --key)         KEY="$2"; shift 2 ;;
        --repo-url)    REPO_URL="$2"; shift 2 ;;
        --branch)      BRANCH="$2"; shift 2 ;;
        --self-signed) SELF_SIGNED=true; shift ;;
        --open-origin) OPEN_ORIGIN=true; shift ;;
        -h|--help)     sed -n '2,19p' "$0"; exit 0 ;;
        *)             fail "Unknown argument: $1" ;;
    esac
done

require_root
require_apt_os
[[ -z "$BUNDLE" ]] || verify_bundle "$BUNDLE"

# ── 1. Packages + Docker ─────────────────────────────────────────────────────
log "Installing base packages..."
apt-get update -qq
apt_install ca-certificates curl git jq openssl cron logrotate tzdata postgresql-client
set_timezone_ist
install_docker

# ── 2. Service user + directories ────────────────────────────────────────────
# cache-clear.cron runs `docker exec` as nivesh-staging; nothing on the GCP VM
# created that user from the repo, so it is created here.
if ! id -u "$SVC_USER" >/dev/null 2>&1; then
    log "Creating service user ${SVC_USER}"
    useradd --system --no-create-home --home-dir "$STAGING_ROOT" --shell /usr/sbin/nologin "$SVC_USER"
fi
usermod -aG docker "$SVC_USER"

log "Ensuring directories under ${STAGING_ROOT}/"
mkdir -p "${STAGING_ROOT}"/{data/{postgres,mongo,redis,app},logs,ssl,nginx,dumps}
# Group-traversable so the cron user can reach logs/; secrets below stay 600 root.
chown root:"$SVC_USER" "$STAGING_ROOT"
chmod 750 "$STAGING_ROOT"
chown "$SVC_USER":"$SVC_USER" "${STAGING_ROOT}/logs"
chmod 700 "${STAGING_ROOT}/dumps"

# ── 3. Repo checkout ─────────────────────────────────────────────────────────
if [[ "$REPO_URL" != https://* ]]; then
    ensure_deploy_key "$DEPLOY_KEY" "nivesh-staging-app@cloudpe"
    require_repo_access "$REPO_URL" "$BRANCH" "$DEPLOY_KEY"
    GIT_SSH_COMMAND="$(git_ssh_command "$DEPLOY_KEY")"
    export GIT_SSH_COMMAND
fi
GIT=(git -c "safe.directory=${REPO_DIR}")
if [[ -d "${REPO_DIR}/.git" ]]; then
    log "Repo exists at ${REPO_DIR}; fetching ${BRANCH}"
    "${GIT[@]}" -C "$REPO_DIR" fetch --quiet origin "$BRANCH"
    "${GIT[@]}" -C "$REPO_DIR" checkout --quiet "$BRANCH"
    "${GIT[@]}" -C "$REPO_DIR" reset --hard --quiet "origin/${BRANCH}"
else
    log "Cloning ${REPO_URL} (${BRANCH}) → ${REPO_DIR}"
    git clone --quiet --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
fi
log "Repo at $("${GIT[@]}" -C "$REPO_DIR" rev-parse --short HEAD)"
[[ -f "${REPO_DIR}/deploy/cloudpe/app/docker-compose.cloudpe.yml" ]] \
    || fail "Branch ${BRANCH} has no deploy/cloudpe/ — push these scripts to it first."

# ── 4. Env file ──────────────────────────────────────────────────────────────
if [[ -f "$ENV_FILE" ]]; then
    # A generated env has different DB passwords and no PI_PAN_ENCRYPTION_KEY;
    # data restored from the bundle would be undecryptable under it.
    if [[ -n "$BUNDLE" && -f "${BUNDLE}/config/.env.staging" ]] \
            && ! cmp -s "${BUNDLE}/config/.env.staging" "$ENV_FILE"; then
        fail "${ENV_FILE} exists and differs from the bundle's config/.env.staging. Reconcile them (or remove ${ENV_FILE} to take the bundle's) and re-run."
    fi
    log ".env.staging already present; leaving as-is."
elif [[ -n "$BUNDLE" && -f "${BUNDLE}/config/.env.staging" ]]; then
    log "Installing .env.staging from the capture bundle"
    install -m 600 -o root -g root "${BUNDLE}/config/.env.staging" "$ENV_FILE"
else
    # No bundle: the existing staging bootstrap generates one with fresh DB
    # passwords. Application secrets then have to be added by hand.
    log "No env in bundle; generating a fresh one via bootstrap-staging.sh"
    bash "${REPO_DIR}/deploy/nivesh-staging/bootstrap-staging.sh"
fi
chmod 600 "$ENV_FILE"

# ── 5. Origin TLS cert ───────────────────────────────────────────────────────
if [[ -z "$CERT" && -n "$BUNDLE" && -f "${BUNDLE}/config/ssl/cert.pem" ]]; then
    CERT="${BUNDLE}/config/ssl/cert.pem"
    KEY="${BUNDLE}/config/ssl/key.pem"
fi
if [[ -n "$CERT" ]]; then
    install_cert_pair "$CERT" "$KEY" "${SSL_DIR}/cert.pem" "${SSL_DIR}/key.pem"
elif [[ -s "${SSL_DIR}/cert.pem" && -s "${SSL_DIR}/key.pem" ]]; then
    log "Origin cert already installed."
elif $SELF_SIGNED; then
    self_signed_cert "${SSL_DIR}/cert.pem" "${SSL_DIR}/key.pem" "$HOSTNAME_PUBLIC"
else
    fail "No origin cert. Pass --bundle (with config/ssl), --cert/--key, or --self-signed for origin-only testing."
fi

# ── 6. Cloudflare-only origin ────────────────────────────────────────────────
# 172.16.0.0/12 is where docker allocates bridge networks: requests from this
# host to the published port (the on-VM health checks) arrive from the bridge gateway.
CF_CONF="${STAGING_ROOT}/nginx/cloudflare-only.conf"
if $OPEN_ORIGIN; then
    warn "--open-origin: the origin will answer requests from ANY address."
    echo "# origin lockdown disabled by bootstrap.sh --open-origin" > "$CF_CONF"
    chmod 644 "$CF_CONF"
else
    write_cloudflare_allowlist "$CF_CONF" 127.0.0.1 172.16.0.0/12
fi

# ── 7. Cron ──────────────────────────────────────────────────────────────────
log "Installing staging cron entries"
install -m 644 -o root -g root "${REPO_DIR}/deploy/nivesh-staging/cache-clear.cron" \
    /etc/cron.d/nivesh-staging-cache-clear
bash "${REPO_DIR}/deploy/nivesh-staging/install-research-watchlist-refresh.sh"
systemctl enable --now cron >/dev/null 2>&1 || true

# ── 8. Env check ─────────────────────────────────────────────────────────────
log "Checking ${ENV_FILE} (names only)..."
if ! bash "${HERE}/../check-env.sh" app "$ENV_FILE"; then
    warn "Fix the items above in ${ENV_FILE} before running deploy.sh."
fi

cat <<EOF

[${TAG}] Bootstrap finished.

Next:
  1. Restore data (skip to start empty):
       sudo bash ${REPO_DIR}/deploy/cloudpe/app/restore.sh <bundle-dir>
  2. Build + start:
       sudo bash ${REPO_DIR}/deploy/cloudpe/app/deploy.sh ${BRANCH}
EOF
