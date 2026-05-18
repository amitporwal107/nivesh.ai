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
import re
from datetime import date
from typing import Awaitable, Callable, Optional

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

AdapterFn = Callable[[aiohttp.ClientSession, date], Awaitable[list[dict]]]


async def sbi(http: aiohttp.ClientSession, as_of_month: date) -> list[dict]:
    return await _amfi_holdings_adapter("sbi", http, as_of_month)


# ── URL-candidate registries ─────────────────────────────────────────
# Each entry: (amc_id, portfolio_page, [url_templates])
# Templates support: {month} lowercase, {Month} title-case, {mm} zero-padded,
# {yyyy} four-digit year.  Add patterns as AMCs change their naming.
#
# All these URLs are SEBI-mandated disclosures published by the 10th of
# each month.  When a pattern 404s, check the AMC's own portfolio/downloads
# page and add the new pattern here.

_URL_TEMPLATES: dict[str, list[str]] = {
    "sbi": [
        "https://www.sbimf.com/docs/default-source/portfolios/portfolio-disclosure-{month}-{yyyy}.xlsx",
        "https://www.sbimf.com/docs/default-source/portfolios/portfolio-{month}-{yyyy}.xlsx",
        "https://www.sbimf.com/docs/default-source/portfolios/portfolio-disclosure-{Month}-{yyyy}.xlsx",
        "https://www.sbimf.com/docs/default-source/portfolios/portfolio{mm}{yyyy}.xlsx",
        "https://www.sbimf.com/docs/default-source/portfolios/sbi-mf-portfolio-{month}-{yyyy}.xlsx",
    ],
    "icici_pru": [
        "https://www.icicipruamc.com/downloads/portfolio-{month}-{yyyy}.xlsx",
        "https://www.icicipruamc.com/downloads/portfolio-disclosure-{month}-{yyyy}.xlsx",
        "https://www.icicipruamc.com/downloads/monthly-portfolio-{month}-{yyyy}.xlsx",
        "https://www.icicipruamc.com/docs/default-source/downloads/portfolio-{Month}-{yyyy}.xlsx",
        "https://www.icicipruamc.com/InvestorServices/PortfolioDisclosure/Portfolio_{Month}_{yyyy}.xlsx",
    ],
    "hdfc": [
        "https://www.hdfcfund.com/downloads/portfolio-disclosures/portfolio-{month}-{yyyy}.xlsx",
        "https://www.hdfcfund.com/downloads/portfolio-{month}-{yyyy}.xlsx",
        "https://www.hdfcfund.com/media/downloads/portfolio/{Month}_{yyyy}_Portfolio.xlsx",
        "https://www.hdfcfund.com/media/downloads/portfolio/portfolio-disclosure-{month}-{yyyy}.xlsx",
    ],
    "nippon": [
        "https://mf.nipponindiaim.com/downloads/portfolio-disclosure-{month}-{yyyy}.xlsx",
        "https://mf.nipponindiaim.com/downloads/portfolio-{month}-{yyyy}.xlsx",
        "https://mf.nipponindiaim.com/InvestorCorner/Downloads/PortfolioDisclosure_{Month}{yyyy}.xlsx",
        "https://mf.nipponindiaim.com/Downloads/PortfolioDisclosure/{Month}_{yyyy}.xlsx",
    ],
    "kotak": [
        "https://www.kotakmf.com/downloads/portfolio-disclosure-{month}-{yyyy}.xlsx",
        "https://www.kotakmf.com/downloads/portfolio-{month}-{yyyy}.xlsx",
        "https://www.kotakmf.com/documents/portfolio-disclosure/{Month}-{yyyy}.xlsx",
        "https://www.kotakmf.com/documents/portfolio/{Month}_{yyyy}_portfolio.xlsx",
    ],
    "absl": [
        "https://mutualfund.adityabirlacapital.com/downloads/portfolio-disclosure-{month}-{yyyy}.xlsx",
        "https://mutualfund.adityabirlacapital.com/downloads/portfolio-{month}-{yyyy}.xlsx",
        "https://mutualfund.adityabirlacapital.com/docs/default-source/downloads/portfolio-{Month}-{yyyy}.xlsx",
        "https://mutualfund.adityabirlacapital.com/documents/portfolio/{Month}{yyyy}.xlsx",
    ],
    "uti": [
        "https://www.utimf.com/downloads/portfolio-disclosure-{month}-{yyyy}.xlsx",
        "https://www.utimf.com/downloads/portfolio-{month}-{yyyy}.xlsx",
        "https://www.utimf.com/siteassets/downloads/portfolio-disclosure/{Month}_{yyyy}.xlsx",
        "https://www.utimf.com/siteassets/downloads/portfolio-disclosure/portfolio-{month}-{yyyy}.xlsx",
    ],
    "axis": [
        "https://www.axismf.com/downloads/portfolio-disclosure-{month}-{yyyy}.xlsx",
        "https://www.axismf.com/downloads/portfolio-{month}-{yyyy}.xlsx",
        "https://www.axismf.com/documents/portfolio/{Month}_{yyyy}_portfolio_disclosure.xlsx",
        "https://www.axismf.com/media/downloads/portfolio-{month}-{yyyy}.xlsx",
    ],
    "tata": [
        "https://www.tatamutualfund.com/downloads/portfolio-disclosure-{month}-{yyyy}.xlsx",
        "https://www.tatamutualfund.com/downloads/portfolio-{month}-{yyyy}.xlsx",
        "https://www.tatamutualfund.com/siteassets/documents/portfolio-disclosure/{Month}-{yyyy}.xlsx",
        "https://www.tatamutualfund.com/documents/portfolio/{Month}_{yyyy}.xlsx",
    ],
    "mirae": [
        "https://www.miraeassetmf.co.in/downloads/portfolio-disclosure-{month}-{yyyy}.xlsx",
        "https://www.miraeassetmf.co.in/downloads/portfolio-{month}-{yyyy}.xlsx",
        "https://www.miraeassetmf.co.in/uploads/downloads/portfolio-{Month}-{yyyy}.xlsx",
        "https://www.miraeassetmf.co.in/assets/downloads/portfolio/{Month}_{yyyy}.xlsx",
    ],
}

# AMC portfolio listing pages — scraped first to auto-discover the
# current xlsx link, then used in the warning message if discovery fails.
_PORTFOLIO_PAGE: dict[str, str] = {
    "sbi":       "https://www.sbimf.com/portfolios",
    "icici_pru": "https://www.icicipruamc.com/portfolio-disclosure",
    "hdfc":      "https://www.hdfcfund.com/downloads",
    "nippon":    "https://mf.nipponindiaim.com/InvestorCorner/Downloads",
    "kotak":     "https://www.kotakmf.com/portfolio-disclosure",
    "absl":      "https://mutualfund.adityabirlacapital.com/portfolio-disclosure",
    "uti":       "https://www.utimf.com/portfolio-disclosure",
    "axis":      "https://www.axismf.com/downloads",
    "tata":      "https://www.tatamutualfund.com/portfolio-disclosure",
    "mirae":     "https://www.miraeassetmf.co.in/downloads",
}


def _render_url(template: str, m: date) -> str:
    return (template
            .replace("{month}", m.strftime("%B").lower())
            .replace("{Month}", m.strftime("%B"))
            .replace("{mm}",    m.strftime("%m"))
            .replace("{yyyy}",  m.strftime("%Y")))


def _discover_xlsx_link(html: str, base_url: str, m: date) -> Optional[str]:
    """Scan the AMC portfolio listing page for an xlsx link matching `m`.

    Match on month-name (full or abbreviated, case-insensitive) AND year.
    Returns the first match; AMCs typically list most-recent-first.
    """
    month_long  = m.strftime("%B").lower()
    month_short = m.strftime("%b").lower()
    year_full   = m.strftime("%Y")
    year_short  = m.strftime("%y")

    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.search(r"\.xlsx?($|\?)", href, re.IGNORECASE):
            continue
        token_source = (href + " " + a.get_text(" ", strip=True)).lower()
        has_month = month_long in token_source or month_short in token_source
        has_year  = year_full in token_source or year_short in token_source
        if has_month and has_year:
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = base_url.rstrip("/") + href
            elif not href.startswith("http"):
                href = base_url.rstrip("/") + "/" + href.lstrip("/")
            return href
    return None


async def _try_listing_page_discovery(
    amc_id: str,
    http: aiohttp.ClientSession,
    as_of_month: date,
) -> Optional[str]:
    page = _PORTFOLIO_PAGE.get(amc_id)
    if not page:
        return None
    try:
        async with http.get(page, allow_redirects=True) as resp:
            if resp.status != 200:
                logger.info("mf_holdings[%s]: listing page returned status=%d at %s",
                            amc_id, resp.status, page)
                return None
            html = await resp.text(errors="replace")
    except Exception as e:  # noqa: BLE001
        logger.info("mf_holdings[%s]: listing page fetch error %s: %s",
                    amc_id, type(e).__name__, e)
        return None
    return _discover_xlsx_link(html, page, as_of_month)


async def _try_download(
    http: aiohttp.ClientSession,
    url: str,
    amc_id: str,
) -> Optional[bytes]:
    try:
        async with http.get(url, allow_redirects=True) as resp:
            if resp.status != 200:
                logger.debug("mf_holdings[%s]: %s → status=%d", amc_id, url, resp.status)
                return None
            ct = resp.headers.get("content-type", "").lower()
            if "html" in ct:
                logger.debug("mf_holdings[%s]: %s → html content-type (likely error page)", amc_id, url)
                return None
            data = await resp.read()
            if len(data) < 1024:
                logger.debug("mf_holdings[%s]: %s → suspiciously small (%d bytes)", amc_id, url, len(data))
                return None
            return data
    except Exception as e:  # noqa: BLE001
        logger.debug("mf_holdings[%s]: %s → %s: %s", amc_id, url, type(e).__name__, e)
        return None


async def _fetch_portfolio(
    amc_id: str,
    http: aiohttp.ClientSession,
    as_of_month: date,
) -> tuple[Optional[bytes], Optional[str]]:
    # 1) Listing-page auto-discovery (robust to URL renames).
    discovered = await _try_listing_page_discovery(amc_id, http, as_of_month)
    if discovered:
        data = await _try_download(http, discovered, amc_id)
        if data is not None:
            logger.info("mf_holdings[%s]: discovered xlsx via listing page: %s", amc_id, discovered)
            return data, discovered

    # 2) Hardcoded URL templates as fallback.
    templates = _URL_TEMPLATES.get(amc_id, [])
    for tmpl in templates:
        url = _render_url(tmpl, as_of_month)
        data = await _try_download(http, url, amc_id)
        if data is not None:
            return data, url

    logger.warning(
        "mf_holdings[%s]: no portfolio Excel found for %s; "
        "listing-page discovery failed and %d URL pattern(s) returned no xlsx. "
        "Inspect %s in a browser and either add a current pattern to "
        "_URL_TEMPLATES or confirm the listing page exposes a matching link.",
        amc_id, as_of_month.isoformat(), len(templates),
        _PORTFOLIO_PAGE.get(amc_id, "(unknown)"),
    )
    return None, None


async def _amfi_holdings_adapter(
    amc_id: str,
    http: aiohttp.ClientSession,
    as_of_month: date,
) -> list[dict]:
    from .sbi_parser import parse_portfolio_xlsx
    from nidp.shared.storage.pg import get_pool

    data, used_url = await _fetch_portfolio(amc_id, http, as_of_month)
    if data is None:
        return []

    source_tag = f"{amc_id.upper()}_MF_PORTFOLIO_XLSX"
    raw_rows = parse_portfolio_xlsx(data, as_of_month, source_url=used_url,
                                    source_tag=source_tag)
    if not raw_rows:
        return []

    pool = await get_pool()
    async with pool.acquire() as conn:
        db_schemes = await conn.fetch(
            """
            SELECT m.scheme_code, m.scheme_name
              FROM nidp.mf_scheme_master m
              JOIN nidp.mf_amc_master    a ON a.id = m.amc_id
             WHERE a.amc_id = $1
            """,
            amc_id,
        )
    name_to_code: dict[str, str] = {
        r["scheme_name"].lower(): r["scheme_code"] for r in db_schemes
    }

    resolved: list[dict] = []
    unmapped: set[str] = set()
    for row in raw_rows:
        raw_name = (row["scheme_code"] or "").lower().strip()
        code = name_to_code.get(raw_name)
        if code is None:
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
            "mf_holdings[%s]: %d scheme names unresolved to AMFI codes: %s",
            amc_id, len(unmapped), list(unmapped)[:5],
        )
    logger.info("mf_holdings[%s]: %d/%d rows resolved from %s",
                amc_id, len(resolved), len(raw_rows), used_url)
    return resolved


async def icici_pru(http: aiohttp.ClientSession, m: date) -> list[dict]:
    return await _amfi_holdings_adapter("icici_pru", http, m)

async def hdfc(http: aiohttp.ClientSession, m: date) -> list[dict]:
    return await _amfi_holdings_adapter("hdfc", http, m)

async def nippon(http: aiohttp.ClientSession, m: date) -> list[dict]:
    return await _amfi_holdings_adapter("nippon", http, m)

async def kotak(http: aiohttp.ClientSession, m: date) -> list[dict]:
    return await _amfi_holdings_adapter("kotak", http, m)

async def absl(http: aiohttp.ClientSession, m: date) -> list[dict]:
    return await _amfi_holdings_adapter("absl", http, m)

async def uti(http: aiohttp.ClientSession, m: date) -> list[dict]:
    return await _amfi_holdings_adapter("uti", http, m)

async def axis(http: aiohttp.ClientSession, m: date) -> list[dict]:
    return await _amfi_holdings_adapter("axis", http, m)

async def tata(http: aiohttp.ClientSession, m: date) -> list[dict]:
    return await _amfi_holdings_adapter("tata", http, m)

async def mirae(http: aiohttp.ClientSession, m: date) -> list[dict]:
    return await _amfi_holdings_adapter("mirae", http, m)


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
