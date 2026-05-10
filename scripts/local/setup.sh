#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────
# Local-laptop bring-up for the COMPLETE Nivesh + NIDP product.
#
# Each "step" below has ONE responsibility, prints exactly what it is
# doing, and bails on the first error (set -e). Nothing is bypassed,
# nothing is silent.
#
# Usage:
#   ./scripts/local/setup.sh <step>
#
#   <step>  prereqs         check docker, docker compose, openssl, curl, jq
#           env             create .env.local + frontend/.env.local from
#                           templates, generate the NIDP internal token
#           build           docker compose build (backend + frontend images)
#           infra           start data plane: mongo, postgres-app, postgres-nidp, redis
#           wait-infra      block until all 4 data-plane containers report healthy
#           migrate         run NIDP SQL migrations against postgres-nidp
#           seed            seed source_registry, daas_api_keys internal row,
#                           materialise intelligence_layer once, sync the
#                           NIDP internal token into the pod backend env
#           services        start app plane: nidp-daas-api, nidp-query-api, backend, frontend
#           verify          run Phase-5 smoke checks (must all pass)
#           all             run every step above, in order
#           down            stop+remove containers (data preserved)
#           clean           stop+remove containers AND wipe volumes (DESTRUCTIVE)
#           logs <svc>      tail logs for one service
#           help            this message
# ────────────────────────────────────────────────────────────────────

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"


# ============================ STEPS ================================

step_prereqs() {
  log_step "STEP 1: Prereqs — docker, docker compose, openssl, curl, jq"
  for bin in docker openssl curl jq; do
    command -v "$bin" >/dev/null 2>&1 || die "missing: $bin (please install it)"
    log_ok "$bin found at $(command -v "$bin")"
  done
  if docker compose version >/dev/null 2>&1; then
    log_ok "docker compose v2: $(docker compose version --short)"
  elif command -v docker-compose >/dev/null 2>&1; then
    log_ok "docker-compose v1: $(docker-compose --version)"
  else
    die "docker compose not found — install Docker Desktop ≥ 4.x"
  fi
  docker info >/dev/null 2>&1 || die "Docker daemon is not running — start Docker Desktop"
  log_ok "Docker daemon is running"
}


step_env() {
  log_step "STEP 2: Generate .env.local + frontend/.env.local"

  if [[ ! -f "$ENV_FILE" ]]; then
    cp "$ENV_FILE_EXAMPLE" "$ENV_FILE"
    log_ok "created $ENV_FILE from .env.local.example"
  else
    log_info "$ENV_FILE already exists — leaving in place"
  fi

  if [[ ! -f "$FE_ENV_FILE" ]]; then
    cp "$FE_ENV_FILE_EXAMPLE" "$FE_ENV_FILE"
    log_ok "created $FE_ENV_FILE from frontend/.env.local.example"
  else
    log_info "$FE_ENV_FILE already exists — leaving in place"
  fi

  # NIDP internal token — generated once, pinned in .env.local. Used
  # both by the DaaS API container (as NIDP_DAAS_INTERNAL_TOKEN) and
  # by the main backend (as NIDP_DAAS_API_KEY) so they share auth.
  local existing
  existing=$(env_get NIDP_DAAS_INTERNAL_TOKEN || true)
  if [[ -z "${existing:-}" ]]; then
    local token
    token=$(gen_token nvd_internal)
    env_set NIDP_DAAS_INTERNAL_TOKEN "$token"
    env_set NIDP_DAAS_API_KEY        "$token"
    log_ok "generated NIDP internal token (pinned in $ENV_FILE)"
  else
    env_set NIDP_DAAS_API_KEY "$existing"
    log_info "NIDP internal token already pinned"
  fi

  # Show the user the keys they still need to fill in.
  log_info ""
  log_info "Open $ENV_FILE and fill in (only what you want to use locally):"
  log_info "  OPENAI_API_KEY            — your OpenAI key (required for chat/copilot/AI features)"
  log_info "  GOOGLE_CLIENT_ID/SECRET   — for Gmail sync + Google sign-in"
  log_info "  CASPARSER_API_KEY         — Nivesh CASparser key (NSDL CAS PDF parsing)"
  log_info "  FRED_API_KEY              — free key from fred.stlouisfed.org"
  log_info ""
  log_info "And $FE_ENV_FILE → REACT_APP_GOOGLE_CLIENT_ID = same as above"
  log_ok "env files ready"
}


step_build() {
  log_step "STEP 3: Build backend + frontend images"
  log_info "this is a one-time long-running step (~3-6 min on first run)"
  COMPOSE build --pull
  log_ok "images built: nivesh/backend:local, nivesh/frontend:local"
}


step_infra() {
  log_step "STEP 4: Start data plane (mongo + postgres-app + postgres-nidp + redis)"
  COMPOSE up -d mongodb postgres-app postgres-nidp redis
  log_ok "data plane containers started"
}


step_wait_infra() {
  log_step "STEP 5: Wait for data plane to be healthy"
  for c in nivesh-mongo nivesh-pg-app nivesh-pg-nidp nivesh-redis; do
    printf "    %-22s " "$c"
    if wait_container_healthy "$c" 60; then
      printf "${_GRN}healthy${_RST}\n"
    else
      printf "${_RED}NOT healthy${_RST}\n"
      die "container $c failed to become healthy — run: $0 logs ${c#nivesh-}"
    fi
  done
}


step_migrate() {
  log_step "STEP 6: Apply NIDP SQL migrations against postgres-nidp"
  load_env_local
  # Run inside the backend image (not the long-lived service) so we
  # don't depend on the daas-api/backend services being up yet. Override
  # NIDP_POSTGRES_URL to use the in-network alias.
  COMPOSE run --rm \
      -e NIDP_POSTGRES_URL="postgresql://${POSTGRES_NIDP_USER:-postgres}:${POSTGRES_NIDP_PASSWORD:-postgres}@postgres-nidp:5432/${POSTGRES_NIDP_DB:-nidp}" \
      --no-deps \
      backend python -m nidp.cli migrate
  log_ok "NIDP migrations applied"
}


step_seed() {
  log_step "STEP 7: Seed source_registry + daas_api_keys + (optional) intelligence_layer"
  load_env_local

  log_info "(7a) source_registry — populates the NIDP UI feed list"
  COMPOSE run --rm \
      -e NIDP_POSTGRES_URL="postgresql://${POSTGRES_NIDP_USER:-postgres}:${POSTGRES_NIDP_PASSWORD:-postgres}@postgres-nidp:5432/${POSTGRES_NIDP_DB:-nidp}" \
      --no-deps backend python /app/backend/nidp/deploy/vm/seed_source_registry.py

  log_info "(7b) daas_api_keys — internal placeholder row for INTERNAL_TOKEN auth"
  local pwd_nidp="${POSTGRES_NIDP_PASSWORD:-postgres}"
  local user_nidp="${POSTGRES_NIDP_USER:-postgres}"
  local db_nidp="${POSTGRES_NIDP_DB:-nidp}"
  docker exec -e PGPASSWORD="$pwd_nidp" nivesh-pg-nidp \
      psql -U "$user_nidp" -d "$db_nidp" -v ON_ERROR_STOP=1 <<'SQL'
INSERT INTO nidp.daas_api_keys (
    key_id, key_prefix, key_hash, name, owner_email, plan,
    rate_limit_rpm, daily_quota, status
) VALUES (
    '00000000-0000-0000-0000-000000000000',
    'nvd_internal',
    'INTERNAL_TOKEN_BYPASS_NEVER_MATCHES_HASH',
    'internal',
    'internal@nidp.local',
    'internal',
    6000, NULL, 'active'
)
ON CONFLICT (key_id) DO NOTHING;
SQL
  log_ok "internal daas_api_keys row seeded"

  log_info "(7c) intelligence_layer — first materialisation (security_master / market_snapshot / dq scores)"
  log_info "       this only produces rows if you have already ingested some bhavcopy/nav/etc."
  log_info "       on a fresh DB it will succeed with zero rows; that's fine."
  COMPOSE run --rm \
      -e NIDP_POSTGRES_URL="postgresql://${user_nidp}:${pwd_nidp}@postgres-nidp:5432/${db_nidp}" \
      --no-deps backend python -m nidp.services.intelligence_layer || \
      log_warn "intelligence_layer materialisation reported issues — see logs above (often expected on empty DB)"

  log_ok "seed step complete"
}


step_services() {
  log_step "STEP 8: Start app plane (nidp-daas-api, nidp-query-api, backend, frontend)"
  COMPOSE up -d nidp-daas-api nidp-query-api backend frontend
  log_info "tail logs in another shell:    ./scripts/local/setup.sh logs backend"
  log_ok "app plane containers started"
}


step_verify() {
  log_step "STEP 9: Verify (Phase 5 smoke tests)"
  bash "$SCRIPT_DIR/smoke.sh"
}


step_down() {
  log_step "STOP — preserve volumes"
  COMPOSE down
}


step_clean() {
  log_step "CLEAN — DESTRUCTIVE: stop + remove containers + wipe volumes"
  COMPOSE down -v
  log_ok "all containers removed and volumes wiped"
}


step_logs() {
  local svc="${1:-}"; [[ -n "$svc" ]] || die "usage: $0 logs <service>"
  COMPOSE logs --tail=100 -f "$svc"
}


step_all() {
  step_prereqs
  step_env
  step_build
  step_infra
  step_wait_infra
  step_migrate
  step_seed
  step_services
  log_step "Waiting 6s for app plane to bind ports …"
  sleep 6
  step_verify
  log_step "${_GRN}🎉  Local Nivesh + NIDP stack is up.${_RST}"
  log_info "    Frontend:   http://localhost:${FRONTEND_PORT:-3000}"
  log_info "    Backend:    http://localhost:${BACKEND_PORT:-8001}/docs"
  log_info "    NIDP DaaS:  http://localhost:${NIDP_DAAS_PORT:-8083}/docs"
  log_info "    NIDP Query: http://localhost:${NIDP_QUERY_PORT:-8090}/docs"
}


# ============================ DISPATCH =============================

show_help() { sed -n '2,/^# *──/p' "$0" | sed 's/^# \?//'; }

case "${1:-help}" in
  prereqs)    step_prereqs ;;
  env)        step_env ;;
  build)      step_build ;;
  infra)      step_infra ;;
  wait-infra) step_wait_infra ;;
  migrate)    step_migrate ;;
  seed)       step_seed ;;
  services)   step_services ;;
  verify)     step_verify ;;
  all)        step_all ;;
  down)       step_down ;;
  clean)      step_clean ;;
  logs)       shift; step_logs "${1:-}" ;;
  help|-h|--help) show_help ;;
  *)          show_help; exit 2 ;;
esac
