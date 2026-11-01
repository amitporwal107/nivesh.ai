#!/usr/bin/env bash
# lib.sh — constants and helpers shared by the CloudPe PRODUCTION scripts. Source, don't run.
#
# Production runs on ONE CloudPe VM (both stacks): the Nivesh app (Docker Compose)
# and the NIDP stack (TimescaleDB + DaaS in Docker, Query API under systemd, cron
# feeds). The host nginx is the only thing on :80/:443; it proxies the app to the
# edge container on 127.0.0.1:8444 and data.<domain> to the NIDP ports.
#
# Callers set TAG (log prefix) before sourcing.

TAG="${TAG:-cloudpe-prod}"
PROD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../cloudpe/lib/common.sh
source "${PROD_DIR}/../cloudpe/lib/common.sh"

APP_ROOT="/opt/nivesh"
NIDP_ROOT="/opt/nidp"
# ONE git checkout serves both stacks, so they always run the same commit.
# /opt/nidp/repo is a symlink to it (run_service.sh and the Query API unit expect that path).
REPO_DIR="${APP_ROOT}/repo"
DEPLOY_KEY="${APP_ROOT}/.ssh/id_ed25519"
REPO_URL_DEFAULT="git@github.com:amitporwal107/nivesh.ai.git"

APP_ENV_FILE="${APP_ROOT}/.env.prod"
NIDP_ENV_FILE="${NIDP_ROOT}/nidp.env"
NIDP_CLOUDPE_ENV="${NIDP_ROOT}/cloudpe.env"
NIDP_QUERY_ENV="${NIDP_ROOT}/query_api.env"

APP_COMPOSE="${REPO_DIR}/deploy/cloudpe-prod/app/docker-compose.yml"
NIDP_COMPOSE="${REPO_DIR}/deploy/cloudpe-prod/nidp/docker-compose.yml"

HOSTNAME_APP="niveshcopilot.com"
HOSTNAME_DATA="data.niveshcopilot.com"

SVC_USER="nidp"          # owns /opt/nidp, runs cron feeds and the Query API
CI_USER="${CI_USER:-ci-deploy}"

# Pull the shared checkout to origin/<branch> with the VM's read-only deploy key.
refresh_repo() {  # <branch>
    local branch="$1"
    if [[ -f "$DEPLOY_KEY" ]]; then
        GIT_SSH_COMMAND="$(git_ssh_command "$DEPLOY_KEY")"
        export GIT_SSH_COMMAND
    fi
    local git=(git -c "safe.directory=${REPO_DIR}" -C "$REPO_DIR")
    log "Refreshing ${REPO_DIR} (branch=${branch})..."
    "${git[@]}" fetch --quiet origin "$branch"
    "${git[@]}" checkout --quiet "$branch"
    "${git[@]}" reset --hard --quiet "origin/${branch}"
    # The NIDP user reads the checkout (cron feeds, Query API, DaaS bind mount) but never writes it.
    chown -R root:"$SVC_USER" "$REPO_DIR"
    chmod -R g+rX "$REPO_DIR"
    log "At $("${git[@]}" log -1 --format='%h %s')"
}
