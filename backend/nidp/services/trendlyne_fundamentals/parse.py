"""Pure parsing and dating for the Trendlyne loader. No I/O."""
from __future__ import annotations

import calendar
import json
from datetime import date
from typing import Dict, List, Optional, Tuple

# Quarter offset -> parameter token, per series. Trendlyne's naming is irregular:
# "4 quarters ago" is `...qmy1`, and there is no `...qmq4`.
OFFSET_SUFFIX = {0: "q", 1: "qmq1", 2: "qmq2", 3: "qmq3", 4: "qmy1", 5: "qmq5", 6: "qmq6", 7: "qmq7"}
# series prefix -> nse_financials_quarterly column
SERIES_COLUMN = {"sr": "revenue_from_ops_cr", "op": "ebitda_cr", "np": "pat_cr", "eps": "eps_basic"}
# single-value parameters -> column on the latest quarter's row (balance-sheet items
# are point-in-time at the latest reported quarter)
LATEST_COLUMN = {
    "intq": "finance_costs_cr", "depq": "depreciation_cr", "taxq": "tax_expense_cr",
    "totalshareholdersfundsq": "total_equity_cr", "longtermborrowingsq": "long_term_debt_cr",
    "cashandcashequivalentsq": "cash_and_equiv_cr",
}


def series_token(prefix: str, offset: int) -> str:
    return prefix + OFFSET_SUFFIX[offset]


# The calls, in priority order. Each pass is one call per 10 stocks.
PASSES: Dict[str, List[str]] = {
    # revenue and profit for the latest five quarters: enough for QoQ and YoY
    "p1": [series_token(s, o) for s in ("sr", "np") for o in range(5)],
    "p2": [series_token(s, o) for s in ("op", "eps") for o in range(5)],
    "p3": [series_token(s, o) for s in ("sr", "np") for o in (5, 6, 7)] + ["mcapq"] + list(LATEST_COLUMN)[:3],
    "p4": [series_token(s, o) for s in ("op", "eps") for o in (5, 6, 7)] + list(LATEST_COLUMN)[3:],
}


def parse_parameter_values(text: str) -> Tuple[Dict[str, date], Dict[str, Dict[str, Optional[float]]]]:
    """A get_stock_parameter_values payload -> ({nse_code: as_of_date}, {label: {nse_code: value}}).

    The payload is a header of `id|name|nse_code|bse_code|date` lines followed by
    one block per parameter (`label`, then `CODE:value` lines) separated by `---`.
    Blocks carry the display label, not the token, and come in the provider's own
    order — callers must map labels back to tokens, never rely on position.
    """
    try:
        body = json.loads(text)
    except ValueError:
        raise ValueError(f"not JSON: {text[:120]!r}") from None
    if body.get("status") != "success" or not isinstance(body.get("data"), str):
        raise ValueError(f"unexpected payload: {str(body)[:160]}")
    chunks = [c.strip("\n") for c in body["data"].split("\n---")]
    header, _, first_block = chunks[0].partition("\n\n")
    stocks: Dict[str, date] = {}
    for line in header.splitlines():
        parts = line.split("|")
        if len(parts) == 5 and parts[2]:
            stocks[parts[2]] = date.fromisoformat(parts[4])
    blocks: Dict[str, Dict[str, Optional[float]]] = {}
    for block in [first_block] + chunks[1:]:
        lines = [l for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        values: Dict[str, Optional[float]] = {}
        for line in lines[1:]:
            code, sep, raw = line.rpartition(":")
            if sep and code in stocks:
                values[code] = _number(raw)
        blocks[lines[0].strip()] = values
    return stocks, blocks


def _number(raw: str) -> Optional[float]:
    raw = raw.strip().replace(",", "")
    if raw in ("", "None", "-", "NA", "null"):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


ENTITY_COLUMNS = ["name", "nse_code", "bse_code", "isin", "entity_type", "sector", "industry"]


def parse_entities(text: str) -> List[Dict[str, str]]:
    """A search_entities payload (a ` | `-delimited table under `data:`) -> rows."""
    rows: List[Dict[str, str]] = []
    seen_header = False
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().split(" | ")]
        if cells == ENTITY_COLUMNS:
            seen_header = True
            continue
        if seen_header and len(cells) == len(ENTITY_COLUMNS):
            rows.append(dict(zip(ENTITY_COLUMNS, cells)))
    return rows


# ── dating ───────────────────────────────────────────────────────────────────

def quarter_end_on_or_before(d: date) -> date:
    """The latest calendar quarter end that is not after `d`."""
    for month in (12, 9, 6, 3):
        end = date(d.year, month, calendar.monthrange(d.year, month)[1])
        if end <= d:
            return end
    return date(d.year - 1, 12, 31)


def shift_quarters(end: date, n: int) -> date:
    """`end` (a quarter end) moved by n quarters (negative = earlier)."""
    months = end.year * 12 + (end.month - 1) + 3 * n
    year, month = divmod(months, 12)
    return date(year, month + 1, calendar.monthrange(year, month + 1)[1])


def latest_quarter_from_anchor(revenue_by_offset: Dict[int, Optional[float]], anchor_end: date,
                               anchor_revenue: Optional[float], tolerance: float = 0.005) -> Optional[date]:
    """Date the provider's "latest quarter" from a quarter we already hold.

    `anchor_end` / `anchor_revenue` are a quarter's end date and revenue from a
    source that states its dates. If exactly one of the provider's offsets has
    that revenue (within `tolerance`), the provider's latest quarter is that many
    quarters after the anchor. None when nothing matches or the match is ambiguous.
    """
    if not anchor_revenue or anchor_revenue <= 0:
        return None
    hits = [o for o, v in revenue_by_offset.items()
            if v is not None and abs(v - anchor_revenue) <= tolerance * anchor_revenue]
    if len(hits) != 1:
        return None
    return shift_quarters(anchor_end, hits[0])


def latest_quarter_from_filings(as_of: date, results_filed_on: List[date]) -> Optional[date]:
    """Date the provider's "latest quarter" from when the company filed results.

    The newest quarter end before `as_of` is the latest reported quarter only if
    results were filed after it ended; otherwise it is the quarter before, provided
    results were filed for that one. None when neither can be shown.
    """
    newest = quarter_end_on_or_before(as_of)
    if any(d > newest for d in results_filed_on):
        return newest
    previous = shift_quarters(newest, -1)
    if any(previous < d <= newest for d in results_filed_on):
        return previous
    return None


def build_quarter_rows(values: Dict[str, Optional[float]], latest_end: date) -> List[Dict[str, object]]:
    """One symbol's staged {parameter: value} -> dated quarterly rows, newest first.
    A quarter with neither revenue nor profit is left out."""
    rows: List[Dict[str, object]] = []
    for offset in range(8):
        row: Dict[str, object] = {"period_end": shift_quarters(latest_end, -offset)}
        for prefix, column in SERIES_COLUMN.items():
            row[column] = values.get(series_token(prefix, offset))
        if offset == 0:
            for parameter, column in LATEST_COLUMN.items():
                row[column] = values.get(parameter)
        if row.get("revenue_from_ops_cr") is None and row.get("pat_cr") is None:
            continue
        rows.append(row)
    return rows
