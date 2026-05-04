"""RBI G-Sec / T-Bill yield page parser.

Two variants are accepted:

(1) BS_NSDPDisplay.aspx ("Daily Reference Rate") — HTML table with
    columns "Date | T-Bill 91D | T-Bill 364D | G-Sec 10Y | …".

(2) ReferenceRateArchive.aspx — HTML <table>s after a POST. We
    accept the rendered table(s) here.

Both parsers are HTML-only and depend on lxml/beautifulsoup4. We
extract the most-recent dated row per tenor.

TODO(parser-completion): RBI page structure has historically shifted
on quarterly site refreshes. Add fixtures in
tests/fixtures/rbi_yields/ and pin parser to detected layout via a
header-fingerprint check.
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
    (re.compile(r"\b10[\s-]?(?:Y|YEAR|YR)\b", re.I), "10Y", "GSEC"),
    (re.compile(r"\b5[\s-]?(?:Y|YEAR|YR)\b", re.I), "5Y", "GSEC"),
    (re.compile(r"\b1[\s-]?(?:Y|YEAR|YR)\b", re.I), "1Y", "GSEC"),
    (re.compile(r"\b364[\s-]?D\b", re.I), "364D", "TBILL"),
    (re.compile(r"\b91[\s-]?D\b", re.I), "91D", "TBILL"),
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


def parse_rbi_yields(body: bytes) -> list[dict[str, Any]]:
    try:
        from bs4 import BeautifulSoup                              # type: ignore[import-not-found]
    except ImportError as e:                                       # pragma: no cover
        raise RuntimeError("rbi_yields parser requires beautifulsoup4") from e

    soup = BeautifulSoup(body, "lxml" if _has_lxml() else "html.parser")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for table in soup.find_all("table"):
        head_cells = []
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

        # Map each header column to a tenor (if it looks like one).
        col_map: dict[int, tuple[str, str]] = {}
        date_col: Optional[int] = None
        for i, h in enumerate(head_cells):
            if "DATE" in h.upper() and date_col is None:
                date_col = i
                continue
            cls = _classify_header(h)
            if cls:
                col_map[i] = cls

        if not col_map:
            continue

        # Pick the most recent dated row per tenor.
        best_by_tenor: dict[str, tuple[str, float]] = {}
        for raw in body_rows:
            d_iso = _parse_date(raw[date_col]) if date_col is not None and date_col < len(raw) else None
            if not d_iso:
                continue
            for col_i, (tenor, instr) in col_map.items():
                if col_i >= len(raw):
                    continue
                v = _to_float(raw[col_i])
                if v is None:
                    continue
                cur = best_by_tenor.get(tenor)
                if cur is None or d_iso > cur[0]:
                    best_by_tenor[tenor] = (d_iso, v)

        for tenor, (d_iso, val) in best_by_tenor.items():
            tenor_instr = next(((t, i) for _, t, i in _TENOR_HINTS if t == tenor), (tenor, None))
            key = (d_iso, tenor)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "as_of_date": d_iso,
                "tenor":      tenor,
                "yield_pct":  val,
                "instrument": tenor_instr[1],
            })
    return rows


def _has_lxml() -> bool:
    try:
        import lxml  # noqa: F401
        return True
    except ImportError:                                            # pragma: no cover
        return False
