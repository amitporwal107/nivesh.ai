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
from nidp.services.daas_api.responses import jsonify, row_to_dict


def jsonify_num(v: Any) -> Any:
    """A flow total is a Decimal or None; the contract is a number or null, never 0 for absent."""
    return None if v is None else jsonify(v)

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


# ---------------------------------------------------------------- periods

# The design's period toggle (spec 2.1). Each window implies a *disclosure* window per leg, and the
# legs do not all reach as far back:
#   flows / deals / delivery  recompute at every period
#   shareholding              1, 1, 2 and 4 quarters back -- present but thin (~160 rows a quarter)
#   MF holdings               only ONE pair exists (months_back = 1, 4,189 ISINs). The 4- and 5-month
#                             pairs cover 103 and 93 ISINs, so honouring a 6M request with the
#                             5-month pair would collapse the scanner from 4,189 names to 93.
# So the MF leg uses the richest pair and the response reports `mf_window` requested vs actual. The
# column states its own window rather than implying it moved with the toggle.
_PERIODS: Dict[str, Dict[str, int]] = {
    "1M": {"mf_months": 1,  "quarters_back": 1, "deal_days": 30,  "sessions": 22},
    "3M": {"mf_months": 3,  "quarters_back": 1, "deal_days": 90,  "sessions": 63},
    "6M": {"mf_months": 6,  "quarters_back": 2, "deal_days": 180, "sessions": 126},
    "1Y": {"mf_months": 12, "quarters_back": 4, "deal_days": 365, "sessions": 248},
}

# The universe options that actually exist as constituent lists. The design offered "Nifty 1000",
# which NSE does not publish and this warehouse does not hold; Nifty Total Market (755) is the
# nearest real list and is offered under its own name rather than a label that implies 1,000 names.
_UNIVERSES: Dict[str, str] = {
    "nifty50": "Nifty 50",
    "nifty100": "Nifty 100",
    "nifty200": "Nifty 200",
    "nifty500": "Nifty 500",
    "total": "Nifty Total Market",
}

# Every disclosed pair for the newest disclosure month, richest first. Picking by coverage rather
# than by "closest to what was asked" is deliberate -- see the note on _PERIODS.
_MF_PAIRS_SQL = """
    SELECT previous_month,
           (EXTRACT(YEAR FROM current_month) * 12 + EXTRACT(MONTH FROM current_month))
         - (EXTRACT(YEAR FROM previous_month) * 12 + EXTRACT(MONTH FROM previous_month)) AS months_back,
           count(*) AS rows
      FROM nidp.mf_holdings_deltas
     WHERE current_month = $1 AND previous_month IS NOT NULL
     GROUP BY current_month, previous_month
     ORDER BY rows DESC
"""

_LATEST_MF_MONTH_SQL = "SELECT max(current_month) FROM nidp.mf_holdings_deltas"

# Quarters that actually carry an institutional column, newest first.
_QUARTERS_SQL = """
    SELECT DISTINCT period_end FROM nidp.shareholding_pattern
     WHERE fii_pct IS NOT NULL ORDER BY period_end DESC LIMIT 8
"""


async def _mf_pair(conn, want_months: int):
    """(current, previous, actual_months_back) for the richest disclosed pair, or None."""
    cur = await conn.fetchval(_LATEST_MF_MONTH_SQL)
    if cur is None:
        return None
    pairs = await conn.fetch(_MF_PAIRS_SQL, cur)
    if not pairs:
        return None
    exact = next((p for p in pairs if int(p["months_back"]) == want_months), None)
    chosen = exact or pairs[0]          # pairs[0] is the widest-coverage pair
    return cur, chosen["previous_month"], int(chosen["months_back"])


_SECTORS_SQL = """
    WITH n5 AS (
        SELECT DISTINCT symbol, isin, industry
          FROM nidp.index_constituents
         WHERE index_name = $5
           AND as_of_date = (SELECT max(as_of_date) FROM nidp.index_constituents WHERE index_name = $5)
           AND symbol <> 'DUMMYHEG'
    ),
    vwap AS (
        SELECT symbol, sum(turnover) / NULLIF(sum(volume), 0) AS vwap
          FROM nidp.prices_eod
         WHERE series IN ('EQ', 'BE') AND as_of_date >= $1 AND as_of_date < $2
         GROUP BY symbol
    ),
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
async def smart_money_sectors(
    window: str = Query("3M", pattern="^(1M|3M|6M|1Y)$"),
    universe: str = Query("nifty500", pattern="^(nifty50|nifty100|nifty200|nifty500|total)$"),
) -> Dict[str, Any]:
    per = _PERIODS[window]
    index_name = _UNIVERSES[universe]
    out: Dict[str, Any] = {
        "as_of": None, "previous_month": None, "window": window, "universe": universe,
        "index_name": index_name, "mf_window": None,
        "source": "nidp.mf_holdings_deltas x nidp.index_constituents x nidp.prices_eod VWAP",
        "disclosure": ("Disclosed monthly portfolios of 11 reporting AMCs -- not 'mutual funds' as a whole, and "
                       "not all institutional flow. Valued at the disclosure month's VWAP. The shareholding "
                       "(FII/DII) leg is deliberately absent: total_shares is NULL in every prior-quarter row, "
                       "so a two-quarter value-weighted delta cannot be computed."),
        "count": 0, "total": 0, "rows": [],
    }
    pool = await get_pool()
    async with pool.acquire() as conn:
        pair = await _mf_pair(conn, per["mf_months"])
        if pair is None:
            return out
        cur, prv, actual = pair
        nxt = date(cur.year + (cur.month // 12), (cur.month % 12) + 1, 1)
        rows = [row_to_dict(r) for r in await conn.fetch(_SECTORS_SQL, cur, nxt, cur, prv, index_name)]

    out["as_of"] = cur.isoformat()
    out["previous_month"] = prv.isoformat()
    out["mf_window"] = {"requested_months": per["mf_months"], "actual_months": actual,
                        "exact": actual == per["mf_months"]}
    out["rows"] = rows
    out["count"] = out["total"] = len(rows)
    return out


# ---------------------------------------------------------------- breadth

# point_in_time = true is mandatory: the table carries both series on the same date and the 'f'
# (reporting-date) series is the look-ahead one the study excluded, measured at 6.72-8.20 points.
# Omitting it roughly doubles every count below.
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

# Evidence class is DERIVED here, never read from the stored evidence_class column (a hardcoded
# literal 'A' on every row). coverage_pct is likewise not served: it is a constant 100.00.
#   D  a disclosed holdings change and a surviving deal leg agree
#   A  a disclosed holdings change
#   B  a disclosed deal leg, net of matched transfers
#   C  a market proxy only -- buyer unknown, never called accumulation
_SCANNER_SQL = """
    WITH n5 AS (
        SELECT DISTINCT symbol, isin, industry
          FROM nidp.index_constituents
         WHERE index_name = $7
           AND as_of_date = (SELECT max(as_of_date) FROM nidp.index_constituents WHERE index_name = $7)
           AND symbol <> 'DUMMYHEG'
    ),
    -- Per house first, so "how many houses raised" means their NET and not "had any scheme raise".
    -- GLENMARK is why: 9 houses had a scheme raise, but on net 3 raised and 6 cut, and one house
    -- (quant, +11,650,536) exceeded the entire +9,602,244 net on its own.
    mf_amc AS (
        SELECT d.security_isin, m.amc_id,
               sum(d.shares_delta) AS amc_delta,
               count(DISTINCT d.scheme_code) FILTER (WHERE d.shares_delta > 0) AS schemes_up,
               count(DISTINCT d.scheme_code) FILTER (WHERE d.shares_delta < 0) AS schemes_dn
          FROM nidp.mf_holdings_deltas d
          JOIN nidp.mf_scheme_master m ON m.scheme_code = d.scheme_code
         WHERE d.current_month = $1 AND d.previous_month = $2 AND d.shares_delta IS NOT NULL
         GROUP BY d.security_isin, m.amc_id
    ),
    mf AS (
        SELECT a.security_isin,
               sum(a.amc_delta)                                     AS net_shares_delta,
               sum(a.schemes_up)                                    AS schemes_up,
               sum(a.schemes_dn)                                    AS schemes_dn,
               count(*) FILTER (WHERE a.amc_delta > 0)              AS amcs_up,
               count(*) FILTER (WHERE a.amc_delta < 0)              AS amcs_dn,
               count(*)                                             AS amcs_holding,
               -- The largest single contribution, as a share of the net move. Above 100% means one
               -- house more than accounts for it and the rest are net sellers.
               round(100.0 * max(a.amc_delta) / NULLIF(sum(a.amc_delta), 0), 0) AS top_amc_pct_of_move
          FROM mf_amc a
         GROUP BY a.security_isin
    ),
    mf_prev AS (
        SELECT security_isin, sum(previous_shares) AS previous_shares
          FROM nidp.mf_holdings_deltas
         WHERE current_month = $1 AND previous_month = $2 AND shares_delta IS NOT NULL
         GROUP BY security_isin
    ),
    -- shareholding_pattern is NOT unique on (symbol, period_end): two sources, ~100 duplicate rows
    -- per quarter. Order by value-presence, not by source name: NSE_SHP holds NULL institutional
    -- columns at the prior quarter while screener_in holds the number (40 deltas vs 73).
    shp AS (
        SELECT DISTINCT ON (symbol, period_end) symbol, period_end, fii_pct, dii_pct
          FROM nidp.shareholding_pattern
         WHERE period_end IN ($3, $4)
         ORDER BY symbol, period_end, (fii_pct IS NOT NULL) DESC, ingested_at DESC
    ),
    -- Where BOTH sources carry a figure they can disagree, and picking the most recently ingested
    -- is arbitrary. Measured on 2026-09-30: 103 of 129 agree exactly, 21 within 0.5pp, but 5
    -- differ by more and ICICIBANK differs by 15.76pp (NSE_SHP 50.44 vs screener_in 34.68). The
    -- spread rides with the row so a contested figure can be shown as contested, not as fact.
    shp_spread AS (
        SELECT symbol, max(spread) AS fii_spread_pp
          FROM (SELECT symbol, period_end, max(fii_pct) - min(fii_pct) AS spread
                  FROM nidp.shareholding_pattern
                 WHERE period_end IN ($3, $4) AND fii_pct IS NOT NULL
                 GROUP BY symbol, period_end
                HAVING count(DISTINCT source) > 1) z
         GROUP BY symbol
    ),
    inst AS (
        SELECT c.symbol, c.fii_pct - p.fii_pct AS fii_delta_pp, c.dii_pct - p.dii_pct AS dii_delta_pp
          FROM shp c JOIN shp p ON p.symbol = c.symbol AND p.period_end = $4
         WHERE c.period_end = $3 AND c.fii_pct IS NOT NULL AND p.fii_pct IS NOT NULL
    ),
    deals AS (
        SELECT symbol, sum(net_qty) AS deal_net_qty, sum(gross_value_inr) AS deal_gross_inr,
               sum(legs) AS deal_legs, sum(offsetting_legs) AS matched_legs,
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
    ),
    px AS (
        SELECT DISTINCT ON (symbol) symbol, close_price, prev_close
          FROM nidp.prices_eod
         WHERE series IN ('EQ', 'BE') AND as_of_date <= $6
         ORDER BY symbol, as_of_date DESC
    ),
    fr AS (
        SELECT symbol, freshness_status, single_amc_signal, latest_reporting_date
          FROM nidp.smart_money_scores_daily
         WHERE point_in_time IS TRUE
           AND as_of_date = (SELECT max(as_of_date) FROM nidp.smart_money_scores_daily
                              WHERE point_in_time IS TRUE)
    ),
    base AS (
        SELECT n5.symbol, n5.industry,
               mf.net_shares_delta, mp.previous_shares, mf.schemes_up, mf.schemes_dn, mf.amcs_up,
               mf.amcs_dn, mf.amcs_holding, mf.top_amc_pct_of_move,
               inst.fii_delta_pp, inst.dii_delta_pp,
               deals.deal_net_qty, deals.deal_gross_inr, deals.deal_legs, deals.matched_legs,
               deals.deal_days, deals.transfer_days,
               (checked.symbol IS NOT NULL) AS deals_checked,
               dl.deliv_10d, dl.deliv_60d,
               px.close_price, px.prev_close,
               fr.freshness_status, fr.single_amc_signal, fr.latest_reporting_date,
               round(sp.fii_spread_pp, 2) AS fii_spread_pp,
               CASE
                 WHEN coalesce(mf.net_shares_delta, 0) <> 0 AND coalesce(deals.deal_net_qty, 0) <> 0 THEN 'D'
                 WHEN coalesce(mf.net_shares_delta, 0) <> 0 THEN 'A'
                 WHEN coalesce(deals.deal_net_qty, 0) <> 0 THEN 'B'
                 WHEN dl.deliv_10d IS NOT NULL AND dl.deliv_60d IS NOT NULL THEN 'C'
                 ELSE 'none'
               END AS evidence
          FROM n5
          LEFT JOIN mf      ON mf.security_isin = n5.isin
          LEFT JOIN mf_prev mp ON mp.security_isin = n5.isin
          LEFT JOIN inst    ON inst.symbol      = n5.symbol
          LEFT JOIN deals   ON deals.symbol     = n5.symbol
          LEFT JOIN checked ON checked.symbol   = n5.symbol
          LEFT JOIN dl      ON dl.symbol        = n5.symbol
          LEFT JOIN px      ON px.symbol        = n5.symbol
          LEFT JOIN fr      ON fr.symbol        = n5.symbol
          LEFT JOIN shp_spread sp ON sp.symbol = n5.symbol
    ),
    -- The lane counts are computed BEFORE the lane filter, so an empty lane can say "none in this
    -- universe" instead of looking broken. In Nifty 500 the proxy lane is legitimately 0: every
    -- name there has a disclosed MF delta, so nothing is proxy-only. Nifty Total Market has all four.
    filtered AS (
        SELECT *,
               count(*) OVER ()                                           AS matched_total,
               count(*) FILTER (WHERE evidence IN ('A', 'B', 'D')) OVER () AS lane_disclosed,
               count(*) FILTER (WHERE evidence = 'C') OVER ()              AS lane_proxy,
               count(*) FILTER (WHERE evidence = 'A') OVER ()              AS class_a,
               count(*) FILTER (WHERE evidence = 'B') OVER ()              AS class_b,
               count(*) FILTER (WHERE evidence = 'C') OVER ()              AS class_c,
               count(*) FILTER (WHERE evidence = 'D') OVER ()              AS class_d
          FROM base
         WHERE ($8::text  IS NULL OR industry = $8)
           AND ($12::text IS NULL OR symbol   = $12)
           AND ($9 = 'all' OR ($9 = 'accumulation'  AND net_shares_delta > 0)
                           OR ($9 = 'distribution' AND net_shares_delta < 0))
           AND ($11 = 'any' OR freshness_status = $11)
           AND evidence <> 'none'
    )
    SELECT symbol, industry,
           round(100.0 * net_shares_delta / NULLIF(previous_shares, 0), 2) AS mf_shares_pct_chg,
           net_shares_delta, schemes_up, schemes_dn, amcs_up, amcs_dn, amcs_holding,
           top_amc_pct_of_move,
           round(fii_delta_pp, 2) AS fii_delta_pp, round(dii_delta_pp, 2) AS dii_delta_pp,
           deal_net_qty, deal_gross_inr, deal_legs, matched_legs, deal_days, transfer_days,
           deals_checked,
           round(deliv_10d, 1) AS deliv_10d, round(deliv_60d, 1) AS deliv_60d,
           round(deliv_10d - deliv_60d, 1) AS deliv_vs_base_pp,
           close_price, prev_close,
           round(100.0 * (close_price - prev_close) / NULLIF(prev_close, 0), 2) AS change_pct,
           freshness_status, single_amc_signal, latest_reporting_date,
           fii_spread_pp,
           evidence,
           matched_total, lane_disclosed, lane_proxy, class_a, class_b, class_c, class_d,
           count(*) OVER () AS lane_total
      FROM filtered
     WHERE ($10 = 'all' OR ($10 = 'disclosed' AND evidence IN ('A', 'B', 'D'))
                        OR ($10 = 'proxy'     AND evidence = 'C'))
     -- Spec 2.6: evidence classes first, then scheme breadth. NEVER by a score.
     ORDER BY CASE evidence WHEN 'D' THEN 0 WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END,
              amcs_up DESC NULLS LAST, schemes_up DESC NULLS LAST, symbol
     LIMIT $13
"""


@router.get("/smart-money/scanner", summary="One row per stock: the disclosed evidence behind it")
async def smart_money_scanner(
    window: str = Query("3M", pattern="^(1M|3M|6M|1Y)$"),
    universe: str = Query("nifty500", pattern="^(nifty50|nifty100|nifty200|nifty500|total)$"),
    sector: Optional[str] = Query(None, min_length=2, max_length=60, pattern=r"^[A-Za-z0-9 &\-]+$"),
    direction: str = Query("all", pattern="^(all|accumulation|distribution)$"),
    lane: str = Query("all", pattern="^(all|disclosed|proxy)$"),
    freshness: str = Query("any", pattern="^(any|fresh|ageing|stale)$"),
    symbol: Optional[str] = Query(None, min_length=1, max_length=20, pattern=r"^[A-Za-z0-9&\-]+$"),
    limit: int = Query(100, ge=1, le=MAX_LIMIT),
) -> Dict[str, Any]:
    per = _PERIODS[window]
    index_name = _UNIVERSES[universe]
    out: Dict[str, Any] = {
        "as_of": None, "previous_month": None, "window": window, "universe": universe,
        "index_name": index_name, "mf_window": None, "quarters": None, "deal_window": None,
        "filters": {"sector": sector, "direction": direction, "lane": lane, "freshness": freshness},
        "source": ("nidp.mf_holdings_deltas, nidp.shareholding_pattern, nidp.v_trendlyne_deals_net, "
                   "nidp.prices_eod, nidp.smart_money_scores_daily, universe nidp.index_constituents"),
        "disclosure": ("Evidence, not a verdict -- no score and no ranking by one. Ordered by evidence class, "
                       "then by how many AMCs raised the holding, which is a disclosure count. A null deal "
                       "column with deals_checked=false means the symbol was never queried, NOT that nothing "
                       "happened. Deal legs carry no counterparty classification: a leg may be a market maker, "
                       "and matched same-day transfers are already netted out by the view. Where two sources "
                       "disclose different FII percentages for the same quarter, `fii_spread_pp` carries the gap "
                       "and the figure is contested, not settled."),
        "count": 0, "total": 0, "matched": 0,
        "lanes": {"disclosed": 0, "proxy": 0, "all": 0},
        "classes": {"A": 0, "B": 0, "C": 0, "D": 0},
        "rows": [],
    }
    pool = await get_pool()
    async with pool.acquire() as conn:
        pair = await _mf_pair(conn, per["mf_months"])
        qs = [r["period_end"] for r in await conn.fetch(_QUARTERS_SQL)]
        end: Optional[date] = await conn.fetchval(
            "SELECT max(as_of_date) FROM nidp.prices_eod WHERE series IN ('EQ','BE')")
        if pair is None or len(qs) < 2 or end is None:
            return out
        cur, prv, actual = pair
        # The requested quarter offset if it is disclosed, else the oldest that is.
        qi = min(per["quarters_back"], len(qs) - 1)
        q_cur, q_prv = qs[0], qs[qi]
        start = end - timedelta(days=per["deal_days"])
        rows = [row_to_dict(r) for r in await conn.fetch(
            _SCANNER_SQL, cur, prv, q_cur, q_prv, start, end, index_name, sector,
            direction, lane, freshness, symbol.upper() if symbol else None, limit)]
        # An empty lane is exactly when the counts matter: "0 of 500 are proxy-only" is an answer,
        # all-zeros is not. The window counts ride on the rows, so on the empty path read them
        # from one row of the same query with the lane filter lifted.
        counts = rows[0] if rows else next(iter([row_to_dict(r) for r in await conn.fetch(
            _SCANNER_SQL, cur, prv, q_cur, q_prv, start, end, index_name, sector,
            direction, "all", freshness, symbol.upper() if symbol else None, 1)] or [{}]), {})

    out["as_of"] = cur.isoformat()
    out["previous_month"] = prv.isoformat()
    out["mf_window"] = {"requested_months": per["mf_months"], "actual_months": actual,
                        "exact": actual == per["mf_months"]}
    out["quarters"] = {"current": q_cur.isoformat(), "previous": q_prv.isoformat(),
                       "requested_back": per["quarters_back"], "actual_back": qi,
                       "exact": qi == per["quarters_back"]}
    out["deal_window"] = {"from": start.isoformat(), "to": end.isoformat(), "days": per["deal_days"]}
    meta = ("matched_total", "lane_disclosed", "lane_proxy", "class_a", "class_b", "class_c",
            "class_d", "lane_total")
    out["rows"] = [{k: v for k, v in r.items() if k not in meta} for r in rows]
    out["count"] = len(out["rows"])
    out["total"] = int(rows[0]["lane_total"]) if rows else 0
    if counts:
        # Counts before the lane filter, so an empty lane is explainable rather than mysterious.
        out["matched"] = int(counts["matched_total"])
        out["lanes"] = {"disclosed": int(counts["lane_disclosed"]), "proxy": int(counts["lane_proxy"]),
                        "all": int(counts["matched_total"])}
        out["classes"] = {"A": int(counts["class_a"]), "B": int(counts["class_b"]),
                          "C": int(counts["class_c"]), "D": int(counts["class_d"])}
    return out

# ---------------------------------------------------------------- AMC contribution

# Which fund HOUSES drive a stock's disclosed change. "11 AMCs" is a coverage statistic; it does
# not say whether the buying is broad-based or one house, and that is the question this answers.
#
# An AMC is not one portfolio: every scheme it runs is aggregated here, and the stock is resolved by
# ISIN so a symbol change cannot split a house in two. `share_of_disclosed_pct` is each house's
# share of the stock's TOTAL disclosed MF holding, which is the contribution figure — a house can
# hold a lot and have changed nothing, or hold little and account for the whole month's move.
#
# Two things this deliberately does NOT serve:
#   * Holding as a % of the AMC's equity AUM. No AUM series is ingested; inventing a denominator
#     would be worse than omitting the column.
#   * A change in holding VALUE. previous/current_market_value_inr exist, but differencing them
#     mixes price movement into what reads as buying. The share-count delta is the honest figure,
#     and the value column below is a LEVEL (what is held now), never a delta.
_AMC_SQL = """
    WITH d AS (
        SELECT d.scheme_code, d.current_shares, d.previous_shares, d.shares_delta,
               d.current_market_value_inr, d.weight_delta_pp, m.amc_id, m.amc_name_raw
          FROM nidp.mf_holdings_deltas d
          JOIN nidp.mf_scheme_master m ON m.scheme_code = d.scheme_code
         WHERE d.current_month = $1 AND d.previous_month = $2 AND d.security_isin = $3
    ),
    tot AS (SELECT sum(current_shares) AS all_shares FROM d)
    SELECT d.amc_id,
           max(d.amc_name_raw)                                              AS amc_name,
           count(DISTINCT d.scheme_code)                                    AS schemes,
           count(DISTINCT d.scheme_code) FILTER (WHERE d.shares_delta > 0)   AS schemes_up,
           count(DISTINCT d.scheme_code) FILTER (WHERE d.shares_delta < 0)   AS schemes_dn,
           count(DISTINCT d.scheme_code) FILTER (WHERE coalesce(d.shares_delta, 0) = 0) AS schemes_flat,
           sum(d.current_shares)                                            AS current_shares,
           sum(d.previous_shares)                                           AS previous_shares,
           sum(d.shares_delta)                                              AS shares_delta,
           round(100.0 * sum(d.shares_delta) / NULLIF(sum(d.previous_shares), 0), 2) AS shares_pct_change,
           -- A LEVEL, not a delta. NULL when no scheme disclosed a value (UTI does this).
           round(sum(d.current_market_value_inr) / 1e7, 1)                   AS current_value_cr,
           count(d.current_market_value_inr)                                AS value_disclosed_schemes,
           round(100.0 * sum(d.current_shares) / NULLIF((SELECT all_shares FROM tot), 0), 1)
                                                                            AS share_of_disclosed_pct,
           round(sum(d.weight_delta_pp), 3)                                 AS weight_delta_pp
      FROM d
     GROUP BY d.amc_id
     ORDER BY abs(coalesce(sum(d.shares_delta), 0)) DESC, sum(d.current_shares) DESC NULLS LAST
"""

# Shares outstanding, newest quarter that discloses one. Absent for ~160 of 2,132 names, in which
# case the equity-percentage is null and the UI says it is undisclosed rather than showing 0.
_SHARES_OUTSTANDING_SQL = """
    SELECT total_shares FROM nidp.shareholding_pattern
     WHERE symbol = $1 AND total_shares IS NOT NULL
     ORDER BY period_end DESC LIMIT 1
"""

_ISIN_SQL = """
    SELECT isin FROM nidp.index_constituents
     WHERE symbol = $1 AND isin IS NOT NULL
     ORDER BY as_of_date DESC LIMIT 1
"""


@router.get("/smart-money/amc", summary="Which fund houses drive one stock's disclosed change")
async def smart_money_amc(
    symbol: str = Query(..., min_length=1, max_length=20, pattern=r"^[A-Za-z0-9&\-]+$"),
) -> Dict[str, Any]:
    sym = symbol.upper()
    out: Dict[str, Any] = {
        "symbol": sym, "isin": None, "as_of": None, "previous_month": None, "mf_window": None,
        "source": "nidp.mf_holdings_deltas x nidp.mf_scheme_master, shares outstanding from nidp.shareholding_pattern",
        "disclosure": ("Every scheme a house runs, aggregated, with the stock resolved by ISIN. "
                       "`share_of_disclosed_pct` is the house's share of this stock's total DISCLOSED "
                       "mutual-fund holding, not of its equity. Holding as a percentage of the AMC's own "
                       "equity AUM is not served: no AUM series is ingested. The value column is a level "
                       "(what is held now), never a change, because differencing two months of market "
                       "value mixes price movement into what would read as buying."),
        "totals": None, "count": 0, "rows": [],
    }
    pool = await get_pool()
    async with pool.acquire() as conn:
        isin = await conn.fetchval(_ISIN_SQL, sym)
        pair = await _mf_pair(conn, 1)
        if isin is None or pair is None:
            return out
        cur, prv, actual = pair
        rows = [row_to_dict(r) for r in await conn.fetch(_AMC_SQL, cur, prv, isin)]
        shares_out = await conn.fetchval(_SHARES_OUTSTANDING_SQL, sym)

    out["isin"] = isin
    out["as_of"] = cur.isoformat()
    out["previous_month"] = prv.isoformat()
    out["mf_window"] = {"requested_months": 1, "actual_months": actual, "exact": actual == 1}
    out["rows"] = rows
    out["count"] = len(rows)

    held = sum(float(r["current_shares"] or 0) for r in rows)
    delta = sum(float(r["shares_delta"] or 0) for r in rows)
    val = [r["current_value_cr"] for r in rows if r["current_value_cr"] is not None]
    # The largest HOLDER, not the largest mover. rows are ordered by |shares_delta| so that the
    # month's movers lead the table; taking rows[0] here reported the biggest buyer's share as if
    # it were the concentration figure (BSE: ICICI 26.1% instead of Nippon's 29.5%).
    shares = [r["share_of_disclosed_pct"] for r in rows if r["share_of_disclosed_pct"] is not None]
    top = max(shares) if shares else None
    out["totals"] = {
        "amcs": len(rows),
        "schemes": sum(int(r["schemes"] or 0) for r in rows),
        "schemes_up": sum(int(r["schemes_up"] or 0) for r in rows),
        "schemes_dn": sum(int(r["schemes_dn"] or 0) for r in rows),
        "current_shares": held or None,
        "shares_delta": delta or None,
        # Only the schemes that disclosed one; the rest are absent, not zero.
        "current_value_cr": round(sum(float(v) for v in val), 1) if val else None,
        "value_disclosed_schemes": sum(int(r["value_disclosed_schemes"] or 0) for r in rows),
        "shares_outstanding": float(shares_out) if shares_out else None,
        "pct_of_equity": round(100.0 * held / float(shares_out), 2) if shares_out and held else None,
        # The concentration answer: how much of the disclosed holding sits with the largest house.
        "largest_amc_share_pct": top,
    }
    return out

# ---------------------------------------------------------------- summary KPIs

# The design's four headline cards. Each carries its own comparison, because the four do not share
# one: cash flows compare an equally-long preceding window, the holdings cards compare the previous
# SCORING DATE (the table is monthly-cadence, not daily), and the shareholding card has no prior at
# all — only two quarters disclose an institutional column, so there is nothing to compare against.
#
# The design's fourth card read "42 (out of 500)". That denominator is wrong: only 89 of the 500
# disclose an FII percentage in BOTH quarters, so the count is served against 89 with the universe
# size beside it. Hiding the gap behind the index size would overstate coverage five-fold.
_FLOW_WINDOW_SQL = """
    SELECT sum(net_value_cr) FILTER (WHERE category = 'FII') AS fii,
           sum(net_value_cr) FILTER (WHERE category = 'DII') AS dii
      FROM nidp.fii_dii_flows
     WHERE source = $1 AND segment = 'EQUITY_CASH' AND category IN ('FII', 'DII')
       AND as_of_date > $2 AND as_of_date <= $3
"""

# One point per scoring date: the holdings cards' sparkline and their previous value.
_RISING_SERIES_SQL = """
    SELECT as_of_date::text AS date,
           count(*)                                    AS evaluated,
           count(*) FILTER (WHERE net_shares_delta > 0) AS rising,
           round(100.0 * count(*) FILTER (WHERE net_shares_delta > 0) / NULLIF(count(*), 0), 1) AS rising_pct
      FROM nidp.smart_money_scores_daily
     WHERE point_in_time IS TRUE
     GROUP BY as_of_date
     ORDER BY as_of_date DESC
     LIMIT 12
"""

_FII_RISING_SQL = """
    WITH n5 AS (
        SELECT DISTINCT symbol FROM nidp.index_constituents
         WHERE index_name = $1
           AND as_of_date = (SELECT max(as_of_date) FROM nidp.index_constituents WHERE index_name = $1)
           AND symbol <> 'DUMMYHEG'
    ),
    shp AS (
        SELECT DISTINCT ON (symbol, period_end) symbol, period_end, fii_pct
          FROM nidp.shareholding_pattern
         WHERE period_end IN ($2, $3)
         ORDER BY symbol, period_end, (fii_pct IS NOT NULL) DESC, ingested_at DESC
    ),
    d AS (
        SELECT c.symbol, c.fii_pct - p.fii_pct AS dpp
          FROM shp c JOIN shp p ON p.symbol = c.symbol AND p.period_end = $3
         WHERE c.period_end = $2 AND c.fii_pct IS NOT NULL AND p.fii_pct IS NOT NULL
    )
    SELECT (SELECT count(*) FROM n5)                  AS universe,
           count(*)                                   AS disclosed,
           count(*) FILTER (WHERE d.dpp > 0)          AS rising,
           count(*) FILTER (WHERE d.dpp < 0)          AS falling
      FROM d JOIN n5 ON n5.symbol = d.symbol
"""


@router.get("/smart-money/summary", summary="The four headline figures, each with its own comparison")
async def smart_money_summary(
    window: str = Query("3M", pattern="^(1M|3M|6M|1Y)$"),
    universe: str = Query("nifty500", pattern="^(nifty50|nifty100|nifty200|nifty500|total)$"),
) -> Dict[str, Any]:
    per = _PERIODS[window]
    index_name = _UNIVERSES[universe]
    source, grain, back = _WINDOWS[window]
    out: Dict[str, Any] = {
        "window": window, "universe": universe, "index_name": index_name, "grain": grain,
        "as_of": None,
        "source": "nidp.fii_dii_flows, nidp.smart_money_scores_daily, nidp.shareholding_pattern",
        "disclosure": ("Each figure carries its OWN comparison, because the four do not share one: cash "
                       "flows compare an equally long preceding window, the holdings figures compare the "
                       "previous scoring date, and the shareholding figure has no prior period at all. "
                       "A percentage change is not served on a net flow that can cross zero."),
        "fii": None, "dii": None, "mf_rising": None, "fii_rising": None,
    }
    pool = await get_pool()
    async with pool.acquire() as conn:
        end: Optional[date] = await conn.fetchval(
            "SELECT max(as_of_date) FROM nidp.fii_dii_flows WHERE source = $1 AND segment = 'EQUITY_CASH'", source)
        if end is not None:
            if back is None:
                tm = end.year * 12 + end.month - 11
                start = date((tm - 1) // 12, (tm - 1) % 12 + 1, 1)
                span = (end - start).days
                prev_start = date(start.year - 1, start.month, 1)
            else:
                start, span = end - back, back.days
                prev_start = start - timedelta(days=span)
            cur = await conn.fetchrow(_FLOW_WINDOW_SQL, source, start, end)
            prv = await conn.fetchrow(_FLOW_WINDOW_SQL, source, prev_start, start)
            out["as_of"] = end.isoformat()
            for key in ("fii", "dii"):
                now_v, was_v = (cur or {}).get(key), (prv or {}).get(key)
                out[key] = {
                    "net_cr": jsonify_num(now_v), "previous_net_cr": jsonify_num(was_v),
                    "change_cr": jsonify_num(None if now_v is None or was_v is None else now_v - was_v),
                    "window_from": start.isoformat(), "previous_from": prev_start.isoformat(),
                }

        series = [row_to_dict(r) for r in await conn.fetch(_RISING_SERIES_SQL)]
        if series:
            now, was = series[0], (series[1] if len(series) > 1 else None)
            out["mf_rising"] = {
                "as_of": now["date"], "pct": now["rising_pct"], "count": now["rising"],
                "evaluated": now["evaluated"],
                "previous_as_of": was["date"] if was else None,
                "previous_pct": was["rising_pct"] if was else None,
                "change_pp": (round(float(now["rising_pct"]) - float(was["rising_pct"]), 1)
                              if was and now["rising_pct"] is not None and was["rising_pct"] is not None else None),
                # Oldest-first for a sparkline.
                "series": list(reversed(series)),
            }

        qs = [r["period_end"] for r in await conn.fetch(_QUARTERS_SQL)]
        if len(qs) >= 2:
            qi = min(per["quarters_back"], len(qs) - 1)
            r = await conn.fetchrow(_FII_RISING_SQL, index_name, qs[0], qs[qi])
            if r is not None:
                out["fii_rising"] = {
                    **row_to_dict(r),
                    "current_quarter": qs[0].isoformat(), "previous_quarter": qs[qi].isoformat(),
                    # No prior period exists: only two quarters carry an institutional column.
                    "previous_count": None, "change": None,
                }
    return out
