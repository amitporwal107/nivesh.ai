"""Custom NSDL Consolidated Account Statement (eCAS) extractor.

Reads an NSDL eCAS PDF *directly* and extracts every holding using the
statement's own authoritative ``Value in `` column, then reconciles the
result against the statement's printed **Portfolio Composition** table and
per-account sub-totals.

Why this exists
---------------
The ``casparser`` library mis-aligns columns on NSDL holding rows that carry
an interleaved ``of which Pledged / Unconfirmed Pledge`` sub-line: it reads the
pledged quantity as the NAV and shifts every following column, silently losing
~25-35 % of portfolio value on statements with demat-MF / SGB / folio holdings.
It also fails to populate the folio ``Current Value`` column (returns 0) and
drops Sovereign Gold Bonds and Preference Shares entirely. See
``docs/open_bugs.md`` and the reconciliation evidence in the CAS test suite.

This extractor is intentionally narrow — it understands exactly the NSDL eCAS
layout (sectioned by demat account, then by asset class) and nothing else. It
returns holdings in the internal shape used by ``helpers.parsing.save_holdings``
plus a ``reconciliation`` block the caller MUST check before persisting:
parsing that does not reconcile to the printed totals is treated as a failure,
never silently accepted.

Public entry point: ``extract_nsdl_cas(pdf_bytes, password) -> ExtractResult``.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── Lexical patterns ──────────────────────────────────────────────────
# Indian ISIN: "IN" + 10 alphanumerics (e.g. INE002A01018, INF179K01830,
# IN0020210129). Anchored to the start of a (stripped) line — every holding
# row begins with its ISIN.
_ISIN = re.compile(r"^(IN[A-Z0-9]{10})\b")
# A signed Indian-formatted number: 14,85,789.00 / -961.96 / 500 / 2.23
_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
# A maturity / allotment date embedded mid-row (SGB rows): 17-Aug-2029
_DATE = re.compile(r"\d{1,2}-[A-Za-z]{3}-\d{4}")
# Section header lines look like "Equities (E)" / "Mutual Fund Folios (F)" —
# a label followed by a parenthesised class code and *nothing else*. The
# Portfolio Composition rows look like "Equities (E) 17,67,935.64 14.60%",
# so requiring end-of-line after the code separates headers from that table.
_SECTION = re.compile(r"^[A-Za-z][A-Za-z &/]*\(([A-Z]{1,3})\)$")
# Composition row: "Equities (E) 17,67,935.64 14.60%"
_COMPOSITION = re.compile(r"^[A-Za-z][A-Za-z &/]*\(([A-Z]{1,3})\)\s+([\d,]+\.\d{2})\b")
# "Monthly movement of your Consolidated Portfolio Value" table row, e.g.
# "MAY 2025 1,11,35,534.55 NA NA" / "JUN 2025 1,13,59,376.19 +223841.64 +2.01".
# Only this table has a 3-letter month + 4-digit year + rupee value at line start,
# so it's captured deterministically here — no OpenAI Vision call needed. Mirrors
# the {month, value_rs} shape services.cas_summary_vision used to return.
_MONTH_ROW = re.compile(
    r"^(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+(\d{4})\s+([\d,]+\.\d{2})\b"
)
# A line that signals the holdings region has ended and the per-account
# Transactions statement has begun. Detected at LINE granularity (not page):
# on the last holdings page the folio "Total" row, the folio tail rows, and
# the "Transactions" header all share a page, so a page-level break would drop
# the folios printed above the header.
def _is_txn_start(line: str) -> bool:
    return (
        line == "Transactions"
        or line.startswith("Summary of Transactions")
        or line.startswith("Statement of Transaction")
        or "Order No" in line
        or "Opening Closing" in line
    )

# NSDL asset-class code → our internal asset_type. The folio (F) and demat
# MF (M) codes both map to mutual_fund; ETF / gold are refined per-name below.
_CLASS_TO_TYPE = {
    "E": "equity",
    "P": "equity",       # preference shares — equity-like; tiny in practice
    "M": "mutual_fund",
    "F": "mutual_fund",
    "SGB": "gold",
    "G": "bond",         # government securities
    "C": "bond",         # corporate bonds
    "I": "other", "S": "other", "Z": "bond", "A": "other",
    "O": "other", "N": "other", "SD": "other", "SF": "other",
}


@dataclass
class Holding:
    name: str
    isin: str
    nsdl_class: str          # E / P / M / SGB / F / ... (for reconciliation)
    asset_type: str          # our taxonomy: equity / mutual_fund / etf / gold / bond
    quantity: float
    current_price: float     # market price / current NAV per unit
    buy_price: float         # avg cost per unit where the statement provides it, else current_price
    value: float             # the statement's authoritative "Value in `" column
    cost_basis: Optional[float] = None  # total invested (folios only); None when unknown
    account: str = ""        # owning demat account / "Mutual Fund Folios"
    folio: str = ""

    def as_holding_dict(self) -> dict:
        """Shape consumed by helpers.parsing.save_holdings."""
        return {
            "name": self.name,
            "ticker": self.isin,
            "asset_type": self.asset_type,
            "quantity": round(self.quantity, 4),
            "buy_price": round(self.buy_price, 4),
            "current_price": round(self.current_price, 4),
            "sector": "",
            "source": "nsdl_cas",
        }


@dataclass
class ExtractResult:
    holdings: list[Holding] = field(default_factory=list)
    composition: dict[str, float] = field(default_factory=dict)   # class code → printed value
    grand_total: Optional[float] = None
    investor_name: str = ""
    statement_date: str = ""
    monthly_values: list = field(default_factory=list)   # [{month, value_rs}] portfolio-value trend
    reconciliation: dict = field(default_factory=dict)

    @property
    def reconciled(self) -> bool:
        return bool(self.reconciliation.get("ok"))


def _f(s: str) -> float:
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _nums(line: str) -> list[float]:
    """All signed numbers on a line, commas stripped, dates removed first."""
    cleaned = _DATE.sub(" ", line)
    return [_f(m.group()) for m in _NUM.finditer(cleaned)]


def _refine_type(nsdl_class: str, name: str) -> str:
    base = _CLASS_TO_TYPE.get(nsdl_class, "other")
    low = name.lower()
    if nsdl_class in ("M", "F"):
        if "gold" in low:
            return "gold"
        if "etf" in low or "bees" in low or "exchange traded" in low:
            return "etf"
    return base


def _parse_folio_row(nums: list[float], name: str, isin: str) -> Optional[Holding]:
    """Parse a Mutual Fund Folio (F) row, robust to NSDL's folio layout drift.

    Across statement vintages the folio table appears as any of:
      [Folio, Units, NAV, Value]                                   (older)
      [Folio, Units, AvgCost, TotalCost, NAV, Value, P/L]          (Apr-2026+)
      [Folio, Units, AvgCost, TotalCost, NAV, Value, P/L, Return%] (some rows)
    and the trailing Return% is present only on rows where it's non-NA, so the
    column count varies *within a single statement*.

    Rather than anchor to a fixed offset, locate the Value column structurally:
    it is the RIGHTMOST column equal to ``units × NAV``. Cost columns satisfy
    ``TotalCost = units × AvgCost`` and therefore appear to its left; P/L and
    Return% satisfy neither relation. This pins Value (and, when present, the
    cost basis) regardless of layout.
    """
    if not nums or len(nums) < 4:
        return None

    def approx(a: float, b: float, scale: float) -> bool:
        return abs(a - b) <= max(1.0, 0.01 * abs(scale))

    n = nums
    # Hypotheses are anchored from the RIGHT (the trailing financial columns
    # are clean; the leading folio-no and any digits embedded in the fund name
    # — e.g. "NIFTY50" — sit further left and must not be counted as Units).
    # Accept the first whose internal relations hold:
    #   value ≈ units × nav   and (when cost columns exist)  pnl ≈ value − total
    # 1) full + trailing Return%: [.. Units Avg Total NAV Value PnL Return]
    if len(n) >= 7:
        units, avg, total, nav, value, pnl = n[-7], n[-6], n[-5], n[-4], n[-3], n[-2]
        if approx(value, units * nav, value) and approx(pnl, value - total, value):
            return Holding(name, isin, "F", _refine_type("F", name),
                           units, nav, avg or nav, value, cost_basis=total)
    # 2) full, no Return%: [.. Units Avg Total NAV Value PnL]
    if len(n) >= 6:
        units, avg, total, nav, value, pnl = n[-6], n[-5], n[-4], n[-3], n[-2], n[-1]
        if approx(value, units * nav, value) and approx(pnl, value - total, value):
            return Holding(name, isin, "F", _refine_type("F", name),
                           units, nav, avg or nav, value, cost_basis=total)
    # 3) simple legacy: [.. Units NAV Value]
    units, nav, value = n[-3], n[-2], n[-1]
    if units <= 0:
        return Holding(name, isin, "F", _refine_type("F", name), 0.0, 0.0, 0.0, 0.0)
    if approx(value, units * nav, value):
        return Holding(name, isin, "F", _refine_type("F", name), units, nav, nav, value)
    logger.warning("nsdl-cas: unreconcilable folio row, skipped: %s %s", isin, n[-6:])
    return None


def _parse_holding_line(line: str, klass: str) -> Optional[Holding]:
    """Parse one ISIN-anchored holding row for the given NSDL class.

    Columns are read from the RIGHT because the leading name/symbol text is
    variable-width and may itself contain digits, whereas the trailing numeric
    columns are fixed per asset class. The pledged-quantity sub-line that trips
    up casparser lives on a *separate* text line and never reaches here.
    """
    m = _ISIN.match(line)
    if not m:
        return None
    isin = m.group(1)
    rest = line[m.end():].strip()
    nums = _nums(rest)
    # Strip the ISIN's own trailing digits should the regex under-match — but
    # _ISIN consumes the full 12-char code, so `rest` is name + columns only.
    name_part = _NUM.sub("", _DATE.sub("", rest)).strip(" .-")
    name = re.sub(r"\s{2,}", " ", name_part) or isin

    see_note = "See Note" in rest

    try:
        if klass in ("E", "P"):
            # [FaceValue, Shares, MarketPrice, Value]  (MarketPrice absent → "See Note")
            if see_note or len(nums) < 4:
                units, value = nums[-2], nums[-1]
                price = value / units if units else 0.0
            else:
                units, price, value = nums[-3], nums[-2], nums[-1]
            return Holding(name, isin, klass, _refine_type(klass, name),
                           units, price, price, value)

        if klass == "M":
            # [No. of Units, NAV, Value]
            units, nav, value = nums[-3], nums[-2], nums[-1]
            return Holding(name, isin, klass, _refine_type(klass, name),
                           units, nav, nav, value)

        if klass == "SGB":
            # [Coupon, (date), No. of Units, FaceValue/Unit, MarketPrice/Unit, Value]
            units, _face, price, value = nums[-4], nums[-3], nums[-2], nums[-1]
            return Holding(name, isin, klass, _refine_type(klass, name),
                           units, price, price, value)

        if klass == "F":
            return _parse_folio_row(nums, name, isin)

        if klass in ("G", "C", "Z"):
            # bond-like: [..., Value] — take last as value, second-last as price
            value = nums[-1]
            price = nums[-2] if len(nums) >= 2 else 0.0
            units = nums[-3] if len(nums) >= 3 else 0.0
            return Holding(name, isin, klass, _refine_type(klass, name),
                           units, price, price, value)
    except IndexError:
        logger.warning("nsdl-cas: malformed %s row, skipped: %s", klass, line[:80])
        return None
    return None


def extract_nsdl_cas(pdf_bytes: bytes, password: str = "") -> ExtractResult:
    """Extract + reconcile an NSDL eCAS PDF. Never raises on a bad row; the
    caller checks ``result.reconciled`` / ``result.reconciliation`` and refuses
    to persist a statement that does not reconcile to its printed totals."""
    import pdfplumber

    res = ExtractResult()
    current_class: Optional[str] = None
    current_account = ""
    in_holdings = False

    stop = False
    with pdfplumber.open(io.BytesIO(pdf_bytes), password=password) as pdf:
        for page in pdf.pages:
            if stop:
                break
            text = page.extract_text() or ""
            for raw in text.split("\n"):
                line = raw.strip()
                if not line:
                    continue
                if in_holdings and _is_txn_start(line):
                    stop = True
                    break  # reached the Transactions section — holdings are done

                # Portfolio-value trend table (captured in this same pass — replaces
                # the OpenAI Vision summary call on the NSDL path).
                mrow = _MONTH_ROW.match(line)
                if mrow:
                    res.monthly_values.append({
                        "month": f"{mrow.group(1).title()} {mrow.group(2)}",
                        "value_rs": _f(mrow.group(3)),
                    })
                    continue

                # Grand total (summary page). Statement vintages label it either
                # "YOUR CONSOLIDATED PORTFOLIO VALUE ` ..." or "Grand Total ...".
                if res.grand_total is None and (
                    line.startswith("YOUR CONSOLIDATED PORTFOLIO VALUE")
                    or line.startswith("Grand Total")
                ):
                    gt = _nums(line)
                    if gt:
                        res.grand_total = gt[-1]
                if line.startswith("Statement for the period"):
                    mdate = re.search(r"to (\d{1,2}-[A-Za-z]{3}-\d{4})", line)
                    if mdate:
                        res.statement_date = mdate.group(1)

                # Portfolio Composition table (reconciliation target)
                comp = _COMPOSITION.match(line)
                if comp:
                    res.composition[comp.group(1)] = _f(comp.group(2))
                    continue

                # Account header
                if line.endswith("Demat Account") or line == "Mutual Fund Folios":
                    current_account = line
                    in_holdings = True
                    current_class = None
                    continue

                # Section header ("Equities (E)" etc.) — bare, no trailing value
                sec = _SECTION.match(line)
                if sec:
                    current_class = sec.group(1)
                    in_holdings = True
                    continue

                # Holding row
                if current_class and _ISIN.match(line):
                    h = _parse_holding_line(line, current_class)
                    if h:
                        h.account = current_account
                        res.holdings.append(h)

    res.reconciliation = _reconcile(res)
    return res


def _reconcile(res: ExtractResult, tol_abs: float = 1.0, tol_pct: float = 0.005) -> dict:
    """Compare extracted per-class value sums against the printed composition.

    A class passes if the extracted sum is within ``tol_abs`` rupees OR
    ``tol_pct`` of the printed value. ``ok`` is True only when every non-zero
    printed class reconciles AND the grand total reconciles.
    """
    by_class: dict[str, float] = {}
    for h in res.holdings:
        by_class[h.nsdl_class] = by_class.get(h.nsdl_class, 0.0) + h.value

    per_class = {}
    all_ok = True
    for code, printed in res.composition.items():
        if printed == 0:
            continue
        got = round(by_class.get(code, 0.0), 2)
        diff = round(got - printed, 2)
        ok = abs(diff) <= tol_abs or abs(diff) <= printed * tol_pct
        per_class[code] = {"printed": printed, "extracted": got, "diff": diff, "ok": ok}
        all_ok = all_ok and ok

    extracted_total = round(sum(h.value for h in res.holdings), 2)
    gt = res.grand_total or 0.0
    total_diff = round(extracted_total - gt, 2)
    total_ok = abs(total_diff) <= max(tol_abs, gt * tol_pct)

    return {
        "ok": all_ok and total_ok,
        "grand_total_printed": gt,
        "grand_total_extracted": extracted_total,
        "grand_total_diff": total_diff,
        "per_class": per_class,
        "holdings_count": len(res.holdings),
    }
