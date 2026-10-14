"""Pure parsing and dating for the Trendlyne loader. No I/O."""
from __future__ import annotations

import calendar
import json
import re
from datetime import date
from typing import Dict, List, NamedTuple, Optional, Tuple

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


class RatioMetric(NamedTuple):
    column: str         # the nidp.stock_features_daily column the figure feeds
    parameter: str      # the token sent to the provider
    unit: str           # 'percent' | 'ratio' | 'inr_crore'
    period_basis: str   # 'annual' = latest reported fiscal year; 'point_in_time' = moves with price


# The provider's own ratios, as checked in the 2026-10-14 pilot against its other fields:
#   ROE Ann. %    = annual net profit / shareholders' funds at that year end x 100
#   ROCE Ann. %   = annual; (PBT + interest) / (total assets - current liabilities) reproduced it
#                   for 3 of 8 companies, so its capital-employed definition is not pinned down
#   Total Debt to Total Equity Ann. = (long-term + short-term borrowings) / shareholders' funds
#   PBV Adjusted  = LTP / latest book value per share
#   Market Cap    = LTP x shares outstanding, in rupees crore
# All on the provider's default basis (consolidated where the company reports it).
RATIO_METRICS: List[RatioMetric] = [
    RatioMetric("roe_pct", "roea", "percent", "annual"),
    RatioMetric("roce_pct", "rocea", "percent", "annual"),
    RatioMetric("debt_to_equity", "debtcea", "ratio", "annual"),
    RatioMetric("pb", "pbva", "ratio", "point_in_time"),
    RatioMetric("market_cap_cr", "mcapq", "inr_crore", "point_in_time"),
]
# The price behind P/B and market cap. The reply's date stamp is not the price's date (a reply
# stamped 13 Oct carried the 12 Oct close), so the price is staged too and matched to our own closes.
PRICE_PARAMETER = "currentprice"
RATIO_PASS = "r1"

# Each pass is one call per 10 stocks.
PASSES: Dict[str, List[str]] = {
    # revenue and profit for the latest five quarters: enough for QoQ and YoY
    "p1": [series_token(s, o) for s in ("sr", "np") for o in range(5)],
    "p2": [series_token(s, o) for s in ("op", "eps") for o in range(5)],
    "p3": [series_token(s, o) for s in ("sr", "np") for o in (5, 6, 7)] + list(LATEST_COLUMN)[:3],
    "p4": [series_token(s, o) for s in ("op", "eps") for o in (5, 6, 7)] + list(LATEST_COLUMN)[3:],
    # ROE, ROCE, debt-to-equity, P/B and market cap, as the provider computes them
    RATIO_PASS: [m.parameter for m in RATIO_METRICS] + [PRICE_PARAMETER],
}
# The order the daily job spends its call budget in.
DAILY_ORDER: Tuple[str, ...] = (RATIO_PASS, "p1", "p2", "p3", "p4")


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


_UNRESOLVED = re.compile(r"Could not resolve stock code\(s\):\s*(.*?)\.?\s*(?:\[code:\d+\])?\s*$")


def unresolved_codes(text: str) -> List[str]:
    """The stock codes an error reply says the provider cannot resolve; [] for any other reply.

    One unknown code fails the whole call:
        {"status": "error", "message": "Could not resolve stock code(s): ZZNOTREAL. [code:1012]"}
    so the caller drops those codes and asks again for the rest.
    """
    try:
        body = json.loads(text)
    except ValueError:
        return []
    if not isinstance(body, dict) or body.get("status") != "error":
        return []
    match = _UNRESOLVED.search(str(body.get("message") or ""))
    return [c.strip() for c in match.group(1).split(",") if c.strip()] if match else []


# ── ratios ───────────────────────────────────────────────────────────────────

# A figure carrying one of these is stored as the provider gave it but is not copied into the
# feature row: the number does not mean what its column says.
UNUSABLE_FLAGS = frozenset({"negative_book_value", "market_cap_zero", "implausible_magnitude"})
ROE_FLAG_BEYOND_PCT = 200.0
# Percentages and ratios at or beyond this cannot be real and would not fit their columns.
MAX_RATIO_MAGNITUDE = 100_000.0


def price_session(ltp: Optional[float], stamp: date, closes: Dict[date, float],
                  tolerance: float = 0.005) -> Optional[date]:
    """The trading day whose close is the provider's price: the latest day on or before the
    reply's stamp whose close (from our own price feed) equals `ltp`. None when no day matches,
    so a date is never guessed."""
    if ltp is None:
        return None
    days = [d for d, close in closes.items() if d <= stamp and close is not None and abs(close - ltp) <= tolerance]
    return max(days) if days else None


def build_ratio_rows(values: Dict[str, Optional[float]], labels: Dict[str, str], stamp: date,
                     price_date: Optional[date]) -> List[Dict[str, object]]:
    """One company's staged {parameter: value} -> one row per figure, with its unit, basis,
    the provider's field name, dates and sanity flags. [] when the provider gave none of the
    five (an ETF, say). A figure the provider did not give keeps value None — never 0.

    `stamp` is the date on the provider's reply; `price_date` the session whose close it used
    (see price_session), or None when that could not be confirmed. Rows are dated by
    `price_date` when there is one, otherwise by the stamp with 'price_date_unconfirmed' on
    the two price-based figures.

    Flags (the value is always kept as given):
      negative_book_value   P/B or D/E below zero means net worth is negative; P/B, D/E and ROE
                            then carry the wrong sign and are marked unusable
      roe_beyond_200        ROE outside +/-200%: kept and usable, but worth a look
      market_cap_zero       market cap of zero or less: unusable
      implausible_magnitude a percentage or ratio of 100,000 or more: unusable
    """
    by_column = {m.column: values.get(m.parameter) for m in RATIO_METRICS}
    if all(v is None for v in by_column.values()):
        return []
    pb, de = by_column["pb"], by_column["debt_to_equity"]
    negative_book = (pb is not None and pb < 0) or (de is not None and de < 0)
    rows: List[Dict[str, object]] = []
    for m in RATIO_METRICS:
        value = by_column[m.column]
        flags: List[str] = []
        if value is not None:
            if negative_book and m.column in ("pb", "debt_to_equity", "roe_pct"):
                flags.append("negative_book_value")
            if m.column == "roe_pct" and abs(value) > ROE_FLAG_BEYOND_PCT:
                flags.append("roe_beyond_200")
            if m.column == "market_cap_cr" and value <= 0:
                flags.append("market_cap_zero")
            if m.unit != "inr_crore" and abs(value) >= MAX_RATIO_MAGNITUDE:
                flags.append("implausible_magnitude")
            if m.period_basis == "point_in_time" and price_date is None:
                flags.append("price_date_unconfirmed")
        rows.append({
            "metric": m.column, "value": value, "unit": m.unit, "period_basis": m.period_basis,
            "usable": not UNUSABLE_FLAGS.intersection(flags), "flags": flags,
            "provider_field": labels.get(m.parameter), "provider_parameter": m.parameter,
            # The provider gives no fiscal-year end for its annual figures, so none is recorded.
            "period_end": None,
            "as_of_date": price_date or stamp, "provider_date": stamp,
        })
    return rows


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


def latest_quarter_from_anchor(values_by_offset: Dict[int, Optional[float]], anchor_end: date,
                               anchor_value: Optional[float], as_of: date,
                               tolerance: float = 0.005) -> Optional[date]:
    """Date the provider's "latest quarter" from a quarter we already hold.

    `anchor_end` / `anchor_value` are a quarter's end date and one figure for it
    (revenue, or profit where the held row has no revenue) from a source that
    states its dates; `values_by_offset` is the provider's series for the same
    figure. If exactly one offset has that value, the provider's latest quarter is that many quarters after the
    anchor. None when nothing matches, when the match is ambiguous, or when it
    would put the latest quarter after `as_of` (a quarter that has not ended).

    The anchor may be rounded to whole crores (Screener's pages are), so a small
    company's figure is allowed to differ by up to 0.5 Cr; that is also why two
    offsets can both match, and then no date is returned.
    """
    if anchor_value is None or anchor_value == 0:
        return None
    allowed = max(0.5, tolerance * abs(anchor_value))
    hits = [o for o, v in values_by_offset.items() if v is not None and abs(v - anchor_value) <= allowed]
    if len(hits) != 1:
        return None
    latest = shift_quarters(anchor_end, hits[0])
    return latest if latest <= quarter_end_on_or_before(as_of) else None


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


def company_search_name(company_name: str) -> str:
    """A sector_master company name as a search query: the provider's search finds
    "Karnataka Bank" but not "The Karnataka Bank Limited" style exchange names
    reliably, and often nothing at all for a bare symbol."""
    name = company_name.strip()
    for prefix in ("The ",):
        if name.startswith(prefix):
            name = name[len(prefix):]
    for suffix in (" Limited", " Ltd.", " Ltd"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.strip()
