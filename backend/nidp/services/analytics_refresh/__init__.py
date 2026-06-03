"""Nightly refresh of the analytics performance layer.

Calls ``analytics.refresh_all(p_date)`` (migration 047) which populates:
  - analytics.stock_card          — per-stock dashboard row
  - analytics.sector_snapshot     — sector aggregate row
  - Materialized views: mv_top_momentum, mv_delivery_surge,
                        mv_sector_heatmap, mv_fund_category_top10

Must run AFTER fundamental_engine (23:05 IST) and snapshot_builder (22:00 IST)
since stock_card reads from nidp.stock_daily_snapshot and
nidp.stock_features_daily.

T12 fix: this service was missing from the cron schedule, leaving
analytics.stock_card and analytics.sector_snapshot permanently empty.
"""