#!/usr/bin/env bash
# force_rebuild_via_cloudbuild.sh — bulletproof rebuild + redeploy.
#
# Bypasses local Docker entirely (Cloud Build runs on Google infra).
# Tags with an explicit timestamp so we can verify Cloud Run is
# actually serving the new image — no `:latest` ambiguity.
#
# Use this when local `./deploy.sh` produces images that Cloud Run
# claims to use but actually serves stale code (Docker-cache /
# proxy issues / push-failed-silently cases).
#
# Usage:
#   ./force_rebuild_via_cloudbuild.sh [--service=<name>]
#       (default: rebuild ALL 13 services)

set -euo pipefail

PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
REGION="${GCP_REGION:-asia-south1}"
TAG="$(date -u +%Y%m%d-%H%M%S)"     # deterministic, unique
SERVICE_FILTER=""

for arg in "$@"; do
    case "$arg" in
        --service=*) SERVICE_FILTER="${arg#*=}" ;;
        --tag=*)     TAG="${arg#*=}" ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NIDP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_ROOT="$(cd "$NIDP_ROOT/../.." && pwd)"
AR_REPO="${REGION}-docker.pkg.dev/${PROJECT}/nidp"

ALL_SERVICES=(
    bulk_deals block_deals bhavcopy delivery
    index_close index_constituents fii_dii corporate_actions
    nse_calendar rbi_yields snapshot_builder
    fred_macro yfinance_backfill
)

echo "[force-rebuild] config:"
echo "  project: $PROJECT"
echo "  region:  $REGION"
echo "  tag:     $TAG"
echo "  filter:  ${SERVICE_FILTER:-all}"
echo

# Step 1: prove the local checkout matches the remote
cd "$REPO_ROOT"
git fetch origin nidp
LOCAL_SHA=$(git rev-parse --short HEAD)
REMOTE_SHA=$(git rev-parse --short origin/nidp)
echo "[force-rebuild] local HEAD:   $LOCAL_SHA"
echo "[force-rebuild] origin/nidp:  $REMOTE_SHA"
if [[ "$LOCAL_SHA" != "$REMOTE_SHA" ]]; then
    echo "[force-rebuild] WARNING: local diverges from origin. Hard-resetting..."
    git reset --hard origin/nidp
fi

# Step 2: prove the patched code is in the local checkout
echo
echo "[force-rebuild] verifying writer patch is in local code..."
if grep -q "to_date(r\[\"holiday_date\"\])" backend/nidp/services/nse_calendar/writer.py; then
    echo "  ✓ to_date() patch present"
else
    echo "  ❌ patch MISSING — abort. Pull failed?"
    exit 1
fi

# Step 3: build via Cloud Build (no local Docker)
build_one() {
    local svc=$1
    local img="$AR_REPO/$svc:$TAG"
    local latest="$AR_REPO/$svc:latest"
    echo
    echo "[force-rebuild] ──── $svc → $TAG ────"

    # Inline cloudbuild.yaml fed via heredoc to avoid file pollution
    gcloud builds submit \
        --project="$PROJECT" \
        --region="$REGION" \
        --config=- \
        "$REPO_ROOT" << EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args:
      - build
      - --no-cache
      - --pull
      - -f
      - backend/nidp/services/$svc/Dockerfile
      - -t
      - $img
      - -t
      - $latest
      - .
images:
  - $img
  - $latest
options:
  logging: CLOUD_LOGGING_ONLY
  machineType: E2_HIGHCPU_8
timeout: 600s
EOF
}

# Step 4: build the requested services
SERVICES_TO_BUILD=()
if [[ -n "$SERVICE_FILTER" ]]; then
    SERVICES_TO_BUILD=("$SERVICE_FILTER")
else
    SERVICES_TO_BUILD=("${ALL_SERVICES[@]}")
fi

for svc in "${SERVICES_TO_BUILD[@]}"; do
    [[ -f "$REPO_ROOT/backend/nidp/services/$svc/Dockerfile" ]] || {
        echo "  ⚠ no Dockerfile for $svc, skipping"; continue; }
    build_one "$svc"
done

# Step 5: update Cloud Run Jobs to point at the EXPLICIT tag (not :latest)
echo
echo "[force-rebuild] updating Cloud Run Jobs to image tag $TAG..."
for svc in "${SERVICES_TO_BUILD[@]}"; do
    [[ -f "$REPO_ROOT/backend/nidp/services/$svc/Dockerfile" ]] || continue
    job_name="nidp-${svc//_/-}"
    img="$AR_REPO/$svc:$TAG"

    if gcloud run jobs describe "$job_name" --region="$REGION" --project="$PROJECT" &>/dev/null; then
        gcloud run jobs update "$job_name" \
            --image="$img" \
            --region="$REGION" --project="$PROJECT" --quiet \
            >/dev/null && echo "  ✓ $job_name → $TAG" \
                       || echo "  ❌ failed to update $job_name"
    else
        echo "  ⚠ $job_name does not exist — run ./deploy.sh first"
    fi
done

# Step 6: verify Cloud Run is on the new tag
echo
echo "[force-rebuild] verifying Cloud Run image tags..."
for svc in "${SERVICES_TO_BUILD[@]}"; do
    [[ -f "$REPO_ROOT/backend/nidp/services/$svc/Dockerfile" ]] || continue
    job_name="nidp-${svc//_/-}"
    actual=$(gcloud run jobs describe "$job_name" --region="$REGION" --project="$PROJECT" \
        --format='value(spec.template.spec.template.spec.containers[0].image)' 2>/dev/null || echo "MISSING")
    expected="$AR_REPO/$svc:$TAG"
    if [[ "$actual" == "$expected" ]]; then
        echo "  ✓ $job_name = $TAG"
    else
        echo "  ❌ $job_name has $actual (expected $TAG)"
    fi
done

# Step 7: trigger a smoke run on nse_calendar (the service that's been failing)
if [[ -z "$SERVICE_FILTER" ]] || [[ "$SERVICE_FILTER" == "nse_calendar" ]]; then
    echo
    echo "[force-rebuild] smoke-testing nidp-nse-calendar..."
    gcloud run jobs execute nidp-nse-calendar \
        --region="$REGION" --project="$PROJECT" --wait 2>&1 | tail -5
fi

cat <<EOF

══════════════════════════════════════════════════════════════
  ✅ force_rebuild_via_cloudbuild.sh complete.
     Tag: $TAG
     Verify with:
       gcloud run jobs describe nidp-nse-calendar \\
           --region=$REGION --project=$PROJECT \\
           --format='value(spec.template.spec.template.spec.containers[0].image)'
═══════════════════════════════════════════════════════════════
EOF
