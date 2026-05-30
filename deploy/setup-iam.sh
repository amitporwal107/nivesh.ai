#!/usr/bin/env bash
# setup-iam.sh — Single script to provision ALL service account roles
# and permissions for the Nivesh + NIDP platform.
#
# Service accounts managed:
#   nidp-sa            Runtime SA  — Cloud Run jobs/services, ingesters
#   nivesh-devops      CI/CD SA    — Jenkins, Cloud Build, VM deploys, IAM admin
#   nidp-admin         Break-glass — Emergency IAM/secret access (no persistent key)
#
# Accounts NOT managed here (can be deleted):
#   nidp-orchestrator-sa  → merged into nivesh-devops (same SSH need)
#   nivesh-log-triage-sa  → merged into nivesh-devops (already has logging.viewer)
#
# Usage:
#   bash deploy/setup-iam.sh                       # dry-run, shows all changes
#   bash deploy/setup-iam.sh --confirm             # apply everything
#   bash deploy/setup-iam.sh --sa=nidp-sa          # dry-run one SA only
#   bash deploy/setup-iam.sh --sa=nivesh-devops --confirm
#   bash deploy/setup-iam.sh --sa=nidp-admin --confirm
#
# Requirements:
#   gcloud authenticated as project Owner (only Owners can grant iam.securityAdmin)

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
REGION="${GCP_REGION:-asia-south1}"
ZONE="${REGION}-a"

SA_RUNTIME="nidp-sa@${PROJECT}.iam.gserviceaccount.com"
SA_DEVOPS="nivesh-devops@${PROJECT}.iam.gserviceaccount.com"
SA_ADMIN="nidp-admin@${PROJECT}.iam.gserviceaccount.com"

CB_BUCKET="gs://${PROJECT}_cloudbuild"

DRY=true
TARGET_SA="all"

for arg in "$@"; do
  case "$arg" in
    --confirm)   DRY=false ;;
    --dry-run)   DRY=true ;;
    --sa=*)      TARGET_SA="${arg#*=}" ;;
    --project=*) PROJECT="${arg#*=}" ;;
    -h|--help)   sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "Unknown arg: $arg" >&2; exit 2 ;;
  esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────
CYAN="\033[1;36m"; GREEN="\033[1;32m"; YEL="\033[1;33m"; BOLD="\033[1m"; RESET="\033[0m"
log()     { echo -e "${CYAN}[iam]${RESET} $*"; }
ok()      { echo -e "${GREEN}[iam] ✓${RESET} $*"; }
warn()    { echo -e "${YEL}[iam] ⚠${RESET}  $*"; }
section() { echo -e "\n${BOLD}${CYAN}══ $* ══${RESET}"; }
run() {
  if $DRY; then echo -e "  ${YEL}DRY:${RESET} $*"
  else eval "$@" >/dev/null 2>&1 && true; fi
}

# Idempotent project-level role binding
bind_project() {
  local sa=$1 role=$2 desc=$3
  run "gcloud projects add-iam-policy-binding '$PROJECT' \
    --member='serviceAccount:$sa' --role='$role' \
    --condition=None --quiet"
  ok "$role"
  echo "     ↳ $desc"
}

# Idempotent SA-level role binding (iam.serviceAccountUser / TokenCreator)
bind_sa() {
  local on_sa=$1 for_sa=$2 role=$3
  run "gcloud iam service-accounts add-iam-policy-binding '$on_sa' \
    --project='$PROJECT' \
    --member='serviceAccount:$for_sa' \
    --role='$role'"
  ok "$role on $on_sa"
}

# Idempotent VM-level binding
bind_vm() {
  local vm=$1 sa=$2 role=$3
  run "gcloud compute instances add-iam-policy-binding '$vm' \
    --zone='$ZONE' --project='$PROJECT' \
    --member='serviceAccount:$sa' --role='$role'"
  ok "$role on $vm"
}

echo
log "════════════════════════════════════════════════════════════════"
log " Nivesh Platform — IAM Setup"
log " Project : $PROJECT  |  Region : $REGION"
log " Mode    : $(${DRY} && echo 'DRY-RUN  (pass --confirm to apply)' || echo 'LIVE — applying now')"
log " Target  : $TARGET_SA"
log "════════════════════════════════════════════════════════════════"

# ══════════════════════════════════════════════════════════════════════════════
# SA 1: nidp-sa — Runtime SA
# Used by: Cloud Run Jobs (13 NIDP ingesters), DaaS API Cloud Run Service,
#          Cloud Scheduler triggers, GCS raw-archive writes, Secret access
# ══════════════════════════════════════════════════════════════════════════════
setup_nidp_sa() {
  section "nidp-sa  (Runtime SA)"
  log "Email: $SA_RUNTIME"
  log "Used by: Cloud Run Jobs/Services, ingesters, Cloud Scheduler"
  echo

  # ── Project-level roles ───────────────────────────────────────────
  log "Project roles:"
  bind_project "$SA_RUNTIME" "roles/run.developer"               "Invoke Cloud Run Jobs (13 NIDP ingesters)"
  bind_project "$SA_RUNTIME" "roles/cloudscheduler.jobRunner"    "Allow Cloud Scheduler to trigger Cloud Run Jobs"
  bind_project "$SA_RUNTIME" "roles/storage.objectAdmin"         "Write raw feed archives to GCS bucket"
  bind_project "$SA_RUNTIME" "roles/secretmanager.secretAccessor" "Read NIDP_POSTGRES_URL and other secrets at runtime"
  bind_project "$SA_RUNTIME" "roles/artifactregistry.writer"     "Push built ingester images to Artifact Registry"
  bind_project "$SA_RUNTIME" "roles/logging.logWriter"           "Write structured logs to Cloud Logging"
  bind_project "$SA_RUNTIME" "roles/monitoring.metricWriter"     "Write Prometheus metrics to Cloud Monitoring"
  bind_project "$SA_RUNTIME" "roles/iam.serviceAccountUser"      "Allow Cloud Run to actAs this SA (self-reference)"
  bind_project "$SA_RUNTIME" "roles/compute.osAdminLogin"        "SSH into nidp-stack-vm for backfill/replay triggers (replaces nidp-orchestrator-sa)"

  # ── VM-level OS Login ──────────────────────────────────────────────
  echo
  log "VM-level grants (SSH access):"
  bind_vm "nidp-stack-vm" "$SA_RUNTIME" "roles/compute.osAdminLogin"

  # ── Enable OS Login on nidp-stack-vm ──────────────────────────────
  run "gcloud compute instances add-metadata 'nidp-stack-vm' \
    --zone='$ZONE' --project='$PROJECT' --metadata='enable-oslogin=TRUE'"
  ok "enable-oslogin=TRUE on nidp-stack-vm"
}

# ══════════════════════════════════════════════════════════════════════════════
# SA 2: nivesh-devops — CI/CD SA
# Used by: Jenkins, Cloud Build pipelines, VM redeploy scripts (SSH),
#          Artifact Registry pushes, Cloud Run deploys, IAM management
# ══════════════════════════════════════════════════════════════════════════════
setup_nivesh_devops() {
  section "nivesh-devops  (CI/CD SA)"
  log "Email: $SA_DEVOPS"
  log "Used by: Jenkins, Cloud Build, gcloud compute ssh, VM redeploys"
  echo

  # ── Project-level roles ───────────────────────────────────────────
  log "Project roles:"
  bind_project "$SA_DEVOPS" "roles/cloudbuild.builds.editor"      "Submit/cancel Cloud Build jobs (ingesters, DaaS, migrations)"
  bind_project "$SA_DEVOPS" "roles/artifactregistry.writer"       "Push Docker images (backend, frontend, nidp/*)"
  bind_project "$SA_DEVOPS" "roles/run.admin"                     "Deploy/update Cloud Run Services (DaaS) and Jobs (ingesters)"
  bind_project "$SA_DEVOPS" "roles/cloudscheduler.admin"          "Create/update cron schedules for NIDP Cloud Run Jobs"
  bind_project "$SA_DEVOPS" "roles/secretmanager.secretAccessor"  "Read secrets during Cloud Build deploy steps"
  bind_project "$SA_DEVOPS" "roles/iam.serviceAccountUser"        "Set nidp-sa as runtime SA on Cloud Run resources"
  bind_project "$SA_DEVOPS" "roles/compute.osAdminLogin"          "SSH into both VMs to run redeploy scripts from Jenkins/pod"
  bind_project "$SA_DEVOPS" "roles/compute.viewer"                "Read VM metadata (zone, IP) for gcloud compute ssh"
  bind_project "$SA_DEVOPS" "roles/iap.tunnelResourceAccessor"    "SSH via IAP tunnel — no need to open public port 22"
  bind_project "$SA_DEVOPS" "roles/logging.viewer"                "Read Cloud Build, Cloud Run, and VM logs"
  bind_project "$SA_DEVOPS" "roles/iam.securityAdmin"             "Manage IAM policies — grants/revokes roles across project"
  bind_project "$SA_DEVOPS" "roles/iam.serviceAccountAdmin"       "Create/delete/enable service accounts"
  bind_project "$SA_DEVOPS" "roles/iam.serviceAccountKeyAdmin"    "Create and rotate SA JSON keys (Jenkins credential rotation)"

  # ── GCS Cloud Build source bucket ────────────────────────────────
  echo
  log "GCS bucket grant (Cloud Build source uploads):"
  if ! gcloud storage buckets describe "$CB_BUCKET" --project="$PROJECT" &>/dev/null 2>&1; then
    run "gcloud storage buckets create '$CB_BUCKET' \
      --project='$PROJECT' --location='$REGION' --uniform-bucket-level-access"
    ok "created $CB_BUCKET"
  fi
  run "gcloud storage buckets add-iam-policy-binding '$CB_BUCKET' \
    --member='serviceAccount:$SA_DEVOPS' --role='roles/storage.objectAdmin'"
  ok "storage.objectAdmin on $CB_BUCKET"

  # ── Artifact Registry repo-level (belt-and-suspenders) ────────────
  echo
  log "Artifact Registry repo grant:"
  run "gcloud artifacts repositories add-iam-policy-binding nidp \
    --location='$REGION' --project='$PROJECT' \
    --member='serviceAccount:$SA_DEVOPS' --role='roles/artifactregistry.writer'"
  ok "artifactregistry.writer on nidp repo"

  # ── SA impersonation — act-as nidp-sa ─────────────────────────────
  echo
  log "SA impersonation grants (devops can act-as runtime SA):"
  bind_sa "$SA_RUNTIME" "$SA_DEVOPS" "roles/iam.serviceAccountUser"

  # ── VM-level OS Login on both VMs ─────────────────────────────────
  echo
  log "VM-level grants (SSH access for Jenkins + manual deploys):"
  bind_vm "nivesh-app-vm"  "$SA_DEVOPS" "roles/compute.osAdminLogin"
  bind_vm "nidp-stack-vm"  "$SA_DEVOPS" "roles/compute.osAdminLogin"

  run "gcloud compute instances add-metadata 'nivesh-app-vm' \
    --zone='$ZONE' --project='$PROJECT' --metadata='enable-oslogin=TRUE'"
  ok "enable-oslogin=TRUE on nivesh-app-vm"

  run "gcloud compute instances add-metadata 'nidp-stack-vm' \
    --zone='$ZONE' --project='$PROJECT' --metadata='enable-oslogin=TRUE'"
  ok "enable-oslogin=TRUE on nidp-stack-vm"
}

# ══════════════════════════════════════════════════════════════════════════════
# SA 3: nidp-admin — Break-glass IAM Admin
# Used by: Emergency credential rotation, IAM debugging, secret access
# Policy: NO persistent JSON key. Generate a short-lived token on demand.
# ══════════════════════════════════════════════════════════════════════════════
setup_nidp_admin() {
  section "nidp-admin  (Break-glass SA)"
  log "Email: $SA_ADMIN"
  log "Policy: NO persistent key. Use impersonation tokens only."
  echo
  warn "These are the highest-privilege roles in the project."
  warn "Treat this SA as equivalent to an Owner account."
  echo

  log "Project roles:"
  bind_project "$SA_ADMIN" "roles/iam.securityAdmin"               "Read + modify ANY IAM policy in the project"
  bind_project "$SA_ADMIN" "roles/iam.serviceAccountAdmin"         "Create/delete/enable/disable any service account"
  bind_project "$SA_ADMIN" "roles/iam.serviceAccountKeyAdmin"      "Create and delete SA JSON keys"
  bind_project "$SA_ADMIN" "roles/iam.serviceAccountTokenCreator"  "Generate short-lived tokens for any SA"
  bind_project "$SA_ADMIN" "roles/resourcemanager.projectIamAdmin" "Get and set project-level IAM policy directly"
  bind_project "$SA_ADMIN" "roles/secretmanager.admin"             "Full CRUD on all secrets (emergency credential rotation)"
  bind_project "$SA_ADMIN" "roles/viewer"                          "Read-only view of all resources for audit/debug"
  bind_project "$SA_ADMIN" "roles/logging.viewer"                  "Read Cloud Audit Logs — who changed what and when"

  echo
  log "VM-level grants (emergency SSH):"
  bind_vm "nivesh-app-vm" "$SA_ADMIN" "roles/compute.osAdminLogin"
  bind_vm "nidp-stack-vm" "$SA_ADMIN" "roles/compute.osAdminLogin"

  echo
  log "SA impersonation grants (admin can act-as any SA for testing):"
  for target in "$SA_RUNTIME" "$SA_DEVOPS"; do
    bind_sa "$target" "$SA_ADMIN" "roles/iam.serviceAccountUser"
  done

  echo
  log "Artifact Registry admin (image cleanup / emergency rollback):"
  run "gcloud artifacts repositories add-iam-policy-binding nidp \
    --location='$REGION' --project='$PROJECT' \
    --member='serviceAccount:$SA_ADMIN' --role='roles/artifactregistry.admin'"
  ok "artifactregistry.admin on nidp repo"
}

# ══════════════════════════════════════════════════════════════════════════════
# Run selected SAs
# ══════════════════════════════════════════════════════════════════════════════
case "$TARGET_SA" in
  all)
    setup_nidp_sa
    setup_nivesh_devops
    setup_nidp_admin
    ;;
  nidp-sa)        setup_nidp_sa ;;
  nivesh-devops)  setup_nivesh_devops ;;
  nidp-admin)     setup_nidp_admin ;;
  *)
    echo "Unknown --sa value: $TARGET_SA" >&2
    echo "Valid values: all | nidp-sa | nivesh-devops | nidp-admin" >&2
    exit 2
    ;;
esac

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
cat <<SUMMARY

$(echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════════════${RESET}")
$(echo -e "${BOLD}${GREEN} IAM Setup Complete — Reference${RESET}")
$(echo -e "${BOLD}${GREEN}════════════════════════════════════════════════════════════════${RESET}")

SERVICE ACCOUNTS (3 total — minimum viable set)
  nidp-sa          → Runtime: Cloud Run jobs/services, ingesters, GCS, secrets
  nivesh-devops    → CI/CD:   Jenkins, Cloud Build, VM SSH, Artifact Registry, IAM mgmt
  nidp-admin       → Admin:   Break-glass IAM/secret access (no persistent key)

ACCOUNTS TO DELETE (roles merged into above)
  nidp-orchestrator-sa   → merged into nidp-sa (same SSH-to-VM need)
  nivesh-log-triage-sa   → merged into nivesh-devops (already has logging.viewer)

  To delete:
    gcloud iam service-accounts delete nidp-orchestrator-sa@${PROJECT}.iam.gserviceaccount.com
    gcloud iam service-accounts delete nivesh-log-triage-sa@${PROJECT}.iam.gserviceaccount.com

HOW TO GET A TOKEN (for /app/.gcp-token)

  Jenkins / CI pipeline — activate JSON key:
    gcloud auth activate-service-account \\
      --key-file=/path/to/nivesh-devops-key.json
    gcloud auth print-access-token > /app/.gcp-token

  Local / manual — impersonate from your own account (no key needed):
    gcloud auth print-access-token \\
      --impersonate-service-account=$SA_DEVOPS > /app/.gcp-token

  Break-glass admin access:
    gcloud auth print-access-token \\
      --impersonate-service-account=$SA_ADMIN > /app/.gcp-token

JENKINS SSH SETUP
  1. Generate SSH key pair once:
       ssh-keygen -t ed25519 -f ~/.ssh/nivesh-devops-deploy -N ""

  2. Register public key with OS Login (1h TTL — run from Jenkins before SSH):
       TOKEN=\$(gcloud auth print-access-token --impersonate-service-account=$SA_DEVOPS)
       curl -sf -X POST -H "Authorization: Bearer \$TOKEN" \\
         "https://oslogin.googleapis.com/v1/users/aporwal107_gmail_com/sshPublicKeys" \\
         -d '{"key":"'"'\$(cat ~/.ssh/nivesh-devops-deploy.pub)'"'"}'

  3. SSH to VM:
       ssh -i ~/.ssh/nivesh-devops-deploy aporwal107_gmail_com@34.100.186.141  # nivesh-app-vm
       ssh -i ~/.ssh/nivesh-devops-deploy aporwal107_gmail_com@34.93.60.254    # nidp-stack-vm

  4. Or via IAP tunnel (no public SSH port needed):
       gcloud compute ssh nivesh-app-vm --tunnel-through-iap \\
         --impersonate-service-account=$SA_DEVOPS \\
         --zone=$ZONE --project=$PROJECT

SUMMARY
if $DRY; then echo "NOTE: DRY-RUN only -- re-run with --confirm to apply."; fi
