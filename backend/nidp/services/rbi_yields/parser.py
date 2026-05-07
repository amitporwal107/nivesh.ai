"""RBI G-Sec / T-Bill yield page parser.

Four layouts are accepted (auto-detected per-page):

(1) Daily-rows: "Date | T-Bill 91D | T-Bill 364D | G-Sec 10Y | …"
    One row per date, one column per tenor.

(2) Weekly-columns: first column carries the tenor label, subsequent
    column headers are full dates. Most-recent column wins per tenor.
        |  Item              | 26-Apr-2026 | 19-Apr-2026 | …
        |  91-Day T-Bill     | 6.45        | 6.42
        |  10-Year G-Sec     | 7.10        | 7.08

(3) ReferenceRateArchive.aspx — same shape as (1).

(4) NSDP / "National Summary Data" multi-row header (BS_NSDPDisplay.aspx
    ?param=4 — what RBI is currently serving as of 2026-05). The date
    is split across two rows: an upper row with year ("Item/Week Ended
    | 2025 | 2026"), a lower row with month-day ("Apr. 25 | Mar. 27 |
    Apr. 3 | Apr. 10 | Apr. 17 | Apr. 24"). Tenor rows follow with
    one numeric per date column. We pick the rightmost (most recent)
    numeric per tenor and emit the latest header date as as_of_date.

Detection runs (4) first because that's RBI's current default; falls
back to (1)/(2) per-table for older snapshots.

Depends on lxml/beautifulsoup4.
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


_MONTH_DAY_RE = re.compile(r"^([A-Z][a-z]{2})\.?\s+(\d{1,2})$")
_YEAR_RE = re.compile(r"^\d{4}$")


def _parse_nsdp_layout(soup) -> dict[str, tuple[str, float]]:
    """RBI BS_NSDPDisplay.aspx?param=4 layout — multi-row header where
    year sits on one row and 'Mon. dd' on the next.

    Strategy: find the rightmost (= most recent) full date by combining
    a 'Mon. dd' cell with the maximum year from the prior 1-3 rows.
    Then for each tenor row, take the rightmost numeric cell — that
    corresponds to the most-recent column.
    """
    all_trs = soup.find_all("tr")

    # Pass 1: find the latest as_of_date by scanning month-day rows.
    max_date: Optional[str] = None
    for i, tr in enumerate(all_trs):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"], recursive=False)]
        if not cells:
            continue
        md_matches = [_MONTH_DAY_RE.match(c.strip()) for c in cells]
        if not any(md_matches):
            continue
        # Pull years from up to 3 prior rows (closest year-only row wins).
        years: list[int] = []
        for back in range(1, 4):
            if i - back < 0:
                break
            prior = [c.get_text(" ", strip=True) for c in all_trs[i - back].find_all(["th", "td"], recursive=False)]
            yrs = [int(c) for c in prior if _YEAR_RE.match(c.strip())]
            if yrs:
                years = yrs
                break
        if not years:
            continue
        max_year = max(years)
        # Rightmost month-day combined with the latest year.
        for j in range(len(cells) - 1, -1, -1):
            m = md_matches[j]
            if not m:
                continue
            try:
                iso = datetime.strptime(
                    f"{m.group(2)} {m.group(1)} {max_year}", "%d %b %Y"
                ).date().isoformat()
            except ValueError:
                continue
            if max_date is None or iso > max_date:
                max_date = iso
            break

    if not max_date:
        return {}

    # Pass 2: tenor rows → rightmost numeric value.
    best: dict[str, tuple[str, float]] = {}
    for tr in all_trs:
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"], recursive=False)]
        if len(cells) < 2:
            continue
        cls = _classify_header(cells[0])
        if not cls:
            continue
        tenor, _ = cls
        for c in reversed(cells[1:]):
            v = _to_float(c)
            if v is None:
                continue
            cur = best.get(tenor)
            if cur is None or max_date > cur[0]:
                best[tenor] = (max_date, v)
            break
    return best


def parse_rbi_yields(body: bytes) -> list[dict[str, Any]]:
    try:
        from bs4 import BeautifulSoup                              # type: ignore[import-not-found]
    except ImportError as e:                                       # pragma: no cover
        raise RuntimeError("rbi_yields parser requires beautifulsoup4") from e

    soup = BeautifulSoup(body, "lxml" if _has_lxml() else "html.parser")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    # Layout (4) first — RBI's NSDP page (current default). If we get
    # tenors out of it, emit and return; otherwise fall through to the
    # per-table daily-rows / weekly-cols logic for older snapshots.
    nsdp_best = _parse_nsdp_layout(soup)
    for tenor, (d_iso, val) in nsdp_best.items():
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
    if rows:
        logger.debug("rbi_yields parsed %d tenors via NSDP layout", len(rows))
        return rows

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
