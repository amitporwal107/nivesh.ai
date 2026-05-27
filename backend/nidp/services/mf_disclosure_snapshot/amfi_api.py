"""AMFI JSON API adapter for TER + risk-o-meter data.

AMFI rebuilt their website as a Next.js SPA in 2026. The old xlsx-based
download pages no longer exist. The new site exposes internal Next.js
API routes that the React client calls to load per-AMC data tables.

Discovered API routes (from /_next/static/chunks/page JS bundle):
  GET /api/populate-ter-month?year={YYYY}
      → [{month: "YYYY-MM", year: "YYYY"}, ...]  — available months
  GET /api/populate-te-rdata-revised?MF_ID={mf_id}&month={YYYY-MM}
      → [{...scheme TER data...}]  — per-AMC TER rows

AMFI mfId mapping (read from RSC payload of /ter-of-mf-schemes):
  Different from our amc_id; hardcoded here to avoid a page-parse on
  every run. Update when AMFI adds/removes AMCs.

Contract: fetch_ter_amfi_api() returns the same shape as amfi_central's
fetch_ter_all(), so callers are interchangeable.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Optional

import aiohttp

from nidp.shared.config import AMFI_WWW

logger = logging.getLogger(__name__)

# AMFI mfId → amc_id mapping.
# Source: RSC payload of https://www.amfiindia.com/ter-of-mf-schemes
# (see tableId list embedded in the RSC flight data).
_AMFI_MF_ID: dict[str, int] = {
    "sbi":       22,
    "icici_pru": 20,
    "hdfc":       9,
    "nippon":    21,
    "kotak":     17,
    "absl":       3,   # Aditya Birla Sun Life
    "uti":        28,
    "axis":       2,
    "mirae":     45,
    "tata":       25,
}

# Reverse map for logging
_MF_ID_AMC: dict[int, str] = {v: k for k, v in _AMFI_MF_ID.items()}

_BASE_API = f"{AMFI_WWW}/api"

# In-process cache — keyed by (mf_id, month_str)
_TER_CACHE:  dict[str, tuple[Optional[float], Optional[float]]] | None = None
_RISK_CACHE: dict[str, str] | None = None


def _to_float(v: object) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (ValueError, AttributeError):
        return None


async def _fetch_latest_month(http: aiohttp.ClientSession) -> Optional[str]:
    """Return the latest available TER month string (YYYY-MM) or None."""
    year = date.today().year
    for y in [year, year - 1]:
        try:
            url = f"{_BASE_API}/populate-ter-month?year={y}"
            async with http.get(url) as resp:
                if resp.status != 200:
                    continue
                months = await resp.json(content_type=None)
                if months:
                    # months is [{month: "YYYY-MM"}, ...] sorted ascending
                    return months[-1].get("month") or months[-1].get("monthName")
        except Exception as e:  # noqa: BLE001
            logger.debug("amfi_api: populate-ter-month year=%d → %s: %s", y, type(e).__name__, e)
    return None


async def _fetch_ter_for_mf(
    http: aiohttp.ClientSession,
    mf_id: int,
    month: Optional[str],
) -> list[dict]:
    """Fetch raw TER rows for one AMC from AMFI JSON API."""
    params: dict[str, str] = {"MF_ID": str(mf_id)}
    if month:
        params["month"] = month
    try:
        async with http.get(f"{_BASE_API}/populate-te-rdata-revised", params=params) as resp:
            if resp.status != 200:
                logger.warning("amfi_api: MF_ID=%d month=%s → status=%d", mf_id, month, resp.status)
                return []
            rows = await resp.json(content_type=None)
            return rows if isinstance(rows, list) else []
    except Exception as e:  # noqa: BLE001
        logger.warning("amfi_api: MF_ID=%d fetch error: %s: %s", mf_id, type(e).__name__, e)
        return []


def _parse_ter_rows(
    rows: list[dict],
) -> dict[str, tuple[Optional[float], Optional[float]]]:
    """Parse AMFI JSON TER rows → {scheme_code: (ter_regular, ter_direct)}.

    The JSON field names are not yet confirmed (API was 500 during dev).
    We probe common patterns and log any unrecognised keys.
    """
    if not rows:
        return {}
    # Log schema of first row for debugging
    if rows:
        logger.debug("amfi_api: ter row keys=%s", list(rows[0].keys()))

    result: dict[str, tuple[Optional[float], Optional[float]]] = {}
    for row in rows:
        # Try common AMFI field name patterns
        code = (
            row.get("schemeCode") or row.get("SchemeCode") or
            row.get("scheme_code") or row.get("AMFI_CODE") or
            row.get("AmfiCode") or ""
        )
        code = str(code).strip()
        if not code or not code[0].isdigit():
            continue

        ter_r = _to_float(
            row.get("terRegular") or row.get("TER_REGULAR") or
            row.get("ter_regular") or row.get("Regular") or
            row.get("regularTer") or row.get("TERRegular")
        )
        ter_d = _to_float(
            row.get("terDirect") or row.get("TER_DIRECT") or
            row.get("ter_direct") or row.get("Direct") or
            row.get("directTer") or row.get("TERDirect")
        )
        result[code] = (ter_r, ter_d)
    return result


async def fetch_ter_all_amfi_api(
    http: aiohttp.ClientSession,
) -> dict[str, tuple[Optional[float], Optional[float]]]:
    """Fetch TER for all top-10 AMCs via AMFI's internal JSON API.

    Returns {scheme_code: (ter_regular_pct, ter_direct_pct)}.
    Module-level cached after first call.
    """
    global _TER_CACHE
    if _TER_CACHE is not None:
        return _TER_CACHE

    month = await _fetch_latest_month(http)
    logger.info("amfi_api: latest TER month=%s", month)

    merged: dict[str, tuple[Optional[float], Optional[float]]] = {}
    for amc_id, mf_id in _AMFI_MF_ID.items():
        rows = await _fetch_ter_for_mf(http, mf_id, month)
        parsed = _parse_ter_rows(rows)
        logger.info("amfi_api: amc=%s mf_id=%d → %d TER rows", amc_id, mf_id, len(parsed))
        merged.update(parsed)

    _TER_CACHE = merged
    logger.info("amfi_api: total TER rows merged = %d", len(merged))
    return merged


async def fetch_risk_all_amfi_api(http: aiohttp.ClientSession) -> dict[str, str]:
    """Fetch risk-o-meter for all schemes via AMFI API.

    The risk API endpoint pattern is not yet confirmed — returns empty dict
    until the endpoint is discovered.
    """
    global _RISK_CACHE
    if _RISK_CACHE is not None:
        return _RISK_CACHE

    # TODO: discover the risk-o-meter JSON API endpoint from the
    #       /risk-parameters page JS bundle (same approach as TER).
    logger.warning("amfi_api: risk-o-meter JSON API not yet implemented")
    _RISK_CACHE = {}
    return _RISK_CACHE


def clear_cache() -> None:
    global _TER_CACHE, _RISK_CACHE
    _TER_CACHE = None
    _RISK_CACHE = None
