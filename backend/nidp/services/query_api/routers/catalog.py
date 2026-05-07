"""Catalog endpoint — every NIDP table's row count + first/last date,
plus by-domain rollup. Mirrors the payload shape the React
NidpCatalogPanel already binds to. The wealth-advisor API service
proxies this through /api/admin/nidp/catalog."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import logging

from fastapi import APIRouter, Depends

from nidp.shared.storage.pg import get_pool
from nidp.services.query_api.auth import require_bearer


logger = logging.getLogger(__name__)
router = APIRouter(prefix="", tags=["catalog"], dependencies=[Depends(require_bearer)])


# (table, date_col_or_None, domain). sector_master + document_chunks
# have no row-level ingestion date worth surfacing — count-only.
_CATALOG_TABLES: List[Tuple[str, Optional[str], str]] = [
    ("prices_eod",                "as_of_date",   "Market data"),
    ("prices_eod_adjusted",       "as_of_date",   "Market data"),
    ("delivery_data",             "as_of_date",   "Market data"),
    ("index_eod",                 "as_of_date",   "Market data"),
    ("fno_bhavcopy",              "as_of_date",   "Market data"),
    ("fii_dii_flows",             "as_of_date",   "Flows & events"),
    ("bulk_deals",                "as_of_date",   "Flows & events"),
    ("block_deals",               "as_of_date",   "Flows & events"),
    ("corporate_actions",         "ex_date",      "Flows & events"),
    ("index_constituents",        "as_of_date",   "Reference"),
    ("nse_holidays",              "holiday_date", "Reference"),
    ("sector_master",             None,           "Reference"),
    ("nse_financials_quarterly",  "period_end",   "Fundamentals"),
    ("shareholding_pattern",      "as_of_date",   "Fundamentals"),
    ("rbi_yields",                "as_of_date",   "Macro"),
    ("fred_macro",                "as_of_date",   "Macro"),
    ("corporate_announcements",   "filed_at",     "Disclosure"),
    ("documents",                 "ingested_at",  "Disclosure"),
    ("document_chunks",           None,           "Disclosure"),
    ("stock_features_daily",      "as_of_date",   "Derived"),
    ("market_daily_snapshot",     "as_of_date",   "Derived"),
    ("stock_daily_snapshot",      "as_of_date",   "Derived"),
]


# Per-table description: source / what's stored / why it matters.
# Surfaced verbatim in the Catalog UI so analysts can self-serve
# without reading migration SQL.
_TABLE_DESC: Dict[str, Dict[str, str]] = {
    "prices_eod": {
        "source":   "NSE bhavcopy (sec_bhavdata_full_DDMMYYYY.csv) — whole-market daily file",
        "stores":   "Open / High / Low / Close / Volume / Turnover per (symbol, trading day)",
        "use":      "Canonical price reference for screens, returns, and feature engineering. NOT split-adjusted — see prices_eod_adjusted for continuous series.",
    },
    "prices_eod_adjusted": {
        "source":   "Derived: prices_eod ⨯ corporate_actions, computed by services/price_adjuster",
        "stores":   "Same OHLCV columns, retroactively scaled for splits/bonuses/dividends",
        "use":      "Use this for momentum/return calculations spanning corporate actions; raw prices_eod will give discontinuous series across ex-dates.",
    },
    "delivery_data": {
        "source":   "NSE security-wise delivery file (MTO_DDMMYYYY.DAT)",
        "stores":   "Daily delivered quantity + delivery % per stock — share of traded volume that actually settled (not intraday flipped)",
        "use":      "Strong accumulation/distribution signal. Sustained high delivery % on rising price = institutional buying.",
    },
    "index_eod": {
        "source":   "NSE indices closing-values file (ind_close_all_DDMMYYYY.csv)",
        "stores":   "Daily OHLC + return for each index (Nifty 50/100/200/500, Bank Nifty, Nifty IT, etc.)",
        "use":      "Benchmarks for relative-strength calculations and macro charts.",
    },
    "fno_bhavcopy": {
        "source":   "NSE F&O bhavcopy (BhavCopy_NSE_FO_0_0_0_DDMMYYYY_F_0000.csv)",
        "stores":   "Per-contract OHLC, open interest, contracts traded — for futures and options across every expiry",
        "use":      "Drives v_options_chain_latest, OI-shift signals, max-pain calc, F&O rollover analysis.",
    },
    "fii_dii_flows": {
        "source":   "NSE FII/DII activity report (XLS scraped daily)",
        "stores":   "Net buy/sell value (₹ Cr) by Foreign and Domestic institutional investors, in cash and F&O",
        "use":      "Macro flow signal — sustained FII selling vs DII buying often marks regime changes.",
    },
    "bulk_deals": {
        "source":   "NSE bulk-deals report (rolling — last N trading days)",
        "stores":   "Trades > 0.5% of listed shares in a single client name; client name + buy/sell + qty + avg price",
        "use":      "Identify smart-money entries/exits in real names (PromoterCo, MF schemes, FPIs).",
    },
    "block_deals": {
        "source":   "NSE block-deals report",
        "stores":   "Negotiated trades > ₹10 Cr or > 5 lakh shares, executed in the special block window",
        "use":      "Often pre-arranged supply transfers — worth flagging when promoter/anchor names appear.",
    },
    "corporate_actions": {
        "source":   "NSE corporate-actions feed (CF-CA file + ad-hoc announcements)",
        "stores":   "Splits, bonuses, dividends, rights, mergers — with ex-date, record date, ratio, value",
        "use":      "Drives the price-adjuster, ex-date alerts, and dividend-yield calculations.",
    },
    "index_constituents": {
        "source":   "NSE index components (ind_niftylist*.csv files)",
        "stores":   "Effective-dated membership: which symbols are in Nifty 50/100/200/500/Bank/IT on a given date",
        "use":      "Universe filter ('run on Nifty 500'). Use as_of_date for point-in-time backtests; v_nifty500_members for current.",
    },
    "nse_holidays": {
        "source":   "NSE trading-holidays calendar",
        "stores":   "List of non-trading dates with reason (Diwali, Republic Day, special closures)",
        "use":      "Skip backfill on holidays; gating for 'is today a market day' checks.",
    },
    "sector_master": {
        "source":   "Manual + scraped sector classification (Industry → Sector mapping)",
        "stores":   "Per-symbol sector + industry + face value + listing date",
        "use":      "Sector rotation analysis, industry benchmark comparisons.",
    },
    "nse_financials_quarterly": {
        "source":   "NSE corporate financial results (XBRL) — quarterly filings",
        "stores":   "Revenue, PAT, EPS, equity, debt, cash — TTM and quarter-on-quarter",
        "use":      "Fundamental screens (P/E, Debt/Equity, ROE), QoQ growth signals.",
    },
    "shareholding_pattern": {
        "source":   "NSE shareholding-pattern XBRL — quarterly",
        "stores":   "Promoter / FII / DII / MF / Insurance / Individual percentages, plus pledge %",
        "use":      "Promoter pledge increase = bearish signal. MF/FII inflow QoQ = institutional conviction.",
    },
    "rbi_yields": {
        "source":   "RBI Database on Indian Economy (DBIE) — daily G-Sec yield curve",
        "stores":   "Generic Govt Bond yields across tenors (1Y, 5Y, 10Y, 30Y) + repo rate",
        "use":      "Equity vs bond risk-premium; rate regime context for sector rotation.",
    },
    "fred_macro": {
        "source":   "FRED API (US Federal Reserve Economic Data)",
        "stores":   "US CPI, PCE, DXY, US10Y, US2Y, Fed Funds rate, VIX — by series_id and date",
        "use":      "Global macro overlays. DXY/US10Y moves drive EM equity flows.",
    },
    "corporate_announcements": {
        "source":   "NSE + BSE corporate filings (XBRL feeds, scraped every 5 min)",
        "stores":   "Filing time, subject, body text, attached PDFs — classified by Haiku into impact tiers",
        "use":      "Real-time event-driven signals. v_announcements_high_impact_today is the alert feed.",
    },
    "documents": {
        "source":   "PDF/XLSX attachments referenced by corporate_announcements (downloaded by document_parser)",
        "stores":   "Parsed text + structured fields per attachment, raw bytes archived to GCS",
        "use":      "Source for chunk + embed pipeline; deeper context for announcement classification.",
    },
    "document_chunks": {
        "source":   "Derived: documents → chunked + embedded by document_parser",
        "stores":   "Text chunks + pgvector embeddings (1024-dim, OpenAI text-embedding-3-large)",
        "use":      "Semantic search over filings; retrieval for the Copilot's grounded Q&A.",
    },
    "stock_features_daily": {
        "source":   "Derived: prices_eod (90 trailing bars) + delivery_data, computed by feature_snapshotter",
        "stores":   "Per-symbol per-day flat row: SMAs, RSI, MACD, ATR, Bollinger, returns, volume Z-score, accumulation score",
        "use":      "The single row strategy compilers and screens bind to. v_stock_features_full extends with fundamentals + shareholding.",
    },
    "market_daily_snapshot": {
        "source":   "Derived: aggregated by services/snapshot_builder after market close",
        "stores":   "One row per trading day: indices, breadth, FII/DII totals, top gainers/losers — frozen JSON",
        "use":      "Powers the dashboard's 'Today's Market' view; immutable point-in-time view.",
    },
    "stock_daily_snapshot": {
        "source":   "Derived: per-symbol point-in-time snapshot, also from snapshot_builder",
        "stores":   "Stock card payload (price, change, volume, delivery, key features) — one per (symbol, day)",
        "use":      "Frozen 'as-of' read for positional picks; ensures historical UI shows what we knew on that day.",
    },
}


_DOMAIN_DESC: Dict[str, str] = {
    "Market data":     "Daily price / volume / derivatives data — the heartbeat of the warehouse. Sourced from NSE bhavcopy + delivery + F&O files.",
    "Flows & events":  "Capital flows (FII/DII), large-trade prints (bulk/block), and corporate-action calendar. Where real money is moving.",
    "Reference":       "Stable lookup data: index membership, holiday calendar, sector classification. Slow-changing but joined into nearly every query.",
    "Fundamentals":    "Quarterly company financials and shareholding patterns. Sourced from NSE XBRL filings.",
    "Macro":           "India rate curve (RBI G-Sec) + global macro (FRED). Context for risk-on/risk-off regime.",
    "Disclosure":      "Real-time exchange filings, parsed PDFs, and pgvector embeddings — drives the announcement intelligence and Copilot.",
    "Derived":         "Pre-computed snapshots and per-stock feature rows. Built nightly so the strategy engine and dashboard read flat rows instead of recomputing 90-bar windows.",
}


@router.get("/catalog")
async def catalog() -> Dict[str, Any]:
    pool = await get_pool()

    async with pool.acquire() as conn:
        tables_out: List[Dict[str, Any]] = []
        for tbl, datecol, domain in _CATALOG_TABLES:
            try:
                if datecol:
                    row = await conn.fetchrow(
                        f"SELECT count(*) AS rows, "
                        f"min({datecol})::text AS first_at, "
                        f"max({datecol})::text AS last_at "
                        f"FROM nidp.{tbl}"
                    )
                else:
                    row = await conn.fetchrow(
                        f"SELECT count(*) AS rows, NULL::text AS first_at, "
                        f"NULL::text AS last_at FROM nidp.{tbl}"
                    )
                tables_out.append({
                    "table":    tbl,
                    "domain":   domain,
                    "date_col": datecol,
                    "rows":     row["rows"],
                    "first_at": row["first_at"],
                    "last_at":  row["last_at"],
                    "description": _TABLE_DESC.get(tbl),
                    "error":    None,
                })
            except Exception as e:                                    # noqa: BLE001
                tables_out.append({
                    "table":    tbl,
                    "domain":   domain,
                    "date_col": datecol,
                    "rows":     None,
                    "first_at": None,
                    "last_at":  None,
                    "description": _TABLE_DESC.get(tbl),
                    "error":    str(e)[:200],
                })

    by_domain: Dict[str, Dict[str, Any]] = {}
    for t in tables_out:
        d = t["domain"]
        agg = by_domain.setdefault(d, {
            "domain": d, "tables": 0, "rows": 0,
            "earliest": None, "latest": None,
            "description": _DOMAIN_DESC.get(d),
        })
        agg["tables"] += 1
        if t["rows"] is not None:
            agg["rows"] += t["rows"]
        if t["first_at"]:
            agg["earliest"] = t["first_at"] if agg["earliest"] is None else min(agg["earliest"], t["first_at"])
        if t["last_at"]:
            agg["latest"]   = t["last_at"]  if agg["latest"]   is None else max(agg["latest"],   t["last_at"])

    return {
        "as_of":     datetime.utcnow().isoformat() + "Z",
        "totals":    {"tables": len(tables_out)},
        "by_domain": list(by_domain.values()),
        "tables":    tables_out,
    }
