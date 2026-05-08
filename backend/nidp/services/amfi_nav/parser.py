"""AMFI NAVAll.txt parser.

File shape (pipe-delimited, with section headers):

    Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date

    Open Ended Schemes(Equity Scheme - Large Cap Fund)

    Aditya Birla Sun Life Mutual Fund
    119551;INF209K01YM2;INF209K01YN0;Aditya Birla Sun Life Frontline Equity Fund - Growth;520.4500;07-May-2026
    119552;INF209K01YO8;INF209K01YP5;Aditya Birla Sun Life Frontline Equity Fund - IDCW;100.1234;07-May-2026
    ...

    Open Ended Schemes(Equity Scheme - Mid Cap Fund)
    ...

Two header types:
  - "Open Ended Schemes(<category>)"  (parens) → category, scheme_type
  - free AMC name on its own line     (no `;`) → amc_name_raw

Strategy: a state machine that tracks (scheme_type, scheme_category,
amc_name_raw) as we walk lines. Data rows have 6 pipe-separated fields
and start with a numeric scheme_code.

Pure function — no I/O. Tested against checked-in golden files.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# "Open Ended Schemes(Equity Scheme - Large Cap Fund)"
# also seen: "Open Ended Schemes ( Equity Scheme - Large Cap Fund )"
_RE_TYPE_HEADER = re.compile(
    r"^\s*(Open Ended Schemes|Close Ended Schemes|Interval Fund Schemes)\s*\(\s*(.+?)\s*\)\s*$",
    re.IGNORECASE,
)


def _to_iso_date(s: str) -> Optional[str]:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _to_float(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    s = s.strip().replace(",", "")
    if not s or s.upper() in {"N.A.", "NA", "-", "N/A"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_nav_all(body: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse AMFI NAVAll.txt bytes.

    Returns (nav_rows, scheme_rows) where:
      nav_rows    -> dicts shaped for mf_nav_daily writer
      scheme_rows -> dicts shaped for mf_scheme_master writer

    Both are derived from the same source pass; nav_rows is one row per
    parseable data line, scheme_rows is one row per unique scheme_code
    (last-write wins on duplicates within the file — shouldn't happen).
    """
    text = body.decode("utf-8-sig", errors="replace")
    nav_rows: list[dict[str, Any]] = []
    scheme_seen: dict[str, dict[str, Any]] = {}

    scheme_type: Optional[str] = None
    scheme_category: Optional[str] = None
    amc_name_raw: Optional[str] = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # File header (first non-empty line):
        # "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date"
        if line.lower().startswith("scheme code"):
            continue

        m = _RE_TYPE_HEADER.match(line)
        if m:
            scheme_type = m.group(1).strip()
            scheme_category = m.group(2).strip()
            # AMC line follows next; reset until we see one.
            amc_name_raw = None
            continue

        # Data rows have ';'. Anything without ';' is a free-form header
        # — typically an AMC name like "Aditya Birla Sun Life Mutual Fund".
        if ";" not in line:
            amc_name_raw = line
            continue

        cols = [c.strip() for c in line.split(";")]
        # Expected 6 cols. Tolerate trailing-empty drift.
        if len(cols) < 5:
            continue
        scheme_code = cols[0]
        if not scheme_code or not scheme_code[0].isdigit():
            # Non-data row that happened to contain ';' — skip.
            continue
        isin_growth = cols[1] or None
        isin_idcw   = cols[2] or None
        scheme_name = cols[3] or None
        nav         = _to_float(cols[4])
        nav_date    = _to_iso_date(cols[5]) if len(cols) > 5 else None

        if scheme_name is None or nav is None or nav_date is None:
            # NAV file occasionally publishes "N.A." NAVs — skip cleanly.
            continue

        # NAV == 0 happens for defunct or un-declared IDCW plans
        # (~380 rows/day in production). They break every return /
        # XIRR calculation downstream, so we don't write them to
        # mf_nav_daily. We DO still register the scheme in
        # scheme_master so callers can see the scheme exists.
        if nav > 0:
            nav_rows.append({
                "scheme_code":    scheme_code,
                "nav_date":       nav_date,
                "nav":            nav,
                "repurchase_nav": None,
                "sale_nav":       None,
            })

        # Last write wins per scheme_code in this file. NAVAll lists
        # each scheme exactly once, but be defensive.
        scheme_seen[scheme_code] = {
            "scheme_code":     scheme_code,
            "scheme_name":     scheme_name,
            "amc_name_raw":    amc_name_raw,
            "isin_growth":     isin_growth if (isin_growth and isin_growth != "-") else None,
            "isin_idcw":       isin_idcw   if (isin_idcw   and isin_idcw   != "-") else None,
            "scheme_type":     scheme_type,
            "scheme_category": scheme_category,
        }

    return nav_rows, list(scheme_seen.values())
