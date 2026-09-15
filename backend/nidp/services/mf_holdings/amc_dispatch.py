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

import asyncio
import logging
import re
from datetime import date
from typing import Awaitable, Callable, Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

AdapterFn = Callable[[aiohttp.ClientSession, date], Awaitable[list[dict]]]


# ---------------------------------------------------------------------------
# Scheme-name → AMFI scheme_code resolution
# ---------------------------------------------------------------------------
# Excel portfolio files name a fund once (no plan/option suffix); the AMFI master
# has one row per plan variant (Regular/Direct × Growth/IDCW/…). We must map the
# Excel name to ALL its plan-variant codes, and ONLY those.
#
# The previous heuristic ("split at the first '(' or '-'") collapsed distinct
# funds that share a prefix before a parenthetical — e.g. every "SBI Fixed
# Maturity Plan (FMP) - Series N" became base "sbi fixed maturity plan", so 20
# FMP series' holdings were written to ALL FMP codes (per-scheme weight summed to
# >1000%). The fix derives a "fund identity" by stripping only the *plan suffix*,
# then matches in precision order (exact → identity → boundary-prefix → space-
# insensitive) so e.g. Series 1 never matches Series 14.
# Strip the plan/option tail so all variants of a fund share one identity.
# Includes bare option keywords (Growth/IDCW/…) because some AMCs name the
# Regular plan "X Fund - Growth" with NO "Regular" word — without these, the
# Regular variants got a distinct identity and were dropped from resolution
# (only the Direct variants matched), roughly halving holdings coverage.
# Series numbers ("- Series 14") are NOT keywords, so FMP series stay distinct.
_PLAN_SUFFIX_RE = re.compile(
    r"\s*-\s*(regular|direct|institutional|retail|growth|idcw|dividend|payout|"
    r"reinvest\w*|bonus|income distribution|daily|weekly|monthly|quarterly|"
    r"annual|half.?yearly|fortnightly)\b.*$", re.I)
_ERSTWHILE_RE = re.compile(r"\s*\(erstwhile[^)]*\)", re.I)


def _norm_scheme_name(s: str) -> str:
    """Lowercase + normalise punctuation/spacing for robust matching."""
    s = _ERSTWHILE_RE.sub("", s.lower())   # drop "(Erstwhile known as …)" descriptors
    s = s.replace("&", " and ")            # "Banking & Financial" == "Banking And Financial"
    s = re.sub(r"[:/]", " ", s)            # "50:50" == "50 50"
    s = re.sub(r"\s*-\s*", "-", s)         # normalise hyphen spacing
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _scheme_identity(name: str) -> str:
    """Fund identity = scheme name with the '- <Regular|Direct> Plan - <Option>'
    tail removed. Distinguishes FMP Series 1 from Series 14, which a naive split
    collapsed."""
    return _norm_scheme_name(_PLAN_SUFFIX_RE.sub("", name.strip()))


def _build_scheme_index(db_schemes) -> dict:
    """Index AMFI master rows (need .scheme_code, .scheme_name) for resolution."""
    name_to_codes: dict[str, list[str]] = {}
    ident_to_codes: dict[str, list[str]] = {}
    sp_to_codes: dict[str, list[str]] = {}     # space/punct-insensitive (last resort)
    for r in db_schemes:
        name_to_codes.setdefault(_norm_scheme_name(r["scheme_name"]), []).append(r["scheme_code"])
        ident = _scheme_identity(r["scheme_name"])
        ident_to_codes.setdefault(ident, []).append(r["scheme_code"])
        sp_to_codes.setdefault(re.sub(r"[^a-z0-9]", "", ident), []).append(r["scheme_code"])
    return {"name": name_to_codes, "ident": ident_to_codes, "sp": sp_to_codes}


def _resolve_scheme_codes(raw_name: str, index: dict) -> list[str]:
    """Resolve an Excel fund name to AMFI codes, most-precise tier first."""
    nm = _norm_scheme_name(raw_name)
    if nm in index["name"]:
        return index["name"][nm]
    ident = _scheme_identity(raw_name)
    if ident in index["ident"]:
        return index["ident"][ident]
    # Boundary-prefix: Excel "…Series 1" is a prefix of DB "…Series 1 (3668 Days)".
    # Require a non-alphanumeric boundary so "Series 1" never matches "Series 14".
    out = [c for di, codes in index["ident"].items()
           if di.startswith(ident) and (len(di) == len(ident) or not di[len(ident)].isalnum())
           for c in codes]
    if out:
        return out
    # Last resort: ignore all spacing/punctuation ("Smallcap" == "Small Cap").
    return list(index["sp"].get(re.sub(r"[^a-z0-9]", "", ident), []))


async def _sbi_multisheet_adapter(
    http: aiohttp.ClientSession,
    as_of_month: date,
) -> list[dict]:
    """SBI publishes a single multi-sheet xlsx (one sheet per base fund).
    Uses the SBI-specific parser instead of the generic single-sheet parser.
    """
    from .sbi_parser import parse_sbi_multisheet_xlsx
    from nidp.shared.storage.pg import get_pool

    amc_id = "sbi"
    data, used_url = await _fetch_portfolio(amc_id, http, as_of_month)
    if data is None:
        return []

    source_tag = "SBI_MF_PORTFOLIO_XLSX"
    raw_rows = parse_sbi_multisheet_xlsx(data, as_of_month,
                                         source_url=used_url or "",
                                         source_tag=source_tag)
    if not raw_rows:
        logger.warning("mf_holdings[sbi]: parse_sbi_multisheet_xlsx returned 0 rows")
        return []

    # Resolve fund-base-name (from Index sheet) → AMFI scheme_codes
    pool = await get_pool()
    async with pool.acquire() as conn:
        db_schemes = await conn.fetch(
            "SELECT scheme_code, scheme_name FROM nidp.mf_scheme_master WHERE amc_id = $1",
            amc_id,
        )

    index = _build_scheme_index(db_schemes)

    resolved: list[dict] = []
    unmapped: set[str] = set()
    for row in raw_rows:
        codes = _resolve_scheme_codes(row["scheme_code"] or "", index)
        if not codes:
            unmapped.add(row["scheme_code"])
        else:
            for code in codes:
                resolved.append({**row, "scheme_code": code})

    if unmapped:
        logger.warning("mf_holdings[sbi]: %d fund names unresolved: %s",
                       len(unmapped), sorted(unmapped)[:5])
    resolved_schemes = len({r["scheme_code"] for r in resolved})
    logger.info("mf_holdings[sbi]: %d raw rows → %d resolved across %d scheme_codes (from %s)",
                len(raw_rows), len(resolved), resolved_schemes, used_url)
    return resolved


async def sbi(http: aiohttp.ClientSession, as_of_month: date) -> list[dict]:
    return await _sbi_multisheet_adapter(http, as_of_month)


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
        # VERIFIED 2026-05 — stable CDN URL with ordinal day suffix
        "https://www.sbimf.com/docs/default-source/scheme-portfolios/all-schemes-monthly-portfolio---as-on-{dom_ord}-{month}-{yyyy}.xlsx",
        "https://www.sbimf.com/docs/default-source/portfolios/portfolio-disclosure-{month}-{yyyy}.xlsx",
        "https://www.sbimf.com/docs/default-source/portfolios/portfolio-{month}-{yyyy}.xlsx",
        "https://www.sbimf.com/docs/default-source/portfolios/portfolio-disclosure-{Month}-{yyyy}.xlsx",
        "https://www.sbimf.com/docs/default-source/portfolios/portfolio{mm}{yyyy}.xlsx",
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
        # VERIFIED 2026-06: betacms CDN; folder = publication month ({pub_yyyy}-{pub_mm})
        # Filename uses spaces between ordinal and month (not hyphens).
        "https://betacms.tatamutualfund.com/system/files/{pub_yyyy}-{pub_mm}/Monthly%20Portfolio%20as%20on%20{dom_ord}%20{Month}%20{yyyy}%20%281%29.xlsx",
        "https://betacms.tatamutualfund.com/system/files/{pub_yyyy}-{pub_mm}/Monthly%20Portfolio%20as%20on%20{dom_ord}%20{Month}%20{yyyy}.xlsx",
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

# AMC portfolio listing pages — multiple candidates per AMC because
# disclosure pages get reorganised every 6-12 months. Scraped in order;
# first 200-OK with a month-matched xlsx link wins. When ALL candidates
# fail for an AMC, the amc_urls_drift_check daily job alerts ops the
# next morning so the gap is bounded by 24h, not 30 days.
_PORTFOLIO_PAGE_CANDIDATES: dict[str, list[str]] = {
    # ── Verified working URLs (2026-05-27) listed first ──────────────
    "sbi": [
        "https://www.sbimf.com/en-us/portfolios",           # VERIFIED ✓
        "https://www.sbimf.com/portfolios",
        "https://www.sbimf.com/downloads/portfolio-disclosure",
        "https://www.sbimf.com/scheme-documents/portfolio-disclosure",
    ],
    "hdfc": [
        "https://www.hdfcfund.com/statutory-disclosure/portfolio/monthly-portfolio",  # VERIFIED ✓
        "https://www.hdfcfund.com/statutory-disclosure/portfolio",
        "https://www.hdfcfund.com/downloads",
        "https://www.hdfcfund.com/downloads/portfolio-disclosures",
        "https://www.hdfcfund.com/our-funds/portfolio-disclosure",
    ],
    "nippon": [
        "https://mf.nipponindiaim.com/investor-service/downloads/factsheet-portfolio-and-other-disclosures",  # VERIFIED ✓
        "https://mf.nipponindiaim.com/InvestorCorner/Downloads",
        "https://mf.nipponindiaim.com/downloads/portfolio-disclosure",
        "https://mf.nipponindiaim.com/InvestorCorner/PortfolioDisclosure",
    ],
    "tata": [
        "https://www.tatamutualfund.com/schemes-related/portfolio",     # VERIFIED ✓
        "https://www.tatamutualfund.com/statutory-disclosures",
        "https://www.tatamutualfund.com/portfolio-disclosure",
        "https://www.tatamutualfund.com/downloads/portfolio-disclosure",
        "https://www.tatamutualfund.com/our-funds/portfolio-disclosure",
        "https://www.tatamutualfund.com/scheme-documents/portfolio-disclosure",
    ],
    "axis": [
        "https://www.axismf.com/statutory-disclosures",                 # VERIFIED ✓ (nested)
        "https://www.axismf.com/downloads",
        "https://www.axismf.com/downloads/portfolio-disclosure",
        "https://www.axismf.com/investor-services/portfolio-disclosure",
    ],
    # ── Not yet verified — original candidates kept as fallbacks ─────
    "icici_pru": [
        "https://www.icicipruamc.com/news-and-media/downloads?currentTabFilter=OtherSchemeDisclosures&subCatTabFilter=Monthly+Portfolio+Disclosures",
        "https://www.icicipruamc.com/portfolio-disclosure",
        "https://www.icicipruamc.com/downloads/portfolio-disclosure",
        "https://www.icicipruamc.com/forms-and-downloads/portfolio-disclosure",
    ],
    "kotak": [
        "https://www.kotakmf.com/Information/about-mutual-funds/statutory-disclosure",
        "https://www.kotakmf.com/portfolio-disclosure",
        "https://www.kotakmf.com/downloads/portfolio-disclosure",
        "https://www.kotakmf.com/investor-services/portfolio-disclosure",
        "https://www.kotakmf.com/forms-and-downloads/portfolio-disclosure",
    ],
    "absl": [
        "https://mutualfund.adityabirlacapital.com/downloads",
        "https://mutualfund.adityabirlacapital.com/resources",
        "https://mutualfund.adityabirlacapital.com/portfolio-disclosure",
        "https://mutualfund.adityabirlacapital.com/downloads/portfolio-disclosure",
        "https://mutualfund.adityabirlacapital.com/investor-education/portfolio-disclosure",
        "https://mutualfund.adityabirlacapital.com/forms-and-downloads/portfolio-disclosure",
    ],
    "uti": [
        "https://www.utimf.com/forms-and-downloads/",
        "https://www.utimf.com/factsheets/",
        "https://www.utimf.com/portfolio-disclosure",
        "https://www.utimf.com/downloads/portfolio-disclosure",
        "https://www.utimf.com/forms-and-downloads/portfolio-disclosure",
    ],
    "mirae": [
        "https://www.miraeassetmf.co.in/investor-services/statutory-disclosures",
        "https://www.miraeassetmf.co.in/downloads",
        "https://www.miraeassetmf.co.in/downloads/portfolio-disclosure",
        "https://www.miraeassetmf.co.in/forms-and-downloads/portfolio-disclosure",
    ],
}

# Compat shim — code paths that imported `_PORTFOLIO_PAGE` see the first
# candidate per AMC. Drift-check + new discovery logic prefer the list.
_PORTFOLIO_PAGE: dict[str, str] = {
    k: v[0] for k, v in _PORTFOLIO_PAGE_CANDIDATES.items()
}


def _ordinal_suffix(n: int) -> str:
    """Return ordinal suffix for an integer (1→'1st', 2→'2nd', ...)."""
    if n in (11, 12, 13):
        return f"{n}th"
    s = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{s}"


def _render_url(template: str, m: date) -> str:
    import calendar
    from datetime import timedelta
    last_day = calendar.monthrange(m.year, m.month)[1]
    # Publication month = first day of next month (SEBI M+10 disclosure; files appear month+1)
    pub = (date(m.year, m.month, 28) + timedelta(days=4)).replace(day=1)
    return (template
            .replace("{month}", m.strftime("%B").lower())
            .replace("{Month}", m.strftime("%B"))
            .replace("{mm}",    m.strftime("%m"))
            .replace("{yyyy}",  m.strftime("%Y"))
            .replace("{dom_ord}", _ordinal_suffix(last_day))
            .replace("{pub_mm}",   pub.strftime("%m"))
            .replace("{pub_yyyy}", pub.strftime("%Y")))


def _discover_xlsx_link(html: str, base_url: str, m: date) -> Optional[str]:
    """Scan the AMC portfolio listing page for an xlsx/xls link matching `m`.

    Supports two extraction modes:
      1. Standard <a href> links (most AMCs)
      2. JSON-embedded URLs (Next.js SPAs like HDFC, Tata) —
         looks for "url":"https://...xlsx" patterns in raw HTML

    Scoring (higher wins):
      +3  href/text has month name (long or short, case-insensitive)
      +2  href/text has year (4-digit or 2-digit short form)
      +2  href/text contains "portfolio" (preferred over TER/risk files)
      +1  href ends with .xlsx (preferred over .xls)

    Also logs format-drift telemetry when only PDF/CSV links match the
    target month — strong signal the AMC switched format.
    """
    month_long  = m.strftime("%B").lower()   # "april"
    month_short = m.strftime("%b").lower()   # "apr"
    year_full   = m.strftime("%Y")           # "2026"
    year_short  = m.strftime("%y")           # "26"

    # Use urlparse to get origin so /abs-paths resolve correctly
    _parsed = urlparse(base_url)
    _origin = f"{_parsed.scheme}://{_parsed.netloc}"

    def _absolutise(href: str) -> str:
        return urljoin(_origin + "/", href.lstrip("/")) if href.startswith("/") else urljoin(base_url, href)

    def _score(token_source: str, href: str) -> int:
        score = 0
        has_month = month_long in token_source or month_short in token_source
        has_year  = year_full in token_source or year_short in token_source
        if has_month:
            score += 3
        if has_year:
            score += 2
        if "portfolio" in token_source:
            score += 2
        if href.lower().endswith(".xlsx") or ".xlsx?" in href.lower():
            score += 1
        return score

    soup = BeautifulSoup(html, "lxml")
    xlsx_candidates: list[tuple[int, str]] = []  # (score, abs_href)
    alt_format_hits: list[str] = []

    # ── Pass 1: standard <a href> extraction ─────────────────────────
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("mailto:"):
            continue
        token_source = (href + " " + a.get_text(" ", strip=True)).lower()

        if re.search(r"\.xlsx?($|\?)", href, re.IGNORECASE):
            sc = _score(token_source, href)
            if sc >= 5:  # must have at least month + year match
                xlsx_candidates.append((sc, _absolutise(href)))
            continue

        # Format-drift telemetry: PDF/CSV matching the target month.
        has_month = month_long in token_source or month_short in token_source
        has_year  = year_full in token_source or year_short in token_source
        if re.search(r"\.(pdf|csv)($|\?)", href, re.IGNORECASE) and has_month and has_year:
            alt_format_hits.append(href)

    # ── Pass 2: JSON-embedded URL extraction (Next.js / Drupal SPAs) ─
    # Finds "url":"https://cdn.../april-2026.xlsx" patterns in raw HTML
    if not xlsx_candidates:
        for m_json in re.finditer(
            r'"url"\s*:\s*"(https?://[^"]+\.xlsx?[^"]*)"',
            html,
            re.IGNORECASE,
        ):
            href = m_json.group(1)
            start = max(0, m_json.start() - 200)
            context = html[start : m_json.end() + 200].lower()
            token_source = (href + " " + context).lower()
            sc = _score(token_source, href)
            if sc >= 5:
                xlsx_candidates.append((sc, href))

    # ── Pass 2b: backslash-escaped JSON (Tata Next.js SSR) ───────────
    # Tata embeds URLs as \"url\":\"https://betacms...xlsx\" in raw HTML.
    # The standard Pass 2 regex doesn't match because the quotes are escaped.
    if not xlsx_candidates:
        for m_json in re.finditer(
            r'\\"url\\"\s*:\s*\\"(https?://[^\\"]+\.xlsx?[^\\"]*)\\"',
            html,
            re.IGNORECASE,
        ):
            href = m_json.group(1)
            start = max(0, m_json.start() - 200)
            context = html[start : m_json.end() + 200].lower()
            token_source = (href + " " + context).lower()
            sc = _score(token_source, href)
            if sc >= 5:
                xlsx_candidates.append((sc, href))

    if xlsx_candidates:
        xlsx_candidates.sort(key=lambda x: x[0], reverse=True)
        logger.debug(
            "mf_holdings: %d xlsx candidates at %s; best: %s (score=%d)",
            len(xlsx_candidates), base_url,
            xlsx_candidates[0][1][-60:], xlsx_candidates[0][0],
        )
        return xlsx_candidates[0][1]

    if alt_format_hits:
        _abs0 = _absolutise(alt_format_hits[0])
        logger.info(
            "mf_holdings: format-drift detected at %s — %d non-xlsx link(s) "
            "match target month (first: %s). Add a parser to consume.",
            base_url, len(alt_format_hits), _abs0,
        )
    return None


async def _try_listing_page_discovery(
    amc_id: str,
    http: aiohttp.ClientSession,
    as_of_month: date,
) -> Optional[str]:
    """Walk the AMC's candidate listing-page URLs in order, stop at the
    first 200-OK that yields a month-matched xlsx link."""
    candidates = _PORTFOLIO_PAGE_CANDIDATES.get(amc_id) or []
    if not candidates:
        return None
    for page in candidates:
        try:
            async with http.get(page, allow_redirects=True) as resp:
                if resp.status != 200:
                    logger.debug(
                        "mf_holdings[%s]: listing candidate %s → status=%d",
                        amc_id, page, resp.status,
                    )
                    continue
                html = await resp.text(errors="replace")
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "mf_holdings[%s]: listing candidate %s → %s: %s",
                amc_id, page, type(e).__name__, e,
            )
            continue
        found = _discover_xlsx_link(html, page, as_of_month)
        if found:
            logger.info(
                "mf_holdings[%s]: listing-page discovery worked at %s",
                amc_id, page,
            )
            return found
    logger.info(
        "mf_holdings[%s]: no listing candidate yielded a match (%d tried)",
        amc_id, len(candidates),
    )
    return None


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
             WHERE m.amc_id = $1
            """,
            amc_id,
        )
    # Build two lookup maps:
    #  1. exact:  DB name (lower) → [scheme_code, ...]   (fast path)
    #  2. identity: DB name with plan suffix stripped → [scheme_code, ...]
    #
    # AMC Excel files emit ONE holding block per fund family (covering all
    # plan variants: Regular/Direct × Growth/IDCW). We expand each Excel
    # block to ALL plan-level scheme_codes sharing the same fund identity
    # (see _resolve_scheme_codes — precision-ordered, collision-free).
    index = _build_scheme_index(db_schemes)

    resolved: list[dict] = []
    unmapped: set[str] = set()
    for row in raw_rows:
        codes = _resolve_scheme_codes(row["scheme_code"] or "", index)
        if not codes:
            unmapped.add(row["scheme_code"])
            continue
        for code in codes:
            resolved.append({**row, "scheme_code": code})

    if unmapped:
        logger.warning(
            "mf_holdings[%s]: %d Excel scheme names unresolved to DB codes: %s",
            amc_id, len(unmapped), sorted(unmapped)[:5],
        )
    resolved_schemes = len({r["scheme_code"] for r in resolved})
    logger.info(
        "mf_holdings[%s]: %d raw rows → %d resolved rows across %d scheme_codes (from %s)",
        amc_id, len(raw_rows), len(resolved), resolved_schemes, used_url,
    )
    return resolved


async def icici_pru(http: aiohttp.ClientSession, m: date) -> list[dict]:
    """ICICI Pru — full monthly disclosure via AdvisorKhoj (uniform static
    index of the official files); falls back to the Playwright SPA path."""
    from .advisorkhoj import advisorkhoj_holdings_adapter
    rows = await advisorkhoj_holdings_adapter("icici_pru", http, m)
    if rows:
        return rows
    return await _playwright_holdings_adapter("icici_pru", http, m)


async def _playwright_holdings_adapter(
    amc_id: str,
    http: aiohttp.ClientSession,
    as_of_month: date,
) -> list[dict]:
    """Generic adapter that uses playwright_scraper to download the portfolio file
    and then parses it with the standard xlsx parser + scheme code resolver.
    Falls back to the HTTP-based _amfi_holdings_adapter if Playwright is unavailable.
    """
    from .sbi_parser import parse_portfolio_xlsx
    from .playwright_scraper import scrape_portfolio
    from nidp.shared.storage.pg import get_pool

    stealth = amc_id == "kotak"
    data, used_url = await scrape_portfolio(amc_id, as_of_month, headless=True, stealth=stealth)

    if data is None:
        logger.warning(
            "mf_holdings[%s]: playwright scrape returned no data — falling back to HTTP adapter",
            amc_id,
        )
        return await _amfi_holdings_adapter(amc_id, http, as_of_month)

    source_tag = f"{amc_id.upper()}_MF_PORTFOLIO_PLAYWRIGHT"

    # Handle ZIP files (some AMCs bundle multiple xlsx files)
    import io, zipfile
    raw_rows: list[dict] = []

    if used_url and (used_url.lower().endswith(".zip") or used_url.lower().endswith(".zip?")):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                xlsx_names = [n for n in zf.namelist() if n.lower().endswith((".xlsx", ".xls"))]
                for name in xlsx_names:
                    try:
                        rows = parse_portfolio_xlsx(zf.read(name), as_of_month,
                                                    source_url=used_url, source_tag=source_tag)
                        raw_rows.extend(rows or [])
                    except Exception as e:
                        logger.warning("mf_holdings[%s]: parse failed for %s: %s", amc_id, name, e)
        except zipfile.BadZipFile:
            raw_rows = parse_portfolio_xlsx(data, as_of_month, source_url=used_url,
                                             source_tag=source_tag) or []
    else:
        raw_rows = parse_portfolio_xlsx(data, as_of_month, source_url=used_url,
                                         source_tag=source_tag) or []

    if not raw_rows:
        return []

    # Resolve scheme codes (same logic as all other adapters)
    pool = await get_pool()
    async with pool.acquire() as conn:
        db_schemes = await conn.fetch(
            "SELECT scheme_code, scheme_name FROM nidp.mf_scheme_master WHERE amc_id = $1",
            amc_id,
        )
    import re as _re
    name_to_codes: dict[str, list[str]] = {}
    base_to_codes: dict[str, list[str]] = {}
    for r in db_schemes:
        nm = r["scheme_name"].lower().strip()
        name_to_codes.setdefault(nm, []).append(r["scheme_code"])
        base = _re.split(r"\s*[\(\-]\s*", nm, maxsplit=1)[0].strip().rstrip(" -")
        if len(base) >= 10:
            base_to_codes.setdefault(base, []).append(r["scheme_code"])

    def _resolve(raw_name: str) -> list[str]:
        nm = raw_name.lower().strip()
        if nm in name_to_codes:
            return name_to_codes[nm]
        base = _re.split(r"\s*[\(\-]\s*", nm, maxsplit=1)[0].strip().rstrip(" -")
        if base in base_to_codes:
            return base_to_codes[base]
        return [c for n, codes in base_to_codes.items()
                if len(n) >= 10 and (n in base or base in n) for c in codes][:1]

    resolved: list[dict] = []
    unmapped: set[str] = set()
    for row in raw_rows:
        codes = _resolve(row.get("scheme_code") or "")
        if not codes:
            unmapped.add(row.get("scheme_code", ""))
        else:
            for code in codes:
                resolved.append({**row, "scheme_code": code})

    if unmapped:
        logger.warning("mf_holdings[%s]: %d unresolved names: %s",
                       amc_id, len(unmapped), sorted(unmapped)[:5])
    logger.info("mf_holdings[%s]: %d raw → %d resolved rows (playwright, from %s)",
                amc_id, len(raw_rows), len(resolved), used_url)
    return resolved

async def _hdfc_multi_file_adapter(
    http: aiohttp.ClientSession,
    as_of_month: date,
) -> list[dict]:
    """HDFC publishes one xlsx file per fund (109+ files for April 2026).
    Extract all xlsx URLs from the JSON-embedded page, download concurrently
    with a semaphore, parse each, then resolve scheme codes.
    """
    from .sbi_parser import parse_portfolio_xlsx
    from nidp.shared.storage.pg import get_pool

    amc_id = "hdfc"
    listing_url = "https://www.hdfcfund.com/statutory-disclosure/portfolio/monthly-portfolio"

    # Fetch listing page and extract all April xlsx URLs from JSON
    html = None
    for page_url in _PORTFOLIO_PAGE_CANDIDATES["hdfc"]:
        try:
            async with http.get(page_url, allow_redirects=True) as resp:
                if resp.status == 200:
                    html = await resp.text(errors="replace")
                    listing_url = page_url
                    break
        except Exception:
            continue
    if html is None:
        logger.warning("mf_holdings[hdfc]: all listing pages failed")
        return []

    month_long  = as_of_month.strftime("%B").lower()   # "april"
    month_short = as_of_month.strftime("%b").lower()   # "apr"
    year_full   = as_of_month.strftime("%Y")           # "2026"

    # Extract JSON-embedded xlsx URLs matching the target month
    all_urls = re.findall(r'"url"\s*:\s*"(https?://[^"]+\.xlsx[^"]*)"', html, re.IGNORECASE)
    target_urls = [
        u for u in all_urls
        if (month_long in u.lower() or month_short in u.lower())
        and year_full in u.lower()
    ]
    if not target_urls:
        logger.warning("mf_holdings[hdfc]: no %s %s xlsx URLs in listing page", month_long, year_full)
        return []

    # Deduplicate (same URL may appear multiple times in JSON)
    target_urls = list(dict.fromkeys(target_urls))
    logger.info("mf_holdings[hdfc]: downloading %d fund xlsx files", len(target_urls))

    # Download with concurrency limit (HDFC CDN is stable but don't hammer it)
    sem = asyncio.Semaphore(8)
    source_tag = "HDFC_MF_PORTFOLIO_XLSX"
    all_raw_rows: list[dict] = []

    async def _fetch_one(url: str) -> None:
        async with sem:
            try:
                async with http.get(url, allow_redirects=True) as resp:
                    if resp.status != 200:
                        return
                    ct = resp.headers.get("content-type", "").lower()
                    if "html" in ct:
                        return
                    data = await resp.read()
                    if len(data) < 1024:
                        return
                rows = parse_portfolio_xlsx(data, as_of_month, source_url=url, source_tag=source_tag)
                if rows:
                    all_raw_rows.extend(rows)
            except Exception as e:
                logger.debug("mf_holdings[hdfc]: %s → %s: %s", url[-60:], type(e).__name__, e)

    await asyncio.gather(*[_fetch_one(u) for u in target_urls])
    logger.info("mf_holdings[hdfc]: parsed %d raw rows from %d files", len(all_raw_rows), len(target_urls))

    if not all_raw_rows:
        return []

    # Reuse generic scheme-code resolution
    pool = await get_pool()
    async with pool.acquire() as conn:
        db_schemes = await conn.fetch(
            "SELECT scheme_code, scheme_name FROM nidp.mf_scheme_master WHERE amc_id = $1",
            amc_id,
        )

    # Use the shared, precision-tiered resolver (the same one SBI and the other
    # AMCs use) instead of a weaker local base-split. The bespoke version did only
    # lower()/strip() + "split at first '(' or '-'" with a [:1] last-resort pick,
    # so merged/"&" funds whose Excel name carries an "(erstwhile …)" descriptor —
    # e.g. HDFC Balanced Advantage Fund (erstwhile HDFC Prudence Fund) — failed to
    # match the AMFI master and were dropped, or landed on a single arbitrary code
    # the copilot doesn't resolve to → empty holdings. _resolve_scheme_codes is
    # erstwhile-aware, normalises "&"→"and", and matches on fund identity across
    # all plan variants.
    index = _build_scheme_index(db_schemes)

    resolved: list[dict] = []
    unmapped: set[str] = set()
    for row in all_raw_rows:
        codes = _resolve_scheme_codes(row["scheme_code"] or "", index)
        if not codes:
            unmapped.add(row["scheme_code"])
        else:
            for code in codes:
                resolved.append({**row, "scheme_code": code})

    if unmapped:
        logger.warning("mf_holdings[hdfc]: %d unresolved fund names: %s", len(unmapped), sorted(unmapped)[:5])
    resolved_schemes = len({r["scheme_code"] for r in resolved})
    logger.info("mf_holdings[hdfc]: %d raw → %d resolved across %d scheme_codes", len(all_raw_rows), len(resolved), resolved_schemes)
    return resolved


async def hdfc(http: aiohttp.ClientSession, m: date) -> list[dict]:
    return await _hdfc_multi_file_adapter(http, m)

async def nippon(http: aiohttp.ClientSession, m: date) -> list[dict]:
    return await _amfi_holdings_adapter("nippon", http, m)

async def absl(http: aiohttp.ClientSession, m: date) -> list[dict]:
    """ABSL — full monthly disclosure via AdvisorKhoj (consolidated .xls);
    falls back to the Sitecore CMS API (Azure CDN, often unreachable).

    Sitecore notes: all listing page URLs are dead (404); the API needs no
    auth; ZIP CDN is abcscprod.azureedge.net. Discovered 2026-06 via HAR.
    """
    from .advisorkhoj import advisorkhoj_holdings_adapter
    _ak = await advisorkhoj_holdings_adapter("absl", http, m)
    if _ak:
        return _ak

    from .sbi_parser import parse_portfolio_xlsx
    from nidp.shared.storage.pg import get_pool
    import io, zipfile, json as _json

    amc_id = "absl"
    api_url = (
        "https://mutualfund.adityabirlacapital.com/postlogin/CustomApi/Resources/FactsheetAccordionById"
        "?id=3ccab227-9de5-4494-b78d-2b4f7c0c054a"
        "&ctype=/sitecore/content/Root/BSL/Library/Lists/FAQ/Customer%20Types/Individual"
        "&month=&year=0"
    )

    month_long  = m.strftime("%B").lower()   # "april"
    year_full   = m.strftime("%Y")           # "2026"

    zip_url: Optional[str] = None
    try:
        async with http.get(api_url, allow_redirects=True) as resp:
            if resp.status != 200:
                logger.warning("mf_holdings[absl]: CMS API → status=%d", resp.status)
            else:
                payload = await resp.json(content_type=None)
                accordion = payload.get("AccordionList") or []
                # Structure (confirmed 2026-06): each entry has ResourceLink (text),
                # pdfUrl (the ZIP download URL directly on the entry — no Files sub-array).
                def _entry_url(e: dict) -> Optional[str]:
                    # Primary: pdfUrl on the entry itself
                    u = e.get("pdfUrl") or e.get("PdfUrl")
                    if u:
                        return str(u).strip()
                    # Fallback: legacy Files[] sub-array shape
                    files = e.get("Files") or e.get("files") or []
                    if files:
                        return files[0].get("URL") or files[0].get("url")
                    return None

                for entry in accordion:
                    rl = entry.get("ResourceLink") or entry.get("Name") or entry.get("name") or ""
                    name = (rl if isinstance(rl, str) else rl.get("ResourceLink", "")).lower()
                    if month_long in name and year_full in name:
                        zip_url = _entry_url(entry)
                        break
                if not zip_url and accordion:
                    # Fallback: first (most recent) entry
                    zip_url = _entry_url(accordion[0])
                    if zip_url:
                        logger.info("mf_holdings[absl]: no exact month match; using latest entry")
                logger.info("mf_holdings[absl]: zip_url=%s", zip_url)
    except Exception as e:  # noqa: BLE001
        logger.warning("mf_holdings[absl]: CMS API call failed: %s", e)

    if not zip_url:
        logger.warning("mf_holdings[absl]: no ZIP URL from CMS API; skipping %s", m.isoformat())
        return []

    # Download ZIP — may fail from some GCP egress IPs (Azure CDN DNS)
    try:
        async with http.get(zip_url, allow_redirects=True) as resp:
            if resp.status != 200:
                logger.warning(
                    "mf_holdings[absl]: ZIP download %s → status=%d "
                    "(if DNS/CDN failure from GCP, check abcscprod.azureedge.net egress)",
                    zip_url, resp.status,
                )
                return []
            zip_bytes = await resp.read()
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "mf_holdings[absl]: ZIP download failed: %s "
            "(if DNS error, abcscprod.azureedge.net may be blocked from this GCP egress IP)",
            e,
        )
        return []

    if len(zip_bytes) < 1024:
        logger.warning("mf_holdings[absl]: ZIP too small (%d bytes)", len(zip_bytes))
        return []

    source_tag = "ABSL_MF_PORTFOLIO_ZIP"
    all_raw_rows: list[dict] = []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            xlsx_names = [n for n in zf.namelist() if n.lower().endswith((".xlsx", ".xls"))]
            logger.info("mf_holdings[absl]: ZIP contains %d xlsx file(s)", len(xlsx_names))
            for name in xlsx_names:
                try:
                    xlsx_bytes = zf.read(name)
                    rows = parse_portfolio_xlsx(xlsx_bytes, m, source_url=zip_url, source_tag=source_tag)
                    if rows:
                        all_raw_rows.extend(rows)
                except Exception as e:  # noqa: BLE001
                    logger.warning("mf_holdings[absl]: parse failed for %s: %s", name, e)
    except zipfile.BadZipFile as e:
        logger.warning("mf_holdings[absl]: bad ZIP from %s: %s", zip_url, e)
        return []

    if not all_raw_rows:
        return []

    pool = await get_pool()
    async with pool.acquire() as conn:
        db_schemes = await conn.fetch(
            "SELECT scheme_code, scheme_name FROM nidp.mf_scheme_master WHERE amc_id = $1",
            amc_id,
        )
    import re as _re
    name_to_codes: dict[str, list[str]] = {}
    base_to_codes: dict[str, list[str]] = {}
    for r in db_schemes:
        nm = r["scheme_name"].lower().strip()
        name_to_codes.setdefault(nm, []).append(r["scheme_code"])
        base = _re.split(r"\s*[\(\-]\s*", nm, maxsplit=1)[0].strip().rstrip(" -")
        if len(base) >= 10:
            base_to_codes.setdefault(base, []).append(r["scheme_code"])

    def _resolve_codes(raw_name: str) -> list[str]:
        nm = raw_name.lower().strip()
        if nm in name_to_codes:
            return name_to_codes[nm]
        base = _re.split(r"\s*[\(\-]\s*", nm, maxsplit=1)[0].strip().rstrip(" -")
        if base in base_to_codes:
            return base_to_codes[base]
        return [c for n, codes in base_to_codes.items()
                if len(n) >= 10 and (n in base or base in n) for c in codes][:1]

    resolved: list[dict] = []
    unmapped: set[str] = set()
    for row in all_raw_rows:
        codes = _resolve_codes(row.get("scheme_code") or "")
        if not codes:
            unmapped.add(row.get("scheme_code", ""))
        else:
            for code in codes:
                resolved.append({**row, "scheme_code": code})

    if unmapped:
        logger.warning("mf_holdings[absl]: %d unresolved: %s", len(unmapped), sorted(unmapped)[:5])
    logger.info("mf_holdings[absl]: %d raw → %d resolved rows (from %s)", len(all_raw_rows), len(resolved), zip_url)
    return resolved

async def uti(http: aiohttp.ClientSession, m: date) -> list[dict]:
    """UTI publishes a consolidated ZIP via an Angular SPA API.

    The listing pages (forms-and-downloads, factsheets, etc.) are all wrong —
    UTI uses a JSON API that returns a CloudFront ZIP URL.
    Discovered 2026-06 via HAR analysis.
    """
    from .sbi_parser import parse_portfolio_xlsx
    from nidp.shared.storage.pg import get_pool
    import io, zipfile

    amc_id = "uti"
    year_str  = m.strftime("%Y")
    month_str = m.strftime("%B")  # Title-case e.g. "April"

    api_url = (
        f"https://www.utimf.com/api/get-consolidate-portfolio-disclosure"
        f"?year={year_str}&month={month_str}"
    )
    zip_url: Optional[str] = None
    try:
        async with http.get(api_url, allow_redirects=True) as resp:
            if resp.status != 200:
                logger.warning("mf_holdings[uti]: API %s → status=%d", api_url, resp.status)
            else:
                data_json = await resp.json(content_type=None)
                rows = data_json.get("rows") or []
                if rows:
                    zip_url = rows[0].get("url")
                    logger.info("mf_holdings[uti]: API returned zip_url=%s", zip_url)
                else:
                    logger.warning("mf_holdings[uti]: API returned empty rows for %s %s", month_str, year_str)
    except Exception as e:  # noqa: BLE001
        logger.warning("mf_holdings[uti]: API call failed: %s", e)

    if not zip_url:
        logger.warning("mf_holdings[uti]: no ZIP URL from API; skipping %s", m.isoformat())
        return []

    # Download ZIP
    try:
        async with http.get(zip_url, allow_redirects=True) as resp:
            if resp.status != 200:
                logger.warning("mf_holdings[uti]: ZIP download %s → status=%d", zip_url, resp.status)
                return []
            zip_bytes = await resp.read()
    except Exception as e:  # noqa: BLE001
        logger.warning("mf_holdings[uti]: ZIP download failed: %s", e)
        return []

    if len(zip_bytes) < 1024:
        logger.warning("mf_holdings[uti]: ZIP too small (%d bytes)", len(zip_bytes))
        return []

    # Extract xlsx files from ZIP and parse each
    source_tag = "UTI_MF_PORTFOLIO_ZIP"
    all_raw_rows: list[dict] = []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            xlsx_names = [n for n in zf.namelist() if n.lower().endswith((".xlsx", ".xls"))]
            logger.info("mf_holdings[uti]: ZIP contains %d xlsx file(s)", len(xlsx_names))
            for name in xlsx_names:
                try:
                    xlsx_bytes = zf.read(name)
                    rows = parse_portfolio_xlsx(xlsx_bytes, m, source_url=zip_url, source_tag=source_tag)
                    if rows:
                        all_raw_rows.extend(rows)
                except Exception as e:  # noqa: BLE001
                    logger.warning("mf_holdings[uti]: parse failed for %s: %s", name, e)
    except zipfile.BadZipFile as e:
        logger.warning("mf_holdings[uti]: bad ZIP from %s: %s", zip_url, e)
        return []

    if not all_raw_rows:
        return []

    # Resolve scheme codes
    pool = await get_pool()
    async with pool.acquire() as conn:
        db_schemes = await conn.fetch(
            "SELECT scheme_code, scheme_name FROM nidp.mf_scheme_master WHERE amc_id = $1",
            amc_id,
        )
    import re as _re
    name_to_codes: dict[str, list[str]] = {}
    base_to_codes: dict[str, list[str]] = {}
    for r in db_schemes:
        nm = r["scheme_name"].lower().strip()
        name_to_codes.setdefault(nm, []).append(r["scheme_code"])
        base = _re.split(r"\s*[\(\-]\s*", nm, maxsplit=1)[0].strip().rstrip(" -")
        if len(base) >= 10:
            base_to_codes.setdefault(base, []).append(r["scheme_code"])

    def _resolve_codes(raw_name: str) -> list[str]:
        nm = raw_name.lower().strip()
        if nm in name_to_codes:
            return name_to_codes[nm]
        base = _re.split(r"\s*[\(\-]\s*", nm, maxsplit=1)[0].strip().rstrip(" -")
        if base in base_to_codes:
            return base_to_codes[base]
        return [c for n, codes in base_to_codes.items()
                if len(n) >= 10 and (n in base or base in n) for c in codes][:1]

    resolved: list[dict] = []
    unmapped: set[str] = set()
    for row in all_raw_rows:
        codes = _resolve_codes(row.get("scheme_code") or "")
        if not codes:
            unmapped.add(row.get("scheme_code", ""))
        else:
            for code in codes:
                resolved.append({**row, "scheme_code": code})

    if unmapped:
        logger.warning("mf_holdings[uti]: %d unresolved: %s", len(unmapped), sorted(unmapped)[:5])
    logger.info("mf_holdings[uti]: %d raw → %d resolved rows (from %s)", len(all_raw_rows), len(resolved), zip_url)
    return resolved

async def axis(http: aiohttp.ClientSession, m: date) -> list[dict]:
    """Axis — full monthly disclosure via AdvisorKhoj (consolidated xlsx);
    falls back to the Playwright SPA accordion."""
    from .advisorkhoj import advisorkhoj_holdings_adapter
    rows = await advisorkhoj_holdings_adapter("axis", http, m)
    if rows:
        return rows
    return await _playwright_holdings_adapter("axis", http, m)

async def kotak(http: aiohttp.ClientSession, m: date) -> list[dict]:
    """Kotak — full monthly disclosure via AdvisorKhoj (consolidated xlsx);
    falls back to the Playwright (hCaptcha) path."""
    from .advisorkhoj import advisorkhoj_holdings_adapter
    rows = await advisorkhoj_holdings_adapter("kotak", http, m)
    if rows:
        return rows
    return await _playwright_holdings_adapter("kotak", http, m)

async def tata(http: aiohttp.ClientSession, m: date) -> list[dict]:
    return await _amfi_holdings_adapter("tata", http, m)

async def mirae(http: aiohttp.ClientSession, m: date) -> list[dict]:
    return await _amfi_holdings_adapter("mirae", http, m)


# ── Tier-3 (AdvisorKhoj, resolved by scheme-name prefix) ─────────────────────
async def franklin(http: aiohttp.ClientSession, m: date) -> list[dict]:
    from .advisorkhoj import advisorkhoj_holdings_adapter
    return await advisorkhoj_holdings_adapter("franklin", http, m)

async def ppfas(http: aiohttp.ClientSession, m: date) -> list[dict]:
    from .advisorkhoj import advisorkhoj_holdings_adapter
    return await advisorkhoj_holdings_adapter("ppfas", http, m)


# ── quant MF ─────────────────────────────────────────────────────────────────
# ASP.NET WebMethod two-step API (discovered 2026-05-27 via Playwright XHR).
#
# Step 1: POST /statutorydisclosures.aspx/displaydisclouser1
#           body: {"id": "<year>", "cat": "MONTHLY PORTFOLIO - FUND - WISE"}
#           response: JSON {d: "<HTML with option tags>"} — month list
#
# Step 2: POST /statutorydisclosures.aspx/displaydisclouser2
#           body: {"id": "<month_id>", "cat": "MONTHLY PORTFOLIO - FUND - WISE",
#                  "tab": "<year>"}
#           response: JSON {d: "<HTML with <a href=...xlsx> per fund>"} — file links
#
# Weight column "% to nav" is already a percentage (no ×100 needed).
# Market-value column "market value(rs.in lakhs)" is in INR lakhs.

_QUANT_BASE = "https://www.quantmutual.com"
_QUANT_CAT  = "MONTHLY PORTFOLIO - FUND - WISE"
_QUANT_HDRS = {
    "Content-Type": "application/json; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{_QUANT_BASE}/statutory-disclosures",
}


async def _quant_get_month_id(http: aiohttp.ClientSession, year: str) -> Optional[str]:
    """Return the month_id for the latest available month for a given year."""
    url = f"{_QUANT_BASE}/statutorydisclosures.aspx/displaydisclouser1"
    import json as _json
    payload = _json.dumps({"id": year, "cat": _QUANT_CAT})
    try:
        async with http.post(url, data=payload, headers=_QUANT_HDRS) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
            html = data.get("d", "")
        soup = BeautifulSoup(html, "lxml")
        # API returns <li id="N" ...>MonthName</li> for each available month.
        # id is the month_id used in the next API call.
        # Find all li elements with a numeric id — pick the highest (most recent).
        li_els = [el for el in soup.find_all("li") if el.get("id", "").isdigit()]
        if li_els:
            return max(li_els, key=lambda el: int(el["id"]))["id"]
        # Legacy fallback: <option value="N">MonthName</option>
        options = soup.find_all("option")
        return options[0]["value"] if options else None
    except Exception as e:  # noqa: BLE001
        logger.warning("mf_holdings[quant]: month lookup failed: %s", e)
        return None


async def _quant_get_xlsx_links(
    http: aiohttp.ClientSession, month_id: str, year: str,
) -> list[tuple[str, str]]:
    """Return [(fund_name, absolute_xlsx_url), ...] for the given month."""
    import json as _json
    url = f"{_QUANT_BASE}/statutorydisclosures.aspx/displaydisclouser2"
    payload = _json.dumps({"id": month_id, "cat": _QUANT_CAT, "tab": year})
    try:
        async with http.post(url, data=payload, headers=_QUANT_HDRS) as resp:
            if resp.status != 200:
                logger.warning("mf_holdings[quant]: displaydisclouser2 status=%d", resp.status)
                return []
            data = await resp.json(content_type=None)
            html = data.get("d", "")
        soup = BeautifulSoup(html, "lxml")
        results = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href.lower().endswith((".xlsx", ".xls")):
                continue
            if not href.startswith("http"):
                href = _QUANT_BASE + ("" if href.startswith("/") else "/") + href
            fund_name = a.get_text(strip=True)
            results.append((fund_name, href))
        return results
    except Exception as e:  # noqa: BLE001
        logger.warning("mf_holdings[quant]: xlsx-link fetch failed: %s", e)
        return []


def _parse_quant_xlsx(data: bytes, fund_name: str, as_of_month: date, source_url: str) -> list[dict]:
    """Parse a quant per-fund xlsx into holding rows."""
    import io, openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    except Exception as e:  # noqa: BLE001
        logger.warning("mf_holdings[quant]: openpyxl failed for %s: %s", fund_name, e)
        return []

    # Find header row (contains 'isin' or 'name of the instrument')
    header_idx = None
    for i, row in enumerate(rows):
        cells = [str(c or "").lower().strip() for c in row]
        if any("isin" in c or "name of the instrument" in c for c in cells):
            header_idx = i
            break
    if header_idx is None:
        return []

    headers = [str(c or "").lower().strip() for c in rows[header_idx]]

    def _col(*frags: str) -> Optional[int]:
        for frag in frags:
            for i, h in enumerate(headers):
                if frag in h:
                    return i
        return None

    col_isin   = _col("isin")
    col_name   = _col("name of the instrument")
    col_rating = _col("rating")
    col_sector = _col("industry")
    col_qty    = _col("quantity")
    col_mv     = _col("market value")
    col_wt     = _col("% to nav", "% to net")

    if col_name is None:
        return []

    def _f(row: tuple, idx: Optional[int]) -> Optional[float]:
        if idx is None or idx >= len(row):
            return None
        v = row[idx]
        if v is None:
            return None
        try:
            return float(str(v).replace(",", "").strip())
        except (ValueError, TypeError):
            return None

    month_str = as_of_month.strftime("%Y-%m-01")
    result = []
    for row in rows[header_idx + 1:]:
        if not row or all(v is None for v in row):
            continue
        name = str(row[col_name] or "").strip() if col_name is not None else ""
        if not name or name.lower() in ("total", "grand total", "sub total"):
            continue
        isin_raw = str(row[col_isin] or "").strip() if col_isin is not None else ""
        isin = isin_raw if re.match(r"IN[A-Z0-9]{10}", isin_raw) else None
        wt = _f(row, col_wt)
        mv_lakh = _f(row, col_mv)
        result.append({
            "scheme_code":      fund_name,   # resolved later
            "as_of_month":      month_str,
            "security_isin":    isin,
            "security_name":    name,
            "instrument_type":  None,
            "sector":           str(row[col_sector] or "").strip() if col_sector is not None else None,
            "rating":           str(row[col_rating] or "").strip() if col_rating is not None else None,
            "quantity":         _f(row, col_qty),
            "market_value_inr": mv_lakh * 1e5 if mv_lakh is not None else None,
            "weight_pct":       wt,
            "source":           "QUANT_MF_PORTFOLIO_XLSX",
            "source_url":       source_url,
        })
    return result


async def quant(http: aiohttp.ClientSession, m: date) -> list[dict]:
    """quant MF portfolio adapter — ASP.NET WebMethod API."""
    from nidp.shared.storage.pg import get_pool

    year = str(m.year)
    month_id = await _quant_get_month_id(http, year)
    if not month_id:
        logger.warning("mf_holdings[quant]: no month_id for year=%s", year)
        return []

    links = await _quant_get_xlsx_links(http, month_id, year)
    if not links:
        logger.warning("mf_holdings[quant]: no xlsx links for month_id=%s", month_id)
        return []

    logger.info("mf_holdings[quant]: %d fund xlsx links found", len(links))

    pool = await get_pool()
    async with pool.acquire() as conn:
        db_schemes = await conn.fetch(
            "SELECT scheme_code, scheme_name FROM nidp.mf_scheme_master WHERE amc_id = 'quant'",
        )
        if not db_schemes:
            # nidp.mf_scheme_master.amc_id is unpopulated for a large slice of
            # the table (5,154 rows), and every quant scheme is in it — so the
            # amc_id lookup returns zero rows, base_to_codes comes out empty
            # and all 29 funds log "unresolved fund name" while 2,692 parsed
            # holding rows land with no scheme_code. The scheme name itself is
            # what actually identifies the AMC here, so fall back to it.
            db_schemes = await conn.fetch(
                "SELECT scheme_code, scheme_name FROM nidp.mf_scheme_master "
                "WHERE scheme_name ILIKE 'quant %'",
            )
            logger.warning(
                "mf_holdings[quant]: mf_scheme_master has no amc_id='quant' rows; "
                "fell back to scheme-name match (%d schemes)", len(db_schemes),
            )

    import re as _re
    base_to_codes: dict[str, list[str]] = {}
    for r in db_schemes:
        nm = r["scheme_name"].lower()
        base = _re.split(r"\s*[-–(]\s*", nm, maxsplit=1)[0].strip().rstrip(" -")
        if len(base) >= 8:
            base_to_codes.setdefault(base, []).append(r["scheme_code"])

    def _resolve(fund_name: str) -> list[str]:
        nm = fund_name.lower().strip()
        base = _re.split(r"\s*[-–(]\s*", nm, maxsplit=1)[0].strip().rstrip(" -")
        if base in base_to_codes:
            return base_to_codes[base]
        return [c for n, codes in base_to_codes.items()
                if len(n) >= 8 and (n in base or base in n)
                for c in codes][:1]

    all_rows: list[dict] = []
    for fund_name, xlsx_url in links:
        try:
            async with http.get(xlsx_url) as resp:
                if resp.status != 200:
                    logger.warning("mf_holdings[quant]: %s → status=%d", xlsx_url, resp.status)
                    continue
                data = await resp.read()
        except Exception as e:  # noqa: BLE001
            logger.warning("mf_holdings[quant]: download failed %s: %s", xlsx_url, e)
            continue

        raw = _parse_quant_xlsx(data, fund_name, m, xlsx_url)
        codes = _resolve(fund_name)
        if not codes:
            logger.warning("mf_holdings[quant]: unresolved fund name=%r", fund_name)
            # Still include rows with the raw fund name so holdings aren't lost
            all_rows.extend(raw)
        else:
            for code in codes:
                all_rows.extend({**r, "scheme_code": code} for r in raw)

    logger.info("mf_holdings[quant]: %d total holding rows from %d funds", len(all_rows), len(links))
    return all_rows


# ── JM Financial ─────────────────────────────────────────────────────────────
# Static CMS path: discovered 2026-05-27.
# Latest fortnightly files are listed on the AMC registry page; we discover
# them by scanning the CMS index for xlsx links matching the as_of_month.
# Headers: isin | name of instrument | rating/industry | quantity |
#          market value (in rs. lakh) | % to net assets

_JM_BASE       = "https://www.jmfinancialmf.com"
_JM_CMS_PREFIX = "/CMS/downloads/Portfolio%20Disclosure/Fortnightly%20Portfolio%20of%20Schemes/"
_JM_LISTING    = f"{_JM_BASE}/statutory-disclosure/portfolio-disclosure"


async def _jm_discover_xlsx_links(
    http: aiohttp.ClientSession, as_of_month: date,
) -> list[str]:
    """Scrape JM listing page for fortnightly xlsx links matching as_of_month."""
    month_patterns = [
        as_of_month.strftime("%B %Y").lower(),          # "april 2026"
        as_of_month.strftime("%b %Y").lower(),           # "apr 2026"
        as_of_month.strftime("%B,%Y").lower(),
    ]
    try:
        async with http.get(_JM_LISTING) as resp:
            if resp.status != 200:
                return []
            html = await resp.text(errors="replace")
    except Exception:
        return []

    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.lower().endswith((".xlsx", ".xls")):
            continue
        text = (a.get_text() + href).lower()
        if not any(p in text for p in month_patterns):
            continue
        if not href.startswith("http"):
            href = _JM_BASE + ("" if href.startswith("/") else "/") + href
        # Fix malformed URLs (missing slash between domain and CMS)
        href = re.sub(r"(jmfinancialmf\.com)([A-Z/])", r"\1/\2", href)
        links.append(href)
    return links


def _parse_jm_xlsx(data: bytes, as_of_month: date, source_url: str) -> list[dict]:
    """Parse a JM Financial fortnightly xlsx into holding rows."""
    import io, openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    except Exception as e:  # noqa: BLE001
        logger.warning("mf_holdings[jm_financial]: openpyxl failed %s: %s", source_url, e)
        return []

    header_idx = None
    for i, row in enumerate(rows):
        cells = [str(c or "").lower() for c in row]
        if any("isin" in c for c in cells):
            header_idx = i
            break
    if header_idx is None:
        return []

    headers = [str(c or "").lower().strip() for c in rows[header_idx]]

    def _col(*frags: str) -> Optional[int]:
        for frag in frags:
            for i, h in enumerate(headers):
                if frag in h:
                    return i
        return None

    col_isin   = _col("isin")
    col_name   = _col("name of instrument", "name")
    col_rating = _col("rating")
    col_qty    = _col("quantity")
    col_mv     = _col("market value")
    col_wt     = _col("% to net", "% to nav")

    if col_name is None:
        return []

    def _f(row: tuple, idx: Optional[int]) -> Optional[float]:
        if idx is None or idx >= len(row):
            return None
        v = row[idx]
        if v is None:
            return None
        try:
            return float(str(v).replace(",", "").strip())
        except (ValueError, TypeError):
            return None

    month_str = as_of_month.strftime("%Y-%m-01")
    result = []
    for row in rows[header_idx + 1:]:
        if not row or all(v is None for v in row):
            continue
        name = str(row[col_name] or "").strip() if col_name is not None else ""
        if not name or name.lower() in ("total", "grand total"):
            continue
        isin_raw = str(row[col_isin] or "").strip() if col_isin is not None else ""
        isin = isin_raw if re.match(r"IN[A-Z0-9]{10}", isin_raw) else None
        rating_sector = str(row[col_rating] or "").strip() if col_rating is not None else ""
        mv_lakh = _f(row, col_mv)
        result.append({
            "scheme_code":      "",            # resolved by caller
            "as_of_month":      month_str,
            "security_isin":    isin,
            "security_name":    name,
            "instrument_type":  None,
            "sector":           rating_sector or None,
            "rating":           rating_sector or None,
            "quantity":         _f(row, col_qty),
            "market_value_inr": mv_lakh * 1e5 if mv_lakh is not None else None,
            "weight_pct":       _f(row, col_wt),
            "source":           "JM_FINANCIAL_MF_PORTFOLIO_XLSX",
            "source_url":       source_url,
        })
    return result


async def jm_financial(http: aiohttp.ClientSession, m: date) -> list[dict]:
    """JM Financial MF portfolio adapter — static CMS fortnightly xlsx files."""
    from nidp.shared.storage.pg import get_pool

    links = await _jm_discover_xlsx_links(http, m)
    if not links:
        # Fallback: try known CMS path pattern for end-of-month
        month_name = m.strftime("%B")
        day = m.strftime("%d").lstrip("0")
        year = m.strftime("%Y")
        candidates = [
            f"{_JM_BASE}{_JM_CMS_PREFIX}Fortnightly%20Portfolio-%20JM%20Liquid%20Fund%20-%20{month_name}%20{day},%20{year}.xlsx",
        ]
        links = [u for u in candidates]
        logger.info("mf_holdings[jm_financial]: listing discovery found 0 links; trying %d fallbacks", len(links))

    pool = await get_pool()
    async with pool.acquire() as conn:
        db_schemes = await conn.fetch(
            "SELECT scheme_code, scheme_name FROM nidp.mf_scheme_master WHERE amc_id = 'jm_financial'",
        )

    import re as _re
    base_to_codes: dict[str, list[str]] = {}
    for r in db_schemes:
        nm = r["scheme_name"].lower()
        base = _re.split(r"\s*[-–(]\s*", nm, maxsplit=1)[0].strip().rstrip(" -")
        if len(base) >= 8:
            base_to_codes.setdefault(base, []).append(r["scheme_code"])

    def _resolve_from_url(xlsx_url: str) -> list[str]:
        """Extract fund name from URL path and resolve to scheme codes."""
        from urllib.parse import unquote
        fname = unquote(xlsx_url.split("/")[-1])
        # "Fortnightly Portfolio- JM Short Duration Fund - May 15, 2026.xlsx"
        m2 = re.search(r"JM\s+(.+?)\s*(?:-\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)|\d{4})", fname, re.IGNORECASE)
        if not m2:
            return []
        fund_part = ("jm " + m2.group(1)).lower().strip().rstrip(" -")
        base_key = _re.split(r"\s*[-–(]\s*", fund_part, maxsplit=1)[0].strip()
        if base_key in base_to_codes:
            return base_to_codes[base_key]
        return [c for n, codes in base_to_codes.items()
                if len(n) >= 8 and (n in fund_part or fund_part in n)
                for c in codes][:1]

    all_rows: list[dict] = []
    for xlsx_url in links:
        try:
            async with http.get(xlsx_url) as resp:
                if resp.status != 200:
                    logger.warning("mf_holdings[jm_financial]: %s → status=%d", xlsx_url, resp.status)
                    continue
                data = await resp.read()
        except Exception as e:  # noqa: BLE001
            logger.warning("mf_holdings[jm_financial]: download failed %s: %s", xlsx_url, e)
            continue

        raw = _parse_jm_xlsx(data, m, xlsx_url)
        codes = _resolve_from_url(xlsx_url)
        if not codes:
            logger.warning("mf_holdings[jm_financial]: unresolved fund from url=%s", xlsx_url)
            all_rows.extend(raw)
        else:
            for code in codes:
                all_rows.extend({**r, "scheme_code": code} for r in raw)

    logger.info("mf_holdings[jm_financial]: %d total holding rows", len(all_rows))
    return all_rows


ADAPTERS: dict[str, AdapterFn] = {
    "sbi":          sbi,
    "icici_pru":    icici_pru,
    "hdfc":         hdfc,
    "nippon":       nippon,
    "kotak":        kotak,
    "absl":         absl,
    "uti":          uti,
    "axis":         axis,
    "tata":         tata,
    "mirae":        mirae,
    # Tier 2
    "quant":        quant,
    "jm_financial": jm_financial,
    # Tier 3 (AdvisorKhoj, name-prefix resolution)
    "franklin":     franklin,
    "ppfas":        ppfas,
}


def get_adapter(amc_id: str) -> Optional[AdapterFn]:
    return ADAPTERS.get(amc_id)
