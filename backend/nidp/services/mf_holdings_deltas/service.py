"""Compute nidp.mf_holdings_deltas — month-over-month mutual-fund holdings changes (§20.1).

The whole Smart Money "disclosed holdings change" evidence class (§17 class A) reduces to one
question per scheme × ISIN: did the SHARE COUNT move between two disclosure months, and can we
prove it. This service answers it in SQL, set-at-a-time, because the comparison is a join
between two months of one table and anything row-at-a-time over ~2M holdings rows would be far
slower without being clearer.

Three rules carry the honesty of the whole layer:

  1. Shares, not value. A holding worth more because the stock rose is NOT accumulation
     (§20.1, §26.3). market_value is stored for display and never classifies the change.
  2. Absence is not an exit unless we fetched the file. If scheme S has no rows at all in the
     comparison month, we did not observe S that month, so an ISIN "missing" from it is our gap,
     not a sale → change_class='unknown', validation_status='coverage_gap' (§26.4, §26.8).
  3. No ISIN, no delta. A holding we cannot tie to an instrument cannot be attributed to a stock
     (§26.2). Those rows are excluded and COUNTED, so the exclusion is reported, not silent.

The comparison month is the latest month BEFORE the target that the scheme actually appears in —
not blindly M-1. With a backfill in progress, or an AMC that skipped a month, M-1 may simply not
exist; comparing against the real previous disclosure is both more useful and more honest, and
previous_month records which month was in fact used.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date
from typing import Optional

from nidp.shared.logging_setup import bind_context, setup_logging
from nidp.shared.storage.job_log import JobRun
from nidp.shared.storage.pg import close_pool, get_pool

logger = logging.getLogger(__name__)

SERVICE_NAME = "mf_holdings_deltas"


# Months that have any holdings at all, newest first.
_MONTHS_SQL = "SELECT DISTINCT as_of_month FROM nidp.mf_holdings_monthly ORDER BY as_of_month DESC"

# Holdings rows dropped for want of an ISIN — reported, never silently discarded.
_NO_ISIN_SQL = """
SELECT count(*) FROM nidp.mf_holdings_monthly
 WHERE as_of_month = $1 AND (security_isin IS NULL OR security_isin = '')
"""

# One month's deltas.
#
#   cur / prv   — ISIN-keyed holdings for the target month and, per scheme, the most recent
#                 earlier month that scheme actually appears in.
#   prev_seen   — did we observe this scheme at all in its comparison month? This is what
#                 separates a real exit from a hole in our collection.
#
# FULL OUTER JOIN so a position present in the previous month but gone from the current one
# (a possible exit) produces a row too, not just the survivors.
_DELTA_SQL = """
WITH
-- When each scheme's disclosure for a given month became knowable. published_at where the
-- source's Last-Modified was credible (migration 171), else the time we observed the file.
-- Taken as the MAX across the scheme's rows: the whole file is knowable only once all of it is.
scheme_known AS (
    SELECT scheme_code, as_of_month,
           max(coalesce(published_at, source_observed_at))  AS known_from,
           -- 'published' only if every row backing this scheme-month had a real publication date.
           CASE WHEN count(*) = count(published_at) THEN 'published' ELSE 'observed' END
               AS known_basis
      FROM nidp.mf_holdings_monthly
     GROUP BY scheme_code, as_of_month
),
cur AS (
    SELECT scheme_code, security_isin,
           max(security_name)      AS security_name,
           sum(quantity)           AS shares,
           sum(weight_pct)         AS weight_pct,
           sum(market_value_inr)   AS market_value_inr,
           min(source_url)         AS source_url
      FROM nidp.mf_holdings_monthly
     WHERE as_of_month = $1 AND security_isin IS NOT NULL AND security_isin <> ''
     GROUP BY scheme_code, security_isin
),
-- Per scheme in the target month, the newest earlier month that scheme was observed in.
prev_month AS (
    SELECT h.scheme_code, max(h.as_of_month) AS prev_month
      FROM nidp.mf_holdings_monthly h
     WHERE h.as_of_month < $1
       AND h.scheme_code IN (SELECT scheme_code FROM nidp.mf_holdings_monthly WHERE as_of_month = $1)
     GROUP BY h.scheme_code
),
prv AS (
    SELECT h.scheme_code, h.security_isin, pm.prev_month,
           max(h.security_name)    AS security_name,
           sum(h.quantity)         AS shares,
           sum(h.weight_pct)       AS weight_pct,
           sum(h.market_value_inr) AS market_value_inr,
           min(h.source_url)       AS source_url
      FROM nidp.mf_holdings_monthly h
      JOIN prev_month pm ON pm.scheme_code = h.scheme_code AND pm.prev_month = h.as_of_month
     WHERE h.security_isin IS NOT NULL AND h.security_isin <> ''
     GROUP BY h.scheme_code, h.security_isin, pm.prev_month
),
j AS (
    SELECT coalesce(cur.scheme_code, prv.scheme_code)     AS scheme_code,
           coalesce(cur.security_isin, prv.security_isin) AS security_isin,
           coalesce(cur.security_name, prv.security_name) AS security_name,
           pm.prev_month,
           prv.shares            AS prev_shares,
           cur.shares            AS cur_shares,
           prv.weight_pct        AS prev_weight,
           cur.weight_pct        AS cur_weight,
           prv.market_value_inr  AS prev_mv,
           cur.market_value_inr  AS cur_mv,
           prv.source_url        AS prev_url,
           cur.source_url        AS cur_url,
           -- Was the scheme observed in its comparison month at all?
           (pm.prev_month IS NOT NULL)                    AS prev_seen,
           -- A change is knowable only once BOTH compared months are published, so take the later.
           greatest(kc.known_from, kp.known_from)         AS known_from,
           CASE WHEN kc.known_basis = 'published'
                 AND coalesce(kp.known_basis, 'published') = 'published'
                THEN 'published' ELSE 'observed' END      AS known_basis
      FROM cur
      FULL OUTER JOIN prv
        ON prv.scheme_code = cur.scheme_code AND prv.security_isin = cur.security_isin
      LEFT JOIN prev_month pm
        ON pm.scheme_code = coalesce(cur.scheme_code, prv.scheme_code)
      LEFT JOIN scheme_known kc
        ON kc.scheme_code = coalesce(cur.scheme_code, prv.scheme_code)
       AND kc.as_of_month = $1::date
      LEFT JOIN scheme_known kp
        ON kp.scheme_code = coalesce(cur.scheme_code, prv.scheme_code)
       AND kp.as_of_month = pm.prev_month
)
INSERT INTO nidp.mf_holdings_deltas (
    scheme_code, security_isin, current_month, previous_month, security_name,
    previous_shares, current_shares, shares_delta, shares_pct_change,
    previous_weight_pct, current_weight_pct, weight_delta_pp,
    previous_market_value_inr, current_market_value_inr,
    change_class, validation_status, source_references,
    known_from, known_from_basis, computed_at)
SELECT
    j.scheme_code,
    j.security_isin,
    $1::date,
    j.prev_month,
    j.security_name,
    j.prev_shares,
    j.cur_shares,
    CASE WHEN j.prev_seen THEN coalesce(j.cur_shares, 0) - coalesce(j.prev_shares, 0) END,
    -- §20.1: a percentage change exists only when the prior count is strictly positive.
    CASE WHEN j.prev_seen AND j.prev_shares > 0
         THEN (coalesce(j.cur_shares, 0) - j.prev_shares) / j.prev_shares END,
    j.prev_weight,
    j.cur_weight,
    CASE WHEN j.prev_seen THEN coalesce(j.cur_weight, 0) - coalesce(j.prev_weight, 0) END,
    j.prev_mv,
    j.cur_mv,
    CASE
        -- No observation of this scheme in any earlier month: direction is unknowable.
        WHEN NOT j.prev_seen                                   THEN 'unknown'
        WHEN j.prev_shares IS NULL AND j.cur_shares > 0        THEN 'new'
        WHEN j.cur_shares IS NULL AND j.prev_shares > 0        THEN 'possible_exit'
        WHEN coalesce(j.cur_shares, 0) > coalesce(j.prev_shares, 0) THEN 'increase'
        WHEN coalesce(j.cur_shares, 0) < coalesce(j.prev_shares, 0) THEN 'decrease'
        ELSE 'unchanged'
    END,
    CASE WHEN j.prev_seen THEN 'validated' ELSE 'coverage_gap' END,
    ARRAY(SELECT u FROM unnest(ARRAY[j.cur_url, j.prev_url]) AS u WHERE u IS NOT NULL),
    j.known_from,
    j.known_basis,
    now()
FROM j
ON CONFLICT (scheme_code, security_isin, current_month) DO UPDATE SET
    previous_month            = EXCLUDED.previous_month,
    security_name             = EXCLUDED.security_name,
    previous_shares           = EXCLUDED.previous_shares,
    current_shares            = EXCLUDED.current_shares,
    shares_delta              = EXCLUDED.shares_delta,
    shares_pct_change         = EXCLUDED.shares_pct_change,
    previous_weight_pct       = EXCLUDED.previous_weight_pct,
    current_weight_pct        = EXCLUDED.current_weight_pct,
    weight_delta_pp           = EXCLUDED.weight_delta_pp,
    previous_market_value_inr = EXCLUDED.previous_market_value_inr,
    current_market_value_inr  = EXCLUDED.current_market_value_inr,
    change_class              = EXCLUDED.change_class,
    validation_status         = EXCLUDED.validation_status,
    source_references         = EXCLUDED.source_references,
    known_from                = EXCLUDED.known_from,
    known_from_basis          = EXCLUDED.known_from_basis,
    computed_at               = now()
"""


async def compute_month(month: date) -> dict:
    """Compute (and upsert) deltas for one disclosure month."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        no_isin = await conn.fetchval(_NO_ISIN_SQL, month)
        tag = await conn.execute(_DELTA_SQL, month, timeout=600)
        counts = await conn.fetch(
            """SELECT change_class, count(*) AS n FROM nidp.mf_holdings_deltas
                WHERE current_month = $1 GROUP BY change_class ORDER BY 2 DESC""",
            month,
        )
    written = int(tag.rsplit(" ", 1)[-1]) if tag.startswith("INSERT") else 0
    by_class = {r["change_class"]: r["n"] for r in counts}
    logger.info("mf_holdings_deltas %s: %d rows; excluded %d holdings with no ISIN; classes=%s",
                month.isoformat(), written, no_isin or 0, by_class)
    return {"month": month.isoformat(), "rows": written,
            "excluded_no_isin": int(no_isin or 0), "by_class": by_class}


async def run(target_date: Optional[date] = None, *, all_months: bool = False) -> dict:
    """target_date → that month only. all_months → every month that has holdings.

    The earliest month always classifies as 'unknown'/'coverage_gap': there is nothing before it
    to compare against. That is the correct reading, not a bug — we genuinely cannot say which
    way those positions moved.
    """
    bind_context(service=SERVICE_NAME)
    pool = await get_pool()
    async with pool.acquire() as conn:
        months = [r["as_of_month"] for r in await conn.fetch(_MONTHS_SQL)]
    if not months:
        logger.warning("mf_holdings_deltas: nidp.mf_holdings_monthly is empty — nothing to do")
        return {"months": [], "rows": 0}

    if all_months:
        targets = sorted(months)
    elif target_date is not None:
        targets = [date(target_date.year, target_date.month, 1)]
    else:
        targets = [months[0]]          # newest

    out: list[dict] = []
    async with JobRun(ingester=SERVICE_NAME, target_date=targets[-1]) as run_:
        bind_context(run_id=str(run_.run_id))
        for m in targets:
            out.append(await compute_month(m))
        total = sum(o["rows"] for o in out)
        run_.rows_inserted = total
        run_.rows_fetched = total
        run_.metadata["months"] = [o["month"] for o in out]
        run_.metadata["excluded_no_isin"] = sum(o["excluded_no_isin"] for o in out)
        await run_.finalize("OK" if total else "FAILED",
                            error_message=None if total else "no delta rows produced")
    return {"months": out, "rows": sum(o["rows"] for o in out)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Compute nidp.mf_holdings_deltas")
    ap.add_argument("--date", default=None, help="YYYY-MM or YYYY-MM-DD (default: newest month)")
    ap.add_argument("--all", action="store_true", help="recompute every month that has holdings")
    args = ap.parse_args()
    setup_logging(service=SERVICE_NAME)

    d = None
    if args.date:
        d = date.fromisoformat(args.date if len(args.date) > 7 else f"{args.date}-01")

    async def _go() -> None:
        try:
            await run(d, all_months=args.all)
        finally:
            await close_pool()

    asyncio.run(_go())


if __name__ == "__main__":
    main()
