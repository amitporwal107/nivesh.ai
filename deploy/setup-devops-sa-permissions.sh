#!/usr/bin/env bash
# setup-devops-sa-permissions.sh
#
# Grants ALL roles required by nivesh-devops SA to build and deploy
# every service across both VMs and Cloud Run.
#
# Covers:
#   - Cloud Build (submit builds, read logs)
#   - Artifact Registry (push/pull images)
#   - Cloud Run (deploy services AND jobs — DaaS API + 13 NIDP ingesters)
#   - Secret Manager (read secrets during build & deploy)
#   - GCS Cloud Build bucket (upload source tarballs)
#   - Compute / OS Login (SSH into nivesh-app-vm and nidp-stack-vm)
#   - IAM service account user (set nidp-sa on Cloud Run resources)
#   - Cloud Scheduler (trigger NIDP cron jobs)
#   - Logging (read build and run logs)
#
# Usage:
#   # Dry-run (default — prints what WOULD be applied)
#   bash deploy/setup-devops-sa-permissions.sh
#
#   # Apply for real
#   bash deploy/setup-devops-sa-permissions.sh --confirm
#
# Requirements:
#   - gcloud authenticated as a project Owner or IAM Admin
#   - gcloud config set project niveshdataintelligence

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
REGION="${GCP_REGION:-asia-south1}"
SA_NAME="nivesh-devops"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

# Other SAs that devops must be able to impersonate / act-as
NIDP_SA="nidp-sa@${PROJECT}.iam.gserviceaccount.com"
NIDP_ORCHESTRATOR_SA="nidp-orchestrator-sa@${PROJECT}.iam.gserviceaccount.com"

CB_BUCKET="gs://${PROJECT}_cloudbuild"
AR_REPO="${REGION}-docker.pkg.dev/${PROJECT}/nidp"

DRY=true
for arg in "$@"; do
  case "$arg" in
    --confirm) DRY=false ;;
    --dry-run) DRY=true ;;
    --project=*) PROJECT="${arg#*=}" ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
  esac
done

CYAN="\033[1;36m"; GREEN="\033[1;32m"; YEL="\033[1;33m"; RED="\033[1;31m"; RESET="\033[0m"
log()  { echo -e "${CYAN}[iam-setup]${RESET} $*"; }
ok()   { echo -e "${GREEN}[iam-setup] ✅${RESET} $*"; }
warn() { echo -e "${YEL}[iam-setup] ⚠${RESET}  $*"; }
run()  {
  if $DRY; then echo -e "  ${YEL}DRY-RUN:${RESET} $*"
  else log "RUN: $*"; eval "$@"; fi
}

echo
log "========================================================"
log " nivesh-devops SA — full build & deploy permissions"
log " SA      : $SA_EMAIL"
log " Project : $PROJECT  |  Region: $REGION"
log " Mode    : $(${DRY} && echo 'DRY-RUN (pass --confirm to apply)' || echo 'LIVE — applying now')"
log "========================================================"
echo

# ── Verify SA exists (non-fatal if caller lacks iam.serviceAccounts.get) ──────
if gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT" &>/dev/null; then
  ok "SA $SA_EMAIL exists (confirmed)"
else
  warn "Could not confirm SA existence — caller may lack iam.serviceAccounts.get."
  warn "Proceeding anyway. If the SA truly doesn't exist, bindings will fail."
  warn "Create it with:"
  warn "  gcloud iam service-accounts create $SA_NAME \\"
  warn "    --display-name='Nivesh DevOps CI/CD' --project='$PROJECT'"
fi
echo

# ── 1. Project-level roles ────────────────────────────────────────────────────
log "Step 1/6 — Granting project-level roles..."
echo

declare -A PROJECT_ROLES
PROJECT_ROLES=(
  # ── Cloud Build ─────────────────────────────────────────────────────────
  ["roles/cloudbuild.builds.editor"]="Submit + cancel Cloud Build jobs (NIDP ingesters, DaaS API, migrations)"

  # ── Artifact Registry ───────────────────────────────────────────────────
  ["roles/artifactregistry.writer"]="Push Docker images (nivesh/backend, nivesh/frontend, nidp/* ingesters)"

  # ── Cloud Run ───────────────────────────────────────────────────────────
  ["roles/run.admin"]="Deploy/update Cloud Run Services (DaaS API) and Jobs (13 NIDP ingesters)"

  # ── Cloud Scheduler ─────────────────────────────────────────────────────
  ["roles/cloudscheduler.admin"]="Create/update cron schedules that trigger NIDP Cloud Run Jobs"

  # ── Secret Manager ──────────────────────────────────────────────────────
  ["roles/secretmanager.secretAccessor"]="Read NIDP_POSTGRES_URL, NIDP_DAAS_INTERNAL_TOKEN during Cloud Build deploy steps"

  # ── IAM (service account user) ──────────────────────────────────────────
  ["roles/iam.serviceAccountUser"]="Required to set --service-account on Cloud Run resources (acts-as nidp-sa)"

  # ── Compute (VM SSH) ────────────────────────────────────────────────────
  ["roles/compute.osAdminLogin"]="SSH into nivesh-app-vm and nidp-stack-vm via OS Login to run redeploy scripts"
  ["roles/compute.viewer"]="Read VM metadata (zone, IP, status) — needed by gcloud compute ssh"
  ["roles/iap.tunnelResourceAccessor"]="SSH via IAP tunnel (no public SSH port needed)"

  # ── Logging ─────────────────────────────────────────────────────────────
  ["roles/logging.viewer"]="Read Cloud Build logs, Cloud Run logs, VM Ops Agent logs"
)

for role in "${!PROJECT_ROLES[@]}"; do
  desc="${PROJECT_ROLES[$role]}"
  run "gcloud projects add-iam-policy-binding '$PROJECT' \
    --member='serviceAccount:$SA_EMAIL' \
    --role='$role' \
    --condition=None \
    --quiet 2>&1 | grep -v '^Updated\|^etag\|^version\|^bindings\|^- members\|serviceAccount\|^  role'"
  ok "$role"
  echo "     ↳ $desc"
done
echo

# ── 2. GCS — Cloud Build source bucket ───────────────────────────────────────
log "Step 2/6 — GCS Cloud Build source bucket ($CB_BUCKET)..."
log "  'gcloud builds submit' uploads source tarball here before build starts."

if ! gcloud storage buckets describe "$CB_BUCKET" --project="$PROJECT" &>/dev/null 2>&1; then
  run "gcloud storage buckets create '$CB_BUCKET' \
    --project='$PROJECT' \
    --location='$REGION' \
    --uniform-bucket-level-access"
fi

run "gcloud storage buckets add-iam-policy-binding '$CB_BUCKET' \
  --member='serviceAccount:$SA_EMAIL' \
  --role='roles/storage.objectAdmin'"
ok "storage.objectAdmin on $CB_BUCKET"
echo

# ── 3. Artifact Registry — repo-level grant (belt-and-suspenders) ─────────────
log "Step 3/6 — Artifact Registry repo-level write ($AR_REPO)..."
log "  Redundant with project-level writer but bypasses org-policy inheritance gaps."

run "gcloud artifacts repositories add-iam-policy-binding nidp \
  --location='$REGION' \
  --project='$PROJECT' \
  --member='serviceAccount:$SA_EMAIL' \
  --role='roles/artifactregistry.writer'"
ok "artifactregistry.writer on nidp repo"
echo

# ── 4. SA impersonation — act-as nidp-sa and nidp-orchestrator-sa ─────────────
log "Step 4/6 — SA impersonation grants..."
log "  Cloud Run deploy steps set --service-account=nidp-sa on services/jobs."
log "  Orchestrator SA needed for SSH backfill/replay triggers from Emergent pod."

for target_sa in "$NIDP_SA" "$NIDP_ORCHESTRATOR_SA"; do
  run "gcloud iam service-accounts add-iam-policy-binding '$target_sa' \
    --project='$PROJECT' \
    --member='serviceAccount:$SA_EMAIL' \
    --role='roles/iam.serviceAccountUser'"
  ok "iam.serviceAccountUser on $target_sa"
done
echo

# ── 5. Compute — VM-level OS Login (SSH) ──────────────────────────────────────
log "Step 5/6 — VM-level compute.osAdminLogin for SSH access..."
log "  Project-level above grants login capability; VM-level ensures it's not"
log "  blocked by a VM's metadata override."

for vm in "nivesh-app-vm" "nidp-stack-vm"; do
  run "gcloud compute instances add-iam-policy-binding '$vm' \
    --zone='$REGION-a' \
    --project='$PROJECT' \
    --member='serviceAccount:$SA_EMAIL' \
    --role='roles/compute.osAdminLogin'"
  ok "compute.osAdminLogin on $vm"
done
echo

# ── 6. OS Login — enable on both VMs ──────────────────────────────────────────
log "Step 6/6 — Enable OS Login metadata on both VMs..."
log "  Without enable-oslogin=true the SSH key registration is ignored."

for vm in "nivesh-app-vm" "nidp-stack-vm"; do
  run "gcloud compute instances add-metadata '$vm' \
    --zone='$REGION-a' \
    --project='$PROJECT' \
    --metadata='enable-oslogin=TRUE'"
  ok "enable-oslogin=TRUE on $vm"
done
echo

# ── Summary ───────────────────────────────────────────────────────────────────
cat <<EOF
$(echo -e "${GREEN}════════════════════════════════════════════════════════${RESET}")
$(echo -e "${GREEN} Permissions reference for nivesh-devops SA${RESET}")
$(echo -e "${GREEN}════════════════════════════════════════════════════════${RESET}")

SERVICE ACCOUNT
  $SA_EMAIL

PROJECT-LEVEL ROLES
  ┌─────────────────────────────────────────┬──────────────────────────────────────────────────────────────────┐
  │ Role                                    │ Why needed                                                       │
  ├─────────────────────────────────────────┼──────────────────────────────────────────────────────────────────┤
  │ roles/cloudbuild.builds.editor          │ Submit / cancel Cloud Build jobs                                 │
  │ roles/artifactregistry.writer           │ Push Docker images to nidp AR repo                               │
  │ roles/run.admin                         │ Deploy Cloud Run Services (DaaS) + Jobs (13 ingesters)           │
  │ roles/cloudscheduler.admin              │ Create/update NIDP cron schedules                                │
  │ roles/secretmanager.secretAccessor      │ Read secrets during Cloud Build deploy steps                     │
  │ roles/iam.serviceAccountUser            │ Set nidp-sa as runtime SA on Cloud Run resources                 │
  │ roles/compute.osAdminLogin              │ SSH into both VMs to run redeploy scripts                        │
  │ roles/compute.viewer                    │ Read VM metadata (zone, IP) for gcloud compute ssh               │
  │ roles/iap.tunnelResourceAccessor        │ SSH via IAP tunnel (no public port required)                     │
  │ roles/logging.viewer                    │ Read Cloud Build / Cloud Run / VM logs                           │
  └─────────────────────────────────────────┴──────────────────────────────────────────────────────────────────┘

RESOURCE-LEVEL GRANTS
  gs://${PROJECT}_cloudbuild          → roles/storage.objectAdmin   (source tarball uploads)
  AR repo: nidp (asia-south1)         → roles/artifactregistry.writer (belt-and-suspenders)
  VM: nivesh-app-vm                   → roles/compute.osAdminLogin
  VM: nidp-stack-vm                   → roles/compute.osAdminLogin
  SA: nidp-sa                         → roles/iam.serviceAccountUser (Cloud Run act-as)
  SA: nidp-orchestrator-sa            → roles/iam.serviceAccountUser (SSH backfill triggers)

HOW TO GET A TOKEN FOR THE AGENT
  # Option A — activate SA key file (if you have the JSON key)
  gcloud auth activate-service-account --key-file=<path/to/nivesh-devops-key.json>
  gcloud auth print-access-token > /app/.gcp-token

  # Option B — impersonate from your own account (no key file needed)
  gcloud auth print-access-token \\
    --impersonate-service-account=$SA_EMAIL > /app/.gcp-token

  # Option C — running AS this SA (ADC / Workload Identity already set)
  gcloud auth print-access-token > /app/.gcp-token

DEPLOY COMMANDS (once token is set)
  # Nivesh app — prod
  bash /app/deploy/nivesh-app/redeploy.sh

  # Nivesh app — staging
  bash /app/deploy/nivesh-staging/redeploy-staging.sh

  # NIDP services — Cloud Build (all ingesters)
  gcloud builds submit --config=backend/nidp/deploy/gcp/cloudbuild-service.yaml \\
    --substitutions=_SERVICE=<name>,_SERVICE_DASHED=<name> --project=$PROJECT .

  # NIDP DaaS API
  gcloud builds submit --config=backend/nidp/deploy/gcp/cloudbuild-daas.yaml \\
    --project=$PROJECT .

  # NIDP code sync to VM (non-Docker services)
  GOOGLE_OAUTH_ACCESS_TOKEN=\$(cat /app/.gcp-token) bash /app/deploy/nidp-vm/redeploy.sh

EOF

$DRY && echo -e "${YEL}⚠  DRY-RUN only — re-run with --confirm to apply all of the above.${RESET}"
