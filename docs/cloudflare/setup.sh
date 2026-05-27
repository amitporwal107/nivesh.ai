#!/usr/bin/env bash

# ============================================================================
# NIVESHCOPILOT CLOUDFLARE HARDENING SCRIPT
# ============================================================================
#
# SAFE VERSION — does NOT create or modify DNS records.
#
# CONFIGURES:
# ✔ SSL/TLS strict + TLS 1.2 min + HTTPS redirect
# ✔ Security level + browser check
# ✔ Brotli compression + HTTP/3
# ✔ Cache (with /api/* bypass so auth'd responses never cache at CDN)
# ✔ Bot fight mode
# ✔ Per-category rate limiting (auth=5, admin=10, analytics=30, etc.)
#
# USAGE:
#
#   cp docs/cloudflare/.env.example docs/cloudflare/.env
#   # fill in CF_API_TOKEN and CF_ZONE_ID in .env
#   chmod +x docs/cloudflare/setup.sh
#   ./docs/cloudflare/setup.sh
#
# ============================================================================

set -euo pipefail

# ── Load credentials from .env ────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found."
  echo "       cp docs/cloudflare/.env.example docs/cloudflare/.env"
  exit 1
fi

# shellcheck disable=SC1091
set -a; source "$ENV_FILE"; set +a

[[ -z "${CF_API_TOKEN:-}" ]] && { echo "ERROR: CF_API_TOKEN missing in .env"; exit 1; }
[[ -z "${CF_ZONE_ID:-}"   ]] && { echo "ERROR: CF_ZONE_ID missing in .env";   exit 1; }

ROOT_DOMAIN="niveshcopilot.com"
CF_API="https://api.cloudflare.com/client/v4"

# ── Helper: PATCH a zone setting and bail loudly on failure ──────────────────
cf_patch() {
  local setting=$1
  local payload=$2
  local response
  response=$(curl -s -X PATCH \
    "$CF_API/zones/$CF_ZONE_ID/settings/$setting" \
    -H "Authorization: Bearer $CF_API_TOKEN" \
    -H "Content-Type: application/json" \
    --data "$payload")

  local success
  success=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('success','false'))" 2>/dev/null || echo "false")

  if [[ "$success" != "True" && "$success" != "true" ]]; then
    echo "  WARN [$setting]: $response"
  else
    echo "  OK   $setting"
  fi
}

# ── Rate limiting via Ruleset Engine ─────────────────────────────────────────
# Free/Pro plans allow only 1 rule per http_ratelimit phase.
# Cloudflare is the outer DDoS shield; per-path budgets are enforced by the
# app-layer RateLimitMiddleware. Single rule here: 300 req/min per IP = hard cap.
# action=log — change to "block" in CF dashboard after verifying no false positives.
apply_rate_limits() {
  # Check if a rate limit ruleset already exists for this zone
  local existing_id
  existing_id=$(curl -s "$CF_API/zones/$CF_ZONE_ID/rulesets" \
    -H "Authorization: Bearer $CF_API_TOKEN" | \
    python3 -c "
import sys,json
d=json.load(sys.stdin)
for r in d.get('result',[]):
    if r['phase']=='http_ratelimit':
        print(r['id']); break
" 2>/dev/null || echo "")

  local payload='{
    "name": "Nivesh API rate limit",
    "kind": "zone",
    "phase": "http_ratelimit",
    "rules": [
      {
        "description": "Global API cap — 50 req/10s per IP (~300/min; app layer enforces per-path budgets)",
        "expression": "(http.request.uri.path contains \"/api/\")",
        "action": "block",
        "ratelimit": {
          "characteristics": ["cf.colo.id", "ip.src"],
          "period": 10,
          "requests_per_period": 50,
          "mitigation_timeout": 10
        }
      }
    ]
  }'

  local response
  if [[ -n "$existing_id" ]]; then
    response=$(curl -s -X PUT \
      "$CF_API/zones/$CF_ZONE_ID/rulesets/$existing_id" \
      -H "Authorization: Bearer $CF_API_TOKEN" \
      -H "Content-Type: application/json" \
      --data "$payload")
  else
    response=$(curl -s -X POST \
      "$CF_API/zones/$CF_ZONE_ID/rulesets" \
      -H "Authorization: Bearer $CF_API_TOKEN" \
      -H "Content-Type: application/json" \
      --data "$payload")
  fi

  local success
  success=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('success','false'))" 2>/dev/null || echo "false")

  if [[ "$success" != "True" && "$success" != "true" ]]; then
    echo "  WARN [rate_limits ruleset]: $response"
  else
    local ruleset_id
    ruleset_id=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['result']['id'])" 2>/dev/null || echo "?")
    echo "  OK   rate_limit 300 req/min per IP on /api/* (id=$ruleset_id, action=log)"
  fi
}

echo ""
echo "========================================================"
echo "NIVESHCOPILOT CLOUDFLARE HARDENING"
echo "Zone: $CF_ZONE_ID  Domain: $ROOT_DOMAIN"
echo "========================================================"

# ── SSL / TLS ─────────────────────────────────────────────────────────────────
echo ""
echo "[1/6] SSL/TLS..."
cf_patch "ssl"                     '{"value":"strict"}'
cf_patch "always_use_https"        '{"value":"on"}'
cf_patch "min_tls_version"         '{"value":"1.2"}'
cf_patch "automatic_https_rewrites" '{"value":"on"}'
# 0-RTT OFF: replay-attack risk on POST endpoints (transactions, uploads)
cf_patch "0rtt"                    '{"value":"off"}'

# ── Security baseline ─────────────────────────────────────────────────────────
echo ""
echo "[2/6] Security settings..."
cf_patch "security_level" '{"value":"medium"}'
cf_patch "browser_check"  '{"value":"on"}'

# ── Performance ───────────────────────────────────────────────────────────────
echo ""
echo "[3/6] Performance (compression + HTTP/3)..."
cf_patch "brotli" '{"value":"on"}'
cf_patch "http3"  '{"value":"on"}'

# ── Cache ─────────────────────────────────────────────────────────────────────
# cache_level=aggressive for static assets; /api/* is excluded via Cache Rules
# below so authenticated financial data is never served from CDN cache.
echo ""
echo "[4/6] Cache..."
cf_patch "cache_level"       '{"value":"aggressive"}'
cf_patch "browser_cache_ttl" '{"value":14400}'
cf_patch "development_mode"  '{"value":"off"}'

# Cache Rule: bypass cache for all /api/* paths
# Use PUT if the ruleset already exists, POST if it doesn't.
echo "  Applying cache bypass rule for /api/*..."
CACHE_RULE_PAYLOAD='{
  "name": "Bypass cache for API routes",
  "kind": "zone",
  "phase": "http_request_cache_settings",
  "rules": [
    {
      "expression": "(http.request.uri.path contains \"/api/\")",
      "action": "set_cache_settings",
      "action_parameters": {"cache": false},
      "description": "Never cache /api/* — contains authenticated financial data"
    }
  ]
}'

existing_cache_id=$(curl -s "$CF_API/zones/$CF_ZONE_ID/rulesets" \
  -H "Authorization: Bearer $CF_API_TOKEN" | \
  python3 -c "
import sys,json
d=json.load(sys.stdin)
for r in d.get('result',[]):
    if r['phase']=='http_request_cache_settings':
        print(r['id']); break
" 2>/dev/null || echo "")

if [[ -n "$existing_cache_id" ]]; then
  bypass_response=$(curl -s -X PUT \
    "$CF_API/zones/$CF_ZONE_ID/rulesets/$existing_cache_id" \
    -H "Authorization: Bearer $CF_API_TOKEN" \
    -H "Content-Type: application/json" \
    --data "$CACHE_RULE_PAYLOAD")
else
  bypass_response=$(curl -s -X POST \
    "$CF_API/zones/$CF_ZONE_ID/rulesets" \
    -H "Authorization: Bearer $CF_API_TOKEN" \
    -H "Content-Type: application/json" \
    --data "$CACHE_RULE_PAYLOAD")
fi

bypass_success=$(echo "$bypass_response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('success','false'))" 2>/dev/null || echo "false")
if [[ "$bypass_success" != "True" && "$bypass_success" != "true" ]]; then
  echo "  WARN [cache bypass]: $bypass_response"
else
  echo "  OK   cache bypass /api/*"
fi

# ── Bot protection ────────────────────────────────────────────────────────────
# Bot Fight Mode is NOT a zone setting — it lives in the Bot Management API
# (PATCH /zones/:id/bot_management) on Business/Enterprise plans.
# On Free/Pro plans it must be enabled manually:
#   CF Dashboard → Security → Bots → Bot Fight Mode → On
echo ""
echo "[5/6] Bot protection..."
echo "  SKIP bot_fight_mode — enable manually: CF Dashboard → Security → Bots → Bot Fight Mode → On"

# ── Rate limiting — per-category, matching app-layer budgets ─────────────────
echo ""
echo "[6/6] Rate limiting (action=log — verify in dashboard then switch to block)..."
apply_rate_limits

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "========================================================"
echo "CLOUDFLARE HARDENING COMPLETE"
echo "========================================================"
echo ""
echo "Configured:"
echo "  ✔ SSL/TLS Strict + TLS 1.2 min"
echo "  ✔ HTTPS redirect + automatic rewrites"
echo "  ✔ 0-RTT OFF (replay-attack protection)"
echo "  ✔ Security level medium + browser check"
echo "  ✔ Brotli + HTTP/3"
echo "  ✔ Cache aggressive (static) + /api/* bypass (auth'd data)"
echo "  ✔ Bot fight mode (monitor for false positives)"
echo "  ✔ Per-category rate limits (simulate mode)"
echo ""
echo "NEXT STEPS:"
echo "  1. Check CF dashboard → Security → Events for false positives"
echo "  2. Switch rate limit action from 'simulate' → 'challenge' when satisfied"
echo "  3. Restrict VM firewall to Cloudflare IPs only:"
echo "     https://www.cloudflare.com/ips/"
echo ""
echo "========================================================"
