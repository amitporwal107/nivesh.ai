#!/usr/bin/env bash
# deploy_bse_history_fetch.sh — run the BSE announcement-history fetcher as a Cloud
# Run job whose BSE traffic leaves through a residential proxy.
#
# WHY A PROXY
#   api.bseindia.com answers HTTP 403 to cloud networks at its Akamai edge. Verified
#   2026-09-25 from nidp-stack-vm (34.93.60.254), nivesh-app-vm (34.47.250.214) and a
#   Cloud Run job (34.96.40.138). The job therefore routes BSE requests through a
#   proxy whose exit IPs are NOT cloud ranges. Datacenter proxies will not work.
#   The owner chose this route over running the fetcher from a home network,
#   knowing BSE treats its historical corporate data as an information product.
#
# WHAT RUNS
#   Image  : public python:3.11-slim — the fetcher is standard-library only.
#   Code   : bse_offvm_fetch.py, uploaded to gs://${BUCKET}/${PREFIX}/.
#   Output : the bucket is mounted at /mnt/hist; files land in gs://${BUCKET}/${PREFIX}/data/
#            as <kind>/YYYY-MM-DD.{bin,json}. Resumable: re-executing skips finished days.
#   Secret : the proxy URL (http://USER:PASS@HOST:PORT) comes ONLY from Secret Manager
#            secret ${SECRET} via --set-secrets. It is never an argument and never printed.
#   Tasks  : --tasks=N splits the date range across N parallel tasks, each day exactly once
#            (CLOUD_RUN_TASK_INDEX / CLOUD_RUN_TASK_COUNT). Each task paces itself at --delay.
#
# ONE-TIME PREREQUISITE (needs secretmanager.admin — nidp-sa does NOT have it):
#   printf '%s' 'http://USER:PASS@HOST:PORT' | \
#     gcloud secrets create ${SECRET} --project=${PROJECT} --data-file=-
#   gcloud secrets add-iam-policy-binding ${SECRET} --project=${PROJECT} \
#     --member=serviceAccount:${SA_EMAIL} --role=roles/secretmanager.secretAccessor
#   (nidp-sa already holds project-level secretAccessor, so the binding is belt-and-braces.)
#
# Default: --dry-run (prints every command). Pass --confirm to act.
#
# Usage (from repo root):
#   bash backend/nidp/deploy/gcp/deploy_bse_history_fetch.sh --self-test --confirm
#   bash backend/nidp/deploy/gcp/deploy_bse_history_fetch.sh \
#       --from=2024-06-01 --to=2026-09-25 --tasks=3 --confirm
#
# Then, on nidp-stack-vm:
#   gcloud storage rsync -r gs://${BUCKET}/${PREFIX}/data /opt/nidp-staging/bse_history
#   python -m nidp.services.corporate_announcements.bse_offvm_replay /opt/nidp-staging/bse_history --dry-run

set -euo pipefail

PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
REGION="${GCP_REGION:-asia-south1}"
SA_EMAIL="nidp-sa@${PROJECT}.iam.gserviceaccount.com"
BUCKET="nidp-raw-niveshdataintelligence"
PREFIX="bse_history"
SECRET="bse-proxy-url"
JOB="nidp-bse-history-fetch"
IMAGE="docker.io/library/python:3.11-slim"
FROM=""; TO=""; TASKS=1; DELAY="1.0"; SELF_TEST=false; DRY=true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FETCHER="$(cd "$SCRIPT_DIR/../.." && pwd)/services/corporate_announcements/bse_offvm_fetch.py"

for arg in "$@"; do
    case "$arg" in
        --project=*) PROJECT="${arg#*=}"; SA_EMAIL="nidp-sa@${PROJECT}.iam.gserviceaccount.com" ;;
        --region=*)  REGION="${arg#*=}" ;;
        --from=*)    FROM="${arg#*=}" ;;
        --to=*)      TO="${arg#*=}" ;;
        --tasks=*)   TASKS="${arg#*=}" ;;
        --delay=*)   DELAY="${arg#*=}" ;;
        --self-test) SELF_TEST=true ;;
        --confirm)   DRY=false ;;
        --dry-run)   DRY=true ;;
        -h|--help)   sed -n '2,42p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

CYAN="\033[1;36m"; GREEN="\033[1;32m"; RED="\033[1;31m"; RESET="\033[0m"
log() { echo -e "${CYAN}[bse-history]${RESET} $*"; }
ok()  { echo -e "${GREEN}[bse-history] ✅${RESET} $*"; }
die() { echo -e "${RED}[bse-history] ❌${RESET} $*" >&2; exit 1; }
run() { if $DRY; then echo "  DRY: $*"; else eval "$@"; fi; }

[ -f "$FETCHER" ] || die "fetcher not found at $FETCHER"
if ! $SELF_TEST; then
    [[ -n "$FROM" && -n "$TO" ]] || die "--from and --to are required (or use --self-test)"
fi
[[ "$TASKS" =~ ^[1-9][0-9]*$ ]] || die "--tasks must be a positive integer"

# The secret must exist before the job can reference it; say so plainly rather than
# letting `jobs create` fail with an opaque permission error.
if ! gcloud secrets describe "$SECRET" --project="$PROJECT" &>/dev/null; then
    die "Secret Manager secret '$SECRET' does not exist. Create it first (see header) —
       it needs secretmanager.admin, which nidp-sa does not have."
fi
ok "secret '$SECRET' exists (value not read)"

MNT="/mnt/hist"
if $SELF_TEST; then
    ARGS="${MNT}/${PREFIX}/bse_offvm_fetch.py@@--self-test"
    TASKS=1
else
    # --flag=value, never "--flag@@value": gcloud rejects an --args list in which any
    # value repeats, so a one-day run (--from D --to D) would fail to create the job.
    ARGS="${MNT}/${PREFIX}/bse_offvm_fetch.py@@--from=${FROM}@@--to=${TO}@@--out=${MNT}/${PREFIX}/data@@--delay=${DELAY}"
fi

log "1/3 upload fetcher -> gs://${BUCKET}/${PREFIX}/"
run "gcloud storage cp '$FETCHER' 'gs://${BUCKET}/${PREFIX}/bse_offvm_fetch.py' --project='$PROJECT' --quiet"

log "2/3 create/update Cloud Run job ${JOB} (tasks=${TASKS}, self_test=${SELF_TEST})"
COMMON="--image='$IMAGE' --region='$REGION' --project='$PROJECT' \
    --command=python3 --args='^@@^${ARGS}' \
    --tasks=${TASKS} --parallelism=${TASKS} \
    --set-secrets='BSE_PROXY_URL=${SECRET}:latest' \
    --add-volume='name=hist,type=cloud-storage,bucket=${BUCKET}' \
    --add-volume-mount='volume=hist,mount-path=${MNT}' \
    --task-timeout=86400s --max-retries=1 --memory=512Mi --cpu=1 --quiet"
if gcloud run jobs describe "$JOB" --region="$REGION" --project="$PROJECT" &>/dev/null; then
    run "gcloud run jobs update '$JOB' $COMMON"
else
    run "gcloud run jobs create '$JOB' --service-account='$SA_EMAIL' $COMMON"
fi

log "3/3 execute"
if $SELF_TEST; then
    run "gcloud run jobs execute '$JOB' --region='$REGION' --project='$PROJECT' --wait --quiet"
    log "self-test output:"
    run "gcloud logging read 'resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"${JOB}\"' \
        --project='$PROJECT' --freshness=15m --limit=20 --format='value(textPayload)'"
else
    run "gcloud run jobs execute '$JOB' --region='$REGION' --project='$PROJECT' --quiet"
    ok "started. Progress: gcloud logging read 'resource.labels.job_name=\"${JOB}\"' --project=${PROJECT} --freshness=1h"
fi
