"""Per-AMC SID/factsheet adapters for mf_disclosure_snapshot.

Contract: each adapter is an async function

    async def adapter(http: aiohttp.ClientSession) -> list[dict]

returning rows shaped for nidp.mf_scheme_disclosure_snapshot:

    {
      "scheme_code":       str,
      "ter_pct":           Optional[float],
      "ter_pct_direct":    Optional[float],
      "risk_o_meter":      Optional[str],   # 'Low'..'Very High'
      "primary_manager":   Optional[str],
      "secondary_manager": Optional[str],
      "aum_inr_crore":     Optional[float],
      "source_url":        str,
    }

Adapters are registered in ADAPTERS keyed by amc_id. Missing adapters
are logged once and contribute zero rows — the orchestrator marks the
JobRun PARTIAL rather than FAILED, so the implemented AMCs continue
to land snapshots.

--- Tier routing (2026-05 — AMFI central migrated to Next.js SPA) ---

T1/T2 AMCs (hdfc, nippon, sbi, tata, uti):
  → _t1_adapter()  — static HTML discovery (BeautifulSoup)
  → ter_scraper.fetch_ter_t1() → discovery.discover_latest_file()

T3/T4 AMCs (icici_pru, axis, kotak, absl, mirae):
  → _amfi_central_adapter() — tries AMFI JSON API, returns [] until
    Playwright is installed on the VM (deferred, logged as missing).

Architecture: docs/NIDP_FEEDS/AMC_DISCLOSURES_AND_TER_REPORTS_STARTEGY.md
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

import aiohttp

logger = logging.getLogger(__name__)

AdapterFn = Callable[[aiohttp.ClientSession], Awaitable[list[dict]]]

# T1/T2 AMCs: static HTML discovery, no browser needed
_T1_AMCS = {"sbi", "hdfc", "nippon", "tata", "uti"}

# T3/T4 AMCs: deferred until Playwright installed on VM
_T3_AMCS = {"icici_pru", "axis", "kotak", "absl", "mirae"}


async def _get_amc_schemes(amc_id: str) -> set[str]:
    """Return scheme codes belonging to this AMC from mf_scheme_master."""
    from nidp.shared.storage.pg import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT m.scheme_code
              FROM nidp.mf_scheme_master m
              JOIN nidp.mf_amc_master    a ON a.id = m.amc_id
             WHERE a.amc_id = $1
            """,
            amc_id,
        )
    return {r["scheme_code"] for r in rows}


async def _t1_adapter(amc_id: str, http: aiohttp.ClientSession) -> list[dict]:
    """T1/T2 adapter: static HTML discovery → per-AMC TER xlsx download + parse.

    Filters the parsed xlsx to only this AMC's scheme codes so each adapter
    remains independent (no shared global state beyond the in-process cache
    inside ter_scraper._REGISTRY_CACHE).
    """
    from .ter_scraper import fetch_ter_t1
    from .amfi_central import fetch_risk_all

    # TER from per-AMC page (T1 discovery)
    ter_map = await fetch_ter_t1(amc_id, http)

    # Risk-o-meter: still attempt AMFI central (may return {} — that's fine)
    try:
        risk_map = await fetch_risk_all(http)
    except Exception as e:  # noqa: BLE001
        logger.warning("mf_disclosure_snapshot[%s]: risk fetch error: %s", amc_id, e)
        risk_map = {}

    if not ter_map and not risk_map:
        logger.warning("mf_disclosure_snapshot[%s]: T1 adapter produced no data", amc_id)
        return []

    codes = await _get_amc_schemes(amc_id)
    if not codes:
        logger.warning("mf_disclosure_snapshot[%s]: no schemes in mf_scheme_master", amc_id)
        return []

    result = []
    for code in codes:
        ter_pct, ter_pct_direct = ter_map.get(code, (None, None))
        risk = risk_map.get(code)
        if ter_pct is None and ter_pct_direct is None and risk is None:
            continue
        result.append({
            "scheme_code":       code,
            "ter_pct":           ter_pct,
            "ter_pct_direct":    ter_pct_direct,
            "risk_o_meter":      risk,
            "primary_manager":   None,
            "secondary_manager": None,
            "aum_inr_crore":     None,
            "source_url":        f"registry:ter_discovery_url:{amc_id}",
        })

    logger.info("mf_disclosure_snapshot[%s]: T1 adapter produced %d rows", amc_id, len(result))
    return result


async def _amfi_central_adapter(amc_id: str, http: aiohttp.ClientSession) -> list[dict]:
    """Fallback for T3/T4 AMCs — tries AMFI JSON API, returns [] until Playwright available."""
    from .amfi_central import fetch_ter_all, fetch_risk_all

    ter_map  = await fetch_ter_all(http)
    risk_map = await fetch_risk_all(http)

    if not ter_map and not risk_map:
        logger.warning(
            "mf_disclosure_snapshot[%s]: T3 adapter — AMFI central empty "
            "(Playwright not yet installed; T3 deferred)",
            amc_id,
        )
        return []

    codes = await _get_amc_schemes(amc_id)
    if not codes:
        logger.warning("mf_disclosure_snapshot[%s]: no schemes in mf_scheme_master", amc_id)
        return []

    result = []
    for code in codes:
        ter_pct, ter_pct_direct = ter_map.get(code, (None, None))
        risk = risk_map.get(code)
        if ter_pct is None and ter_pct_direct is None and risk is None:
            continue
        result.append({
            "scheme_code":       code,
            "ter_pct":           ter_pct,
            "ter_pct_direct":    ter_pct_direct,
            "risk_o_meter":      risk,
            "primary_manager":   None,
            "secondary_manager": None,
            "aum_inr_crore":     None,
            "source_url":        "https://www.amfiindia.com/ter-of-mf-schemes",
        })
    logger.info("mf_disclosure_snapshot[%s]: %d rows assembled", amc_id, len(result))
    return result


# --- Individual adapters ---

async def sbi(http: aiohttp.ClientSession) -> list[dict]:
    return await _t1_adapter("sbi", http)

async def hdfc(http: aiohttp.ClientSession) -> list[dict]:
    return await _t1_adapter("hdfc", http)

async def nippon(http: aiohttp.ClientSession) -> list[dict]:
    return await _t1_adapter("nippon", http)

async def tata(http: aiohttp.ClientSession) -> list[dict]:
    return await _t1_adapter("tata", http)

async def uti(http: aiohttp.ClientSession) -> list[dict]:
    return await _t1_adapter("uti", http)

# T3/T4 — deferred; uses AMFI central fallback (returns [] currently)
async def icici_pru(http: aiohttp.ClientSession) -> list[dict]:
    return await _amfi_central_adapter("icici_pru", http)

async def kotak(http: aiohttp.ClientSession) -> list[dict]:
    return await _amfi_central_adapter("kotak", http)

async def absl(http: aiohttp.ClientSession) -> list[dict]:
    return await _amfi_central_adapter("absl", http)

async def axis(http: aiohttp.ClientSession) -> list[dict]:
    return await _amfi_central_adapter("axis", http)

async def mirae(http: aiohttp.ClientSession) -> list[dict]:
    return await _amfi_central_adapter("mirae", http)


ADAPTERS: dict[str, AdapterFn] = {
    "sbi":       sbi,
    "icici_pru": icici_pru,
    "hdfc":      hdfc,
    "nippon":    nippon,
    "kotak":     kotak,
    "absl":      absl,
    "uti":       uti,
    "axis":      axis,
    "tata":      tata,
    "mirae":     mirae,
}


def get_adapter(amc_id: str) -> Optional[AdapterFn]:
    return ADAPTERS.get(amc_id)
