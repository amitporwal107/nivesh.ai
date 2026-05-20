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

# ── Phase 1B daily — NSE rolling-list ingesters ────────────────────
# fno_bhavcopy: same window as cash bhavcopy (post-close, ~18:00 IST
#   actually publishes; we run at 19:30 to give NSE buffer time).
# nse_financials / nse_shareholding: rolling-list endpoints, low-cost
#   to re-run; pinned to 20:30 so the heavy XBRL fan-out doesn't
#   collide with cash-bhavcopy fetch traffic.
add_schedule nidp-fno-bhavcopy       '30 19 * * 1-5'  'NSE F&O EOD bhavcopy'
add_schedule nidp-nse-financials     '30 20 * * *'    'NSE financial-results XBRL'
add_schedule nidp-nse-shareholding   '0 21 * * *'     'NSE shareholding-pattern XBRL'

# ── Phase 1B weekly + derivation ───────────────────────────────────
# nse_equity_master: listing universe drifts slowly; weekly Sunday is
#   plenty.
# price_adjuster: derivation, run AFTER bhavcopy + corporate_actions
#   land for the day. 22:30 (post-snapshot) gives both upstream feeds
#   time to settle.
add_schedule nidp-nse-equity-master  '0 7 * * 0'      'NSE equity master (weekly)'
add_schedule nidp-price-adjuster     '30 22 * * 1-5'  'split/bonus adjusted close (post-bhavcopy)'

# ── End-of-day snapshot (after all daily ingesters) ────────────────
add_schedule nidp-snapshot-builder   '0 22 * * 1-5'   'snapshot builder'

# ── Derived analytics engines (Action Matrix scoring inputs) ───────
# Run order is load-bearing: each reads from the prior tier.
#
# mf_analytics_engine — depends on amfi_nav (20:00) for NAV history.
#   Populates analytics.fund_category_rank: return_1y/3y/5y, Sharpe,
#   Sortino, alpha, beta, volatility, max_drawdown. Must land before
#   mf_derived_refresh (23:50) which reads fund_category_rank.
#
# technical_indicator_engine — depends on price_adjuster (22:30) for
#   adjusted close prices. Computes per-symbol numpy features (SMAs,
#   RSI, MACD, ATR, Bollinger, swing high/low) AND invokes the SQL
#   function nidp.populate_stock_price_features() which fills the
#   252-bar metrics (volatility_1y_pct, return_252d_pct, beta_1y,
#   max_drawdown_1y_pct) from prices_eod_adjusted in one pass.
#
# fundamental_engine — depends on stock_features_daily rows produced
#   by technical_indicator_engine (it looks up symbols WHERE
#   as_of_date = target). Computes Piotroski score, Altman Z,
#   sector_median_pe, and calls populate_stock_features_extended()
#   for PE/PB/ROE/D-E/market_cap/ROCE/EV-EBITDA/dividend_yield.
add_schedule nidp-mf-analytics-engine        '30 20 * * 1-5'  'MF return/Sharpe/Sortino/drawdown rankings'
add_schedule nidp-technical-indicator-engine '35 22 * * 1-5'  'stock technical features + 252-bar price metrics'
add_schedule nidp-fundamental-engine         '5  23 * * 1-5'  'stock Piotroski / Altman / sector PE'

# ── S4: corporate announcements (NSE + BSE) ────────────────────────
# Filings stream all day with peaks around results season + post-close
# 17:00-22:00 IST when board-meeting outcomes land. Every 10 min from
# 09:00-23:50 IST captures pre-open + intraday + post-close windows.
# Upserts on (announcement_id, source) make over-fetching cheap.
add_schedule nidp-corporate-announcements-nse  '*/10 9-23 * * 1-5'  'NSE announcements feed'
add_schedule nidp-corporate-announcements-bse  '*/10 9-23 * * 1-5'  'BSE announcements feed'

# ── S4: Haiku classifier (event taxonomy + impact + sentiment) ─────
# Reads unclassified rows from corporate_announcements, calls Haiku 4.5,
# UPDATEs in place. Every 30 min handles the ~500/day NSE+BSE volume
# with comfortable headroom (Haiku at ~4s/row sequential = ~33 min/day
# total compute, spread across 48 daily firings). Runs all week to
# clean up any stragglers; idempotent on classifier_version.
add_schedule nidp-announcement-classifier  '*/30 * * * *'  'Haiku event/impact classifier'

# ── S5: document parser (download PDFs, extract, chunk, write) ─────
# Two-phase loop on every fire: discover (register pending) + parse
# (download/extract/chunk a batch of 50). Every 15 min all day every
# day — off-hours fires are cheap no-ops when no new attachments are
# pending. Single schedule because add_schedule derives the Cloud Run
# job URI from its first arg, so two schedules need two trigger funcs.
add_schedule nidp-document-parser  '*/15 * * * *'  'PDF parser + chunker (S5)'

# ── Mutual fund data feeds (MF phase) ─────────────────────────────
#
# amfi_nav:
#   AMFI publishes NAVAll.txt by ~18:30 IST each trading day.
#   Run at 20:00 IST Mon-Fri to give AMFI a comfortable buffer.
#   Idempotent: ON CONFLICT UPDATE, so a re-run is harmless.
#
# amfi_circulars:
#   AMFI posts scheme-lifecycle notices (mergers, renames, regulatory
#   changes) asynchronously throughout the day. Daily morning fetch
#   ensures yesterday's circulars are captured by 09:00 IST.
#
# mf_disclosure_snapshot:
#   SEBI mandates TER + risk-o-meter publication by the 10th of each
#   month. We run on the 12th at 10:00 IST to give a two-day buffer
#   for late filers; the diff engine fires automatically to emit
#   mf_scheme_events for any TER/risk changes.
#
# mf_holdings:
#   SEBI mandates monthly portfolio disclosure by the 10th of each
#   month. Run on the 12th at 11:00 IST (one hour after snapshot so
#   scheme_master is fully populated). Staggered from snapshot to
#   avoid concurrent DB write contention.
#
# amfi_nav_history (backfill) is NOT scheduled — run manually once
#   via:  gcloud run jobs execute nidp-amfi-nav-history --region=...
add_schedule nidp-amfi-nav           '0 20 * * 1-5'   'AMFI NAVAll daily (all schemes)'
add_schedule nidp-amfi-circulars     '0 9 * * *'      'AMFI scheme circulars'
add_schedule nidp-mf-disclosure-snapshot '0 10 12 * *' 'MF TER + risk-o-meter snapshot (12th)'
add_schedule nidp-mf-holdings        '0 11 12 * *'    'MF monthly portfolio holdings (12th)'

# ── Corporate event intelligence pipeline ─────────────────────────
#
# event_calendar:
#   Fetches NSE board-meeting / results calendar (today-7 to today+90).
#   Run twice daily: 6:30am seeds tomorrow's schedule before intraday
#   polling starts; 8:30pm picks up any late filings added during the day.
#
# event_day_poller:
#   Checks NSE for results announcements every 5 min during market hours.
#   The service has a built-in IST window guard (exits immediately outside
#   09:15–16:30 IST), so firing every 5 min all day is safe and cheap.
#
# d1_prep:
#   Evening D-1 briefings via Claude Sonnet for tomorrow's results.
#   Runs once at 19:00 IST (after bhavcopy + fno_bhavcopy land).
#
# intelligence:
#   Post-event scoring: volume/OI/PCR confirmation + breakout detection
#   + Telegram alerts. Runs at 20:00 IST so both bhavcopy (19:00) and
#   fno_bhavcopy (19:30) have settled.
add_schedule nidp-event-calendar     '30 6 * * 1-5'   'NSE corporate event calendar (morning + evening)'
# Second daily fire for event_calendar at 20:30 IST — same Cloud Run job, different scheduler trigger.
# add_schedule derives the job URI from arg 1, so we create a wrapper trigger manually here.
if ! gcloud scheduler jobs describe "nidp-cron-event-calendar-pm" \
        --location="$REGION" --project="$PROJECT" &>/dev/null; then
    if [[ -n "$DRY" ]]; then
        log "DRY-RUN  create nidp-cron-event-calendar-pm (30 20 * * 1-5)"
    else
        gcloud scheduler jobs create http "nidp-cron-event-calendar-pm" \
            --schedule="30 20 * * 1-5" --time-zone='Asia/Kolkata' \
            --uri="${RUN_API}/nidp-event-calendar:run" --http-method=POST \
            --oauth-service-account-email="$SA_EMAIL" \
            --location="$REGION" --project="$PROJECT" --quiet && \
            ok "nidp-cron-event-calendar-pm  (30 20 * * 1-5, evening refresh)" || \
            warn "nidp-cron-event-calendar-pm  failed to create"
    fi
else
    ok "nidp-cron-event-calendar-pm  (already exists)"
fi
add_schedule nidp-event-day-poller   '*/5 9-16 * * 1-5' 'Event-day results poller (intraday)'
add_schedule nidp-d1-prep            '0 19 * * 1-5'   'D-1 pre-event briefings (Claude Sonnet)'
add_schedule nidp-intelligence       '0 20 * * 1-5'   'Post-event intelligence + breakout alerts'

# ── Post-ingestion quality gate ────────────────────────────────────
#
# quality_gate:
#   Runs the full post-ingestion pipeline for each trading date:
#     1. Cross-source + temporal consistency checks (mf + equity)
#     2. Weighted quality score (Q = 0.40A + 0.30C + 0.15P + 0.10F + 0.05U)
#     3. Gate decision: PASS → certify + cache flush
#                       REVIEW → exception queue (ops resolves)
#                       FAIL   → quarantine (Cloud Run retries up to max-retries)
#
#   22:30 IST runs AFTER:
#     • snapshot_builder (22:00 IST)  — stock feature snapshots settled
#     • price_adjuster   (22:30 IST)  — same window, no DB write conflict
#       (price_adjuster reads prices_eod; quality_gate reads it too but read-only)
#
#   Non-trading days: Cloud Run jobs exit cleanly with 0 rows found.
#   Re-runs are idempotent: consistency_runs are append-only (new run_id),
#   quality_scores are append-only, certified_dates uses UPSERT.
add_schedule nidp-quality-gate       '30 22 * * 1-5'  'Quality gate: consistency + score + certify'

echo
log "done. List triggers:  ./list_schedules.sh"
log "yfinance_backfill is event-driven (manual run only) — not scheduled."
log "amfi_nav_history is a one-time backfill — not scheduled (run manually)."
