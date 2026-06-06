#!/usr/bin/env bash
#
# gsm-scaffold-secrets.sh — create EMPTY Secret Manager containers (no versions)
# for the full app secret inventory, so the entries exist and can have real
# values added later (via migrate-secrets-to-gsm.sh or manually).
#
# Empty = no version, so helpers.gsm.get() returns None and get_for_env()
# falls back to the env var — creating these does NOT change app behaviour.
#
# Auth: reads a GCP OAuth access token (secretmanager.admin) from $1 or the
# file ./.gcp-token. Idempotent: skips secrets that already exist.
# Prints names + action only.
#
#   ./gsm-scaffold-secrets.sh [token-file]
#
set -euo pipefail
PROJECT="${GSM_PROJECT:-niveshdataintelligence}"
TOKFILE="${1:-/app/.gcp-token}"
[ -f "$TOKFILE" ] || { echo "token file not found: $TOKFILE" >&2; exit 1; }
TOKEN="$(cat "$TOKFILE")"
API="https://secretmanager.googleapis.com/v1/projects/${PROJECT}/secrets"

# Shared across envs → unsuffixed
COMMON=(
  OPENAI_API_KEY ANTHROPIC_API_KEY EMERGENT_LLM_KEY
  ALPHA_VANTAGE_KEY FRED_API_KEY
  CASPARSER_API_KEY PI_CASPARSER_API_KEY
  GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET
)
# Per-env → each gets _STAGING and _PROD
ENV_BASE=(
  PI_POSTGRES_USER PI_POSTGRES_PASSWORD PI_MONGO_USER PI_MONGO_PASSWORD PI_REDIS_PASSWORD
  MONGO_URL POSTGRES_URL REDIS_URL
  PI_PAN_ENCRYPTION_KEY PII_ENCRYPTION_KEY
  PI_ADMIN_TOKEN PI_WEBHOOK_SECRET
  NIDP_DAAS_INTERNAL_TOKEN NIDP_QUERY_API_TOKEN NIDP_DAAS_API_KEY
  NIDP_MINIO_ACCESS_KEY NIDP_MINIO_SECRET_KEY
  ADMIN_SESSION_TOKEN MONITORING_ACTION_SECRET GRAFANA_WEBHOOK_SECRET WORK_INGEST_SECRET
)
# Deliberately NOT scaffolded (undecided shared/per-env): NIDP_TELEGRAM_BOT_TOKEN, OPENALGO_MANAGEMENT_TOKEN

NAMES=("${COMMON[@]}")
for b in "${ENV_BASE[@]}"; do NAMES+=("${b}_STAGING" "${b}_PROD"); done

created=0; existed=0; failed=0
for n in "${NAMES[@]}"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "${API}/${n}")
  if [ "$code" = "200" ]; then echo "exists   $n"; existed=$((existed+1)); continue; fi
  rc=$(curl -s -o /tmp/gsm_scaffold.json -w "%{http_code}" -X POST \
        -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
        "${API}?secretId=${n}" -d '{"replication":{"automatic":{}}}')
  if [ "$rc" = "200" ]; then echo "created  $n"; created=$((created+1))
  else echo "FAILED   $n (HTTP $rc) $(python3 -c "import json;print(json.load(open('/tmp/gsm_scaffold.json')).get('error',{}).get('message','')[:100])" 2>/dev/null)"; failed=$((failed+1)); fi
done
rm -f /tmp/gsm_scaffold.json; unset TOKEN
echo "# summary: created=$created existed=$existed failed=$failed total=${#NAMES[@]}"
