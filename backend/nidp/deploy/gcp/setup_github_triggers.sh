#!/usr/bin/env bash
# setup_github_triggers.sh — wire up GitHub-push → Cloud Build for
# every NIDP service + the migrations folder.
#
# After this runs, pushing to the nidp branch on GitHub auto-builds
# (and updates the Cloud Run job for) only the services whose code
# changed, and re-applies migrations if migrations/*.sql changed.
#
# Prereqs (one-time, manual):
#   1. Connect the GitHub repo to Cloud Build via the Console:
#        https://console.cloud.google.com/cloud-build/repositories
#      Click "Connect Repository" → choose GitHub → authenticate →
#      pick amitporwal107/nivesh.ai. (Cannot be done via gcloud yet.)
#   2. The Cloud Build SA needs IAP-tunnel + osAdminLogin to run the
#      migration trigger; this script grants those automatically.
#
# Usage:
#   ./setup_github_triggers.sh                  # create all 14 triggers
#   ./setup_github_triggers.sh --service=bhavcopy   # one trigger
#   ./setup_github_triggers.sh --dry-run        # show what would happen
#   ./setup_github_triggers.sh --replace        # delete + recreate
set -uo pipefail

PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
REGION="${GCP_REGION:-asia-south1}"
# 2nd-gen Cloud Build "host connection" + linked repository.
# These names come from the Cloud Build Console → Repositories page.
# Override via env if your connection has different names.
CB_CONNECTION="${CB_CONNECTION:-nivesh}"
CB_REPOSITORY="${CB_REPOSITORY:-amitporwal107-nivesh.ai}"
BRANCH_PATTERN='^nidp$'

DRY=""
REPLACE=""
SERVICE_FILTER=""
for arg in "$@"; do
    case "$arg" in
        --project=*) PROJECT="${arg#*=}" ;;
        --region=*)  REGION="${arg#*=}" ;;
        --service=*) SERVICE_FILTER="${arg#*=}" ;;
        --dry-run)   DRY=1 ;;
        --replace)   REPLACE=1 ;;
        -h|--help)   sed -n '2,28p' "$0"; exit 0 ;;
    esac
done

CYAN="\033[1;36m"; GREEN="\033[1;32m"; YEL="\033[1;33m"; RED="\033[1;31m"; RESET="\033[0m"
log()  { echo -e "${CYAN}[triggers]${RESET} $*"; }
ok()   { echo -e "${GREEN}[triggers] ✅${RESET} $*"; }
warn() { echo -e "${YEL}[triggers] ⚠${RESET}  $*"; }
err()  { echo -e "${RED}[triggers] ❌${RESET} $*"; }

ALL_SERVICES=(
    bulk_deals block_deals bhavcopy delivery
    index_close index_constituents fii_dii corporate_actions
    nse_calendar rbi_yields snapshot_builder
    fred_macro yfinance_backfill
)

if [[ -n "$SERVICE_FILTER" ]]; then
    SERVICES=("$SERVICE_FILTER")
else
    SERVICES=("${ALL_SERVICES[@]}")
fi

# ── Pre-flight ──────────────────────────────────────────────────────
REPO_RESOURCE="projects/$PROJECT/locations/$REGION/connections/$CB_CONNECTION/repositories/$CB_REPOSITORY"
log "project=$PROJECT region=$REGION ${DRY:+(dry-run)} ${REPLACE:+(replace)}"
log "repo:    $REPO_RESOURCE"

# Verify the connection + repository exist (2nd-gen).
if ! gcloud builds repositories describe "$CB_REPOSITORY" \
        --connection="$CB_CONNECTION" --region="$REGION" \
        --project="$PROJECT" &>/dev/null; then
    err "Cloud Build connection '$CB_CONNECTION' or repository '$CB_REPOSITORY' not found in $REGION."
    err "  Available connections + repos:"
    gcloud builds connections list --region="$REGION" --project="$PROJECT" \
        --format='table(name.basename())' 2>&1 | sed 's/^/      /'
    err "  Override via env: CB_CONNECTION=... CB_REPOSITORY=... ./setup_github_triggers.sh"
    exit 1
fi
ok "connection + repo verified"

# Cloud Build's default SA — needed for IAP tunnel (migration trigger).
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format='value(projectNumber)' 2>/dev/null)
CB_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

if [[ -n "$PROJECT_NUMBER" ]]; then
    log "Cloud Build SA: $CB_SA"
    if [[ -z "$DRY" ]]; then
        # Grant IAP tunnel + OS admin login (idempotent — repeat is fine)
        for role in roles/iap.tunnelResourceAccessor roles/compute.osAdminLogin roles/compute.viewer; do
            gcloud projects add-iam-policy-binding $PROJECT \
                --member="serviceAccount:$CB_SA" --role="$role" \
                --condition=None --quiet >/dev/null 2>&1 || true
        done
        ok "Cloud Build SA has IAP tunnel + OS admin login"
    fi
fi

# ── Helper to create / replace one trigger ──────────────────────────
create_trigger() {
    local name=$1 cfg=$2 included=$3
    shift 3
    local subs=("$@")

    if [[ -n "$REPLACE" ]] && gcloud builds triggers describe "$name" \
            --region="$REGION" --project=$PROJECT &>/dev/null; then
        if [[ -n "$DRY" ]]; then
            log "DRY-RUN  delete trigger $name"
        else
            gcloud builds triggers delete "$name" \
                --region="$REGION" --project=$PROJECT --quiet >/dev/null 2>&1 || true
            log "deleted $name"
        fi
    fi

    if gcloud builds triggers describe "$name" --region="$REGION" --project=$PROJECT &>/dev/null; then
        ok "$name  (already exists)"
        return
    fi

    # gcloud wants a single --substitutions flag with comma-separated
    # KV pairs — repeating the flag drops all but the last value.
    local sub_csv
    sub_csv=$(IFS=,; echo "${subs[*]}")

    if [[ -n "$DRY" ]]; then
        log "DRY-RUN  create $name (config=$cfg, included=$included, subs=$sub_csv)"
        return
    fi

    # 2nd-gen syntax: --repository=<full resource name>; the
    # `gcloud builds triggers create github` subcommand still works
    # for 2nd-gen as long as you pass --repository instead of
    # --repo-owner/--repo-name.
    if gcloud builds triggers create github \
            --name="$name" \
            --repository="$REPO_RESOURCE" \
            --branch-pattern="$BRANCH_PATTERN" \
            --included-files="$included" \
            --build-config="$cfg" \
            --substitutions="$sub_csv" \
            --region="$REGION" \
            --project=$PROJECT --quiet >/dev/null 2>&1; then
        ok "$name"
    else
        err "$name failed — full error:"
        gcloud builds triggers create github \
            --name="$name" \
            --repository="$REPO_RESOURCE" \
            --branch-pattern="$BRANCH_PATTERN" \
            --included-files="$included" \
            --build-config="$cfg" \
            --substitutions="$sub_csv" \
            --region="$REGION" \
            --project=$PROJECT 2>&1 | sed 's/^/    /'
    fi
}

# ── Per-service triggers ────────────────────────────────────────────
echo
log "creating per-service triggers..."
SHARED_GLOBS='backend/nidp/shared/**,backend/nidp/contracts/**,backend/nidp/deploy/requirements.txt,backend/nidp/__init__.py'
for svc in "${SERVICES[@]}"; do
    svc_dashed="${svc//_/-}"
    included="backend/nidp/services/${svc}/**,${SHARED_GLOBS}"
    create_trigger \
        "nidp-${svc_dashed}-on-push" \
        "backend/nidp/deploy/gcp/cloudbuild-service.yaml" \
        "$included" \
        "_SERVICE=${svc}" \
        "_SERVICE_DASHED=${svc_dashed}" \
        "_REGION=${REGION}"
done

# ── Migrations trigger ──────────────────────────────────────────────
if [[ -z "$SERVICE_FILTER" ]]; then
    echo
    log "creating migrations trigger..."
    create_trigger \
        "nidp-migrations-on-push" \
        "backend/nidp/deploy/gcp/cloudbuild-migrations.yaml" \
        "backend/nidp/migrations/**" \
        "_VM_NAME=nidp-stack-vm" \
        "_ZONE=${REGION}-a"
fi

echo
log "done. List triggers:"
log "  gcloud builds triggers list --region=$REGION --project=$PROJECT --format='table(name,filename)' | grep nidp-"
