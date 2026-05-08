#!/usr/bin/env bash
# setup_github_trigger_daas.sh — create a Cloud Build trigger that fires
# on push to the `nidp` branch (or your main branch) whenever files
# under backend/nidp/services/daas_api/** change.
#
# Pre-requisites:
#   • The GitHub repo is already connected to Cloud Build
#     (Cloud Console → Cloud Build → Triggers → Connect Repository)
#   • bootstrap.sh --confirm has run
#   • setup_daas.sh --confirm has run
#
# Usage:
#   ./setup_github_trigger_daas.sh --project=<PROJECT_ID> [options] [--confirm]
#
# Options:
#   --project=<ID>           GCP project (or GCP_PROJECT env)
#   --region=asia-south1     Cloud Build + Run region
#   --repo-owner=<gh-owner>  GitHub org/user (e.g. "nivesh-ai")
#   --repo-name=<gh-repo>    GitHub repository name (e.g. "platform")
#   --branch=nidp            Branch pattern regex (default: ^nidp$)
#   --confirm                Actually create the trigger

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MANIFEST="$SCRIPT_DIR/gcp_resources.jsonl"

PROJECT="${GCP_PROJECT:-}"
REGION="${GCP_REGION:-asia-south1}"
REPO_OWNER="${GH_REPO_OWNER:-}"
REPO_NAME="${GH_REPO_NAME:-}"
BRANCH_PATTERN="^nidp$"
DRY=true

for arg in "$@"; do
    case "$arg" in
        --project=*)      PROJECT="${arg#*=}" ;;
        --region=*)       REGION="${arg#*=}" ;;
        --repo-owner=*)   REPO_OWNER="${arg#*=}" ;;
        --repo-name=*)    REPO_NAME="${arg#*=}" ;;
        --branch=*)       BRANCH_PATTERN="${arg#*=}" ;;
        --confirm)        DRY=false ;;
        --dry-run)        DRY=true ;;
        -h|--help)        sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

log()   { echo "[trigger-daas] $*"; }
maybe() { if $DRY; then log "DRY-RUN  $*"; else log "RUN      $*"; eval "$@"; fi; }
die()   { echo "ERROR: $*" >&2; exit 1; }
manifest() {
    local row="{\"ts\":\"$(date -u +%FT%TZ)\",\"type\":\"$1\",\"name\":\"$2\",\"region\":\"$3\""
    [[ -n "${4:-}" ]] && row="$row,\"extra\":$4"
    row="$row}"
    echo "$row" >> "$MANIFEST"
}

command -v gcloud >/dev/null || die "gcloud CLI not found"
[[ -n "$PROJECT"    ]] || die "--project is required (or GCP_PROJECT env)"
[[ -n "$REPO_OWNER" ]] || die "--repo-owner is required (GitHub org/user)"
[[ -n "$REPO_NAME"  ]] || die "--repo-name is required"

$DRY && log "🚧 dry-run — re-run with --confirm to apply"
log "project=$PROJECT  repo=$REPO_OWNER/$REPO_NAME  branch=$BRANCH_PATTERN"

TRIGGER_NAME="nidp-daas-api-push"
CB_CONFIG="backend/nidp/deploy/gcp/cloudbuild-daas.yaml"

# Check if trigger already exists
if gcloud builds triggers describe "$TRIGGER_NAME" \
        --region="$REGION" --project="$PROJECT" &>/dev/null; then
    log "  trigger already exists: $TRIGGER_NAME — updating"
    _CMD="gcloud builds triggers update $TRIGGER_NAME"
else
    log "  creating trigger: $TRIGGER_NAME"
    _CMD="gcloud builds triggers create github"
fi

maybe "$_CMD \
    --name='$TRIGGER_NAME' \
    --repo-name='$REPO_NAME' \
    --repo-owner='$REPO_OWNER' \
    --branch-pattern='$BRANCH_PATTERN' \
    --build-config='$CB_CONFIG' \
    --included-files='backend/nidp/services/daas_api/**,backend/nidp/deploy/gcp/cloudbuild-daas.yaml' \
    --region='$REGION' \
    --project='$PROJECT' \
    --substitutions='_REGION=$REGION,_CORS_ORIGINS=*'"

$DRY || manifest "cloud_build_trigger" "$TRIGGER_NAME" "$REGION" \
    "{\"repo\":\"$REPO_OWNER/$REPO_NAME\",\"branch\":\"$BRANCH_PATTERN\"}"

cat <<EOF

[trigger-daas] ✅ done.

Trigger '$TRIGGER_NAME' fires when:
  • branch matches: $BRANCH_PATTERN
  • files changed:  backend/nidp/services/daas_api/**

To run manually (no push needed):
  gcloud builds triggers run $TRIGGER_NAME \\
    --branch=nidp --region=$REGION --project=$PROJECT

To view the trigger in Cloud Console:
  https://console.cloud.google.com/cloud-build/triggers;region=$REGION?project=$PROJECT

EOF
$DRY && log "(dry-run only)"
