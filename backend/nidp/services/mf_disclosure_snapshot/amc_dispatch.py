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

Each adapter is its own self-contained scrape. Keep them small,
log selectors when they break, and prefer XHR/JSON endpoints over
DOM scraping when the AMC offers either.
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

import aiohttp

logger = logging.getLogger(__name__)

AdapterFn = Callable[[aiohttp.ClientSession], Awaitable[list[dict]]]


async def sbi(http: aiohttp.ClientSession) -> list[dict]:
    return await _amfi_central_adapter("sbi", http)


async def _amfi_central_adapter(
    amc_id: str,
    http: aiohttp.ClientSession,
) -> list[dict]:
    """Generic AMFI-central adapter for any top-10 AMC.

    TER and risk-o-meter come from AMFI's all-scheme Excel disclosures;
    we filter to the given AMC's scheme codes from mf_scheme_master.
    Fund manager data is not available from AMFI central — left None until
    a per-AMC factsheet scraper is added.
    """
    from .amfi_central import fetch_ter_all, fetch_risk_all
    from nidp.shared.storage.pg import get_pool

    ter_map  = await fetch_ter_all(http)
    risk_map = await fetch_risk_all(http)

    if not ter_map and not risk_map:
        logger.warning("mf_disclosure_snapshot[%s]: both TER and risk-o-meter empty", amc_id)
        return []

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
    codes = {r["scheme_code"] for r in rows}
    if not codes:
        logger.warning("mf_disclosure_snapshot[%s]: no schemes in mf_scheme_master yet", amc_id)
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
            "source_url": "https://www.amfiindia.com/research-information/other-data/ter",
        })
    logger.info("mf_disclosure_snapshot[%s]: %d rows assembled", amc_id, len(result))
    return result


async def icici_pru(http: aiohttp.ClientSession) -> list[dict]:
    return await _amfi_central_adapter("icici_pru", http)

async def hdfc(http: aiohttp.ClientSession) -> list[dict]:
    return await _amfi_central_adapter("hdfc", http)

async def nippon(http: aiohttp.ClientSession) -> list[dict]:
    return await _amfi_central_adapter("nippon", http)

async def kotak(http: aiohttp.ClientSession) -> list[dict]:
    return await _amfi_central_adapter("kotak", http)

async def absl(http: aiohttp.ClientSession) -> list[dict]:
    return await _amfi_central_adapter("absl", http)

async def uti(http: aiohttp.ClientSession) -> list[dict]:
    return await _amfi_central_adapter("uti", http)

async def axis(http: aiohttp.ClientSession) -> list[dict]:
    return await _amfi_central_adapter("axis", http)

async def tata(http: aiohttp.ClientSession) -> list[dict]:
    return await _amfi_central_adapter("tata", http)

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
