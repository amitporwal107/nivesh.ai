#!/usr/bin/env bash
# up.sh — bring up the laptop 2 (nidp-stack-vm replica) stack.
#
#   ./up.sh                  core + observability
#   ./up.sh --with-feeds     also start the 49-job feed scheduler (AI tier)
#   ./up.sh --with-kafka     also start redpanda + schema registry
#   ./up.sh --migrate        run the 112-migration chain, then exit
#
# On Windows run this from WSL2 (Ubuntu) with Docker Desktop's WSL2 backend
# enabled, or use up.ps1.

set -euo pipefail
cd "$(dirname "$0")"

# ── Safe .env reading ────────────────────────────────────────────────────
# A .env file is NOT a shell script. `source .env` shell-evaluates it, so a
# perfectly valid value breaks bring-up:
#   SMTP_FROM=Nivesh Copilot <noreply@niveshcopilot.com>
#   -> .env: line 63: syntax error near unexpected token `newline'
# Same for values containing ( ) | ' " & ; $ backticks. docker compose does
# NOT shell-evaluate .env, so anything compose accepts must work here too.
#
# env_get reads one key literally, mirroring compose's own semantics:
# an inline comment must be preceded by whitespace.
env_get() {
    sed -n "s/^$1=//p" .env | head -1 \
        | sed -e 's/[[:space:]]\+#.*$//' \
              -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
              -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

COMPOSE_FILE=docker-compose.nidp.yml
PROFILES=()
MIGRATE_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --with-feeds) PROFILES+=(--profile feeds) ;;
        --with-kafka) PROFILES+=(--profile kafka) ;;
        --migrate)    MIGRATE_ONLY=true ;;
        *) echo "unknown flag: $arg" >&2; exit 2 ;;
    esac
done

# ── Preflight ────────────────────────────────────────────────────────────
if [[ ! -f .env ]]; then
    echo "FATAL: .env not found. Run:  cp .env.example .env  then fill it in." >&2
    exit 1
fi

# Fail fast on the vars that have no sane default, rather than letting a
# container die 30 seconds later with an opaque error.
missing=()
for v in NIDP_PG_PASSWORD NIDP_DAAS_INTERNAL_TOKEN NIDP_QUERY_API_TOKEN \
         MINIO_ROOT_PASSWORD GRAFANA_ADMIN_PASSWORD; do
    val=$(env_get "$v")
    [[ -z "$val" ]] && missing+=("$v")
done
if (( ${#missing[@]} )); then
    echo "FATAL: these are unset in .env:" >&2
    printf '  - %s\n' "${missing[@]}" >&2
    echo "Generate tokens with: openssl rand -hex 32" >&2
    exit 1
fi

# Docker Desktop on Windows defaults to 2GB RAM for WSL2, which is not enough
# for TimescaleDB + 10 containers. Warn early with a real number.
if command -v docker >/dev/null; then
    total_mem_b=$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 0)
    total_mem_gb=$(( total_mem_b / 1024 / 1024 / 1024 ))
    if (( total_mem_gb > 0 && total_mem_gb < 8 )); then
        echo "WARNING: Docker reports only ${total_mem_gb}GB of RAM." >&2
        echo "         This stack wants 8GB+ (16GB if you use --with-feeds)." >&2
        echo "         Raise it in Docker Desktop > Settings > Resources," >&2
        echo "         or via [wsl2] memory=12GB in %USERPROFILE%\\.wslconfig" >&2
    fi
fi

if $MIGRATE_ONLY; then
    echo "==> Starting Postgres only"
    docker compose -f "$COMPOSE_FILE" up -d postgres
    echo "==> Waiting for Postgres to be healthy"
    until [[ "$(docker inspect -f '{{.State.Health.Status}}' nidp-lt-postgres 2>/dev/null)" == "healthy" ]]; do
        sleep 3; printf '.'
    done
    echo ""
    echo "==> Running migrations (112 files)"
    docker compose -f "$COMPOSE_FILE" --profile migrate run --rm migrate
    exit $?
fi

echo "==> Building images (first run pulls ~2GB; the AI tier adds ~1.5GB more)"
docker compose -f "$COMPOSE_FILE" "${PROFILES[@]+"${PROFILES[@]}"}" build

echo "==> Starting stack"
docker compose -f "$COMPOSE_FILE" "${PROFILES[@]+"${PROFILES[@]}"}" up -d

echo ""
echo "==> Waiting for health"
sleep 5
docker compose -f "$COMPOSE_FILE" ps

cat <<'EOF'

─────────────────────────────────────────────────────────────
Laptop 2 (NIDP) is up. Endpoints:

  http://localhost:8080/daas/     DaaS API
  http://localhost:8080/query/    Query API
  http://localhost:8080/grafana/  Grafana
  http://localhost:9090           Prometheus
  http://localhost:9001           MinIO console
  localhost:5433                  Postgres (TimescaleDB)

Tell laptop 1 where to find this box — put its LAN IP in laptop 1's .env:
  NIDP_HOST=<this machine's LAN IP>

Find it with:   ip route get 1.1.1.1 | awk '{print $7; exit}'
        (Win):  ipconfig | findstr IPv4

Next: restore the staging dump
  ./restore.sh dumps/nidp_staging_YYYYMMDD.dump
─────────────────────────────────────────────────────────────
EOF
