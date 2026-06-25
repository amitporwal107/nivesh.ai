"""Market Pulse feeds — FII/DII history, the corporate-action calendar,
classified-filing articles, and cap-segmented movers.

These read the NIDP data lake directly (NIDP_POSTGRES_URL → the populated
nidp_staging / prod DB), so the Nivesh app can source the Market Pulse tabs
over DaaS instead of its own application Postgres (which carries the nidp.*
schema but none of the ingested rows). Shapes mirror exactly what the app's
/api/markets/* endpoints return, so the app layer is a thin pass-through.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key

router = APIRouter(prefix="/market-pulse", tags=["market-pulse"],
                   dependencies=[Depends(require_api_key)])


def _f(v) -> Optional[float]:
    return round(float(v), 2) if v is not None else None


# ════════════════════════════════════════════════════════════════════════
# FII / DII — daily series + monthly aggregates (EQUITY_CASH), ₹ crore
# ════════════════════════════════════════════════════════════════════════

def _fd_row(r) -> Dict[str, Any]:
    return {
        "fii_buy":  _f(r["fii_buy"]),  "fii_sell": _f(r["fii_sell"]),  "fii_net": _f(r["fii_net"]),
        "dii_buy":  _f(r["dii_buy"]),  "dii_sell": _f(r["dii_sell"]),  "dii_net": _f(r["dii_net"]),
    }


@router.get("/fii-dii", summary="FII/DII cash flows — daily series + monthly aggregates")
async def fii_dii(days: int = Query(90, ge=7, le=365)):
    daily_sql = """
        SELECT as_of_date,
               SUM(buy_value_cr)  FILTER (WHERE category='FII') AS fii_buy,
               SUM(sell_value_cr) FILTER (WHERE category='FII') AS fii_sell,
               SUM(net_value_cr)  FILTER (WHERE category='FII') AS fii_net,
               SUM(buy_value_cr)  FILTER (WHERE category='DII') AS dii_buy,
               SUM(sell_value_cr) FILTER (WHERE category='DII') AS dii_sell,
               SUM(net_value_cr)  FILTER (WHERE category='DII') AS dii_net
          FROM nidp.fii_dii_flows
         WHERE segment='EQUITY_CASH' AND category IN ('FII','DII')
           AND as_of_date >= (current_date - $1::int)
         GROUP BY as_of_date
         ORDER BY as_of_date DESC
    """
    monthly_sql = """
        SELECT date_trunc('month', as_of_date)::date AS month,
               SUM(buy_value_cr)  FILTER (WHERE category='FII') AS fii_buy,
               SUM(sell_value_cr) FILTER (WHERE category='FII') AS fii_sell,
               SUM(net_value_cr)  FILTER (WHERE category='FII') AS fii_net,
               SUM(buy_value_cr)  FILTER (WHERE category='DII') AS dii_buy,
               SUM(sell_value_cr) FILTER (WHERE category='DII') AS dii_sell,
               SUM(net_value_cr)  FILTER (WHERE category='DII') AS dii_net
          FROM nidp.fii_dii_flows
         WHERE segment='EQUITY_CASH' AND category IN ('FII','DII')
           AND as_of_date >= (date_trunc('month', current_date) - interval '17 months')
         GROUP BY month
         ORDER BY month DESC
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        daily = await conn.fetch(daily_sql, days)
        monthly = await conn.fetch(monthly_sql)
    return {
        "as_of":   daily[0]["as_of_date"].isoformat() if daily else None,
        "daily":   [{"date": r["as_of_date"].isoformat(), **_fd_row(r)} for r in daily],
        "monthly": [{"month": r["month"].isoformat(), **_fd_row(r)} for r in monthly],
    }


# ════════════════════════════════════════════════════════════════════════
# Corporate-action calendar (joined to ref.security_master for names)
# ════════════════════════════════════════════════════════════════════════

_CA_TYPES = ["DIVIDEND", "BONUS", "RIGHTS", "SPLIT", "MERGER", "DEMERGER", "BUYBACK"]


def _ca_value_label(r) -> Optional[str]:
    at = (r["action_type"] or "").upper()
    if at == "DIVIDEND" and r["dividend_amount"] is not None:
        return f"₹{float(r['dividend_amount']):g}"
    if at == "SPLIT":
        if r["face_value_pre"] is not None and r["face_value_post"] is not None:
            return f"FV ₹{float(r['face_value_pre']):g} → ₹{float(r['face_value_post']):g}"
        return r["ratio"] or None
    if at in ("BONUS", "RIGHTS") and r["ratio"]:
        return r["ratio"]
    if r["ratio"]:
        return r["ratio"]
    return r["purpose"] or None


@router.get("/corporate-actions", summary="Corporate-action calendar (filterable)")
async def corporate_actions(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    action_type: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    today = date.today()
    d_from = date.fromisoformat(date_from) if date_from else today - timedelta(days=30)
    d_to = date.fromisoformat(date_to) if date_to else today + timedelta(days=30)
    a_type = action_type.upper() if action_type else None
    if a_type and a_type not in _CA_TYPES:
        a_type = None
    like = f"%{q}%" if q else None

    list_sql = """
        SELECT ca.symbol, sm.security_name AS name,
               ca.action_type, ca.action_subtype, ca.purpose, ca.ratio,
               ca.face_value_pre, ca.face_value_post, ca.dividend_amount,
               ca.record_date, ca.ex_date
          FROM nidp.corporate_actions ca
          LEFT JOIN ref.security_master sm
                 ON sm.entity_type = 'EQUITY' AND sm.symbol = ca.symbol
         WHERE ca.ex_date >= $1::date AND ca.ex_date <= $2::date
           AND ($3::text IS NULL OR ca.action_type = $3)
           AND ($4::text IS NULL OR ca.symbol ILIKE $4 OR sm.security_name ILIKE $4)
         ORDER BY ca.ex_date ASC, ca.symbol
         LIMIT $5 OFFSET $6
    """
    count_sql = """
        SELECT action_type, count(*) AS n
          FROM nidp.corporate_actions
         WHERE ex_date >= $1::date AND ex_date <= $2::date
         GROUP BY action_type
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(list_sql, d_from, d_to, a_type, like, limit, offset)
        counts = await conn.fetch(count_sql, d_from, d_to)

    actions = [{
        "symbol":      r["symbol"],
        "name":        r["name"] or r["symbol"],
        "action_type": r["action_type"],
        "subtype":     r["action_subtype"],
        "ex_date":     r["ex_date"].isoformat() if r["ex_date"] else None,
        "record_date": r["record_date"].isoformat() if r["record_date"] else None,
        "value_label": _ca_value_label(r),
        "dividend_amount": float(r["dividend_amount"]) if r["dividend_amount"] is not None else None,
        "ratio":       r["ratio"],
        "purpose":     r["purpose"],
    } for r in rows]
    return {
        "from":        d_from.isoformat(),
        "to":          d_to.isoformat(),
        "types":       _CA_TYPES,
        "actions":     actions,
        "type_counts": {r["action_type"]: int(r["n"]) for r in counts if r["action_type"]},
    }


# ════════════════════════════════════════════════════════════════════════
# Articles — classified NSE/BSE filings as a news grid
# ════════════════════════════════════════════════════════════════════════

def _read_min(subject: Optional[str], description: Optional[str]) -> int:
    text = (description or subject or "").strip()
    return max(1, min(round(len(text.split()) / 200) or 1, 6))


@router.get("/articles", summary="Stock-market news & analysis (classified filings)")
async def articles(
    days: int = Query(7, ge=1, le=30),
    category: Optional[str] = Query(None),
    impact: Optional[str] = Query(None),
    sentiment: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(60, ge=1, le=120),
    offset: int = Query(0, ge=0),
):
    since = date.today() - timedelta(days=days)
    category = category.lower() if category else None
    impact = impact.lower() if impact else None
    sentiment = sentiment.lower() if sentiment else None
    like = f"%{q}%" if q else None

    list_sql = """
        SELECT announcement_id, source, ticker_symbol, company_name, subject,
               description, event_category, impact_score, sentiment,
               filed_at, attachment_url
          FROM nidp.corporate_announcements
         WHERE filed_at >= $1::date
           AND ($2::text IS NULL OR event_category = $2)
           AND ($3::text IS NULL OR impact_score = $3)
           AND ($4::text IS NULL OR sentiment = $4)
           AND ($5::text IS NULL OR subject ILIKE $5 OR company_name ILIKE $5 OR ticker_symbol ILIKE $5)
           AND ($2::text IS NOT NULL OR event_category IS NULL OR event_category NOT IN ('regulatory', 'other'))
         ORDER BY (impact_score='high') DESC, filed_at DESC
         LIMIT $6 OFFSET $7
    """
    cat_sql = """
        SELECT event_category, count(*) AS n
          FROM nidp.corporate_announcements
         WHERE filed_at >= $1::date AND event_category IS NOT NULL
           AND event_category NOT IN ('regulatory', 'other')
         GROUP BY event_category
         ORDER BY n DESC
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(list_sql, since, category, impact, sentiment, like, limit, offset)
        cats = await conn.fetch(cat_sql, since)

    out = []
    for r in rows:
        subject = (r["subject"] or "").strip()
        desc = (r["description"] or "").strip()
        out.append({
            "id":        r["announcement_id"],
            "title":     subject or "Corporate announcement",
            "summary":   desc[:240] or None,
            "company":   r["company_name"] or r["ticker_symbol"],
            "symbol":    r["ticker_symbol"],
            "category":  (r["event_category"] or "markets").replace("_", " ").title(),
            "impact":    r["impact_score"],
            "sentiment": r["sentiment"],
            "when":      r["filed_at"].isoformat() if r["filed_at"] else None,
            "source":    r["source"],
            "url":       r["attachment_url"],
            "read_min":  _read_min(subject, desc),
        })
    return {"articles": out, "categories": {r["event_category"]: int(r["n"]) for r in cats}}


# ════════════════════════════════════════════════════════════════════════
# Movers by market-cap segment (Nifty-500 EOD bucketed by market_cap_bucket)
# ════════════════════════════════════════════════════════════════════════

_CAP_BUCKET = {"large": "LARGE_CAP", "mid": "MID_CAP", "small": "SMALL_CAP"}


@router.get("/movers", summary="Top gainers/losers by market-cap segment")
async def movers(cap: str = Query("large")):
    cap = (cap or "large").lower()
    bucket = _CAP_BUCKET.get(cap)
    if bucket is None:
        return {"as_of": None, "cap": cap, "gainers": [], "losers": []}

    sql = """
        SELECT sc.symbol, sc.company_name, sc.close, sc.pct_change
          FROM analytics.stock_card sc
          JOIN nidp.stock_features_daily f
            ON f.symbol = sc.symbol
           AND f.as_of_date = (SELECT max(as_of_date) FROM nidp.stock_features_daily)
         WHERE sc.as_of_date = (SELECT max(as_of_date) FROM analytics.stock_card)
           AND sc.in_nifty500
           AND sc.pct_change IS NOT NULL
           AND f.market_cap_bucket = $1
         ORDER BY sc.pct_change {dir}
         LIMIT 5
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        as_of = await conn.fetchval("SELECT max(as_of_date) FROM analytics.stock_card")
        if as_of is None:
            return {"as_of": None, "cap": cap, "gainers": [], "losers": []}
        gainers = await conn.fetch(sql.format(dir="DESC"), bucket)
        losers = await conn.fetch(sql.format(dir="ASC"), bucket)

    def _row(r) -> Dict[str, Any]:
        return {
            "symbol":     r["symbol"],
            "name":       r["company_name"] or r["symbol"],
            "price":      _f(r["close"]),
            "change_pct": _f(r["pct_change"]),
        }

    return {
        "as_of":   as_of.isoformat(),
        "cap":     cap,
        "gainers": [_row(r) for r in gainers],
        "losers":  [_row(r) for r in losers],
    }


# ════════════════════════════════════════════════════════════════════════
# Earnings Tracker — per-sector results for one index + quarter.
#
# Real NIDP data only (nidp.nse_financials_quarterly + nidp.index_constituents).
# We do NOT have an analyst-consensus feed, so there is no "beat/miss vs
# estimates"; instead we report growth vs the year-ago quarter (YoY), vs the
# prior quarter (QoQ), and a profit-grew / profit-shrank / no-comparable split.
#
# Growth headline per sector is the MEDIAN of per-company growth (the typical
# company), which is robust to the single-symbol outliers and negative-base
# sign-flips that wreck a naive sum-based aggregate. A company is "declared"
# when it has filed a quarterly result for the period; banks file pat_cr but
# not revenue_from_ops_cr, so sales metrics naturally cover non-banks only.
#
# period_type is matched case-insensitively to 'quarterly' (the rows are stored
# lowercase) and ANNUAL filings are excluded so Q4 YoY isn't contaminated by the
# full-year numbers many companies file at year-end.
# ════════════════════════════════════════════════════════════════════════

# Shared CTE: resolves the target quarter (latest filed if not given), the prior
# quarter and year-ago quarter, picks one basis per symbol (consolidated first),
# and left-joins each index member to its three comparison rows.
#   $1 = index_name   $2 = target period_end (DATE, nullable → latest quarter)
_EARNINGS_CTE = """
WITH params AS (
    SELECT COALESCE($2::date,
                    (SELECT MAX(period_end) FROM nidp.nse_financials_quarterly
                      WHERE LOWER(period_type) = 'quarterly')) AS pe
),
idx AS (
    SELECT DISTINCT ic.symbol, ic.industry
      FROM nidp.index_constituents ic
     WHERE ic.index_name = $1
       AND ic.as_of_date = (SELECT MAX(as_of_date) FROM nidp.index_constituents
                             WHERE index_name = $1)
),
prior_q AS (
    SELECT MAX(period_end) AS pe FROM nidp.nse_financials_quarterly
     WHERE LOWER(period_type) = 'quarterly' AND period_end < (SELECT pe FROM params)
),
fin AS (
    SELECT symbol, period_end, revenue_from_ops_cr AS rev, pat_cr AS pat,
           ROW_NUMBER() OVER (PARTITION BY symbol, period_end
                              ORDER BY consolidated DESC) AS rn
      FROM nidp.nse_financials_quarterly
     WHERE LOWER(period_type) = 'quarterly'
       AND period_end IN ((SELECT pe FROM params),
                          ((SELECT pe FROM params) - INTERVAL '1 year')::date,
                          (SELECT pe FROM prior_q))
),
cur AS (SELECT symbol, rev, pat FROM fin WHERE rn = 1 AND period_end =  (SELECT pe FROM params)),
yoy AS (SELECT symbol, rev, pat FROM fin WHERE rn = 1 AND period_end = ((SELECT pe FROM params) - INTERVAL '1 year')::date),
qoq AS (SELECT symbol, rev, pat FROM fin WHERE rn = 1 AND period_end =  (SELECT pe FROM prior_q)),
j AS (
    SELECT idx.industry              AS sector,
           (cur.symbol IS NOT NULL)  AS declared,
           cur.rev AS crev, cur.pat AS cpat,
           yoy.rev AS yrev, yoy.pat AS ypat,
           qoq.rev AS qrev, qoq.pat AS qpat
      FROM idx
      LEFT JOIN cur ON cur.symbol = idx.symbol
      LEFT JOIN yoy ON yoy.symbol = idx.symbol
      LEFT JOIN qoq ON qoq.symbol = idx.symbol
)
"""

# Per-company growth medians + profit-direction split. Reused for the per-sector
# rows (GROUP BY sector) and the index-wide summary (no GROUP BY).
_EARNINGS_METRICS = """
    COUNT(*)                                                         AS members,
    COUNT(*) FILTER (WHERE declared)                                 AS declared,
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY (crev - yrev) / yrev * 100)
          FILTER (WHERE crev IS NOT NULL AND yrev > 0)::numeric, 1)   AS sales_yoy,
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY (cpat - ypat) / ypat * 100)
          FILTER (WHERE cpat IS NOT NULL AND ypat > 0)::numeric, 1)   AS profit_yoy,
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY (crev - qrev) / qrev * 100)
          FILTER (WHERE crev IS NOT NULL AND qrev > 0)::numeric, 1)   AS sales_qoq,
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY (cpat - qpat) / qpat * 100)
          FILTER (WHERE cpat IS NOT NULL AND qpat > 0)::numeric, 1)   AS profit_qoq,
    COUNT(*) FILTER (WHERE cpat IS NOT NULL AND ypat IS NOT NULL AND cpat >  ypat) AS grew,
    COUNT(*) FILTER (WHERE cpat IS NOT NULL AND ypat IS NOT NULL AND cpat <= ypat) AS shrank,
    COUNT(*) FILTER (WHERE cpat IS NOT NULL AND ypat IS NULL)                      AS no_compare
"""

_SECTOR_SQL = _EARNINGS_CTE + "SELECT sector, " + _EARNINGS_METRICS + """
  FROM j
 WHERE sector IS NOT NULL
 GROUP BY sector
 ORDER BY declared DESC, members DESC
"""

_SUMMARY_SQL = _EARNINGS_CTE + "SELECT " + _EARNINGS_METRICS + """,
       (SELECT pe FROM params)  AS period_end,
       (SELECT pe FROM prior_q) AS prior_q
  FROM j
"""


def _quarter_label(pe: Optional[date]) -> Optional[str]:
    """Indian-fiscal-year quarter label for a quarter-end date (Apr–Mar FY)."""
    if pe is None:
        return None
    m, y = pe.month, pe.year
    if   m == 3:  q, fy = 4, y          # Jan–Mar  → Q4, FY = calendar year
    elif m == 6:  q, fy = 1, y + 1      # Apr–Jun  → Q1
    elif m == 9:  q, fy = 2, y + 1      # Jul–Sep  → Q2
    elif m == 12: q, fy = 3, y + 1      # Oct–Dec  → Q3
    else:
        return pe.isoformat()
    return f"Q{q} FY{fy % 100:02d}"


def _pct(v) -> Optional[float]:
    return round(float(v), 1) if v is not None else None


def _earnings_metrics(r) -> Dict[str, Any]:
    return {
        "members":    int(r["members"]),
        "declared":   int(r["declared"]),
        "sales_yoy":  _pct(r["sales_yoy"]),
        "profit_yoy": _pct(r["profit_yoy"]),
        "sales_qoq":  _pct(r["sales_qoq"]),
        "profit_qoq": _pct(r["profit_qoq"]),
        "grew":       int(r["grew"]),
        "shrank":     int(r["shrank"]),
        "no_compare": int(r["no_compare"]),
    }


async def build_earnings(conn, index: str, quarter: Optional[str]) -> Dict[str, Any]:
    """Assemble the Earnings-Tracker payload for one index + quarter.

    Shared verbatim with the app's PG fallback (backend/routes/markets.py) so
    either data path returns an identical shape.
    """
    pe_param = None
    if quarter:
        try:
            pe_param = date.fromisoformat(quarter)
        except ValueError:
            pe_param = None

    sectors = await conn.fetch(_SECTOR_SQL, index, pe_param)
    summary = await conn.fetchrow(_SUMMARY_SQL, index, pe_param)
    quarters = await conn.fetch(
        """SELECT DISTINCT period_end FROM nidp.nse_financials_quarterly
            WHERE LOWER(period_type) = 'quarterly'
            ORDER BY period_end DESC LIMIT 8"""
    )
    indices = await conn.fetch(
        """SELECT index_name FROM (
               SELECT ic.index_name, COUNT(*) AS n
                 FROM nidp.index_constituents ic
                WHERE ic.as_of_date = (SELECT MAX(as_of_date)
                                         FROM nidp.index_constituents i2
                                        WHERE i2.index_name = ic.index_name)
                GROUP BY ic.index_name) t
            ORDER BY n DESC"""
    )

    period_end = summary["period_end"] if summary else None
    summary_obj = None
    if summary and summary["declared"]:
        m = _earnings_metrics(summary)
        summary_obj = {
            "members":       m["members"],
            "declared":      m["declared"],
            "profit_grew":   m["grew"],
            "profit_shrank": m["shrank"],
            "no_compare":    m["no_compare"],
            "sales_yoy":     m["sales_yoy"],
            "profit_yoy":    m["profit_yoy"],
            "sales_qoq":     m["sales_qoq"],
            "profit_qoq":    m["profit_qoq"],
        }

    return {
        "index":      index,
        "period_end": period_end.isoformat() if period_end else None,
        "quarter":    _quarter_label(period_end),
        "summary":    summary_obj,
        "sectors":    [{"sector": r["sector"], **_earnings_metrics(r)} for r in sectors],
        "available_indices":  [r["index_name"] for r in indices],
        "available_quarters": [
            {"period_end": r["period_end"].isoformat(),
             "label":      _quarter_label(r["period_end"])}
            for r in quarters
        ],
    }


@router.get("/earnings", summary="Earnings Tracker — per-sector results for an index + quarter")
async def earnings(
    index: str = Query("Nifty 500"),
    quarter: Optional[str] = Query(None, description="Quarter end date YYYY-MM-DD; latest filed if omitted"),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await build_earnings(conn, (index or "Nifty 500").strip(), quarter)
