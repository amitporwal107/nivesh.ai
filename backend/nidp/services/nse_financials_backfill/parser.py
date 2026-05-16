"""Multi-quarter financial data parsers.

Two sources:

1. NSE XBRL comparator  (/api/results-comparator?params={SYM}&period=Quarterly&type=...)
   Returns last 4-8 quarters in wide format:
     List[{"slNo":1, "desc":"Revenue", "1":1234.0, "2":2345.0, ...}]
   Period headers come from a separate "headers" key or must be inferred.

2. Screener.in  (https://www.screener.in/company/{SYM}/consolidated/)
   HTML page with a <table data-qa="quarters"> containing the last 20
   quarters with Revenue, Expenses, OPM%, PAT, EPS rows.

Both parsers return List[dict] — one dict per quarter, ready for
upsert_financials().  Callers must supply source="nse_xbrl" or
"screener_in" so the conflict-resolution in the writer can prefer
the higher-fidelity NSE XBRL rows.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── NSE XBRL Comparator parser ─────────────────────────────────────

_METRIC_MAP: Dict[str, str] = {
    # various label spellings NSE uses across schema revisions
    "total income":                "total_income_cr",
    "revenue from operations":     "revenue_from_ops_cr",
    "revenue":                     "revenue_from_ops_cr",
    "sales":                       "revenue_from_ops_cr",
    "total expenses":              "total_expenses_cr",
    "expenses":                    "total_expenses_cr",
    "ebitda":                      "ebitda_cr",
    "operating profit":            "ebitda_cr",
    "profit before tax":           "pbt_cr",
    "pbt":                         "pbt_cr",
    "profit before exceptional":   "pbt_before_exc_cr",
    "exceptional items":           "exceptional_items_cr",
    "tax expense":                 "tax_expense_cr",
    "tax":                         "tax_expense_cr",
    "profit after tax":            "pat_cr",
    "pat":                         "pat_cr",
    "net profit":                  "pat_cr",
    "profit/loss for the period":  "pat_cr",
    "basic eps":                   "eps_basic",
    "eps":                         "eps_basic",
    "earnings per share":          "eps_basic",
    "diluted eps":                 "eps_diluted",
    "finance costs":               "finance_costs_cr",
    "interest":                    "finance_costs_cr",
    "depreciation":                "depreciation_cr",
    "interest earned":             "interest_earned_cr",
    "interest expended":           "interest_expended_cr",
    "total equity":                "total_equity_cr",
    "equity":                      "total_equity_cr",
    "long term borrowings":        "long_term_debt_cr",
    "long-term borrowings":        "long_term_debt_cr",
    "short term borrowings":       "short_term_debt_cr",
    "short-term borrowings":       "short_term_debt_cr",
    "cash and cash equivalents":   "cash_and_equiv_cr",
}

# Month abbreviations → month number
_MONTH_MAP = {
    "jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
    "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
}

def _parse_quarter_date(s: str) -> Optional[date]:
    """Convert 'Sep 2024', '30-Sep-2024', 'Q2FY25', '2024-09-30' to a period-end date."""
    s = (s or "").strip()
    if not s:
        return None
    # ISO date
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        pass
    # dd-Mon-yyyy
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%b-%Y", "%B-%Y"):
        try:
            d = datetime.strptime(s, fmt)
            # For month-year only, use last day of month
            if "%d" not in fmt:
                import calendar
                last_day = calendar.monthrange(d.year, d.month)[1]
                return date(d.year, d.month, last_day)
            return d.date()
        except ValueError:
            continue
    # "Sep 2024" style
    m = re.match(r"(\w{3})\s+(\d{4})", s)
    if m:
        mon = _MONTH_MAP.get(m.group(1).lower())
        yr = int(m.group(2))
        if mon:
            import calendar
            last = calendar.monthrange(yr, mon)[1]
            return date(yr, mon, last)
    # Q2FY25 → Jun 30 2025 (quarter-end mapping: Q1=Jun, Q2=Sep, Q3=Dec, Q4=Mar)
    m = re.match(r"Q([1-4])FY(\d{2,4})", s, re.IGNORECASE)
    if m:
        q, yr = int(m.group(1)), int(m.group(2))
        if yr < 100:
            yr += 2000
        qend = {1: (6, 30), 2: (9, 30), 3: (12, 31), 4: (3, 31)}[q]
        mon, day = qend
        actual_yr = yr if mon != 3 else yr - 1  # Q4FY25 = Mar 2025 = FY2024-25
        # For Q4, fiscal year label refers to year ending March of that year
        actual_yr = yr if q != 4 else yr
        return date(actual_yr, mon, day)
    return None


def _to_crore(v: Any, col: str) -> Optional[float]:
    """Parse numeric value; EPS / face_value stay as-is, others in crore."""
    if v is None:
        return None
    try:
        f = float(str(v).replace(",", "").replace("(", "-").replace(")", "").strip())
        # EPS and face_value are per-share — don't scale
        if col in ("eps_basic", "eps_diluted", "face_value"):
            return round(f, 4)
        return round(f, 4)
    except (ValueError, TypeError):
        return None


def parse_nse_xbrl_multi_quarter(
    symbol: str,
    raw_json: str,
    consolidated: bool,
) -> List[Dict[str, Any]]:
    """Parse NSE XBRL comparator JSON response into per-quarter records.

    NSE returns data in wide format:
      List of metric rows, each having numeric column keys "1", "2", ...
      corresponding to period headers stored in a separate list.

    Falls back to the LLM extractor's single-quarter parser if the
    multi-quarter format is not detected.
    """
    try:
        payload = json.loads(raw_json)
    except Exception:
        return []

    # Unwrap envelope
    if isinstance(payload, dict):
        headers_raw = payload.get("headers") or payload.get("periods") or []
        rows_raw    = payload.get("data") or payload.get("result") or payload.get("rows") or []
        if not rows_raw and isinstance(payload, dict):
            # Flat dict — single quarter from old parser
            rows_raw = [payload]
    elif isinstance(payload, list):
        headers_raw = []
        rows_raw = payload
    else:
        return []

    if not rows_raw:
        return []

    # ── Detect format ──────────────────────────────────────────────
    first = rows_raw[0] if rows_raw else {}

    # Format A: wide — keys are "1","2"... metrics are in "desc" field
    numeric_keys = [k for k in first if re.match(r"^\d+$", str(k))]
    has_desc      = "desc" in first or "name" in first or "metric" in first

    if has_desc and numeric_keys:
        return _parse_wide_format(
            symbol, rows_raw, headers_raw, numeric_keys, consolidated
        )

    # Format B: long — each row is one quarter, metrics as column keys
    # Keys will be readable strings like "totalIncome", "pat" etc.
    return _parse_long_format(symbol, rows_raw, consolidated)


def _parse_wide_format(
    symbol: str,
    rows: list,
    headers: list,
    numeric_keys: list,
    consolidated: bool,
) -> List[Dict[str, Any]]:
    """Wide format: rows=metrics, cols=quarters."""
    # Build index: col_number → period_end date
    col_dates: Dict[str, Optional[date]] = {}
    for i, h in enumerate(headers):
        col_key = str(i + 1)
        d = _parse_quarter_date(str(h)) if isinstance(h, (str, int)) else None
        if d is None and isinstance(h, dict):
            d = _parse_quarter_date(h.get("period") or h.get("date") or "")
        col_dates[col_key] = d

    # Fill missing dates: if headers not provided, infer from column count
    # fallback — quarters descending from today
    import calendar
    from datetime import date as dt_date
    today = dt_date.today()
    auto_dates = []
    # Walk backwards by quarter
    y, m = today.year, today.month
    for _ in range(max(len(numeric_keys), 8)):
        last = calendar.monthrange(y, m)[1]
        auto_dates.append(dt_date(y, m, last))
        m -= 3
        if m <= 0:
            m += 12
            y -= 1

    for k in numeric_keys:
        if k not in col_dates or col_dates[k] is None:
            idx = int(k) - 1
            if idx < len(auto_dates):
                col_dates[k] = auto_dates[idx]

    # Build per-quarter records
    quarters: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        desc_raw = (row.get("desc") or row.get("name") or row.get("metric") or "").strip().lower()
        col_name = _METRIC_MAP.get(desc_raw)
        if not col_name:
            continue
        for k in numeric_keys:
            period_end = col_dates.get(k)
            if period_end is None:
                continue
            key = period_end.isoformat()
            if key not in quarters:
                quarters[key] = {
                    "period_end":   period_end,
                    "consolidated": consolidated,
                    "audited":      None,
                    "period_type":  "QUARTERLY",
                }
            val = _to_crore(row.get(k), col_name)
            if val is not None and quarters[key].get(col_name) is None:
                quarters[key][col_name] = val

    return [q for q in quarters.values() if q.get("period_end")]


def _parse_long_format(
    symbol: str,
    rows: list,
    consolidated: bool,
) -> List[Dict[str, Any]]:
    """Long format: each row is one quarter."""
    results = []
    for row in rows:
        period_end = None
        for pk in ("period", "period_end", "date", "toDate", "quarter"):
            if row.get(pk):
                period_end = _parse_quarter_date(str(row[pk]))
                if period_end:
                    break

        if not period_end:
            continue

        def _g(keys: list) -> Optional[float]:
            for k in keys:
                if row.get(k) is not None:
                    try:
                        return float(str(row[k]).replace(",", ""))
                    except (ValueError, TypeError):
                        pass
            return None

        rec = {
            "period_end":           period_end,
            "consolidated":         consolidated,
            "audited":              None,
            "period_type":          "QUARTERLY",
            "revenue_from_ops_cr":  _g(["totalIncome", "revenue", "sales"]),
            "total_income_cr":      _g(["totalIncome"]),
            "total_expenses_cr":    _g(["totalExpenses", "expenses"]),
            "ebitda_cr":            _g(["ebitda", "operatingProfit"]),
            "pbt_cr":               _g(["pbt", "profitBeforeTax"]),
            "tax_expense_cr":       _g(["tax", "taxExpense"]),
            "pat_cr":               _g(["pat", "netProfit", "profitAfterTax"]),
            "eps_basic":            _g(["eps", "basicEps", "earningsPerShare"]),
            "eps_diluted":          _g(["dilutedEps"]),
            "finance_costs_cr":     _g(["financeCosts", "interest"]),
            "depreciation_cr":      _g(["depreciation"]),
            "interest_earned_cr":   _g(["interestEarned"]),
            "interest_expended_cr": _g(["interestExpended"]),
            "total_equity_cr":      _g(["equity", "totalEquity"]),
            "long_term_debt_cr":    _g(["longTermBorrowings"]),
            "short_term_debt_cr":   _g(["shortTermBorrowings"]),
            "cash_and_equiv_cr":    _g(["cashAndEquivalents"]),
        }
        results.append(rec)
    return results


# ─── Screener.in HTML parser ─────────────────────────────────────────

def parse_screener_quarters(symbol: str, html: str) -> List[Dict[str, Any]]:
    """Parse the Screener.in quarterly results table.

    Screener HTML contains:
      <section id="quarters">
        <table class="data-table...">
          <thead><tr><th>...</th><th>Sep 2024</th>...</tr></thead>
          <tbody>
            <tr><td class="...">Sales +</td><td>1234</td>...</tr>
            <tr><td>Expenses +</td>...
            <tr><td>Operating Profit</td>...
            <tr><td>OPM %</td>...
            <tr><td>Other Income +</td>...
            <tr><td>Interest</td>...
            <tr><td>Depreciation</td>...
            <tr><td>Profit before tax</td>...
            <tr><td>Tax %</td>...
            <tr><td>Net Profit +</td>...
            <tr><td>EPS in Rs</td>...
    """
    try:
        from html.parser import HTMLParser
    except ImportError:
        return []

    # Find the #quarters section
    m = re.search(r'id=["\']quarters["\'].*?<table(.*?)</table>', html, re.DOTALL | re.IGNORECASE)
    if not m:
        # Try data-qa="quarters"
        m = re.search(r'data-qa=["\']quarters["\'].*?<table(.*?)</table>', html, re.DOTALL | re.IGNORECASE)
    if not m:
        return []

    table_html = "<table" + m.group(1) + "</table>"

    # Extract headers (period dates)
    header_m = re.search(r"<thead>(.*?)</thead>", table_html, re.DOTALL)
    periods: List[Optional[date]] = []
    if header_m:
        ths = re.findall(r"<th[^>]*>(.*?)</th>", header_m.group(1), re.DOTALL)
        for th in ths[1:]:  # skip first "Metric" column
            text = re.sub(r"<[^>]+>", "", th).strip()
            d = _parse_quarter_date(text)
            periods.append(d)

    if not periods:
        return []

    # Extract data rows
    body_m = re.search(r"<tbody>(.*?)</tbody>", table_html, re.DOTALL)
    if not body_m:
        return []

    # metric name → column name
    SCREENER_MAP = {
        "sales":                "revenue_from_ops_cr",
        "revenue":              "revenue_from_ops_cr",
        "expenses":             "total_expenses_cr",
        "operating profit":     "ebitda_cr",
        "other income":         "other_income_cr",
        "interest":             "finance_costs_cr",
        "depreciation":         "depreciation_cr",
        "profit before tax":    "pbt_cr",
        "net profit":           "pat_cr",
        "eps in rs":            "eps_basic",
        "earnings per share":   "eps_basic",
    }

    quarters: Dict[str, Dict[str, Any]] = {}
    for p in periods:
        if p:
            quarters[p.isoformat()] = {
                "period_end":   p,
                "consolidated": False,  # caller sets this
                "audited":      None,
                "period_type":  "QUARTERLY",
            }

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", body_m.group(1), re.DOTALL)
    for row_html in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL)
        if not cells:
            continue
        metric_raw = re.sub(r"<[^>]+>", "", cells[0]).strip().lower()
        # strip trailing " +" or " %"
        metric_raw = re.sub(r"\s*[\+%]$", "", metric_raw).strip()
        col = SCREENER_MAP.get(metric_raw)
        if not col:
            continue

        # skip OPM% rows (percentages, not absolute values)
        if "%" in col:
            continue

        for i, period in enumerate(periods):
            if period is None or i + 1 >= len(cells):
                continue
            raw = re.sub(r"<[^>]+>", "", cells[i + 1]).strip().replace(",", "")
            if not raw or raw in ("-", "—", ""):
                continue
            try:
                val = float(raw)
            except ValueError:
                continue
            key = period.isoformat()
            if key in quarters and quarters[key].get(col) is None:
                quarters[key][col] = round(val, 4)

    return [q for q in quarters.values() if q.get("period_end") and any(
        q.get(c) is not None
        for c in ("revenue_from_ops_cr", "pat_cr", "eps_basic")
    )]
