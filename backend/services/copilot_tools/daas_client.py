"""Thin async client for the NIDP DAAS API.

Uses env vars:
  NIDP_DAAS_BASE_URL  — e.g. http://34.93.60.254:8083
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
