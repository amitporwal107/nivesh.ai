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

import asyncio
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
            "SELECT scheme_code FROM nidp.mf_scheme_master WHERE amc_id = $1",
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
    """Nippon adapter: name-based TER matching (Nippon xlsx uses NSDL codes, not AMFI codes)."""
    from .ter_scraper import fetch_ter_t1
    from .amfi_central import fetch_risk_all
    import re as _re
    import io as _io

    AMC_ID = "nippon"

    # ── Discover and download TER xlsx ──────────────────────────────────
    from .ter_scraper import _load_registry, _to_float
    from .discovery import discover_latest_file
    import aiohttp as _aiohttp

    registry = await _load_registry()
    meta = registry.get(AMC_ID, {})
    discovery_url = meta.get("ter_discovery_url", "")
    regex_pattern = meta.get("regex_pattern") or r".*(TotalExpenseRatio|ter).*\.xlsx"

    ter_map: dict[str, tuple] = {}

    if discovery_url:
        file_url = await discover_latest_file(discovery_url, regex_pattern, http, label=f"{AMC_ID}_ter")
        if file_url:
            try:
                async with http.get(file_url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
                    resp.raise_for_status()
                    data = await resp.read()
                # Parse Nippon-format xlsx using name-based matching
                ter_map = await _parse_nippon_ter_xlsx(AMC_ID, data)
                logger.info("mf_disclosure_snapshot[nippon]: parsed %d TER rows from %s",
                            len(ter_map), file_url[-60:])
            except Exception as e:  # noqa: BLE001
                logger.warning("mf_disclosure_snapshot[nippon]: TER download/parse failed: %s", e)

    # ── Risk-o-meter from AMFI central ──────────────────────────────────
    try:
        risk_map = await fetch_risk_all(http)
    except Exception as e:  # noqa: BLE001
        logger.warning("mf_disclosure_snapshot[nippon]: risk fetch error: %s", e)
        risk_map = {}

    if not ter_map and not risk_map:
        logger.warning("mf_disclosure_snapshot[nippon]: no data from TER or risk sources")
        return []

    result = []
    all_codes = set(ter_map) | set(risk_map)
    for code in all_codes:
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
            "source_url":        discovery_url,
        })
    logger.info("mf_disclosure_snapshot[nippon]: produced %d rows", len(result))
    return result


async def _parse_nippon_ter_xlsx(amc_id: str, data: bytes) -> dict[str, tuple]:
    """Parse Nippon TER xlsx using scheme name → AMFI code resolution.

    Nippon publishes daily TER rows per scheme. The file has no AMFI numeric
    codes — only scheme names. We take the latest row per scheme name and
    match to mf_scheme_master via base-name lookup.
    """
    import io as _io, re as _re, openpyxl as _opx
    from .ter_scraper import _to_float

    try:
        wb = _opx.load_workbook(_io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:
        logger.warning("mf_disclosure_snapshot[nippon]: cannot open xlsx: %s", e)
        return {}

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        return {}

    row0 = [str(c or "").strip() for c in rows[0]]

    # Detect format:
    #   New (2026-27): single header row with full column names in row0, data from row1.
    #                  Col 0 = NSDL Code, Col 1 = Scheme Name, Col 7 = Regular Total TER,
    #                  Col 12 = Direct Total TER.
    #   Old (2022-23): two-row header (row0 = group labels, row1 = sub-labels), data from row2.
    #                  Row0 has "Name of Scheme" in col 0.

    is_new_format = any("Total TER" in h for h in row0)

    if is_new_format:
        # Single-row header; find columns by searching row0 for "Total TER"
        total_ter_cols = [i for i, h in enumerate(row0) if "Total TER" in h]
        reg_col = next((i for i in total_ter_cols if "Regular" in row0[i]), None)
        dir_col = next((i for i in total_ter_cols if "Direct" in row0[i]), None)
        if reg_col is None and len(total_ter_cols) >= 1:
            reg_col = total_ter_cols[0]
        if dir_col is None and len(total_ter_cols) >= 2:
            dir_col = total_ter_cols[1]
        name_col = next((i for i, h in enumerate(row0) if "Scheme Name" in h or "Scheme" == h), 1)
        data_start = 1
    else:
        # Two-row header
        row1 = [str(c or "").strip() for c in rows[1]]
        total_ter_in_row1 = [i for i, h in enumerate(row1) if "Total TER" in h]
        reg_col = total_ter_in_row1[0] if len(total_ter_in_row1) >= 1 else None
        dir_col = total_ter_in_row1[1] if len(total_ter_in_row1) >= 2 else None
        name_col = next((i for i, h in enumerate(row0) if "Scheme" in h or "Name" in h), 0)
        data_start = 2

    logger.debug("nippon ter: format=%s name_col=%s reg_col=%s dir_col=%s",
                 "new" if is_new_format else "old", name_col, reg_col, dir_col)

    # Take latest row per scheme name (file is sorted by scheme, then date)
    latest: dict[str, tuple] = {}
    current_name = None
    for row in rows[data_start:]:
        if not row or all(c is None for c in row):
            continue
        name = str(row[name_col] or "").strip()
        if name and name != current_name:
            current_name = name
        name = current_name or name
        if not name:
            continue
        ter_r = _to_float(row[reg_col]) if reg_col is not None and reg_col < len(row) else None
        ter_d = _to_float(row[dir_col]) if dir_col is not None and dir_col < len(row) else None
        if ter_r is not None or ter_d is not None:
            latest[name] = (ter_r, ter_d)

    if not latest:
        logger.warning("mf_disclosure_snapshot[nippon]: no TER data parsed from xlsx")
        return {}

    # Resolve scheme names → AMFI codes
    from nidp.shared.storage.pg import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        db_rows = await conn.fetch(
            "SELECT scheme_code, scheme_name FROM nidp.mf_scheme_master WHERE amc_id = $1",
            amc_id,
        )

    name_to_codes: dict[str, list[str]] = {}
    for r in db_rows:
        n = r["scheme_name"].lower().strip()
        name_to_codes.setdefault(n, []).append(r["scheme_code"])

    base_to_codes: dict[str, list[str]] = {}
    for n, codes in name_to_codes.items():
        base = _re.split(r"\s*[\(\-]\s*", n, maxsplit=1)[0].strip().rstrip(" -")
        base_to_codes.setdefault(base, []).extend(codes)

    def _resolve(name: str) -> list[str]:
        nm = name.lower().strip()
        if nm in name_to_codes:
            return name_to_codes[nm]
        base = _re.split(r"\s*[\(\-]\s*", nm, maxsplit=1)[0].strip().rstrip(" -")
        if base in base_to_codes:
            return base_to_codes[base]
        return [c for b, codes in base_to_codes.items()
                if len(b) >= 10 and (b in base or base in b)
                for c in codes][:1]

    result: dict[str, tuple] = {}
    for name, (ter_r, ter_d) in latest.items():
        for code in _resolve(name):
            result[code] = (ter_r, ter_d)

    return result

async def tata(http: aiohttp.ClientSession) -> list[dict]:
    return await _t1_adapter("tata", http)


async def _fetch_uti_ter(http: aiohttp.ClientSession) -> dict[str, tuple]:
    """Fetch TER for UTI from their statutory disclosure API.

    UTI's TER page is JS-rendered; they expose it via:
      https://www.utimf.com/api/statutory-disclosure/total-expense-ratio-ter-revised-format
    Returns name → (ter_regular_pct, ter_direct_pct).
    """
    import xlrd as _xlrd

    api_url = ("https://www.utimf.com/api/statutory-disclosure/"
               "total-expense-ratio-ter-revised-format?&page=")
    try:
        async with http.get(api_url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
            resp.raise_for_status()
            doc = await resp.json(content_type=None)
    except Exception as e:
        logger.warning("mf_disclosure_snapshot[uti]: TER API error: %s", e)
        return {}

    rows = doc.get("rows") or []
    if not rows:
        return {}
    # Take most recent file (rows are newest-first)
    file_url = rows[0].get("file_url", "")
    if not file_url:
        return {}

    try:
        async with http.get(file_url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
            resp.raise_for_status()
            data = await resp.read()
    except Exception as e:
        logger.warning("mf_disclosure_snapshot[uti]: TER download error: %s", e)
        return {}

    # Parse .xls: col2=name, col8=Regular TER, col13=Direct TER
    try:
        wb = _xlrd.open_workbook(file_contents=data)
        ws = wb.sheet_by_index(0)
        result: dict[str, tuple] = {}
        for i in range(1, ws.nrows):
            name = str(ws.cell_value(i, 2) or "").strip()
            if not name:
                continue
            ter_r = ws.cell_value(i, 8)
            ter_d = ws.cell_value(i, 13)
            try:
                ter_r = float(ter_r) if ter_r else None
            except (ValueError, TypeError):
                ter_r = None
            try:
                ter_d = float(ter_d) if ter_d else None
            except (ValueError, TypeError):
                ter_d = None
            result[name] = (ter_r, ter_d)
        logger.info("mf_disclosure_snapshot[uti]: parsed %d TER entries from %s",
                    len(result), file_url[-60:])
        return result
    except Exception as e:
        logger.warning("mf_disclosure_snapshot[uti]: TER xls parse error: %s", e)
        return {}


async def _fetch_uti_aum(http: aiohttp.ClientSession) -> dict[str, float]:
    """Fetch AAUM (scheme-wise) for UTI from their statutory disclosure API.

    Returns scheme_base_name → aum_inr_crore.
    """
    import xlrd as _xlrd
    from datetime import date as _date

    today = _date.today()
    api_url = (
        f"https://www.utimf.com/api/statutory-disclosure/"
        f"aum-disclosure-scheme-wisestate-wise-monthly-average"
        f"?month={today.month}&year={today.year}&page="
    )
    try:
        async with http.get(api_url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
            resp.raise_for_status()
            doc = await resp.json(content_type=None)
    except Exception as e:
        logger.warning("mf_disclosure_snapshot[uti]: AUM API error: %s", e)
        return {}

    rows = doc.get("rows") or []
    # Pick the 'Schemewise' file (not statewise)
    scheme_row = next(
        (r for r in rows if "schemewise" in r.get("title", "").lower()),
        None,
    )
    if not scheme_row:
        logger.warning("mf_disclosure_snapshot[uti]: no schemewise AUM file in API response")
        return {}

    file_url = scheme_row.get("file_url", "")
    try:
        async with http.get(file_url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
            resp.raise_for_status()
            data = await resp.read()
    except Exception as e:
        logger.warning("mf_disclosure_snapshot[uti]: AUM download error: %s", e)
        return {}

    # Parse .xls: col1=scheme name, col62=Grand Total AAUM (Rs. Crore)
    _SKIP = {"sub-total", "total", "grand total", "grand"}
    try:
        wb = _xlrd.open_workbook(file_contents=data)
        ws = wb.sheet_by_index(0)
        result: dict[str, float] = {}
        for i in range(10, ws.nrows):
            name = str(ws.cell_value(i, 1) or "").strip()
            if not name or name.startswith("("):
                continue
            if any(s in name.lower() for s in _SKIP):
                continue
            try:
                aum = float(ws.cell_value(i, 62) or 0)
            except (ValueError, TypeError):
                aum = 0.0
            if aum > 0:
                result[name] = aum
        logger.info("mf_disclosure_snapshot[uti]: parsed %d AUM entries", len(result))
        return result
    except Exception as e:
        logger.warning("mf_disclosure_snapshot[uti]: AUM xls parse error: %s", e)
        return {}


async def uti(http: aiohttp.ClientSession) -> list[dict]:
    """UTI adapter: TER from statutory disclosure API + AUM from schemewise file.

    UTI's forms-and-downloads page is a JS-rendered Angular SPA with no
    static xlsx links. Instead their API at /api/statutory-disclosure/…
    lists files that are downloadable directly from CloudFront.
    Name-based resolution maps UTI base-fund names → AMFI scheme_codes.
    """
    import re as _re
    from .amfi_central import fetch_risk_all

    AMC_ID = "uti"

    ter_name_map, aum_name_map = await asyncio.gather(
        _fetch_uti_ter(http),
        _fetch_uti_aum(http),
        return_exceptions=True,
    )
    if isinstance(ter_name_map, Exception):
        logger.warning("mf_disclosure_snapshot[uti]: TER fetch failed: %s", ter_name_map)
        ter_name_map = {}
    if isinstance(aum_name_map, Exception):
        logger.warning("mf_disclosure_snapshot[uti]: AUM fetch failed: %s", aum_name_map)
        aum_name_map = {}

    try:
        risk_map = await fetch_risk_all(http)
    except Exception as e:  # noqa: BLE001
        logger.warning("mf_disclosure_snapshot[uti]: risk fetch error: %s", e)
        risk_map = {}

    if not ter_name_map and not aum_name_map and not risk_map:
        logger.warning("mf_disclosure_snapshot[uti]: all data sources empty")
        return []

    # Load scheme master for name → code resolution
    from nidp.shared.storage.pg import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        db_rows = await conn.fetch(
            "SELECT scheme_code, scheme_name FROM nidp.mf_scheme_master WHERE amc_id = $1",
            AMC_ID,
        )

    name_to_codes: dict[str, list[str]] = {}
    base_to_codes: dict[str, list[str]] = {}
    for r in db_rows:
        nm = r["scheme_name"].lower().strip()
        name_to_codes.setdefault(nm, []).append(r["scheme_code"])
        base = _re.split(r"\s*[\(\-]\s*", nm, maxsplit=1)[0].strip().rstrip(" -.")
        if len(base) >= 8:
            base_to_codes.setdefault(base, []).append(r["scheme_code"])

    def _resolve(name: str) -> list[str]:
        nm = name.lower().strip().rstrip(" -.")
        if nm in name_to_codes:
            return name_to_codes[nm]
        # Strip common UTI prefixes: "UTI - " or "UTI- "
        nm2 = _re.sub(r"^uti\s*[-–]\s*", "", nm).strip()
        if nm2 in name_to_codes:
            return name_to_codes[nm2]
        base = _re.split(r"\s*[\(\-]\s*", nm2, maxsplit=1)[0].strip().rstrip(" -.")
        if base in base_to_codes:
            return base_to_codes[base]
        return [c for b, codes in base_to_codes.items()
                if len(b) >= 8 and (b in base or base in b)
                for c in codes][:4]

    # Build per-scheme-code maps
    code_ter: dict[str, tuple] = {}
    for name, vals in ter_name_map.items():
        for code in _resolve(name):
            code_ter.setdefault(code, vals)

    code_aum: dict[str, float] = {}
    for name, aum in aum_name_map.items():
        for code in _resolve(name):
            code_aum.setdefault(code, aum)

    all_codes = await _get_amc_schemes(AMC_ID)
    result = []
    for code in all_codes:
        ter_pct, ter_pct_direct = code_ter.get(code, (None, None))
        aum = code_aum.get(code)
        risk = risk_map.get(code)
        if ter_pct is None and ter_pct_direct is None and aum is None and risk is None:
            continue
        result.append({
            "scheme_code":       code,
            "ter_pct":           ter_pct,
            "ter_pct_direct":    ter_pct_direct,
            "risk_o_meter":      risk,
            "primary_manager":   None,
            "secondary_manager": None,
            "aum_inr_crore":     aum,
            "source_url":        "https://www.utimf.com/statutory-disclosures/",
        })

    logger.info("mf_disclosure_snapshot[uti]: produced %d rows (TER=%d, AUM=%d codes)",
                len(result), len(code_ter), len(code_aum))
    return result

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
