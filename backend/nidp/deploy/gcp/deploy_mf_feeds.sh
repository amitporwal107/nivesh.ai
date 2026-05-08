#!/usr/bin/env bash
# deploy_mf_feeds.sh — one-shot GCP deployment for the 5 MF data-feed services:
#   amfi_nav, amfi_nav_history, amfi_circulars, mf_disclosure_snapshot, mf_holdings
#
# What this script does (in order):
#   1. Run DB migrations via Cloud Build (applies any pending .sql files)
#   2. Build + push each service image via Cloud Build (cloudbuild-service.yaml)
#   3. Create Cloud Run Jobs for services that don't exist yet
#   4. Create missing Cloud Scheduler triggers (4 schedules; amfi_nav_history skipped)
#   5. Create missing GitHub push triggers via setup_github_triggers.sh
#   6. Smoke-test: execute nidp-amfi-nav and tail logs
#
# Default: --dry-run (prints every gcloud command without running it).
# Pass --confirm to actually deploy.
#
# Usage (run from repo root):
#   bash backend/nidp/deploy/gcp/deploy_mf_feeds.sh \
#       --project=niveshdataintelligence [--region=asia-south1] [--confirm]
#
# Pre-reqs:
#   - gcloud CLI authenticated (gcloud auth login / application-default login)
#   - Artifact Registry repo 'nidp' exists (bootstrap.sh --confirm was run)
#   - VPC connector 'nidp-vpc' exists in the region
#   - Service account nidp-sa exists + has required roles
#   - GitHub connection + Cloud Build triggers wired once via Console
#   - setup_github_triggers.sh and setup_schedules.sh are in the same directory

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
PROJECT="${GCP_PROJECT:-}"
REGION="${GCP_REGION:-asia-south1}"
DRY=true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"

SERVICES=(amfi_nav amfi_nav_history amfi_circulars mf_disclosure_snapshot mf_holdings)

# ── Args ──────────────────────────────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --project=*)  PROJECT="${arg#*=}" ;;
        --region=*)   REGION="${arg#*=}" ;;
        --confirm)    DRY=false ;;
        --dry-run)    DRY=true ;;
        -h|--help)    sed -n '2,24p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────
CYAN="\033[1;36m"; GREEN="\033[1;32m"; YEL="\033[1;33m"; RED="\033[1;31m"; RESET="\033[0m"
log()  { echo -e "${CYAN}[mf-deploy]${RESET} $*"; }
ok()   { echo -e "${GREEN}[mf-deploy] ✅${RESET} $*"; }
warn() { echo -e "${YEL}[mf-deploy] ⚠${RESET}  $*"; }
err()  { echo -e "${RED}[mf-deploy] ❌${RESET} $*"; }

run() {
    if $DRY; then
        echo -e "${YEL}DRY-RUN${RESET}  $*"
    else
        log "RUN  $*"
        eval "$@"
    fi
}

# ── Validate inputs ───────────────────────────────────────────────────────────
if [[ -z "$PROJECT" ]]; then
    err "--project is required (or set GCP_PROJECT env var)"
    exit 2
fi

if $DRY; then
    warn "dry-run mode — pass --confirm to actually deploy"
fi

AR_HOST="${REGION}-docker.pkg.dev"
AR_REPO="${AR_HOST}/${PROJECT}/nidp"
SA_EMAIL="nidp-sa@${PROJECT}.iam.gserviceaccount.com"
VPC_CONN="projects/${PROJECT}/locations/${REGION}/connectors/nidp-vpc"

COMMON_ENV="NIDP_STORAGE_BACKEND=gcs,NIDP_S3_BUCKET=nidp-raw-${PROJECT},NIDP_EVENT_BUS=kafka,GCP_PROJECT=${PROJECT},GCP_REGION=${REGION}"
COMMON_SECRETS="NIDP_POSTGRES_URL=NIDP_POSTGRES_URL:latest,NIDP_KAFKA_BROKERS=NIDP_KAFKA_BROKERS:latest,NIDP_SCHEMA_REGISTRY_URL=NIDP_SCHEMA_REGISTRY_URL:latest,NIDP_REDIS_URL=NIDP_REDIS_URL:latest"

cat <<EOF
[mf-deploy] ─────────────────────────────────────────────────────
  project:   ${PROJECT}
  region:    ${REGION}
  ar repo:   ${AR_REPO}
  sa:        ${SA_EMAIL}
  services:  ${SERVICES[*]}
  dry-run:   ${DRY}
[mf-deploy] ─────────────────────────────────────────────────────
EOF

# ── 1. Migrations ─────────────────────────────────────────────────────────────
# Cloud Build only builds + pushes the migrations image.
# This script then creates/executes the Cloud Run Job directly using the
# caller's gcloud credentials, which have full project permissions.
# (Cloud Build's default SA lacks roles/run.developer, so Cloud Run operations
# must happen outside Cloud Build.)
echo
log "Step 1/6 — build migration image via Cloud Build"

run "gcloud builds submit '${REPO_ROOT}' \
    --config='${SCRIPT_DIR}/cloudbuild-migrations.yaml' \
    --project='${PROJECT}' \
    --region='${REGION}'"

log "Step 1/6 — create / execute nidp-migrations Cloud Run Job"

MIGRATIONS_IMG="${AR_REPO}/migrations:latest"

if ! $DRY && gcloud run jobs describe nidp-migrations \
        --region="${REGION}" --project="${PROJECT}" &>/dev/null; then
    run "gcloud run jobs update nidp-migrations \
        --image='${MIGRATIONS_IMG}' \
        --region='${REGION}' --project='${PROJECT}' --quiet"
else
    run "gcloud run jobs create nidp-migrations \
        --image='${MIGRATIONS_IMG}' \
        --region='${REGION}' --project='${PROJECT}' \
        --service-account='${SA_EMAIL}' \
        --vpc-connector='${VPC_CONN}' \
        --vpc-egress=private-ranges-only \
        --set-secrets='NIDP_POSTGRES_URL=NIDP_POSTGRES_URL:latest' \
        --task-timeout=300s --max-retries=0 \
        --memory=512Mi --cpu=1 \
        --quiet"
fi

run "gcloud run jobs execute nidp-migrations \
    --region='${REGION}' --project='${PROJECT}' --wait"

ok "migrations applied"

# ── 2. Build + push service images ───────────────────────────────────────────
echo
log "Step 2/6 — build + push images via Cloud Build (one job per service)"

for svc in "${SERVICES[@]}"; do
    svc_dashed="${svc//_/-}"
    log "  submitting build for ${svc}…"
    run "gcloud builds submit '${REPO_ROOT}' \
        --config='${SCRIPT_DIR}/cloudbuild-service.yaml' \
        --project='${PROJECT}' \
        --region='${REGION}' \
        --substitutions='_SERVICE=${svc},_SERVICE_DASHED=${svc_dashed},_REGION=${REGION}'"
done

ok "all image builds submitted"

# ── 3. Create Cloud Run Jobs (first time only) ────────────────────────────────
echo
log "Step 3/6 — create Cloud Run Jobs (skips if already exists)"

for svc in "${SERVICES[@]}"; do
    svc_dashed="${svc//_/-}"
    job_name="nidp-${svc_dashed}"
    img="${AR_REPO}/${svc}:latest"

    if ! $DRY && gcloud run jobs describe "${job_name}" \
            --region="${REGION}" --project="${PROJECT}" &>/dev/null; then
        ok "  ${job_name} already exists — skipping create"
        continue
    fi
    $DRY && log "  (would check if ${job_name} exists, create if not)"

    run "gcloud run jobs create '${job_name}' \
        --image='${img}' \
        --region='${REGION}' \
        --project='${PROJECT}' \
        --service-account='${SA_EMAIL}' \
        --vpc-connector='${VPC_CONN}' \
        --vpc-egress=private-ranges-only \
        --set-env-vars='${COMMON_ENV}' \
        --set-secrets='${COMMON_SECRETS}' \
        --task-timeout=900s \
        --max-retries=2 \
        --memory=512Mi \
        --cpu=1 \
        --quiet"
    ok "  created ${job_name}"
done

# ── 4. Cloud Scheduler triggers ───────────────────────────────────────────────
echo
log "Step 4/6 — create Cloud Scheduler triggers"

RUN_API="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs"

add_schedule() {
    local job=$1 cron=$2 desc=$3
    local trigger="nidp-cron-${job}"

    if ! $DRY && gcloud scheduler jobs describe "${trigger}" \
            --location="${REGION}" --project="${PROJECT}" &>/dev/null; then
        ok "  ${trigger} already exists — skipping"
        return
    fi
    $DRY && log "  (would check if ${trigger} exists, create if not)"

    run "gcloud scheduler jobs create http '${trigger}' \
        --schedule='${cron}' \
        --time-zone='Asia/Kolkata' \
        --uri='${RUN_API}/${job}:run' \
        --http-method=POST \
        --oauth-service-account-email='${SA_EMAIL}' \
        --location='${REGION}' \
        --project='${PROJECT}' \
        --quiet"
    ok "  ${trigger} created  (${cron} IST — ${desc})"
}

# amfi_nav: AMFI publishes NAVAll.txt ~18:30 IST; run at 20:00 with buffer
add_schedule nidp-amfi-nav               '0 20 * * 1-5'   'AMFI NAVAll daily'
# amfi_circulars: captures scheme lifecycle notices (mergers, renames)
add_schedule nidp-amfi-circulars         '0 9 * * *'      'AMFI scheme circulars'
# mf_disclosure_snapshot: SEBI mandates TER + risk-o-meter by 10th; run 12th
add_schedule nidp-mf-disclosure-snapshot '0 10 12 * *'    'MF TER + risk-o-meter (12th)'
# mf_holdings: SEBI mandates portfolio by 10th; run 12th (1h after snapshot)
add_schedule nidp-mf-holdings            '0 11 12 * *'    'MF monthly portfolio (12th)'
# amfi_nav_history is a one-time backfill — NOT scheduled (run manually)

ok "schedules done  (amfi_nav_history intentionally skipped — manual backfill only)"

# ── 5. GitHub push triggers ───────────────────────────────────────────────────
echo
log "Step 5/6 — create GitHub push triggers via setup_github_triggers.sh"

for svc in "${SERVICES[@]}"; do
    run "bash '${SCRIPT_DIR}/setup_github_triggers.sh' \
        --project='${PROJECT}' \
        --region='${REGION}' \
        --service='${svc}'"
done

ok "GitHub push triggers created"

# ── 6. Smoke test ─────────────────────────────────────────────────────────────
echo
log "Step 6/6 — smoke test: execute nidp-amfi-nav and tail logs"

run "gcloud run jobs execute nidp-amfi-nav \
    --region='${REGION}' \
    --project='${PROJECT}' \
    --wait"

if ! $DRY; then
    log "Tailing last 50 log lines for nidp-amfi-nav…"
    gcloud logging read \
        "resource.type=cloud_run_job AND resource.labels.job_name=nidp-amfi-nav" \
        --limit=50 \
        --format='value(textPayload)' \
        --project="${PROJECT}" || true
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo
if $DRY; then
    warn "dry-run complete — re-run with --confirm to apply all changes"
else
    ok "All 5 MF services deployed, scheduled, and triggered."
    cat <<EOF

  Jobs created / updated:
    nidp-amfi-nav, nidp-amfi-nav-history, nidp-amfi-circulars,
    nidp-mf-disclosure-snapshot, nidp-mf-holdings

  Schedules created (Asia/Kolkata):
    nidp-cron-nidp-amfi-nav               : Mon-Fri 20:00
    nidp-cron-nidp-amfi-circulars         : daily 09:00
    nidp-cron-nidp-mf-disclosure-snapshot : 12th of month 10:00
    nidp-cron-nidp-mf-holdings            : 12th of month 11:00

  Manual backfill (run once after first deploy):
    gcloud run jobs execute nidp-amfi-nav-history \\
      --region=${REGION} --project=${PROJECT} --wait

  Tail logs for any job:
    gcloud logging read \\
      'resource.type=cloud_run_job AND resource.labels.job_name=nidp-amfi-nav' \\
      --limit=50 --format='value(textPayload)' --project=${PROJECT}
EOF
fi
