#!/usr/bin/env bash
# redeploy.sh — Fast code-update deploy for nidp-stack-vm.
#
# Syncs the latest /app/backend/nidp/ code to the VM and reloads services.
# Does NOT restart TimescaleDB (data store — leave it running).
#
# Usage (from the Emergent pod / local machine with gcloud):
#   bash deploy/nidp-vm/redeploy.sh
#
# Requires:
#   - gcloud authenticated with an account that has compute.osLogin or
#     instance metadata SSH access to nidp-stack-vm
#   - Or: GOOGLE_OAUTH_ACCESS_TOKEN set to an owner-level bearer token
#     (used to register a temporary OS Login key via the API)

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
VM_IP="34.93.60.254"
VM_NAME="nidp-stack-vm"
VM_ZONE="asia-south1-a"
PROJECT="niveshdataintelligence"
SSH_USER="aporwal107_gmail_com"

LOCAL_NIDP_DIR="/app/backend/nidp"
REMOTE_NIDP_DIR="/opt/nidp/repo/backend/nidp"
SSH_KEY="/root/.ssh/nidp_gcp"

log()  { printf '\033[1;36m[nidp-deploy]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[nidp-deploy]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[nidp-deploy]\033[0m %s\n' "$*"; exit 1; }

# ── 1. Ensure SSH key exists ──────────────────────────────────────────────────
if [[ ! -f "$SSH_KEY" ]]; then
  log "Generating SSH key at $SSH_KEY..."
  ssh-keygen -t ed25519 -f "$SSH_KEY" -N "" -C "nidp-deploy-$(date +%Y%m%d)" -q
fi
PUB_KEY=$(cat "${SSH_KEY}.pub")

# ── 2. Register SSH key (via OS Login API or gcloud metadata) ─────────────────
OWNER_TOKEN="${GOOGLE_OAUTH_ACCESS_TOKEN:-}"

if [[ -n "$OWNER_TOKEN" ]]; then
  log "Registering OS Login SSH key via API (1h TTL)..."
  EXPIRY=$(python3 -c "import time; print(int((time.time() + 3600) * 1e6))")
  curl -sf -X POST \
    -H "Authorization: Bearer $OWNER_TOKEN" \
    -H "Content-Type: application/json" \
    "https://oslogin.googleapis.com/v1/users/${SSH_USER//_gmail_com/@gmail.com}/sshPublicKeys" \
    -d "{\"key\": \"$PUB_KEY\", \"expirationTimeUsec\": \"$EXPIRY\"}" \
    > /dev/null
  ok "SSH key registered (1h TTL)."
else
  log "No GOOGLE_OAUTH_ACCESS_TOKEN — attempting gcloud metadata key injection..."
  GCLOUD=$(command -v gcloud 2>/dev/null || echo "/root/google-cloud-sdk/bin/gcloud")
  KEYVAL="${SSH_USER}:${PUB_KEY} ${SSH_USER}"
  "$GCLOUD" compute instances add-metadata "$VM_NAME" \
    --zone="$VM_ZONE" --project="$PROJECT" \
    --metadata="ssh-keys=$KEYVAL" 2>&1 | grep -v "^Updated" || true
  log "SSH key injected via metadata. Waiting 10s for sshd to pick it up..."
  sleep 10
fi

SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=30"

# ── 3. Verify SSH connectivity ────────────────────────────────────────────────
log "Testing SSH to $VM_IP..."
ssh $SSH_OPTS "$SSH_USER@$VM_IP" "echo 'SSH OK'" \
  || fail "SSH failed. Check key registration and VM firewall rules."

# ── 4. Sync NIDP code ─────────────────────────────────────────────────────────
log "Syncing $LOCAL_NIDP_DIR → VM:$REMOTE_NIDP_DIR ..."
rsync -az \
  -e "ssh $SSH_OPTS" \
  --exclude="__pycache__" \
  --exclude="*.pyc" \
  --exclude=".git" \
  --exclude="*.egg-info" \
  --exclude=".pytest_cache" \
  "$LOCAL_NIDP_DIR/" \
  "$SSH_USER@$VM_IP:$REMOTE_NIDP_DIR/"
ok "Code synced."

# ── 5. Reload services on VM ──────────────────────────────────────────────────
log "Reloading NIDP services on VM..."
ssh $SSH_OPTS "$SSH_USER@$VM_IP" bash <<'REMOTE'
  set -euo pipefail
  log() { printf '\033[1;36m[nidp-vm]\033[0m %s\n' "$*"; }
  ok()  { printf '\033[1;32m[nidp-vm]\033[0m %s\n' "$*"; }

  # Reload cron (picks up new job scripts)
  sudo systemctl reload cron 2>/dev/null && ok "Cron reloaded." || log "Cron reload skipped."

  # Restart query API if running as a systemd service
  if systemctl is-active --quiet nidp-query-api 2>/dev/null; then
    sudo systemctl restart nidp-query-api
    ok "nidp-query-api restarted."
  fi

  # If DaaS runs as a uvicorn process, restart it
  if systemctl is-active --quiet nidp-daas 2>/dev/null; then
    sudo systemctl restart nidp-daas
    ok "nidp-daas restarted."
  fi

  ok "All NIDP services reloaded."
REMOTE

# ── 6. Health check ───────────────────────────────────────────────────────────
log "Checking DaaS health..."
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" "http://$VM_IP:8010/health" 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" == "200" ]]; then
  ok "DaaS is healthy (HTTP 200)."
else
  log "DaaS health returned HTTP $HTTP_CODE (may be expected if port 8010 is internal-only)."
fi

# ── 7. Summary ────────────────────────────────────────────────────────────────
ok ""
ok "✅ NIDP deploy complete!"
ok "   VM: $VM_IP"
ok ""
ok "   To inspect:"
ok "   ssh -i $SSH_KEY $SSH_USER@$VM_IP"
ok "   docker logs nidp-postgres  (TimescaleDB)"
