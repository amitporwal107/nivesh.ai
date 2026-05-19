#!/usr/bin/env bash
# install_query_api.sh — install the NIDP Query API as a systemd
# service on nidp-stack-vm.
#
# Idempotent: re-run any time to update the unit/env or the code
# (after `deploy.sh` pulls latest from origin).
#
# Usage (run on the VM, NOT in the pod):
#   sudo bash /opt/nidp/repo/backend/nidp/deploy/vm/install_query_api.sh
#
# Or remote-invoke from the pod:
#   ssh ... "sudo NIDP_QUERY_API_TOKEN=<token> bash /opt/nidp/repo/.../install_query_api.sh"

set -euo pipefail

NIDP_HOME=/opt/nidp
ENV_FILE="$NIDP_HOME/query_api.env"
UNIT_SRC="$NIDP_HOME/repo/backend/nidp/deploy/vm/nidp-query-api.service"
UNIT_DST="/etc/systemd/system/nidp-query-api.service"

PORT="${NIDP_QUERY_API_PORT:-8090}"
TOKEN="${NIDP_QUERY_API_TOKEN:-}"

log() { printf '\033[1;36m[install_query_api]\033[0m %s\n' "$*"; }

# ── 1. Generate / preserve token ───────────────────────────────────
if [[ -z "$TOKEN" ]]; then
  if [[ -f "$ENV_FILE" ]] && grep -q '^NIDP_QUERY_API_TOKEN=' "$ENV_FILE"; then
    log "Reusing existing token from $ENV_FILE"
    TOKEN=$(grep '^NIDP_QUERY_API_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2-)
  else
    log "No token supplied — generating a fresh 64-char hex token"
    TOKEN=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
  fi
fi

# ── 2. Write env file (mode 0640, owned by root:nidp) ──────────────
log "Writing $ENV_FILE"
tee "$ENV_FILE" >/dev/null <<EOF
NIDP_QUERY_API_TOKEN=$TOKEN
NIDP_QUERY_API_PORT=$PORT
GCP_PROJECT=niveshdataintelligence
EOF
chown root:nidp "$ENV_FILE"
chmod 0640 "$ENV_FILE"

# ── 3. Install systemd unit ────────────────────────────────────────
log "Installing $UNIT_DST"
cp "$UNIT_SRC" "$UNIT_DST"
chmod 0644 "$UNIT_DST"

# ── 4. Reload + enable + (re)start ─────────────────────────────────
systemctl daemon-reload
systemctl enable nidp-query-api.service >/dev/null 2>&1
systemctl restart nidp-query-api.service

# ── 5. Health check ────────────────────────────────────────────────
sleep 2
if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  log "✓ Service healthy on port $PORT"
else
  log "✗ Service did not come up — check: journalctl -u nidp-query-api -n 50 --no-pager"
  systemctl status nidp-query-api.service --no-pager || true
  exit 1
fi

# ── 6. Print connection details (token only on stdout, never logged) ─
log "================================================================"
log "NIDP Query API is running on port $PORT"
log "  Public URL:  http://34.47.191.39:$PORT"
log "  Token:       $TOKEN"
log "  Status:      systemctl status nidp-query-api"
log "  Logs:        journalctl -u nidp-query-api -f"
log "================================================================"
