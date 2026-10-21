#!/usr/bin/env bash
# install.sh — install or update the Claude Code gateway on the app VM.
#
#   sudo bash deploy/cloudpe/app/claude-gateway/install.sh
#
# Installs gateway.py and the systemd unit, creates the gateway's bearer token on
# first run, and points the backend's env file at the gateway. The backend
# container has to be recreated afterwards to pick up the new values
# (deploy/cloudpe/app/deploy.sh dev --backend-only). Secrets are never printed.
#
# Idempotent.

set -euo pipefail

TAG="claude-gateway"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../../lib/common.sh
source "${HERE}/../../lib/common.sh"

GATEWAY_ENV="/etc/claude-gateway.env"
APP_ENV="${APP_ENV_FILE:-/opt/nivesh-staging/.env.staging}"
PORT="${CLAUDE_GATEWAY_PORT:-8790}"
MODEL="${CLAUDE_GATEWAY_MODEL:-claude-sonnet-5-5}"
RUN_AS="deploy"

require_root
[[ -x "/home/${RUN_AS}/.local/bin/claude" ]] || fail "Claude Code CLI not found for user ${RUN_AS}."

# The address containers reach the host on (host.docker.internal -> docker0).
BRIDGE_IP="$(ip -4 -o addr show docker0 | awk '{print $4}' | cut -d/ -f1)"
[[ -n "${BRIDGE_IP}" ]] || fail "docker0 has no IPv4 address; is Docker running?"

set_kv() {   # <file> <key> <value> — add or replace one KEY=VALUE line
    local file="$1" key="$2" value="$3" tmp
    tmp="$(mktemp)"
    grep -v "^${key}=" "${file}" > "${tmp}" || true
    printf '%s=%s\n' "${key}" "${value}" >> "${tmp}"
    cat "${tmp}" > "${file}"
    rm -f "${tmp}"
}

if [[ ! -s "${GATEWAY_ENV}" ]]; then
    log "Creating ${GATEWAY_ENV} with a new token"
    ( umask 077; printf 'CLAUDE_GATEWAY_TOKEN=%s\n' "$(openssl rand -hex 32)" > "${GATEWAY_ENV}" )
fi
set_kv "${GATEWAY_ENV}" CLAUDE_GATEWAY_HOST "${BRIDGE_IP}"
set_kv "${GATEWAY_ENV}" CLAUDE_GATEWAY_PORT "${PORT}"
set_kv "${GATEWAY_ENV}" CLAUDE_GATEWAY_MODEL "${MODEL}"
set_kv "${GATEWAY_ENV}" CLAUDE_GATEWAY_WORK_DIR /var/lib/claude-gateway/work
chown root:root "${GATEWAY_ENV}"
chmod 600 "${GATEWAY_ENV}"

install -d -m 755 /opt/claude-gateway
install -m 644 "${HERE}/gateway.py" /opt/claude-gateway/gateway.py
install -m 644 "${HERE}/claude-gateway.service" /etc/systemd/system/claude-gateway.service
systemctl daemon-reload
systemctl enable claude-gateway >/dev/null 2>&1
systemctl restart claude-gateway

wait_http_ok "gateway health on ${BRIDGE_IP}:${PORT}" 10 "http://${BRIDGE_IP}:${PORT}/health"

if [[ -f "${APP_ENV}" ]]; then
    token="$(grep '^CLAUDE_GATEWAY_TOKEN=' "${GATEWAY_ENV}" | cut -d= -f2-)"
    set_kv "${APP_ENV}" CLAUDE_CODE_API_URL "http://host.docker.internal:${PORT}/v1"
    set_kv "${APP_ENV}" CLAUDE_CODE_API_TOKEN "${token}"
    set_kv "${APP_ENV}" COPILOT_LLM_PROVIDER claude_code
    log "Updated ${APP_ENV}: CLAUDE_CODE_API_URL, CLAUDE_CODE_API_TOKEN, COPILOT_LLM_PROVIDER=claude_code"
    log "Recreate the backend to apply: deploy/cloudpe/app/deploy.sh dev --backend-only"
else
    warn "${APP_ENV} not found; set CLAUDE_CODE_API_URL, CLAUDE_CODE_API_TOKEN and COPILOT_LLM_PROVIDER=claude_code yourself."
fi
