"""Compute nidp.mf_holdings_deltas — month-over-month mutual-fund holdings changes (§20.1).

The whole Smart Money "disclosed holdings change" evidence class (§17 class A) reduces to one
question per fund × ISIN: did the SHARE COUNT move between two disclosure months, and can we
prove it. This service answers it in SQL, set-at-a-time, because the comparison is a join
between two months of one table and anything row-at-a-time over ~2M holdings rows would be far
slower without being clearer.

Five rules carry the honesty of the whole layer:

  1. Shares, not value. A holding worth more because the stock rose is NOT accumulation
     (§20.1, §26.3). market_value is stored for display and never classifies the change.
  2. Absence is not an exit unless we fetched the file. If fund F has no rows at all in the
     comparison month, we did not observe F that month, so an ISIN "missing" from it is our gap,
     not a sale → change_class='unknown', validation_status='coverage_gap' (§26.4, §26.8).
  3. No ISIN, no delta. A holding we cannot tie to an instrument cannot be attributed to a stock
     (§26.2). Those rows are excluded and COUNTED, so the exclusion is reported, not silent.
  4. ONE ROW PER FUND, not per plan variant (migration 182/183). The source table stores a
     holding once per plan/option scheme_code with an identical quantity — 4.09x fan-out
     measured on 2026-09 — so the input here is nidp.v_mf_holdings_canonical, and the row is
     written under the fund's representative scheme_code. naive_* columns keep the pre-dedupe
     sum so the inflation stays auditable.
  5. CONSTANT PANEL. Our index grew from 7 AMCs / 20,604 canonical fund-ISIN rows (2025-09) to
     11 / 38,318 (2026-09). A difference taken over a growing panel reads "we started indexing
     this fund" as "mutual funds bought", so a fund absent from the comparison month is
     panel_status='panel_entry' and carries no direction at all.

The comparison month is the latest month BEFORE the target that the FUND actually appears in —
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

# One month's deltas, at the CANONICAL FUND grain (migration 182/183).
#
#   fund_months — which (fund, month) pairs we observed at all. Cheap: built from the distinct
#                 (scheme_code, source, as_of_month) triples, not from the holdings rows.
#   cur / prv   — canonical holdings (one row per fund x ISIN, plan variants collapsed, derivative
#                 legs excluded) for the target month and, per fund, the most recent earlier month
#                 that fund actually appears in.
#   prev_seen   — did we observe this FUND at all in its comparison month? This is what separates
#                 a real exit from a hole in our collection, and a real purchase from our index
#                 having grown.
#
# FULL OUTER JOIN so a position present in the previous month but gone from the current one
# (a possible exit) produces a row too, not just the survivors.
_DELTA_SQL = """
WITH
fund_months AS (
    SELECT DISTINCT k.amc_id || '|' || k.base_scheme AS canonical_fund_key, h.as_of_month
      FROM (SELECT DISTINCT scheme_code, source, as_of_month FROM nidp.mf_holdings_monthly) h
      JOIN nidp.v_mf_scheme_canonical_key k
        ON k.scheme_code = h.scheme_code AND k.source = h.source
),
cur AS (
    SELECT * FROM nidp.v_mf_holdings_canonical WHERE as_of_month = $1::date
),
-- Per fund in the target month, the newest earlier month that fund was observed in.
prev_month AS (
    SELECT fm.canonical_fund_key, max(fm.as_of_month) AS prev_month
      FROM fund_months fm
     WHERE fm.as_of_month < $1::date
       AND fm.canonical_fund_key IN (SELECT canonical_fund_key FROM cur)
     GROUP BY 1
),
prv AS (
    SELECT c.*, pm.prev_month
      FROM nidp.v_mf_holdings_canonical c
      JOIN prev_month pm
        ON pm.canonical_fund_key = c.canonical_fund_key AND pm.prev_month = c.as_of_month
),
j AS (
    SELECT coalesce(cur.canonical_fund_key, prv.canonical_fund_key) AS canonical_fund_key,
           coalesce(cur.amc_id, prv.amc_id)                         AS amc_id,
           coalesce(cur.base_scheme, prv.base_scheme)               AS base_scheme,
           coalesce(cur.representative_scheme_code,
                    prv.representative_scheme_code)                 AS scheme_code,
           coalesce(cur.security_isin, prv.security_isin)            AS security_isin,
           coalesce(cur.security_name, prv.security_name)            AS security_name,
           pm.prev_month,
           prv.shares                AS prev_shares,
           cur.shares                AS cur_shares,
           prv.naive_sum_quantity    AS prev_naive_shares,
           cur.naive_sum_quantity    AS cur_naive_shares,
           prv.weight_pct            AS prev_weight,
           cur.weight_pct            AS cur_weight,
           prv.market_value_inr      AS prev_mv,
           cur.market_value_inr      AS cur_mv,
           coalesce(cur.variant_scheme_codes, prv.variant_scheme_codes) AS variant_scheme_codes,
           coalesce(cur.variant_rows, prv.variant_rows)              AS variant_rows,
           coalesce(cur.derivative_rows, prv.derivative_rows)        AS derivative_rows,
           ARRAY(SELECT DISTINCT u
                   FROM unnest(coalesce(cur.source_urls, ARRAY[]::text[])
                             || coalesce(prv.source_urls, ARRAY[]::text[])) AS u
                  WHERE u IS NOT NULL)                              AS source_refs,
           -- Was the fund observed in its comparison month at all?
           (pm.prev_month IS NOT NULL)                              AS prev_seen,
           -- A change is knowable only once BOTH compared months are published, so take the later.
           greatest(cur.known_from, prv.known_from)                  AS known_from,
           CASE WHEN coalesce(cur.known_from_basis, 'observed') = 'published'
                 AND coalesce(prv.known_from_basis, 'published') = 'published'
                THEN 'published' ELSE 'observed' END                 AS known_basis
      FROM cur
      FULL OUTER JOIN prv
        ON prv.canonical_fund_key = cur.canonical_fund_key
       AND prv.security_isin      = cur.security_isin
      LEFT JOIN prev_month pm
        ON pm.canonical_fund_key = coalesce(cur.canonical_fund_key, prv.canonical_fund_key)
)
INSERT INTO nidp.mf_holdings_deltas (
    scheme_code, security_isin, current_month, previous_month, security_name,
    previous_shares, current_shares, shares_delta, shares_pct_change,
    previous_weight_pct, current_weight_pct, weight_delta_pp,
    previous_market_value_inr, current_market_value_inr,
    change_class, validation_status, source_references,
    known_from, known_from_basis,
    amc_id, base_scheme, canonical_fund_key, variant_scheme_codes, variant_rows,
    panel_status, naive_previous_shares, naive_current_shares, derivative_rows,
    computed_basis, computed_at)
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
        -- The fund itself is new to our index: direction is unknowable, not zero and not buying.
        WHEN NOT j.prev_seen                                   THEN 'unknown'
        WHEN j.prev_shares IS NULL AND j.cur_shares > 0        THEN 'new'
        WHEN j.cur_shares IS NULL AND j.prev_shares > 0        THEN 'possible_exit'
        WHEN coalesce(j.cur_shares, 0) > coalesce(j.prev_shares, 0) THEN 'increase'
        WHEN coalesce(j.cur_shares, 0) < coalesce(j.prev_shares, 0) THEN 'decrease'
        ELSE 'unchanged'
    END,
    CASE WHEN j.prev_seen THEN 'validated' ELSE 'coverage_gap' END,
    j.source_refs,
    j.known_from,
    j.known_basis,
    j.amc_id,
    j.base_scheme,
    j.canonical_fund_key,
    j.variant_scheme_codes,
    j.variant_rows,
    CASE WHEN j.prev_seen THEN 'constant_panel' ELSE 'panel_entry' END,
    j.prev_naive_shares,
    j.cur_naive_shares,
    j.derivative_rows,
    'canonical_fund',
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
    amc_id                    = EXCLUDED.amc_id,
    base_scheme               = EXCLUDED.base_scheme,
    canonical_fund_key        = EXCLUDED.canonical_fund_key,
    variant_scheme_codes      = EXCLUDED.variant_scheme_codes,
    variant_rows              = EXCLUDED.variant_rows,
    panel_status              = EXCLUDED.panel_status,
    naive_previous_shares     = EXCLUDED.naive_previous_shares,
    naive_current_shares      = EXCLUDED.naive_current_shares,
    derivative_rows           = EXCLUDED.derivative_rows,
    computed_basis            = 'canonical_fund',
    computed_at               = now()
"""

# A month recomputed at the canonical grain must not leave its old plan-variant rows behind:
# those are the 4.09x duplicates, and a consumer summing the table would read both grains at
# once. Deleted explicitly and counted, never left to a later reader to notice.
_DROP_LEGACY_SQL = """
DELETE FROM nidp.mf_holdings_deltas
 WHERE current_month = $1 AND computed_basis <> 'canonical_fund'
"""

# What the month looks like after the write: grain, panel split and the inflation removed.
_SHAPE_SQL = """
SELECT count(*)                                                        AS rows,
       count(DISTINCT canonical_fund_key)                              AS funds,
       count(*) FILTER (WHERE panel_status = 'constant_panel')          AS constant_panel_rows,
       count(*) FILTER (WHERE panel_status = 'panel_entry')             AS panel_entry_rows,
       sum(variant_rows)                                               AS source_rows_collapsed,
       round(sum(variant_rows)::numeric / nullif(count(*), 0), 3)       AS duplication_factor,
       sum(shares_delta) FILTER (WHERE panel_status = 'constant_panel'
                                   AND change_class <> 'unknown')       AS net_shares_delta,
       sum(coalesce(naive_current_shares, 0) - coalesce(naive_previous_shares, 0))
           FILTER (WHERE panel_status = 'constant_panel')               AS naive_net_shares_delta
  FROM nidp.mf_holdings_deltas
 WHERE current_month = $1 AND computed_basis = 'canonical_fund'
"""


async def compute_month(month: date) -> dict:
    """Compute (and upsert) deltas for one disclosure month, at the canonical fund grain."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        no_isin = await conn.fetchval(_NO_ISIN_SQL, month)
        tag = await conn.execute(_DELTA_SQL, month, timeout=1800)
        # Remove the month's pre-dedupe rows, so the table never holds both grains at once.
        drop_tag = await conn.execute(_DROP_LEGACY_SQL, month, timeout=600)
        shape = await conn.fetchrow(_SHAPE_SQL, month)
        counts = await conn.fetch(
            """SELECT change_class, count(*) AS n FROM nidp.mf_holdings_deltas
                WHERE current_month = $1 AND computed_basis = 'canonical_fund'
                GROUP BY change_class ORDER BY 2 DESC""",
            month,
        )
    written = int(tag.rsplit(" ", 1)[-1]) if tag.startswith("INSERT") else 0
    legacy_dropped = int(drop_tag.rsplit(" ", 1)[-1]) if drop_tag.startswith("DELETE") else 0
    by_class = {r["change_class"]: r["n"] for r in counts}
    logger.info(
        "mf_holdings_deltas %s: %d canonical rows over %s funds (duplication removed %sx); "
        "panel constant/entry %s/%s; dropped %d legacy plan-variant rows; "
        "excluded %d holdings with no ISIN; classes=%s",
        month.isoformat(), written, shape["funds"] if shape else 0,
        shape["duplication_factor"] if shape else None,
        shape["constant_panel_rows"] if shape else 0,
        shape["panel_entry_rows"] if shape else 0,
        legacy_dropped, no_isin or 0, by_class,
    )
    return {"month": month.isoformat(), "rows": written,
            "excluded_no_isin": int(no_isin or 0), "by_class": by_class,
            "legacy_rows_dropped": legacy_dropped,
            "funds": int(shape["funds"]) if shape and shape["funds"] else 0,
            "constant_panel_rows": int(shape["constant_panel_rows"] or 0) if shape else 0,
            "panel_entry_rows": int(shape["panel_entry_rows"] or 0) if shape else 0,
            "duplication_factor": float(shape["duplication_factor"]) if shape and shape["duplication_factor"] else None,
            "net_shares_delta": float(shape["net_shares_delta"]) if shape and shape["net_shares_delta"] is not None else None,
            "naive_net_shares_delta": float(shape["naive_net_shares_delta"]) if shape and shape["naive_net_shares_delta"] is not None else None}


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
        # Both recorded: a reader of the job log can see how much duplication was removed and
        # how much of the table was rewritten from the old plan-variant grain.
        run_.metadata["legacy_rows_dropped"] = sum(o["legacy_rows_dropped"] for o in out)
        run_.metadata["panel_entry_rows"] = sum(o["panel_entry_rows"] for o in out)
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
