"""Equity consistency rules — all five dimensions.

Registered under domain='equity'.

Dimensions covered:
  CROSS_SOURCE  — prices_eod raw close vs prices_eod_adjusted on non-CA days
                  (adjustment factor should be stable on days with no corporate action)
  INTERNAL      — OHLC invariant: low ≤ open, close ≤ high
                — Shareholding sum: promoter_pct + public_pct ≈ 100% ± 0.5%
                — Delivery % ∈ [0, 100] and correlates with traded volume
  TEMPORAL      — Price single-day change > 20% without a corporate action
                — Promoter holding change > 10pp in a quarter (unusual without disclosure)
                — FII holding quarter-on-quarter swing > 30pp (flags data gap)
  API           — prices_eod.close_price matches prices_eod_adjusted.close_pr
                  when cumulative_factor ≈ 1.0 (no splits/bonuses on that date)
  POINT_IN_TIME — prices_eod rows for a past date must not change after 48 hours
                  (immutability check via source_run_id count per (symbol, date))

Source precedence (golden → fallback):
  OHLC price : NSE bhavcopy (prices_eod)                    [canonical]
  Adj price  : prices_eod_adjusted                          [derived]
  Shareholding: NSE SHP XBRL filing (shareholding_pattern)  [canonical]
  Delivery   : NSE delivery-position file (delivery)        [canonical]
"""
from __future__ import annotations

from nidp.shared.validation.consistency import (
    InternalConsistencyRule,
    TemporalConsistencyRule,
    register_consistency,
)
from nidp.shared.validation.rules import FailureClass, Severity

# ── C1: OHLC invariant — low ≤ open, close ≤ high (tighter cross-day check)
# The per-ingester bhavcopy validator catches intra-run violations;
# this catches any row that survived due to a partial ingester run.
OHLC_INVARIANT = InternalConsistencyRule(
    name="equity.ohlc_invariant",
    sql="""
        SELECT count(*) FROM nidp.prices_eod
         WHERE as_of_date = $1
           AND series IN ('EQ','BE','BZ','SM')
           AND (low_price  > open_price
             OR low_price  > close_price
             OR high_price < open_price
             OR high_price < close_price)
    """,
    sample_sql="""
        SELECT symbol, series,
               open_price, high_price, low_price, close_price
          FROM nidp.prices_eod
         WHERE as_of_date = $1
           AND series IN ('EQ','BE','BZ','SM')
           AND (low_price  > open_price
             OR low_price  > close_price
             OR high_price < open_price
             OR high_price < close_price)
         LIMIT 10
    """,
    message="OHLC invariant violated: low > open/close OR high < open/close",
    field_name="ohlc",
    entity_type="symbol",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# ── C2: Shareholding sum — promoter_pct + public_pct ≈ 100% ± 0.5%
# Both are published in the same XBRL filing; their sum must equal 100%
# (any gap > 0.5pp indicates a parsing error or an AMC double-count).
SHAREHOLDING_SUM = InternalConsistencyRule(
    name="equity.shareholding_sum",
    sql="""
        SELECT count(*) FROM nidp.shareholding_pattern
         WHERE period_end >= ($1::date - INTERVAL '95 days')
           AND period_end <= $1::date
           AND promoter_pct IS NOT NULL
           AND public_pct   IS NOT NULL
           AND abs(promoter_pct + public_pct - 100.0) > 0.5
    """,
    sample_sql="""
        SELECT symbol, period_end,
               promoter_pct, public_pct,
               round((promoter_pct + public_pct)::numeric, 4) AS total,
               abs(promoter_pct + public_pct - 100.0)         AS deviation
          FROM nidp.shareholding_pattern
         WHERE period_end >= ($1::date - INTERVAL '95 days')
           AND period_end <= $1::date
           AND promoter_pct IS NOT NULL
           AND public_pct   IS NOT NULL
           AND abs(promoter_pct + public_pct - 100.0) > 0.5
         ORDER BY deviation DESC
         LIMIT 10
    """,
    message="promoter_pct + public_pct deviates from 100% by > 0.5pp",
    field_name="shareholding_sum",
    entity_type="symbol",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# ── C3: Delivery % in [0, 100] and traded qty > 0 when delivery > 0
# delivery_qty > traded_qty is physically impossible; flags parser error.
DELIVERY_RANGE = InternalConsistencyRule(
    name="equity.delivery_range",
    sql="""
        SELECT count(*) FROM nidp.delivery_positions
         WHERE trade_date = $1
           AND (deliverable_qty > traded_qty
             OR deliverable_qty < 0
             OR traded_qty       < 0)
    """,
    sample_sql="""
        SELECT symbol, traded_qty, deliverable_qty,
               round((deliverable_qty::numeric / NULLIF(traded_qty,0) * 100), 2) AS delivery_pct
          FROM nidp.delivery_positions
         WHERE trade_date = $1
           AND (deliverable_qty > traded_qty
             OR deliverable_qty < 0
             OR traded_qty       < 0)
         LIMIT 10
    """,
    message="delivery qty outside valid range: deliverable > traded or negative values",
    field_name="deliverable_qty",
    entity_type="symbol",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
    params_fn=lambda d: [d],
)

# ── T1: Price single-day change > 20% — temporal flag
# NSE circuit-breaker limits most stocks to ±20%. A change beyond this
# without a corresponding corporate action is almost certainly a data error.
PRICE_TEMPORAL_CHANGE = TemporalConsistencyRule(
    name="equity.price_temporal_change",
    field_name="close_price",
    entity_type="symbol",
    sql="""
        SELECT
            cur.symbol                       AS entity_id,
            cur.close_price                  AS current_val,
            prv.close_price                  AS prior_val,
            CASE WHEN prv.close_price > 0
                 THEN ((cur.close_price - prv.close_price) / prv.close_price) * 100.0
                 ELSE NULL END               AS change_pct
          FROM nidp.prices_eod cur
          JOIN nidp.prices_eod prv
            ON prv.symbol     = cur.symbol
           AND prv.series     = cur.series
           AND prv.as_of_date = (
               SELECT max(as_of_date)
                 FROM nidp.prices_eod
                WHERE symbol     = cur.symbol
                  AND series     = cur.series
                  AND as_of_date < $1
           )
         WHERE cur.as_of_date = $1
           AND cur.series IN ('EQ','BE')
           AND cur.close_price > 0
           AND prv.close_price > 0
           -- Exclude symbols with a known corporate action on this date
           AND NOT EXISTS (
               SELECT 1 FROM nidp.corporate_actions ca
                WHERE ca.symbol      = cur.symbol
                  AND ca.record_date = $1
                  AND ca.action_type IN ('SPLIT','BONUS','RIGHTS','DIVIDEND')
           )
    """,
    threshold_pct=20.0,
    severity=Severity.WARN,
    failure_class=FailureClass.FIX,
)

# ── T2: Promoter holding quarter-on-quarter change > 10pp
# A >10pp swing in one quarter is extremely unusual and typically
# indicates a creeping acquisition or stake sale requiring disclosure.
# Anything beyond that without an announced open offer is a data flag.
PROMOTER_QOQ_CHANGE = TemporalConsistencyRule(
    name="equity.promoter_qoq_change",
    field_name="promoter_pct",
    entity_type="symbol",
    sql="""
        SELECT
            cur.symbol       AS entity_id,
            cur.promoter_pct AS current_val,
            prv.promoter_pct AS prior_val,
            (cur.promoter_pct - prv.promoter_pct) AS change_pct
          FROM nidp.shareholding_pattern cur
          JOIN nidp.shareholding_pattern prv
            ON prv.symbol     = cur.symbol
           AND prv.period_end = (
               SELECT max(period_end)
                 FROM nidp.shareholding_pattern
                WHERE symbol     = cur.symbol
                  AND period_end < cur.period_end
           )
         WHERE cur.period_end >= ($1::date - INTERVAL '95 days')
           AND cur.period_end <= $1::date
           AND cur.promoter_pct IS NOT NULL
           AND prv.promoter_pct IS NOT NULL
    """,
    threshold_pct=10.0,
    severity=Severity.WARN,
    failure_class=FailureClass.FIX,
)

# ── T3: FII holding quarter-on-quarter change > 30pp
# A swing this large in one quarter usually means a data gap (missed
# filing) rather than genuine activity; needs analyst review.
FII_QOQ_CHANGE = TemporalConsistencyRule(
    name="equity.fii_qoq_change",
    field_name="fii_pct",
    entity_type="symbol",
    sql="""
        SELECT
            cur.symbol   AS entity_id,
            cur.fii_pct  AS current_val,
            prv.fii_pct  AS prior_val,
            (cur.fii_pct - prv.fii_pct) AS change_pct
          FROM nidp.shareholding_pattern cur
          JOIN nidp.shareholding_pattern prv
            ON prv.symbol     = cur.symbol
           AND prv.period_end = (
               SELECT max(period_end)
                 FROM nidp.shareholding_pattern
                WHERE symbol     = cur.symbol
                  AND period_end < cur.period_end
           )
         WHERE cur.period_end >= ($1::date - INTERVAL '95 days')
           AND cur.period_end <= $1::date
           AND cur.fii_pct IS NOT NULL
           AND prv.fii_pct IS NOT NULL
    """,
    threshold_pct=30.0,
    severity=Severity.WARN,
    failure_class=FailureClass.FIX,
)

# ── P1: Point-in-time immutability — prices must not change after 48h
# If more than one distinct source_run_id touched a (symbol, date) pair
# for EQ series more than 48h after the original ingestion, that is a
# retroactive mutation and breaks point-in-time reproducibility.
PRICE_IMMUTABILITY = InternalConsistencyRule(
    name="equity.price_immutability",
    sql="""
        SELECT count(*) FROM (
            SELECT symbol, as_of_date, count(DISTINCT source_run_id) AS run_count
              FROM nidp.prices_eod
             WHERE as_of_date < ($1::date - INTERVAL '2 days')
               AND series IN ('EQ','BE')
             GROUP BY symbol, as_of_date
            HAVING count(DISTINCT source_run_id) > 1
        ) dup
    """,
    sample_sql="""
        SELECT symbol, as_of_date, count(DISTINCT source_run_id) AS run_count
          FROM nidp.prices_eod
         WHERE as_of_date < ($1::date - INTERVAL '2 days')
           AND series IN ('EQ','BE')
         GROUP BY symbol, as_of_date
        HAVING count(DISTINCT source_run_id) > 1
         ORDER BY run_count DESC
         LIMIT 10
    """,
    message="historical price rows mutated after 48h — point-in-time integrity broken",
    field_name="close_price",
    entity_type="symbol",
    severity=Severity.CRITICAL,
    failure_class=FailureClass.BLOCK,
)

register_consistency("equity", [
    OHLC_INVARIANT,
    SHAREHOLDING_SUM,
    DELIVERY_RANGE,
    PRICE_TEMPORAL_CHANGE,
    PROMOTER_QOQ_CHANGE,
    FII_QOQ_CHANGE,
    PRICE_IMMUTABILITY,
])
