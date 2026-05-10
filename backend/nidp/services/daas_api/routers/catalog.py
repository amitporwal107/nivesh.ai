"""Public dataset catalog — what's exposed via this API + coverage stats.

Distinct from the internal admin catalog (services/query_api/routers/catalog.py).
That one lists every nidp.* table with counts; this one lists *publicly
exposed datasets* and the v1 endpoints that surface them, so DaaS callers
can discover the API without reading source code."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key


router = APIRouter(prefix="/catalog", tags=["meta"], dependencies=[Depends(require_api_key)])


# (dataset name, source table, date_col, domain, endpoints, description)
_DATASETS: List[Dict[str, Any]] = [
    {
        "name":       "prices_eod",
        "table":      "nidp.prices_eod",
        "date_col":   "as_of_date",
        "domain":     "Market data",
        "endpoints":  ["/v1/prices/eod/{symbol}", "/v1/prices/eod", "/v1/prices/latest/{symbol}"],
        "description": "NSE bhavcopy daily OHLCV per (symbol, day). Not split-adjusted.",
    },
    {
        "name":       "prices_eod_adjusted",
        "table":      "nidp.prices_eod_adjusted",
        "date_col":   "as_of_date",
        "domain":     "Market data",
        "endpoints":  ["/v1/prices/adjusted/{symbol}"],
        "description": "Split/bonus-adjusted (price-return) and total-return prices for backtests.",
    },
    {
        "name":       "delivery_data",
        "table":      "nidp.delivery_data",
        "date_col":   "as_of_date",
        "domain":     "Market data",
        "endpoints":  ["/v1/prices/delivery/{symbol}"],
        "description": "Daily deliverable quantity + delivery % per stock.",
    },
    {
        "name":       "index_eod",
        "table":      "nidp.index_eod",
        "date_col":   "as_of_date",
        "domain":     "Market data",
        "endpoints":  ["/v1/prices/index/{index_name}", "/v1/indices"],
        "description": "Daily OHLC + return for every index (Nifty 50/100/500, Bank Nifty, …).",
    },
    {
        "name":       "fno_bhavcopy",
        "table":      "nidp.fno_bhavcopy",
        "date_col":   "as_of_date",
        "domain":     "Derivatives",
        "endpoints":  ["/v1/fno/{symbol}", "/v1/fno/{symbol}/chain", "/v1/fno/{symbol}/expiries"],
        "description": "Per-contract OHLC + open-interest for futures and options.",
    },
    {
        "name":       "fii_dii_flows",
        "table":      "nidp.fii_dii_flows",
        "date_col":   "as_of_date",
        "domain":     "Flows & events",
        "endpoints":  ["/v1/flows/fii-dii"],
        "description": "Daily FII/DII net buy/sell in cash and F&O segments.",
    },
    {
        "name":       "bulk_deals",
        "table":      "nidp.bulk_deals",
        "date_col":   "as_of_date",
        "domain":     "Flows & events",
        "endpoints":  ["/v1/flows/bulk-deals"],
        "description": "Trades > 0.5% of listed shares in one client name.",
    },
    {
        "name":       "block_deals",
        "table":      "nidp.block_deals",
        "date_col":   "as_of_date",
        "domain":     "Flows & events",
        "endpoints":  ["/v1/flows/block-deals"],
        "description": "Negotiated trades > ₹10 Cr or > 5L shares.",
    },
    {
        "name":       "corporate_actions",
        "table":      "nidp.corporate_actions",
        "date_col":   "ex_date",
        "domain":     "Flows & events",
        "endpoints":  ["/v1/corporate-actions", "/v1/corporate-actions/{symbol}"],
        "description": "Splits, bonuses, dividends, rights, mergers — with ex-date and ratio.",
    },
    {
        "name":       "index_constituents",
        "table":      "nidp.index_constituents",
        "date_col":   "as_of_date",
        "domain":     "Reference",
        "endpoints":  ["/v1/indices/{index_name}/constituents"],
        "description": "Effective-dated index membership (point-in-time backtests).",
    },
    {
        "name":       "nse_holidays",
        "table":      "nidp.nse_holidays",
        "date_col":   "holiday_date",
        "domain":     "Reference",
        "endpoints":  ["/v1/holidays"],
        "description": "NSE trading-holiday calendar by segment (CM / FO / CD / …).",
    },
    {
        "name":       "sector_master",
        "table":      "nidp.sector_master",
        "date_col":   None,
        "domain":     "Reference",
        "endpoints":  ["/v1/symbols", "/v1/symbols/search", "/v1/symbols/{symbol}", "/v1/sectors"],
        "description": "Symbol master with sector / industry / face value / listing date.",
    },
    {
        "name":       "nse_financials_quarterly",
        "table":      "nidp.nse_financials_quarterly",
        "date_col":   "period_end",
        "domain":     "Fundamentals",
        "endpoints":  ["/v1/financials/{symbol}"],
        "description": "Quarterly XBRL filings — revenue, PAT, EPS, debt, cash.",
    },
    {
        "name":       "shareholding_pattern",
        "table":      "nidp.shareholding_pattern",
        "date_col":   "period_end",
        "domain":     "Fundamentals",
        "endpoints":  ["/v1/shareholding/{symbol}"],
        "description": "Quarterly shareholding split — promoter, FII, DII, retail.",
    },
    {
        "name":       "rbi_yields",
        "table":      "nidp.rbi_yields",
        "date_col":   "as_of_date",
        "domain":     "Macro",
        "endpoints":  ["/v1/macro/rbi-yields"],
        "description": "Indian G-Sec / T-bill / repo yields across tenors.",
    },
    {
        "name":       "fred_macro",
        "table":      "nidp.fred_macro",
        "date_col":   "as_of_date",
        "domain":     "Macro",
        "endpoints":  ["/v1/macro/fred", "/v1/macro/fred/series"],
        "description": "FRED global macro — US10Y, DXY, VIX, Fed Funds, etc.",
    },
    {
        "name":       "corporate_announcements",
        "table":      "nidp.corporate_announcements",
        "date_col":   "filed_at",
        "domain":     "Disclosure",
        "endpoints":  ["/v1/announcements", "/v1/announcements/{announcement_id}"],
        "description": "NSE + BSE filings, classified into impact / category / sentiment.",
    },
    {
        "name":       "stock_features_daily",
        "table":      "nidp.stock_features_daily",
        "date_col":   "as_of_date",
        "domain":     "Derived",
        "endpoints":  ["/v1/features/stocks/{symbol}", "/v1/features/stocks/{symbol}/latest"],
        "description": "Engineered features — SMAs, RSI, MACD, ATR, Bollinger, volume z-score.",
    },
    {
        "name":       "market_daily_snapshot",
        "table":      "nidp.market_daily_snapshot",
        "date_col":   "as_of_date",
        "domain":     "Derived",
        "endpoints":  ["/v1/snapshots/market", "/v1/snapshots/market/recent"],
        "description": "Frozen point-in-time market view — indices, breadth, FII/DII.",
    },
    {
        "name":       "stock_daily_snapshot",
        "table":      "nidp.stock_daily_snapshot",
        "date_col":   "as_of_date",
        "domain":     "Derived",
        "endpoints":  ["/v1/snapshots/stock/{symbol}"],
        "description": "Per-stock point-in-time card — OHLCV + index flags + deals.",
    },
    {
        "name":       "intelligence_security_master",
        "table":      "ref.security_master",
        "date_col":   "updated_at",
        "domain":     "Intelligence",
        "endpoints":  ["/v1/intelligence/reference/securities"],
        "description": "Canonical entity master across equity, mutual funds, indices and macro series.",
    },
    {
        "name":       "intelligence_quality_scores",
        "table":      "dq.quality_scores",
        "date_col":   "target_date",
        "domain":     "Intelligence",
        "endpoints":  ["/v1/intelligence/dq/scores"],
        "description": "Daily dataset quality scoring with tiering for trust-gated consumption.",
    },
    {
        "name":       "intelligence_stock_features_daily",
        "table":      "features.stock_features_daily",
        "date_col":   "as_of_date",
        "domain":     "Intelligence",
        "endpoints":  ["/v1/intelligence/features/stocks/{symbol}"],
        "description": "Feature store rows (returns, RSI/MACD, volatility, beta, sharpe, relative strength).",
    },
    {
        "name":       "intelligence_entity_links",
        "table":      "graph.entity_links",
        "date_col":   "as_of_date",
        "domain":     "Intelligence",
        "endpoints":  ["/v1/intelligence/graph/entity-links"],
        "description": "Ownership and membership graph edges (fund holdings, index/sector links, promoter links).",
    },
    {
        "name":       "intelligence_correlations",
        "table":      "graph.correlations",
        "date_col":   "as_of_date",
        "domain":     "Intelligence",
        "endpoints":  ["/v1/intelligence/graph/correlations"],
        "description": "Correlation graph edges across securities and factors.",
    },
    {
        "name":       "intelligence_normalized_events",
        "table":      "events.normalized_events",
        "date_col":   "event_date",
        "domain":     "Intelligence",
        "endpoints":  ["/v1/intelligence/events", "/v1/intelligence/events/search"],
        "description": "Normalized event feed and searchable event corpus.",
    },
    {
        "name":       "intelligence_market_snapshot",
        "table":      "analytics.market_snapshot",
        "date_col":   "as_of_date",
        "domain":     "Intelligence",
        "endpoints":  ["/v1/intelligence/snapshots/market", "/v1/intelligence/snapshots/market/recent"],
        "description": "Daily market intelligence summary with flows and market regime.",
    },
    {
        "name":       "intelligence_portfolio_snapshot",
        "table":      "portfolio.user_intelligence_snapshot",
        "date_col":   "snapshot_date",
        "domain":     "Intelligence",
        "endpoints":  ["/v1/intelligence/portfolio/{external_user_id}/snapshot"],
        "description": "Per-user portfolio intelligence snapshot computed from synced holdings.",
    },
    {
        "name":       "intelligence_portfolio_holdings",
        "table":      "portfolio.user_holdings_snapshot",
        "date_col":   "snapshot_date",
        "domain":     "Intelligence",
        "endpoints":  ["/v1/intelligence/portfolio/{external_user_id}/holdings"],
        "description": "Synced user holdings with security-master resolution metadata.",
    },
    # ── Mutual Fund feeds ─────────────────────────────────────────────
    {
        "name":       "mf_scheme_master",
        "table":      "nidp.mf_scheme_master",
        "date_col":   None,
        "domain":     "Mutual Funds",
        "endpoints":  ["/v1/mf/schemes", "/v1/mf/schemes/{scheme_code}"],
        "description": "AMFI scheme catalog — codes, ISINs, AMC, category, benchmark, status.",
    },
    {
        "name":       "mf_nav_daily",
        "table":      "nidp.mf_nav_daily",
        "date_col":   "nav_date",
        "domain":     "Mutual Funds",
        "endpoints":  ["/v1/mf/nav/{scheme_code}", "/v1/mf/nav/latest"],
        "description": "Daily NAV time series for all AMFI schemes (~10k schemes, updated daily).",
    },
    {
        "name":       "mf_holdings_monthly",
        "table":      "nidp.mf_holdings_monthly",
        "date_col":   "as_of_month",
        "domain":     "Mutual Funds",
        "endpoints":  ["/v1/mf/holdings/{scheme_code}", "/v1/mf/holdings/overlap"],
        "description": "Monthly SEBI-mandated portfolio holdings for top-10 AMCs.",
    },
    {
        "name":       "mf_scheme_events",
        "table":      "nidp.mf_scheme_events",
        "date_col":   "event_date",
        "domain":     "Mutual Funds",
        "endpoints":  ["/v1/mf/schemes/{scheme_code}/events"],
        "description": "Detected scheme lifecycle events: TER changes, manager changes, risk shifts, mergers, renames.",
    },
    {
        "name":       "mf_scheme_disclosure_snapshot",
        "table":      "nidp.mf_scheme_disclosure_snapshot",
        "date_col":   "snapshot_date",
        "domain":     "Mutual Funds",
        "endpoints":  ["/v1/mf/schemes/{scheme_code}/disclosure"],
        "description": "Weekly TER, risk-o-meter, and fund manager snapshots from SID pages.",
    },
    {
        "name":       "mf_amfi_circulars",
        "table":      "nidp.mf_amfi_circulars",
        "date_col":   "published_at",
        "domain":     "Mutual Funds",
        "endpoints":  ["/v1/mf/circulars"],
        "description": "AMFI notices, circulars, and addenda — source for scheme lifecycle events.",
    },
]


@router.get("", summary="List of datasets exposed by this API + coverage")
async def catalog() -> Dict[str, Any]:
    pool = await get_pool()
    out: List[Dict[str, Any]] = []
    async with pool.acquire() as conn:
        for ds in _DATASETS:
            tbl = ds["table"]
            datecol = ds["date_col"]
            try:
                if datecol:
                    row = await conn.fetchrow(
                        f"SELECT count(*) AS rows, min({datecol})::text AS first_at, "
                        f"max({datecol})::text AS last_at FROM {tbl}"
                    )
                else:
                    row = await conn.fetchrow(
                        f"SELECT count(*) AS rows, NULL::text AS first_at, "
                        f"NULL::text AS last_at FROM {tbl}"
                    )
                stats = {"rows": int(row["rows"]), "first_at": row["first_at"], "last_at": row["last_at"]}
            except Exception as e:                                  # noqa: BLE001
                stats = {"rows": None, "first_at": None, "last_at": None, "error": str(e)[:200]}
            out.append({**ds, **stats})
    by_domain: Dict[str, Dict[str, Any]] = {}
    for ds in out:
        agg = by_domain.setdefault(ds["domain"], {"domain": ds["domain"], "datasets": 0, "rows": 0})
        agg["datasets"] += 1
        if ds.get("rows"):
            agg["rows"] += ds["rows"]
    return {
        "as_of":     datetime.utcnow().isoformat() + "Z",
        "totals":    {"datasets": len(out)},
        "by_domain": list(by_domain.values()),
        "datasets":  out,
    }
