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

# Lazy import to avoid circular deps at module load time.
def _secrets_get(key: str) -> str:
    try:
        from helpers import secrets
        return secrets.get(key)
    except Exception:
        return os.environ.get(key, "")

_DEFAULT_TIMEOUT = 10.0


class DaasError(Exception):
    """Raised when the DAAS API returns a non-200 response or is unreachable."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _creds() -> tuple[str, str]:
    base = _secrets_get("NIDP_DAAS_BASE_URL").rstrip("/")
    # Admin UI registers the key as NIDP_DAAS_INTERNAL_TOKEN; Cloud Run env var
    # may be named NIDP_DAAS_API_KEY — try both so either path works.
    key = _secrets_get("NIDP_DAAS_INTERNAL_TOKEN") or _secrets_get("NIDP_DAAS_API_KEY")
    if not base or not key:
        raise DaasError(
            "NIDP_DAAS_BASE_URL and NIDP_DAAS_API_KEY (or NIDP_DAAS_INTERNAL_TOKEN) must be set to call DAAS"
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
    key = _secrets_get("NIDP_DAAS_INTERNAL_TOKEN") or _secrets_get("NIDP_DAAS_API_KEY")
    return bool(_secrets_get("NIDP_DAAS_BASE_URL").strip() and key.strip())


async def get_stock_features_latest(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch the most recent technical feature row for a symbol.

    Returns the feature dict or None if no data exists.
    """
    data = await _get(f"/v1/features/stocks/{symbol}/latest")
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
    data = await _get(f"/v1/features/stocks/{symbol}", params=params)
    if data is None:
        return []
    return data.get("data", [])


async def get_stock_price_latest(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch the latest OHLCV price row for a symbol."""
    data = await _get(f"/v1/prices/latest/{symbol}")
    if data is None:
        return None
    return data.get("data")


async def get_stock_fundamentals(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch the latest fundamental/financial data for a symbol."""
    data = await _get(f"/v1/financials/{symbol}")
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
    data = await _get(f"/v1/financials/{symbol}", params=params)
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
    data = await _get(f"/v1/shareholding/{symbol}", params={"limit": limit})
    if data is None:
        return []
    rows = data.get("data") or data.get("rows") or []
    return rows if isinstance(rows, list) else []


async def get_top_add_funds_by_category(
    category: str,
    n: int = 5,
    timeout: float = 8.0,
) -> List[Dict[str, Any]]:
    """Return the top-N MF candidates for an ADD recommendation in a given category.

    Calls GET /mf/performance/screener/top?metric=composite_rank&category_filter=<category>&limit=<n>.
    Returns rows with at minimum {scheme_name, isin, category, composite_rank, composite_score, return_3y}.
    Returns an empty list on DaaS unavailability so callers fall back to static defaults.
    """
    try:
        payload = await _get(
            "/mf/performance/screener/top",
            params={"metric": "composite_rank", "category_filter": category, "limit": n},
            timeout=timeout,
        )
    except DaasError as exc:
        logger.debug("get_top_add_funds_by_category(%s): %s", category, exc)
        return []
    if not payload:
        return []
    rows = payload.get("data") or payload.get("rows") or []
    return rows if isinstance(rows, list) else []


async def get_mf_scorecard(scheme_code: str) -> Optional[Dict[str, Any]]:
    """Full category scorecard for a scheme: composite_score, quality_label, quartile ranks.

    Returns None on 404 or DaaS unavailability so callers can degrade gracefully.
    """
    data = await _get(f"/v1/mf/performance/scorecard/{scheme_code}")
    if data is None:
        return None
    return data.get("data") or data


async def get_mf_events(scheme_code: str, limit: int = 20) -> list[Dict[str, Any]]:
    """Lifecycle events for a scheme: TER changes, manager changes, risk shifts, mergers.

    Returns empty list on failure so callers never need to guard against None.
    """
    data = await _get(f"/v1/mf/schemes/{scheme_code}/events", params={"limit": limit})
    if data is None:
        return []
    rows = data.get("data") or data.get("events") or data.get("rows") or []
    return rows if isinstance(rows, list) else []


async def get_price_latest(symbol: str) -> Optional[float]:
    """Fetch the latest EOD close price for a single NSE symbol from NIDP.

    Returns None if the symbol has no price data yet (data lake may be empty
    before the yfinance backfill runs).
    """
    data = await _get(f"/v1/prices/latest/{symbol}")
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


async def get_mf_category_sizes(
    categories: list[str],
    timeout: float = 3.0,
) -> Dict[str, int]:
    """Return {category: total_funds_in_category} for each category.

    Calls GET /mf/performance/category/{cat}?metric=composite_rank&limit=1
    which returns a `total` field. All requests run concurrently with a
    3s per-request timeout and a 5s hard ceiling for the whole batch,
    so this never adds more than ~5s to the critical path.
    """
    import asyncio as _asyncio

    async def _fetch_one(cat: str) -> tuple[str, int]:
        try:
            payload = await _get(
                f"/mf/performance/category/{cat}",
                params={"metric": "composite_rank", "limit": 1},
                timeout=timeout,
            )
            total = payload.get("total") if payload else None
            return cat, int(total) if total else 0
        except Exception:  # noqa: BLE001
            return cat, 0

    if not categories:
        return {}
    try:
        results = await _asyncio.wait_for(
            _asyncio.gather(*[_fetch_one(c) for c in categories]),
            timeout=5.0,
        )
    except _asyncio.TimeoutError:
        return {}
    return {cat: total for cat, total in results if total > 0}


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


async def get_category_top(
    category: str,
    n: int = 5,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """Return top-N ranked funds for a SEBI category from mf_category_rank_daily.

    Returns {category, rank_date, total_in_category, funds: [{scheme_code, scheme_name,
    category_rank, category_pct, composite, ret_3y, ret_1y, sharpe, expense_ratio}]}.
    Empty dict on failure.
    """
    if not category:
        return {}
    try:
        import urllib.parse
        params = {"category": category, "n": n}
        payload = await _get("/mf/performance/category-top", params=params, timeout=timeout)
    except DaasError as exc:
        logger.warning("get_category_top(%r): %s", category[:40], exc)
        return {}
    return payload or {}


async def get_user_holdings(
    external_user_id: str,
    on: Optional[str] = None,
    limit: int = 500,
) -> list[Dict[str, Any]]:
    """Fetch a user's holdings from NIDP — joined with `ref.security_master`
    (for scheme_name + sector) and `analytics.fund_category_rank` (for TER
    + rolling returns).

    Returns the rows list (newest snapshot, ordered by market value DESC) or
    an empty list on DaaS unavailability so the caller can fall back without
    raising.

    `external_user_id` is the email NIDP uses as the canonical user key.
    """
    if not external_user_id:
        return []
    params: Dict[str, Any] = {"limit": limit}
    if on:
        params["on"] = on
    try:
        payload = await _get(
            f"/v1/intelligence/portfolio/{external_user_id}/holdings",
            params=params,
        )
    except DaasError as exc:
        logger.warning("get_user_holdings(%s): %s", external_user_id, exc)
        return []
    if not payload:
        return []
    rows = payload.get("data") or payload.get("rows") or []
    return rows if isinstance(rows, list) else []


async def get_portfolio_correlations(
    security_ids: list[str],
    min_abs_corr: float = 0.7,
    window_days: Optional[int] = 90,
    timeout: float = 10.0,
) -> list[dict]:
    """Fetch pairwise correlations for all holdings in a portfolio.

    Calls POST /v1/intelligence/graph/correlations/bulk — returns only pairs
    where BOTH sides are in the supplied security_id list (the portfolio
    correlation subgraph). security_ids are UUIDs from ref.security_master.

    Returns empty list on connectivity failure so the CorrelationEngine
    degrades gracefully to zero pairs rather than crashing the pipeline.

    Args:
        security_ids:  UUIDs from ref.security_master (max 50).
        min_abs_corr:  Only return pairs with |corr| >= this value (default 0.7).
        window_days:   Lookback window filter — 90 for 90-day Pearson (default).
                       Pass None to get all windows.
    """
    if not security_ids:
        return []
    try:
        payload = await _post(
            "/v1/intelligence/graph/correlations/bulk",
            {"security_ids": security_ids},
            timeout=timeout,
        )
    except DaasError as exc:
        logger.warning("get_portfolio_correlations: %s", exc)
        return []
    if not payload:
        return []
    rows = payload.get("data") or []
    # Apply client-side filters in case server params weren't respected
    result = [r for r in rows if isinstance(r, dict)]
    if min_abs_corr > 0:
        result = [r for r in result if float(r.get("abs_correlation") or 0) >= min_abs_corr]
    return result


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
            "/v1/stocks/v3-primitives/bulk",
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
