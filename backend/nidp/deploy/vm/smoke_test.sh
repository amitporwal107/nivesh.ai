#!/usr/bin/env bash
# smoke_test.sh — post-deployment smoke test for NIDP data plane.
#
# Run after every deploy to data.niveshcopilot.com to verify:
#   - nginx + TLS termination
#   - DaaS API (/daas/*) auth, health, real /v1/catalog query
#   - Query API (/query/*) auth, health, real /v1/catalog + /v1/feeds query
#   - Grafana (/grafana/*) reachable
#   - Loopback isolation — raw ports 8083/8090/3000 are NOT publicly exposed
#
# Usage:
#   smoke_test.sh                        # tokens read from env
#   NIDP_DAAS_API_KEY=… NIDP_QUERY_API_TOKEN=… smoke_test.sh
#   smoke_test.sh --verbose
#
# Exits 0 iff every required check passes; otherwise 1.

set -uo pipefail

DOMAIN="${NIDP_DOMAIN:-data.niveshcopilot.com}"
ORIGIN_IP="${NIDP_ORIGIN_IP:-34.93.60.254}"

DAAS_KEY="${NIDP_DAAS_API_KEY:-${NIDP_DAAS_INTERNAL_TOKEN:-}}"
QUERY_TOKEN="${NIDP_QUERY_API_TOKEN:-}"

VERBOSE=0
for arg in "$@"; do
    case "$arg" in
        -v|--verbose) VERBOSE=1 ;;
        -h|--help)    sed -n '2,18p' "$0"; exit 0 ;;
    esac
done

# ── output helpers ────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    RED="\033[0;31m"; GREEN="\033[0;32m"; YELLOW="\033[0;33m"
    CYAN="\033[0;36m"; GRAY="\033[0;90m"; BOLD="\033[1m"; RESET="\033[0m"
else
    RED=""; GREEN=""; YELLOW=""; CYAN=""; GRAY=""; BOLD=""; RESET=""
fi

PASS=0; FAIL=0; SKIP=0
FAILED_TESTS=()

pass()    { echo -e "  ${GREEN}✓${RESET} $1"; PASS=$((PASS+1)); }
fail()    { echo -e "  ${RED}✗${RESET} ${BOLD}$1${RESET}";
            [[ -n "${2:-}" ]] && echo -e "    ${GRAY}${2}${RESET}";
            FAIL=$((FAIL+1)); FAILED_TESTS+=("$1"); }
skip()    { echo -e "  ${YELLOW}-${RESET} $1 ${GRAY}(skipped: $2)${RESET}"; SKIP=$((SKIP+1)); }
section() { echo -e "\n${BOLD}${CYAN}▶ $1${RESET}"; }
trace()   { [[ $VERBOSE -eq 1 ]] && echo -e "    ${GRAY}${1}${RESET}" || true; }

echo -e "${BOLD}NIDP smoke test${RESET}  ${GRAY}— $(date -Iseconds)${RESET}"
echo -e "  domain : ${DOMAIN}"
echo -e "  origin : ${ORIGIN_IP}"
echo -e "  daas key   : $([[ -n "$DAAS_KEY"    ]] && echo "set" || echo "${YELLOW}unset${RESET}")"
echo -e "  query token: $([[ -n "$QUERY_TOKEN" ]] && echo "set" || echo "${YELLOW}unset${RESET}")"

# ── 1. TLS + nginx ────────────────────────────────────────────────────────
section "1. TLS + nginx reverse proxy"

resp=$(curl -sf --max-time 5 "https://${DOMAIN}/health" 2>&1) || resp="ERR"
if [[ "$resp" == "ok" ]]; then
    pass "GET https://${DOMAIN}/health → ok"
else
    fail "GET https://${DOMAIN}/health" "got: $resp"
fi

cert=$(echo | openssl s_client -servername "$DOMAIN" -connect "${DOMAIN}:443" \
            -verify_return_error 2>/dev/null \
        | openssl x509 -noout -subject -issuer -enddate 2>/dev/null) || cert=""
if [[ -n "$cert" ]]; then
    pass "TLS cert presented and validates"
    trace "$cert"
else
    fail "TLS cert" "openssl handshake failed"
fi

redirect=$(curl -sI --max-time 5 "http://${DOMAIN}/health" 2>&1 | head -1)
if echo "$redirect" | grep -qE "30[12]"; then
    pass "HTTP → HTTPS redirect"
else
    fail "HTTP → HTTPS redirect" "got: $redirect"
fi

# ── 2. DaaS API ───────────────────────────────────────────────────────────
section "2. DaaS API  (/daas/*)"

resp=$(curl -sf --max-time 5 "https://${DOMAIN}/daas/health" 2>&1) || resp="ERR"
if echo "$resp" | grep -q '"ok":true'; then
    pass "GET /daas/health → ok"
    trace "$resp"
else
    fail "GET /daas/health" "$resp"
fi

code=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" "https://${DOMAIN}/daas/v1/catalog")
if [[ "$code" == "401" || "$code" == "403" ]]; then
    pass "GET /daas/v1/catalog without auth → ${code}"
else
    fail "GET /daas/v1/catalog auth" "expected 401/403, got ${code}"
fi

if [[ -n "$DAAS_KEY" ]]; then
    body=$(curl -s --max-time 30 -H "X-API-Key: $DAAS_KEY" "https://${DOMAIN}/daas/v1/catalog")
    if echo "$body" | python3 -c '
import json,sys
d=json.load(sys.stdin)
assert isinstance(d.get("datasets") or d.get("tables") or d.get("data") or d, (list,dict))
' 2>/dev/null; then
        pass "GET /daas/v1/catalog with X-API-Key → JSON payload"
        trace "$(echo "$body" | head -c 150)…"
    else
        fail "GET /daas/v1/catalog with X-API-Key" "$(echo "$body" | head -c 200)"
    fi
else
    skip "GET /daas/v1/catalog with X-API-Key" "NIDP_DAAS_API_KEY not set"
fi

# ── 3. Query API ──────────────────────────────────────────────────────────
section "3. Query API  (/query/*)"

resp=$(curl -sf --max-time 5 "https://${DOMAIN}/query/health" 2>&1) || resp="ERR"
if echo "$resp" | grep -q '"ok":true'; then
    pass "GET /query/health → ok"
    trace "$resp"
else
    fail "GET /query/health" "$resp"
fi

code=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" "https://${DOMAIN}/query/catalog")
if [[ "$code" == "401" || "$code" == "403" ]]; then
    pass "GET /query/catalog without auth → ${code}"
else
    fail "GET /query/catalog auth" "expected 401/403, got ${code}"
fi

if [[ -n "$QUERY_TOKEN" ]]; then
    body=$(curl -s --max-time 30 -H "Authorization: Bearer $QUERY_TOKEN" \
                "https://${DOMAIN}/query/catalog")
    if echo "$body" | python3 -c '
import json,sys
d=json.load(sys.stdin)
assert isinstance(d.get("tables", []), list), "no tables[]"
assert len(d["tables"]) > 0, "tables empty"
' 2>/dev/null; then
        n=$(echo "$body" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["tables"]))')
        pass "GET /query/catalog with bearer → ${n} tables"
    else
        fail "GET /query/catalog with bearer" "$(echo "$body" | head -c 200)"
    fi

    body=$(curl -s --max-time 30 -H "Authorization: Bearer $QUERY_TOKEN" \
                "https://${DOMAIN}/query/feeds")
    if echo "$body" | python3 -c '
import json,sys
d=json.load(sys.stdin)
assert isinstance(d.get("feeds", []), list)
' 2>/dev/null; then
        n=$(echo "$body" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["feeds"]))')
        pass "GET /query/feeds with bearer → ${n} feeds"
    else
        fail "GET /query/feeds with bearer" "$(echo "$body" | head -c 200)"
    fi

    body=$(curl -s --max-time 30 -H "Authorization: Bearer $QUERY_TOKEN" \
                "https://${DOMAIN}/query/validation?limit=5")
    if echo "$body" | python3 -c '
import json,sys
d=json.load(sys.stdin)
assert "validation" in d
' 2>/dev/null; then
        pass "GET /query/validation with bearer → ok"
    else
        fail "GET /query/validation" "$(echo "$body" | head -c 200)"
    fi
else
    skip "Query API authenticated calls" "NIDP_QUERY_API_TOKEN not set"
fi

# ── 4. Grafana ────────────────────────────────────────────────────────────
section "4. Grafana  (/grafana/*)"

code=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" "https://${DOMAIN}/grafana/api/health")
if [[ "$code" == "200" ]]; then
    pass "GET /grafana/api/health → 200"
elif [[ "$code" == "502" || "$code" == "503" ]]; then
    skip "GET /grafana/api/health" "grafana not running (got ${code})"
else
    fail "GET /grafana/api/health" "got HTTP ${code}"
fi

# ── 5. Loopback isolation ─────────────────────────────────────────────────
section "5. Loopback isolation  (raw ports MUST be blocked)"

for PORT in 8083 8090 3000; do
    code=$(curl -s --max-time 3 -o /dev/null -w "%{http_code}" \
                "http://${ORIGIN_IP}:${PORT}/health" 2>/dev/null) || code="blocked"
    if [[ "$code" == "blocked" || "$code" == "000" || -z "$code" ]]; then
        pass "port ${PORT} on ${ORIGIN_IP} blocked externally"
    else
        fail "port ${PORT} on ${ORIGIN_IP}" \
             "got HTTP ${code} — port is publicly reachable (security issue)"
    fi
done

# ── Summary ───────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}Summary:${RESET} ${GREEN}${PASS} passed${RESET}, ${RED}${FAIL} failed${RESET}, ${YELLOW}${SKIP} skipped${RESET}"

if [[ $FAIL -gt 0 ]]; then
    echo -e "\n${RED}${BOLD}FAILED:${RESET}"
    for t in "${FAILED_TESTS[@]}"; do echo "  - $t"; done
    exit 1
fi

echo -e "${GREEN}${BOLD}✓ All NIDP smoke tests passed.${RESET}"
