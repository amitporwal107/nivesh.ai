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
    ConsistencyDimension,
    ConsistencyFinding,
    ConsistencyRule,
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

# ── C2: Shareholding sum, by each source's own definition of "public"
# The two sources mean different things by public_pct (measured on staging, Jul–Oct 2026 filings):
#   * NSE_SHP (the NSE SHP filing): public = every non-promoter holder, EXCEPT the "non-promoter non-public" category
#     (shares underlying depository receipts, employee benefit trusts), which has no column here. So
#     promoter + public may be BELOW 100 by that category's size, and may never be ABOVE it.
#   * screener_in: public = retail and others only; FII, DII and government are separate columns. So
#     promoter + fii + dii + govt + public = 100 (424 of 453 filings did, within 0.5pp).
# The rule used to test promoter + public = 100 for both, which failed 85% of screener_in filings every day and rejected
# the whole equity day. Only each symbol's LATEST filing per source in the window counts, so a superseded filing stops
# failing the rule once a newer one arrives.
_SHAREHOLDING_LATEST = """
    SELECT DISTINCT ON (symbol, source)
           symbol, source, period_end, promoter_pct, public_pct, fii_pct, dii_pct, govt_holding_pct
      FROM nidp.shareholding_pattern
     WHERE period_end >= ($1::date - INTERVAL '95 days')
       AND period_end <= $1::date
       AND promoter_pct IS NOT NULL
       AND public_pct   IS NOT NULL
     ORDER BY symbol, source, period_end DESC
"""
_SHAREHOLDING_TOTAL = """
    CASE WHEN source = 'screener_in'
         THEN promoter_pct + coalesce(fii_pct, 0) + coalesce(dii_pct, 0) + coalesce(govt_holding_pct, 0) + public_pct
         ELSE promoter_pct + public_pct END
"""
_SHAREHOLDING_BAD = """
    CASE WHEN source = 'screener_in'
         THEN abs(promoter_pct + coalesce(fii_pct, 0) + coalesce(dii_pct, 0) + coalesce(govt_holding_pct, 0)
                  + public_pct - 100.0) > 0.5
         ELSE promoter_pct + public_pct > 100.5 END
"""
SHAREHOLDING_SUM = InternalConsistencyRule(
    name="equity.shareholding_sum",
    sql=f"""
        SELECT count(*) FROM ({_SHAREHOLDING_LATEST}) latest
         WHERE {_SHAREHOLDING_BAD}
    """,
    sample_sql=f"""
        SELECT symbol, source, period_end, promoter_pct, public_pct, fii_pct, dii_pct, govt_holding_pct,
               round(({_SHAREHOLDING_TOTAL})::numeric, 4) AS total
          FROM ({_SHAREHOLDING_LATEST}) latest
         WHERE {_SHAREHOLDING_BAD}
         ORDER BY abs(({_SHAREHOLDING_TOTAL}) - 100.0) DESC
         LIMIT 10
    """,
    message=("shareholding categories do not add up (NSE: promoter + public above 100.5%; "
             "screener_in: promoter + FII + DII + govt + public not within 0.5pp of 100%)"),
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
        SELECT count(*) FROM nidp.delivery_data
         WHERE as_of_date = $1
           AND (deliverable_qty > traded_qty
             OR deliverable_qty < 0
             OR traded_qty       < 0)
    """,
    sample_sql="""
        SELECT symbol, traded_qty, deliverable_qty,
               round((deliverable_qty::numeric / NULLIF(traded_qty,0) * 100), 2) AS delivery_pct
          FROM nidp.delivery_data
         WHERE as_of_date = $1
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

# Corporate actions that change the price base on their EX-date (the day the price adjusts). NSE adjusts the day's
# prev_close for these, so a move measured against prev_close is already corrected; they are excluded anyway, and the
# continuity rule below must not call NSE's adjusted base a mismatch.
_PRICE_BASE_ACTIONS = "('SPLIT','BONUS','RIGHTS','DEMERGER','CAPITAL_REDUCTION','DISTRIBUTION')"

# ── T1: Price single-day change > 20% — temporal flag
# NSE price bands cap most stocks at ±20% of the day's base price. The base is the row's own NSE `prev_close` (the
# security's previous close, carried across a series switch EQ ↔ BE and across days it did not trade). The rule used
# to compare against the last stored row of the SAME series, which can be months old (GSLSU: 23 Feb vs 26 Oct), so most
# of its findings were artefacts. Rights entitlements (-RE, -RE1, …) and listing days are excluded: neither has a band.
PRICE_TEMPORAL_CHANGE = TemporalConsistencyRule(
    name="equity.price_temporal_change",
    field_name="close_price",
    entity_type="symbol",
    sql=f"""
        SELECT
            cur.symbol      AS entity_id,
            cur.close_price AS current_val,
            cur.prev_close  AS prior_val,
            ((cur.close_price - cur.prev_close) / cur.prev_close) * 100.0 AS change_pct
          FROM nidp.prices_eod cur
         WHERE cur.as_of_date = $1
           AND cur.series IN ('EQ','BE')
           AND cur.close_price > 0
           AND cur.prev_close  > 0
           -- Rights entitlements (-RE, -RE1, …) have no price band.
           AND cur.symbol !~ '-RE[0-9]*$'
           -- A listing or relisting day: prev_close is the issue / base price and no band applies to price discovery
           -- (staging 12–28 Oct: TONBO, JPL, TRIVENIPT, SHIVAM-RE1 were all their first day in the store).
           AND EXISTS (
               SELECT 1 FROM nidp.prices_eod p
                WHERE p.symbol = cur.symbol
                  AND p.as_of_date <  $1
                  AND p.as_of_date >= $1::date - 30
           )
           AND NOT EXISTS (
               SELECT 1 FROM nidp.corporate_actions ca
                WHERE ca.symbol      = cur.symbol
                  AND ca.ex_date     = $1
                  AND ca.action_type IN {_PRICE_BASE_ACTIONS}
           )
    """,
    threshold_pct=20.0,
    severity=Severity.WARN,
    failure_class=FailureClass.FIX,
)


class PrevCloseContinuityRule(ConsistencyRule):
    """NSE's own previous close against the close we stored for the security's previous trading day.

    The bhavcopy carries `prev_close` for every row; it must equal the last close we hold for that security (any of EQ,
    BE, BZ, so a series switch is not a break) within the last 30 days. A mismatch with no price-base corporate action
    on the ex-date means one of the two days is wrong in our store (a missed split or consolidation, or a bad row). On
    staging, 12–27 Oct, it was silent on 2,7xx securities a day except three real breaks (CCAVENUE 13.83 stored vs
    138.30 NSE, 19 Oct). One finding per security.
    """
    name = "equity.prev_close_continuity"
    dimension = ConsistencyDimension.CROSS_SOURCE
    severity = Severity.ERROR
    failure_class = FailureClass.FIX
    # Prices are quoted to 0.05 (tick) or 0.01; anything within a paisa, or 0.01% of the price, is the same close.
    ABS_TOLERANCE = 0.011
    REL_TOLERANCE = 0.0001
    LOOKBACK_DAYS = 30

    SQL = f"""
        SELECT cur.symbol, cur.prev_close AS nse_prev_close, prior.close_price AS stored_close,
               prior.as_of_date AS stored_date
          FROM nidp.prices_eod cur
          JOIN LATERAL (
               SELECT p.close_price, p.as_of_date
                 FROM nidp.prices_eod p
                WHERE p.symbol = cur.symbol
                  AND p.series IN ('EQ','BE','BZ')
                  AND p.as_of_date <  $1
                  AND p.as_of_date >= $1::date - $2::int
                ORDER BY p.as_of_date DESC
                LIMIT 1
          ) prior ON TRUE
         WHERE cur.as_of_date = $1
           AND cur.series IN ('EQ','BE','BZ')
           AND cur.prev_close > 0
           AND prior.close_price > 0
           AND abs(prior.close_price - cur.prev_close) > greatest($3::numeric, cur.prev_close * $4::numeric)
           AND NOT EXISTS (
               SELECT 1 FROM nidp.corporate_actions ca
                WHERE ca.symbol      = cur.symbol
                  AND ca.ex_date     = $1
                  AND ca.action_type IN {_PRICE_BASE_ACTIONS}
           )
         ORDER BY cur.symbol
    """

    async def check(self, conn, target_date):
        rows = await conn.fetch(self.SQL, target_date, self.LOOKBACK_DAYS, self.ABS_TOLERANCE, self.REL_TOLERANCE)
        findings: list[ConsistencyFinding] = []
        for r in rows:
            nse, ours = float(r["nse_prev_close"]), float(r["stored_close"])
            dev = abs(ours - nse) / nse * 100.0
            findings.append(ConsistencyFinding(
                rule_name=self.name,
                dimension=self.dimension,
                severity=self.severity,
                failure_class=self.failure_class,
                message=(f"prev_close break for {r['symbol']}: NSE prev_close {nse} vs our close {ours} on "
                         f"{r['stored_date']} (deviation {dev:.2f}%) with no price-base corporate action"),
                entity_type="symbol",
                entity_id=str(r["symbol"]),
                field_name="close_price",
                source_a="nidp.prices_eod (stored prior close)",
                value_a=str(ours),
                source_b="NSE bhavcopy prev_close",
                value_b=str(nse),
                deviation_pct=round(dev, 4),
            ))
        return findings


PREV_CLOSE_CONTINUITY = PrevCloseContinuityRule()

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
    PREV_CLOSE_CONTINUITY,
    PROMOTER_QOQ_CHANGE,
    FII_QOQ_CHANGE,
    PRICE_IMMUTABILITY,
])
