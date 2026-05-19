"""Thin async client for the NIDP DAAS API.

Uses env vars:
  NIDP_DAAS_BASE_URL  — e.g. https://data.niveshcopilot.com/daas
  NIDP_DAAS_API_KEY   — API key issued by the DAAS /admin/keys endpoint

All methods raise DaasError on HTTP or connectivity failures so callers
can handle them uniformly without caring about httpx internals.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10.0


class DaasError(Exception):
    """Raised when the DAAS API returns a non-200 response or is unreachable."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _creds() -> tuple[str, str]:
    base = os.environ.get("NIDP_DAAS_BASE_URL", "").rstrip("/")
    key = os.environ.get("NIDP_DAAS_API_KEY", "")
    if not base or not key:
        raise DaasError(
            "NIDP_DAAS_BASE_URL and NIDP_DAAS_API_KEY must be set to call DAAS"
        )
    return base, key


async def _get(path: str, params: Optional[Dict[str, Any]] = None, timeout: float = _DEFAULT_TIMEOUT) -> Any:
    base, key = _creds()
    url = f"{base}/v1{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                url,
                params=params,
                headers={"X-API-Key": key, "Accept": "application/json"},
            )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise DaasError(
                f"DAAS {path} returned HTTP {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
            )
        return resp.json()
    except httpx.TimeoutException:
        raise DaasError(f"DAAS request timed out after {timeout}s: {path}")
    except httpx.HTTPError as exc:
        raise DaasError(f"DAAS connectivity error on {path}: {exc}")


async def _post(path: str, body: Dict[str, Any], timeout: float = _DEFAULT_TIMEOUT) -> Any:
    base, key = _creds()
    url = f"{base}/v1{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url,
                json=body,
                headers={
                    "X-API-Key": key,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise DaasError(
                f"DAAS {path} returned HTTP {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
            )
        return resp.json()
    except httpx.TimeoutException:
        raise DaasError(f"DAAS POST timed out after {timeout}s: {path}")
    except httpx.HTTPError as exc:
        raise DaasError(f"DAAS connectivity error on {path}: {exc}")


def is_configured() -> bool:
    """True when both NIDP_DAAS_BASE_URL and NIDP_DAAS_API_KEY are set.
    Callers use this to decide whether to attempt DaaS HTTP before
    falling back to a direct PG read.
    """
    return bool(
        os.environ.get("NIDP_DAAS_BASE_URL", "").strip()
        and os.environ.get("NIDP_DAAS_API_KEY", "").strip()
    )


async def get_stock_features_latest(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch the most recent technical feature row for a symbol.

    Returns the feature dict or None if no data exists.
    """
    data = await _get(f"/features/stocks/{symbol}/latest")
    if data is None:
        return None
    return data.get("data")


async def get_stock_features_history(
    symbol: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 30,
) -> list[Dict[str, Any]]:
    """Fetch historical feature rows for a symbol (newest first)."""
    params: Dict[str, Any] = {"limit": limit}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    data = await _get(f"/features/stocks/{symbol}", params=params)
    if data is None:
        return []
    return data.get("data", [])


async def get_stock_price_latest(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch the latest OHLCV price row for a symbol."""
    data = await _get(f"/prices/stocks/{symbol}/latest")
    if data is None:
        return None
    return data.get("data")


async def get_stock_fundamentals(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch the latest fundamental/financial data for a symbol."""
    data = await _get(f"/financials/stocks/{symbol}/latest")
    if data is None:
        return None
    return data.get("data")


async def get_quarterly_financials(
    symbol: str,
    limit: int = 8,
    consolidated: bool = True,
) -> list[Dict[str, Any]]:
    """Fetch recent quarterly P&L, balance sheet rows from nse_financials_quarterly.

    Returns newest-first list of up to `limit` quarters.
    """
    params: Dict[str, Any] = {"limit": limit, "consolidated": str(consolidated).lower()}
    data = await _get(f"/financials/{symbol}", params=params)
    if data is None:
        return []
    rows = data.get("data") or data.get("rows") or []
    return rows if isinstance(rows, list) else []


async def get_shareholding_history(
    symbol: str,
    limit: int = 5,
) -> list[Dict[str, Any]]:
    """Fetch recent shareholding pattern rows (promoter/FII/DII/MF).

    Returns newest-first list of up to `limit` periods.
    """
    data = await _get(f"/shareholding/{symbol}", params={"limit": limit})
    if data is None:
        return []
    rows = data.get("data") or data.get("rows") or []
    return rows if isinstance(rows, list) else []


async def get_mf_scorecard(scheme_code: str) -> Optional[Dict[str, Any]]:
    """Full category scorecard for a scheme: composite_score, quality_label, quartile ranks.

    Returns None on 404 or DaaS unavailability so callers can degrade gracefully.
    """
    data = await _get(f"/mf/performance/scorecard/{scheme_code}")
    if data is None:
        return None
    return data.get("data") or data


async def get_mf_events(scheme_code: str, limit: int = 20) -> list[Dict[str, Any]]:
    """Lifecycle events for a scheme: TER changes, manager changes, risk shifts, mergers.

    Returns empty list on failure so callers never need to guard against None.
    """
    data = await _get(f"/mf/schemes/{scheme_code}/events", params={"limit": limit})
    if data is None:
        return []
    rows = data.get("data") or data.get("events") or data.get("rows") or []
    return rows if isinstance(rows, list) else []


async def get_price_latest(symbol: str) -> Optional[float]:
    """Fetch the latest EOD close price for a single NSE symbol from NIDP.

    Returns None if the symbol has no price data yet (data lake may be empty
    before the yfinance backfill runs).
    """
    data = await _get(f"/prices/latest/{symbol}")
    if data is None:
        return None
    row = data.get("data") or data
    price = row.get("close_price") or row.get("prev_close")
    return float(price) if price is not None else None


async def get_prices_latest_batch(symbols: list[str]) -> Dict[str, float]:
    """Concurrently fetch latest close prices for a list of NSE symbols.

    Fires individual /prices/latest/{symbol} calls in parallel. Returns a
    symbol→close_price dict — missing symbols are simply absent (not errored).
    """
    import asyncio

    result: Dict[str, float] = {}

    async def _one(sym: str) -> None:
        try:
            p = await get_price_latest(sym)
            if p is not None:
                result[sym] = p
        except DaasError:
            pass

    await asyncio.gather(*(_one(s) for s in symbols), return_exceptions=True)
    return result


# ── V3 primitives (bulk) ─────────────────────────────────────────────

async def get_v3_mf_primitives_bulk(
    isins: list[str],
    timeout: float = 15.0,
) -> Dict[str, Dict[str, Any]]:
    """Fetch the V3 primitive row for each ISIN.

    Returns ``{isin: {primitive_row}}`` keyed by ISIN. Empty dict on
    connectivity failure / missing config so the caller can fall back
    to a direct PG read without raising.

    NIDP keys its MF primitives view on ISIN (migration 058) — the
    natural cross-system identifier from CAS imports. The Nivesh-side
    caller resolves instrument_id → ISIN via the local instrument_master
    PG table before invoking this.
    """
    if not isins:
        return {}
    try:
        payload = await _post(
            "/mf/performance/v3-primitives/bulk",
            {"isins": isins},
            timeout=timeout,
        )
    except DaasError as exc:
        logger.warning("get_v3_mf_primitives_bulk: %s", exc)
        return {}
    if not payload:
        return {}
    data = payload.get("data") or {}
    return data if isinstance(data, dict) else {}


async def get_v3_stock_primitives_bulk(
    symbols: list[str],
    timeout: float = 15.0,
) -> Dict[str, Dict[str, Any]]:
    """Fetch the latest V3 primitive row for each NSE symbol.

    Empty dict on connectivity failure so callers can degrade to the
    PG-direct path.
    """
    if not symbols:
        return {}
    try:
        payload = await _post(
            "/stocks/v3-primitives/bulk",
            {"symbols": symbols},
            timeout=timeout,
        )
    except DaasError as exc:
        logger.warning("get_v3_stock_primitives_bulk: %s", exc)
        return {}
    if not payload:
        return {}
    data = payload.get("data") or {}
    return data if isinstance(data, dict) else {}
