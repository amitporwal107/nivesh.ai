"""nidp-feature_snapshotter — derives per-stock daily technical features.

Unlike the source-fetching ingesters in this folder, the snapshotter
reads from NIDP-internal tables (`prices_eod` + `delivery_data`),
computes ~25 features per (symbol, date), and writes one row per
(symbol, as_of_date) into `nidp.stock_features_daily`.

Trigger: invoked after the bhavcopy + delivery ingesters have both
landed for a given as_of_date, gated through the same snapshot
readiness check as `snapshot_builder`.

Public entry: `snapshot_features_for_date(target_date) -> FeatureSnapshotReport`.
"""
from .service import snapshot_features_for_date, FeatureSnapshotReport  # noqa: F401
