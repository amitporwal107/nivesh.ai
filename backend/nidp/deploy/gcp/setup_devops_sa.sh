#!/usr/bin/env bash
# setup_devops_sa.sh — create the nivesh-devops service account with all
# permissions needed for CI/CD: Cloud Build, Artifact Registry, Cloud Run,
# Secret Manager, and GCS source uploads.
#
# Run once from any machine authenticated as a project Owner/Editor:
#
#   gcloud auth login
#   ./setup_devops_sa.sh --project=niveshdataintelligence [--confirm]
#
# Default: --dry-run. Pass --confirm to actually apply.
set -euo pipefail

PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
REGION="${GCP_REGION:-asia-south1}"
DRY=true
KEY_FILE=""

for arg in "$@"; do
    case "$arg" in
        --project=*) PROJECT="${arg#*=}" ;;
        --region=*)  REGION="${arg#*=}" ;;
        --key-file=*) KEY_FILE="${arg#*=}" ;;
        --confirm)   DRY=false ;;
        --dry-run)   DRY=true ;;
        -h|--help)   sed -n '2,12p' "$0"; exit 0 ;;
    esac
done

SA_NAME="nivesh-devops"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
CB_BUCKET="gs://${PROJECT}_cloudbuild"
AR_REPO="${REGION}-docker.pkg.dev/${PROJECT}/nidp"
NIDP_SA="nidp-sa@${PROJECT}.iam.gserviceaccount.com"

CYAN="\033[1;36m"; GREEN="\033[1;32m"; YEL="\033[1;33m"; RESET="\033[0m"
log()  { echo -e "${CYAN}[devops-setup]${RESET} $*"; }
ok()   { echo -e "${GREEN}[devops-setup] ✅${RESET} $*"; }
warn() { echo -e "${YEL}[devops-setup] ⚠${RESET}  $*"; }
run()  {
    if $DRY; then log "DRY-RUN  $*"
    else log "RUN  $*"; eval "$@"; fi
}

log "project=$PROJECT  region=$REGION  SA=$SA_EMAIL  ${DRY:+(dry-run)}"
echo

# ── 1. Create service account ──────────────────────────────────────────────
if gcloud iam service-accounts describe "$SA_EMAIL" \
        --project="$PROJECT" &>/dev/null; then
    ok "SA $SA_EMAIL already exists"
else
    run "gcloud iam service-accounts create $SA_NAME \
        --display-name='Nivesh DevOps CI/CD' \
        --description='Build, push, and deploy NIDP services. Used by Claude Code agent and CI.' \
        --project='$PROJECT'"
fi
echo

# ── 2. Project-level roles ─────────────────────────────────────────────────
log "Granting project-level roles..."

PROJECT_ROLES=(
    # Cloud Build — submit builds, list/get/cancel them
    "roles/cloudbuild.builds.editor"

    # Artifact Registry — push images (docker push)
    "roles/artifactregistry.writer"

    # Cloud Run — deploy/update services AND jobs, list revisions, get URLs
    "roles/run.admin"

    # Secret Manager — read secrets at build time (migrate step, future steps)
    "roles/secretmanager.secretAccessor"

    # Logging — read Cloud Build + Cloud Run logs
    "roles/logging.viewer"

    # Service Account User — required to deploy Cloud Run with --service-account=nidp-sa
    # (deploy step sets SA on the Cloud Run service/job)
    "roles/iam.serviceAccountUser"
)

for role in "${PROJECT_ROLES[@]}"; do
    run "gcloud projects add-iam-policy-binding '$PROJECT' \
        --member='serviceAccount:$SA_EMAIL' \
        --role='$role' \
        --condition=None \
        --quiet"
    ok "$role"
done
echo

# ── 3. GCS Cloud Build source bucket ──────────────────────────────────────
# gcloud builds submit uploads the source tarball here before creating the
# build. Without objectAdmin the upload fails with FORBIDDEN.
log "Granting objectAdmin on Cloud Build source bucket ($CB_BUCKET)..."
run "gsutil iam ch serviceAccount:${SA_EMAIL}:roles/storage.objectAdmin '$CB_BUCKET'"
ok "storage.objectAdmin on $CB_BUCKET"
echo

# ── 4. Artifact Registry — explicit repo-level write ──────────────────────
# roles/artifactregistry.writer above covers project-level, but a repo-level
# grant is belt-and-suspenders for org policies that restrict project-level
# inheritance.
log "Granting Artifact Registry writer on nidp repo..."
run "gcloud artifacts repositories add-iam-policy-binding nidp \
    --location='$REGION' \
    --project='$PROJECT' \
    --member='serviceAccount:$SA_EMAIL' \
    --role='roles/artifactregistry.writer'"
ok "artifactregistry.writer on $AR_REPO"
echo

# ── 5. Service account impersonation ──────────────────────────────────────
# Cloud Build deploy steps run `gcloud run services update --service-account
# nidp-sa`. To set a service account on a Cloud Run resource the caller must
# have iam.serviceAccountUser on THAT SA specifically.
log "Granting iam.serviceAccountUser on nidp-sa (for Cloud Run deploy)..."
run "gcloud iam service-accounts add-iam-policy-binding '$NIDP_SA' \
    --project='$PROJECT' \
    --member='serviceAccount:$SA_EMAIL' \
    --role='roles/iam.serviceAccountUser'"
ok "iam.serviceAccountUser on $NIDP_SA"
echo

# ── 6. (Optional) Create + download JSON key ──────────────────────────────
if [[ -n "$KEY_FILE" ]]; then
    log "Creating JSON key → $KEY_FILE"
    run "gcloud iam service-accounts keys create '$KEY_FILE' \
        --iam-account='$SA_EMAIL' \
        --project='$PROJECT'"
    ok "Key written to $KEY_FILE"
    echo
fi

# ── Summary ────────────────────────────────────────────────────────────────
cat <<EOF

$(echo -e "${GREEN}Done.${RESET}")

Service account : $SA_EMAIL
Project roles   : ${PROJECT_ROLES[*]}
GCS bucket      : objectAdmin on $CB_BUCKET
AR repo         : writer on $AR_REPO
SA impersonation: iam.serviceAccountUser on $NIDP_SA

To get a fresh short-lived token (valid 1 hour) for the agent:

    gcloud auth activate-service-account \\
        --key-file=<key.json>          # if using JSON key
    gcloud auth print-access-token

  OR (if running as this SA via ADC / Workload Identity):

    gcloud auth print-access-token --impersonate-service-account=$SA_EMAIL

Paste the token into /app/.gcp-token. The agent will use it automatically.

EOF

$DRY && warn "(dry-run only — re-run with --confirm to apply)"
