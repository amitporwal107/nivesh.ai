#!/usr/bin/env bash
# ensure_raw_dirs.sh — pre-create every nidp_raw subdir so individual
# ingesters never race each other on mkdir under concurrent load.
#
# Idempotent. Safe to add to bootstrap.sh and to a daily cron.
#
# Why this exists:
#   ingester_base + storage_backend lazy-mkdir the raw archive path
#   when storing the first response of the day. Under concurrent
#   writes (e.g., a 90-day backfill heavy with fno_bhavcopy in flight),
#   ext4 has occasionally returned EROFS on a new top-level subdir
#   creation — manifesting as a hard fail in cron'd ingesters
#   (most often `delivery` and `amfi_nav`).
#
# Deploy:
#   - Once: `sudo bash ensure_raw_dirs.sh`
#   - Recurring safety net: add to /etc/cron.d/nidp:
#       0 * * * * root /opt/nidp/repo/backend/nidp/deploy/vm/ensure_raw_dirs.sh >/dev/null 2>&1
#   - Permanent: source this from bootstrap.sh after `chown nidp:nidp /opt/nidp/repo`.

set -euo pipefail

DATA_DIR=/opt/nidp/repo/backend/data/nidp_raw

INGESTERS=(
    amfi_circulars amfi_nav amfi_nav_history
    announcements
    bhavcopy block_deals bulk_deals
    corporate_actions corporate_announcements_bse corporate_announcements_nse
    delivery
    document_parser
    event_calendar event_day_poller
    fii_dii fno_bhavcopy fred_macro
    index_close index_constituents
    mf_disclosure_snapshot mf_holdings
    nse_calendar nse_equity_master nse_financials nse_shareholding
    parsed price_adjuster
    rbi_yields
    snapshot_builder
)

mkdir -p "$DATA_DIR"
for ing in "${INGESTERS[@]}"; do
    mkdir -p "$DATA_DIR/$ing"
done
chown -R nidp:nidp "$DATA_DIR"
echo "[$(date -Iseconds)] ensure_raw_dirs: ensured ${#INGESTERS[@]} subdirs under $DATA_DIR"
