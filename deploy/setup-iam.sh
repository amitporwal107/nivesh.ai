#!/usr/bin/env bash
# setup-iam.sh — Single script to provision ALL service account roles
# and permissions for the Nivesh + NIDP platform.
#
# Compatible with: Linux, macOS, Windows (Git Bash / WSL)
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
#   bash deploy/setup-iam.sh                        # dry-run IAM roles (all SAs)
#   bash deploy/setup-iam.sh --confirm              # apply IAM roles (all SAs)
#   bash deploy/setup-iam.sh --confirm --ssh        # apply IAM + generate/register SSH keys
#   bash deploy/setup-iam.sh --sa=nivesh-devops --confirm --ssh
#   bash deploy/setup-iam.sh --sa=nidp-sa --confirm
#   bash deploy/setup-iam.sh --sa=nidp-admin --confirm
#
# SSH keys generated (in ~/.ssh/nivesh/ or %USERPROFILE%\.ssh\nivesh on Windows):
#   nivesh-devops-deploy   Jenkins/CI → both VMs   (1-year TTL, no passphrase)
#   nidp-sa-deploy         Orchestrator → nidp-stack-vm (1-year TTL, no passphrase)
#   nidp-admin-deploy      Break-glass → both VMs  (1-hour TTL, passphrase protected)
#
# Requirements:
#   - gcloud CLI  (https://cloud.google.com/sdk/docs/install)
#   - ssh-keygen  (built-in on Linux/macOS; Git Bash or OpenSSH on Windows)
#   - curl        (built-in on Linux/macOS/Windows 10+)
#   - python3     (or python on Windows)
#   - Authenticated as project Owner:
#       gcloud auth login
#       gcloud config set project niveshdataintelligence

set -euo pipefail

# ── OS detection + portable paths ────────────────────────────────────────────
case "$(uname -s 2>/dev/null || echo Windows)" in
  Linux*)   OS=linux ;;
  Darwin*)  OS=mac ;;
  MINGW*|MSYS*|CYGWIN*|Windows*) OS=windows ;;
  *)        OS=linux ;;
esac

# Portable home dir: Git Bash sets $HOME; fallback to USERPROFILE on Windows
_HOME="${HOME:-${USERPROFILE:-$PWD}}"

# Convert Windows backslash path to forward-slash for bash tools
if [[ "$OS" == "windows" ]]; then
  _HOME="$(echo "$_HOME" | tr '\\' '/')"
fi

# python3 is 'python' on many Windows installs
PYTHON="python3"
if ! command -v python3 &>/dev/null && command -v python &>/dev/null; then
  PYTHON="python"
fi

# ── Config ────────────────────────────────────────────────────────────────────
PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
REGION="${GCP_REGION:-asia-south1}"
ZONE="${REGION}-a"

SA_RUNTIME="nidp-sa@${PROJECT}.iam.gserviceaccount.com"
SA_DEVOPS="nivesh-devops@${PROJECT}.iam.gserviceaccount.com"
SA_ADMIN="nidp-admin@${PROJECT}.iam.gserviceaccount.com"

CB_BUCKET="gs://${PROJECT}_cloudbuild"
VM_NIVESH_IP="34.100.186.141"
VM_NIDP_IP="34.93.60.254"
OS_LOGIN_USER="aporwal107_gmail_com"    # GCP OS Login username (email dots/@ → underscores)
SSH_KEY_DIR="${_HOME}/.ssh/nivesh"      # portable across Linux/macOS/Windows Git Bash

DRY=true
TARGET_SA="all"
DO_SSH=false                            # --ssh flag enables key generation + registration

for arg in "$@"; do
  case "$arg" in
    --confirm)   DRY=false ;;
    --dry-run)   DRY=true ;;
    --sa=*)      TARGET_SA="${arg#*=}" ;;
    --project=*) PROJECT="${arg#*=}" ;;
    --ssh)       DO_SSH=true ;;
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
# SSH Key Setup — generate ed25519 keys + register via OS Login API
#
# One key pair per role:
#   nivesh-devops-deploy  → used by Jenkins / CI pipeline for VM SSH
#   nidp-sa-deploy        → used by NIDP orchestrator for nidp-stack-vm backfills
#   nidp-admin-deploy     → break-glass emergency SSH (passphrase protected)
#
# Registration uses the OS Login API (not metadata ssh-keys).
# Keys expire after TTL_HOURS (default 8760h = 1 year for persistent keys,
# 1h for the break-glass key).
# ══════════════════════════════════════════════════════════════════════════════
setup_ssh() {
  section "SSH Key Generation + OS Login Registration"
  log "OS      : $OS"
  log "Key dir : $SSH_KEY_DIR"
  log "VMs     : nivesh-app-vm ($VM_NIVESH_IP) | nidp-stack-vm ($VM_NIDP_IP)"
  log "OS user : $OS_LOGIN_USER"
  echo

  # ── Prereq check ──────────────────────────────────────────────────
  local missing=()
  command -v ssh-keygen &>/dev/null || missing+=("ssh-keygen")
  command -v ssh        &>/dev/null || missing+=("ssh")
  command -v curl       &>/dev/null || missing+=("curl")
  command -v "$PYTHON"  &>/dev/null || missing+=("python3 (or python)")

  if [[ ${#missing[@]} -gt 0 ]]; then
    warn "Missing tools: ${missing[*]}"
    if [[ "$OS" == "windows" ]]; then
      warn "On Windows, install via one of:"
      warn "  • Git for Windows (includes ssh, curl):  https://git-scm.com/download/win"
      warn "  • OpenSSH feature: Settings → Apps → Optional Features → OpenSSH Client"
      warn "  • WSL2 (full Linux environment):         https://aka.ms/wsl"
      warn "  • Python: https://www.python.org/downloads/windows/"
    fi
    $DRY || { echo "Aborting — install missing tools first." >&2; exit 1; }
  fi

  mkdir -p "$SSH_KEY_DIR"
  # chmod is a no-op on Windows but harmless
  chmod 700 "$SSH_KEY_DIR" 2>/dev/null || true

  # ── Helper: generate key if missing ───────────────────────────────
  gen_key() {
    local name=$1 comment=$2 passphrase=${3:-}
    local key="$SSH_KEY_DIR/$name"
    if [[ -f "$key" ]]; then
      ok "Key already exists: $key"
    else
      if $DRY; then
        echo -e "  ${YEL}DRY:${RESET} ssh-keygen -t ed25519 -f $key -C '$comment' -N '<passphrase>'"
      else
        ssh-keygen -t ed25519 -f "$key" -C "$comment" -N "$passphrase" -q
        chmod 600 "$key" && chmod 644 "${key}.pub"
        ok "Generated: $key"
      fi
    fi
  }

  # ── Helper: register public key via OS Login API ───────────────────
  # TTL in microseconds. 0 = no expiry (persistent).
  register_key() {
    local key_file=$1 sa_email=$2 ttl_hours=${3:-8760}
    local pub_key token expiry_usec

    if [[ ! -f "${key_file}.pub" ]]; then
      warn "Public key not found: ${key_file}.pub — skipping registration"
      return
    fi

    pub_key=$(cat "${key_file}.pub")

    if $DRY; then
      echo -e "  ${YEL}DRY:${RESET} register ${key_file}.pub via OS Login API as $sa_email (TTL=${ttl_hours}h)"
      return
    fi

    log "Getting token for $sa_email ..."
    token=$(gcloud auth print-access-token \
      --impersonate-service-account="$sa_email" 2>/dev/null \
      || gcloud auth print-access-token 2>/dev/null)

    if [[ -z "$token" ]]; then
      warn "Could not get token for $sa_email — skipping key registration"
      warn "Run manually: gcloud auth print-access-token [--impersonate-service-account=$sa_email]"
      return
    fi

    expiry_usec=$($PYTHON -c "import time; print(int((time.time() + $ttl_hours * 3600) * 1e6))")

    local payload="{\"key\": \"${pub_key}\", \"expirationTimeUsec\": \"${expiry_usec}\"}"
    local http_code
    http_code=$(curl -sf -o /dev/null -w "%{http_code}" -X POST \
      -H "Authorization: Bearer $token" \
      -H "Content-Type: application/json" \
      "https://oslogin.googleapis.com/v1/users/${OS_LOGIN_USER}/sshPublicKeys" \
      -d "$payload" 2>/dev/null || echo "000")

    if [[ "$http_code" == "200" ]]; then
      ok "Registered ${key_file}.pub → OS Login (TTL=${ttl_hours}h, expires in ~$((ttl_hours/24)) days)"
    else
      warn "OS Login API returned HTTP $http_code for $sa_email"
      warn "Key may still work if it was previously registered, or register manually:"
      warn "  gcloud compute os-login ssh-keys add --key-file=${key_file}.pub --ttl=${ttl_hours}h"
    fi
  }

  # ── Helper: test SSH connectivity ─────────────────────────────────
  test_ssh() {
    local key=$1 ip=$2 vm_name=$3
    if $DRY; then
      echo -e "  ${YEL}DRY:${RESET} ssh -i $key -o ConnectTimeout=10 $OS_LOGIN_USER@$ip 'echo SSH_OK'"
      return
    fi
    log "Testing SSH to $vm_name ($ip) ..."
    if ssh -i "$key" \
         -o StrictHostKeyChecking=no \
         -o ConnectTimeout=10 \
         -o BatchMode=yes \
         "${OS_LOGIN_USER}@${ip}" "echo SSH_OK" 2>/dev/null; then
      ok "SSH to $vm_name: OK"
    else
      warn "SSH to $vm_name failed — key may need a few seconds to propagate. Retry:"
      warn "  ssh -i $key $OS_LOGIN_USER@$ip"
    fi
  }

  # ════════════════════════════════════════════════════════════════════
  # Key 1: nivesh-devops-deploy
  # Used by Jenkins pipelines and manual deploys to both VMs
  # ════════════════════════════════════════════════════════════════════
  log "── Key 1: nivesh-devops-deploy (CI/CD + Jenkins) ──"
  gen_key "nivesh-devops-deploy" "nivesh-devops-ci-cd-$(date +%Y%m%d)" ""
  register_key "$SSH_KEY_DIR/nivesh-devops-deploy" "$SA_DEVOPS" 8760
  echo
  log "Testing SSH access with nivesh-devops-deploy key:"
  test_ssh "$SSH_KEY_DIR/nivesh-devops-deploy" "$VM_NIVESH_IP" "nivesh-app-vm"
  test_ssh "$SSH_KEY_DIR/nivesh-devops-deploy" "$VM_NIDP_IP"   "nidp-stack-vm"
  echo

  # ════════════════════════════════════════════════════════════════════
  # Key 2: nidp-sa-deploy
  # Used by NIDP orchestrator / backfill triggers → nidp-stack-vm only
  # ════════════════════════════════════════════════════════════════════
  log "── Key 2: nidp-sa-deploy (NIDP orchestrator → nidp-stack-vm) ──"
  gen_key "nidp-sa-deploy" "nidp-sa-orchestrator-$(date +%Y%m%d)" ""
  register_key "$SSH_KEY_DIR/nidp-sa-deploy" "$SA_RUNTIME" 8760
  echo
  log "Testing SSH access with nidp-sa-deploy key:"
  test_ssh "$SSH_KEY_DIR/nidp-sa-deploy" "$VM_NIDP_IP" "nidp-stack-vm"
  echo

  # ════════════════════════════════════════════════════════════════════
  # Key 3: nidp-admin-deploy (break-glass)
  # Passphrase protected. Short TTL (1h) — re-register each use.
  # ════════════════════════════════════════════════════════════════════
  log "── Key 3: nidp-admin-deploy (break-glass, passphrase protected) ──"
  warn "This key is passphrase-protected. You will be prompted if generating fresh."
  if $DRY; then
    echo -e "  ${YEL}DRY:${RESET} ssh-keygen -t ed25519 -f $SSH_KEY_DIR/nidp-admin-deploy (passphrase required)"
    echo -e "  ${YEL}DRY:${RESET} register via OS Login API as $SA_ADMIN (TTL=1h)"
  else
    local key="$SSH_KEY_DIR/nidp-admin-deploy"
    if [[ ! -f "$key" ]]; then
      log "Generating passphrase-protected key (you will be prompted)..."
      ssh-keygen -t ed25519 -f "$key" -C "nidp-admin-breakglass-$(date +%Y%m%d)"
      chmod 600 "$key" && chmod 644 "${key}.pub"
      ok "Generated: $key"
    else
      ok "Key already exists: $key"
    fi
    # Register for 1h only — must re-register each break-glass use
    register_key "$key" "$SA_ADMIN" 1
  fi
  echo

  # ════════════════════════════════════════════════════════════════════
  # Print SSH config block for ~/.ssh/config
  # ════════════════════════════════════════════════════════════════════
  cat <<SSHCONF

$(echo -e "${BOLD}── Add to ~/.ssh/config ──────────────────────────────────────${RESET}")
# Linux/macOS: ~/.ssh/config
# Windows:     %USERPROFILE%\.ssh\config  (create if missing)

Host nivesh-app-vm
  HostName $VM_NIVESH_IP
  User $OS_LOGIN_USER
  IdentityFile $SSH_KEY_DIR/nivesh-devops-deploy
  StrictHostKeyChecking no
  ServerAliveInterval 30

Host nidp-stack-vm
  HostName $VM_NIDP_IP
  User $OS_LOGIN_USER
  IdentityFile $SSH_KEY_DIR/nivesh-devops-deploy
  StrictHostKeyChecking no
  ServerAliveInterval 30

# After adding the above, connect with:
#   ssh nivesh-app-vm
#   ssh nidp-stack-vm
#
# Windows Git Bash note: use forward slashes in IdentityFile path, e.g.:
#   IdentityFile C:/Users/<you>/.ssh/nivesh/nivesh-devops-deploy

$(echo -e "${BOLD}── Jenkins Credentials to add ───────────────────────────────${RESET}")

  Kind    : SSH Username with private key
  ID      : nivesh-devops-vm-ssh
  Username: $OS_LOGIN_USER
  Key     : (paste contents of $SSH_KEY_DIR/nivesh-devops-deploy)

  Kind    : Secret text
  ID      : NIVESH_APP_VM_HOST
  Value   : $VM_NIVESH_IP

  Kind    : Secret text
  ID      : NIDP_STACK_VM_HOST
  Value   : $VM_NIDP_IP

$(echo -e "${BOLD}── Jenkins Pipeline SSH snippet ─────────────────────────────${RESET}")

  // In Jenkinsfile:
  sshagent(['nivesh-devops-vm-ssh']) {
    sh "ssh $OS_LOGIN_USER@$VM_NIVESH_IP 'bash /opt/nivesh/deploy/redeploy.sh'"
    sh "ssh $OS_LOGIN_USER@$VM_NIDP_IP  'bash /opt/nidp/repo/backend/nidp/deploy/vm/deploy.sh'"
  }

SSHCONF
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
  ssh)            DO_SSH=true ;;   # allow --sa=ssh as alias
  *)
    echo "Unknown --sa value: $TARGET_SA" >&2
    echo "Valid values: all | nidp-sa | nivesh-devops | nidp-admin" >&2
    exit 2
    ;;
esac

# SSH setup runs after IAM (keys need OS Login roles to be in place first)
if $DO_SSH; then
  setup_ssh
fi

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
