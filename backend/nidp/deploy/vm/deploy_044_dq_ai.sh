#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# deploy_044_dq_ai.sh — one-shot VM deploy for replay readiness
# ─────────────────────────────────────────────────────────────────
#
# What this does on the NIDP VM:
#   1. Runs the existing quick_deploy.sh (rsync /app/backend/nidp/ → VM)
#   2. Applies migration 044 to NIDP TimescaleDB (audit schema)
#   3. Restarts nidp-daas-api so the new dq_ai router with
#      /v1/dq/proposals/generate-all is picked up
#   4. Smoke-tests both endpoints
#
# Requires a fresh OS Login owner token (1-hour TTL):
#   gcloud auth print-access-token
#
# Usage:
#   bash /app/backend/nidp/deploy/vm/deploy_044_dq_ai.sh <OWNER_TOKEN>
#
set -euo pipefail

OWNER_TOKEN="${1:-${GOOGLE_OAUTH_ACCESS_TOKEN:-}}"
if [[ -z "${OWNER_TOKEN}" ]]; then
  echo "usage: $0 <GCP_OWNER_TOKEN>"
  echo "  get one via: gcloud auth print-access-token"
  exit 2
fi

VM_IP="34.47.191.39"
SSH_USER="aporwal107_gmail_com"
SSH_KEY="/root/.ssh/nidp_gcp"
SSH_OPTS=(-i "$SSH_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=30)

# ── Step 1 — rsync code via existing quick_deploy ─────────────────
echo "▶ Step 1/4 — quick_deploy.sh (rsync nidp/ to VM)"
bash /app/backend/nidp/deploy/vm/quick_deploy.sh "$OWNER_TOKEN"

SSH="ssh ${SSH_OPTS[*]} ${SSH_USER}@${VM_IP}"

# ── Step 2 — apply migration 044 ──────────────────────────────────
echo ""
echo "▶ Step 2/4 — apply migration 044 to NIDP Postgres"
$SSH 'PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d nidp \
  -f /opt/nidp/repo/backend/nidp/migrations/044_nidp_replay_engine.sql \
  2>&1 | tail -20'

# ── Step 3 — restart daas_api so updated dq_ai router loads ───────
echo ""
echo "▶ Step 3/4 — restart nidp-daas-api"
$SSH 'sudo systemctl restart nidp-daas-api && sleep 2 && \
      sudo systemctl status nidp-daas-api --no-pager | head -10'

# ── Step 4 — smoke tests ──────────────────────────────────────────
echo ""
echo "▶ Step 4/4 — smoke-test new endpoints"
KEY="$(grep '^NIDP_DAAS_API_KEY=' /app/backend/.env | cut -d= -f2-)"

echo "  • POST /v1/dq/proposals/generate-all → (200 = router deployed)"
curl -sS -o /dev/null -X POST "http://${VM_IP}:8083/v1/dq/proposals/generate-all" \
  -H "X-API-Key: ${KEY}" -H "Content-Type: application/json" \
  -d '{"sample_size":10,"failure_history_days":30,"feeds":["amfi_nav"]}' \
  -w "    HTTP %{http_code}\n"

echo "  • Verify audit schema:"
$SSH 'PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d nidp -t \
      -c "SELECT version,description FROM audit.policy_versions ORDER BY version;"'

echo ""
echo "🎉 Done."
echo ""
echo "Next steps (manual):"
echo "  1. Open Cloud Console firewall for port 5433 from the Emergent pod's"
echo "     egress range so the pod can reach the NIDP DB directly. THEN:"
echo "  2. Add to /app/backend/.env (pod side):"
echo "       NIDP_PG_DSN=postgresql://postgres:postgres@${VM_IP}:5433/nidp"
echo "  3. sudo supervisorctl restart backend"
echo "  4. Open /nidp → Replay (90d) → Start Replay (last 90d, v1, both domains)"
