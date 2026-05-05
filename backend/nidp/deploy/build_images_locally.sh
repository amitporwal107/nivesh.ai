#!/usr/bin/env bash
# build_images_locally.sh — build all 13 NIDP service images on your
# local Docker, smoke-test each (`python -c "import"` inside the image),
# and report which builds succeeded.
#
# Goal: prove every Dockerfile produces a working image BEFORE any GCP
# deploy. Once this passes, the GCP deploy reduces to a `docker push +
# gcloud run jobs update` step that can't introduce code bugs.
#
# Usage:
#   ./build_images_locally.sh                    # build all 13
#   ./build_images_locally.sh --service=bhavcopy # one specific service
#   ./build_images_locally.sh --no-cache         # force fresh build
#
# Pre-reqs:
#   - Docker Desktop running (or any Docker daemon)
#   - Run from the repo root OR from any subdirectory (script auto-detects)

set -uo pipefail

GREEN="\033[1;32m"; RED="\033[1;31m"; YEL="\033[1;33m"; CYAN="\033[1;36m"; RESET="\033[0m"
log()  { echo -e "${CYAN}[build]${RESET} $*"; }
ok()   { echo -e "${GREEN}[build] ✅${RESET} $*"; }
warn() { echo -e "${YEL}[build] ⚠${RESET}  $*"; }
err()  { echo -e "${RED}[build] ❌${RESET} $*"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NIDP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$NIDP_ROOT/../.." && pwd)"

ALL_SERVICES=(
    bulk_deals block_deals bhavcopy delivery
    index_close index_constituents fii_dii corporate_actions
    nse_calendar rbi_yields snapshot_builder
    fred_macro yfinance_backfill
)

SERVICE_FILTER=""
NO_CACHE=""
TAG="local-$(date +%Y%m%d-%H%M%S)"

for arg in "$@"; do
    case "$arg" in
        --service=*) SERVICE_FILTER="${arg#*=}" ;;
        --no-cache)  NO_CACHE="--no-cache" ;;
        --tag=*)     TAG="${arg#*=}" ;;
        -h|--help)   sed -n '2,16p' "$0"; exit 0 ;;
    esac
done

# ── Pre-flight ──────────────────────────────────────────────────────
if ! command -v docker >/dev/null; then
    err "docker not found. Install Docker Desktop."; exit 1
fi
if ! docker info &>/dev/null; then
    err "docker daemon not running. Start Docker Desktop."; exit 1
fi
ok "docker daemon healthy"

cd "$REPO_ROOT"

# ── Determine services to build ─────────────────────────────────────
if [[ -n "$SERVICE_FILTER" ]]; then
    SERVICES=("$SERVICE_FILTER")
else
    SERVICES=("${ALL_SERVICES[@]}")
fi

PASS=0
FAIL=0
PASSED_LIST=()
FAILED_LIST=()
SKIPPED_LIST=()

for svc in "${SERVICES[@]}"; do
    DOCKERFILE="$NIDP_ROOT/services/$svc/Dockerfile"
    if [[ ! -f "$DOCKERFILE" ]]; then
        warn "  no Dockerfile for $svc — skipping"
        SKIPPED_LIST+=("$svc")
        continue
    fi

    IMG="nidp-${svc//_/-}:${TAG}"
    LATEST="nidp-${svc//_/-}:latest"

    echo
    log "──── building $svc → $IMG ────"
    if docker build $NO_CACHE \
        -f "$DOCKERFILE" \
        -t "$IMG" -t "$LATEST" \
        "$REPO_ROOT" 2>&1 | tail -5; then

        # Smoke test: prove the image's Python can import the service module
        # (catches missing deps / typos / import-time crashes that don't
        # show up in `docker build` alone)
        log "  smoke-testing import..."
        if docker run --rm --entrypoint python "$IMG" \
                -c "import nidp.services.${svc}; print('  import OK')" 2>&1 | tail -3; then
            ok "$svc: built + import succeeded"
            PASS=$((PASS+1))
            PASSED_LIST+=("$svc")
        else
            err "$svc: built but import failed (missing dep or runtime bug)"
            FAIL=$((FAIL+1))
            FAILED_LIST+=("$svc")
        fi
    else
        err "$svc: docker build failed"
        FAIL=$((FAIL+1))
        FAILED_LIST+=("$svc")
    fi
done

# ── Summary ─────────────────────────────────────────────────────────
echo
echo -e "════════════════════════════════════════════════════════════"
echo -e "${GREEN}PASSED${RESET} (${PASS}): ${PASSED_LIST[*]:-(none)}"
[[ $FAIL -gt 0 ]] && echo -e "${RED}FAILED${RESET} (${FAIL}): ${FAILED_LIST[*]}"
[[ ${#SKIPPED_LIST[@]} -gt 0 ]] && echo -e "${YEL}SKIPPED${RESET} (${#SKIPPED_LIST[@]}): ${SKIPPED_LIST[*]}"
echo -e "════════════════════════════════════════════════════════════"

if [[ $FAIL -eq 0 ]]; then
    cat <<EOF
${GREEN}✅ All images built + import-tested successfully.${RESET}

Tag: ${TAG}

Optional: run a real ingester locally (against a local PG) to prove
end-to-end behavior before GCP deploy:

    # Bring up local Postgres (only PG, not full stack):
    docker run -d --name nidp-pg-local -p 5433:5432 \\
        -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=nidp \\
        timescale/timescaledb:latest-pg16

    # Apply migrations:
    for f in backend/nidp/migrations/*.sql; do
        docker cp "\$f" nidp-pg-local:/tmp/
        docker exec nidp-pg-local psql -U postgres -d nidp -f "/tmp/\$(basename \$f)"
    done

    # Run a service against local PG (network=host so container can reach localhost):
    docker run --rm --network=host \\
        -e NIDP_POSTGRES_URL='postgres://postgres:postgres@localhost:5433/nidp' \\
        -e NIDP_STORAGE_BACKEND=local \\
        -e NIDP_EVENT_BUS=local \\
        -e NIDP_S3_BUCKET=ignored \\
        -e NIDP_KAFKA_BROKERS=ignored \\
        -e NIDP_SCHEMA_REGISTRY_URL=ignored \\
        -e NIDP_REDIS_URL=ignored \\
        nidp-nse-calendar:${TAG}

    # Verify rows:
    docker exec nidp-pg-local psql -U postgres -d nidp \\
        -c "SELECT count(*) FROM nidp.nse_holidays"

When everything works locally, push to GCP:
    cd backend/nidp/deploy/gcp
    ./deploy.sh --project=niveshdataintelligence --confirm
EOF
    exit 0
else
    err "${FAIL} image(s) failed. Inspect with:"
    for svc in "${FAILED_LIST[@]}"; do
        echo "    docker build -f backend/nidp/services/${svc}/Dockerfile -t debug-${svc} ${REPO_ROOT}"
    done
    exit 1
fi
