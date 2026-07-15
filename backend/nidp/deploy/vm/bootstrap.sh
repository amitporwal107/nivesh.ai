#!/usr/bin/env bash
# bootstrap.sh — one-shot provisioner for the NIDP VM.
#
# Designed to be passed as `--metadata-from-file=startup-script=bootstrap.sh`
# to `gcloud compute instances create`, so it runs as root on first boot.
# Idempotent — safe to re-run.
#
# Provisions:
#   • System packages (python3.11, git, postgres-client, jq, curl)
#   • Service user `nidp` with locked-down home at /opt/nidp
#   • Repo checkout at /opt/nidp/repo
#   • Python venv at /opt/nidp/venv with NIDP deps installed
#   • Log directory + logrotate config
#   • Empty /opt/nidp/nidp.env (operator must fill secrets after first boot)
#
# Does NOT install the crontab or systemd timer — those are explicit
# operator actions documented in README.md, so an unconfigured VM
# never starts firing jobs against an unset env.

set -euo pipefail

REPO_URL="${NIDP_REPO_URL:-https://github.com/your-org/your-repo.git}"
REPO_BRANCH="${NIDP_REPO_BRANCH:-main}"
NIDP_HOME=/opt/nidp
NIDP_USER=nidp

log() { printf '\033[1;36m[bootstrap]\033[0m %s\n' "$*"; }

# ── 0. Timezone — must be set before any service starts ───────────
# TZ=Asia/Kolkata in nidp.env only works when tzdata is present and the
# system clock is anchored to IST. Set it at the OS level so cron,
# Python, and Docker containers all agree.
if command -v timedatectl >/dev/null 2>&1; then
    timedatectl set-timezone Asia/Kolkata
else
    ln -sf /usr/share/zoneinfo/Asia/Kolkata /etc/localtime
    echo 'Asia/Kolkata' > /etc/timezone
fi

# ── 1. System packages ────────────────────────────────────────────
log "installing apt packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    python3.11 python3.11-venv python3-pip \
    git curl jq postgresql-client logrotate cron ca-certificates tzdata \
    tesseract-ocr poppler-utils   # OCR fallback for image/scanned filing PDFs (document_parser)

# ── 2. Service user ───────────────────────────────────────────────
if ! id -u "$NIDP_USER" >/dev/null 2>&1; then
    log "creating service user $NIDP_USER"
    useradd --system --create-home --home-dir "$NIDP_HOME" \
            --shell /bin/bash "$NIDP_USER"
else
    log "service user $NIDP_USER already exists"
fi
mkdir -p "$NIDP_HOME"/{logs,run}
chown -R "$NIDP_USER:$NIDP_USER" "$NIDP_HOME"

# ── 3. Repo ───────────────────────────────────────────────────────
if [[ ! -d "$NIDP_HOME/repo/.git" ]]; then
    log "cloning repo"
    sudo -u "$NIDP_USER" git clone --depth=20 --branch="$REPO_BRANCH" \
        "$REPO_URL" "$NIDP_HOME/repo"
else
    log "repo already cloned at $NIDP_HOME/repo (skipping)"
fi

# ── 4. Python venv ────────────────────────────────────────────────
if [[ ! -x "$NIDP_HOME/venv/bin/python" ]]; then
    log "creating Python venv"
    sudo -u "$NIDP_USER" python3.11 -m venv "$NIDP_HOME/venv"
fi
log "installing NIDP requirements"
sudo -u "$NIDP_USER" "$NIDP_HOME/venv/bin/pip" install --quiet --upgrade pip
sudo -u "$NIDP_USER" "$NIDP_HOME/venv/bin/pip" install --quiet \
    -r "$NIDP_HOME/repo/backend/nidp/deploy/requirements.txt"

# ── 5. Env file placeholder ───────────────────────────────────────
if [[ ! -f "$NIDP_HOME/nidp.env" ]]; then
    log "seeding empty $NIDP_HOME/nidp.env (operator must fill secrets)"
    cp "$NIDP_HOME/repo/backend/nidp/deploy/vm/nidp.env.example" \
       "$NIDP_HOME/nidp.env"
    chown "$NIDP_USER:$NIDP_USER" "$NIDP_HOME/nidp.env"
    chmod 600 "$NIDP_HOME/nidp.env"
fi

# ── 6. Logrotate ──────────────────────────────────────────────────
log "configuring logrotate"
cat > /etc/logrotate.d/nidp <<'EOF'
/opt/nidp/logs/*/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    su nidp nidp
    create 0640 nidp nidp
    sharedscripts
}
EOF

# ── 7. Cloud Logging — install Ops Agent so NIDP cron logs reach Cloud Logging
log "installing Google Cloud Ops Agent"
bash "$NIDP_HOME/repo/backend/nidp/deploy/vm/install-ops-agent.sh"

log "✅ bootstrap done. Next: edit /opt/nidp/nidp.env, then install"
log "   /etc/cron.d/nidp + nidp-health.timer (see README.md)"
