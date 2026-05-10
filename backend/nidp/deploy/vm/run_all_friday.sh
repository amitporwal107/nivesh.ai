#!/usr/bin/env bash
# run_all_friday.sh — re-execute every NIDP ingester for a target trading
# date (default: most recent Friday) in two waves so the dependency
# pipeline still works even when triggered out-of-band.
#
# Wave 1 (parallel, ~32 services): all raw ingesters that pull from
#   external sources (NSE / NSDL / RBI / FRED / AMFI / etc.).
# Wave 2 (sequential, ~5 services): everything that derives from
#   Wave 1 output (price_adjuster → snapshot_builder → quality_gate
#   → d1_prep → intelligence).
#
# Usage:
#   sudo bash run_all_friday.sh [YYYY-MM-DD]
#
# Logs land per-service in /opt/nidp/logs/<svc>/<svc>.log; final summary
# in /opt/nidp/logs/run_all_friday.summary

set -uo pipefail

TARGET_DATE="${1:-2026-05-08}"
NIDP_HOME=/opt/nidp
RUNNER="$NIDP_HOME/repo/backend/nidp/deploy/vm/run_service.sh"
SUMMARY="$NIDP_HOME/logs/run_all_friday.summary"

mkdir -p "$NIDP_HOME/logs"
: > "$SUMMARY"

log() { printf '\033[1;36m[run_all_friday]\033[0m %s\n' "$*" | tee -a "$SUMMARY"; }

# ── Wave 1: independent raw ingesters (run in parallel) ───────────
WAVE1_DATED=(
  bhavcopy delivery index_close fii_dii bulk_deals block_deals
  fno_bhavcopy amfi_nav amfi_circulars index_constituents
  mf_disclosure_snapshot mf_holdings
)
WAVE1_NODATE=(
  corporate_actions rbi_yields fred_macro nse_calendar nse_equity_master
  nse_shareholding nse_financials
  corporate_announcements_nse corporate_announcements_bse
  event_calendar event_day_poller
)

# ── Wave 2: derived (sequential) ──────────────────────────────────
WAVE2=(
  price_adjuster
  snapshot_builder
  announcement_classifier
  document_parser
  d1_prep
  intelligence
  quality_gate
)

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
    printf '  ✓ %-32s OK   (%ds)\n' "$svc" "$dur" | tee -a "$SUMMARY"
  else
    printf '  ✗ %-32s FAIL (%ds, rc=%d)\n' "$svc" "$dur" "$rc" | tee -a "$SUMMARY"
  fi
}

# ── Wave 1 ────────────────────────────────────────────────────────
log "─ Wave 1: parallel raw ingesters (target_date=$TARGET_DATE)"
for svc in "${WAVE1_DATED[@]}";  do run_one "$svc" yes & done
for svc in "${WAVE1_NODATE[@]}"; do run_one "$svc" no  & done
wait
log "─ Wave 1 complete"

# ── Wave 2 (each depends on prior wave's output) ───────────────────
log "─ Wave 2: sequential derived jobs"
for svc in "${WAVE2[@]}"; do
  case "$svc" in
    price_adjuster|snapshot_builder|d1_prep|intelligence|quality_gate)
      # snapshot_builder + d1_prep + intelligence accept --date
      if [[ "$svc" == "snapshot_builder" ]]; then
        run_one "$svc" yes
      else
        run_one "$svc" no
      fi
      ;;
    *)
      run_one "$svc" no
      ;;
  esac
done
log "─ Wave 2 complete"

log "All waves done. Summary at $SUMMARY"
