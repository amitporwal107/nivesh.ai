#!/usr/bin/env bash
# Shared helpers for scripts/local/*.sh
# Source with:  source "$(dirname "$0")/lib.sh"

set -euo pipefail

# ── pretty output ────────────────────────────────────────────────────
_BOLD="$(tput bold 2>/dev/null || true)"
_DIM="$(tput dim 2>/dev/null || true)"
_RED="$(tput setaf 1 2>/dev/null || true)"
_GRN="$(tput setaf 2 2>/dev/null || true)"
_YEL="$(tput setaf 3 2>/dev/null || true)"
_BLU="$(tput setaf 4 2>/dev/null || true)"
_RST="$(tput sgr0 2>/dev/null || true)"

log_step() {  printf "\n${_BOLD}${_BLU}── %s ──${_RST}\n" "$*"; }
log_info() {  printf "${_DIM}    %s${_RST}\n" "$*"; }
log_ok()   {  printf "${_GRN}  ✓ %s${_RST}\n" "$*"; }
log_warn() {  printf "${_YEL}  ! %s${_RST}\n" "$*"; }
log_err()  {  printf "${_RED}  ✗ %s${_RST}\n" "$*" >&2; }
die()      {  log_err "$*"; exit 1; }

# ── repo root resolution (script lives at scripts/local/lib.sh) ──────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$REPO_ROOT/.env.local"
ENV_FILE_EXAMPLE="$REPO_ROOT/.env.local.example"
FE_ENV_FILE="$REPO_ROOT/frontend/.env.local"
FE_ENV_FILE_EXAMPLE="$REPO_ROOT/frontend/.env.local.example"
COMPOSE_FILE="$REPO_ROOT/docker-compose.local.yml"

# ── docker compose wrapper (compose v2 vs v1) ────────────────────────
COMPOSE() {
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose -f "$COMPOSE_FILE" "$@"
  else
    die "neither 'docker compose' nor 'docker-compose' is installed"
  fi
}

# ── env-file readers (load .env.local into current shell) ────────────
load_env_local() {
  [[ -f "$ENV_FILE" ]] || die "$ENV_FILE not found — run: ./scripts/local/setup.sh env"
  set -a; source "$ENV_FILE"; set +a
}

# Read a single key from .env.local without `source`-ing the file.
env_get() {
  local key="$1"
  [[ -f "$ENV_FILE" ]] || return 1
  grep -E "^${key}=" "$ENV_FILE" | tail -n1 | cut -d= -f2-
}

# Replace or append a key in .env.local.
env_set() {
  local key="$1"; local val="$2"
  touch "$ENV_FILE"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    # macOS sed needs '' after -i; use perl for cross-platform safety
    perl -i -pe "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  fi
}

# ── wait helpers ─────────────────────────────────────────────────────
wait_http() {
  local url="$1"; local tries="${2:-30}"; local sleep_s="${3:-2}"
  for i in $(seq 1 "$tries"); do
    if curl -fsS -m 3 "$url" >/dev/null 2>&1; then
      return 0
    fi
    printf "."
    sleep "$sleep_s"
  done
  printf "\n"
  return 1
}

wait_container_healthy() {
  local name="$1"; local tries="${2:-30}"
  for i in $(seq 1 "$tries"); do
    local status
    status=$(docker inspect --format '{{ .State.Health.Status }}' "$name" 2>/dev/null || echo missing)
    case "$status" in
      healthy) return 0 ;;
      missing) sleep 2; continue ;;
      *)       sleep 2 ;;
    esac
  done
  return 1
}

# ── token generation ─────────────────────────────────────────────────
gen_token() {
  local prefix="${1:-nvd_internal}"
  printf "%s_%s" "$prefix" "$(openssl rand -base64 36 | tr -d '=+/' | cut -c1-48)"
}
