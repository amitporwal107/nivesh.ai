"""LLM-powered financial data extractor.

Takes raw text (HTML / PDF text / XBRL JSON) from a company's result
document and extracts structured financial figures into a dict matching
the nidp.nse_financials_quarterly schema.

Backend selection (checked in order):
  1. OPENAI_API_KEY set  → OpenAI gpt-4o-mini
  2. ANTHROPIC_API_KEY set → Claude claude-haiku-4-5
Falls back gracefully if the LLM cannot find a number (returns None).
"""
from __future__ import annotations

import json
import logging
import os
from nidp.shared.openai_key import get_openai_api_key
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

_CLAUDE_MODEL = "claude-haiku-4-5-20251001"
_OPENAI_MODEL = "gpt-4o-mini"

_SYSTEM = """You are a financial data extraction assistant specialised in Indian company quarterly results.
Extract structured financial data from the provided document text.
Return ONLY valid JSON — no explanation, no markdown, no code fences.
All monetary values must be in Indian Rupees Crore (₹ Cr).
If a value is not found, use null.
Use negative numbers for losses/expenses where appropriate."""

_PROMPT_TEMPLATE = """Extract the quarterly financial results for {symbol} from the following document.

Document text:
---
{text}
---

Return JSON with exactly this structure:
{{
  "period_end": "YYYY-MM-DD",
  "period_start": "YYYY-MM-DD",
  "period_type": "quarterly",
  "consolidated": true or false,
  "audited": true or false,
  "revenue_from_ops_cr": number or null,
  "other_income_cr": number or null,
  "total_income_cr": number or null,
  "total_expenses_cr": number or null,
  "ebitda_cr": number or null,
  "finance_costs_cr": number or null,
  "depreciation_cr": number or null,
  "pbt_before_exc_cr": number or null,
  "exceptional_items_cr": number or null,
  "pbt_cr": number or null,
  "tax_expense_cr": number or null,
  "pat_cr": number or null,
  "pat_attrib_owners_cr": number or null,
  "eps_basic": number or null,
  "eps_diluted": number or null,
  "face_value": number or null,
  "total_equity_cr": number or null,
  "long_term_debt_cr": number or null,
  "short_term_debt_cr": number or null,
  "cash_and_equiv_cr": number or null,
  "interest_earned_cr": number or null,
  "interest_expended_cr": number or null,
  "nim_pct": number or null
}}"""


def _provider() -> str:
    """Return 'openai' or 'anthropic' based on which key is set."""
    if get_openai_api_key():
        return "openai"
    return "anthropic"


async def extract_financials(
    symbol: str,
    raw_text: str,
    source_url: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Extract structured financials from raw document text using the configured LLM.

    Returns a dict matching nse_financials_quarterly columns, or None on failure.
    """
    if not raw_text or len(raw_text) < 100:
        return None

    # Trim to 15k chars — enough for a full result page without burning tokens
    text = raw_text[:15_000]
    prompt = _PROMPT_TEMPLATE.format(symbol=symbol, text=text)

    try:
        if _provider() == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=get_openai_api_key())
            resp = client.chat.completions.create(
                model=_OPENAI_MODEL,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            )
            raw = resp.choices[0].message.content.strip()
            tokens = resp.usage.prompt_tokens
        else:
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
            msg = client.messages.create(
                model=_CLAUDE_MODEL,
                max_tokens=1024,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            tokens = msg.usage.input_tokens

        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        logger.info("llm_extractor: extracted financials for %s via %s (tokens=%d)", symbol, _provider(), tokens)
        return data
    except json.JSONDecodeError as e:
        logger.warning("llm_extractor: JSON parse failed for %s: %s", symbol, e)
        return None
    except Exception as e:
        logger.error("llm_extractor: extraction failed for %s: %s", symbol, e)
        return None


def _screener_quarter_label_to_date(label: str) -> Optional[str]:
    """Convert Screener.in quarter label to ISO date string (period-end date).

    Handles multiple formats that Screener.in uses across different companies:
      'Mar 2025'  → '2025-03-31'   (standard monthly label, most common)
      'Dec 2024'  → '2024-12-31'
      'Q1 FY24'   → '2023-06-30'   (Indian FY: Q1=Apr-Jun, FY24 ends Mar 2024)
      'Q2 FY24'   → '2023-09-30'
      'Q3 FY24'   → '2023-12-31'
      'Q4 FY24'   → '2024-03-31'
      'FY24'      → '2024-03-31'   (annual period ending March of the FY year)
      'TTM'       → None (skip — not a fixed period end)
    """
    _MONTH_END = {
        "jan": (1, 31), "feb": (2, 28), "mar": (3, 31), "apr": (4, 30),
        "may": (5, 31), "jun": (6, 30), "jul": (7, 31), "aug": (8, 31),
        "sep": (9, 30), "oct": (10, 31), "nov": (11, 30), "dec": (12, 31),
    }
    # Indian FY quarter → (month, day) of period-end
    _Q_PERIOD_END = {1: (6, 30), 2: (9, 30), 3: (12, 31), 4: (3, 31)}

    raw = label.strip()

    # Format: "Q{N} FY{YY}" or "Q{N} FY{YYYY}" or "Q{N}FY{YY/YYYY}"
    m_qfy = re.match(r"Q([1-4])\s*FY(\d{2,4})$", raw, re.IGNORECASE)
    if m_qfy:
        q = int(m_qfy.group(1))
        fy_raw = int(m_qfy.group(2))
        fy = fy_raw + 2000 if fy_raw < 100 else fy_raw  # 24 → 2024
        mo, d = _Q_PERIOD_END[q]
        # Q1-Q3: calendar year = fy - 1; Q4: calendar year = fy
        cal_year = fy - 1 if q <= 3 else fy
        return f"{cal_year}-{mo:02d}-{d:02d}"

    # Format: "FY{YY}" or "FY{YYYY}" — annual period ending March of that year
    m_fy = re.match(r"FY(\d{2,4})$", raw, re.IGNORECASE)
    if m_fy:
        fy_raw = int(m_fy.group(1))
        fy = fy_raw + 2000 if fy_raw < 100 else fy_raw
        return f"{fy}-03-31"

    # Standard "Mon YYYY" format (most common)
    parts = raw.split()
    if len(parts) != 2:
        return None
    mon = parts[0].lower()[:3]
    try:
        year = int(parts[1])
    except ValueError:
        return None
    if mon not in _MONTH_END:
        return None
    mo, d = _MONTH_END[mon]
    return f"{year}-{mo:02d}-{d:02d}"


def _parse_screener_section(
    html: str,
    section_id: str,
) -> Optional[tuple[list[str], dict[str, list[Optional[float]]]]]:
    """Generic Screener.in data-table parser for any named section.

    section_id: HTML id attribute of the <section> element, e.g. 'quarters',
        'balance-sheet', 'shareholding', 'cash-flow'.

    Returns (col_labels, raw_table) or None if the section/table is absent.
    col_labels: column header strings (oldest→newest for time-series sections).
    raw_table:  dict mapping normalised row label → list of float|None values
                aligned with col_labels.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html, "lxml")
    # Screener.in uses <section id="..."> on some pages and <div id="..."> on others
    section = soup.find("section", {"id": section_id}) or soup.find(id=section_id)
    if not section:
        return None
    table = section.find("table", class_="data-table")
    if not table:
        table = section.find("table")  # fallback: first table in section
    if not table:
        return None
    thead = table.find("thead")
    tbody = table.find("tbody")
    if not thead or not tbody:
        return None

    ths = thead.find_all("th")
    if len(ths) < 2:
        return None
    col_labels = [th.get_text(strip=True) for th in ths[1:]]

    raw_table: dict[str, list[Optional[float]]] = {}
    for tr in tbody.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True).rstrip("+").strip().lower()
        all_vals: list[Optional[float]] = []
        for cell in cells[1:]:
            raw = cell.get_text(strip=True).replace(",", "").rstrip("%")
            try:
                all_vals.append(float(raw))
            except ValueError:
                all_vals.append(None)
        raw_table[label] = all_vals

    return col_labels, raw_table


def _parse_screener_table(
    html: str,
) -> Optional[tuple[list[str], dict[str, list[Optional[float]]]]]:
    """Parse the Screener.in #quarters table. Delegates to _parse_screener_section."""
    return _parse_screener_section(html, "quarters")


def _build_quarter_dict(
    row_map: dict[str, Optional[float]],
    period_end: str,
    consolidated: bool,
) -> dict[str, Any]:
    """Map a Screener row_map (single quarter) to nse_financials_quarterly columns."""
    def _get(*keys: str) -> Optional[float]:
        for k in keys:
            for label, val in row_map.items():
                if k in label:
                    return val
        return None

    revenue = _get("sales")
    other_income = _get("other income")
    total_income: Optional[float] = None
    if revenue is not None and other_income is not None:
        total_income = round(revenue + other_income, 4)
    elif revenue is not None:
        total_income = revenue

    return {
        "period_end":           period_end,
        "period_type":          "quarterly",
        "consolidated":         consolidated,
        "audited":              None,
        "revenue_from_ops_cr":  revenue,
        "other_income_cr":      other_income,
        "total_income_cr":      total_income,
        "total_expenses_cr":    _get("expenses"),
        "ebitda_cr":            _get("operating profit"),
        "finance_costs_cr":     _get("interest"),
        "depreciation_cr":      _get("depreciation"),
        "pbt_cr":               _get("profit before tax"),
        "pat_cr":               _get("net profit"),
        "eps_basic":            _get("eps in rs", "eps"),
    }


def parse_screener_quarters(
    symbol: str, html: str, consolidated: bool = False
) -> Optional[tuple[dict[str, Any], dict[str, Any]]]:
    """Parse Screener.in company page HTML.

    Returns (parsed, raw_data) where:
    - parsed  matches nse_financials_quarterly columns (latest quarter only)
    - raw_data stores all quarters & all rows for future metric extraction

    Screener reports values in ₹ Crore — no unit conversion needed.
    Returns None on failure.
    """
    result = _parse_screener_table(html)
    if not result:
        logger.debug("parse_screener_quarters: no #quarters section for %s", symbol)
        return None

    quarter_labels, raw_table = result
    latest_label = quarter_labels[-1]
    period_end = _screener_quarter_label_to_date(latest_label)
    if not period_end:
        logger.warning("parse_screener_quarters: unrecognised quarter label '%s' for %s", latest_label, symbol)
        return None

    row_map_latest = {label: vals[-1] if vals else None for label, vals in raw_table.items()}

    raw_data: dict[str, Any] = {
        "source": "screener_in",
        "consolidated": consolidated,
        "quarters": quarter_labels,
        "data": raw_table,
    }

    def _get(*keys: str) -> Optional[float]:
        for k in keys:
            for label, val in row_map_latest.items():
                if k in label:
                    return val
        return None

    revenue = _get("sales")
    other_income = _get("other income")
    expenses = _get("expenses")
    op_profit = _get("operating profit")
    interest = _get("interest")
    parsed = _build_quarter_dict(row_map_latest, period_end, consolidated)

    non_null = sum(1 for v in parsed.values() if v is not None)
    logger.info(
        "parse_screener_quarters: %s parsed %d fields for %s (consolidated=%s, quarters=%d)",
        symbol, non_null, period_end, consolidated, len(quarter_labels),
    )
    return parsed, raw_data


def parse_all_screener_quarters(
    symbol: str,
    html: str,
    consolidated: bool = False,
    since_date: Optional[str] = None,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Parse ALL quarters from a Screener.in page within the given date window.

    Returns a list of (parsed, raw_data) tuples — one per quarter where
    period_end >= since_date (ISO string, e.g. '2025-01-01').
    raw_data is the same full-table payload for each entry.
    Returns [] on failure.
    """
    result = _parse_screener_table(html)
    if not result:
        logger.debug("parse_all_screener_quarters: no #quarters section for %s", symbol)
        return []

    quarter_labels, raw_table = result
    raw_data: dict[str, Any] = {
        "source": "screener_in",
        "consolidated": consolidated,
        "quarters": quarter_labels,
        "data": raw_table,
    }

    output: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for i, label in enumerate(quarter_labels):
        period_end = _screener_quarter_label_to_date(label)
        if not period_end:
            continue
        if since_date and period_end < since_date:
            continue
        row_map = {lbl: vals[i] if i < len(vals) else None for lbl, vals in raw_table.items()}
        parsed = _build_quarter_dict(row_map, period_end, consolidated)
        output.append((parsed, raw_data))

    logger.info(
        "parse_all_screener_quarters: %s — %d quarters in window (since=%s, total=%d)",
        symbol, len(output), since_date, len(quarter_labels),
    )
    return output


def parse_nse_integrated_xbrl(symbol: str, xml_text: str) -> Optional[dict[str, Any]]:
    """Parse NSE Integrated XBRL filing (SEBI IndAS/IGAAP format) — zero LLM tokens.

    The integrated filing XML stores monetary values in base INR (rupees).
    All P&L items use contextRef="OneD" (current quarter).
    Balance sheet items use contextRef="OneI" (period-end instant).
    Metadata fields (dates, flags) also use contextRef="OneD".
    """
    if not xml_text or "<?xml" not in xml_text[:100]:
        return None

    def _num(tag: str, ctx: str) -> Optional[float]:
        m = re.search(
            r'<[^:>]+:' + re.escape(tag) + r'[^>]*contextRef="' + ctx + r'"[^>]*>([^<]+)<',
            xml_text,
        )
        if not m:
            return None
        try:
            return round(float(m.group(1).replace(",", "")) / 1e7, 4)  # rupees → crores
        except (ValueError, TypeError):
            return None

    def _raw(tag: str, ctx: str) -> Optional[float]:
        """Return raw numeric value (no crore conversion — for EPS, face value)."""
        m = re.search(
            r'<[^:>]+:' + re.escape(tag) + r'[^>]*contextRef="' + ctx + r'"[^>]*>([^<]+)<',
            xml_text,
        )
        if not m:
            return None
        try:
            return float(m.group(1).replace(",", ""))
        except (ValueError, TypeError):
            return None

    def _str(tag: str, ctx: str = "OneD") -> Optional[str]:
        m = re.search(
            r'<[^:>]+:' + re.escape(tag) + r'[^>]*contextRef="' + ctx + r'"[^>]*>([^<]+)<',
            xml_text,
        )
        return m.group(1).strip() if m else None

    period_end = _str("DateOfEndOfReportingPeriod")
    period_start = _str("DateOfStartOfReportingPeriod")
    if not period_end:
        logger.warning("parse_nse_integrated_xbrl: no period_end in XML for %s", symbol)
        return None

    nature = _str("NatureOfReportStandaloneConsolidated") or ""
    audited_str = _str("WhetherResultsAreAuditedOrUnaudited") or ""
    consolidated = "consolidated" in nature.lower()
    audited = "audited" in audited_str.lower() and "unaudited" not in audited_str.lower()

    pat = _num("ProfitLossForPeriod", "OneD") or _num("ProfitLossForPeriodFromContinuingOperations", "OneD")
    pbt_exc = _num("ProfitBeforeExceptionalItemsAndTax", "OneD")
    fin_costs = _num("FinanceCosts", "OneD")
    dep = _num("DepreciationDepletionAndAmortisationExpense", "OneD")
    ebitda = round(pbt_exc + fin_costs + dep, 4) if all(v is not None for v in [pbt_exc, fin_costs, dep]) else None

    # EPS and face value are per-share rupee amounts — no crore conversion
    eps_basic = (_raw("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "OneD")
                 or _raw("BasicEarningsLossPerShareFromContinuingOperations", "OneD"))
    eps_diluted = (_raw("DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "OneD")
                   or _raw("DilutedEarningsLossPerShareFromContinuingOperations", "OneD"))
    face_value = (_raw("FaceValueOfEquityShareCapital", "OneD")
                  or _raw("FaceValueOfEquityShareCapital", "FourD"))

    result = {
        "period_end":           period_end,
        "period_start":         period_start,
        "period_type":          "quarterly",
        "consolidated":         consolidated,
        "audited":              audited,
        "revenue_from_ops_cr":  _num("RevenueFromOperations", "OneD"),
        "other_income_cr":      _num("OtherIncome", "OneD"),
        "total_income_cr":      _num("Income", "OneD"),
        "total_expenses_cr":    _num("Expenses", "OneD"),
        "ebitda_cr":            ebitda,
        "finance_costs_cr":     fin_costs,
        "depreciation_cr":      dep,
        "pbt_before_exc_cr":    pbt_exc,
        "exceptional_items_cr": _num("ExceptionalItemsBeforeTax", "OneD"),
        "pbt_cr":               _num("ProfitBeforeTax", "OneD"),
        "tax_expense_cr":       _num("TaxExpense", "OneD"),
        "pat_cr":               pat,
        "pat_attrib_owners_cr": _num("ProfitLossAttributableToOwnersOfParent", "OneD"),
        "eps_basic":            eps_basic,
        "eps_diluted":          eps_diluted,
        "face_value":           face_value,
        "total_equity_cr":      _num("Equity", "OneI"),
        "long_term_debt_cr":    _num("BorrowingsNoncurrent", "OneI"),
        "short_term_debt_cr":   _num("BorrowingsCurrent", "OneI"),
        "cash_and_equiv_cr":    _num("CashAndCashEquivalents", "OneI"),
    }
    non_null = sum(1 for v in result.values() if v is not None)
    logger.info("parse_nse_integrated_xbrl: %s parsed %d fields (period=%s, consolidated=%s)",
                symbol, non_null, period_end, consolidated)
    return result


def parse_screener_balance_sheet(
    symbol: str,
    html: str,
    consolidated: bool = False,
) -> list[dict[str, Any]]:
    """Parse Screener.in #balance-sheet section → list of annual dicts.

    Each entry covers a fiscal year-end (March 31) and contains:
      period_end, equity_share_capital_cr, total_equity_cr (equity + reserves),
      long_term_debt_cr (borrowings), consolidated.

    Screener reports all figures in ₹ Crore — no conversion needed.
    Returns [] if the section is absent or no parseable rows are found.
    """
    result = _parse_screener_section(html, "balance-sheet")
    if not result:
        logger.debug("parse_screener_balance_sheet: no #balance-sheet section for %s", symbol)
        return []

    col_labels, raw_table = result

    def _row(*keys: str) -> list[Optional[float]]:
        for k in keys:
            for label, vals in raw_table.items():
                if k in label:
                    return vals
        return [None] * len(col_labels)

    equity_cap_vals = _row("equity capital", "share capital")
    reserves_vals   = _row("reserves")
    borrowings_vals = _row("borrowings")

    output: list[dict[str, Any]] = []
    for i, label in enumerate(col_labels):
        period_end = _screener_quarter_label_to_date(label)
        if not period_end:
            continue

        def _v(vals: list) -> Optional[float]:
            return vals[i] if i < len(vals) else None

        eq_cap   = _v(equity_cap_vals)
        reserves = _v(reserves_vals)
        borrow   = _v(borrowings_vals)

        total_equity: Optional[float] = None
        if eq_cap is not None and reserves is not None:
            total_equity = round(eq_cap + reserves, 4)
        elif eq_cap is not None:
            total_equity = eq_cap

        output.append({
            "period_end":              period_end,
            "consolidated":            consolidated,
            "equity_share_capital_cr": eq_cap,
            "total_equity_cr":         total_equity,
            "long_term_debt_cr":       borrow,
        })

    logger.info(
        "parse_screener_balance_sheet: %s — %d annual entries (consolidated=%s)",
        symbol, len(output), consolidated,
    )
    return output


def parse_screener_profit_loss(
    symbol: str,
    html: str,
    consolidated: bool = False,
    since_year: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Parse Screener.in #profit-loss section → list of annual dicts.

    Each entry covers a fiscal year-end (March 31) and contains P&L fields
    sufficient to compute revenue_growth_3y_cagr, profit_margin_trend, and
    earnings_consistency primitives.

    Screener reports all figures in ₹ Crore — no unit conversion needed.
    Column labels are "Mar 2018" etc.; converted to ISO "2018-03-31".
    Returns [] if the section is absent or no parseable rows are found.
    """
    result = _parse_screener_section(html, "profit-loss")
    if not result:
        logger.debug("parse_screener_profit_loss: no #profit-loss section for %s", symbol)
        return []

    col_labels, raw_table = result

    def _row(*keys: str) -> list[Optional[float]]:
        for k in keys:
            for label, vals in raw_table.items():
                if k in label:
                    return vals
        return [None] * len(col_labels)

    sales_vals        = _row("sales")
    expenses_vals     = _row("expenses")
    op_profit_vals    = _row("operating profit")
    other_income_vals = _row("other income")
    interest_vals     = _row("interest")
    dep_vals          = _row("depreciation")
    pbt_vals          = _row("profit before tax")
    pat_vals          = _row("net profit")
    eps_vals          = _row("eps in rs", "eps")

    output: list[dict[str, Any]] = []
    for i, label in enumerate(col_labels):
        period_end = _screener_quarter_label_to_date(label)
        if not period_end:
            continue
        try:
            year = int(period_end[:4])
        except ValueError:
            continue
        if since_year and year < since_year:
            continue

        def _v(vals: list, idx: int = i) -> Optional[float]:
            return vals[idx] if idx < len(vals) else None

        revenue = _v(sales_vals)
        pat     = _v(pat_vals)
        # Skip completely empty years (all key fields null)
        if revenue is None and pat is None and _v(eps_vals) is None:
            continue

        output.append({
            "period_end":           period_end,
            "period_type":          "annual",
            "consolidated":         consolidated,
            "revenue_from_ops_cr":  revenue,
            "total_expenses_cr":    _v(expenses_vals),
            "ebitda_cr":            _v(op_profit_vals),
            "other_income_cr":      _v(other_income_vals),
            "finance_costs_cr":     _v(interest_vals),
            "depreciation_cr":      _v(dep_vals),
            "pbt_cr":               _v(pbt_vals),
            "pat_cr":               pat,
            "eps_basic":            _v(eps_vals),
        })

    logger.info(
        "parse_screener_profit_loss: %s — %d annual entries (consolidated=%s, since_year=%s)",
        symbol, len(output), consolidated, since_year,
    )
    return output


def parse_screener_shareholding(
    symbol: str,
    html: str,
) -> list[dict[str, Any]]:
    """Parse Screener.in #shareholding section → list of quarterly dicts.

    Each entry covers a quarter-end date and contains:
      period_end, promoter_pct, fii_pct, dii_pct, public_pct.

    Values are percentages (0–100).
    Returns [] if the section is absent or cannot be parsed.
    """
    result = _parse_screener_section(html, "shareholding")
    if not result:
        logger.debug("parse_screener_shareholding: no #shareholding section for %s", symbol)
        return []

    col_labels, raw_table = result

    def _row(*keys: str) -> list[Optional[float]]:
        for k in keys:
            for label, vals in raw_table.items():
                if k in label:
                    return vals
        return [None] * len(col_labels)

    promoter_vals = _row("promoters")
    fii_vals      = _row("fiis", "fpis", "foreign")
    dii_vals      = _row("diis")
    public_vals   = _row("public")

    output: list[dict[str, Any]] = []
    for i, label in enumerate(col_labels):
        period_end = _screener_quarter_label_to_date(label)
        if not period_end:
            continue

        def _v(vals: list) -> Optional[float]:
            return vals[i] if i < len(vals) else None

        output.append({
            "period_end":   period_end,
            "promoter_pct": _v(promoter_vals),
            "fii_pct":      _v(fii_vals),
            "dii_pct":      _v(dii_vals),
            "public_pct":   _v(public_vals),
        })

    logger.info(
        "parse_screener_shareholding: %s — %d quarterly entries",
        symbol, len(output),
    )
    return output


def parse_nse_xbrl_json(symbol: str, xbrl_text: str) -> Optional[dict[str, Any]]:
    """Parse NSE's structured XBRL comparator JSON response directly (no LLM needed)."""
    try:
        data = json.loads(xbrl_text)
    except Exception:
        return None

    rows = data if isinstance(data, list) else data.get("data", data.get("result", []))
    if not rows:
        return None

    # NSE XBRL comparator returns rows keyed by metric name
    # Latest quarter is usually rows[0]
    def _get(key: str) -> Optional[float]:
        for row in rows:
            if isinstance(row, dict):
                v = row.get(key)
                if v is not None:
                    try:
                        return float(str(v).replace(",", ""))
                    except (ValueError, TypeError):
                        pass
        return None

    return {
        "period_end":            None,  # to be filled by caller from event_calendar
        "consolidated":          False,
        "audited":               None,
        "revenue_from_ops_cr":   _get("totalIncome") or _get("revenue"),
        "total_income_cr":       _get("totalIncome"),
        "total_expenses_cr":     _get("totalExpenses"),
        "ebitda_cr":             _get("ebitda"),
        "pbt_cr":                _get("pbt"),
        "tax_expense_cr":        _get("tax"),
        "pat_cr":                _get("pat") or _get("netProfit"),
        "eps_basic":             _get("eps") or _get("basicEps"),
        "eps_diluted":           _get("dilutedEps"),
        "interest_earned_cr":    _get("interestEarned"),
        "interest_expended_cr":  _get("interestExpended"),
    }
