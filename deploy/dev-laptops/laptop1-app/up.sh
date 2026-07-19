#!/usr/bin/env bash
# up.sh — bring up the laptop 1 (nivesh-app-vm replica) stack.
#
#   ./up.sh              build + start everything (v5-only)
#   ./up.sh --migrate    run the app Postgres migrations, then exit
#   ./up.sh --no-build   start without rebuilding (fast restart)
#   ./up.sh --with-v2    also build/start the legacy V2 frontend
#
# This stack is v5-only by default: the V2 frontend is behind the `v2`
# compose profile and nginx 302s / to /v5/work. v5 does not depend on V2.
#
# On Windows run from WSL2 (Ubuntu) with Docker Desktop's WSL2 backend.

set -euo pipefail
cd "$(dirname "$0")"

COMPOSE_FILE=docker-compose.app.yml
MIGRATE_ONLY=false
DO_BUILD=true
PROFILES=()

for arg in "$@"; do
    case "$arg" in
        --migrate)  MIGRATE_ONLY=true ;;
        --no-build) DO_BUILD=false ;;
        --with-v2)  PROFILES+=(--profile v2) ;;
        *) echo "unknown flag: $arg" >&2; exit 2 ;;
    esac
done

if [[ ! -f .env ]]; then
    echo "FATAL: .env not found. Run:  cp .env.example .env  then fill it in." >&2
    exit 1
fi

# Fail fast with a useful message instead of a container dying opaquely.
missing=()
for v in NIDP_HOST NIDP_DAAS_INTERNAL_TOKEN NIDP_QUERY_API_TOKEN \
         PI_POSTGRES_PASSWORD PI_MONGO_PASSWORD PI_REDIS_PASSWORD; do
    val=$(grep -E "^${v}=" .env | cut -d= -f2- || true)
    [[ -z "$val" ]] && missing+=("$v")
done
if (( ${#missing[@]} )); then
    echo "FATAL: these are unset in .env:" >&2
    printf '  - %s\n' "${missing[@]}" >&2
    echo "" >&2
    echo "NIDP_HOST is laptop 2's LAN IP. The two NIDP_*_TOKEN values must" >&2
    echo "match laptop 2's .env exactly, or every NIDP call returns 401." >&2
    exit 1
fi

set -a; source .env; set +a

# Reachability check for laptop 2 — a wrong NIDP_HOST is the single most
# likely setup mistake, and it otherwise shows up much later as empty data.
echo "==> Checking laptop 2 at ${NIDP_HOST}:${NIDP_EDGE_PORT:-8080}"
if curl -sf --max-time 5 "http://${NIDP_HOST}:${NIDP_EDGE_PORT:-8080}/healthz" >/dev/null 2>&1; then
    echo "    reachable ✓"
else
    echo "    WARNING: no response from http://${NIDP_HOST}:${NIDP_EDGE_PORT:-8080}/healthz" >&2
    echo "    The app will start, but every NIDP-backed screen will be empty." >&2
    echo "    Check: laptop 2 is up (./up.sh there), both machines are on the" >&2
    echo "    same network, and Windows Firewall allows inbound 8080 on laptop 2." >&2
fi

if $MIGRATE_ONLY; then
    echo "==> Starting Postgres only"
    docker compose -f "$COMPOSE_FILE" up -d postgres
    until [[ "$(docker inspect -f '{{.State.Health.Status}}' nivesh-lt-postgres 2>/dev/null)" == "healthy" ]]; do
        sleep 3; printf '.'
    done
    echo ""
    docker compose -f "$COMPOSE_FILE" --profile migrate run --rm app-migrate
    exit $?
fi

if $DO_BUILD; then
    echo "==> Building (frontends bake APP_PUBLIC_URL=${APP_PUBLIC_URL:-http://localhost:3000})"
    docker compose -f "$COMPOSE_FILE" "${PROFILES[@]+"${PROFILES[@]}"}" build
fi

echo "==> Starting stack"
docker compose -f "$COMPOSE_FILE" "${PROFILES[@]+"${PROFILES[@]}"}" up -d
sleep 5
docker compose -f "$COMPOSE_FILE" ps

cat <<EOF

─────────────────────────────────────────────────────────────
Laptop 1 (app) is up.

  http://localhost:3000/          -> redirects to /v5/work
  http://localhost:3000/v5/       frontend-v5
  http://localhost:3000/api/docs  FastAPI docs
  http://localhost:8001/docs      backend direct

Cloudflare tunnel: point the route at  http://localhost:3000
(NOT https:// — this edge serves plain HTTP. See README.)

Talking to laptop 2 at: http://${NIDP_HOST}:${NIDP_EDGE_PORT:-8080}
─────────────────────────────────────────────────────────────
EOF
