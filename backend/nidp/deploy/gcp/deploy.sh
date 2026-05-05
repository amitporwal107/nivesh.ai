#!/usr/bin/env bash
# deploy.sh — build NIDP service images locally, push to Artifact
# Registry, and create/update Cloud Run Jobs for each.
#
# Idempotent: re-running rebuilds (with cache), pushes a new tag, and
# updates each Cloud Run Job to point at the new tag.
#
# Default mode: --dry-run. Pass --confirm to actually build/push/deploy.
#
# Pre-requisites (verified at start):
#   1. gcloud CLI installed + authenticated
#   2. Docker daemon running
#   3. setup_credentials.sh has been run (SA exists)
#   4. bootstrap.sh has been run --confirm (Artifact Registry repo
#      exists, GCE VM is up, secrets are populated)
#
# Usage:
#   ./deploy.sh --project=<PROJECT_ID> [--region=asia-south1] \
#               [--tag=$(git rev-parse --short HEAD)] \
#               [--services=bulk_deals,bhavcopy,...] \
#               [--confirm]
#
# Env overrides:
#   GCP_PROJECT, GCP_REGION, NIDP_IMAGE_TAG, NIDP_SERVICES

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────
PROJECT="${GCP_PROJECT:-}"
REGION="${GCP_REGION:-asia-south1}"
TAG="${NIDP_IMAGE_TAG:-}"
SERVICES_ARG="${NIDP_SERVICES:-}"
DRY=true

# Repo root = .../backend/nidp/deploy/gcp/.. (3 levels up)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NIDP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_ROOT="$(cd "$NIDP_ROOT/.." && pwd)"
REPO_ROOT="$(cd "$BACKEND_ROOT/.." && pwd)"
MANIFEST="$SCRIPT_DIR/gcp_resources.jsonl"

# All services that have a Dockerfile.
ALL_SERVICES=(
    bulk_deals block_deals bhavcopy delivery
    index_close index_constituents fii_dii corporate_actions
    nse_calendar rbi_yields snapshot_builder
)

# ── Args ────────────────────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --project=*)  PROJECT="${arg#*=}" ;;
        --region=*)   REGION="${arg#*=}" ;;
        --tag=*)      TAG="${arg#*=}" ;;
        --services=*) SERVICES_ARG="${arg#*=}" ;;
        --confirm)    DRY=false ;;
        --dry-run)    DRY=true ;;
        -h|--help)
            sed -n '2,22p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

# ── Sanity ──────────────────────────────────────────────────────────
log() { echo "[deploy] $*"; }
maybe() {
    if $DRY; then log "DRY-RUN  $*"; else log "RUN      $*"; eval "$@"; fi
}
manifest() {
    local row="{\"ts\":\"$(date -u +%FT%TZ)\",\"type\":\"$1\",\"name\":\"$2\",\"region\":\"$3\""
    [[ -n "${4:-}" ]] && row="$row,\"extra\":$4"
    row="$row}"
    echo "$row" >> "$MANIFEST"
}

if ! command -v gcloud >/dev/null; then
    echo "ERROR: gcloud CLI not found." >&2; exit 1
fi
if ! command -v docker >/dev/null; then
    echo "ERROR: docker not found." >&2; exit 1
fi
if [[ -z "$PROJECT" ]]; then
    echo "ERROR: --project is required (or GCP_PROJECT env)" >&2; exit 2
fi
if [[ -z "$TAG" ]]; then
    if command -v git >/dev/null && git -C "$REPO_ROOT" rev-parse --short HEAD &>/dev/null; then
        TAG="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
    else
        TAG="$(date +%Y%m%d-%H%M%S)"
    fi
fi

# Resolve service list
IFS=',' read -r -a SVC_LIST <<< "${SERVICES_ARG:-$(IFS=,; echo "${ALL_SERVICES[*]}")}"

if $DRY; then
    log "🚧 dry-run. Re-run with --confirm to actually build / push / deploy."
fi

cat <<EOF
[deploy] config:
  project:    $PROJECT
  region:     $REGION
  tag:        $TAG
  services:   ${SVC_LIST[*]}
  repo root:  $REPO_ROOT
EOF

AR_HOST="${REGION}-docker.pkg.dev"
AR_REPO="$AR_HOST/$PROJECT/nidp"

# ── 1. Verify Artifact Registry exists ──────────────────────────────
if ! gcloud artifacts repositories describe nidp \
        --location="$REGION" --project="$PROJECT" &>/dev/null; then
    echo "ERROR: Artifact Registry repo 'nidp' not found in $REGION." >&2
    echo "  Run bootstrap.sh --confirm first." >&2
    exit 1
fi
log "  ✓ artifact registry exists: $AR_REPO"

# ── 2. Authenticate Docker to Artifact Registry ─────────────────────
maybe "gcloud auth configure-docker $AR_HOST --quiet"

SA_EMAIL="nidp-sa@${PROJECT}.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT" &>/dev/null; then
    echo "ERROR: SA $SA_EMAIL missing. Run setup_credentials.sh first." >&2
    exit 1
fi

# ── 3. Build + push each service ────────────────────────────────────
for svc in "${SVC_LIST[@]}"; do
    DOCKERFILE="$NIDP_ROOT/services/$svc/Dockerfile"
    if [[ ! -f "$DOCKERFILE" ]]; then
        log "  ⚠ no Dockerfile for $svc — skipping"
        continue
    fi
    IMG="$AR_REPO/$svc:$TAG"
    LATEST="$AR_REPO/$svc:latest"

    log "──── building $svc ────"
    # Build context = REPO_ROOT (Dockerfile copies backend/nidp/ in)
    maybe "docker build -f '$DOCKERFILE' -t '$IMG' -t '$LATEST' '$REPO_ROOT'"
    maybe "docker push '$IMG'"
    maybe "docker push '$LATEST'"
    if ! $DRY; then
        manifest "container_image" "$IMG" "$REGION"
    fi
done

# ── 4. Deploy / update Cloud Run Jobs ───────────────────────────────
# Per-service env wiring. Cloud Run Job reads runtime config from
# Secret Manager; image name is the only thing that changes per deploy.
declare -A JOB_ENVS=(
    # NIDP_STORAGE_BACKEND=gcs uses google-cloud-storage with the SA's
    # Application Default Credentials (no AWS keys needed). The bucket
    # is GCS, so s3 backend would fail with NoCredentialsError.
    [common]="NIDP_STORAGE_BACKEND=gcs,NIDP_S3_BUCKET=nidp-raw-${PROJECT},NIDP_EVENT_BUS=kafka,GCP_PROJECT=${PROJECT},GCP_REGION=${REGION}"
)
declare -A JOB_SECRETS=(
    [common]="NIDP_POSTGRES_URL=NIDP_POSTGRES_URL:latest,NIDP_KAFKA_BROKERS=NIDP_KAFKA_BROKERS:latest,NIDP_SCHEMA_REGISTRY_URL=NIDP_SCHEMA_REGISTRY_URL:latest,NIDP_REDIS_URL=NIDP_REDIS_URL:latest"
)

for svc in "${SVC_LIST[@]}"; do
    DOCKERFILE="$NIDP_ROOT/services/$svc/Dockerfile"
    [[ -f "$DOCKERFILE" ]] || continue

    IMG="$AR_REPO/$svc:$TAG"
    JOB_NAME="nidp-${svc//_/-}"

    # VPC connector required so Cloud Run jobs can reach the VM's
    # internal IP (where Postgres + Kafka live). private-ranges-only
    # routes only RFC1918 traffic via the connector; public egress
    # (NSE, RBI archives) goes via Cloud NAT — faster + cheaper.
    VPC_CONN="projects/$PROJECT/locations/$REGION/connectors/nidp-vpc"
    VPC_FLAGS="--vpc-connector=$VPC_CONN --vpc-egress=private-ranges-only"

    if gcloud run jobs describe "$JOB_NAME" --region="$REGION" --project="$PROJECT" &>/dev/null; then
        # Update existing job
        maybe "gcloud run jobs update '$JOB_NAME' \
            --image='$IMG' \
            --region='$REGION' --project='$PROJECT' \
            --service-account='$SA_EMAIL' \
            $VPC_FLAGS \
            --set-env-vars='${JOB_ENVS[common]}' \
            --set-secrets='${JOB_SECRETS[common]}' \
            --task-timeout=900s --max-retries=2 --memory=512Mi --cpu=1 \
            --quiet"
        log "  ✓ updated Cloud Run Job: $JOB_NAME"
    else
        maybe "gcloud run jobs create '$JOB_NAME' \
            --image='$IMG' \
            --region='$REGION' --project='$PROJECT' \
            --service-account='$SA_EMAIL' \
            $VPC_FLAGS \
            --set-env-vars='${JOB_ENVS[common]}' \
            --set-secrets='${JOB_SECRETS[common]}' \
            --task-timeout=900s --max-retries=2 --memory=512Mi --cpu=1 \
            --quiet"
        if ! $DRY; then
            manifest "cloud_run_job" "$JOB_NAME" "$REGION"
        fi
        log "  ✓ created Cloud Run Job: $JOB_NAME"
    fi
done

# ── 5. Print smoke command ──────────────────────────────────────────
SMOKE_JOB="${SMOKE_JOB:-nidp-nse-calendar}"
cat <<EOF

[deploy] ✅ done.

Smoke-test one job (executes immediately, no schedule):

    gcloud run jobs execute $SMOKE_JOB --region=$REGION --project=$PROJECT --wait

Tail logs:

    gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=$SMOKE_JOB' \\
      --limit=50 --format='value(textPayload)' --project=$PROJECT

To redeploy after a code change, just re-run this script — image tag
defaults to the current git short SHA.

EOF

$DRY && log "(dry-run only — re-run with --confirm to apply)"
