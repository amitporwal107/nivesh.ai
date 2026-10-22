"""DaaS — Smart Money Movement reads for the Smart trading desk.

    GET /v1/desk/smart-money/feeds              per-feed status, paired with the real data as-of date
    GET /v1/desk/smart-money/flows?window=      FII/DII cash net + cumulative, one grain per window
    GET /v1/desk/smart-money/sectors            disclosed MF holdings change by industry
    GET /v1/desk/smart-money/breadth            how many names have disclosed / proxy evidence
    GET /v1/desk/smart-money/scanner            one row per Nifty 500 stock: the evidence behind it

Read-only. Every answer names its source table and the as-of date; a missing figure is null, never 0.
No data -> 200 with an empty list and the as-of date.

This serves EVIDENCE, not a verdict. The smart-money validation study (NIDP-SM-VALIDATION-001/002)
returned INCONCLUSIVE at stage 'exploratory', and nidp.smart_money_promotion_decisions holds zero
APPROVED rows, so no scored or ranked claim is authorised. Deliberate omissions, each with a reason:

  * No accumulation/distribution score and no rank by one. The study's CI lower bound is 0.0000,
    which fails its own frozen `full_promotion_requires` ("lower bound above zero"), and the point
    estimate 0.2189 pp fails ">= +1.0 pp". Two of four criteria are measured failures.
  * No hit rate / "historical market reaction" figure. None exists: a database-wide column search
    for hit_rate|win_rate|forward_return|reaction finds nothing in the smart-money path. The screen
    ships the words "no validated study available" instead.
  * nidp.v_smart_money_shadow_rank is NOT read. It lacks a point_in_time predicate (936 of 2,479
    symbols duplicate on 2026-10-21 with two different scores, so its rank() window runs over a
    duplicated population), and its shadow_score silently falls back to live_score when the join
    misses (on 2026-10-19 all 2,480 rows carry a score with zero smart-money input).
  * evidence_class is NOT read. It is a hardcoded literal 'A' at
    nidp/services/smart_money_scores/service.py:229 -- 100% of 25,313 rows on all 16 dates. There is
    no classifier. Reading it would render a constant as a measurement. The disclosed/proxy split
    here is derived from net_shares_delta vs proxy_delivery_pct_avg_20 instead.

Definitions
  feeds       `ingested_at` is when the loader last ran; `data_as_of` is max() of the real date
              column in the underlying table. They differ a lot (shareholding ingested 2026-10-22,
              data period 2026-09-30) so both are returned and the UI must label which is which.
  flows       one grain per window, never summed across grains: the monthly row for the current
              month is month-to-date and exactly equals the sum of that month's daily rows, so
              mixing them double-counts 2x. 1M/3M/6M use source SENSIBULL (daily, from 2026-04-01);
              1Y uses SENSIBULL_MONTHLY (98 months from 2018-09). A 1Y request answered from daily
              rows would silently truncate to ~6.7 months and look plausible.
  sectors     net_value_cr = sum(shares_delta x September VWAP) / 1e7. The month pair is pinned:
              an unpinned previous_month mixes 1-, 4- and 5-month lookbacks silently.
  breadth     disclosed = a validated holdings change; proxy = delivery/volume only, buyer unknown,
              which is never called accumulation. Counted on the point-in-time series only.
  scanner     the core row (MF delta + delivery baseline) is available for 497 of 500 names. The
              FII/DII pp and deal columns are null for most names BY COVERAGE, not by absence of
              activity -- `deals_checked` distinguishes "we never asked" from "no deals".
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import row_to_dict

router = APIRouter(prefix="/desk", tags=["desk"], dependencies=[Depends(require_api_key)])

MAX_LIMIT = 500

# ---------------------------------------------------------------- feeds

# (label, v_feed_status.source_name, table, real date column). A feed whose status row is missing
# still gets a strip from its table max -- the Trendlyne fundamentals path has no v_feed_status row.
_FEEDS: List[tuple] = [
    ("FII/DII cash (Sensibull)", "sensibull_fii_dii",  "nidp.fii_dii_flows",            "as_of_date"),
    ("NSE FII/DII cash",         "NSE_FII_DII",         "nidp.fii_dii_flows",            "as_of_date"),
    ("AMFI scheme portfolios",   "mf_holdings",         "nidp.mf_holdings_monthly",      "as_of_month"),
    ("Shareholding patterns",    "NSE_SHAREHOLDING",    "nidp.shareholding_pattern",     "period_end"),
    ("Deals (Trendlyne)",        "trendlyne_deals",     "nidp.trendlyne_deals",          "deal_date"),
    ("Bulk deals",               "NSE_BULK_DEALS",      "nidp.bulk_deals",               "as_of_date"),
]

_FEED_STATUS_SQL = """
    SELECT source_name, effective_status, expected_freq, staleness_days, staleness_budget_days,
           coalesce(last_target_date, last_snapshot_date)::text AS ingested_for,
           last_success_at::date::text                          AS last_success
      FROM nidp.v_feed_status
     WHERE source_name = ANY($1::text[])
"""


@router.get("/smart-money/feeds", summary="Smart-money feed status, with the real data as-of date")
async def smart_money_feeds() -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        status = {r["source_name"]: dict(r) for r in await conn.fetch(_FEED_STATUS_SQL, [f[1] for f in _FEEDS])}
        # One scalar per distinct table/column: the date the DATA actually reaches.
        wanted = {(t, c) for _, _, t, c in _FEEDS}
        data_as_of: Dict[tuple, Optional[str]] = {}
        for tbl, col in wanted:
            got = await conn.fetchval(f"SELECT max({col})::text FROM {tbl}")  # noqa: S608 - fixed allow-list above
            data_as_of[(tbl, col)] = got

    rows: List[Dict[str, Any]] = []
    for label, src, tbl, col in _FEEDS:
        st = status.get(src) or {}
        rows.append({
            "feed": label,
            "source_name": src,
            "table": tbl,
            "status": st.get("effective_status"),
            "expected_freq": st.get("expected_freq"),
            "staleness_days": st.get("staleness_days"),
            "staleness_budget_days": st.get("staleness_budget_days"),
            "last_success": st.get("last_success"),
            "ingested_for": st.get("ingested_for"),
            "data_as_of": data_as_of.get((tbl, col)),
            "status_row_present": src in status,
        })
    return {
        "source": "nidp.v_feed_status, paired with max() of each underlying table",
        "disclosure": ("`ingested_for` is when the loader last ran; `data_as_of` is the newest data period. "
                       "They are different dates and the second is the honest one."),
        "count": len(rows), "total": len(rows), "rows": rows,
    }


# ---------------------------------------------------------------- flows

# window -> (source, grain, how far back). One grain per window, never mixed.
_WINDOWS: Dict[str, tuple] = {
    "1M": ("SENSIBULL",         "daily",   timedelta(days=30)),
    "3M": ("SENSIBULL",         "daily",   timedelta(days=90)),
    "6M": ("SENSIBULL",         "daily",   timedelta(days=180)),
    "1Y": ("SENSIBULL_MONTHLY", "monthly", None),
}

_FLOWS_SQL = """
    WITH d AS (
        SELECT as_of_date,
               sum(net_value_cr) FILTER (WHERE category = 'FII') AS fii_net_cr,
               sum(net_value_cr) FILTER (WHERE category = 'DII') AS dii_net_cr
          FROM nidp.fii_dii_flows
         WHERE source = $1 AND segment = 'EQUITY_CASH' AND category IN ('FII', 'DII')
           AND as_of_date >= $2 AND as_of_date <= $3
         GROUP BY as_of_date
    )
    SELECT as_of_date::text AS date, fii_net_cr, dii_net_cr,
           sum(fii_net_cr) OVER (ORDER BY as_of_date) AS fii_cum_cr,
           sum(dii_net_cr) OVER (ORDER BY as_of_date) AS dii_cum_cr
      FROM d ORDER BY as_of_date
"""


@router.get("/smart-money/flows", summary="FII/DII cash net and cumulative, one grain per window")
async def smart_money_flows(
    window: str = Query("3M", pattern="^(1M|3M|6M|1Y)$", description="1M, 3M and 6M are daily; 1Y is monthly"),
) -> Dict[str, Any]:
    source, grain, back = _WINDOWS[window]
    out: Dict[str, Any] = {
        "as_of": None, "window": window, "grain": grain, "source": f"nidp.fii_dii_flows (source={source})",
        "disclosure": ("Market-wide cash-segment flows, not stock-specific. Daily rows begin 2026-04-01, so a "
                       "1Y window is served at monthly grain; the two grains are never summed together "
                       "(the current month's monthly row equals the sum of its daily rows)."),
        "start": None, "points": 0, "fii_net_cr": None, "dii_net_cr": None,
        "count": 0, "total": 0, "rows": [],
    }
    pool = await get_pool()
    async with pool.acquire() as conn:
        end: Optional[date] = await conn.fetchval(
            "SELECT max(as_of_date) FROM nidp.fii_dii_flows WHERE source = $1 AND segment = 'EQUITY_CASH'", source)
        if end is None:
            return out
        if back is None:
            # 1Y monthly: the 12 month-start rows ending at the newest one (11 months back, inclusive).
            tm = end.year * 12 + end.month - 11
            start = date((tm - 1) // 12, (tm - 1) % 12 + 1, 1)
        else:
            start = end - back
        rows = [row_to_dict(r) for r in await conn.fetch(_FLOWS_SQL, source, start, end)]

    out["as_of"] = end.isoformat()
    out["start"] = start.isoformat()
    out["rows"] = rows
    out["count"] = out["total"] = out["points"] = len(rows)
    if rows:
        out["fii_net_cr"] = rows[-1]["fii_cum_cr"]
        out["dii_net_cr"] = rows[-1]["dii_cum_cr"]
    return out


# ---------------------------------------------------------------- the pinned MF month pair

_MF_PAIR_SQL = """
    SELECT current_month, max(previous_month) AS previous_month
      FROM nidp.mf_holdings_deltas
     WHERE current_month = (SELECT max(current_month) FROM nidp.mf_holdings_deltas)
       AND previous_month IS NOT NULL
     GROUP BY current_month
"""

# Nifty 500's newest list. DUMMYHEG is a placeholder with no price rows; the 3 REITs on series 'RR'
# drop out of the VWAP join on their own and are reported as such rather than silently missing.
_UNIVERSE_CTE = """
    n5 AS (
        SELECT DISTINCT symbol, isin, industry
          FROM nidp.index_constituents
         WHERE index_name = 'Nifty 500'
           AND as_of_date = (SELECT max(as_of_date) FROM nidp.index_constituents WHERE index_name = 'Nifty 500')
           AND symbol <> 'DUMMYHEG'
    )
"""

# series IN ('EQ','BE') is mandatory: 55 series values share (symbol, as_of_date) and an
# unfiltered aggregate double-counts.
_VWAP_CTE = """
    vwap AS (
        SELECT symbol, sum(turnover) / NULLIF(sum(volume), 0) AS vwap
          FROM nidp.prices_eod
         WHERE series IN ('EQ', 'BE') AND as_of_date >= $1 AND as_of_date < $2
         GROUP BY symbol
    )
"""

_SECTORS_SQL = f"""
    WITH {_UNIVERSE_CTE},
    {_VWAP_CTE},
    d AS (
        SELECT security_isin,
               sum(shares_delta)                                              AS net_shares_delta,
               count(DISTINCT scheme_code) FILTER (WHERE shares_delta > 0)     AS schemes_up,
               count(DISTINCT scheme_code) FILTER (WHERE shares_delta < 0)     AS schemes_dn
          FROM nidp.mf_holdings_deltas
         WHERE current_month = $3 AND previous_month = $4 AND shares_delta IS NOT NULL
         GROUP BY security_isin
    )
    SELECT n5.industry,
           count(*)                                              AS stocks,
           count(v.vwap)                                         AS stocks_priced,
           round(sum(d.net_shares_delta * v.vwap) / 1e7, 0)       AS net_value_cr,
           sum(d.schemes_up)                                     AS schemes_up,
           sum(d.schemes_dn)                                     AS schemes_dn
      FROM n5
      JOIN d    ON d.security_isin = n5.isin
      LEFT JOIN vwap v ON v.symbol = n5.symbol
     GROUP BY n5.industry
     ORDER BY net_value_cr DESC NULLS LAST
"""


@router.get("/smart-money/sectors", summary="Disclosed MF holdings change by industry")
async def smart_money_sectors() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "as_of": None, "previous_month": None,
        "source": "nidp.mf_holdings_deltas x nidp.index_constituents (Nifty 500) x nidp.prices_eod VWAP",
        "disclosure": ("Disclosed monthly portfolios of 11 reporting AMCs -- not 'mutual funds' as a whole, and "
                       "not all institutional flow. Valued at the disclosure month's VWAP. The shareholding "
                       "(FII/DII) leg is deliberately absent: total_shares is NULL in every prior-quarter row, "
                       "so a two-quarter value-weighted delta cannot be computed."),
        "count": 0, "total": 0, "rows": [],
    }
    pool = await get_pool()
    async with pool.acquire() as conn:
        pair = await conn.fetchrow(_MF_PAIR_SQL)
        if pair is None:
            return out
        cur, prv = pair["current_month"], pair["previous_month"]
        nxt = date(cur.year + (cur.month // 12), (cur.month % 12) + 1, 1)
        rows = [row_to_dict(r) for r in await conn.fetch(_SECTORS_SQL, cur, nxt, cur, prv)]

    out["as_of"] = cur.isoformat()
    out["previous_month"] = prv.isoformat()
    out["rows"] = rows
    out["count"] = out["total"] = len(rows)
    return out


# ---------------------------------------------------------------- breadth

# point_in_time = true is mandatory: the table carries both series on the same date and the 'f'
# (reporting-date) series is the look-ahead one the study excluded, measured at 6.72-8.20 points.
_BREADTH_SQL = """
    SELECT count(*)                                                                      AS evaluated,
           count(*) FILTER (WHERE net_shares_delta > 0)                                  AS disclosed_rising,
           count(*) FILTER (WHERE net_shares_delta < 0)                                  AS disclosed_falling,
           count(*) FILTER (WHERE net_shares_delta > 0
                              AND proxy_delivery_pct_avg_20 IS NOT NULL)                  AS rising_direct_and_proxy,
           count(*) FILTER (WHERE net_shares_delta > 0
                              AND proxy_delivery_pct_avg_20 IS NULL)                      AS rising_direct_only,
           count(*) FILTER (WHERE net_shares_delta IS NULL
                              AND proxy_delivery_pct_avg_20 IS NOT NULL)                  AS proxy_only,
           count(*) FILTER (WHERE single_amc_signal)                                      AS single_amc,
           count(*) FILTER (WHERE freshness_status = 'fresh')                             AS fresh,
           count(*) FILTER (WHERE freshness_status = 'ageing')                            AS ageing,
           count(*) FILTER (WHERE freshness_status = 'stale')                             AS stale,
           max(latest_reporting_date)::text                                              AS disclosure_as_of
      FROM nidp.smart_money_scores_daily
     WHERE as_of_date = $1 AND point_in_time IS TRUE
"""


@router.get("/smart-money/breadth", summary="How many names carry disclosed vs proxy-only evidence")
async def smart_money_breadth() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "as_of": None, "disclosure_as_of": None, "validated_study": False,
        "source": "nidp.smart_money_scores_daily (point_in_time series)",
        "disclosure": ("Counts of disclosed-holdings evidence. 'proxy_only' means delivery or volume moved and the "
                       "buyer is unknown -- it is never called accumulation. No score and no rank are served: the "
                       "validation study returned INCONCLUSIVE and no promotion decision is on record."),
        "metrics": None,
    }
    pool = await get_pool()
    async with pool.acquire() as conn:
        day = await conn.fetchval(
            "SELECT max(as_of_date) FROM nidp.smart_money_scores_daily WHERE point_in_time IS TRUE")
        if day is None:
            return out
        row = await conn.fetchrow(_BREADTH_SQL, day)
        # False unless a gate actually passed. It has not.
        out["validated_study"] = bool(await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM nidp.smart_money_promotion_decisions WHERE decision = 'APPROVED')"))

    m = row_to_dict(row) if row else {}
    out["as_of"] = day.isoformat()
    out["disclosure_as_of"] = m.pop("disclosure_as_of", None)
    out["metrics"] = m
    return out


# ---------------------------------------------------------------- scanner

_SCANNER_SQL = f"""
    WITH {_UNIVERSE_CTE},
    mf AS (
        SELECT d.security_isin,
               sum(d.shares_delta)                                              AS net_shares_delta,
               sum(d.previous_shares)                                           AS previous_shares,
               count(DISTINCT d.scheme_code) FILTER (WHERE d.shares_delta > 0)    AS schemes_up,
               count(DISTINCT d.scheme_code) FILTER (WHERE d.shares_delta < 0)    AS schemes_dn,
               count(DISTINCT m.amc_id)      FILTER (WHERE d.shares_delta > 0)    AS amcs_up
          FROM nidp.mf_holdings_deltas d
          JOIN nidp.mf_scheme_master m ON m.scheme_code = d.scheme_code
         WHERE d.current_month = $1 AND d.previous_month = $2 AND d.shares_delta IS NOT NULL
         GROUP BY d.security_isin
    ),
    -- shareholding_pattern is NOT unique on (symbol, period_end): two sources, ~100 duplicate rows
    -- per quarter. Order by value-presence, not by source: NSE_SHP holds NULL institutional columns
    -- at the prior quarter while screener_in holds the number (40 computable deltas vs 73).
    shp AS (
        SELECT DISTINCT ON (symbol, period_end) symbol, period_end, fii_pct, dii_pct
          FROM nidp.shareholding_pattern
         WHERE period_end IN ($3, $4)
         ORDER BY symbol, period_end, (fii_pct IS NOT NULL) DESC, ingested_at DESC
    ),
    inst AS (
        SELECT c.symbol, c.fii_pct - p.fii_pct AS fii_delta_pp, c.dii_pct - p.dii_pct AS dii_delta_pp
          FROM shp c JOIN shp p ON p.symbol = c.symbol AND p.period_end = $4
         WHERE c.period_end = $3 AND c.fii_pct IS NOT NULL AND p.fii_pct IS NOT NULL
    ),
    deals AS (
        SELECT symbol, sum(net_qty) AS deal_net_qty, sum(gross_value_inr) AS deal_gross_inr,
               count(*) AS deal_days, count(*) FILTER (WHERE pure_transfer_day) AS transfer_days
          FROM nidp.v_trendlyne_deals_net
         WHERE deal_date > $5 AND deal_date <= $6
         GROUP BY symbol
    ),
    checked AS (SELECT DISTINCT symbol FROM nidp.trendlyne_deal_fetch_log),
    dl AS (
        SELECT symbol,
               avg(deliv_pct) FILTER (WHERE rn <= 10) AS deliv_10d,
               avg(deliv_pct)                          AS deliv_60d
          FROM (SELECT symbol, deliv_pct,
                       row_number() OVER (PARTITION BY symbol ORDER BY as_of_date DESC) rn
                  FROM nidp.prices_eod
                 WHERE series IN ('EQ', 'BE') AND as_of_date <= $6 AND deliv_pct IS NOT NULL) z
         WHERE rn <= 60
         GROUP BY symbol
    )
    SELECT n5.symbol, n5.industry,
           round(100.0 * mf.net_shares_delta / NULLIF(mf.previous_shares, 0), 2) AS mf_shares_pct_chg,
           mf.net_shares_delta, mf.schemes_up, mf.schemes_dn, mf.amcs_up,
           round(inst.fii_delta_pp, 2) AS fii_delta_pp,
           round(inst.dii_delta_pp, 2) AS dii_delta_pp,
           deals.deal_net_qty, deals.deal_gross_inr, deals.deal_days, deals.transfer_days,
           (checked.symbol IS NOT NULL) AS deals_checked,
           round(dl.deliv_10d, 1) AS deliv_10d, round(dl.deliv_60d, 1) AS deliv_60d,
           round(dl.deliv_10d - dl.deliv_60d, 1) AS deliv_vs_base_pp
      FROM n5
      LEFT JOIN mf      ON mf.security_isin = n5.isin
      LEFT JOIN inst    ON inst.symbol      = n5.symbol
      LEFT JOIN deals   ON deals.symbol     = n5.symbol
      LEFT JOIN checked ON checked.symbol   = n5.symbol
      LEFT JOIN dl      ON dl.symbol        = n5.symbol
     WHERE ($7::text IS NULL OR n5.symbol = $7)
       AND (NOT $8 OR mf.net_shares_delta > 0)
     ORDER BY mf.amcs_up DESC NULLS LAST, mf.schemes_up DESC NULLS LAST, n5.symbol
     LIMIT $9
"""

_QUARTERS_SQL = """
    SELECT DISTINCT period_end FROM nidp.shareholding_pattern
     WHERE fii_pct IS NOT NULL ORDER BY period_end DESC LIMIT 2
"""


@router.get("/smart-money/scanner", summary="One row per Nifty 500 stock: the disclosed evidence behind it")
async def smart_money_scanner(
    symbol: Optional[str] = Query(None, min_length=1, max_length=20, pattern=r"^[A-Za-z0-9&\-]+$"),
    rising_only: bool = Query(False, description="Only names whose disclosed holdings rose"),
    deal_days: int = Query(90, ge=1, le=365, description="Look-back for the deal columns, in calendar days"),
    limit: int = Query(100, ge=1, le=MAX_LIMIT),
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "as_of": None, "previous_month": None, "quarters": None, "deal_window": None,
        "source": ("nidp.mf_holdings_deltas, nidp.shareholding_pattern, nidp.v_trendlyne_deals_net, "
                   "nidp.prices_eod, universe nidp.index_constituents 'Nifty 500'"),
        "disclosure": ("Evidence, not a verdict -- no score and no ranking by one. Ordered by how many AMCs "
                       "raised the holding, which is a disclosure count, not a model output. A null deal column "
                       "with deals_checked=false means the symbol was never queried, NOT that nothing happened. "
                       "Deal legs carry no counterparty classification: a leg may be a market maker, and matched "
                       "same-day transfers are already netted out by the view."),
        "count": 0, "total": 0, "rows": [],
    }
    pool = await get_pool()
    async with pool.acquire() as conn:
        pair = await conn.fetchrow(_MF_PAIR_SQL)
        qs = [r["period_end"] for r in await conn.fetch(_QUARTERS_SQL)]
        end: Optional[date] = await conn.fetchval(
            "SELECT max(as_of_date) FROM nidp.prices_eod WHERE series IN ('EQ','BE')")
        if pair is None or len(qs) < 2 or end is None:
            return out
        cur, prv = pair["current_month"], pair["previous_month"]
        start = end - timedelta(days=deal_days)
        rows = [row_to_dict(r) for r in await conn.fetch(
            _SCANNER_SQL, cur, prv, qs[0], qs[1], start, end,
            symbol.upper() if symbol else None, rising_only, limit)]

    out["as_of"] = cur.isoformat()
    out["previous_month"] = prv.isoformat()
    out["quarters"] = {"current": qs[0].isoformat(), "previous": qs[1].isoformat()}
    out["deal_window"] = {"from": start.isoformat(), "to": end.isoformat()}
    out["rows"] = rows
    out["count"] = out["total"] = len(rows)
    return out
