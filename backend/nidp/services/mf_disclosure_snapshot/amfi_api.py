"""AMFI JSON API adapter for TER data.

AMFI rebuilt their website as a Next.js SPA in 2026. The old xlsx-based
download pages no longer exist. The new site exposes internal Next.js
API routes that the React client calls to load per-AMC data tables.

Verified API routes (2026-05-27 — from JS bundle analysis of
/_next/static/chunks/app/ter-of-mf-schemes/page-*.js):

  GET /api/populate-ter-month?year={FY_RANGE}
      e.g. year=2025-2026
      → [{MonthYear: "April-2026", MonthNumber: "04-2026"}, ...]

  GET /api/populate-te-rdata-revised
      params: MF_ID=All, Month=04-2026, strCat=ALL, strType=ALL,
              page=1, pageSize=2000
      → {data: [{NSDLSchemeCode, Scheme_Name, R_TER, D_TER, TER_Date,
                 SchemeType_Desc, SchemeCat_Desc, MF_ID, Month}],
         meta: {page, pageSize, total, pageCount}}

Important: the API returns DAILY rows (one per calendar day per scheme).
Deduplicate by NSDLSchemeCode, taking the last date's values.

Scheme code resolution:
  AMFI numeric scheme codes (our DB primary key) are NOT present in the
  TER API response. We resolve them by:
    1. Downloading portal.amfiindia.com/spages/NAVAll.txt (AMFI NAV feed).
    2. Normalising NAV scheme names: strip " - Direct Plan - Growth" etc.
    3. Matching normalised NAV names against TER API Scheme_Name.
    4. Using "direct" / "regular" substring in the NAV name to pick R_TER or D_TER.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Optional

import aiohttp

from nidp.shared.config import AMFI_WWW

logger = logging.getLogger(__name__)

_BASE_API = f"{AMFI_WWW}/api"
_NAV_URL  = "https://portal.amfiindia.com/spages/NAVAll.txt"

# Module-level cache — cleared by clear_cache()
_TER_CACHE:  dict[str, tuple[Optional[float], Optional[float]]] | None = None

# Plan-type keywords that appear in NAV scheme names after the base name
_PLAN_KEYWORDS = {
    "direct", "regular", "growth", "idcw", "dividend",
    "monthly", "quarterly", "weekly", "daily", "annual",
    "bonus", "retail", "institutional", "payout",
    "reinvestment", "appreciation", "option", "plan",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_float(v: object) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (ValueError, AttributeError):
        return None


def _normalize_scheme_name(name: str) -> str:
    """Strip plan/option suffixes from an AMFI scheme name.

    "Aditya Birla Sun Life Banking & PSU Debt Fund  - DIRECT - IDCW"
    → "aditya birla sun life banking & psu debt fund"

    The TER API already returns base names without suffixes.  NAV names
    have " - <plan> - <option>" appended; we strip everything from the
    first dash-separated segment that is a pure plan keyword.
    """
    parts = re.split(r"\s*[-–]\s*", name)
    base: list[str] = []
    for part in parts:
        words = re.findall(r"[a-z]+", part.lower())
        if words and all(w in _PLAN_KEYWORDS for w in words):
            break
        if part.strip().lower() in _PLAN_KEYWORDS:
            break
        base.append(part.strip())
    return re.sub(r"\s+", " ", " ".join(base)).lower().strip()


# ---------------------------------------------------------------------------
# NAV feed → AMFI code index
# ---------------------------------------------------------------------------

async def _build_nav_index(
    http: aiohttp.ClientSession,
) -> dict[str, dict[str, list[str]]]:
    """Download NAV feed and return {norm_name: {direct: [codes], regular: [codes]}}.

    NAV format (semicolon-separated):
      Scheme Code;ISIN Growth;ISIN IDCW;Scheme Name;NAV;Date
    Section headers and blank lines are skipped (they don't start with digits).
    """
    try:
        async with http.get(_NAV_URL, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                logger.warning("amfi_api: NAV feed status=%d", resp.status)
                return {}
            text = await resp.text(errors="replace")
    except Exception as e:  # noqa: BLE001
        logger.warning("amfi_api: NAV feed fetch error: %s: %s", type(e).__name__, e)
        return {}

    index: dict[str, dict[str, list[str]]] = {}
    for line in text.splitlines():
        parts = line.split(";")
        if len(parts) < 4 or not parts[0].strip().isdigit():
            continue
        code = parts[0].strip()
        raw_name = parts[3].strip()
        norm = _normalize_scheme_name(raw_name)
        if not norm:
            continue
        is_direct = "direct" in raw_name.lower()
        entry = index.setdefault(norm, {"direct": [], "regular": []})
        if is_direct:
            entry["direct"].append(code)
        else:
            entry["regular"].append(code)

    logger.info("amfi_api: NAV index built — %d unique base names, %d total codes",
                len(index), sum(len(v["direct"]) + len(v["regular"]) for v in index.values()))
    return index


# ---------------------------------------------------------------------------
# TER API
# ---------------------------------------------------------------------------

async def _fetch_latest_month(http: aiohttp.ClientSession) -> Optional[str]:
    """Return the latest available TER month as 'MM-YYYY' (e.g. '04-2026')."""
    today = date.today()
    # Fiscal year label: Apr 2025–Mar 2026 → "2025-2026"
    fy_start = today.year if today.month >= 4 else today.year - 1
    for fy in [f"{fy_start}-{fy_start+1}", f"{fy_start-1}-{fy_start}"]:
        try:
            url = f"{_BASE_API}/populate-ter-month?year={fy}"
            async with http.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    continue
                months = await resp.json(content_type=None)
                if months and isinstance(months, list):
                    # API returns newest-first; first entry is the latest month
                    return months[0].get("MonthNumber")
        except Exception as e:  # noqa: BLE001
            logger.debug("amfi_api: populate-ter-month fy=%s error: %s", fy, e)
    return None


async def _fetch_all_ter_rows(
    http: aiohttp.ClientSession,
    month: str,
    page_size: int = 2000,
) -> list[dict]:
    """Fetch all TER daily rows for a given month via pagination."""
    all_rows: list[dict] = []
    page = 1
    while True:
        params = {
            "MF_ID": "All",
            "Month": month,
            "strCat": "ALL",
            "strType": "ALL",
            "page": str(page),
            "pageSize": str(page_size),
        }
        try:
            async with http.get(
                f"{_BASE_API}/populate-te-rdata-revised",
                params=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    logger.warning("amfi_api: TER page=%d → status=%d", page, resp.status)
                    break
                payload = await resp.json(content_type=None)
        except Exception as e:  # noqa: BLE001
            logger.warning("amfi_api: TER page=%d error: %s", page, e)
            break

        rows: list[dict] = payload.get("data", []) if isinstance(payload, dict) else []
        all_rows.extend(rows)

        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        page_count = meta.get("pageCount", 1)
        logger.debug("amfi_api: TER page %d/%d fetched (%d rows)", page, page_count, len(rows))

        if page >= page_count or not rows:
            break
        page += 1

    return all_rows


def _deduplicate_ter_rows(rows: list[dict]) -> dict[str, dict]:
    """Keep the last-date row for each NSDLSchemeCode (TER can vary intra-month)."""
    latest: dict[str, dict] = {}
    for row in rows:
        code = row.get("NSDLSchemeCode", "")
        if not code:
            continue
        existing = latest.get(code)
        if existing is None or row.get("TER_Date", "") >= existing.get("TER_Date", ""):
            latest[code] = row
    return latest


def _resolve_amfi_codes(
    ter_by_nsdl: dict[str, dict],
    nav_index: dict[str, dict[str, list[str]]],
) -> dict[str, tuple[Optional[float], Optional[float]]]:
    """Join TER rows with NAV index; return {amfi_scheme_code: (R_TER, D_TER)}."""
    result: dict[str, tuple[Optional[float], Optional[float]]] = {}
    matched_schemes = 0
    unmatched: list[str] = []

    for nsdl_code, row in ter_by_nsdl.items():
        scheme_name = row.get("Scheme_Name", "")
        norm = _normalize_scheme_name(scheme_name)
        r_ter = _to_float(row.get("R_TER"))
        d_ter = _to_float(row.get("D_TER"))

        nav_entry = nav_index.get(norm)
        if nav_entry is None:
            unmatched.append(scheme_name)
            continue

        matched_schemes += 1
        # Each AMFI direct-plan code → D_TER; regular/other → R_TER
        for amfi_code in nav_entry["direct"]:
            result[amfi_code] = (r_ter, d_ter)
        for amfi_code in nav_entry["regular"]:
            result[amfi_code] = (r_ter, d_ter)

    if unmatched:
        logger.info(
            "amfi_api: %d/%d TER schemes unmatched in NAV feed (sample: %s)",
            len(unmatched), len(ter_by_nsdl), unmatched[:5],
        )
    logger.info(
        "amfi_api: resolved %d/%d TER schemes → %d AMFI codes",
        matched_schemes, len(ter_by_nsdl), len(result),
    )
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_ter_all_amfi_api(
    http: aiohttp.ClientSession,
) -> dict[str, tuple[Optional[float], Optional[float]]]:
    """Fetch TER for ALL AMFI schemes via the AMFI JSON API.

    Returns {scheme_code: (ter_regular_pct, ter_direct_pct)}.
    Module-level cached after first call.

    Strategy:
      1. Get latest available month from /api/populate-ter-month.
      2. Fetch all paginated rows from /api/populate-te-rdata-revised (MF_ID=All).
      3. Deduplicate: keep last-date row per NSDLSchemeCode.
      4. Download AMFI NAV feed to build normalised-name → AMFI-codes index.
      5. Match TER Scheme_Name to NAV index; emit one result per AMFI code.
    """
    global _TER_CACHE
    if _TER_CACHE is not None:
        return _TER_CACHE

    month = await _fetch_latest_month(http)
    if not month:
        logger.error("amfi_api: could not determine latest TER month")
        return {}
    logger.info("amfi_api: fetching TER for month=%s", month)

    all_rows = await _fetch_all_ter_rows(http, month)
    logger.info("amfi_api: fetched %d daily TER rows", len(all_rows))

    if not all_rows:
        logger.error("amfi_api: zero TER rows returned for month=%s", month)
        return {}

    ter_by_nsdl = _deduplicate_ter_rows(all_rows)
    logger.info("amfi_api: %d unique NSDL scheme codes after dedup", len(ter_by_nsdl))

    nav_index = await _build_nav_index(http)
    if not nav_index:
        logger.error("amfi_api: NAV index empty — cannot resolve AMFI codes")
        return {}

    result = _resolve_amfi_codes(ter_by_nsdl, nav_index)
    _TER_CACHE = result
    logger.info("amfi_api: TER cache populated — %d AMFI scheme codes", len(result))
    return result


async def fetch_risk_all_amfi_api(http: aiohttp.ClientSession) -> dict[str, str]:
    """Risk-o-meter via AMFI API — not yet implemented (endpoint TBD)."""
    logger.warning("amfi_api: risk-o-meter JSON API not yet discovered")
    return {}


def clear_cache() -> None:
    global _TER_CACHE
    _TER_CACHE = None
