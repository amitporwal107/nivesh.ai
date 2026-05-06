#!/usr/bin/env bash
# setup_schedules.sh — create/update Cloud Scheduler triggers for
# every NIDP Cloud Run job. Idempotent: existing schedules are
# skipped (use --replace to recreate them).
#
# Standalone — does NOT touch the VM, Postgres, IAM, or anything
# beyond Cloud Scheduler. Safe to re-run.
#
# Usage:
#   ./setup_schedules.sh                       # create missing triggers
#   ./setup_schedules.sh --replace             # delete + recreate all
#   ./setup_schedules.sh --dry-run             # show what would happen
#   ./setup_schedules.sh --project=PROJ        # override project
set -uo pipefail

PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
REGION="${GCP_REGION:-asia-south1}"
DRY=""
REPLACE=""

for arg in "$@"; do
    case "$arg" in
        --project=*) PROJECT="${arg#*=}" ;;
        --region=*)  REGION="${arg#*=}" ;;
        --dry-run)   DRY=1 ;;
        --replace)   REPLACE=1 ;;
        -h|--help)   sed -n '2,15p' "$0"; exit 0 ;;
    esac
done

CYAN="\033[1;36m"; GREEN="\033[1;32m"; YEL="\033[1;33m"; RESET="\033[0m"
log()  { echo -e "${CYAN}[scheduler]${RESET} $*"; }
ok()   { echo -e "${GREEN}[scheduler] ✅${RESET} $*"; }
warn() { echo -e "${YEL}[scheduler] ⚠${RESET}  $*"; }

SA_EMAIL="nidp-sa@${PROJECT}.iam.gserviceaccount.com"
RUN_API="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs"

add_schedule() {
    local job=$1 cron=$2 desc=$3
    local trigger="nidp-cron-$job"

    if [[ -n "$REPLACE" ]] && gcloud scheduler jobs describe "$trigger" \
            --location="$REGION" --project="$PROJECT" &>/dev/null; then
        if [[ -n "$DRY" ]]; then
            log "DRY-RUN  delete $trigger"
        else
            gcloud scheduler jobs delete "$trigger" \
                --location="$REGION" --project="$PROJECT" --quiet >/dev/null 2>&1 || true
            log "deleted $trigger"
        fi
    fi

    if gcloud scheduler jobs describe "$trigger" \
            --location="$REGION" --project="$PROJECT" &>/dev/null; then
        ok "$trigger  (already exists, $desc)"
        return
    fi

    if [[ -n "$DRY" ]]; then
        log "DRY-RUN  create $trigger ($cron Asia/Kolkata)"
    else
        if gcloud scheduler jobs create http "$trigger" \
                --schedule="$cron" --time-zone='Asia/Kolkata' \
                --uri="${RUN_API}/${job}:run" --http-method=POST \
                --oauth-service-account-email="$SA_EMAIL" \
                --location="$REGION" --project="$PROJECT" --quiet >/dev/null 2>&1; then
            ok "$trigger  ($cron, $desc)"
        else
            warn "$trigger  failed to create — re-run with verbose:"
            gcloud scheduler jobs create http "$trigger" \
                --schedule="$cron" --time-zone='Asia/Kolkata' \
                --uri="${RUN_API}/${job}:run" --http-method=POST \
                --oauth-service-account-email="$SA_EMAIL" \
                --location="$REGION" --project="$PROJECT" 2>&1 | tail -10
        fi
    fi
}

log "project=$PROJECT region=$REGION ${DRY:+(dry-run)} ${REPLACE:+(replace)}"
echo

# ── Daily NSE EOD (post-close, 19:00–19:30 IST staggered) ──────────
add_schedule nidp-bhavcopy           '0 19 * * 1-5'   'NSE bhavcopy EOD'
add_schedule nidp-index-close        '0 19 * * 1-5'   'NSE index closes'
add_schedule nidp-fii-dii            '30 19 * * 1-5'  'NSE FII/DII flows'
add_schedule nidp-bulk-deals         '30 19 * * 1-5'  'NSE bulk deals'
add_schedule nidp-block-deals        '30 19 * * 1-5'  'NSE block deals'

# ── T+1 next morning (delivery is republished with delivery-pct) ──
add_schedule nidp-delivery           '30 10 * * 2-6'  'NSE delivery (T+1)'

# ── Daily / weekday data ───────────────────────────────────────────
add_schedule nidp-corporate-actions  '0 20 * * *'     'NSE corporate actions'
add_schedule nidp-rbi-yields         '30 20 * * 1-5'  'RBI WSS yields'
add_schedule nidp-fred-macro         '0 21 * * *'     'FRED macro series'

# ── Monthly ────────────────────────────────────────────────────────
add_schedule nidp-nse-calendar       '0 6 1 * *'      'NSE holiday master'
add_schedule nidp-index-constituents '30 6 1 * *'     'NSE index constituents'

# ── End-of-day snapshot (after all daily ingesters) ────────────────
add_schedule nidp-snapshot-builder   '0 22 * * 1-5'   'snapshot builder'

echo
log "done. List triggers:  ./list_schedules.sh"
log "yfinance_backfill is event-driven (manual run only) — not scheduled."
