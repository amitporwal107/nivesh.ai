#!/usr/bin/env bash
# quick_deploy.sh — fast code sync from the Emergent pod to nidp-stack-vm.
#
# Usage (from the Emergent pod):
#   bash /app/backend/nidp/deploy/vm/quick_deploy.sh [GCP_OWNER_TOKEN]
#
# Requires: gcloud installed at /opt/google-cloud-sdk/bin/gcloud
#           ssh key at /root/.ssh/nidp_gcp (or auto-creates via OS Login)
#
# What it does:
#   1. Registers a fresh OS Login SSH key with the provided GCP token
#   2. rsyncs /app/backend/nidp/ → VM /opt/nidp/repo/backend/nidp/
#   3. Restarts cron on the VM so new code is picked up next job run

set -euo pipefail

VM_IP="34.93.60.254"
VM_ZONE="asia-south1-a"
PROJECT="niveshdataintelligence"
SSH_USER="aporwal107_gmail_com"
SSH_KEY="/root/.ssh/nidp_gcp"

OWNER_TOKEN="${1:-${GOOGLE_OAUTH_ACCESS_TOKEN:-}}"

if [[ -z "$OWNER_TOKEN" ]]; then
  echo "Usage: $0 <GCP_OWNER_TOKEN>"
  echo "  or set GOOGLE_OAUTH_ACCESS_TOKEN env var"
  exit 1
fi

log() { printf '\033[1;36m[quick_deploy]\033[0m %s\n' "$*"; }

# ── 1. Register fresh SSH key (1-hour TTL) ────────────────────────
log "Registering OS Login SSH key (1h TTL)..."
if [[ ! -f "$SSH_KEY" ]]; then
  ssh-keygen -t ed25519 -f "$SSH_KEY" -N "" -C "nidp-deploy-agent" -q
fi

PUB_KEY=$(cat "${SSH_KEY}.pub")
EXPIRY=$(python3 -c "import time; print(int((time.time() + 3600) * 1e6))")

curl -sf -X POST \
  -H "Authorization: Bearer $OWNER_TOKEN" \
  -H "Content-Type: application/json" \
  "https://oslogin.googleapis.com/v1/users/$SSH_USER%40gmail.com/sshPublicKeys" \
  -d "{\"key\": \"$PUB_KEY\", \"expirationTimeUsec\": \"$EXPIRY\"}" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('Key registered:', d.get('name','?'))"

# ── 2. rsync NIDP code to VM ──────────────────────────────────────
log "Syncing /app/backend/nidp/ → VM..."
rsync -az \
  -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=30" \
  --exclude="__pycache__" --exclude="*.pyc" --exclude=".git" \
  /app/backend/nidp/ \
  "$SSH_USER@$VM_IP:/opt/nidp/repo/backend/nidp/"

log "Sync complete!"

# ── 3. Reload cron on VM ──────────────────────────────────────────
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$SSH_USER@$VM_IP" \
  "sudo systemctl reload cron && echo 'Cron reloaded'"

log "Deployment done. Next cron triggers will use the new code."
log "To check status:  ssh -i $SSH_KEY $SSH_USER@$VM_IP"
