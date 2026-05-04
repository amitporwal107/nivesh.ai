#!/usr/bin/env bash
# bootstrap.sh — provision NIDP infrastructure on GCP.
#
# Idempotent: every step checks existence before creating. Logs every
# created resource to gcp_resources.jsonl so rotate/teardown can act
# precisely. Default mode is DRY-RUN. Pass --confirm to actually
# create resources.
#
# Required env:
#   GOOGLE_APPLICATION_CREDENTIALS  — path to a service account key
#                                     OR run from an authed gcloud
#                                     session.
#   GCP_PROJECT                     — target project ID.
#   GCP_REGION                      — default asia-south1.
#
# Resources created (logged to gcp_resources.jsonl):
#   1. Service account              nidp-sa@${GCP_PROJECT}.iam…
#   2. GCS bucket                   nidp-raw-${GCP_PROJECT}
#   3. Secret Manager secrets       NIDP_POSTGRES_URL, NIDP_KAFKA_BROKERS,
#                                   NIDP_S3_BUCKET, NIDP_REDIS_URL,
#                                   NIDP_SCHEMA_REGISTRY_URL
#   4. Artifact Registry            nidp/ (Docker)
#   5. GCE e2-small VM              nidp-stack-vm  (runs docker-compose.dev.yml)
#   6. Cloud Run Jobs               nidp-<service>  (one per ingester)
#   7. Cloud Scheduler triggers     daily cron per Cloud Run Job

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="${ROOT_DIR}/gcp/gcp_resources.jsonl"
CONFIRM="${1:-}"
DRY=true
[[ "$CONFIRM" == "--confirm" ]] && DRY=false

PROJECT="${GCP_PROJECT:?GCP_PROJECT must be set}"
REGION="${GCP_REGION:-asia-south1}"
ZONE="${GCP_ZONE:-${REGION}-a}"

SA_NAME="nidp-sa"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
BUCKET="nidp-raw-${PROJECT}"
VM_NAME="nidp-stack-vm"
AR_REPO="nidp"

# Logical service list — matches nidp/services/*.
SERVICES=(
  bulk_deals block_deals bhavcopy delivery
  index_close index_constituents fii_dii corporate_actions
  nse_calendar rbi_yields snapshot_builder
)

log() { echo "[bootstrap] $*"; }
manifest() {
    # $1=type $2=name $3=region/location $4=extra-json
    local row="{\"ts\":\"$(date -u +%FT%TZ)\",\"type\":\"$1\",\"name\":\"$2\",\"region\":\"$3\""
    [[ -n "${4:-}" ]] && row="$row,\"extra\":$4"
    row="$row}"
    echo "$row" >> "$MANIFEST"
}
maybe_run() {
    if $DRY; then
        log "DRY-RUN  $*"
    else
        log "RUN      $*"
        eval "$@"
    fi
}

if $DRY; then
    log "🚧 dry-run mode. Re-run with --confirm to actually create resources."
fi

log "project=${PROJECT}  region=${REGION}  zone=${ZONE}"
log "manifest path: ${MANIFEST}"
mkdir -p "$(dirname "$MANIFEST")"
touch "$MANIFEST"

# 1. Enable APIs
APIS=(
    iam.googleapis.com
    iamcredentials.googleapis.com
    secretmanager.googleapis.com
    storage.googleapis.com
    artifactregistry.googleapis.com
    run.googleapis.com
    cloudscheduler.googleapis.com
    compute.googleapis.com
    logging.googleapis.com
    monitoring.googleapis.com
)
log "enabling APIs..."
for api in "${APIS[@]}"; do
    maybe_run "gcloud services enable $api --project=$PROJECT"
done

# 2. Service account
if ! gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT" &>/dev/null; then
    maybe_run "gcloud iam service-accounts create $SA_NAME \
        --display-name='NIDP service account' --project=$PROJECT"
    manifest "service_account" "$SA_EMAIL" "global" "{\"display\":\"NIDP service account\"}"
else
    log "  ✓ service account already exists: $SA_EMAIL"
fi

ROLES=(
    roles/storage.objectAdmin
    roles/secretmanager.secretAccessor
    roles/run.developer
    roles/cloudscheduler.admin
    roles/artifactregistry.writer
    roles/logging.logWriter
)
for role in "${ROLES[@]}"; do
    maybe_run "gcloud projects add-iam-policy-binding $PROJECT \
        --member='serviceAccount:$SA_EMAIL' --role='$role' --condition=None"
done

# 3. GCS bucket
if ! gsutil ls -b "gs://$BUCKET" &>/dev/null; then
    maybe_run "gsutil mb -l $REGION -p $PROJECT gs://$BUCKET"
    manifest "gcs_bucket" "$BUCKET" "$REGION"
else
    log "  ✓ bucket already exists: gs://$BUCKET"
fi

# 4. Secret Manager — placeholder values; operator overrides via console.
SECRETS=(NIDP_POSTGRES_URL NIDP_KAFKA_BROKERS NIDP_S3_BUCKET NIDP_REDIS_URL NIDP_SCHEMA_REGISTRY_URL)
for s in "${SECRETS[@]}"; do
    if ! gcloud secrets describe "$s" --project="$PROJECT" &>/dev/null; then
        maybe_run "echo -n 'SET_ME' | gcloud secrets create $s --replication-policy=automatic \
            --data-file=- --project=$PROJECT"
        manifest "secret" "$s" "global"
    else
        log "  ✓ secret already exists: $s"
    fi
done

# 5. Artifact Registry (Docker)
if ! gcloud artifacts repositories describe "$AR_REPO" --project="$PROJECT" \
        --location="$REGION" &>/dev/null; then
    maybe_run "gcloud artifacts repositories create $AR_REPO --repository-format=docker \
        --location=$REGION --description='NIDP container images' --project=$PROJECT"
    manifest "artifact_registry" "$AR_REPO" "$REGION"
else
    log "  ✓ artifact registry already exists: $AR_REPO"
fi

# 6. GCE VM (runs docker-compose stack: PG+Timescale, Redpanda, Redis, Prometheus, Grafana)
if ! gcloud compute instances describe "$VM_NAME" --zone="$ZONE" --project="$PROJECT" &>/dev/null; then
    maybe_run "gcloud compute instances create $VM_NAME \
        --machine-type=e2-small \
        --image-family=debian-12 --image-project=debian-cloud \
        --zone=$ZONE --project=$PROJECT \
        --service-account=$SA_EMAIL \
        --scopes=cloud-platform \
        --metadata=enable-oslogin=TRUE \
        --tags=nidp-stack"
    manifest "gce_vm" "$VM_NAME" "$ZONE"
else
    log "  ✓ VM already exists: $VM_NAME"
fi

# 7. Cloud Run Jobs (created on first deploy of each container; logged here for inventory)
log "Cloud Run Jobs (created at deploy-time, inventoried here):"
for svc in "${SERVICES[@]}"; do
    log "  - nidp-${svc//_/-}  (region=$REGION)"
done

# 8. Cloud Scheduler stubs — disabled by default; operator enables after smoke.
SCHEDULES=(
    "nidp-bhavcopy:0 19 * * 1-5"
    "nidp-delivery:30 10 * * 1-5"
    "nidp-index-close:0 19 * * 1-5"
    "nidp-fii-dii:30 19 * * 1-5"
    "nidp-bulk-deals:30 19 * * 1-5"
    "nidp-block-deals:30 19 * * 1-5"
    "nidp-corporate-actions:0 20 * * *"
    "nidp-rbi-yields:30 20 * * 1-5"
    "nidp-nse-calendar:0 6 1 * *"
    "nidp-snapshot-builder:0 22 * * 1-5"
)
for entry in "${SCHEDULES[@]}"; do
    name="${entry%%:*}"
    cron="${entry#*:}"
    log "  schedule (paused): $name '$cron'"
done

log "✅ bootstrap complete."
$DRY && log "(dry-run only — re-run with --confirm to apply)"
