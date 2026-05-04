"""nidp-snapshot-builder — the AS-OF coherence engine.

Reads from raw NIDP fact tables (prices_eod, delivery_data,
index_eod, index_constituents, fii_dii_flows, corporate_actions,
bulk_deals, block_deals, rbi_yields, nse_holidays) and assembles two
output tables for a target date:

    nidp.market_daily_snapshot   — one row per date
    nidp.stock_daily_snapshot    — one row per (symbol, date, series)

Carry-forward rules:
    * Daily domains (prices_eod, delivery_data, fii_dii_flows, index_eod,
      rbi_yields)            — must be present *for* the target date
                               (else row carries the most recent prior
                               date and `*_as_of` is set accordingly).
    * Index constituents      — uses latest as_of_date <= target_date.
    * Corporate actions       — flagged on the stock row if any CA's
                               ex_date falls in (target_date, target_date+7d].

Build precondition: nidp.daily_snapshot.snapshot_status not in
{FAILED}, and no validation_findings with failure_class='BLOCK' exist
for any contributing source-run-id on this date. The builder refuses
to write rather than mix bad data into the snapshot.

Idempotent: re-running the builder for the same date overwrites the
snapshot rows (single-transaction DELETE + INSERT) and increments
build_run_id.
"""
