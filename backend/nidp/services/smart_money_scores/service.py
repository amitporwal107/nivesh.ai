"""Smart Money accumulation/distribution component for the existing stock-selection engine.

Architecture decision (2026-10-22): this is an ADDITIONAL COMPONENT, not a second engine. It
writes only nidp.smart_money_scores_daily. It never writes nidp.v3_stock_scores_daily and never
changes a user-visible score; nidp.v_smart_money_shadow_rank is how its effect on ranking is read
before anyone promotes it into the production composite.

Scope: class-A evidence (disclosed mutual-fund holdings change) from nidp.mf_holdings_deltas.
FII/DII QoQ changes and delivery/volume proxies are deliberately NOT scored here — governance.py
already scores the former inside the fundamental pillar and the technical pillar already scores
the latter, so including them would give the same evidence two votes. See migration 166.

Five sub-signals, each normalised to 0-100 by percentile rank across the symbols that have
evidence on that date, then combined over whichever are present:

  breadth      net share of schemes increasing vs reducing      — is it broad or one fund?
  amc_breadth  count of independent AMCs increasing             — breadth that is not one AMC's
  persistence  months with net accumulation / months observed    — sustained or a single month?
  magnitude    net share change vs prior holding                 — size, from share COUNT only
  conviction   summed portfolio-weight change in pp              — raising weight, not riding inflow

Percentile rank is used because the raw units (scheme counts, share counts, pp) are not
comparable and have long tails; it is a documented, reproducible normalisation, and it is
explicitly relative to the evidence-bearing set on that date, which `components` records.

Distribution is computed as its own score from the mirrored signals, never as 100 - accumulation:
a stock can show both (some schemes adding, others exiting) and the source requirement demands the
two be displayed separately.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date, timedelta
from typing import Optional

from nidp.shared.logging_setup import bind_context, setup_logging
from nidp.shared.storage.job_log import JobRun
from nidp.shared.storage.pg import close_pool, get_pool

logger = logging.getLogger(__name__)

SERVICE_NAME = "smart_money_scores"

# Bumped whenever the sub-signals or their weights change, so a stored row can be reproduced.
CONFIG_VERSION = "sm-component-v2"   # v2: breadth counts funds, not plan variants (migration 177)

# Default disclosure months to look across. 3 is the shortest window in which "persistence" means
# anything; the source requirement's 1/3/6/12 lookbacks are served by re-running with --lookback.
DEFAULT_LOOKBACK = 3

# SEBI requires monthly portfolio disclosure within 10 days of month end, and the sources we
# discover through lag that by a day or two, so a month is treated as first knowable at
# month-end + 12 days. Used only by --month to place a historical scoring date.
DISCLOSURE_LAG_DAYS = 12

# Sub-signal weights within the component. Hypotheses, not tuned — the component itself is in
# shadow mode precisely so these can be argued with before anything depends on them.
_WEIGHTS = {
    "breadth":     0.25,
    "amc_breadth": 0.20,
    "persistence": 0.20,
    "magnitude":   0.20,
    "conviction":  0.15,
}


_UPSERT_SQL = f"""
WITH months AS (
    -- The lookback window: the most recent disclosure months that actually carry validated
    -- evidence. Picking from the data rather than from the calendar means a month the AMCs have
    -- not published yet cannot silently shorten the window.
    SELECT DISTINCT current_month
      FROM nidp.mf_holdings_deltas
     WHERE validation_status = 'validated' AND current_month <= $2::date
       -- Point-in-time mode: a month counts only once its comparison was actually knowable, and
       -- only when both sides carry a real publication date (migration 172). Without this a
       -- historical scoring date reads changes weeks before anyone could have seen them.
       AND (NOT $6::bool OR (known_from IS NOT NULL
                             AND known_from::date <= $1::date
                             AND known_from_basis = 'published'))
     ORDER BY current_month DESC
     LIMIT $3
),
-- Per ISIN per month, so persistence can be measured before collapsing the window.
per_month AS (
    SELECT d.security_isin,
           d.current_month,
           -- FUND counts, not scheme-code counts. One fund's disclosure fans out to every
           -- plan variant it runs (Regular/Direct x Growth/IDCW), each an identical copy, so
           -- counting rows counted the same decision 2.5-3.4x over and biased breadth toward
           -- AMCs with more variants (Tata 13x vs Kotak 3.4x). Plan variants share
           -- (amc, previous_shares, current_shares) exactly, which collapses them. See
           -- migration 177.
           count(DISTINCT (coalesce(nullif(sm.amc_id,''), d.scheme_code),
                           d.previous_shares, d.current_shares))
               FILTER (WHERE d.change_class IN ('increase','new'))                  AS inc,
           count(DISTINCT (coalesce(nullif(sm.amc_id,''), d.scheme_code),
                           d.previous_shares, d.current_shares))
               FILTER (WHERE d.change_class IN ('decrease','possible_exit'))        AS red,
           count(DISTINCT (coalesce(nullif(sm.amc_id,''), d.scheme_code),
                           d.previous_shares, d.current_shares))
               FILTER (WHERE d.change_class = 'new')                                AS new_pos,
           count(DISTINCT (coalesce(nullif(sm.amc_id,''), d.scheme_code),
                           d.previous_shares, d.current_shares))
               FILTER (WHERE d.change_class = 'possible_exit')                      AS exits,
           count(DISTINCT coalesce(nullif(sm.amc_id,''), 'unattributed:'||d.scheme_code))
               FILTER (WHERE d.change_class IN ('increase','new'))                 AS amcs_inc,
           sum(d.shares_delta)                                                     AS net_shares,
           sum(d.previous_shares)                                                  AS prev_shares,
           sum(d.weight_delta_pp)                                                  AS weight_pp
      FROM nidp.mf_holdings_deltas d
      JOIN months m ON m.current_month = d.current_month
      LEFT JOIN nidp.mf_scheme_master sm ON sm.scheme_code = d.scheme_code
     WHERE d.validation_status = 'validated'
       AND (NOT $6::bool OR (d.known_from IS NOT NULL
                             AND d.known_from::date <= $1::date
                             AND d.known_from_basis = 'published'))
     GROUP BY d.security_isin, d.current_month
),
agg AS (
    SELECT security_isin,
           sum(inc)::int                                            AS schemes_increasing,
           sum(red)::int                                            AS schemes_reducing,
           sum(new_pos)::int                                        AS schemes_new,
           sum(exits)::int                                          AS schemes_exited,
           max(amcs_inc)::int                                       AS amcs_increasing,
           sum(net_shares)                                          AS net_shares_delta,
           sum(prev_shares)                                         AS prev_shares,
           sum(weight_pp)                                           AS weight_delta_pp,
           count(*)::int                                            AS months_observed,
           count(*) FILTER (WHERE net_shares > 0)::int               AS months_accumulating,
           count(*) FILTER (WHERE net_shares < 0)::int               AS months_distributing,
           max(current_month)                                       AS latest_reporting_date
      FROM per_month
     GROUP BY security_isin
),
-- Map to the engine's symbol space. Without a symbol the component cannot join the rest of the
-- engine, so unmapped ISINs are dropped here (they remain visible in the delta/breadth layer).
mapped AS (
    SELECT a.*, sm.symbol
      FROM agg a
      JOIN nidp.sector_master sm ON sm.isin = a.security_isin
     WHERE sm.symbol IS NOT NULL
),
raw AS (
    SELECT m.*,
           -- Net scheme breadth, bounded -1..1. Bounded first so one heavily-held name cannot
           -- dominate the percentile purely through scheme count.
           CASE WHEN (m.schemes_increasing + m.schemes_reducing) > 0
                THEN (m.schemes_increasing - m.schemes_reducing)::numeric
                     / (m.schemes_increasing + m.schemes_reducing)
           END AS breadth_raw,
           CASE WHEN m.months_observed > 0
                THEN m.months_accumulating::numeric / m.months_observed END AS persistence_raw,
           CASE WHEN m.months_observed > 0
                THEN m.months_distributing::numeric / m.months_observed END AS persistence_dist_raw,
           -- Share-count change relative to the prior holding. NULL when the prior holding was
           -- zero (no meaningful denominator) — the source requirement's explicit rule.
           CASE WHEN m.prev_shares > 0 THEN m.net_shares_delta / m.prev_shares END AS magnitude_raw,
           m.weight_delta_pp AS conviction_raw
      FROM mapped m
),
-- Percentile-normalise each sub-signal across the evidence-bearing set for this date.
norm AS (
    SELECT r.*,
           (100 * percent_rank() OVER (ORDER BY r.breadth_raw     NULLS FIRST))::numeric AS breadth_s,
           (100 * percent_rank() OVER (ORDER BY r.amcs_increasing NULLS FIRST))::numeric AS amc_s,
           (100 * percent_rank() OVER (ORDER BY r.persistence_raw NULLS FIRST))::numeric AS persistence_s,
           (100 * percent_rank() OVER (ORDER BY r.magnitude_raw   NULLS FIRST))::numeric AS magnitude_s,
           (100 * percent_rank() OVER (ORDER BY r.conviction_raw  NULLS FIRST))::numeric AS conviction_s,
           -- Mirrored signals for the distribution score.
           (100 * percent_rank() OVER (ORDER BY -r.breadth_raw        NULLS FIRST))::numeric AS breadth_d,
           (100 * percent_rank() OVER (ORDER BY r.schemes_exited      NULLS FIRST))::numeric AS exit_d,
           (100 * percent_rank() OVER (ORDER BY r.persistence_dist_raw NULLS FIRST))::numeric AS persistence_d,
           (100 * percent_rank() OVER (ORDER BY -r.magnitude_raw      NULLS FIRST))::numeric AS magnitude_d,
           (100 * percent_rank() OVER (ORDER BY -r.conviction_raw     NULLS FIRST))::numeric AS conviction_d
      FROM raw r
),
scored AS (
    SELECT n.*,
           -- Weighted mean over the sub-signals that are present, re-normalised by the weight
           -- actually available. A NULL sub-signal contributes nothing and takes no weight;
           -- it is never treated as a zero.
           (  coalesce(n.breadth_s     * {_WEIGHTS['breadth']},     0)
            + coalesce(n.amc_s         * {_WEIGHTS['amc_breadth']}, 0)
            + coalesce(n.persistence_s * {_WEIGHTS['persistence']}, 0)
            + coalesce(n.magnitude_s   * {_WEIGHTS['magnitude']},   0)
            + coalesce(n.conviction_s  * {_WEIGHTS['conviction']},  0)
           ) / nullif(
                 (CASE WHEN n.breadth_s     IS NULL THEN 0 ELSE {_WEIGHTS['breadth']}     END
                + CASE WHEN n.amc_s         IS NULL THEN 0 ELSE {_WEIGHTS['amc_breadth']} END
                + CASE WHEN n.persistence_s IS NULL THEN 0 ELSE {_WEIGHTS['persistence']} END
                + CASE WHEN n.magnitude_s   IS NULL THEN 0 ELSE {_WEIGHTS['magnitude']}   END
                + CASE WHEN n.conviction_s  IS NULL THEN 0 ELSE {_WEIGHTS['conviction']}  END), 0)
           AS acc_score,
           (  coalesce(n.breadth_d     * {_WEIGHTS['breadth']},     0)
            + coalesce(n.exit_d        * {_WEIGHTS['amc_breadth']}, 0)
            + coalesce(n.persistence_d * {_WEIGHTS['persistence']}, 0)
            + coalesce(n.magnitude_d   * {_WEIGHTS['magnitude']},   0)
            + coalesce(n.conviction_d  * {_WEIGHTS['conviction']},  0)
           ) / nullif(
                 (CASE WHEN n.breadth_d     IS NULL THEN 0 ELSE {_WEIGHTS['breadth']}     END
                + CASE WHEN n.exit_d        IS NULL THEN 0 ELSE {_WEIGHTS['amc_breadth']} END
                + CASE WHEN n.persistence_d IS NULL THEN 0 ELSE {_WEIGHTS['persistence']} END
                + CASE WHEN n.magnitude_d   IS NULL THEN 0 ELSE {_WEIGHTS['magnitude']}   END
                + CASE WHEN n.conviction_d  IS NULL THEN 0 ELSE {_WEIGHTS['conviction']}  END), 0)
           AS dist_score,
           -- Share of the five sub-signals that were populated. This is NOT holdings coverage:
           -- it is 100.00 on every row because all five are always present, which is why
           -- migration 183 moved it to its own column and gave coverage_pct a measured value.
           ( (n.breadth_s     IS NOT NULL)::int + (n.amc_s        IS NOT NULL)::int
           + (n.persistence_s IS NOT NULL)::int + (n.magnitude_s  IS NOT NULL)::int
           + (n.conviction_s  IS NOT NULL)::int )::numeric / 5 * 100 AS subsignal_coverage_pct
      FROM norm n
)
INSERT INTO nidp.smart_money_scores_daily (
    as_of_date, symbol, security_isin, accumulation_score, distribution_score, evidence_class,
    schemes_increasing, schemes_reducing, amcs_increasing, schemes_new, schemes_exited,
    net_shares_delta, net_shares_pct, weight_delta_pp, months_observed, months_accumulating,
    single_amc_signal, components, proxy_delivery_pct_avg_20, proxy_vol_z20,
    data_confidence, coverage_pct, coverage_basis, subsignal_coverage_pct,
    latest_reporting_date, freshness_status, lookback_months,
    source_references, config_version, point_in_time, computed_at)
SELECT
    $1::date,
    s.symbol,
    s.security_isin,
    round(s.acc_score, 2),
    round(s.dist_score, 2),
    'A',
    s.schemes_increasing, s.schemes_reducing, s.amcs_increasing, s.schemes_new, s.schemes_exited,
    s.net_shares_delta,
    CASE WHEN s.prev_shares > 0 THEN round(s.net_shares_delta / s.prev_shares, 6) END,
    s.weight_delta_pp,
    s.months_observed,
    s.months_accumulating,
    (s.amcs_increasing <= 1),
    jsonb_build_object(
        'normalisation', 'percent_rank over symbols with class-A evidence on this as_of_date',
        'weights', $4::jsonb,
        'sub_signals', jsonb_build_object(
            'breadth',     jsonb_build_object('raw', s.breadth_raw,     'score', round(s.breadth_s, 2)),
            'amc_breadth', jsonb_build_object('raw', s.amcs_increasing, 'score', round(s.amc_s, 2)),
            'persistence', jsonb_build_object('raw', s.persistence_raw, 'score', round(s.persistence_s, 2)),
            'magnitude',   jsonb_build_object('raw', s.magnitude_raw,   'score', round(s.magnitude_s, 2)),
            'conviction',  jsonb_build_object('raw', s.conviction_raw,  'score', round(s.conviction_s, 2))),
        'excluded_by_design', jsonb_build_array(
            'fii_pct_change_qoq / dii_pct_change_qoq / promoter_pct_change_qoq — already scored by sector_scoring/governance.py',
            'delivery % / relative volume / volatility — already scored by the technical pillar')
    ),
    f.deliv_pct_avg_20,
    f.vol_z20,
    -- Confidence from breadth of independent holders and depth of observation, not from score size.
    CASE WHEN s.amcs_increasing >= 3 AND s.months_observed >= 3 THEN 'high'
         WHEN s.amcs_increasing >= 2 AND s.months_observed >= 2 THEN 'medium'
         ELSE 'low' END,
    -- MEASURED holdings coverage: the share of the mutual-fund holding this stock's own
    -- shareholding filing discloses that our indexed AMCs actually account for (migration 183).
    -- NULL where the filing does not disclose both mf_pct and total_shares — never 0, never 100.
    mc.coverage_pct,
    coalesce(mc.coverage_basis, 'not_measured'),
    round(s.subsignal_coverage_pct, 2),
    s.latest_reporting_date,
    -- Monthly cadence: a disclosure is due ~10 days after month end, so <70d is fresh and
    -- <100d is ageing. Judged against its own cadence, not against a daily feed's.
    CASE WHEN $1::date - s.latest_reporting_date <= 70  THEN 'fresh'
         WHEN $1::date - s.latest_reporting_date <= 100 THEN 'ageing'
         ELSE 'stale' END,
    $3,
    ARRAY['nidp.mf_holdings_deltas'],
    $5,
    $6::bool,
    now()
FROM scored s
LEFT JOIN nidp.stock_features_daily f
       ON f.symbol = s.symbol AND f.as_of_date = $1::date
-- Joined on ISIN, not symbol: the coverage view is ISIN-keyed and resolves the symbol itself
-- at the reporting month's last session, which survives a mid-series rename.
LEFT JOIN nidp.v_mf_stock_coverage mc
       ON mc.security_isin = s.security_isin AND mc.as_of_month = s.latest_reporting_date
ON CONFLICT (as_of_date, symbol, point_in_time) DO UPDATE SET
    security_isin        = EXCLUDED.security_isin,
    accumulation_score   = EXCLUDED.accumulation_score,
    distribution_score   = EXCLUDED.distribution_score,
    evidence_class       = EXCLUDED.evidence_class,
    schemes_increasing   = EXCLUDED.schemes_increasing,
    schemes_reducing     = EXCLUDED.schemes_reducing,
    amcs_increasing      = EXCLUDED.amcs_increasing,
    schemes_new          = EXCLUDED.schemes_new,
    schemes_exited       = EXCLUDED.schemes_exited,
    net_shares_delta     = EXCLUDED.net_shares_delta,
    net_shares_pct       = EXCLUDED.net_shares_pct,
    weight_delta_pp      = EXCLUDED.weight_delta_pp,
    months_observed      = EXCLUDED.months_observed,
    months_accumulating  = EXCLUDED.months_accumulating,
    single_amc_signal    = EXCLUDED.single_amc_signal,
    components           = EXCLUDED.components,
    proxy_delivery_pct_avg_20 = EXCLUDED.proxy_delivery_pct_avg_20,
    proxy_vol_z20        = EXCLUDED.proxy_vol_z20,
    data_confidence      = EXCLUDED.data_confidence,
    coverage_pct         = EXCLUDED.coverage_pct,
    coverage_basis       = EXCLUDED.coverage_basis,
    subsignal_coverage_pct = EXCLUDED.subsignal_coverage_pct,
    latest_reporting_date = EXCLUDED.latest_reporting_date,
    freshness_status     = EXCLUDED.freshness_status,
    lookback_months      = EXCLUDED.lookback_months,
    source_references    = EXCLUDED.source_references,
    config_version       = EXCLUDED.config_version,
    computed_at          = now()
"""


async def run(
    target_date: Optional[date] = None,
    *,
    lookback: int = DEFAULT_LOOKBACK,
    as_of_month: Optional[date] = None,
    point_in_time: bool = False,
) -> dict:
    """Compute the component for target_date (default: the newest scored date).

    as_of_month caps which disclosure months may be used. Leaving it at target_date is the
    point-in-time-honest default: a backfilled run for an older date must not see disclosures
    published after it.
    """
    import json

    bind_context(service=SERVICE_NAME)
    pool = await get_pool()

    async with pool.acquire() as conn:
        if target_date is None:
            target_date = await conn.fetchval(
                "SELECT max(as_of_date) FROM nidp.v3_stock_scores_daily")
        if target_date is None:
            logger.warning("%s: nidp.v3_stock_scores_daily is empty — nothing to attach to",
                           SERVICE_NAME)
            return {"as_of_date": None, "rows": 0}

    cap = as_of_month or target_date

    async with JobRun(ingester=SERVICE_NAME, target_date=target_date) as run_:
        bind_context(run_id=str(run_.run_id))
        async with pool.acquire() as conn:
            tag = await conn.execute(
                _UPSERT_SQL, target_date, cap, lookback,
                json.dumps(_WEIGHTS), CONFIG_VERSION, point_in_time, timeout=600)
            written = int(tag.rsplit(" ", 1)[-1]) if tag.startswith("INSERT") else 0

            universe = await conn.fetchval(
                "SELECT count(*) FROM nidp.v3_stock_scores_daily WHERE as_of_date = $1",
                target_date)
            conf = await conn.fetch(
                """SELECT data_confidence, count(*) n FROM nidp.smart_money_scores_daily
                    WHERE as_of_date = $1 AND point_in_time = $2
                    GROUP BY 1 ORDER BY 2 DESC""", target_date, point_in_time)

        by_conf = {r["data_confidence"]: r["n"] for r in conf}
        logger.info("%s %s: wrote %d rows (universe %s, lookback %d months, pit=%s); "
                    "confidence=%s",
                    SERVICE_NAME, target_date, written, universe, lookback,
                    point_in_time, by_conf)

        run_.rows_fetched = written
        run_.rows_inserted = written
        run_.metadata.update({
            "universe": universe, "scored": written, "lookback_months": lookback,
            "by_confidence": by_conf, "config_version": CONFIG_VERSION,
            "point_in_time": point_in_time,
            # Recorded so the gap between universe and scored is never mistaken for zero signal.
            "unscored_no_disclosed_evidence": (universe or 0) - written,
        })
        await run_.finalize("OK" if written else "FAILED",
                            error_message=None if written else "no symbols had class-A evidence")

    return {"as_of_date": target_date.isoformat(), "rows": written,
            "universe": universe, "by_confidence": by_conf}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Smart Money accumulation component (shadow mode; writes only "
                    "nidp.smart_money_scores_daily)")
    ap.add_argument("--date", default=None, help="scoring date (default: newest scored date)")
    ap.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK,
                    help=f"disclosure months to look across (default {DEFAULT_LOOKBACK})")
    ap.add_argument("--month", default=None, metavar="YYYY-MM",
                    help="historical mode: score as of this DISCLOSURE month. The scoring date "
                         "becomes month-end + DISCLOSURE_LAG_DAYS (roughly when the month could "
                         "first be known) and no later disclosure is visible. This is what makes "
                         "a multi-date shadow series possible from backfilled data — but it is "
                         "reporting-date-based, NOT point-in-time: the rows were observed in "
                         "October 2026, so a historical run still sees them earlier than anyone "
                         "could have. Treat the series as a stability check, not a backtest.")
    ap.add_argument("--point-in-time", action="store_true",
                    help="use only changes that were KNOWABLE by the scoring date, and only where "
                         "both compared months carry a real publication timestamp. This is what "
                         "makes a historical series valid for a backtest; without it the series "
                         "is reporting-date-based and sees the future.")
    args = ap.parse_args()
    setup_logging(service=SERVICE_NAME)

    if args.month and args.date:
        raise SystemExit("give either --month or --date, not both")

    cap = None
    if args.month:
        y, m = (int(x) for x in args.month.split("-")[:2])
        cap = date(y, m, 1)
        month_end = (date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)) - timedelta(days=1)
        d = month_end + timedelta(days=DISCLOSURE_LAG_DAYS)
    else:
        d = date.fromisoformat(args.date) if args.date else None

    async def _go() -> None:
        try:
            await run(d, lookback=args.lookback, as_of_month=cap,
                      point_in_time=args.point_in_time)
        finally:
            await close_pool()

    asyncio.run(_go())


if __name__ == "__main__":
    main()
