#!/usr/bin/env bash
# bootstrap.sh — one-time setup of the NIDP staging VM on CloudPe.
#
# Run as root on the NIDP VM. Idempotent: safe to re-run.
#
#   sudo bash deploy/cloudpe/nidp/bootstrap.sh [options]
#
#   --bundle DIR      capture bundle from migrate/capture-gcp-nidp.sh; supplies
#                     nidp.env, the TimescaleDB version, pip freeze, the live
#                     crontab, query_api.env and the origin cert
#   --tsdb-tag TAG    timescale/timescaledb image tag (e.g. 2.26.4-pg16);
#                     required when there is no bundle
#   --cert F --key F  origin cert/key files (override the bundle's)
#   --self-signed     generate a throwaway cert (origin testing only)
#   --repo-url URL    default git@github.com:amitporwal107/nivesh.ai.git
#   --branch NAME     default dev
#   --open-origin     skip the Cloudflare-only allow-list
#
# Keeps the layout NIDP staging has on GCP: host Python 3.11 venv, TimescaleDB
# + DaaS API in Docker, the Query API as a systemd unit, host nginx, cron feeds.
# Starts only Postgres. The DaaS API, Query API and cron are started by
# nidp/deploy.sh, after nidp/restore.sh if restoring.

set -euo pipefail

TAG="nidp-bootstrap"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../lib/common.sh
source "${HERE}/../lib/common.sh"

NIDP_HOME="/opt/nidp-staging"
SVC_USER="nidp-staging"
DEV_REPO="/opt/nidp/dev-repo/nivesh.ai"
ENV_FILE="${NIDP_HOME}/nidp.env"
CLOUDPE_ENV="${NIDP_HOME}/cloudpe.env"
QUERY_ENV="${NIDP_HOME}/query_api.env"
DEPLOY_KEY="/opt/nidp/.ssh/id_ed25519"
HOSTNAME_PUBLIC="staging-data.niveshcopilot.com"
PG_CONTAINER="nidp-postgres-staging"

REPO_URL="git@github.com:amitporwal107/nivesh.ai.git"
BRANCH="dev"
BUNDLE=""
TSDB_TAG=""
CERT=""
KEY=""
SELF_SIGNED=false
OPEN_ORIGIN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bundle)      BUNDLE="$2"; shift 2 ;;
        --tsdb-tag)    TSDB_TAG="$2"; shift 2 ;;
        --cert)        CERT="$2"; shift 2 ;;
        --key)         KEY="$2"; shift 2 ;;
        --repo-url)    REPO_URL="$2"; shift 2 ;;
        --branch)      BRANCH="$2"; shift 2 ;;
        --self-signed) SELF_SIGNED=true; shift ;;
        --open-origin) OPEN_ORIGIN=true; shift ;;
        -h|--help)     sed -n '2,24p' "$0"; exit 0 ;;
        *)             fail "Unknown argument: $1" ;;
    esac
done

require_root
require_apt_os
if [[ -n "$BUNDLE" ]]; then
    verify_bundle "$BUNDLE"
    BUNDLE="$(cd "$BUNDLE" && pwd)"
fi

# The DB image must match the TimescaleDB version the dump was taken from.
if [[ -z "$TSDB_TAG" && -n "$BUNDLE" ]]; then
    src_ver=$(env_get TSDB_VERSION "${BUNDLE}/meta/versions.env")
    [[ -z "$src_ver" ]] || TSDB_TAG="${src_ver}-pg16"
fi
if [[ -z "$TSDB_TAG" && -f "$CLOUDPE_ENV" ]]; then
    TSDB_TAG=$(env_get NIDP_TSDB_TAG "$CLOUDPE_ENV")
fi
[[ -n "$TSDB_TAG" ]] || fail "TimescaleDB version unknown. Pass --bundle (with meta/versions.env) or --tsdb-tag."
# Never swap the image under a data directory initialised by another version.
if [[ -f "$CLOUDPE_ENV" && -f "${NIDP_HOME}/data/postgres/PG_VERSION" ]]; then
    current_tag=$(env_get NIDP_TSDB_TAG "$CLOUDPE_ENV")
    [[ -z "$current_tag" || "$current_tag" == "$TSDB_TAG" ]] \
        || fail "Postgres data already exists under image tag ${current_tag}; refusing to switch to ${TSDB_TAG}. Empty ${NIDP_HOME}/data/postgres first if that is intended."
fi

# ── 1. Packages ──────────────────────────────────────────────────────────────
# Same set as backend/nidp/deploy/vm/bootstrap.sh, plus nginx and build tools
# for wheels that have no binary for this platform.
log "Installing base packages..."
apt-get update -qq
apt_install ca-certificates curl git jq openssl cron logrotate tzdata \
    postgresql-client nginx tesseract-ocr poppler-utils build-essential libpq-dev
set_timezone_ist

# The DaaS container (python:3.11-slim) imports from the host venv, so the
# host venv must be Python 3.11 too. Ubuntu 24.04 ships 3.12 only.
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

# ── 2. Service user + directories ────────────────────────────────────────────
if ! id -u "$SVC_USER" >/dev/null 2>&1; then
    log "Creating service user ${SVC_USER}"
    useradd --system --create-home --home-dir "$NIDP_HOME" --shell /bin/bash "$SVC_USER"
fi
# container_health_collector (cron) calls the docker CLI as this user.
usermod -aG docker "$SVC_USER"
mkdir -p "${NIDP_HOME}"/{logs,run,data/postgres,raw_archives,dumps,cron}
chown "$SVC_USER":"$SVC_USER" "$NIDP_HOME" "${NIDP_HOME}"/{logs,run,raw_archives,cron}
chmod 700 "${NIDP_HOME}/dumps"

# ── 3. Repo checkout ─────────────────────────────────────────────────────────
mkdir -p /opt/nidp
if [[ "$REPO_URL" != https://* ]]; then
    ensure_deploy_key "$DEPLOY_KEY" "nidp-staging@cloudpe"
    require_repo_access "$REPO_URL" "$BRANCH" "$DEPLOY_KEY"
    GIT_SSH_COMMAND="$(git_ssh_command "$DEPLOY_KEY")"
    export GIT_SSH_COMMAND
fi
GIT=(git -c "safe.directory=${DEV_REPO}")
if [[ -d "${DEV_REPO}/.git" ]]; then
    log "Repo exists at ${DEV_REPO}; fetching ${BRANCH}"
    "${GIT[@]}" -C "$DEV_REPO" fetch --quiet origin "$BRANCH"
    "${GIT[@]}" -C "$DEV_REPO" checkout --quiet "$BRANCH"
    "${GIT[@]}" -C "$DEV_REPO" reset --hard --quiet "origin/${BRANCH}"
else
    log "Cloning ${REPO_URL} (${BRANCH}) → ${DEV_REPO}"
    git clone --quiet --branch "$BRANCH" "$REPO_URL" "$DEV_REPO"
fi
# Readable by the service user (cron feeds, Query API) but not writable.
chown -R root:"$SVC_USER" "$DEV_REPO"
chmod -R g+rX "$DEV_REPO"
log "Repo at $("${GIT[@]}" -C "$DEV_REPO" rev-parse --short HEAD)"
[[ -f "${DEV_REPO}/deploy/cloudpe/nidp/docker-compose.cloudpe.yml" ]] \
    || fail "Branch ${BRANCH} has no deploy/cloudpe/ — push these scripts to it first."

# ── 4. Env files ─────────────────────────────────────────────────────────────
if [[ -f "$ENV_FILE" ]]; then
    if [[ -n "$BUNDLE" && -f "${BUNDLE}/config/nidp.env" ]] \
            && ! cmp -s "${BUNDLE}/config/nidp.env" "$ENV_FILE"; then
        warn "${ENV_FILE} differs from the bundle's config/nidp.env — keeping the existing file. Compare them before deploy."
    fi
    log "nidp.env already present; leaving as-is."
elif [[ -n "$BUNDLE" && -f "${BUNDLE}/config/nidp.env" ]]; then
    log "Installing nidp.env from the capture bundle"
    install -m 600 -o "$SVC_USER" -g "$SVC_USER" "${BUNDLE}/config/nidp.env" "$ENV_FILE"
else
    # No bundle (the source VM is unreachable): start from the example with a
    # fresh DB password and fresh internal tokens. The two tokens must also be
    # set on the app VM (NIDP_QUERY_API_TOKEN, NIDP_DAAS_INTERNAL_TOKEN in
    # .env.staging). External API keys still have to be added by hand.
    log "No nidp.env in a bundle — generating one from the example with fresh secrets"
    pg_pass=$(openssl rand -hex 24)
    query_token=$(openssl rand -hex 32)
    daas_token=$(openssl rand -hex 32)
    tmp_env=$(mktemp)
    sed -e "s|^NIDP_PG_PASSWORD=.*|NIDP_PG_PASSWORD=${pg_pass}|" \
        -e "s|^NIDP_POSTGRES_URL=.*|NIDP_POSTGRES_URL=postgresql://nidp_staging:${pg_pass}@localhost:5434/nidp_staging|" \
        -e "s|^NIDP_QUERY_API_TOKEN=.*|NIDP_QUERY_API_TOKEN=${query_token}|" \
        -e "s|^NIVESH_POSTGRES_URL=.*|# NIVESH_POSTGRES_URL= (app Postgres is on another VM and not exposed)|" \
        "${DEV_REPO}/backend/nidp/deploy/vm/nidp.env.staging.example" > "$tmp_env"
    printf '\n# ── DaaS API internal token (must match the app VM) ──\nNIDP_DAAS_INTERNAL_TOKEN=%s\n' "$daas_token" >> "$tmp_env"
    install -m 600 -o "$SVC_USER" -g "$SVC_USER" "$tmp_env" "$ENV_FILE"
    rm -f "$tmp_env"
    unset pg_pass query_token daas_token
fi

printf '# Written by deploy/cloudpe/nidp/bootstrap.sh\nNIDP_TSDB_TAG=%s\n' "$TSDB_TAG" > "$CLOUDPE_ENV"
chmod 644 "$CLOUDPE_ENV"
log "TimescaleDB image: timescale/timescaledb:${TSDB_TAG}"

log "Checking ${ENV_FILE} (names only)..."
ENV_OK=true
bash "${HERE}/../check-env.sh" nidp "$ENV_FILE" || ENV_OK=false
[[ -n "$(env_get NIDP_PG_PASSWORD "$ENV_FILE")" ]] \
    || fail "NIDP_PG_PASSWORD is not set in ${ENV_FILE} — Postgres cannot be initialised."
[[ "$(env_get NIDP_PG_PASSWORD "$ENV_FILE")" != *CHANGEME* ]] \
    || fail "NIDP_PG_PASSWORD is still a placeholder in ${ENV_FILE}. Set it, then re-run."

# ── 5. Postgres (only) ───────────────────────────────────────────────────────
BASE_COMPOSE="${DEV_REPO}/backend/nidp/deploy/vm/docker-compose.staging.yml"
OVERRIDE_COMPOSE="${DEV_REPO}/deploy/cloudpe/nidp/docker-compose.cloudpe.yml"
[[ -f "$OVERRIDE_COMPOSE" ]] || fail "Missing ${OVERRIDE_COMPOSE} on branch ${BRANCH}."
dc() { docker compose --env-file "$ENV_FILE" --env-file "$CLOUDPE_ENV" -f "$BASE_COMPOSE" -f "$OVERRIDE_COMPOSE" "$@"; }

docker network inspect nidp-staging-bridge >/dev/null 2>&1 \
    || { log "Creating docker network nidp-staging-bridge"; docker network create nidp-staging-bridge >/dev/null; }
log "Starting ${PG_CONTAINER}..."
dc up -d postgres
wait_container_healthy "$PG_CONTAINER" 60 2

# ── 6. Venv, logrotate, run_service.sh ───────────────────────────────────────
# backend/nidp/deploy/vm/bootstrap-staging.sh is not called: it brings Postgres
# up from the base compose file alone (which fails here on the 10.160.0.3 port
# bind) and `chown -R`s the whole home, Postgres data directory included. Its
# logrotate config and run_service.sh wrapper are taken from it verbatim so
# there is still one definition of each.
STAGING_BOOTSTRAP="${DEV_REPO}/backend/nidp/deploy/vm/bootstrap-staging.sh"

if [[ ! -x "${NIDP_HOME}/venv/bin/python" ]]; then
    log "Creating Python 3.11 venv at ${NIDP_HOME}/venv"
    sudo -u "$SVC_USER" python3.11 -m venv "${NIDP_HOME}/venv"
fi
log "Installing NIDP requirements into the venv..."
sudo -u "$SVC_USER" "${NIDP_HOME}/venv/bin/pip" install --quiet --upgrade pip
sudo -u "$SVC_USER" "${NIDP_HOME}/venv/bin/pip" install --quiet \
    -r "${DEV_REPO}/backend/nidp/deploy/requirements.txt"

sed -n "/logrotate.d\/nidp-staging <<'EOF'/,/^EOF\$/p" "$STAGING_BOOTSTRAP" | sed '1d;$d' \
    > /etc/logrotate.d/nidp-staging
grep -q '/opt/nidp-staging/logs' /etc/logrotate.d/nidp-staging \
    || fail "Could not extract the logrotate config from ${STAGING_BOOTSTRAP}."

RUN_SERVICE="${NIDP_HOME}/run_service.sh"
sed -n "/<<'RSEOF'/,/^RSEOF\$/p" "$STAGING_BOOTSTRAP" | sed '1d;$d' > "${RUN_SERVICE}.new"
head -1 "${RUN_SERVICE}.new" | grep -q '^#!/usr/bin/env bash' \
    || fail "Could not extract run_service.sh from ${STAGING_BOOTSTRAP}."
install -m 755 -o "$SVC_USER" -g "$SVC_USER" "${RUN_SERVICE}.new" "$RUN_SERVICE"
rm -f "${RUN_SERVICE}.new"
if [[ -n "$BUNDLE" && -f "${BUNDLE}/config/run_service.sh" ]] \
        && ! diff -q "${BUNDLE}/config/run_service.sh" "$RUN_SERVICE" >/dev/null; then
    warn "run_service.sh on the GCP VM differs from the repo version installed here — compare with ${BUNDLE}/config/run_service.sh"
fi

# requirements.txt does not list everything the services import (pyarrow,
# duckdb, yfinance, ...). The capture bundle carries the live venv's freeze.
if [[ -n "$BUNDLE" && -s "${BUNDLE}/config/pip-freeze.txt" ]]; then
    FREEZE="${NIDP_HOME}/pip-freeze.captured.txt"
    grep -vE '^(-e |#)| @ ' "${BUNDLE}/config/pip-freeze.txt" > "$FREEZE" || true
    skipped=$(grep -cE '^(-e |#)| @ ' "${BUNDLE}/config/pip-freeze.txt" || true)
    chown "$SVC_USER":"$SVC_USER" "$FREEZE"
    log "Installing the captured venv freeze ($(wc -l < "$FREEZE") pins, ${skipped} local/editable lines skipped)..."
    if ! sudo -u "$SVC_USER" "${NIDP_HOME}/venv/bin/pip" install --quiet -r "$FREEZE"; then
        warn "Installing the captured freeze FAILED — the venv has requirements.txt only."
        warn "Services importing undeclared packages will fail until this is resolved."
    fi
else
    warn "No pip freeze in the bundle — the venv has requirements.txt only (missing e.g. pyarrow, duckdb, yfinance)."
fi

# ── 7. Query API unit ────────────────────────────────────────────────────────
UNIT_SRC="${DEV_REPO}/deploy/cloudpe/nidp/nidp-staging-query-api.service"
UNIT_DST="/etc/systemd/system/nidp-staging-query-api.service"
if [[ ! -f "$QUERY_ENV" ]]; then
    if [[ -n "$BUNDLE" && -f "${BUNDLE}/config/query_api.env" ]]; then
        log "Installing query_api.env from the capture bundle"
        install -m 640 -o root -g "$SVC_USER" "${BUNDLE}/config/query_api.env" "$QUERY_ENV"
    else
        : > "$QUERY_ENV"
        chown root:"$SVC_USER" "$QUERY_ENV"; chmod 640 "$QUERY_ENV"
    fi
fi
# nginx.staging.conf proxies /query/ to 8091.
[[ -n "$(env_get NIDP_QUERY_API_PORT "$QUERY_ENV")" ]] || printf '\nNIDP_QUERY_API_PORT=8091\n' >> "$QUERY_ENV"
install -m 644 "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload
systemctl enable nidp-staging-query-api.service >/dev/null 2>&1
if [[ -n "$BUNDLE" && -f "${BUNDLE}/config/nidp-staging-query-api.service" ]]; then
    if diff -u "${BUNDLE}/config/nidp-staging-query-api.service" "$UNIT_SRC" > "${NIDP_HOME}/query-api-unit.diff"; then
        log "Query API unit is identical to the one captured from GCP."
    else
        warn "Query API unit differs from the one captured from GCP — review ${NIDP_HOME}/query-api-unit.diff"
    fi
fi

# ── 8. nginx ─────────────────────────────────────────────────────────────────
if [[ -z "$CERT" && -n "$BUNDLE" && -f "${BUNDLE}/config/ssl/data.crt" ]]; then
    CERT="${BUNDLE}/config/ssl/data.crt"
    KEY="${BUNDLE}/config/ssl/data.key"
fi
if [[ -n "$CERT" ]]; then
    install_cert_pair "$CERT" "$KEY" /etc/nginx/ssl/data.crt /etc/nginx/ssl/data.key
elif [[ -s /etc/nginx/ssl/data.crt && -s /etc/nginx/ssl/data.key ]]; then
    log "Origin cert already installed."
elif $SELF_SIGNED; then
    self_signed_cert /etc/nginx/ssl/data.crt /etc/nginx/ssl/data.key "$HOSTNAME_PUBLIC"
else
    fail "No origin cert. Pass --bundle (with config/ssl), --cert/--key, or --self-signed for origin-only testing."
fi

# nginx.staging.conf uses the nidp_api zone, which on GCP is defined by the
# prod vhost sharing the same nginx. Same definition as vm/nginx.conf.
cat > /etc/nginx/conf.d/nidp-staging-ratelimit.conf <<'EOF'
# Rate-limit zone — server-to-server APIs. 100 r/s per IP, burst 200.
limit_req_zone $binary_remote_addr zone=nidp_api:10m rate=100r/s;
EOF
CF_CONF=/etc/nginx/conf.d/00-cloudflare-only.conf
if $OPEN_ORIGIN; then
    warn "--open-origin: the origin will answer requests from ANY address."
    echo "# origin lockdown disabled by bootstrap.sh --open-origin" > "$CF_CONF"
else
    write_cloudflare_allowlist "$CF_CONF" 127.0.0.1 ::1
fi
install -m 644 "${DEV_REPO}/backend/nidp/deploy/vm/nginx.staging.conf" /etc/nginx/sites-available/nidp-staging
ln -sf /etc/nginx/sites-available/nidp-staging /etc/nginx/sites-enabled/nidp-staging
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx >/dev/null 2>&1
systemctl reload nginx 2>/dev/null || systemctl restart nginx
log "nginx vhost ${HOSTNAME_PUBLIC} installed."

# ── 9. Stage the crontab (not enabled yet) ───────────────────────────────────
# Feeds must not run against an empty database, so the file is only staged;
# `nidp/deploy.sh --install-cron` puts it in /etc/cron.d.
# gate4_replication_check compares this DB with a prod Postgres on the same
# host (5433). There is no prod DB on this VM, so those lines are dropped.
STAGED_CRON="${NIDP_HOME}/cron/nidp-staging.cron"
if [[ -n "$BUNDLE" && -s "${BUNDLE}/config/cron/nidp-staging" ]]; then
    CRON_SRC="${BUNDLE}/config/cron/nidp-staging"
    log "Staging the crontab captured from the live GCP VM"
else
    # No capture: the CloudPe schedule, with the feeds verified on this VM enabled.
    CRON_SRC="${DEV_REPO}/deploy/cloudpe/nidp/nidp-staging.cron"
    log "No captured crontab — staging deploy/cloudpe/nidp/nidp-staging.cron"
fi
grep -v 'gate4_replication_check' "$CRON_SRC" > "$STAGED_CRON"
chmod 644 "$STAGED_CRON"
log "Staged $(grep -cvE '^\s*(#|$|[A-Z_]+=)' "$STAGED_CRON" || true) active cron entries → ${STAGED_CRON}"
systemctl enable --now cron >/dev/null 2>&1 || true

$ENV_OK || warn "check-env reported problems in ${ENV_FILE} (see above) — fix them before deploy.sh."

cat <<EOF

[${TAG}] Bootstrap finished.

Next:
  1. Restore data (skip to start empty, then run deploy.sh --migrate instead):
       sudo bash ${DEV_REPO}/deploy/cloudpe/nidp/restore.sh <bundle-dir>
  2. Start the services and enable cron:
       sudo bash ${DEV_REPO}/deploy/cloudpe/nidp/deploy.sh ${BRANCH} --install-cron
EOF
