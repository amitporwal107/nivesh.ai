#!/usr/bin/env bash
# Phase 5 smoke tests — must ALL pass for "complete local" sign-off.
# Each test prints PASS or FAIL with the actual response. Exits non-zero
# on any failure so CI / setup.sh can block on it.

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

load_env_local

PASS=0; FAIL=0
ok()   { log_ok "$*"; PASS=$((PASS+1)); }
nope() { log_err "$*"; FAIL=$((FAIL+1)); }

BACKEND="http://localhost:${BACKEND_PORT:-8001}"
FRONTEND="http://localhost:${FRONTEND_PORT:-3000}"
DAAS="http://localhost:${NIDP_DAAS_PORT:-8083}"
QUERY="http://localhost:${NIDP_QUERY_PORT:-8090}"
KEY="$(env_get NIDP_DAAS_API_KEY || true)"

log_step "Phase 5 smoke tests"

# 1. NIDP infra healthy
log_info "Test 1: NIDP DaaS API /openapi.json reachable"
if curl -fsS -m 5 "$DAAS/openapi.json" >/dev/null; then ok "DaaS up"; else nope "DaaS unreachable at $DAAS"; fi

log_info "Test 2: NIDP Query API /openapi.json reachable"
if curl -fsS -m 5 "$QUERY/openapi.json" >/dev/null; then ok "Query API up"; else nope "Query API unreachable at $QUERY"; fi

# 3. /v1/catalog includes intelligence datasets
log_info "Test 3: /v1/catalog?domain=Intelligence returns ≥9 datasets"
body=$(curl -fsS -m 5 -H "X-API-Key: $KEY" "$DAAS/v1/catalog?domain=Intelligence" || true)
count=$(echo "$body" | jq -r '[.datasets[]?|select(.domain=="Intelligence")]|length' 2>/dev/null || echo 0)
if [[ "$count" -ge 9 ]]; then ok "$count Intelligence datasets in catalog"; else nope "expected ≥9 got $count"; fi

# 4. /v1/intelligence/portfolio/{user}/snapshot 404 (or 200) shape
log_info "Test 4: /v1/intelligence/portfolio/test_user/snapshot returns 200 OR 404 (not 5xx)"
code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' -H "X-API-Key: $KEY" "$DAAS/v1/intelligence/portfolio/test_user/snapshot")
if [[ "$code" =~ ^(200|404)$ ]]; then ok "got $code"; else nope "got $code (expected 200|404)"; fi

# 5. Auth enforcement
log_info "Test 5: /v1/catalog without X-API-Key returns 401"
code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$DAAS/v1/catalog")
if [[ "$code" == "401" ]]; then ok "auth enforced"; else nope "got $code (expected 401)"; fi

# 6. Main backend up + serves /api/health (or /docs)
log_info "Test 6: Main backend reachable"
code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$BACKEND/docs")
if [[ "$code" == "200" ]]; then ok "backend up"; else nope "backend got $code at $BACKEND/docs"; fi

# 7. Backend → NIDP DaaS connectivity (proxy endpoint exists)
log_info "Test 7: Backend can reach NIDP via /api/admin/nidp/diag (auth-required, just probing reachability)"
code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$BACKEND/api/admin/nidp/diag")
if [[ "$code" =~ ^(200|401|403)$ ]]; then ok "backend reaches NIDP layer (got $code)"; else nope "got $code"; fi

# 8. Frontend dev server
log_info "Test 8: Frontend dev server responds at /"
code=$(curl -s -o /dev/null -m 8 -w '%{http_code}' "$FRONTEND/")
if [[ "$code" == "200" ]]; then ok "frontend serving"; else nope "frontend got $code (might still be compiling — wait 30s and retry)"; fi

# 9. Mongo reachable from host
log_info "Test 9: MongoDB ping from host"
if docker exec nivesh-mongo mongosh --quiet --eval 'db.runCommand({ping:1}).ok' 2>/dev/null | grep -q 1; then ok "mongo ok"; else nope "mongo ping failed"; fi

# 10. Both Postgres instances reachable
log_info "Test 10: postgres-app reachable"
if docker exec nivesh-pg-app pg_isready -U "${POSTGRES_APP_USER:-nivesh}" -d "${POSTGRES_APP_DB:-nivesh_dev}" >/dev/null 2>&1; then ok "postgres-app ok"; else nope "postgres-app down"; fi

log_info "Test 11: postgres-nidp reachable"
if docker exec nivesh-pg-nidp pg_isready -U "${POSTGRES_NIDP_USER:-postgres}" -d "${POSTGRES_NIDP_DB:-nidp}" >/dev/null 2>&1; then ok "postgres-nidp ok"; else nope "postgres-nidp down"; fi

# 12. Redis reachable
log_info "Test 12: Redis PING"
if docker exec nivesh-redis redis-cli ping 2>/dev/null | grep -q PONG; then ok "redis ok"; else nope "redis down"; fi

# ── summary ──────────────────────────────────────────────────────────
printf "\n${_BOLD}Phase 5 result: ${_GRN}%d passed${_RST} ${_BOLD}/${_RST} ${_RED}%d failed${_RST}\n" "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
