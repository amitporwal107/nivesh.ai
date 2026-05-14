#!/usr/bin/env bash
# bootstrap.sh — One-shot VM provisioner. Run as root on first boot.
# Installs Docker, Docker Compose, clones repo, creates app dirs.
# Safe to re-run (idempotent).
#
# Usage (on the VM):
#   sudo bash ~/nivesh-app/bootstrap.sh

set -euo pipefail

REPO_URL="https://github.com/amitporwal107/nivesh.ai.git"
REPO_BRANCH="nivesh-v2-copilot"
APP_HOME="/opt/nivesh"
APP_USER="nivesh"

log() { printf '\033[1;36m[bootstrap]\033[0m %s\n' "$*"; }

# ── 1. System packages ────────────────────────────────────────────────────────
log "Installing apt packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    curl git jq ca-certificates gnupg lsb-release \
    postgresql-client python3-pip

# ── 2. Docker ─────────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    log "Installing Docker..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/debian $(lsb_release -cs) stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    systemctl enable --now docker
else
    log "Docker already installed — skipping"
fi

# ── 3. Service user ───────────────────────────────────────────────────────────
if ! id -u "$APP_USER" &>/dev/null; then
    log "Creating service user $APP_USER..."
    useradd --system --create-home --home-dir "$APP_HOME" \
            --shell /bin/bash "$APP_USER"
    usermod -aG docker "$APP_USER"
else
    log "User $APP_USER already exists — ensuring docker group membership"
    usermod -aG docker "$APP_USER" 2>/dev/null || true
fi

# ── 4. App directory structure ────────────────────────────────────────────────
log "Creating app directories..."
mkdir -p "$APP_HOME"/{repo,data/{mongo,postgres,redis},logs,deploy}
chown -R "$APP_USER:$APP_USER" "$APP_HOME"

# ── 5. Clone repository ───────────────────────────────────────────────────────
if [[ ! -d "$APP_HOME/repo/.git" ]]; then
    log "Cloning $REPO_BRANCH branch..."
    sudo -u "$APP_USER" git clone --depth=50 --branch="$REPO_BRANCH" \
        "$REPO_URL" "$APP_HOME/repo"
else
    log "Repo already cloned — pulling latest..."
    sudo -u "$APP_USER" git -C "$APP_HOME/repo" pull --ff-only
fi

# ── 6. Copy deploy files into app home ───────────────────────────────────────
log "Installing deploy files..."
cp -r ~/nivesh-app/. "$APP_HOME/deploy/"
chown -R "$APP_USER:$APP_USER" "$APP_HOME/deploy"
chmod +x "$APP_HOME/deploy/"*.sh

# ── 7. .env.prod placeholder (operator fills after bootstrap) ─────────────────
if [[ ! -f "$APP_HOME/.env.prod" ]]; then
    log "Placing .env.prod (pre-filled — review before deploying)..."
    cp "$APP_HOME/deploy/.env.prod" "$APP_HOME/.env.prod"
    chown "$APP_USER:$APP_USER" "$APP_HOME/.env.prod"
    chmod 600 "$APP_HOME/.env.prod"
fi

log ""
log "✅ Bootstrap complete."
log ""
log "Next: run the deploy script:"
log "   sudo EXTERNAL_IP=<this-vm-external-ip> bash $APP_HOME/deploy/deploy.sh"
log ""
log "Get your external IP with:"
log "   curl -s https://api.ipify.org"
