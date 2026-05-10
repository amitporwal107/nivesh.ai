#!/usr/bin/env bash
# run_all_friday.sh — re-execute every NIDP ingester for a target trading
# date with bounded concurrency so a small VM doesn't get OOM-thrashed.
#
# Concurrency is capped at WAVE1_PAR (default 4 — tuned for e2-standard-4
# with 4 vCPU, leaves headroom for the Postgres + Kafka containers and
# for the query_api systemd service that the admin console depends on).
#
# Usage:
#   sudo bash run_all_friday.sh [YYYY-MM-DD]   # default: 2026-05-08

set -uo pipefail

TARGET_DATE="${1:-2026-05-08}"
WAVE1_PAR="${WAVE1_PAR:-4}"

NIDP_HOME=/opt/nidp
RUNNER="$NIDP_HOME/repo/backend/nidp/deploy/vm/run_service.sh"
SUMMARY="$NIDP_HOME/logs/run_all_friday.summary"

mkdir -p "$NIDP_HOME/logs"
: > "$SUMMARY"

log() { printf '\033[1;36m[run_all_friday]\033[0m %s\n' "$*" | tee -a "$SUMMARY"; }

# ── Wave 1: independent raw ingesters ──────────────────────────────
WAVE1_DATED=(
  bhavcopy delivery index_close fii_dii bulk_deals block_deals
  fno_bhavcopy amfi_nav amfi_circulars index_constituents
  mf_disclosure_snapshot mf_holdings
)
WAVE1_NODATE=(
  corporate_actions rbi_yields fred_macro nse_calendar nse_equity_master
  nse_shareholding nse_financials event_calendar event_day_poller
)
# Note: corporate_announcements_nse/bse fail without specific runtime
# args (they're high-freq pollers, not date-driven). Skipped here — the
# */10 cron schedule keeps them current.

# ── Wave 2: derived (sequential) ──────────────────────────────────
WAVE2_NODATE=( price_adjuster announcement_classifier document_parser
               d1_prep intelligence quality_gate )
WAVE2_DATED=( snapshot_builder )

run_one() {
  local svc="$1"; local has_date="$2"
  local start; start=$(date +%s)
  if [[ "$has_date" == "yes" ]]; then
    sudo -u nidp "$RUNNER" "$svc" --date "$TARGET_DATE" >/dev/null 2>&1
  else
    sudo -u nidp "$RUNNER" "$svc" >/dev/null 2>&1
  fi
  local rc=$?
  local end; end=$(date +%s)
  local dur=$((end - start))
  if [[ $rc -eq 0 ]]; then
    printf '  ✓ %-32s OK   (%4ds)\n' "$svc" "$dur" | tee -a "$SUMMARY"
  else
    printf '  ✗ %-32s FAIL (%4ds, rc=%d)\n' "$svc" "$dur" "$rc" | tee -a "$SUMMARY"
  fi
}

# Bounded-concurrency runner: spawns at most $WAVE1_PAR concurrent
# children. Uses `wait -n` to reap any one finishing before launching
# the next.
run_bounded() {
  local services=("$@")
  local active=0
  for spec in "${services[@]}"; do
    local svc="${spec%:*}"; local hd="${spec#*:}"
    while (( active >= WAVE1_PAR )); do
      wait -n
      active=$((active - 1))
    done
    run_one "$svc" "$hd" &
    active=$((active + 1))
  done
  wait
}

# ── Build a unified spec list "service:has_date" for wave 1 ─────────
declare -a WAVE1=()
for s in "${WAVE1_DATED[@]}";  do WAVE1+=("$s:yes"); done
for s in "${WAVE1_NODATE[@]}"; do WAVE1+=("$s:no");  done

log "Wave 1: ${#WAVE1[@]} services, max $WAVE1_PAR parallel (target_date=$TARGET_DATE)"
START_W1=$(date +%s)
run_bounded "${WAVE1[@]}"
log "Wave 1 complete in $(( $(date +%s) - START_W1 ))s"

log "Wave 2: ${#WAVE2_NODATE[@]} + ${#WAVE2_DATED[@]} services, sequential"
for svc in "${WAVE2_NODATE[@]}"; do run_one "$svc" no;  done
for svc in "${WAVE2_DATED[@]}";  do run_one "$svc" yes; done
log "Wave 2 complete"

# ── Final summary table from job_log ──────────────────────────────
log "─── Final job_log status (last 90 min) ───"
sudo -u nidp /opt/nidp/venv/bin/python -c "
import asyncio, asyncpg
async def main():
    c = await asyncpg.connect('postgresql://postgres:postgres@localhost:5433/nidp')
    rows = await c.fetch(\"\"\"
        SELECT DISTINCT ON (ingester) ingester, status, started_at, duration_ms, rows_inserted, error_message
          FROM nidp.job_log
         WHERE started_at >= NOW() - INTERVAL '90 minutes'
         ORDER BY ingester, started_at DESC
    \"\"\")
    ok=sum(1 for r in rows if r['status'] in ('OK','GREEN'))
    fail=sum(1 for r in rows if r['status']=='FAILED')
    part=sum(1 for r in rows if r['status']=='PARTIAL')
    print(f'Total {len(rows)} services · OK {ok} · FAILED {fail} · PARTIAL {part}')
    for r in rows:
        em = (r['error_message'] or '')[:80]
        print(f'  {r[\"status\"]:8s} {r[\"ingester\"]:32s} {r[\"duration_ms\"] or 0:6d}ms  rows={r[\"rows_inserted\"] or 0}  {em}')
    await c.close()
asyncio.run(main())
" 2>&1 | tee -a "$SUMMARY"

log "Done. Summary at $SUMMARY"
