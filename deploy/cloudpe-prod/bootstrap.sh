#!/usr/bin/env bash
# bootstrap.sh — one-time setup of the CloudPe PRODUCTION VM (app + NIDP on one host).
#
# Run as root on the prod VM. Idempotent: safe to re-run.
#
#   sudo bash bootstrap.sh --tsdb-tag TAG --ci-pubkey FILE [options]
#
#   --tsdb-tag TAG     timescale/timescaledb image tag (e.g. 2.26.4-pg16). Must equal the
#                      version the data was dumped from. Required on the first run.
#   --ci-pubkey FILE   public key GitHub Actions logs in with (user ci-deploy; sudo is
#                      limited to ci-deploy.sh). Required on the first run.
#   --cert F --key F   Cloudflare Origin CA cert + key for niveshcopilot.com and *.niveshcopilot.com
#   --self-signed      throwaway cert (origin testing only; Cloudflare Full-strict will refuse it)
#   --freeze FILE      `pip freeze` of the NIDP venv to install on top of requirements.txt
#                      (requirements.txt omits pyarrow, duckdb, yfinance, ...)
#   --repo-url URL     default git@github.com:amitporwal107/nivesh.ai.git
#   --branch NAME      branch to check out first (default main)
#   --open-origin      skip the Cloudflare-only allow-list (origin reachable by anyone)
#
# Layout it creates:
#   /opt/nivesh/{repo,data,logs,dumps,downloads,.ssh}  + .env.prod (not created here)
#   /opt/nidp/{data,logs,run,raw_archives,dumps,cron,venv} + nidp.env (not created here)
#   /opt/nidp/repo → /opt/nivesh/repo (ONE checkout for both stacks)
#
# It does NOT write the env files (they hold secrets copied from staging: see
# clone-from-staging.sh) and does NOT start the stacks (deploy-nidp.sh / deploy-app.sh).

set -euo pipefail

TAG="prod-bootstrap"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "${HERE}/lib.sh"

REPO_URL="$REPO_URL_DEFAULT"
BRANCH="main"
TSDB_TAG=""
CI_PUBKEY=""
CERT=""
KEY=""
FREEZE=""
SELF_SIGNED=false
OPEN_ORIGIN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tsdb-tag)    TSDB_TAG="$2"; shift 2 ;;
        --ci-pubkey)   CI_PUBKEY="$2"; shift 2 ;;
        --cert)        CERT="$2"; shift 2 ;;
        --key)         KEY="$2"; shift 2 ;;
        --freeze)      FREEZE="$2"; shift 2 ;;
        --repo-url)    REPO_URL="$2"; shift 2 ;;
        --branch)      BRANCH="$2"; shift 2 ;;
        --self-signed) SELF_SIGNED=true; shift ;;
        --open-origin) OPEN_ORIGIN=true; shift ;;
        -h|--help)     sed -n '2,30p' "$0"; exit 0 ;;
        *)             fail "Unknown argument: $1" ;;
    esac
done

require_root
require_apt_os

if [[ -z "$TSDB_TAG" && -f "$NIDP_CLOUDPE_ENV" ]]; then
    TSDB_TAG=$(env_get NIDP_TSDB_TAG "$NIDP_CLOUDPE_ENV")
fi
[[ -n "$TSDB_TAG" ]] || fail "TimescaleDB version unknown. Pass --tsdb-tag (the version the data was dumped from)."
if [[ -f "$NIDP_CLOUDPE_ENV" && -f "${NIDP_ROOT}/data/postgres/PG_VERSION" ]]; then
    current_tag=$(env_get NIDP_TSDB_TAG "$NIDP_CLOUDPE_ENV")
    [[ -z "$current_tag" || "$current_tag" == "$TSDB_TAG" ]] \
        || fail "Postgres data already exists under image tag ${current_tag}; refusing to switch to ${TSDB_TAG}."
fi
[[ -n "$CI_PUBKEY" || -f "/home/${CI_USER}/.ssh/authorized_keys" ]] \
    || fail "Pass --ci-pubkey FILE (the public key GitHub Actions deploys with)."
[[ -z "$CI_PUBKEY" || -s "$CI_PUBKEY" ]] || fail "Cannot read ${CI_PUBKEY}"

# ── 1. Packages, timezone, Python 3.11, Docker ───────────────────────────────
log "Installing base packages..."
apt-get update -qq
apt_install ca-certificates curl git jq openssl cron logrotate tzdata \
    postgresql-client nginx tesseract-ocr poppler-utils build-essential libpq-dev
set_timezone_ist

# The DaaS container (python:3.11-slim) imports from the host venv, so the venv must be 3.11.
# Ubuntu 24.04 ships 3.12 only.
if ! command -v python3.11 >/dev/null 2>&1; then
    if [[ "$OS_ID" == "ubuntu" ]]; then
        log "Installing Python 3.11 from the deadsnakes PPA..."
        apt_install software-properties-common
        add-apt-repository -y ppa:deadsnakes/ppa >/dev/null
        apt-get update -qq
    fi
    apt_install python3.11 python3.11-venv python3.11-dev
fi
log "Python: $(python3.11 --version)"
install_docker

# ── 2. Users + directories ───────────────────────────────────────────────────
if ! id -u "$SVC_USER" >/dev/null 2>&1; then
    log "Creating service user ${SVC_USER}"
    useradd --system --create-home --home-dir "$NIDP_ROOT" --shell /bin/bash "$SVC_USER"
fi
usermod -aG docker "$SVC_USER"   # container_health_collector (cron) calls the docker CLI as this user

if ! id -u "$CI_USER" >/dev/null 2>&1; then
    log "Creating CI user ${CI_USER}"
    useradd --create-home --shell /bin/bash "$CI_USER"
fi
if [[ -n "$CI_PUBKEY" ]]; then
    install -d -m 700 -o "$CI_USER" -g "$CI_USER" "/home/${CI_USER}/.ssh"
    install -m 600 -o "$CI_USER" -g "$CI_USER" "$CI_PUBKEY" "/home/${CI_USER}/.ssh/authorized_keys"
fi
# The CI user may run exactly one command as root (and owns downloads/ so the APK
# publish job can write without sudo).
SUDOERS=/etc/sudoers.d/92-ci-deploy-prod
echo "${CI_USER} ALL=(root) NOPASSWD: /usr/bin/bash ${REPO_DIR}/deploy/cloudpe-prod/ci-deploy.sh *" > "${SUDOERS}.new"
visudo -cf "${SUDOERS}.new" >/dev/null || { rm -f "${SUDOERS}.new"; fail "generated sudoers entry is invalid"; }
install -m 440 -o root -g root "${SUDOERS}.new" "$SUDOERS"; rm -f "${SUDOERS}.new"

log "Ensuring directories under ${APP_ROOT}/ and ${NIDP_ROOT}/"
mkdir -p "${APP_ROOT}"/{data/{postgres,mongo,redis,app},logs,dumps,downloads,.ssh} \
         "${NIDP_ROOT}"/{logs,run,data/postgres,raw_archives,dumps,cron}
chmod 700 "${APP_ROOT}/dumps" "${NIDP_ROOT}/dumps" "${APP_ROOT}/.ssh"
chown "$CI_USER":"$CI_USER" "${APP_ROOT}/downloads"
chown "$SVC_USER":"$SVC_USER" "$NIDP_ROOT" "${NIDP_ROOT}"/{logs,run,raw_archives,cron}
# Traversal only (no o+r): the secrets below are protected by their own modes.
chmod 755 "$APP_ROOT"

# ── 3. Repo checkout (one, shared) ───────────────────────────────────────────
if [[ "$REPO_URL" != https://* ]]; then
    ensure_deploy_key "$DEPLOY_KEY" "nivesh-prod@cloudpe"
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
chown -R root:"$SVC_USER" "$REPO_DIR"
chmod -R g+rX "$REPO_DIR"
[[ -f "${REPO_DIR}/deploy/cloudpe-prod/app/docker-compose.yml" ]] \
    || fail "Branch ${BRANCH} has no deploy/cloudpe-prod/ — push these scripts to it first."
if [[ -e "${NIDP_ROOT}/repo" && ! -L "${NIDP_ROOT}/repo" ]]; then
    fail "${NIDP_ROOT}/repo exists and is not a symlink — move it aside."
fi
ln -sfn "$REPO_DIR" "${NIDP_ROOT}/repo"
log "Repo at $("${GIT[@]}" -C "$REPO_DIR" rev-parse --short HEAD); ${NIDP_ROOT}/repo → ${REPO_DIR}"

# ── 4. NIDP: image tag, venv, run_service.sh, Query API unit ─────────────────
printf '# Written by deploy/cloudpe-prod/bootstrap.sh\nNIDP_TSDB_TAG=%s\n' "$TSDB_TAG" > "$NIDP_CLOUDPE_ENV"
chmod 644 "$NIDP_CLOUDPE_ENV"
log "TimescaleDB image: timescale/timescaledb:${TSDB_TAG}"

if [[ ! -x "${NIDP_ROOT}/venv/bin/python" ]]; then
    log "Creating Python 3.11 venv at ${NIDP_ROOT}/venv"
    sudo -u "$SVC_USER" python3.11 -m venv "${NIDP_ROOT}/venv"
fi
log "Installing NIDP requirements into the venv..."
sudo -u "$SVC_USER" "${NIDP_ROOT}/venv/bin/pip" install --quiet --upgrade pip
sudo -u "$SVC_USER" "${NIDP_ROOT}/venv/bin/pip" install --quiet -r "${REPO_DIR}/backend/nidp/deploy/requirements.txt"
if [[ -n "$FREEZE" ]]; then
    [[ -s "$FREEZE" ]] || fail "Cannot read ${FREEZE}"
    FZ="${NIDP_ROOT}/pip-freeze.captured.txt"
    grep -vE '^(-e |#)| @ ' "$FREEZE" > "$FZ" || true
    chown "$SVC_USER":"$SVC_USER" "$FZ"
    log "Installing the captured venv freeze ($(wc -l < "$FZ") pins)..."
    if ! sudo -u "$SVC_USER" "${NIDP_ROOT}/venv/bin/pip" install --quiet -r "$FZ"; then
        warn "Installing the captured freeze FAILED — the venv has requirements.txt only."
        warn "Services importing undeclared packages (pyarrow, duckdb, yfinance, ...) will fail."
    fi
else
    warn "No --freeze given: the venv has requirements.txt only (missing e.g. pyarrow, duckdb, yfinance)."
fi

# Logrotate: the repo's own prod config (heredoc in vm/bootstrap.sh) so there is one definition.
sed -n "/logrotate.d\/nidp <<'EOF'/,/^EOF\$/p" "${REPO_DIR}/backend/nidp/deploy/vm/bootstrap.sh" | sed '1d;$d' \
    > /etc/logrotate.d/nidp
grep -q '/opt/nidp/logs' /etc/logrotate.d/nidp \
    || fail "Could not extract the logrotate config from backend/nidp/deploy/vm/bootstrap.sh."

if [[ ! -f "$NIDP_QUERY_ENV" ]]; then
    : > "$NIDP_QUERY_ENV"; chown root:"$SVC_USER" "$NIDP_QUERY_ENV"; chmod 640 "$NIDP_QUERY_ENV"
fi
[[ -n "$(env_get NIDP_QUERY_API_PORT "$NIDP_QUERY_ENV")" ]] || printf 'NIDP_QUERY_API_PORT=8090\n' >> "$NIDP_QUERY_ENV"
install -m 644 "${REPO_DIR}/deploy/cloudpe-prod/nidp/nidp-query-api.service" /etc/systemd/system/nidp-query-api.service
systemctl daemon-reload
systemctl enable nidp-query-api.service >/dev/null 2>&1

# ── 5. Host nginx ────────────────────────────────────────────────────────────
if [[ -n "$CERT" ]]; then
    install_cert_pair "$CERT" "$KEY" /etc/nginx/ssl/prod.crt /etc/nginx/ssl/prod.key
elif [[ -s /etc/nginx/ssl/prod.crt && -s /etc/nginx/ssl/prod.key ]]; then
    log "Origin cert already installed."
elif $SELF_SIGNED; then
    self_signed_cert /etc/nginx/ssl/prod.crt /etc/nginx/ssl/prod.key "$HOSTNAME_APP"
else
    fail "No origin cert. Pass --cert/--key (Cloudflare Origin CA) or --self-signed for origin-only testing."
fi

cat > /etc/nginx/conf.d/nivesh-prod-ratelimit.conf <<'CONF'
# Rate-limit zone for the data.* vhost — server-to-server APIs. 100 r/s per IP, burst 200.
limit_req_zone $binary_remote_addr zone=nidp_api:10m rate=100r/s;
CONF
CF_CONF=/etc/nginx/conf.d/00-cloudflare-only.conf
if $OPEN_ORIGIN; then
    warn "--open-origin: the origin will answer requests from ANY address."
    echo "# origin lockdown disabled by bootstrap.sh --open-origin" > "$CF_CONF"
else
    # 172.16.0.0/12: docker bridge gateways (on-VM health checks and the backend → data.* hairpin).
    write_cloudflare_allowlist "$CF_CONF" 127.0.0.1 ::1 172.16.0.0/12
fi
install -m 644 "${REPO_DIR}/deploy/cloudpe-prod/edge/nginx-prod.conf" /etc/nginx/sites-available/nivesh-prod
ln -sf /etc/nginx/sites-available/nivesh-prod /etc/nginx/sites-enabled/nivesh-prod
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx >/dev/null 2>&1
log "nginx vhosts for ${HOSTNAME_APP} and ${HOSTNAME_DATA} installed (reloaded by the deploy scripts once the upstreams exist)."

systemctl enable --now cron >/dev/null 2>&1 || true

cat <<EOF

[${TAG}] Bootstrap finished.

Next:
  1. Create ${APP_ENV_FILE} and ${NIDP_ENV_FILE}  (clone-from-staging.sh does this from the staging env files)
  2. NIDP:  sudo bash ${REPO_DIR}/deploy/cloudpe-prod/deploy-nidp.sh ${BRANCH}   # then restore data before --install-cron
  3. App:   sudo bash ${REPO_DIR}/deploy/cloudpe-prod/deploy-app.sh ${BRANCH}
EOF
