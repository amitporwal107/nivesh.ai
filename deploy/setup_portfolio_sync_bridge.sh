#!/usr/bin/env bash
# setup_portfolio_sync_bridge.sh
#
# One-time setup that wires the Nivesh ↔ NIDP portfolio sync bridge.
# Run from the sandbox / Emergent pod (NOT on the VM itself).
#
# What it does:
#   1. Registers a 1-hour SSH key via GCP OS Login
#   2. Rsyncs updated NIDP code + Nivesh compose to the VM
#   3. On the VM:
#      a. Creates nidp-bridge Docker network
#      b. Starts / connects nidp-postgres to that network
#      c. Patches /opt/nidp/nidp.env  → adds NIVESH_POSTGRES_URL + NIDP_PG_*
#      d. Patches /opt/nivesh/.env.prod → adds NIDP_QUERY_API_* + NIDP_POSTGRES_URL
#      e. Recreates nivesh-backend container so it joins nidp-bridge
#      f. Installs updated crontab (adds portfolio_holdings_sync at 23:00)
#
# Usage:
#   bash setup_portfolio_sync_bridge.sh <GCP_OWNER_TOKEN>
#   or: GOOGLE_OAUTH_ACCESS_TOKEN=<token> bash setup_portfolio_sync_bridge.sh

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
VM_IP="34.93.60.254"
VM_ZONE="asia-south1-a"
PROJECT="niveshdataintelligence"
SSH_USER="aporwal107_gmail_com"
SSH_KEY="/root/.ssh/nidp_gcp"

OWNER_TOKEN="${1:-${GOOGLE_OAUTH_ACCESS_TOKEN:-}}"

# ── Helpers ───────────────────────────────────────────────────────────────────
CYAN="\033[1;36m"; GREEN="\033[1;32m"; RED="\033[1;31m"; RESET="\033[0m"
log()  { printf "${CYAN}[bridge-setup]${RESET} %s\n" "$*"; }
ok()   { printf "${GREEN}[bridge-setup] ✅${RESET} %s\n" "$*"; }
fail() { printf "${RED}[bridge-setup] ❌${RESET} %s\n" "$*"; exit 1; }

ssh_cmd() { ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=30 "$SSH_USER@$VM_IP" "$@"; }
rsync_to() {
    rsync -az --delete \
        -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=30" \
        --exclude="__pycache__" --exclude="*.pyc" --exclude=".git" \
        "$@"
}

# ── 1. SSH key via GCP OS Login ───────────────────────────────────────────────
[[ -n "$OWNER_TOKEN" ]] || fail "Pass GCP owner token as \$1 or GOOGLE_OAUTH_ACCESS_TOKEN"

log "Registering OS Login SSH key (1h TTL)..."
[[ -f "$SSH_KEY" ]] || ssh-keygen -t ed25519 -f "$SSH_KEY" -N "" -C "bridge-deploy" -q

PUB_KEY=$(cat "${SSH_KEY}.pub")
EXPIRY=$(python3 -c "import time; print(int((time.time() + 3600) * 1e6))")

curl -sf -X POST \
    -H "Authorization: Bearer $OWNER_TOKEN" \
    -H "Content-Type: application/json" \
    "https://oslogin.googleapis.com/v1/users/${SSH_USER}%40gmail.com/sshPublicKeys" \
    -d "{\"key\": \"$PUB_KEY\", \"expirationTimeUsec\": \"$EXPIRY\"}" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print('  Key registered:', d.get('name','?'))"

ok "SSH key registered."

# ── 2. Rsync code to VM ───────────────────────────────────────────────────────
log "Syncing NIDP code → VM /opt/nidp/repo/backend/nidp/ ..."
rsync_to \
    /app/backend/nidp/ \
    "$SSH_USER@$VM_IP:/opt/nidp/repo/backend/nidp/"
ok "NIDP code synced."

log "Syncing Nivesh deploy files → VM /opt/nivesh/deploy/ ..."
rsync_to \
    --exclude=".env.prod" \
    /app/deploy/nivesh-app/ \
    "$SSH_USER@$VM_IP:/opt/nivesh/deploy/"
ok "Nivesh deploy files synced."

# ── 3. Remote setup on the VM ─────────────────────────────────────────────────
log "Running setup on VM $VM_IP ..."

ssh_cmd bash -s << 'REMOTE_SCRIPT'
set -euo pipefail
CYAN="\033[1;36m"; GREEN="\033[1;32m"; RESET="\033[0m"
step() { printf "${CYAN}  [vm]${RESET} %s\n" "$*"; }
ok()   { printf "${GREEN}  [vm] ✓${RESET} %s\n" "$*"; }

NIDP_ENV="/opt/nidp/nidp.env"
NIVESH_ENV="/opt/nivesh/.env.prod"
NIDP_QA_ENV="/opt/nidp/query_api.env"
NIDP_COMPOSE="/opt/nidp/repo/backend/nidp/deploy/vm/docker-compose.prod.yml"
NIVESH_COMPOSE="/opt/nivesh/deploy/docker-compose.prod.yml"

# ── a. Create nidp-bridge network ─────────────────────────────────────────────
step "Creating nidp-bridge Docker network..."
docker network create nidp-bridge 2>/dev/null && ok "Network created." || ok "Network already exists."

# ── b. Set up NIDP postgres credentials ───────────────────────────────────────
step "Checking NIDP postgres credentials in $NIDP_ENV ..."
source "$NIDP_ENV"

if [[ -z "${NIDP_PG_PASSWORD:-}" ]]; then
    step "NIDP_PG_PASSWORD not set — generating one..."
    NIDP_PG_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
    # If nidp-postgres is already running, read its actual password from the container env
    if docker inspect nidp-postgres &>/dev/null; then
        RUNNING_PW=$(docker inspect nidp-postgres \
            --format '{{range .Config.Env}}{{println .}}{{end}}' \
            | grep POSTGRES_PASSWORD | cut -d= -f2)
        [[ -n "$RUNNING_PW" ]] && NIDP_PG_PASSWORD="$RUNNING_PW"
        step "Read password from running container."
    fi

    # Persist to nidp.env
    grep -q "^NIDP_PG_PASSWORD=" "$NIDP_ENV" \
        && sed -i "s|^NIDP_PG_PASSWORD=.*|NIDP_PG_PASSWORD=$NIDP_PG_PASSWORD|" "$NIDP_ENV" \
        || printf "\nNIDP_PG_USER=nidp\nNIDP_PG_PASSWORD=%s\nNIDP_PG_DB=nidp\n" "$NIDP_PG_PASSWORD" >> "$NIDP_ENV"
fi

# Re-read so NIDP_PG_PASSWORD is in scope
source "$NIDP_ENV"
NIDP_PG_USER="${NIDP_PG_USER:-nidp}"
NIDP_PG_DB="${NIDP_PG_DB:-nidp}"
ok "NIDP postgres credentials ready."

# ── c. Start/reconnect nidp-postgres ──────────────────────────────────────────
step "Checking nidp-postgres container..."
if docker inspect nidp-postgres &>/dev/null; then
    ok "Container already running — connecting to nidp-bridge..."
    docker network connect nidp-bridge nidp-postgres 2>/dev/null \
        && ok "Connected nidp-postgres to nidp-bridge." \
        || ok "Already on nidp-bridge."
else
    step "Starting nidp-postgres via $NIDP_COMPOSE ..."
    docker compose -f "$NIDP_COMPOSE" up -d
    ok "nidp-postgres started."
fi

# ── d. Patch /opt/nidp/nidp.env with NIVESH_POSTGRES_URL ─────────────────────
step "Patching $NIDP_ENV with NIVESH_POSTGRES_URL ..."
source "$NIVESH_ENV"

NIVESH_PG_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5432/${POSTGRES_DB}"

if grep -q "^NIVESH_POSTGRES_URL=" "$NIDP_ENV"; then
    sed -i "s|^NIVESH_POSTGRES_URL=.*|NIVESH_POSTGRES_URL=$NIVESH_PG_URL|" "$NIDP_ENV"
else
    printf "\n# Nivesh main-app Postgres (Docker container, port bound to 127.0.0.1:5432)\n" >> "$NIDP_ENV"
    printf "NIVESH_POSTGRES_URL=%s\n" "$NIVESH_PG_URL" >> "$NIDP_ENV"
fi
ok "NIVESH_POSTGRES_URL patched."

# ── e. Patch /opt/nivesh/.env.prod with NIDP vars ─────────────────────────────
step "Patching $NIVESH_ENV with NIDP connection vars ..."

# Get Query API token
QUERY_API_TOKEN=""
if [[ -f "$NIDP_QA_ENV" ]]; then
    source "$NIDP_QA_ENV"
    QUERY_API_TOKEN="${NIDP_QUERY_API_TOKEN:-}"
fi

QUERY_API_PORT="${NIDP_QUERY_API_PORT:-8090}"
QUERY_API_URL="http://host-gateway:${QUERY_API_PORT}"
NIDP_PG_CONN="postgresql://${NIDP_PG_USER}:${NIDP_PG_PASSWORD}@nidp-postgres:5432/${NIDP_PG_DB}"

patch_env() {
    local key="$1" val="$2" file="$3"
    if grep -q "^${key}=" "$file"; then
        sed -i "s|^${key}=.*|${key}=${val}|" "$file"
    else
        printf "%s=%s\n" "$key" "$val" >> "$file"
    fi
}

patch_env "NIDP_QUERY_API_URL"   "$QUERY_API_URL"        "$NIVESH_ENV"
patch_env "NIDP_POSTGRES_URL"    "$NIDP_PG_CONN"         "$NIVESH_ENV"

if [[ -n "$QUERY_API_TOKEN" ]]; then
    patch_env "NIDP_QUERY_API_TOKEN" "$QUERY_API_TOKEN" "$NIVESH_ENV"
    ok "NIDP_QUERY_API_TOKEN patched from query_api.env."
else
    printf "\n# ⚠ NIDP_QUERY_API_TOKEN not found in %s — fill manually.\n" "$NIDP_QA_ENV" >> "$NIVESH_ENV"
    ok "NIDP_QUERY_API_TOKEN placeholder added (fill in manually)."
fi
ok "NIVESH_ENV patched with NIDP_QUERY_API_URL + NIDP_POSTGRES_URL."

# ── f. Recreate nivesh-backend to join nidp-bridge ────────────────────────────
step "Recreating nivesh-backend to attach nidp-bridge network..."
cd /opt/nivesh
docker compose -f "$NIVESH_COMPOSE" \
    --env-file "$NIVESH_ENV" \
    up -d --no-deps --force-recreate backend
ok "nivesh-backend recreated."

# Wait for health
step "Waiting for backend health..."
for i in $(seq 1 30); do
    if curl -sf http://localhost/health &>/dev/null 2>&1; then
        ok "Backend healthy."; break
    fi
    sleep 3
    [[ $i -eq 30 ]] && echo "⚠  Backend not healthy after 90s — check: docker logs nivesh-backend"
done

# ── g. Install updated crontab ────────────────────────────────────────────────
step "Installing updated crontab (adds portfolio_holdings_sync at 23:00)..."
sudo install -m 644 \
    /opt/nidp/repo/backend/nidp/deploy/vm/nidp.cron \
    /etc/cron.d/nidp
sudo systemctl reload cron
ok "Crontab installed."

# ── h. Quick smoke test ────────────────────────────────────────────────────────
step "Smoke-testing connections..."

# Nivesh backend → NIDP postgres via nidp-bridge
docker exec nivesh-backend \
    python3 -c "
import asyncio, asyncpg, os
async def test():
    url = os.environ.get('NIDP_POSTGRES_URL','')
    if not url: print('  NIDP_POSTGRES_URL not set'); return
    conn = await asyncpg.connect(url)
    v = await conn.fetchval('SELECT 1')
    await conn.close()
    print('  nivesh-backend → nidp-postgres: OK')
asyncio.run(test())
" 2>&1 || echo "  ⚠ NIDP postgres connectivity check failed — check logs"

# NIDP native → Nivesh postgres via localhost:5432
/opt/nidp/venv/bin/python3 -c "
import asyncio, asyncpg
async def test():
    import os; url = os.environ.get('NIVESH_POSTGRES_URL','')
    if not url: print('  NIVESH_POSTGRES_URL not set in nidp.env'); return
    conn = await asyncpg.connect(url)
    v = await conn.fetchval('SELECT 1')
    await conn.close()
    print('  nidp-native → nivesh-postgres: OK')
" 2>&1 || echo "  ⚠ Nivesh postgres connectivity check failed — check nidp.env"

printf "\n${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"
printf "${GREEN}  Portfolio sync bridge setup complete!${RESET}\n"
printf "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"
printf "\n  Scheduled run : 23:00 IST weekdays  (portfolio_holdings_sync)\n"
printf "  Intel pass    : 23:30 IST weekdays  (portfolio_intelligence_sync)\n"
printf "  Manual trigger: POST /feeds/portfolio_holdings_sync/execute\n"
printf "\n  Verify with:\n"
printf "    docker logs -f nivesh-backend | grep portfolio\n"
printf "    docker exec nidp-postgres psql -U nidp -c 'SELECT count(*) FROM portfolio.client_master'\n\n"
REMOTE_SCRIPT

ok "Done! Bridge is live on $VM_IP."
