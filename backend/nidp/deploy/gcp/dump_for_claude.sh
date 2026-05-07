#!/usr/bin/env bash
# dump_for_claude.sh — one-shot diagnostic dump bundled and uploaded to
# a private GitHub gist. Run this on the VM, paste the URL into chat,
# Claude reads everything via WebFetch. No more screenshot copy-paste.
#
# Usage:
#   bash backend/nidp/deploy/gcp/dump_for_claude.sh
#
# What it captures:
#   1. Feed-health verdict (the per-feed PASS/FAIL/STALE table)
#   2. Recent FAILED job_log entries (last 24h, with error_class + msg)
#   3. ERROR validation findings (last 24h)
#   4. Cloud Run job images currently deployed (per ingester)
#   5. Last execution logs for any feed not GREEN (last 4h)
#   6. Schema migrations applied
#   7. Data depth per feed (row counts + earliest/latest dates)
#
# Privacy: uploads to a *secret* gist (URL-only access, not indexed).
# Anyone with the URL can read it — treat the URL like a password.
# The dump may include error messages, run IDs, and internal table
# stats; it does NOT include secret values (we read env-var *names*
# only, not values).
set -euo pipefail

PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
REGION="${GCP_REGION:-asia-south1}"
WINDOW="${1:-4h}"

OUT="/tmp/nidp_dump_$(date -u +%Y%m%d_%H%M%S).md"

# ── helpers ─────────────────────────────────────────────────────────
hdr() { printf '\n## %s\n\n' "$1"; }
sub() { printf '\n### %s\n\n' "$1"; }
fence_open()  { printf '```%s\n' "${1:-}"; }
fence_close() { printf '```\n'; }

run_psql() {
    sudo docker exec -i nidp-postgres psql -U postgres -d nidp -P pager=off "$@"
}

# ── build the dump ──────────────────────────────────────────────────
{
echo "# NIDP diagnostic dump"
echo
echo "- generated: $(date -u +%FT%TZ)"
echo "- project:   \`$PROJECT\`"
echo "- region:    \`$REGION\`"
echo "- log window: $WINDOW"

# ── 1. Feed health verdict ──────────────────────────────────────────
hdr "1. Feed health (one row per ingester)"
fence_open
run_psql <<'SQL' || echo "(psql failed)"
WITH findings AS (
    SELECT vf.job_run_id,
           count(*) FILTER (WHERE vf.severity='ERROR' AND vf.actual='True')      AS err_n,
           count(*) FILTER (WHERE vf.severity='WARN'  AND vf.actual='True')      AS warn_n,
           string_agg(DISTINCT vf.rule_name, ', ')
             FILTER (WHERE vf.severity='ERROR' AND vf.actual='True')             AS failed_rules
      FROM nidp.validation_findings vf
     GROUP BY vf.job_run_id
)
SELECT
    v.ingester, v.expected_freq AS cadence, v.last_run_status AS run_status,
    COALESCE(f.err_n,0) AS err_findings, COALESCE(f.warn_n,0) AS warn_findings,
    v.consecutive_failures AS streak,
    v.last_run_at::timestamp(0) AS last_run,
    CASE
        WHEN v.last_run_at IS NULL                                                          THEN 'NEVER_RAN'
        WHEN v.expected_freq='daily'     AND v.last_run_at < NOW()-INTERVAL '2 days'        THEN 'STALE'
        WHEN v.expected_freq='monthly'   AND v.last_run_at < NOW()-INTERVAL '40 days'       THEN 'STALE'
        WHEN v.expected_freq='quarterly' AND v.last_run_at < NOW()-INTERVAL '100 days'      THEN 'STALE'
        WHEN v.last_run_status='FAILED'                                                     THEN 'FAILED'
        WHEN v.last_run_status='PARTIAL'                                                    THEN 'PARTIAL'
        WHEN v.last_run_status='SKIPPED'                                                    THEN 'SKIPPED'
        WHEN COALESCE(f.err_n,0) > 0                                                        THEN 'VALIDATION_ERR'
        WHEN v.last_run_status='OK' AND v.consecutive_failures=0
             AND COALESCE(f.warn_n,0)=0                                                     THEN 'GREEN'
        WHEN v.last_run_status='OK' AND COALESCE(f.warn_n,0) > 0                            THEN 'GREEN_W_WARN'
        ELSE 'UNKNOWN'
    END AS verdict,
    COALESCE(f.failed_rules, left(v.last_error_message, 120), '') AS detail
  FROM nidp.v_feed_status v
  LEFT JOIN findings f ON f.job_run_id = v.last_run_id
 ORDER BY
    CASE
        WHEN v.last_run_status='FAILED'                                                     THEN 0
        WHEN v.last_run_at IS NULL                                                          THEN 1
        WHEN (v.expected_freq='daily'     AND v.last_run_at < NOW()-INTERVAL '2 days')
          OR (v.expected_freq='monthly'   AND v.last_run_at < NOW()-INTERVAL '40 days')
          OR (v.expected_freq='quarterly' AND v.last_run_at < NOW()-INTERVAL '100 days')    THEN 2
        WHEN COALESCE(f.err_n,0) > 0                                                        THEN 3
        WHEN v.last_run_status='PARTIAL'                                                    THEN 4
        WHEN v.last_run_status='SKIPPED'                                                    THEN 5
        ELSE 9
    END,
    v.ingester;
SQL
fence_close

# ── 2. Recent FAILED runs ───────────────────────────────────────────
hdr "2. FAILED runs in last 24h (with error details)"
fence_open
run_psql <<'SQL' || echo "(psql failed)"
SELECT ingester, started_at::timestamp(0) AS started,
       error_class, left(error_message, 300) AS err
  FROM nidp.job_log
 WHERE status='FAILED'
   AND started_at > NOW() - INTERVAL '24 hours'
 ORDER BY started_at DESC LIMIT 20;
SQL
fence_close

# ── 3. ERROR validation findings ────────────────────────────────────
hdr "3. ERROR validation findings in last 24h"
fence_open
run_psql <<'SQL' || echo "(psql failed)"
SELECT detected_at::timestamp(0) AS detected,
       ingester, rule_name, failure_class,
       left(message, 200) AS msg
  FROM nidp.validation_findings
 WHERE severity='ERROR' AND actual='True'
   AND detected_at > NOW() - INTERVAL '24 hours'
 ORDER BY detected_at DESC LIMIT 20;
SQL
fence_close

# ── 4. Cloud Run job images currently deployed ──────────────────────
hdr "4. Cloud Run job images deployed"
fence_open
for j in $(gcloud run jobs list --filter="name~^nidp-" --region="$REGION" \
              --project="$PROJECT" --format='value(name)' 2>/dev/null); do
    img=$(gcloud run jobs describe "$j" --region="$REGION" --project="$PROJECT" \
            --format='value(spec.template.spec.template.spec.containers[0].image)' 2>/dev/null \
        || echo "(describe failed)")
    upd=$(gcloud run jobs describe "$j" --region="$REGION" --project="$PROJECT" \
            --format='value(metadata.annotations."run.googleapis.com/lastModifier",updateTime)' 2>/dev/null \
        || echo "(unknown)")
    printf '%-35s %s\n   updated: %s\n\n' "$j" "$img" "$upd"
done
fence_close

# ── 5. Logs for any non-green feed ──────────────────────────────────
hdr "5. Recent logs for non-GREEN feeds (last $WINDOW)"
NOT_GREEN=$(run_psql -tAc "
    SELECT v.ingester
      FROM nidp.v_feed_status v
     WHERE v.last_run_status NOT IN ('OK','SKIPPED')
        OR v.consecutive_failures > 0;" 2>/dev/null || true)

if [[ -z "$NOT_GREEN" ]]; then
    echo "_All feeds GREEN — no logs to dump._"
else
    for ing in $NOT_GREEN; do
        job="nidp-${ing//_/-}"
        sub "$job"
        fence_open
        gcloud logging read \
            "resource.type=cloud_run_job AND resource.labels.job_name=\"${job}\"" \
            --freshness="$WINDOW" --limit=80 \
            --format='value(timestamp,severity,jsonPayload.msg,jsonPayload.exc,textPayload)' \
            --project="$PROJECT" --order=desc 2>&1 | head -100 \
        || echo "(no logs)"
        fence_close
    done
fi

# ── 6. Schema migrations applied ────────────────────────────────────
hdr "6. Schema migrations"
fence_open
run_psql <<'SQL' 2>/dev/null || echo "_no schema_migrations table — migrations may be tracked differently_"
SELECT version, applied_at FROM nidp.schema_migrations ORDER BY 1;
SQL
fence_close

# ── 7. Data depth ───────────────────────────────────────────────────
hdr "7. Data depth per feed"
fence_open
run_psql <<'SQL' || echo "(psql failed)"
SELECT 'bhavcopy'           AS feed, count(DISTINCT trade_date) AS days,
       min(trade_date) AS earliest, max(trade_date) AS latest
  FROM nidp.prices_eod
UNION ALL SELECT 'delivery',          count(DISTINCT trade_date),
       min(trade_date), max(trade_date) FROM nidp.delivery_data
UNION ALL SELECT 'index_close',       count(DISTINCT trade_date),
       min(trade_date), max(trade_date) FROM nidp.index_eod
UNION ALL SELECT 'fii_dii',           count(DISTINCT trade_date),
       min(trade_date), max(trade_date) FROM nidp.fii_dii_flows
UNION ALL SELECT 'bulk_deals',        count(DISTINCT trade_date),
       min(trade_date), max(trade_date) FROM nidp.bulk_deals
UNION ALL SELECT 'block_deals',       count(DISTINCT trade_date),
       min(trade_date), max(trade_date) FROM nidp.block_deals
UNION ALL SELECT 'corporate_actions', count(DISTINCT ex_date),
       min(ex_date),    max(ex_date)    FROM nidp.corporate_actions
UNION ALL SELECT 'rbi_yields',        count(DISTINCT as_of_date),
       min(as_of_date), max(as_of_date) FROM nidp.rbi_yields
UNION ALL SELECT 'fred_macro',        count(DISTINCT as_of_date),
       min(as_of_date), max(as_of_date) FROM nidp.fred_macro
ORDER BY 1;
SQL
fence_close

echo
echo "_end of dump_"
} > "$OUT"

# ── upload to private gist ──────────────────────────────────────────
echo
echo "📄 Dump written: $OUT  ($(wc -l < "$OUT") lines, $(wc -c < "$OUT") bytes)"
echo

if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
    URL=$(gh gist create --desc "NIDP dump $(date -u +%FT%TZ)" "$OUT" 2>&1 | tail -1)
    if [[ "$URL" == https://gist.github.com/* ]]; then
        echo "✅ Uploaded to private gist:"
        echo
        echo "   $URL"
        echo
        echo "Paste that URL into chat. Claude will fetch and read it."
    else
        echo "⚠️  gh gist create returned unexpected output: $URL"
        echo "   Dump is still at: $OUT"
        echo "   Run manually:  gh gist create --desc 'NIDP dump' '$OUT'"
    fi
else
    echo "ℹ️  gh CLI not installed/authed on this VM."
    echo "   Either:"
    echo "     1. Install: sudo apt install gh && gh auth login"
    echo "     2. Or just paste the file contents:"
    echo "          cat $OUT"
fi
