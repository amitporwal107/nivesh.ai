"""AdvisorKhoj-sourced monthly portfolio holdings (full security-level).

The SEBI-mandated monthly portfolio disclosure — every security, not the
factsheet's top-10 — is the right source for holdings, but each AMC
publishes it in a different (often JS-rendered) location, which is why
the direct adapters for several big AMCs are broken. AdvisorKhoj indexes
the SAME official files in STATIC HTML at a uniform URL per AMC, so we
scrape it to find the target month's disclosure file (whose link points
back to the official AMC source), download, and parse.

This is the holdings fallback for AMCs whose direct adapter is broken
(ICICI, Kotak, ABSL, UTI, Axis …). The disclosure is a zip of per-fund
xlsx in the standard SEBI format:

  Company/Issuer/Instrument | ISIN | Industry/Rating | Quantity |
  Exposure/Market Value (Rs Lakh) | % to Nav

We keep ISIN-keyed securities only — that drops section subtotals, cash,
TREPS and derivative rows (which carry a weight but no ISIN and would
otherwise double-count), and matches the downstream ISIN-keyed primitives
(migration 058). The scheme name is the xlsx filename; one fund's
holdings fan out to all its plan-variant scheme_codes (the convention the
concentration/active-share views read).
"""
from __future__ import annotations

import calendar
import io
import logging
import re
import zipfile
from datetime import date
from typing import Optional
from urllib.parse import urljoin

import aiohttp
import openpyxl

from .sbi_parser import _to_float  # reuse the tolerant numeric coercion

logger = logging.getLogger(__name__)

_AK_BASE = "https://www.advisorkhoj.com/form-download-centre/Mutual"

# amc_id → AdvisorKhoj slug. Covers the broken-adapter AMCs first; extend as
# each is verified.
AK_SLUG: dict[str, str] = {
    "icici_pru": "ICICI-Prudential-Mutual-Fund",
    "kotak":     "Kotak-Mahindra-Mutual-Fund",
    "absl":      "Aditya-Birla-Sun-Life-Mutual-Fund",
    "uti":       "UTI-Mutual-Fund",
    "axis":      "Axis-Mutual-Fund",
}

_ISIN_RE = re.compile(r"^IN[EF][A-Z0-9]{9}$")
_DISCLOSURE_EXT_RE = re.compile(r"\.(?:zip|xlsx|xls)(?:$|\?)", re.I)
# Header column synonyms (substring match against the disclosure header row).
_H_NAME = ("company", "issuer", "instrument", "name of")
_H_MV = ("exposure/market", "market value", "fair value", "market/fair")
_H_WT = ("% to nav", "% to net", "% of net", "% to aum")


def _month_patterns(as_of_month: date) -> list[str]:
    """Regexes that identify as_of_month in a disclosure-file URL. AMCs encode
    it inconsistently: by month name (.../2026/May/, as-on-May-2026) or by the
    month-END date in DD?MM?YYYY / DD?MM?YY form (31.05.2026, 31_05_26, 31052026,
    .../2026/3105...). We match the month-end date because disclosures are
    'as on' the last day of the month."""
    full = as_of_month.strftime("%B").lower()      # 'may'
    abbr = as_of_month.strftime("%b").lower()      # 'may' / 'apr'
    yr, mo = as_of_month.year, as_of_month.month
    last = calendar.monthrange(yr, mo)[1]          # 31 for May
    sep = r"[._\-/ ]?"                              # optional separator between parts
    # Use digit/alpha lookarounds (not \b): a date is often preceded by '_'
    # (a word char), where \b would NOT fire — e.g. 'portfolios_31.05.2026'.
    return [
        rf"/{yr}/{full}/", rf"/{yr}/{abbr}/",                                  # ICICI path
        rf"(?<![a-z]){full}{sep}(?:{last}{sep})?{yr}(?!\d)",                   # 'May-2026' / 'May-31-2026'
        rf"(?<![a-z]){abbr}{sep}(?:{last}{sep})?{yr}(?!\d)",
        rf"(?<![a-z]){last:02d}{sep}{full}{sep}{yr}(?!\d)",                    # '31-May-2026' (day first)
        rf"(?<!\d){last:02d}{sep}{mo:02d}{sep}{yr}(?!\d)",                     # 31.05.2026 / 31052026
        rf"(?<!\d){last:02d}{sep}{mo:02d}{sep}{yr % 100:02d}(?!\d)",           # 31_05_26 (2-digit yr)
        rf"/{yr}{sep}{mo:02d}(?!\d)",                                         # /2026/05, 2026-05
    ]


def _file_url_for_month(html: str, base_url: str, as_of_month: date) -> Optional[str]:
    """Pick the disclosure-file href referencing as_of_month from a page."""
    pats = _month_patterns(as_of_month)
    for href in re.findall(r'href=["\']([^"\']+)["\']', html, re.I):
        if not _DISCLOSURE_EXT_RE.search(href):
            continue
        low = href.lower()
        if any(re.search(p, low) for p in pats):
            return urljoin(base_url, href.replace(" ", "%20"))
    return None


async def _discover_disclosure_url(
    http: aiohttp.ClientSession, amc_id: str, as_of_month: date,
) -> Optional[str]:
    slug = AK_SLUG.get(amc_id)
    if not slug:
        return None
    page = f"{_AK_BASE}/{slug}/Monthly-Portfolio-Disclosures"
    try:
        async with http.get(page, allow_redirects=True) as resp:
            if resp.status != 200:
                logger.info("advisorkhoj[%s]: page %s → HTTP %d", amc_id, page, resp.status)
                return None
            html = await resp.text()
    except aiohttp.ClientError as e:
        logger.info("advisorkhoj[%s]: page fetch error: %s: %s", amc_id, type(e).__name__, e)
        return None
    url = _file_url_for_month(html, page, as_of_month)
    if not url:
        logger.info("advisorkhoj[%s]: no disclosure file for %s on the page",
                    amc_id, as_of_month.isoformat())
    return url


def _parse_workbook(data: bytes, scheme_name: str, as_of_str: str,
                    source_url: str, source_tag: str) -> list[dict]:
    """Parse one per-fund disclosure xlsx → ISIN-keyed holding rows.

    Reads the FIRST sheet (the portfolio; a 'Derivative' detail sheet, if
    present, is skipped to avoid double counting). Keeps only rows with a
    valid ISIN. weight_pct is normalised to 0–100.
    """
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:                                   # noqa: BLE001
        logger.debug("advisorkhoj: workbook open failed for %r: %s", scheme_name, e)
        return []
    ws = wb[wb.sheetnames[0]]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]

    # Locate the header row (has an instrument/company column AND an ISIN column).
    header_idx = None
    header: list[str] = []
    for i, r in enumerate(rows[:25]):
        low = [str(c or "").strip().lower() for c in r]
        if any(any(k in c for k in _H_NAME) for c in low) and any("isin" in c for c in low):
            header_idx, header = i, low
            break
    if header_idx is None:
        return []

    def col(*keys: str) -> Optional[int]:
        for j, c in enumerate(header):
            if any(k in c for k in keys):
                return j
        return None

    ci_name = col(*_H_NAME)
    ci_isin = col("isin")
    ci_ind = col("industry", "rating", "sector")
    ci_qty = col("quantity")
    ci_mv = col(*_H_MV)
    ci_wt = col(*_H_WT)
    if ci_name is None or ci_isin is None:
        return []

    def cell(r: list, idx: Optional[int]):
        return r[idx] if idx is not None and idx < len(r) else None

    out: list[dict] = []
    for r in rows[header_idx + 1:]:
        raw_isin = cell(r, ci_isin)
        isin = str(raw_isin).strip().replace("\t", "") if raw_isin else ""
        if not _ISIN_RE.match(isin):
            continue                                   # drops aggregates/cash/TREPS/derivatives
        name = str(cell(r, ci_name) or "").strip()
        if not name:
            continue
        mv_lakh = _to_float(cell(r, ci_mv))
        weight = _to_float(cell(r, ci_wt))
        sector = cell(r, ci_ind)
        out.append({
            "scheme_code": scheme_name,                # resolved to AMFI code by the adapter
            "as_of_month": as_of_str,
            "security_isin": isin,
            "security_name": name,
            "instrument_type": None,
            "sector": str(sector).strip() if sector else None,
            "rating": None,
            "quantity": _to_float(cell(r, ci_qty)),
            "market_value_inr": (mv_lakh * 100000.0) if mv_lakh is not None else None,  # ₹lakh → ₹
            "weight_pct": weight,
            "source": source_tag,
            "source_url": source_url,
        })

    # Normalise weight to percent (0–100): some AMCs report a fraction (sum≈1).
    weights = [h["weight_pct"] for h in out if h["weight_pct"] is not None]
    if weights and sum(weights) < 2.5:
        for h in out:
            if h["weight_pct"] is not None:
                h["weight_pct"] = round(h["weight_pct"] * 100, 4)
    return out


def parse_disclosure_zip(zip_bytes: bytes, as_of_month: date,
                         source_url: str, source_tag: str) -> list[dict]:
    """Parse a monthly-disclosure ZIP (one xlsx per fund) → holding rows.

    scheme_code is set to the fund NAME (the xlsx filename); the adapter
    resolves it to AMFI scheme_codes.
    """
    as_of_str = date(as_of_month.year, as_of_month.month, 1).isoformat()
    out: list[dict] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        logger.warning("advisorkhoj: not a valid zip (%s)", source_url)
        return out
    for name in zf.namelist():
        if not name.lower().endswith((".xlsx", ".xls")):
            continue
        scheme_name = name.rsplit("/", 1)[-1].rsplit(".", 1)[0].strip()
        try:
            out.extend(_parse_workbook(zf.read(name), scheme_name, as_of_str, source_url, source_tag))
        except Exception as e:                              # noqa: BLE001
            logger.debug("advisorkhoj: member %r parse skipped: %s", scheme_name, e)
    return out


async def advisorkhoj_holdings_adapter(
    amc_id: str, http: aiohttp.ClientSession, as_of_month: date,
) -> list[dict]:
    """Discover → download → parse → resolve the monthly disclosure for amc_id.

    Returns mf_holdings_monthly-shaped rows with scheme_code resolved to
    AMFI codes (one fund's holdings fan out to all its plan variants).
    Returns [] if no disclosure file is found or nothing parses.
    """
    from nidp.shared.storage.pg import get_pool
    from .amc_dispatch import _build_scheme_index, _resolve_scheme_codes

    url = await _discover_disclosure_url(http, amc_id, as_of_month)
    if not url:
        return []
    try:
        async with http.get(url, allow_redirects=True) as resp:
            if resp.status != 200:
                logger.info("advisorkhoj[%s]: file %s → HTTP %d", amc_id, url, resp.status)
                return []
            data = await resp.read()
    except aiohttp.ClientError as e:
        logger.info("advisorkhoj[%s]: download error: %s: %s", amc_id, type(e).__name__, e)
        return []

    source_tag = f"{amc_id.upper()}_DISCLOSURE_ADVISORKHOJ"
    parsed = parse_disclosure_zip(data, as_of_month, url, source_tag)
    if not parsed:
        logger.info("advisorkhoj[%s]: %s parsed 0 holdings", amc_id, url)
        return []

    # Resolve fund name → AMFI scheme_codes and fan out.
    pool = await get_pool()
    async with pool.acquire() as conn:
        db = await conn.fetch(
            "SELECT scheme_code, scheme_name FROM nidp.mf_scheme_master WHERE amc_id = $1",
            amc_id,
        )
    index = _build_scheme_index(
        [{"scheme_code": r["scheme_code"], "scheme_name": r["scheme_name"]} for r in db]
    )

    out: list[dict] = []
    code_cache: dict[str, list[str]] = {}
    funds_resolved: set[str] = set()
    for row in parsed:
        fund = row["scheme_code"]
        codes = code_cache.get(fund)
        if codes is None:
            codes = _resolve_scheme_codes(fund, index)
            code_cache[fund] = codes
        if not codes:
            continue
        funds_resolved.add(fund)
        for code in codes:
            out.append({**row, "scheme_code": str(code)})

    logger.info("advisorkhoj[%s]: %d funds → %d resolved → %d holding rows over %d scheme_codes",
                amc_id, len(code_cache), len(funds_resolved), len(out),
                len({r["scheme_code"] for r in out}))
    return out
