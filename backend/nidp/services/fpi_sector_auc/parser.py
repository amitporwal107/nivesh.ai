"""NSDL FPI Monitor — fortnightly sector-wise AUC / net-investment parser.

Report shape (verified against FIIInvestSector_Jul312026.html, 2026-08-18):

    row0   AUC as on Jul 15 |c24| Net Inv Jul 01-15 |c24| Net Inv Jul 16-31 |c24| AUC as on Jul 31 |c24
    row1   IN INR Cr. |c12| IN USD Mn |c12|   ... repeated per measure ...
    row3   Sr.No | Sectors | <12 asset-class columns> x 8
    row4+  1 | Automobile and Auto Components | 4,99,910 | 191 | ... (96 values)

So each file is a CALENDAR MONTH holding two fortnights, and we emit both: the
mid-month one (AUC@mid + net investment of the 1st half) and the month-end one
(AUC@end + net investment of the 2nd half). Adjacent files overlap by a fortnight,
which the writer's upsert collapses.

Numbers are Indian-grouped ('4,99,910'), negatives appear both bare ('-6,936') and
parenthesised ('(618.83)') depending on the report vintage, and blanks/'-'/'NA' mean
"not reported for this period" — NSDL phased Debt-FAR, Mutual Funds and AIF in only
from Aug/Sep 2024 (the report says so in its own footnote), so older files legitimately
carry fewer populated columns.
"""
from __future__ import annotations

import html as _html
import logging
import re
from datetime import date
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The 12 columns inside every measure/currency block, in report order.
ASSET_CLASSES: tuple[str, ...] = (
    "EQUITY",
    "DEBT_GENERAL",
    "DEBT_VRR",
    "DEBT_FAR",
    "HYBRID",
    "MF_EQUITY",
    "MF_DEBT_GENERAL",
    "MF_HYBRID",
    "MF_SOLUTION_ORIENTED",
    "MF_OTHER",
    "AIF",
    "TOTAL",
)
BLOCK = len(ASSET_CLASSES)

# NSDL labels sectors with BSE's Common Industry Classification; nidp.sector_master
# carries NSE's macro-sector labels. Only the genuinely different ones need an entry —
# 'Capital Goods', 'Chemicals', 'Construction', 'Consumer Durables', 'Consumer
# Services', 'Construction Materials', 'Diversified', 'Healthcare', 'Media', 'Power',
# 'Realty', 'Services', 'Telecommunication', 'Textiles' already match byte-for-byte.
SECTOR_ALIASES: dict[str, str] = {
    "automobile and auto components": "Automobile",
    "fast moving consumer goods": "FMCG",
    "financial services": "Finance",
    "information technology": "Information Technology",
    "oil, gas & consumable fuels": "Oil Gas",
    "oil gas & consumable fuels": "Oil Gas",
    "metals & mining": "Metals",
    "forest materials": "Textiles",
    "consumer discretionary": "Consumer Services",
}

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _text(fragment: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _rows(table_html: str) -> list[list[tuple[str, int]]]:
    """Return each <tr> as a list of (cell text, colspan)."""
    out: list[list[tuple[str, int]]] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.S | re.I):
        cells: list[tuple[str, int]] = []
        for attrs, body in re.findall(
                r"<t[dh]([^>]*)>(.*?)</t[dh]>", tr, re.S | re.I):
            m = re.search(r'colspan="?(\d+)', attrs, re.I)
            cells.append((_text(body), int(m.group(1)) if m else 1))
        out.append(cells)
    return out


def _num(raw: str) -> Optional[float]:
    """Indian-grouped number -> float. Blank / '-' / 'NA' -> None."""
    s = raw.replace(",", "").replace("\xa0", " ").strip()
    if s in ("", "-", "--", "NA", "N.A.", "N/A"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1].strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _period_end(label: str) -> Optional[date]:
    """'AUC as on July 15, 2026' / 'Net Investment July 16-31, 2026' -> date.

    Both forms end at a day number and a year; for a range we want the LAST day,
    which is the fortnight end the row is keyed on.
    """
    m = re.search(
        r"([A-Za-z]{3,9})\s*0?(\d{1,2})\s*(?:-\s*0?(\d{1,2}))?\s*,?\s*(\d{4})",
        label)
    if not m:
        return None
    mon = _MONTHS.get(m.group(1)[:3].lower())
    if not mon:
        return None
    day = int(m.group(3) or m.group(2))
    try:
        return date(int(m.group(4)), mon, day)
    except ValueError:
        return None


def _conversion_rates(tables: list[str]) -> dict[str, float]:
    """Label -> RBI reference rate, from the report's conversion-note table."""
    rates: dict[str, float] = {}
    for t in tables:
        for cells in _rows(t):
            if len(cells) == 2:
                rate = _num(cells[1][0])
                if rate and re.search(r"(AUC as on|Net Investment)", cells[0][0], re.I):
                    rates[cells[0][0].strip()] = rate
    return rates


def normalise_sector(sector: str) -> str:
    return SECTOR_ALIASES.get(sector.strip().lower(), sector.strip())


def parse_fortnight_index(body: bytes) -> list[tuple[date, str]]:
    """Parse FPI_Fortnightly_Selection.aspx -> [(fortnight end, absolute url)].

    The dropdown's option VALUES are used verbatim and never reconstructed: NSDL's
    filenames are inconsistent ('June302026' vs 'Jul312026') and one is outright
    misspelt ('FIIInvestSecor_Jan312012.html', missing the 't').
    """
    text = body.decode("utf-8", "replace")
    out: list[tuple[date, str]] = []
    for value, label in re.findall(
            r'<option[^>]*value="([^"]+)"[^>]*>([^<]+)</option>', text, re.I):
        d = _period_end(_html.unescape(label))
        if not d or ".html" not in value.lower():
            continue
        url = "https://www.fpi.nsdl.co.in/web/" + value.lstrip("~/").lstrip("/")
        out.append((d, url))
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def parse_sector_report(body: bytes, source_url: str = "") -> list[dict[str, Any]]:
    """Parse one fortnightly report into rows for nidp.fpi_sector_auc."""
    text = body.decode("utf-8", "replace")
    tables = re.findall(r"<table.*?</table>", text, re.S | re.I)
    if not tables:
        logger.warning("fpi_sector_auc: no <table> in body (%d bytes)", len(body))
        return []

    grid = next((t for t in tables
                 if re.search(r"Sr\.?\s*No", t, re.I)
                 and re.search(r"Sectors", t, re.I)), None)
    if grid is None:
        logger.warning("fpi_sector_auc: no sector grid found in %s", source_url)
        return []

    rows = _rows(grid)
    # Measure header: the row whose colspans describe the four measures.
    measures = next(
        ([c[0] for c in r if c[0]] for r in rows[:4]
         if sum(1 for c in r if re.search(r"AUC as on|Net Investment", c[0], re.I)) >= 3),
        None)
    if not measures or len(measures) < 4:
        logger.warning("fpi_sector_auc: unrecognised header in %s", source_url)
        return []

    # (auc label, net-investment label) for the first and second fortnight.
    periods = [(measures[0], measures[1]), (measures[3], measures[2])]
    rates = _conversion_rates(tables)

    out: list[dict[str, Any]] = []
    for cells in rows:
        if len(cells) < 2 + 8 * BLOCK:
            continue
        if not re.fullmatch(r"\d{1,3}", cells[0][0].strip()):
            continue                      # header / note / total row
        sector = cells[1][0].strip()
        if not sector:
            continue
        vals = [c[0] for c in cells[2:2 + 8 * BLOCK]]

        for idx, (auc_label, net_label) in enumerate(periods):
            report_date = _period_end(auc_label)
            if report_date is None:
                continue
            # Block layout: [AUC_mid INR][AUC_mid USD][Net1 INR][Net1 USD]
            #               [Net2 INR][Net2 USD][AUC_end INR][AUC_end USD]
            auc_blk = 0 if idx == 0 else 6
            net_blk = 2 if idx == 0 else 4
            for j, asset in enumerate(ASSET_CLASSES):
                row = {
                    "report_date": report_date,
                    "sector": sector,
                    "sector_norm": normalise_sector(sector),
                    "asset_class": asset,
                    "auc_inr_cr": _num(vals[auc_blk * BLOCK + j]),
                    "auc_usd_mn": _num(vals[(auc_blk + 1) * BLOCK + j]),
                    "net_inv_inr_cr": _num(vals[net_blk * BLOCK + j]),
                    "net_inv_usd_mn": _num(vals[(net_blk + 1) * BLOCK + j]),
                    "usd_inr_rate": rates.get(auc_label.strip()),
                    "source_url": source_url,
                }
                if any(row[k] is not None for k in
                       ("auc_inr_cr", "auc_usd_mn",
                        "net_inv_inr_cr", "net_inv_usd_mn")):
                    out.append(row)
    logger.info("fpi_sector_auc: parsed %d row(s) from %s", len(out), source_url)
    return out
