#!/usr/bin/env bash
# fetch_logs.sh — dump recent Cloud Run job logs to /app/.logs/ for
# the agent to read in the sandbox. No credentials in the sandbox; the
# auth happens locally on your machine via your own gcloud session.
#
# Usage:
#   ./fetch_logs.sh                       # last 200 lines from all 11 NIDP jobs (1h window)
#   ./fetch_logs.sh nidp-bhavcopy         # specific job, 1h window
#   ./fetch_logs.sh nidp-bhavcopy 24h     # specific job, custom window
#   ./fetch_logs.sh all 30m               # all NIDP jobs, last 30 min
#
# Writes to /app/.logs/<job>.log (gitignored).

set -euo pipefail

PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
TARGET="${1:-all}"
WINDOW="${2:-1h}"

LOGS_DIR="/app/.logs"
mkdir -p "$LOGS_DIR"

# Make sure .logs/ is gitignored — append once if not already there
GITIGNORE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo /app)"
if [[ -f "$GITIGNORE_ROOT/.gitignore" ]] && ! grep -qE '^\.logs/?$' "$GITIGNORE_ROOT/.gitignore"; then
    echo -e "\n# Agent log workspace — never commit\n.logs/" >> "$GITIGNORE_ROOT/.gitignore"
    echo "  ✓ added .logs/ to .gitignore"
fi

JOBS=(
    nidp-bhavcopy nidp-block-deals nidp-bulk-deals nidp-corporate-actions
    nidp-delivery nidp-fii-dii nidp-index-close nidp-index-constituents
    nidp-nse-calendar nidp-rbi-yields nidp-snapshot-builder
)

fetch_one() {
    local job=$1
    local outfile="$LOGS_DIR/${job}.log"
    echo "[fetch_logs] $job → $outfile (last $WINDOW)..."
    {
        echo "# job: $job"
        echo "# window: last $WINDOW"
        echo "# fetched_at: $(date -u +%FT%TZ)"
        echo "# project: $PROJECT"
        echo "----------------------------------------"
        gcloud logging read \
            "resource.type=cloud_run_job AND resource.labels.job_name=\"${job}\"" \
            --freshness="$WINDOW" \
            --limit=500 \
            --format='value(timestamp,severity,textPayload)' \
            --project="$PROJECT" \
            --order=desc 2>&1
    } > "$outfile"
    local lines=$(wc -l < "$outfile")
    echo "  ✓ wrote $lines lines"
}

if [[ "$TARGET" == "all" ]]; then
    for j in "${JOBS[@]}"; do
        fetch_one "$j"
    done

    # Also dump nidp.job_log + recent validation findings via SSH+docker
    echo "[fetch_logs] also dumping nidp.job_log + validation_findings..."
    DBOUT="$LOGS_DIR/_db_state.log"
    {
        echo "# nidp.job_log (last 24h)"
        echo "# fetched_at: $(date -u +%FT%TZ)"
        echo "----------------------------------------"
        gcloud compute ssh nidp-stack-vm --zone=asia-south1-a \
            --project="$PROJECT" --quiet \
            --command='sudo docker exec nidp-postgres psql -U postgres -d nidp -P pager=off -c "
                SELECT ingester, target_date, status, rows_inserted, rows_skipped,
                       error_class, finished_at
                  FROM nidp.job_log
                 WHERE started_at > NOW() - INTERVAL '\''24 hours'\''
                 ORDER BY started_at DESC LIMIT 30;
                "
                sudo docker exec nidp-postgres psql -U postgres -d nidp -P pager=off -c "
                SELECT detected_at, ingester, severity, failure_class,
                       rule_name, message
                  FROM nidp.validation_findings
                 WHERE detected_at > NOW() - INTERVAL '\''24 hours'\''
                 ORDER BY detected_at DESC LIMIT 30;
                "' 2>&1
    } > "$DBOUT"
    echo "  ✓ wrote $DBOUT"

else
    fetch_one "$TARGET"
fi

echo
echo "── done ──"
echo "agent can now read /app/.logs/* from the sandbox."
echo "tell it: 'logs updated' and it'll grep through /app/.logs/"
