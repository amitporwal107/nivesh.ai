"""Per-AMC monthly-portfolio adapters.

Contract: each adapter is

    async def adapter(http: aiohttp.ClientSession,
                      as_of_month: date) -> list[dict]

returning rows shaped for nidp.mf_holdings_monthly:

    {
      "scheme_code":      str,
      "as_of_month":      "YYYY-MM-01",
      "security_isin":    Optional[str],
      "security_name":    str,
      "instrument_type":  Optional[str],   # 'EQUITY'|'DEBT'|'CASH'|'DERIVATIVE'|'REIT'|'OTHER'
      "sector":           Optional[str],
      "rating":           Optional[str],
      "quantity":         Optional[float],
      "market_value_inr": Optional[float],
      "weight_pct":       Optional[float],
      "source":           str,              # e.g. 'SBI_MF_PORTFOLIO_XLSX'
      "source_url":       str,
    }

Adapters are registered in ADAPTERS keyed by amc_id. Stub
implementations contribute zero rows; the orchestrator marks the run
PARTIAL until each is filled in.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Awaitable, Callable, Optional

import aiohttp

logger = logging.getLogger(__name__)

AdapterFn = Callable[[aiohttp.ClientSession, date], Awaitable[list[dict]]]


async def _stub(amc_id: str, http: aiohttp.ClientSession, as_of_month: date) -> list[dict]:
    logger.warning(
        "mf_holdings[%s]: adapter not implemented — skipping. Add scraper "
        "at nidp/services/mf_holdings/amc_<id>.py and register here.", amc_id,
    )
    return []


async def sbi(http: aiohttp.ClientSession, as_of_month: date) -> list[dict]:
    """Fetch SBI MF monthly portfolio for as_of_month.

    SBI MF's portfolios page (https://www.sbimf.com/portfolios) is JS-rendered.
    We probe a set of predictable direct-download URL patterns based on SBI's
    historical file-naming convention. If all patterns return non-200, the
    adapter returns [] and the run is marked PARTIAL.

    If a new URL pattern is needed, add it to `_url_candidates()` below.
    """
    from .sbi_parser import parse_portfolio_xlsx
    from nidp.shared.storage.pg import get_pool

    data, used_url = await _sbi_fetch_portfolio(http, as_of_month)
    if data is None:
        return []

    raw_rows = parse_portfolio_xlsx(data, as_of_month, source_url=used_url)
    if not raw_rows:
        return []

    # Resolve scheme names → AMFI scheme codes via DB.
    pool = await get_pool()
    async with pool.acquire() as conn:
        sbi_schemes = await conn.fetch(
            """
            SELECT m.scheme_code, m.scheme_name
              FROM nidp.mf_scheme_master m
              JOIN nidp.mf_amc_master    a ON a.id = m.amc_id
             WHERE a.amc_id = 'sbi'
            """
        )
    name_to_code: dict[str, str] = {
        r["scheme_name"].lower(): r["scheme_code"] for r in sbi_schemes
    }

    resolved: list[dict] = []
    unmapped = set()
    for row in raw_rows:
        raw_name = (row["scheme_code"] or "").lower().strip()
        code = name_to_code.get(raw_name)
        if code is None:
            # Partial name match — find closest prefix
            for name, c in name_to_code.items():
                if raw_name and (raw_name in name or name in raw_name):
                    code = c
                    break
        if code is None:
            unmapped.add(row["scheme_code"])
            continue
        resolved.append({**row, "scheme_code": code})

    if unmapped:
        logger.warning(
            "mf_holdings[sbi]: %d scheme names unresolved to AMFI codes: %s",
            len(unmapped), list(unmapped)[:5],
        )
    logger.info("mf_holdings[sbi]: %d/%d rows resolved from %s",
                len(resolved), len(raw_rows), used_url)
    return resolved


def _sbi_url_candidates(m: date) -> list[str]:
    month = m.strftime("%B").lower()    # "april"
    Month = m.strftime("%B")            # "April"
    mm    = m.strftime("%m")            # "04"
    yyyy  = m.strftime("%Y")            # "2026"
    base  = "https://www.sbimf.com/docs/default-source/portfolios"
    return [
        f"{base}/portfolio-disclosure-{month}-{yyyy}.xlsx",
        f"{base}/portfolio-{month}-{yyyy}.xlsx",
        f"{base}/portfolio-disclosure-{Month}-{yyyy}.xlsx",
        f"{base}/portfolio{mm}{yyyy}.xlsx",
        f"{base}/sbi-mf-portfolio-{month}-{yyyy}.xlsx",
        f"{base}/sbimf-portfolio-{month}{yyyy}.xlsx",
    ]


async def _sbi_fetch_portfolio(
    http: aiohttp.ClientSession,
    as_of_month: date,
) -> tuple[Optional[bytes], Optional[str]]:
    candidates = _sbi_url_candidates(as_of_month)
    for url in candidates:
        try:
            async with http.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    continue
                ct = resp.headers.get("content-type", "").lower()
                if "html" in ct:
                    continue        # redirect to error page
                data = await resp.read()
                if len(data) < 1024:
                    continue        # suspiciously small — likely an error page
                return data, url
        except Exception:           # noqa: BLE001
            continue
    logger.warning(
        "mf_holdings[sbi]: no portfolio Excel found for %s; tried %d URL patterns. "
        "Verify current URL at https://www.sbimf.com/portfolios and update "
        "_sbi_url_candidates() in nidp/services/mf_holdings/amc_dispatch.py",
        as_of_month.isoformat(), len(candidates),
    )
    return None, None


async def icici_pru(http, m): return await _stub("icici_pru", http, m)
async def hdfc(http, m):      return await _stub("hdfc", http, m)
async def nippon(http, m):    return await _stub("nippon", http, m)
async def kotak(http, m):     return await _stub("kotak", http, m)
async def absl(http, m):      return await _stub("absl", http, m)
async def uti(http, m):       return await _stub("uti", http, m)
async def axis(http, m):      return await _stub("axis", http, m)
async def tata(http, m):      return await _stub("tata", http, m)
async def mirae(http, m):     return await _stub("mirae", http, m)


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
