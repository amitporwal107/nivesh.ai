"""The data platform reads behind the Research Copilot answers (W1, research_builders.py). Read-only, in-process DaaS client
(readers._daas), never a direct warehouse query. Each raises on failure; the builder then records the source as missing and
shows no figure from it. The unit tests replace these functions.

    financials        DaaS /v1/financials/{symbol} (nidp.nse_financials_quarterly): quarterly or annual rows, newest first, with
                      the balance-sheet columns of the March / September rows (current assets and liabilities, receivables,
                      inventory, payables; `bs_truedata` = the TrueData load's provenance tag) on a DaaS that serves them
    cashflow          DaaS /v1/financials/{symbol}/cashflow (nidp.nse_financials_cashflow): fiscal-year CFO, CFI, CFF, capex
    shareholding      DaaS /v1/shareholding/{symbol} (nidp.shareholding_pattern): NSE's own rows (NSE_SHP) and screener.in's
    features_latest   DaaS /v1/features/stocks/{symbol}/latest (nidp.stock_features_daily): the newest feature row
    pe_history        DaaS /v1/features/stocks/{symbol}: the stored daily P/E (pe_ttm) since the feature history starts
    amc               DaaS /v1/smart-money/amc (nidp.mf_holdings_deltas): which fund houses changed their disclosed holding
    universe          routes.positional._scan_snapshot (DaaS /v1/features/scan-snapshot, cached): every stock's sector label and
                      NSE industry on the latest features day
    features_on       DaaS POST /v1/features/bulk: the feature rows of up to 300 stocks on one day
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

from . import readers as rd


def _rows(body: Any, what: str) -> List[Dict[str, Any]]:
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(f"{what}: the data platform sent no rows list")
    return [r for r in rows if isinstance(r, dict)]


async def financials(symbol: str, period_type: str, limit: int = 40) -> List[Dict[str, Any]]:
    body = await rd._daas(f"/financials/{quote(symbol)}", {"period_type": period_type, "limit": limit})
    return _rows(body, "financials")


async def cashflow(symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
    body = await rd._daas(f"/financials/{quote(symbol)}/cashflow", {"limit": limit})
    return _rows(body, "cash flow")


async def shareholding(symbol: str, limit: int = 40) -> List[Dict[str, Any]]:
    body = await rd._daas(f"/shareholding/{quote(symbol)}", {"limit": limit})
    return _rows(body, "shareholding")


async def features_latest(symbol: str) -> Optional[Dict[str, Any]]:
    """The newest feature row, or None when the platform has none for this stock."""
    body = await rd._daas(f"/features/stocks/{quote(symbol)}/latest")
    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, dict) else None


async def pe_history(symbol: str, limit: int = 600) -> List[Dict[str, Any]]:
    """Daily feature rows, newest first (the P/E series is read from them)."""
    body = await rd._daas(f"/features/stocks/{quote(symbol)}", {"limit": limit})
    return _rows(body, "feature history")


async def amc(symbol: str) -> Dict[str, Any]:
    body = await rd._daas("/smart-money/amc", {"symbol": symbol})
    if not isinstance(body, dict) or not isinstance(body.get("rows"), list):
        raise RuntimeError("smart-money/amc sent no rows list")
    return body


async def universe() -> Dict[str, Any]:
    return await rd.scan_snapshot()


async def features_on(symbols: List[str], day: str) -> Dict[str, Dict[str, Any]]:
    """{symbol: that day's feature row} for up to 300 stocks (DaaS POST /features/bulk)."""
    from services.copilot_tools import daas_client
    if not daas_client.is_configured():
        raise RuntimeError("the data platform (DaaS) is not configured")
    data = await daas_client.get_features_bulk(symbols[:300], start=day, end=day)
    out: Dict[str, Dict[str, Any]] = {}
    for sym, rows in (data or {}).items():
        if isinstance(rows, list) and rows and isinstance(rows[-1], dict):
            out[str(sym).upper()] = rows[-1]
    return out
