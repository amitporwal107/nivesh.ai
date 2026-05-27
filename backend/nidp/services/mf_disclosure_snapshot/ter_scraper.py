"""T1/T2 TER scraper using the Phase 1 static HTML discovery engine.

Flow per AMC:
  1. Load discovery URL + regex from mf_amc_source_registry
  2. discover_latest_file() → latest TER xlsx/pdf URL
  3. Download + parse → {scheme_code: (ter_regular, ter_direct)}
  4. Caller filters to this AMC's scheme codes

Only handles extraction_strategy='static_html'. T3/T4 (playwright, xhr)
are deferred until Playwright is installed on the VM.
"""
from __future__ import annotations

import io
import logging
from typing import Optional

import aiohttp
import openpyxl

from .discovery import discover_latest_file, discover_latest_file_multi

logger = logging.getLogger(__name__)

# Registry cache: amc_id → {ter_discovery_url, regex_pattern, tier, ...}
_REGISTRY_CACHE: Optional[dict[str, dict]] = None


async def _load_registry() -> dict[str, dict]:
    """Load mf_amc_source_registry into memory (cached per process)."""
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is not None:
        return _REGISTRY_CACHE

    from nidp.shared.storage.pg import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT amc_id, tier, extraction_strategy,
                   ter_discovery_url, regex_pattern
              FROM nidp.mf_amc_source_registry
             WHERE active = TRUE
            """
        )
    _REGISTRY_CACHE = {r["amc_id"]: dict(r) for r in rows}
    logger.info("ter_scraper: registry loaded for %d AMCs", len(_REGISTRY_CACHE))
    return _REGISTRY_CACHE


def _col_idx(headers: list[str], *fragments: str) -> Optional[int]:
    for frag in fragments:
        for i, h in enumerate(headers):
            if frag in h:
                return i
    return None


def _to_float(v: object) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (ValueError, AttributeError):
        return None


def _parse_ter_xlsx(data: bytes) -> dict[str, tuple[Optional[float], Optional[float]]]:
    """Parse per-AMC TER xlsx → {scheme_code: (ter_regular, ter_direct)}.

    Handles the standard AMFI/SEBI TER disclosure format:
    Scheme Code | Scheme Name | TER (Regular) % | TER (Direct) %
    """
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:
        logger.warning("ter_scraper: cannot open xlsx: %s", e)
        return {}
    ws = wb.active
    raw = list(ws.iter_rows(values_only=True))
    if not raw:
        return {}

    # Find header row (first row containing 'scheme' or 'code')
    header_row = 0
    for i, row in enumerate(raw):
        cells = [str(c or "").lower() for c in row]
        if any("scheme" in c or "code" in c for c in cells):
            header_row = i
            break

    headers = [str(c or "").strip().lower() for c in raw[header_row]]
    code_col  = _col_idx(headers, "scheme code", "amfi code", "schemecode", "scheme_code")
    ter_r_col = _col_idx(headers, "ter (regular", "regular plan", "ter%", "ter (r", "regular ter", "regular")
    ter_d_col = _col_idx(headers, "ter (direct", "direct plan", "ter (d", "direct ter", "direct")

    if code_col is None:
        logger.warning("ter_scraper: no scheme-code column; headers=%s", headers[:8])
        return {}

    result: dict[str, tuple[Optional[float], Optional[float]]] = {}
    for row in raw[header_row + 1:]:
        if not row or row[code_col] is None:
            continue
        code = str(row[code_col]).strip()
        if not code or not code[0].isdigit():
            continue

        def _f(col: Optional[int]) -> Optional[float]:
            if col is None or col >= len(row):
                return None
            return _to_float(row[col])

        result[code] = (_f(ter_r_col), _f(ter_d_col))

    return result


async def fetch_ter_t1(
    amc_id: str,
    http: aiohttp.ClientSession,
) -> dict[str, tuple[Optional[float], Optional[float]]]:
    """Fetch TER for a T1/T2 AMC using the static HTML discovery engine.

    Returns {scheme_code: (ter_regular_pct, ter_direct_pct)}.
    Returns {} on any failure — caller treats as missing, not crash.
    """
    registry = await _load_registry()
    meta = registry.get(amc_id)
    if not meta:
        logger.warning("ter_scraper[%s]: not in registry", amc_id)
        return {}

    tier = meta.get("tier", "T1")
    strategy = meta.get("extraction_strategy", "static_html")
    if strategy != "static_html":
        logger.info(
            "ter_scraper[%s]: strategy=%s (tier=%s) — skipping, only static_html supported now",
            amc_id, strategy, tier,
        )
        return {}

    discovery_url = meta.get("ter_discovery_url")
    regex_pattern = meta.get("regex_pattern") or r".*(expense|ter|ratio).*\.(pdf|xlsx)"

    if not discovery_url:
        logger.warning("ter_scraper[%s]: no ter_discovery_url in registry", amc_id)
        return {}

    logger.info("ter_scraper[%s]: discovering TER file from %s", amc_id, discovery_url)
    file_url = await discover_latest_file(
        discovery_url, regex_pattern, http, label=f"{amc_id}_ter"
    )
    if not file_url:
        logger.warning("ter_scraper[%s]: no TER file discovered", amc_id)
        return {}

    # Prefer xlsx over pdf (pdf parsing not implemented yet)
    if file_url.lower().endswith(".pdf") or ".pdf?" in file_url.lower():
        logger.info("ter_scraper[%s]: TER file is PDF — skipping (xlsx only for now)", amc_id)
        return {}

    try:
        async with http.get(file_url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
            resp.raise_for_status()
            data = await resp.read()
    except Exception as e:
        logger.warning("ter_scraper[%s]: download failed %s: %s", amc_id, file_url, e)
        return {}

    result = _parse_ter_xlsx(data)
    logger.info("ter_scraper[%s]: parsed %d TER rows from %s", amc_id, len(result), file_url[-60:])
    return result


def clear_registry_cache() -> None:
    """Reset registry cache (testing / forced refresh)."""
    global _REGISTRY_CACHE
    _REGISTRY_CACHE = None
