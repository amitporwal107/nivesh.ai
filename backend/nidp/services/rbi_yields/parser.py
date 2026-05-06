"""RBI G-Sec / T-Bill yield page parser.

Three layouts are accepted (auto-detected per-table):

(1) Daily-rows: "Date | T-Bill 91D | T-Bill 364D | G-Sec 10Y | …"
    One row per date, one column per tenor.

(2) Weekly-columns (RBI WSS / Weekly Statistical Supplement layout):
    First column carries the tenor label, subsequent column headers
    are dates. Picks the most-recent column for each tenor.
        |  Item              | 26-Apr-2026 | 19-Apr-2026 | …
        |  91-Day T-Bill     | 6.45        | 6.42
        |  10-Year G-Sec     | 7.10        | 7.08

(3) ReferenceRateArchive.aspx — same daily-rows shape after POST
    rendering; same path as (1).

Detection: count cells in the first row vs first column that parse
as dates. Whichever side wins decides orientation.

Depends on lxml/beautifulsoup4. We extract the most-recent dated
value per tenor across all tables on the page.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _parse_date(s: str) -> Optional[str]:
    s = (s or "").strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


_TENOR_HINTS = [
    (re.compile(r"\b10[\s-]?(?:Y|YR|YEAR|YEARS?)\b", re.I), "10Y", "GSEC"),
    (re.compile(r"\b5[\s-]?(?:Y|YR|YEAR|YEARS?)\b", re.I), "5Y", "GSEC"),
    (re.compile(r"\b1[\s-]?(?:Y|YR|YEAR|YEARS?)\b", re.I), "1Y", "GSEC"),
    (re.compile(r"\b364[\s-]?(?:D|DAY|DAYS?)\b", re.I), "364D", "TBILL"),
    (re.compile(r"\b91[\s-]?(?:D|DAY|DAYS?)\b", re.I), "91D", "TBILL"),
    (re.compile(r"OVERNIGHT|CALL\s*MONEY|REPO", re.I), "OVERNIGHT", "POLICY_REPO"),
]


def _classify_header(header: str) -> Optional[tuple[str, str]]:
    for rx, tenor, instr in _TENOR_HINTS:
        if rx.search(header):
            return tenor, instr
    return None


def _to_float(s: str) -> Optional[float]:
    s = s.strip().replace(",", "").replace("%", "")
    if not s or s in ("-", "—", "N.A.", "NA"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _instr_for(tenor: str) -> Optional[str]:
    for _, t, instr in _TENOR_HINTS:
        if t == tenor:
            return instr
    return None


def _detect_orientation(head_cells: list[str], body_rows: list[list[str]]) -> str:
    """Returns 'daily-rows' (dates in first column) or 'weekly-cols'
    (dates in header row). Tie-breaker: daily-rows.

    Heuristic: count how many cells in the first column of body_rows
    parse as dates, and how many cells in the header row (skipping
    index 0) parse as dates. Pick whichever has more.
    """
    col0_dates = sum(
        1 for r in body_rows[:8] if r and _parse_date(r[0])
    )
    head_dates = sum(
        1 for h in head_cells[1:8] if _parse_date(h)
    )
    if head_dates > col0_dates:
        return "weekly-cols"
    return "daily-rows"


def _parse_daily_rows(
    head_cells: list[str], body_rows: list[list[str]],
) -> dict[str, tuple[str, float]]:
    """Layout: Date | T-Bill 91D | G-Sec 10Y | …"""
    col_map: dict[int, tuple[str, str]] = {}
    date_col: Optional[int] = None
    for i, h in enumerate(head_cells):
        if date_col is None and ("DATE" in h.upper() or _parse_date(h)):
            date_col = i
            continue
        cls = _classify_header(h)
        if cls:
            col_map[i] = cls
    if date_col is None or not col_map:
        return {}

    best: dict[str, tuple[str, float]] = {}
    for raw in body_rows:
        if date_col >= len(raw):
            continue
        d_iso = _parse_date(raw[date_col])
        if not d_iso:
            continue
        for col_i, (tenor, _instr) in col_map.items():
            if col_i >= len(raw):
                continue
            v = _to_float(raw[col_i])
            if v is None:
                continue
            cur = best.get(tenor)
            if cur is None or d_iso > cur[0]:
                best[tenor] = (d_iso, v)
    return best


def _parse_weekly_cols(
    head_cells: list[str], body_rows: list[list[str]],
) -> dict[str, tuple[str, float]]:
    """Layout: tenor labels in column 0; dates in header columns 1..N."""
    date_cols: list[tuple[int, str]] = [
        (i, d) for i, h in enumerate(head_cells)
        if i > 0 and (d := _parse_date(h))
    ]
    if not date_cols:
        return {}
    # Most recent date column wins for each tenor.
    date_cols.sort(key=lambda x: x[1], reverse=True)

    best: dict[str, tuple[str, float]] = {}
    for raw in body_rows:
        if not raw:
            continue
        cls = _classify_header(raw[0])
        if not cls:
            continue
        tenor, _instr = cls
        for col_i, d_iso in date_cols:
            if col_i >= len(raw):
                continue
            v = _to_float(raw[col_i])
            if v is None:
                continue
            cur = best.get(tenor)
            if cur is None or d_iso > cur[0]:
                best[tenor] = (d_iso, v)
            break    # first non-null cell is the most recent
    return best


def parse_rbi_yields(body: bytes) -> list[dict[str, Any]]:
    try:
        from bs4 import BeautifulSoup                              # type: ignore[import-not-found]
    except ImportError as e:                                       # pragma: no cover
        raise RuntimeError("rbi_yields parser requires beautifulsoup4") from e

    soup = BeautifulSoup(body, "lxml" if _has_lxml() else "html.parser")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for table in soup.find_all("table"):
        head_cells: list[str] = []
        body_rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if not cells:
                continue
            if not head_cells and any(cell for cell in cells):
                head_cells = cells
                continue
            body_rows.append(cells)

        if not head_cells or not body_rows:
            continue

        orientation = _detect_orientation(head_cells, body_rows)
        if orientation == "weekly-cols":
            best_by_tenor = _parse_weekly_cols(head_cells, body_rows)
        else:
            best_by_tenor = _parse_daily_rows(head_cells, body_rows)

        for tenor, (d_iso, val) in best_by_tenor.items():
            key = (d_iso, tenor)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "as_of_date": d_iso,
                "tenor":      tenor,
                "yield_pct":  val,
                "instrument": _instr_for(tenor),
            })
        if best_by_tenor:
            logger.debug(
                "rbi_yields parsed %d tenors via %s layout",
                len(best_by_tenor), orientation,
            )
    return rows


def _has_lxml() -> bool:
    try:
        import lxml  # noqa: F401
        return True
    except ImportError:                                            # pragma: no cover
        return False
