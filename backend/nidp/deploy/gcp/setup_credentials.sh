#!/usr/bin/env bash
# setup_credentials.sh — provision the NIDP runtime service account
# and download a JSON key to /app/.gcp/nidp-sa.json.
#
# Implements Path A from the runbook: a narrow-scope runtime SA with
# only the roles the ingesters + Cloud Run jobs need at runtime. Your
# personal `gcloud auth` (run beforehand) does the one-time create.
#
# Idempotent: re-running re-uses the existing SA + IAM bindings;
# only the JSON key is freshly minted (older keys are listed but NOT
# auto-deleted — use rotate_credentials.sh for that).
#
# Default mode: --dry-run. Pass --confirm to actually create.
#
# Usage:
#   ./setup_credentials.sh --project=<PROJECT_ID> [--region=asia-south1]
#                          [--key-out=/app/.gcp/nidp-sa.json]
#                          [--name=nidp-sa]
#                          [--confirm]
#
# Env overrides:
#   GCP_PROJECT, GCP_REGION, NIDP_SA_NAME, NIDP_SA_KEY_PATH

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────
PROJECT="${GCP_PROJECT:-}"
REGION="${GCP_REGION:-asia-south1}"
SA_NAME="${NIDP_SA_NAME:-nidp-sa}"
KEY_PATH="${NIDP_SA_KEY_PATH:-/app/.gcp/nidp-sa.json}"
DRY=true

# ── Args ────────────────────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --project=*)  PROJECT="${arg#*=}" ;;
        --region=*)   REGION="${arg#*=}" ;;
        --name=*)     SA_NAME="${arg#*=}" ;;
        --key-out=*)  KEY_PATH="${arg#*=}" ;;
        --confirm)    DRY=false ;;
        --dry-run)    DRY=true ;;
        -h|--help)
            sed -n '2,18p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

# ── Sanity: gcloud installed ────────────────────────────────────────
if ! command -v gcloud >/dev/null; then
    cat >&2 <<'EOF'
ERROR: gcloud CLI not found. Install it first:
    https://cloud.google.com/sdk/docs/install
On Debian/Ubuntu:
    sudo apt-get install -y google-cloud-cli
On macOS:
    brew install --cask google-cloud-sdk
EOF
    exit 1
fi

# ── Sanity: project ID ──────────────────────────────────────────────
if [[ -z "$PROJECT" ]]; then
    echo "ERROR: --project is required (or set GCP_PROJECT env)" >&2
    exit 2
fi

# ── Sanity: caller is authenticated ─────────────────────────────────
ACTIVE_ACCT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null || true)
if [[ -z "$ACTIVE_ACCT" ]]; then
    cat >&2 <<EOF
ERROR: no active gcloud account. Run first:
    gcloud auth login
    gcloud config set project ${PROJECT}
    gcloud auth application-default login
EOF
    exit 1
fi

SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

log() { echo "[setup-creds] $*"; }
maybe() {
    if $DRY; then log "DRY-RUN  $*"; else log "RUN      $*"; eval "$@"; fi
}

if $DRY; then
    log "🚧 dry-run. Re-run with --confirm to actually create."
fi

cat <<EOF
[setup-creds] config:
  project:    ${PROJECT}
  region:     ${REGION}
  caller:     ${ACTIVE_ACCT}
  sa name:    ${SA_NAME}
  sa email:   ${SA_EMAIL}
  key path:   ${KEY_PATH}
EOF

# ── 1. Enable APIs needed by Phase 2a ───────────────────────────────
APIS=(
    iam.googleapis.com
    iamcredentials.googleapis.com
    serviceusage.googleapis.com
    cloudresourcemanager.googleapis.com
    secretmanager.googleapis.com
    storage.googleapis.com
    artifactregistry.googleapis.com
    run.googleapis.com
    cloudscheduler.googleapis.com
    compute.googleapis.com
    logging.googleapis.com
    monitoring.googleapis.com
)
log "ensuring required APIs are enabled..."
for api in "${APIS[@]}"; do
    if gcloud services list --enabled --project="$PROJECT" \
            --filter="config.name=$api" --format="value(config.name)" 2>/dev/null \
            | grep -q "^$api$"; then
        log "  ✓ $api"
    else
        maybe "gcloud services enable $api --project=$PROJECT"
    fi
done

# ── 2. Create runtime SA (idempotent) ───────────────────────────────
if gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT" &>/dev/null; then
    log "  ✓ service account already exists: $SA_EMAIL"
else
    maybe "gcloud iam service-accounts create $SA_NAME \
        --display-name='NIDP runtime service account' \
        --description='Used by NIDP Cloud Run Jobs + ingesters' \
        --project=$PROJECT"
fi

# ── 3. Bind narrow runtime roles ────────────────────────────────────
ROLES=(
    roles/storage.objectAdmin            # raw-archive bucket writes
    roles/secretmanager.secretAccessor   # read POSTGRES_URL etc.
    roles/run.developer                  # invoke Cloud Run Jobs
    roles/cloudscheduler.jobRunner       # cron triggers
    roles/artifactregistry.writer        # push container images
    roles/logging.logWriter              # write structured logs
    roles/monitoring.metricWriter        # write Prometheus metrics
    roles/iam.serviceAccountUser         # let Cloud Run actAs this SA
)
log "binding runtime roles..."
for role in "${ROLES[@]}"; do
    if $DRY; then
        log "DRY-RUN  add-iam-policy-binding $role"
    else
        # add-iam-policy-binding is idempotent server-side (no-op if
        # binding already exists).
        gcloud projects add-iam-policy-binding "$PROJECT" \
            --member="serviceAccount:$SA_EMAIL" --role="$role" \
            --condition=None --quiet >/dev/null
        log "  ✓ $role"
    fi
done

# ── 4. Mint JSON key ────────────────────────────────────────────────
mkdir -p "$(dirname "$KEY_PATH")"
chmod 700 "$(dirname "$KEY_PATH")" 2>/dev/null || true

# List existing keys so the operator sees what's there before creating one more
log "existing user-managed keys:"
gcloud iam service-accounts keys list --iam-account="$SA_EMAIL" \
    --project="$PROJECT" --filter='keyType=USER_MANAGED' \
    --format="table(name.basename(),validAfterTime,disabled)" 2>/dev/null \
    | sed 's/^/  /' || true

if [[ -f "$KEY_PATH" ]] && ! $DRY; then
    BACKUP="${KEY_PATH}.$(date +%Y%m%d-%H%M%S).bak"
    log "existing key file at $KEY_PATH — backing up to $BACKUP"
    mv "$KEY_PATH" "$BACKUP"
fi

maybe "gcloud iam service-accounts keys create '$KEY_PATH' \
    --iam-account=$SA_EMAIL --project=$PROJECT"

if ! $DRY; then
    chmod 600 "$KEY_PATH"
    log "  ✓ key written to $KEY_PATH (chmod 600)"
fi

# ── 5. .gitignore sanity ────────────────────────────────────────────
GITIGNORE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo /app)"
if [[ -f "$GITIGNORE_ROOT/.gitignore" ]]; then
    if ! grep -q '^\.gcp/' "$GITIGNORE_ROOT/.gitignore"; then
        log "WARNING: $GITIGNORE_ROOT/.gitignore is missing a '.gcp/' entry."
        log "  appending now..."
        if ! $DRY; then
            printf '\n# GCP credentials (NIDP)\n.gcp/\n*.gcp.json\nbackend/.gcp/\n' \
                >> "$GITIGNORE_ROOT/.gitignore"
        fi
    else
        log "  ✓ .gitignore excludes .gcp/"
    fi
fi

# Hard-fail if the key path would land inside a git repo and isn't ignored.
if [[ -d "$GITIGNORE_ROOT/.git" ]] && ! $DRY && [[ -f "$KEY_PATH" ]]; then
    if ! git -C "$GITIGNORE_ROOT" check-ignore -q "$KEY_PATH"; then
        log "ERROR: $KEY_PATH is NOT git-ignored. Remove it before continuing."
        exit 1
    fi
    log "  ✓ git check-ignore confirms $KEY_PATH is excluded"
fi

# ── 6. Smoke-verify the key works ───────────────────────────────────
if ! $DRY; then
    log "verifying key by activating and listing a single secret name..."
    GOOGLE_APPLICATION_CREDENTIALS="$KEY_PATH" \
        gcloud auth activate-service-account --key-file="$KEY_PATH" --quiet
    GOOGLE_APPLICATION_CREDENTIALS="$KEY_PATH" \
        gcloud projects describe "$PROJECT" --format="value(projectId)" >/dev/null
    log "  ✓ key authenticates against project $PROJECT"
fi

# ── 7. Print env-var hints ──────────────────────────────────────────
cat <<EOF

[setup-creds] ✅ done.

Next, in the shell that will run NIDP:

    export GOOGLE_APPLICATION_CREDENTIALS=$KEY_PATH
    export GCP_PROJECT=$PROJECT
    export GCP_REGION=$REGION

Or persist these to /app/.env (already gitignored). Then:

    cd $(cd "$(dirname "$0")" && pwd)
    ./bootstrap.sh --confirm    # provisions resources, logs to gcp_resources.jsonl

When dev/test ends:

    ./rotate_credentials.sh --confirm    # cycles the SA key
    ./teardown.sh --confirm              # destroys everything in the manifest

EOF

$DRY && log "(dry-run only — re-run with --confirm to apply)"
