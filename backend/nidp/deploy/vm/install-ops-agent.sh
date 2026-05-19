#!/usr/bin/env bash
# install-ops-agent.sh — install/refresh the Google Cloud Ops Agent on the
# NIDP VM so that cron job logs at /opt/nidp/logs/*/*.log are forwarded to
# Cloud Logging (where they show up as jsonPayload.application="nidp-console").
#
# Idempotent — safe to re-run. Called from bootstrap.sh on first boot and
# from deploy.sh on every deploy (refreshes config if the YAML changed).
#
# Standalone usage (on an existing VM):
#   sudo bash /opt/nidp/repo/backend/nidp/deploy/vm/install-ops-agent.sh

set -euo pipefail

CONFIG_SRC_DEFAULT=/opt/nidp/repo/backend/nidp/deploy/vm/ops-agent-config.yaml
CONFIG_SRC="${OPS_AGENT_CONFIG_SRC:-$CONFIG_SRC_DEFAULT}"
CONFIG_DST=/etc/google-cloud-ops-agent/config.yaml

log() { printf '\033[1;36m[ops-agent]\033[0m %s\n' "$*"; }

if [[ $EUID -ne 0 ]]; then
    echo "must run as root (use sudo)" >&2
    exit 1
fi

[[ -f "$CONFIG_SRC" ]] || { echo "config not found at $CONFIG_SRC" >&2; exit 1; }

# ── 1. Install the agent (once) ──────────────────────────────────────────────
if ! systemctl list-unit-files google-cloud-ops-agent.service >/dev/null 2>&1; then
    log "installing google-cloud-ops-agent..."
    TMP=$(mktemp)
    curl -fsSL https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh -o "$TMP"
    bash "$TMP" --also-install
    rm -f "$TMP"
else
    log "google-cloud-ops-agent already installed"
fi

# ── 2. Install / refresh config ──────────────────────────────────────────────
install -d -m 0755 /etc/google-cloud-ops-agent
if ! cmp -s "$CONFIG_SRC" "$CONFIG_DST"; then
    log "config changed — installing $CONFIG_SRC → $CONFIG_DST"
    install -m 0644 "$CONFIG_SRC" "$CONFIG_DST"
    log "restarting google-cloud-ops-agent..."
    systemctl restart google-cloud-ops-agent
else
    log "config unchanged — skipping restart"
fi

# ── 3. Ensure agent can read NIDP log files ──────────────────────────────────
# Ops Agent runs as root, but /opt/nidp/logs is owned by `nidp:nidp` 0750. We
# need the directory traversal bit so root tail can follow new files. Files
# are 0640 nidp:nidp — root reads regardless of mode, so no further chmod
# needed on individual files.
if [[ -d /opt/nidp/logs ]]; then
    chmod a+rx /opt/nidp/logs
    find /opt/nidp/logs -maxdepth 1 -type d -exec chmod a+rx {} +
fi

# ── 4. Ensure enabled at boot ────────────────────────────────────────────────
systemctl enable google-cloud-ops-agent >/dev/null 2>&1 || true

log "status:"
systemctl is-active google-cloud-ops-agent && log "✅ active"
