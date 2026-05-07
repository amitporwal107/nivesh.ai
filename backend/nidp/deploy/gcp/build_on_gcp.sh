#!/usr/bin/env bash
# build_on_gcp.sh — build all NIDP images via Google Cloud Build
# (zero local Docker required) and update Cloud Run Jobs.
#
# Why: removes Docker Desktop / local proxy / WSL2 networking from
# the deploy loop. Cloud Build runs each build on a clean, fast VM
# inside Google's network → no NSE IP-blocks during pip install,
# no caching surprises, no "stale image" mysteries.
#
# Usage:
#   ./build_on_gcp.sh                       # build all 13, migrate, update jobs
#   ./build_on_gcp.sh --service=bhavcopy    # one service only
#   ./build_on_gcp.sh --tag=mytag           # custom tag (default: timestamp)
#   ./build_on_gcp.sh --no-update           # just build, don't update Cloud Run
#   ./build_on_gcp.sh --no-cache            # force --no-cache in Docker build
#   ./build_on_gcp.sh --no-migrations       # skip schema-migration step
#
# Order: build → migrate → update Cloud Run. Migrations run BEFORE
# the new image starts so freshly-deployed code never reads a stale
# schema. Build failures abort before migrations; migration failures
# abort before Cloud Run update so old code keeps running against
# the old schema.
#
# Cost: free up to 120 build-minutes/day on Cloud Build's default
# tier. Each NIDP image takes ~2-3 min, so building all 13 = ~30-40
# build-minutes, fits well in the free tier.

set -uo pipefail

GREEN="\033[1;32m"; RED="\033[1;31m"; YEL="\033[1;33m"; CYAN="\033[1;36m"; RESET="\033[0m"
log()  { echo -e "${CYAN}[gcp-build]${RESET} $*"; }
ok()   { echo -e "${GREEN}[gcp-build] ✅${RESET} $*"; }
warn() { echo -e "${YEL}[gcp-build] ⚠${RESET}  $*"; }
err()  { echo -e "${RED}[gcp-build] ❌${RESET} $*"; }

PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
REGION="${GCP_REGION:-asia-south1}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NIDP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_ROOT="$(cd "$NIDP_ROOT/../.." && pwd)"
AR_REPO="${REGION}-docker.pkg.dev/${PROJECT}/nidp"

ALL_SERVICES=(
    # Phase 1A — core market data + reference + macro
    bulk_deals block_deals bhavcopy delivery
    index_close index_constituents fii_dii corporate_actions
    nse_calendar rbi_yields snapshot_builder
    fred_macro yfinance_backfill
    # Phase 1B — financials + shareholding + adjusted close + sector + F&O
    nse_financials nse_shareholding price_adjuster
    nse_equity_master fno_bhavcopy
)

SERVICE_FILTER=""
NO_UPDATE=""
NO_CACHE=""
NO_MIGRATIONS=""
TAG="$(date -u +%Y%m%d-%H%M%S)"

for arg in "$@"; do
    case "$arg" in
        --service=*)     SERVICE_FILTER="${arg#*=}" ;;
        --tag=*)         TAG="${arg#*=}" ;;
        --no-update)     NO_UPDATE=1 ;;
        --no-cache)      NO_CACHE=1 ;;
        --no-migrations) NO_MIGRATIONS=1 ;;
        -h|--help)       sed -n '2,26p' "$0"; exit 0 ;;
    esac
done

# ── Pre-flight ──────────────────────────────────────────────────────
if ! command -v gcloud >/dev/null; then
    err "gcloud not found"; exit 1
fi
ACTIVE=$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1)
[[ -z "$ACTIVE" ]] && { err "no active gcloud account — run: gcloud auth login"; exit 1; }
ok "authenticated as: $ACTIVE"

if ! gcloud artifacts repositories describe nidp \
        --location="$REGION" --project="$PROJECT" &>/dev/null; then
    err "Artifact Registry 'nidp' missing in $REGION — run bootstrap.sh first"; exit 1
fi
ok "Artifact Registry: $AR_REPO"

# Ensure cloudbuild API is enabled
if ! gcloud services list --enabled --project="$PROJECT" \
        --filter='config.name=cloudbuild.googleapis.com' \
        --format='value(config.name)' 2>/dev/null | grep -q cloudbuild; then
    log "enabling cloudbuild.googleapis.com..."
    gcloud services enable cloudbuild.googleapis.com --project="$PROJECT"
fi
ok "cloudbuild API enabled"

# ── Determine services to build ─────────────────────────────────────
if [[ -n "$SERVICE_FILTER" ]]; then
    SERVICES=("$SERVICE_FILTER")
else
    SERVICES=("${ALL_SERVICES[@]}")
fi

cd "$REPO_ROOT"
echo
log "config: project=$PROJECT  region=$REGION  tag=$TAG  count=${#SERVICES[@]}"

# ── Build a cloudbuild.yaml per service to a /tmp dir ───────────────
TMPDIR=$(mktemp -d)
trap 'rm -rf $TMPDIR' EXIT

DOCKER_ARGS_PREFIX="build"
[[ -n "$NO_CACHE" ]] && DOCKER_ARGS_PREFIX="build, --no-cache, --pull"

for svc in "${SERVICES[@]}"; do
    DOCKERFILE="backend/nidp/services/$svc/Dockerfile"
    [[ ! -f "$REPO_ROOT/$DOCKERFILE" ]] && continue
    cat > "$TMPDIR/build-${svc}.yaml" << EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args: [${DOCKER_ARGS_PREFIX},
           -f, ${DOCKERFILE},
           -t, ${AR_REPO}/${svc}:${TAG},
           -t, ${AR_REPO}/${svc}:latest,
           .]
images:
  - ${AR_REPO}/${svc}:${TAG}
  - ${AR_REPO}/${svc}:latest
options:
  logging: CLOUD_LOGGING_ONLY
  machineType: E2_HIGHCPU_8
timeout: 600s
EOF
done

# ── Submit builds (parallel) ────────────────────────────────────────
echo
log "submitting ${#SERVICES[@]} builds to Cloud Build (parallel)..."
declare -A BUILD_PIDS
for svc in "${SERVICES[@]}"; do
    [[ ! -f "$TMPDIR/build-${svc}.yaml" ]] && continue
    {
        if gcloud builds submit \
                --project="$PROJECT" \
                --config="$TMPDIR/build-${svc}.yaml" \
                . 2>"$TMPDIR/build-${svc}.log" >>"$TMPDIR/build-${svc}.log"; then
            echo "OK"  > "$TMPDIR/build-${svc}.status"
        else
            echo "FAIL" > "$TMPDIR/build-${svc}.status"
        fi
    } &
    BUILD_PIDS[$svc]=$!
    echo "  → $svc (pid ${BUILD_PIDS[$svc]})"
done

# Track progress
log "waiting for builds to finish (Cloud Build runs in parallel; total ≤ 5 min if all succeed)..."
for svc in "${!BUILD_PIDS[@]}"; do
    wait "${BUILD_PIDS[$svc]}"
done

# ── Report build results ────────────────────────────────────────────
echo
SUCCEEDED=()
FAILED=()
for svc in "${SERVICES[@]}"; do
    [[ ! -f "$TMPDIR/build-${svc}.status" ]] && continue
    status=$(cat "$TMPDIR/build-${svc}.status")
    if [[ "$status" == "OK" ]]; then
        SUCCEEDED+=("$svc")
        ok "  $svc → $TAG"
    else
        FAILED+=("$svc")
        err "  $svc — see ${TMPDIR}/build-${svc}.log"
        tail -20 "$TMPDIR/build-${svc}.log" | sed 's/^/     /'
    fi
done

# ── Apply pending DB migrations ─────────────────────────────────────
# Runs AFTER builds succeed but BEFORE Cloud Run update. If the
# migration fails, we abort before flipping any image tags so the
# old code keeps running against the old schema.
if [[ -z "$NO_MIGRATIONS" && -z "$NO_UPDATE" && ${#FAILED[@]} -eq 0 && ${#SUCCEEDED[@]} -gt 0 ]]; then
    echo
    log "applying NIDP migrations (phase6_robust.sh)..."
    if [[ -x "$SCRIPT_DIR/phase6_robust.sh" ]]; then
        if "$SCRIPT_DIR/phase6_robust.sh"; then
            ok "migrations applied"
        else
            err "migration step failed — aborting Cloud Run update"
            err "  fix the migration, then re-run with --no-cache to retry"
            exit 1
        fi
    else
        warn "phase6_robust.sh not found or not executable — skipping migrations"
        warn "  re-add it under $SCRIPT_DIR/ or pass --no-migrations to silence"
    fi
fi

# ── Update Cloud Run Jobs to the new tag ────────────────────────────
if [[ -z "$NO_UPDATE" && ${#SUCCEEDED[@]} -gt 0 ]]; then
    echo
    log "updating Cloud Run Jobs to image tag $TAG..."
    for svc in "${SUCCEEDED[@]}"; do
        job_name="nidp-${svc//_/-}"
        if gcloud run jobs describe "$job_name" --region="$REGION" \
                --project="$PROJECT" &>/dev/null; then
            if gcloud run jobs update "$job_name" \
                    --image="${AR_REPO}/${svc}:${TAG}" \
                    --region="$REGION" --project="$PROJECT" \
                    --quiet >/dev/null 2>&1; then
                ok "  $job_name → $TAG"
            else
                err "  $job_name update failed"
            fi
        else
            warn "  $job_name does not exist — bootstrap.sh / deploy.sh first"
        fi
    done
fi

# ── Final summary ───────────────────────────────────────────────────
echo
echo -e "════════════════════════════════════════════════════════════"
echo -e "${GREEN}BUILT${RESET} (${#SUCCEEDED[@]}): ${SUCCEEDED[*]:-(none)}"
[[ ${#FAILED[@]} -gt 0 ]] && echo -e "${RED}FAILED${RESET} (${#FAILED[@]}): ${FAILED[*]}"
echo -e "Tag: ${TAG}"
echo -e "════════════════════════════════════════════════════════════"

if [[ ${#FAILED[@]} -eq 0 && -z "$NO_UPDATE" ]]; then
    cat <<EOF

✅ All builds + Cloud Run updates succeeded.

Smoke-test the deploy:
    gcloud run jobs execute nidp-nse-calendar \\
        --region=${REGION} --project=${PROJECT} --wait

Verify deployed image is on the new tag:
    gcloud run jobs describe nidp-nse-calendar \\
        --region=${REGION} --project=${PROJECT} \\
        --format='value(spec.template.spec.template.spec.containers[0].image)'
EOF
elif [[ ${#FAILED[@]} -gt 0 ]]; then
    err "Some builds failed. Logs in $TMPDIR/build-<svc>.log"
    exit 1
fi
