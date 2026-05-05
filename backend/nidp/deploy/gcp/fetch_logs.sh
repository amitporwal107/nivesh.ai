#!/usr/bin/env bash
# fetch_logs.sh — print recent Cloud Run job logs (+ NIDP DB state)
# to stdout. Pipe to clipboard or paste into chat for the agent.
#
# Usage:
#   ./fetch_logs.sh                       # all 11 NIDP jobs, last 1h
#   ./fetch_logs.sh nidp-bhavcopy         # specific job, 1h
#   ./fetch_logs.sh nidp-bhavcopy 24h     # specific job, 24h window
#   ./fetch_logs.sh all 30m               # all jobs, last 30 min
#
# Pipe to clipboard:
#   ./fetch_logs.sh nidp-bhavcopy | clip                    # Windows
#   ./fetch_logs.sh nidp-bhavcopy | pbcopy                  # macOS
#   ./fetch_logs.sh nidp-bhavcopy | xclip -selection clip   # Linux
#
# Or save locally for later paste:
#   ./fetch_logs.sh > recent.log

set -euo pipefail

PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
TARGET="${1:-all}"
WINDOW="${2:-1h}"

JOBS=(
    nidp-bhavcopy nidp-block-deals nidp-bulk-deals nidp-corporate-actions
    nidp-delivery nidp-fii-dii nidp-index-close nidp-index-constituents
    nidp-nse-calendar nidp-rbi-yields nidp-snapshot-builder
)

separator() {
    echo
    echo "════════════════════════════════════════════════════════════"
    echo "$1"
    echo "════════════════════════════════════════════════════════════"
}

dump_job() {
    local job=$1
    separator "JOB: $job  (last $WINDOW)"
    gcloud logging read \
        "resource.type=cloud_run_job AND resource.labels.job_name=\"${job}\"" \
        --freshness="$WINDOW" \
        --limit=200 \
        --format='value(timestamp,severity,textPayload)' \
        --project="$PROJECT" \
        --order=desc 2>&1 || echo "(no logs)"
}

dump_db_state() {
    separator "nidp.job_log + validation_findings (last 24h)"
    gcloud compute ssh nidp-stack-vm --zone=asia-south1-a \
        --project="$PROJECT" --quiet \
        --command='
            echo "── nidp.job_log ──"
            sudo docker exec nidp-postgres psql -U postgres -d nidp -P pager=off \
                -c "SELECT ingester, target_date, status, rows_inserted, rows_skipped, error_class, finished_at
                      FROM nidp.job_log
                     WHERE started_at > NOW() - INTERVAL '\''24 hours'\''
                     ORDER BY started_at DESC LIMIT 30;"
            echo
            echo "── nidp.validation_findings ──"
            sudo docker exec nidp-postgres psql -U postgres -d nidp -P pager=off \
                -c "SELECT detected_at, ingester, severity, failure_class, rule_name, message
                      FROM nidp.validation_findings
                     WHERE detected_at > NOW() - INTERVAL '\''24 hours'\''
                     ORDER BY detected_at DESC LIMIT 30;"
        ' 2>&1 || echo "(VM unreachable)"
}

echo "# fetch_logs.sh"
echo "# project: $PROJECT"
echo "# fetched_at: $(date -u +%FT%TZ)"
echo "# target:  ${TARGET}"
echo "# window:  ${WINDOW}"

if [[ "$TARGET" == "all" ]]; then
    for j in "${JOBS[@]}"; do
        dump_job "$j"
    done
    dump_db_state
else
    dump_job "$TARGET"
    dump_db_state
fi
