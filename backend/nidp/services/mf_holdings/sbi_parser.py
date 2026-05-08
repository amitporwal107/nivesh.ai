"""SBI Mutual Fund monthly portfolio Excel parser.

SEBI Circular SEBI/HO/IMD/DF3/CIR/P/2020/197 mandates portfolio disclosures
in a structured format. SBI MF's Excel typically has one sheet per scheme
(or named sections within a single sheet) with columns:

  Name of Instrument | ISIN | Industry/Sector | Rating | Quantity |
  Market/Fair Value (Rs in Lakhs) | % to Net Assets

The scheme name appears as a merged-cell header above each block.
"""
from __future__ import annotations

import io
import logging
from datetime import date
from typing import Any, Optional

import openpyxl

logger = logging.getLogger(__name__)

SOURCE_TAG = "SBI_MF_PORTFOLIO_XLSX"   # default; callers may override

_COL_ALIASES: list[tuple[str, str]] = [
    ("name of instrument", "security_name"),
    ("instrument name",    "security_name"),
    ("security name",      "security_name"),
    ("isin",               "security_isin"),
    ("industry",           "sector"),
    ("sector",             "sector"),
    ("rating",             "rating"),
    ("quantity",           "quantity"),
    ("market value",       "market_value_inr"),
    ("fair value",         "market_value_inr"),
    ("% to net assets",    "weight_pct"),
    ("% net assets",       "weight_pct"),
    ("% of net",           "weight_pct"),
]

_ITYPE_KEYWORDS: list[tuple[str, str]] = [
    ("equity shares",              "EQUITY"),
    ("equity & equity",            "EQUITY"),
    ("listed equity",              "EQUITY"),
    ("government securities",      "DEBT"),
    ("government bond",            "DEBT"),
    ("treasury bill",              "DEBT"),
    ("t-bill",                     "DEBT"),
    ("commercial paper",           "DEBT"),
    ("certificate of deposit",     "DEBT"),
    ("non-convertible debenture",  "DEBT"),
    ("ncd",                        "DEBT"),
    ("bond",                       "DEBT"),
    ("debenture",                  "DEBT"),
    ("futures",                    "DERIVATIVE"),
    ("options",                    "DERIVATIVE"),
    ("reit",                       "REIT"),
    ("invit",                      "REIT"),
    ("cash & cash equivalent",     "CASH"),
    ("cblo",                       "CASH"),
    ("reverse repo",               "CASH"),
    ("net receivable",             "CASH"),
    ("mutual fund unit",           "OTHER"),
]


def _guess_itype(name: str, sector: Optional[str]) -> Optional[str]:
    haystack = ((name or "") + " " + (sector or "")).lower()
    for kw, itype in _ITYPE_KEYWORDS:
        if kw in haystack:
            return itype
    return None


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (ValueError, AttributeError):
        return None


def _col_idx(headers: list[str], *fragments: str) -> Optional[int]:
    for frag in fragments:
        for i, h in enumerate(headers):
            if frag in h:
                return i
    return None


def parse_portfolio_xlsx(
    data: bytes,
    as_of_month: date,
    source_url: str,
    source_tag: str = SOURCE_TAG,
) -> list[dict]:
    """Parse an AMC portfolio Excel → list of mf_holdings_monthly rows.

    scheme_code is set to the scheme *name* from the Excel header row.
    The calling adapter resolves name → AMFI code via DB lookup.
    """
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    as_of_str = date(as_of_month.year, as_of_month.month, 1).isoformat()
    result: list[dict] = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        sheet_rows = list(ws.iter_rows(values_only=True))
        result.extend(
            _parse_sheet(sheet_rows, as_of_str, source_url, sheet_name, source_tag)
        )
    return result


def _parse_sheet(
    rows: list[tuple],
    as_of_month: str,
    source_url: str,
    sheet_name: str,
    source_tag: str = SOURCE_TAG,
) -> list[dict]:
    result: list[dict] = []
    current_scheme: Optional[str] = None
    header_map: dict[int, str] = {}   # col_index → field_name
    in_sub_header = False             # section header row (e.g. "Equity and Equity related")

    for row in rows:
        str_cells = [str(c or "").strip() for c in row]
        non_empty  = [c for c in str_cells if c]
        if not non_empty:
            # blank separator — a new scheme block may follow; reset header
            if header_map:
                header_map = {}
                in_sub_header = False
            continue

        # ── Try to (re)build header map ──────────────────────────────
        if not header_map:
            candidate: dict[int, str] = {}
            for i, cell in enumerate(str_cells):
                cl = cell.lower()
                for alias, field in _COL_ALIASES:
                    if alias in cl:
                        if field not in candidate.values():  # first match wins
                            candidate[i] = field
                        break
            if "security_name" in candidate.values():
                header_map = candidate
                continue
            # Not a header row — could be scheme name
            if len(non_empty) == 1:
                name = non_empty[0]
                nl = name.lower()
                if any(kw in nl for kw in ("fund", "plan", "scheme", "folio", "growth",
                                            "direct", "regular", "idcw", "dividend")):
                    current_scheme = name
            continue

        # ── Sub-section label detection ──────────────────────────────
        # Lines like "Equity & Equity related Instruments" with no numeric data
        if len(non_empty) <= 3 and not any(
            c.replace(".", "").replace(",", "").replace("-", "").isdigit()
            for c in non_empty
        ):
            name_col_idx = next(
                (i for i, f in header_map.items() if f == "security_name"), None
            )
            if name_col_idx is None or not str_cells[name_col_idx]:
                continue  # skip annotation rows

        # ── Data row ─────────────────────────────────────────────────
        name_col = next((i for i, f in header_map.items() if f == "security_name"), None)
        if name_col is None or name_col >= len(str_cells) or not str_cells[name_col]:
            continue

        sec_name = str_cells[name_col]
        if sec_name.lower() in {"name of instrument", "instrument name", "security name"}:
            continue  # repeated header row

        def _get(field: str) -> Optional[str]:
            for ci, fn in header_map.items():
                if fn == field and ci < len(str_cells) and str_cells[ci]:
                    return str_cells[ci]
            return None

        isin    = _get("security_isin")
        sector  = _get("sector")
        rating  = _get("rating")
        qty     = _to_float(_get("quantity"))
        mkt_val = _to_float(_get("market_value_inr"))
        if mkt_val is not None:
            mkt_val *= 100_000          # Lakhs → INR
        weight  = _to_float(_get("weight_pct"))

        result.append({
            # scheme_code will be resolved by the adapter (name → AMFI code).
            "scheme_code":      current_scheme or sheet_name,
            "as_of_month":      as_of_month,
            "security_isin":    isin if (isin and isin not in {"-", "N.A.", "NA"}) else None,
            "security_name":    sec_name,
            "instrument_type":  _guess_itype(sec_name, sector),
            "sector":           sector,
            "rating":           rating,
            "quantity":         qty,
            "market_value_inr": mkt_val,
            "weight_pct":       weight,
            "source":           source_tag,
            "source_url":       source_url,
        })
    return result
