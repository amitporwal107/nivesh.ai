"""Factsheet PDF → per-fund Average AUM (AAUM, ₹ crore).

Each AMC's monthly factsheet states every fund's "Average AUM for the
Month" on that fund's summary page. We download the factsheet PDF,
extract the fund-level AAUM, resolve the fund name to its AMFI
plan-variant scheme_codes, and contribute aum_inr_crore rows to the
disclosure snapshot.

Granularity: the factsheet gives ONE fund-level AAUM per fund. We write
it to EVERY plan variant of that fund — matching the convention the
scorecard reads. Verified empirically: nidp.v_mf_category_scorecard
exposes the fund-level value per variant (e.g. UTI Low Duration shows
2847.76 on all 19 variants), so duplicating fund-level AAUM across
variants is the correct, non-double-counting representation.

This is the per-AMC factsheet source the service was scaffolded for
(see __init__: "TER, risk-o-meter, primary/secondary manager, AUM").
The central AMFI AAUM API is authoritative where it has data; this
factsheet pass fills the schemes it misses.

Design: one config per AMC (URL builder + AAUM regex + fund-name regex +
how to select its schemes from mf_scheme_master). Adding an AMC = adding
a config, not new code, as long as its factsheet states a per-scheme
AAUM in extractable text. AMCs whose factsheets put AUM only in graphical
tables, or that need archive-page link discovery, are not yet covered.
"""
from __future__ import annotations

import asyncio
import calendar
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional
from urllib.parse import quote

import aiohttp

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

# Browser-like UA — some AMC CDNs 403 a bare client. Filenames with spaces
# MUST be percent-encoded (the host 403s the raw path but serves the %20 GET).
_FS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*",
}

_MNAME = calendar.month_name        # _MNAME[4] == 'April'
_MABBR = calendar.month_abbr        # _MABBR[4] == 'Apr'

# Reject fund-name candidates that are really objective/category sentences.
_NAME_REJECT = re.compile(r"category|investing|scheme inv|objective|predominantly", re.I)


def _to_cr(s: str) -> Optional[float]:
    try:
        v = float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None
    return v if v > 0 else None


def _recent_data_months(anchor: date, n: int) -> list[tuple[int, int]]:
    """The n most-recent completed data months, newest first.

    SEBI factsheets publish for the *previous* calendar month, so from a
    run on 2026-06-25 the newest factsheet is May 2026. We try a few
    months back so a late-publishing AMC or a mid-month run still finds
    the latest available file.
    """
    y, m, out = anchor.year, anchor.month, []
    for _ in range(n):
        m -= 1
        if m == 0:
            m, y = 12, y - 1
        out.append((y, m))
    return out


def _next_month(y: int, m: int) -> tuple[int, int]:
    return (y + 1, 1) if m == 12 else (y, m + 1)


@dataclass(frozen=True)
class _AmcCfg:
    amc_id: str
    # (y, m) → candidate PDF URLs, highest-priority first.
    urls: Callable[[int, int], list[str]]
    # Captures the per-scheme AAUM (₹ crore) as group(1).
    aum_re: re.Pattern
    # Captures the fund-name heading; the LAST sane match before the AUM
    # block on a page is taken as the scheme name.
    name_re: re.Pattern
    # How to select this AMC's rows from nidp.mf_scheme_master:
    #   ("amc_id = $1", "<id>")            — top-10 AMCs (amc_id populated)
    #   ("scheme_name ILIKE $1", "DSP %")  — others (match by name prefix)
    master_filter: tuple[str, str]
    # Multiply the captured number to get ₹ crore (e.g. Tata reports Net
    # Assets in ₹ lakh → 0.01). Default 1.0 (value already in ₹ crore).
    scale: float = 1.0
    # Optional: captures the primary fund-manager name as group(1) from the
    # same scheme page. None → this AMC contributes no manager.
    manager_re: Optional[re.Pattern] = None


# ───────────────────────── URL builders ─────────────────────────
def _hdfc_urls(y: int, m: int) -> list[str]:
    # Folder = the month AFTER the data month (upload month).
    ny, nm = _next_month(y, m)
    fname = f"HDFC MF Factsheet - {_MNAME[m]} {y}.pdf"
    return [f"https://files.hdfcfund.com/s3fs-public/{ny}-{nm:02d}/{quote(fname)}"]


def _dsp_urls(y: int, m: int) -> list[str]:
    base = "https://www.dspim.com/downloads"
    return [f"{base}/dsp-factsheet-{_MNAME[m].lower()}-{y}.pdf"]


def _hsbc_urls(y: int, m: int) -> list[str]:
    # Flat media dir, data month; the factsheet is branded "The Asset".
    base = ("https://www.assetmanagement.hsbc.co.in/-/media/files/attachments/"
            "india/mutual-funds/factsheet")
    return [f"{base}/the-asset-{_MNAME[m].lower()}-{y}.pdf"]


def _tata_urls(y: int, m: int) -> list[str]:
    # Folder = the month AFTER the data month; filename wording varies.
    ny, nm = _next_month(y, m)
    folder = f"{ny}-{nm:02d}"
    names = [
        f"TataMF Factsheet - {_MNAME[m]} {y}.pdf",
        f"Tata MF Factsheet - {_MNAME[m]} {y}.pdf",
    ]
    return [f"https://www.tatamutualfund.com/system/files/{folder}/{quote(n)}" for n in names]


def _mirae_urls(y: int, m: int) -> list[str]:
    base = "https://www.miraeassetmf.co.in/docs/default-source/fachsheet"
    return [
        f"{base}/active-factsheet---{_MNAME[m].lower()}-{y}.pdf",
        f"{base}/active-factsheet---{_MABBR[m].lower()}-{y}.pdf",
    ]


# ───────────────────────── AAUM regexes ─────────────────────────
# HDFC fund page:
#   ASSETS UNDER MANAGEMENT €
#   As on <date>   Average for Month of <month>, <year>
#   ₹<month-end>Cr.   ₹<AAUM>Cr.
# Skip the first (month-end) value; capture the second (AAUM).
_HDFC_AUM_RE = re.compile(
    r"ASSETS UNDER MANAGEMENT.*?₹?\s*[\d,]+\.?\d*\s*Cr\.?\s*₹?\s*([\d,]+\.?\d*)\s*Cr\.?",
    re.S | re.I,
)
# DSP fund page:  "MONTHLY AVERAGE AUM\n7,222 Cr."  (preceded by TOTAL AUM)
_DSP_AUM_RE = re.compile(
    r"MONTHLY AVERAGE AUM\s*[`₹]?\s*([\d,]+\.?\d*)\s*Cr\.?",
    re.S | re.I,
)
# HSBC fund page:  "AAUM (for the month of May) ₹ 1773.84 Cr."
_HSBC_AUM_RE = re.compile(
    r"AAUM\s*\(for the month[^)]*\)\s*₹?\s*([\d,]+\.?\d*)\s*Cr\.?",
    re.S | re.I,
)
# Tata fund page: no AAUM text label — the holdings table's total row carries
# the fund's Net Assets in ₹ LAKH: "Net Assets 268169.70 100.00" (100.00 = the
# weight-% total). Captured value × 0.01 = ₹ crore. This is month-end net
# assets ≈ AUM (a close proxy for AAUM; only used to fill gaps).
_TATA_AUM_RE = re.compile(r"Net Assets\s+([\d,]+\.\d+)\s+100\.00")
# Mirae fund page:  "Monthly Average AUM (₹ Cr.)\n38,055.800"  (first value = AAUM)
_MIRAE_AUM_RE = re.compile(r"Monthly Average AUM\s*\(₹\s*Cr\.?\)\s*([\d,]+\.?\d*)", re.I)


FACTSHEET_SOURCES: dict[str, _AmcCfg] = {
    "hdfc": _AmcCfg(
        amc_id="hdfc",
        urls=_hdfc_urls,
        aum_re=_HDFC_AUM_RE,
        name_re=re.compile(r"^HDFC [A-Za-z0-9&',\.\- ]+?Fund\b", re.M),
        master_filter=("amc_id = $1", "hdfc"),
        # FUND MANAGER block: the name sits after the 'Total Exp' sub-header.
        manager_re=re.compile(
            r"FUND MANAGER.{0,80}?Total Exp(?:erience)?\s*\n\s*([A-Z][A-Za-z.\s]+?)\s*\n", re.S),
    ),
    "dsp": _AmcCfg(
        amc_id="dsp",
        urls=_dsp_urls,
        aum_re=_DSP_AUM_RE,
        name_re=re.compile(r"^DSP [A-Za-z0-9&',\.\- ]+?Fund\b", re.M),
        master_filter=("scheme_name ILIKE $1", "DSP %"),
    ),
    "hsbc": _AmcCfg(
        amc_id="hsbc",
        urls=_hsbc_urls,
        aum_re=_HSBC_AUM_RE,
        name_re=re.compile(r"^HSBC [A-Za-z0-9&',\.\- ]+?Fund\b", re.M),
        master_filter=("scheme_name ILIKE $1", "HSBC %"),
    ),
    "tata": _AmcCfg(
        amc_id="tata",
        urls=_tata_urls,
        aum_re=_TATA_AUM_RE,
        name_re=re.compile(r"^Tata [A-Za-z0-9&',\.\- ]+?Fund\b", re.M),
        master_filter=("amc_id = $1", "tata"),
        scale=0.01,                      # Net Assets are in ₹ lakh
    ),
    "mirae": _AmcCfg(
        amc_id="mirae",
        urls=_mirae_urls,
        aum_re=_MIRAE_AUM_RE,
        name_re=re.compile(r"^Mirae Asset [A-Za-z0-9&',\.\- ]+?Fund\b", re.M),
        master_filter=("amc_id = $1", "mirae"),
    ),
}


def _parse_page(text: str, cfg: _AmcCfg) -> Optional[dict]:
    """Parse ONE factsheet page's text → {scheme_name, aaum_cr} or None.

    Pure (no PDF/IO) so the extraction logic is unit-testable on captured
    page text. A fund page carries one AAUM value and a fund-name heading
    above it; pages without both yield None.
    """
    m = cfg.aum_re.search(text)
    if not m:
        return None
    aaum = _to_cr(m.group(1))
    if aaum is None:
        return None
    aaum = round(aaum * cfg.scale, 2)
    manager = None
    if cfg.manager_re is not None:
        mm = cfg.manager_re.search(text)
        if mm:
            cand = re.sub(r"\s+", " ", mm.group(1)).strip()
            # Plausible person name: 2–40 chars, not a stray header token.
            if 2 < len(cand) < 40 and not re.search(r"\d|fund|plan|name|since|total", cand, re.I):
                manager = cand
    head = text[: m.start()]
    for cand in reversed(cfg.name_re.findall(head)):
        c = re.sub(r"\s+", " ", cand).strip()
        if 8 < len(c) < 70 and not _NAME_REJECT.search(c):
            return {"scheme_name": c, "aaum_cr": aaum, "manager": manager}
    return None


def _parse_pdf(pdf_bytes: bytes, cfg: _AmcCfg) -> list[dict]:
    """Extract [{scheme_name, aaum_cr}] from a factsheet PDF (one per fund).

    Uses PyMuPDF (fitz): ~10× faster than pypdf on the 100–170 page factsheets
    (Tata: 3.8s vs 38.6s), which keeps the monthly run inside budget.
    """
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    out: list[dict] = []
    seen: set[str] = set()
    for i in range(doc.page_count):
        try:
            text = doc[i].get_text()
        except Exception:                                   # noqa: BLE001
            continue
        rec = _parse_page(text, cfg)
        if rec is None or rec["scheme_name"] in seen:
            continue
        seen.add(rec["scheme_name"])
        out.append(rec)
    return out


async def _download_pdf(http: aiohttp.ClientSession, url: str) -> Optional[bytes]:
    try:
        async with http.get(url, headers=_FS_HEADERS, allow_redirects=True) as resp:
            if resp.status != 200:
                logger.info("factsheet: %s → HTTP %d", url, resp.status)
                return None
            data = await resp.read()
    except aiohttp.ClientError as e:
        logger.info("factsheet: %s → %s: %s", url, type(e).__name__, e)
        return None
    if data[:4] != b"%PDF":                 # HTML error page served as 200
        logger.info("factsheet: %s → not a PDF (%r)", url, data[:8])
        return None
    return data


async def _resolve_funds_to_codes(cfg: _AmcCfg, funds: list[dict]) -> list[dict]:
    """Resolve parsed fund names to AMFI plan-variant scheme_codes.

    Reuses the mf_holdings name→codes resolver (exact → fund-identity →
    boundary-prefix → space-insensitive). One fund's AAUM fans out to all
    its plan variants.
    """
    from nidp.services.mf_holdings.amc_dispatch import (
        _build_scheme_index, _resolve_scheme_codes,
    )

    where, param = cfg.master_filter
    pool = await get_pool()
    async with pool.acquire() as conn:
        db_schemes = await conn.fetch(
            f"SELECT scheme_code, scheme_name FROM nidp.mf_scheme_master WHERE {where}",
            param,
        )
    index = _build_scheme_index(
        [{"scheme_code": r["scheme_code"], "scheme_name": r["scheme_name"]} for r in db_schemes]
    )

    rows: list[dict] = []
    matched = 0
    for f in funds:
        codes = _resolve_scheme_codes(f["scheme_name"], index)
        if not codes:
            logger.info("factsheet[%s]: unresolved fund name %r", cfg.amc_id, f["scheme_name"])
            continue
        matched += 1
        for code in codes:
            rows.append({"scheme_code": str(code), "aum_inr_crore": f["aaum_cr"],
                         "primary_manager": f.get("manager")})
    logger.info("factsheet[%s]: %d/%d funds resolved → %d scheme_codes",
                cfg.amc_id, matched, len(funds), len(rows))
    return rows


async def fetch_factsheet_aum(
    amc_id: str, http: aiohttp.ClientSession, snapshot_date: date,
) -> list[dict]:
    """Download the latest available factsheet for amc_id, parse fund-level
    AAUM, and return [{scheme_code, aum_inr_crore, source_url}].

    Returns [] for AMCs without a registered factsheet config, or when no
    recent month's PDF could be fetched/parsed.
    """
    cfg = FACTSHEET_SOURCES.get(amc_id)
    if cfg is None:
        return []

    for y, m in _recent_data_months(snapshot_date, n=3):
        for url in cfg.urls(y, m):
            pdf = await _download_pdf(http, url)
            if pdf is None:
                continue
            funds = await asyncio.to_thread(_parse_pdf, pdf, cfg)
            if not funds:
                logger.info("factsheet[%s]: %s parsed 0 funds", amc_id, url)
                continue
            logger.info("factsheet[%s]: %s → %d funds (data month %s-%02d)",
                        amc_id, url, len(funds), y, m)
            rows = await _resolve_funds_to_codes(cfg, funds)
            for r in rows:
                r["source_url"] = url
            return rows

    logger.warning("factsheet[%s]: no recent factsheet resolved", amc_id)
    return []
