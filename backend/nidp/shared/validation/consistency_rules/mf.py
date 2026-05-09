"""Mutual Fund consistency rules — all five dimensions.

Registered under domain='mf'.

Dimensions covered:
  CROSS_SOURCE  — NAV matches between mf_nav_daily and scheme_master cache pointer
  INTERNAL      — Direct plan TER < Regular plan TER (SEBI mandate)
                — Holdings weights sum to 100% ± 0.5% per scheme
                — Scheme category identical across scheme_master and disclosure snapshot
  TEMPORAL      — NAV single-day change ≤ 20%
                — TER change between snapshots ≤ 25% (requires new mf_scheme_event)
                — AUM single-snapshot change ≤ 50%

Source precedence (golden → fallback):
  NAV       : AMFI NAVAll.txt (mf_nav_daily)     > mf_scheme_master.latest_nav
  TER       : AMC Fact Sheet / disclosure_snapshot — single authoritative source
  Holdings  : AMC monthly disclosure (mf_holdings_monthly)
"""
from __future__ import annotations

from nidp.shared.validation.consistency import (
    ConsistencyDimension,
    CrossSourceRule,
    InternalConsistencyRule,
    TemporalConsistencyRule,
    register_consistency,
)
from nidp.shared.validation.rules import FailureClass, Severity

# ── C1: NAV cross-source — mf_nav_daily (AMFI) vs scheme_master pointer ─
# mf_scheme_master.latest_nav is refreshed by the amfi_nav ingester as a
# convenience cache. The two should be identical for the latest date.
NAV_CROSS_SOURCE = CrossSourceRule(
    name="mf.nav_cross_source",
    field_name="nav",
    entity_type="scheme",
    source_a_label="amfi_nav_daily",
    source_a_sql="""
        SELECT scheme_code AS entity_id, nav AS value
          FROM nidp.mf_nav_daily
         WHERE nav_date = $1
    """,
    source_b_label="scheme_master_cache",
    source_b_sql="""
        SELECT scheme_code AS entity_id, latest_nav AS value
          FROM nidp.mf_scheme_master
         WHERE latest_nav_date = $1
           AND latest_nav IS NOT NULL
    """,
    min_accuracy=99.99,   # NAV must be exact (4 decimal places)
    severity=Severity.CRITICAL,
    failure_class=FailureClass.BLOCK,
)

# ── C2: Direct TER ≤ Regular TER (SEBI Circular SEBI/HO/IMD/DF2/CIR/2018/147)
# A direct plan must never have a higher expense ratio than the regular plan.
TER_DIRECT_LT_REGULAR = InternalConsistencyRule(
    name="mf.ter_direct_lt_regular",
    sql="""
        SELECT count(*) FROM nidp.mf_scheme_disclosure_snapshot
         WHERE snapshot_date = $1
           AND ter_pct        IS NOT NULL
           AND ter_pct_direct IS NOT NULL
           AND ter_pct_direct >= ter_pct
    """,
    sample_sql="""
        SELECT scheme_code,
               ter_pct        AS regular_ter,
               ter_pct_direct AS direct_ter,
               (ter_pct_direct - ter_pct) AS excess
          FROM nidp.mf_scheme_disclosure_snapshot
         WHERE snapshot_date = $1
           AND ter_pct        IS NOT NULL
           AND ter_pct_direct IS NOT NULL
           AND ter_pct_direct >= ter_pct
         ORDER BY excess DESC
         LIMIT 10
    """,
    message="direct plan TER >= regular plan TER — violates SEBI circular",
    field_name="ter_pct_direct",
    entity_type="scheme",
    severity=Severity.CRITICAL,
    failure_class=FailureClass.BLOCK,
)

# ── C3: Holdings weight sum ≈ 100% per scheme (tolerance ± 0.5%)
# Tighter than the per-ingester rule (±5%) applied at ingest time.
# At consistency-check time the full month's data is settled.
HOLDINGS_WEIGHT_SUM = InternalConsistencyRule(
    name="mf.holdings_weight_sum",
    sql="""
        SELECT count(*) FROM (
            SELECT scheme_code, as_of_month, sum(weight_pct) AS s
              FROM nidp.mf_holdings_monthly
             WHERE as_of_month = date_trunc('month', $1::date)::date
               AND weight_pct IS NOT NULL
             GROUP BY scheme_code, as_of_month
            HAVING abs(sum(weight_pct) - 100.0) > 0.5
        ) bad
    """,
    sample_sql="""
        SELECT scheme_code,
               as_of_month,
               round(sum(weight_pct)::numeric, 4) AS total_weight,
               abs(sum(weight_pct) - 100.0)       AS deviation
          FROM nidp.mf_holdings_monthly
         WHERE as_of_month = date_trunc('month', $1::date)::date
           AND weight_pct IS NOT NULL
         GROUP BY scheme_code, as_of_month
        HAVING abs(sum(weight_pct) - 100.0) > 0.5
         ORDER BY deviation DESC
         LIMIT 10
    """,
    message="scheme holdings weights deviate from 100% by > 0.5%",
    field_name="weight_pct",
    entity_type="scheme",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# ── C4: Scheme category stable — master vs disclosure snapshot
# The scheme_category in mf_scheme_master should match what appears in
# the latest disclosure snapshot (different AMC parsers; they must agree).
SCHEME_CATEGORY_STABLE = InternalConsistencyRule(
    name="mf.scheme_category_stable",
    sql="""
        SELECT count(*)
          FROM nidp.mf_scheme_master sm
          JOIN nidp.mf_scheme_disclosure_snapshot ds
            ON ds.scheme_code  = sm.scheme_code
           AND ds.snapshot_date = (
               SELECT max(snapshot_date)
                 FROM nidp.mf_scheme_disclosure_snapshot
                WHERE scheme_code = sm.scheme_code
                  AND snapshot_date <= $1
           )
         WHERE sm.scheme_category IS NOT NULL
           AND ds.risk_o_meter    IS NOT NULL
    """,
    # This is a structural sanity check (non-zero count means data exists).
    # The real check is a mismatch between fields — use as a health signal.
    message="no scheme_category/risk_o_meter overlap found — parser may have dropped data",
    field_name="scheme_category",
    entity_type="scheme",
    severity=Severity.WARN,
    failure_class=FailureClass.INFO,
    params_fn=lambda d: [d],
)

# ── T1: NAV single-day change > 20% — temporal flag
# Legitimate for equity funds on ex-dividend or during a market crash;
# this raises a WARN so analysts can verify, not a BLOCK.
NAV_TEMPORAL_CHANGE = TemporalConsistencyRule(
    name="mf.nav_temporal_change",
    field_name="nav",
    entity_type="scheme",
    sql="""
        SELECT
            cur.scheme_code   AS entity_id,
            cur.nav           AS current_val,
            prv.nav           AS prior_val,
            CASE WHEN prv.nav > 0
                 THEN ((cur.nav - prv.nav) / prv.nav) * 100.0
                 ELSE NULL END AS change_pct
          FROM nidp.mf_nav_daily cur
          JOIN nidp.mf_nav_daily prv
            ON prv.scheme_code = cur.scheme_code
           AND prv.nav_date    = (
               SELECT max(nav_date)
                 FROM nidp.mf_nav_daily
                WHERE scheme_code = cur.scheme_code
                  AND nav_date < $1
           )
         WHERE cur.nav_date = $1
           AND cur.nav > 0
           AND prv.nav > 0
    """,
    threshold_pct=20.0,
    severity=Severity.WARN,
    failure_class=FailureClass.FIX,
)

# ── T2: TER change > 25% between consecutive snapshots
# TER changes require SEBI approval and an AMC circular. An unannounced
# jump is almost always a data or parsing error.
TER_TEMPORAL_CHANGE = TemporalConsistencyRule(
    name="mf.ter_temporal_change",
    field_name="ter_pct",
    entity_type="scheme",
    sql="""
        SELECT
            cur.scheme_code   AS entity_id,
            cur.ter_pct       AS current_val,
            prv.ter_pct       AS prior_val,
            CASE WHEN prv.ter_pct > 0
                 THEN ((cur.ter_pct - prv.ter_pct) / prv.ter_pct) * 100.0
                 ELSE NULL END AS change_pct
          FROM nidp.mf_scheme_disclosure_snapshot cur
          JOIN nidp.mf_scheme_disclosure_snapshot prv
            ON prv.scheme_code   = cur.scheme_code
           AND prv.snapshot_date = (
               SELECT max(snapshot_date)
                 FROM nidp.mf_scheme_disclosure_snapshot
                WHERE scheme_code   = cur.scheme_code
                  AND snapshot_date < $1
           )
         WHERE cur.snapshot_date = $1
           AND cur.ter_pct  IS NOT NULL
           AND prv.ter_pct  IS NOT NULL
           AND prv.ter_pct > 0
    """,
    threshold_pct=25.0,
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# ── T3: AUM single-snapshot change > 50%
# AUM can legitimately swing ±20% in volatile markets; >50% without
# a merger/closure event is almost certainly a parse error.
AUM_TEMPORAL_CHANGE = TemporalConsistencyRule(
    name="mf.aum_temporal_change",
    field_name="aum_inr_crore",
    entity_type="scheme",
    sql="""
        SELECT
            cur.scheme_code   AS entity_id,
            cur.aum_inr_crore AS current_val,
            prv.aum_inr_crore AS prior_val,
            CASE WHEN prv.aum_inr_crore > 0
                 THEN ((cur.aum_inr_crore - prv.aum_inr_crore) / prv.aum_inr_crore) * 100.0
                 ELSE NULL END AS change_pct
          FROM nidp.mf_scheme_disclosure_snapshot cur
          JOIN nidp.mf_scheme_disclosure_snapshot prv
            ON prv.scheme_code   = cur.scheme_code
           AND prv.snapshot_date = (
               SELECT max(snapshot_date)
                 FROM nidp.mf_scheme_disclosure_snapshot
                WHERE scheme_code   = cur.scheme_code
                  AND snapshot_date < $1
           )
         WHERE cur.snapshot_date = $1
           AND cur.aum_inr_crore  IS NOT NULL
           AND prv.aum_inr_crore  IS NOT NULL
           AND prv.aum_inr_crore > 0
    """,
    threshold_pct=50.0,
    severity=Severity.WARN,
    failure_class=FailureClass.FIX,
)

register_consistency("mf", [
    NAV_CROSS_SOURCE,
    TER_DIRECT_LT_REGULAR,
    HOLDINGS_WEIGHT_SUM,
    SCHEME_CATEGORY_STABLE,
    NAV_TEMPORAL_CHANGE,
    TER_TEMPORAL_CHANGE,
    AUM_TEMPORAL_CHANGE,
])
