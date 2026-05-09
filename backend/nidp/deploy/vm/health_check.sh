#!/usr/bin/env bash
# health_check.sh — scan nidp.job_log for stale services and alert.
#
# Fired by nidp-health.timer every 30 min. Connects with the same
# /opt/nidp/nidp.env that the cron jobs use, so credentials are
# consistent.
#
# Logic:
#   • Pull latest finished_at per service from nidp.job_log
#   • Compare against an SLO table (hours since last OK)
#   • Anything stale → POST to Telegram
#
# The SLO is intentionally generous: weekly jobs get 8d slack,
# monthly get 35d, intraday pollers get 6h. Tune in $SLO below.

set -uo pipefail

NIDP_HOME=/opt/nidp
set -a; source "$NIDP_HOME/nidp.env"; set +a

PSQL=(psql "$NIDP_POSTGRES_URL" -At -F'|' -v ON_ERROR_STOP=1)

# Service → max-staleness in hours. Anything missing from this table
# is treated as 24h (the default for "daily").
read -r -d '' SLO <<'EOF' || true
bhavcopy=24
index_close=24
fii_dii=24
bulk_deals=24
block_deals=24
delivery=30
corporate_actions=24
rbi_yields=48
fred_macro=48
nse_calendar=840
index_constituents=840
fno_bhavcopy=24
nse_financials=48
nse_shareholding=48
nse_equity_master=192
price_adjuster=24
snapshot_builder=24
corporate_announcements_nse=2
corporate_announcements_bse=2
announcement_classifier=2
document_parser=2
amfi_nav=24
amfi_circulars=48
mf_disclosure_snapshot=840
mf_holdings=840
event_calendar=24
event_day_poller=2
d1_prep=24
intelligence=24
quality_gate=24
EOF

declare -A SLO_HOURS
while IFS='=' read -r k v; do
    [[ -n "$k" ]] && SLO_HOURS["$k"]="$v"
done <<<"$SLO"

# Pull last successful run per service.
ROWS=$("${PSQL[@]}" -c "
    select service,
           extract(epoch from (now() - max(finished_at))) / 3600
      from nidp.job_log
     where status = 'OK'
     group by service
" 2>/dev/null) || {
    echo "health_check: cannot connect to postgres" >&2
    exit 1
}

stale_msgs=()
declare -A SEEN
while IFS='|' read -r svc hours_str; do
    [[ -z "$svc" ]] && continue
    SEEN["$svc"]=1
    hours=${hours_str%.*}
    slo=${SLO_HOURS[$svc]:-24}
    if (( hours > slo )); then
        stale_msgs+=("⚠ $svc stale: ${hours}h since last OK (SLO ${slo}h)")
    fi
done <<<"$ROWS"

# Services in SLO table that have NEVER produced an OK row.
for svc in "${!SLO_HOURS[@]}"; do
    if [[ -z "${SEEN[$svc]:-}" ]]; then
        stale_msgs+=("✗ $svc has no OK row ever — has it run?")
    fi
done

if [[ ${#stale_msgs[@]} -eq 0 ]]; then
    echo "health_check: all services within SLO"
    exit 0
fi

printf '%s\n' "${stale_msgs[@]}"

# Telegram alert (only if configured).
if [[ -n "${NIDP_TELEGRAM_BOT_TOKEN:-}" && -n "${NIDP_TELEGRAM_CHAT_ID:-}" ]]; then
    BODY=$(printf 'NIDP health check\n%s\n' "$(printf '%s\n' "${stale_msgs[@]}")")
    curl -fsS -X POST \
        "https://api.telegram.org/bot${NIDP_TELEGRAM_BOT_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${NIDP_TELEGRAM_CHAT_ID}" \
        --data-urlencode "text=${BODY}" \
        > /dev/null || echo "health_check: telegram POST failed" >&2
fi

exit 1
