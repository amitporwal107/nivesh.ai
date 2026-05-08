#!/usr/bin/env bash
# deploy_daas.sh — build the nidp-daas-api Docker image, push to
# Artifact Registry, and create/update the Cloud Run *Service*.
#
# The DaaS API is a long-running HTTP service (not a Cloud Run Job).
# It must be publicly reachable (--allow-unauthenticated) because
# authentication is handled in-app via per-caller API keys.  A VPC
# connector bridges it to the private GCE VM where Postgres lives.
#
# Default mode: --dry-run. Pass --confirm to actually build/push/deploy.
#
# Usage:
#   cd backend/nidp/deploy/gcp
#   ./deploy_daas.sh --project=<PROJECT_ID> [options] [--confirm]
#
# Options:
#   --project=<ID>          GCP project (or GCP_PROJECT env)
#   --region=asia-south1    Cloud Run region (default)
#   --tag=<sha>             Image tag (default: git short-SHA or timestamp)
#   --min-instances=1       Min live instances to keep warm (default 1)
#   --max-instances=20      Autoscaling ceiling (default 20)
#   --memory=512Mi          Per-instance memory (default 512Mi)
#   --cpu=1                 Per-instance vCPU (default 1)
#   --cors-origins=*        Comma-separated allowed CORS origins
#   --no-vpc                Skip VPC connector (if Postgres is reachable another way)
#   --confirm               Actually build / push / deploy

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NIDP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_ROOT="$(cd "$NIDP_ROOT/.." && pwd)"
REPO_ROOT="$(cd "$BACKEND_ROOT/.." && pwd)"
MANIFEST="$SCRIPT_DIR/gcp_resources.jsonl"
DOCKERFILE="$NIDP_ROOT/services/daas_api/Dockerfile"

# ── Defaults ────────────────────────────────────────────────────────
PROJECT="${GCP_PROJECT:-}"
REGION="${GCP_REGION:-asia-south1}"
TAG="${NIDP_IMAGE_TAG:-}"
MIN_INSTANCES=1
MAX_INSTANCES=20
MEMORY=512Mi
CPU=1
CORS_ORIGINS="${NIDP_DAAS_CORS_ORIGINS:-*}"
USE_VPC=true
DRY=true
SVC_NAME="nidp-daas-api"
SA_NAME="nidp-sa"

# ── Args ────────────────────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --project=*)      PROJECT="${arg#*=}" ;;
        --region=*)       REGION="${arg#*=}" ;;
        --tag=*)          TAG="${arg#*=}" ;;
        --min-instances=*)MIN_INSTANCES="${arg#*=}" ;;
        --max-instances=*)MAX_INSTANCES="${arg#*=}" ;;
        --memory=*)       MEMORY="${arg#*=}" ;;
        --cpu=*)          CPU="${arg#*=}" ;;
        --cors-origins=*) CORS_ORIGINS="${arg#*=}" ;;
        --no-vpc)         USE_VPC=false ;;
        --confirm)        DRY=false ;;
        --dry-run)        DRY=true ;;
        -h|--help)        sed -n '2,25p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

# ── Helpers ──────────────────────────────────────────────────────────
log()     { echo "[deploy-daas] $*"; }
maybe()   { if $DRY; then log "DRY-RUN  $*"; else log "RUN      $*"; eval "$@"; fi; }
die()     { echo "ERROR: $*" >&2; exit 1; }
manifest() {
    local row="{\"ts\":\"$(date -u +%FT%TZ)\",\"type\":\"$1\",\"name\":\"$2\",\"region\":\"$3\""
    [[ -n "${4:-}" ]] && row="$row,\"extra\":$4"
    row="$row}"
    echo "$row" >> "$MANIFEST"
}

# ── Sanity ──────────────────────────────────────────────────────────
command -v gcloud >/dev/null || die "gcloud CLI not found"
command -v docker  >/dev/null || die "docker not found"
[[ -n "$PROJECT" ]]  || die "--project is required (or GCP_PROJECT env)"
[[ -f "$DOCKERFILE" ]] || die "Dockerfile not found: $DOCKERFILE"

if [[ -z "$TAG" ]]; then
    if command -v git >/dev/null && git -C "$REPO_ROOT" rev-parse --short HEAD &>/dev/null; then
        TAG="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
    else
        TAG="$(date +%Y%m%d-%H%M%S)"
    fi
fi

SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
AR_HOST="${REGION}-docker.pkg.dev"
AR_REPO="$AR_HOST/$PROJECT/nidp"
IMG="$AR_REPO/daas_api:$TAG"
IMG_LATEST="$AR_REPO/daas_api:latest"

$DRY && log "🚧 dry-run mode — re-run with --confirm to apply"

cat <<EOF
[deploy-daas] config:
  project:       $PROJECT
  region:        $REGION
  service_name:  $SVC_NAME
  image_tag:     $TAG
  min_instances: $MIN_INSTANCES
  max_instances: $MAX_INSTANCES
  memory:        $MEMORY / cpu: $CPU
  cors_origins:  $CORS_ORIGINS
  vpc_connector: $USE_VPC
  repo_root:     $REPO_ROOT
EOF

# ── 1. Artifact Registry exists? ────────────────────────────────────
gcloud artifacts repositories describe nidp \
    --location="$REGION" --project="$PROJECT" &>/dev/null \
    || die "Artifact Registry 'nidp' not found in $REGION. Run bootstrap.sh --confirm first."
log "  ✓ Artifact Registry exists"

# ── 2. Authenticate Docker → AR ─────────────────────────────────────
maybe "gcloud auth configure-docker $AR_HOST --quiet"

# ── 3. Build image ──────────────────────────────────────────────────
log "──── building daas_api ────"
# Build context is REPO_ROOT — Dockerfile does:  COPY backend/nidp /app/nidp
maybe "docker build \
    -f '$DOCKERFILE' \
    -t '$IMG' \
    -t '$IMG_LATEST' \
    '$REPO_ROOT'"

# ── 4. Push ─────────────────────────────────────────────────────────
maybe "docker push '$IMG'"
maybe "docker push '$IMG_LATEST'"
$DRY || manifest "container_image" "$IMG" "$REGION"

# ── 5. Secret must exist before deployment ──────────────────────────
# NIDP_POSTGRES_URL is the only secret the DaaS API *requires*.
# NIDP_DAAS_INTERNAL_TOKEN is optional (skip if absent).
_req_secret="NIDP_POSTGRES_URL"
gcloud secrets describe "$_req_secret" --project="$PROJECT" &>/dev/null \
    || die "Secret '$_req_secret' not in Secret Manager. Run setup_daas.sh first."
log "  ✓ required secret exists: $_req_secret"

# ── 6. VPC connector ────────────────────────────────────────────────
VPC_FLAGS=""
if $USE_VPC; then
    VPC_CONN="nidp-vpc"
    VPC_CONN_FULL="projects/$PROJECT/locations/$REGION/connectors/$VPC_CONN"
    if ! gcloud compute networks vpc-access connectors describe "$VPC_CONN" \
            --region="$REGION" --project="$PROJECT" &>/dev/null; then
        log "  ⚠ VPC connector '$VPC_CONN' not found — run setup_daas.sh --confirm to create it"
        log "    (continuing without connector; Service will not be able to reach the VM)"
        VPC_FLAGS=""
    else
        log "  ✓ VPC connector exists: $VPC_CONN"
        VPC_FLAGS="--vpc-connector=$VPC_CONN_FULL --vpc-egress=private-ranges-only"
    fi
fi

# ── 7. Secrets to mount ─────────────────────────────────────────────
_SECRETS="NIDP_POSTGRES_URL=NIDP_POSTGRES_URL:latest"
if gcloud secrets describe NIDP_DAAS_INTERNAL_TOKEN --project="$PROJECT" &>/dev/null; then
    _SECRETS="$_SECRETS,NIDP_DAAS_INTERNAL_TOKEN=NIDP_DAAS_INTERNAL_TOKEN:latest"
    log "  ✓ mounting optional secret: NIDP_DAAS_INTERNAL_TOKEN"
fi

# ── 8. Env vars ─────────────────────────────────────────────────────
_ENV_VARS="NIDP_STORAGE_BACKEND=gcs"
_ENV_VARS="$_ENV_VARS,GCP_PROJECT=$PROJECT"
_ENV_VARS="$_ENV_VARS,GCP_REGION=$REGION"
_ENV_VARS="$_ENV_VARS,NIDP_DAAS_LOG_REQUESTS=1"
_ENV_VARS="$_ENV_VARS,NIDP_DAAS_CORS_ORIGINS=$CORS_ORIGINS"
_ENV_VARS="$_ENV_VARS,LOG_LEVEL=info"

# ── 9. Run DB migrations via a one-off Cloud Run Job ────────────────
# Runs `python -m nidp.cli migrate` inside the just-pushed image.
# The job uses the same VPC connector + secrets as the Service so it
# can reach the private GCE VM's Postgres without any SSH/IAP setup.
# Idempotent — safe to re-run on every deploy.
MIGRATE_JOB="nidp-daas-migrate"
_MIGRATE_FLAGS="
    --image='$IMG'
    --region='$REGION' --project='$PROJECT'
    --service-account='$SA_EMAIL'
    --set-secrets='$_SECRETS'
    --set-env-vars='$_ENV_VARS'
    $VPC_FLAGS
    --args='python,-m,nidp.cli,migrate'
    --max-retries=1
    --quiet"

log "──── applying DB migrations ────"
if gcloud run jobs describe "$MIGRATE_JOB" \
        --region="$REGION" --project="$PROJECT" &>/dev/null; then
    maybe "gcloud run jobs update '$MIGRATE_JOB' $_MIGRATE_FLAGS"
else
    maybe "gcloud run jobs create '$MIGRATE_JOB' $_MIGRATE_FLAGS"
fi
maybe "gcloud run jobs execute '$MIGRATE_JOB' \
    --region='$REGION' --project='$PROJECT' --wait"
log "  ✓ migrations applied"

# ── 10. Deploy Cloud Run Service ──────────────────────────────────────
_COMMON_FLAGS="
    --image='$IMG'
    --region='$REGION' --project='$PROJECT'
    --service-account='$SA_EMAIL'
    --port=8081
    --cpu=$CPU --memory=$MEMORY
    --min-instances=$MIN_INSTANCES
    --max-instances=$MAX_INSTANCES
    --concurrency=80
    --timeout=30s
    --set-env-vars='$_ENV_VARS'
    --set-secrets='$_SECRETS'
    $VPC_FLAGS
    --allow-unauthenticated
    --quiet"

if gcloud run services describe "$SVC_NAME" \
        --region="$REGION" --project="$PROJECT" &>/dev/null; then
    log "──── updating existing Cloud Run Service: $SVC_NAME ────"
    maybe "gcloud run services update '$SVC_NAME' $_COMMON_FLAGS"
    log "  ✓ updated"
else
    log "──── creating new Cloud Run Service: $SVC_NAME ────"
    maybe "gcloud run services create '$SVC_NAME' $_COMMON_FLAGS"
    $DRY || manifest "cloud_run_service" "$SVC_NAME" "$REGION" \
        "{\"image\":\"$IMG\",\"public\":true}"
    log "  ✓ created"
fi

# ── 11. Print service URL ────────────────────────────────────────────
if ! $DRY; then
    SVC_URL=$(gcloud run services describe "$SVC_NAME" \
        --region="$REGION" --project="$PROJECT" \
        --format="value(status.url)" 2>/dev/null || echo "(run gcloud run services describe to get URL)")
    cat <<EOF

[deploy-daas] ✅ done.

Service URL: $SVC_URL

Smoke-test:
    curl $SVC_URL/health

Issue a key (run against the production DB):
    python -m nidp.cli daas-keygen \\
        --name "first-user" --owner ops@yourco.com --plan free

Test the key:
    curl -H "X-API-Key: nvd_..." $SVC_URL/v1/catalog

Interactive API docs:
    $SVC_URL/docs

EOF
else
    cat <<EOF

[deploy-daas] (dry-run complete)
Re-run with --confirm to actually build / push / deploy.

EOF
fi

$DRY && log "(dry-run only)"
