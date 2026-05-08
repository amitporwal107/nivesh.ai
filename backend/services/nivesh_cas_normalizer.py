"""NIVESH_CAS_PARSER — Document AI → Claude/CAS-Connect schema normalizer.

Takes the raw `{text, tables}` output from Google Document AI (see
`services.nivesh_cas_parser`) and reshapes it into the same JSON schema
that `services.claude_cas_parser.EXTRACTION_PROMPT` produces. Once
normalised, the output flows through the *same* `claude_cas_mapper.
map_to_internal()` pipeline as Claude Vision parses — so all downstream
holdings/transactions/scoring code is reused 1:1.

Output shape (subset that the mapper needs):
    {
      "statement_info":   {...},
      "investor_info":    {...},
      "portfolio_summary": {"total_value_inr": .., "asset_allocation": [..]},
      "portfolio_value_trend": [..],
      "accounts": [..],
      "holdings": {
          "equities": [..], "preference_shares": [..],
          "sovereign_gold_bonds": [..],
          "mutual_funds_demat": [..], "mutual_fund_folios": [..]
      },
      "transactions": {
          "demat_transactions": [..],
          "mutual_fund_transactions": [..]
      }
    }
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Regex patterns ──────────────────────────────────────────────────────
# Indian ISIN = 12 chars total: "IN" + 10-char body
ISIN_EQUITY_RE = re.compile(r"\bINE[A-Z0-9]{9}\b")
ISIN_MF_RE = re.compile(r"\bINF[A-Z0-9]{9}\b")
ISIN_SGB_RE = re.compile(r"\bIN0020\d{6}\b")
ISIN_PREF_RE = re.compile(r"\bINE[A-Z0-9]{6}04\d\b")  # preference share ISINs end with 04x
ANY_ISIN_RE = re.compile(r"\bIN[A-Z0-9]{10}\b")
PAN_RE = re.compile(r"\b([A-Z]{5}\d{4}[A-Z]|[A-Z]{2}XXXXX\d?[A-Z])\b")
FOLIO_NUM_RE = re.compile(r"^\d{6,15}$")
UCC_RE = re.compile(r"\bMF[A-Z]{3,5}\d{3,5}\b|\b1\d{4,5}\b")
DATE_DDMMMYYYY_RE = re.compile(r"\b(\d{1,2})[-/ ]([A-Za-z]{3})[-/ ](\d{4})\b")
DATE_DDMMYYYY_RE = re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b")
PERIOD_RE = re.compile(
    r"period\s+from\s+(\d{1,2}[-/ ][A-Za-z]{3}[-/ ]\d{4})\s+to\s+(\d{1,2}[-/ ][A-Za-z]{3}[-/ ]\d{4})",
    re.I,
)
# CDSL CAS uses DD-MM-YYYY: "Period: 01-02-2026 to 28-02-2026" or "From 01/02/2026 To 28/02/2026"
PERIOD_DDMMYYYY_RE = re.compile(
    r"(?:period|from)[:\s]+(\d{1,2}[-/]\d{1,2}[-/]\d{4})\s+(?:to|-)\s+(\d{1,2}[-/]\d{1,2}[-/]\d{4})",
    re.I,
)
MONTH_RE = re.compile(r"^([A-Z]{3})\s+(\d{4})$")
# CDSL BO ID: 16-digit account number, sometimes printed with spaces every 4 digits
BO_ID_RE = re.compile(r"\bBO\s*ID[:\s]*([0-9 ]{12,20})\b", re.I)


# ── Helpers ─────────────────────────────────────────────────────────────
def _f(v, default: float = 0.0) -> float:
    """Parse a possibly Indian-comma-formatted number string to float."""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return default
    # Multi-line cells: take the first non-empty numeric-looking line.
    if "\n" in s:
        for line in s.split("\n"):
            line = line.strip()
            if line and re.search(r"\d", line):
                s = line
                break
    # Strip currency symbols, commas, percent
    s = s.replace("\u20b9", "").replace("Rs.", "").replace("INR", "").replace("₹", "")
    s = s.replace(",", "").replace(" ", "")
    s = s.replace("%", "")
    # Drop trailing notes like "Cr" / "Lakh"
    s = re.sub(r"[A-Za-z]+$", "", s).strip()
    try:
        return float(s) if s and s not in ("-", "+", ".", "NA", "ΝΑ") else default
    except (TypeError, ValueError):
        return default


def _i(v, default: int = 0) -> int:
    return int(_f(v, default))


def _clean(s: Optional[str]) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s).replace("\n", " ")).strip()


def _split_lines(s: Optional[str]) -> List[str]:
    if not s:
        return []
    return [ln.strip() for ln in str(s).split("\n") if ln.strip()]


def _iso_date(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = str(s).strip()
    m = DATE_DDMMMYYYY_RE.search(s)
    if not m:
        return None
    try:
        dt = datetime.strptime(f"{m.group(1)} {m.group(2).title()} {m.group(3)}", "%d %b %Y")
        return dt.date().isoformat()
    except ValueError:
        return None


def _has_isin(s: str, pat: re.Pattern) -> Optional[str]:
    if not s:
        return None
    m = pat.search(s)
    return m.group() if m else None


def _first_isin(s: str) -> Optional[str]:
    if not s:
        return None
    m = ANY_ISIN_RE.search(s)
    return m.group() if m else None


# ── Depository detection ──────────────────────────────────────────────
# CDSL markers: "Central Depository Services", "BO ID", "CDSL" header text,
# "Depository: CDSL", or "Demat A/c No:" without an "NSDL ID" anywhere in
# the same document. We scan the first ~4000 chars (cover page).
_CDSL_MARKERS = re.compile(
    r"\bCDSL\b|Central\s+Depository\s+Services|\bBO\s*ID\b|\bDepository[:\s]+CDSL\b",
    re.I,
)
_NSDL_MARKERS = re.compile(r"\bNSDL\b|National\s+Securities\s+Depository", re.I)


def _detect_depository(text: str) -> str:
    """Return 'CDSL' if CDSL markers dominate the cover page, else 'NSDL'.

    NSDL is the default because the original parser was NSDL-only, and any
    consolidated CAS PDF contains NSDL boilerplate even when the demat side
    is CDSL. We only flip to CDSL when CDSL markers appear and the NSDL ID
    pattern is absent — i.e. it's a CDSL-only statement.
    """
    if not text:
        return "NSDL"
    head = text[:8000]
    has_cdsl = bool(_CDSL_MARKERS.search(head))
    # Strong NSDL signal = an actual "NSDL ID: <digits>" header line.
    has_nsdl_id = bool(re.search(r"NSDL\s*ID[:\s]+\d+", head, re.I))
    if has_cdsl and not has_nsdl_id:
        return "CDSL"
    return "NSDL"


# ── Statement / investor extraction (from text) ────────────────────────
def _extract_investor_info(text: str, depository: str = "NSDL") -> Dict[str, Any]:
    info: Dict[str, Any] = {"name": None, "pan": None, "address": None}
    if not text:
        return info

    # PAN — typically "PAN:AMXXXXXX7E" or full PAN
    m = re.search(r"PAN[:\s]+([A-Z]{2}X{4,7}[0-9A-Z]{1,3}|[A-Z]{5}\d{4}[A-Z])", text)
    if m:
        info["pan"] = m.group(1)

    # Name — usually followed by "(PAN:..." or appears in "In the Single Name of\n<NAME>"
    m = re.search(r"In the Single Name of[\s\n]+([A-Z][A-Z .]{2,80}?)\s*\(?PAN", text)
    if m:
        info["name"] = m.group(1).strip()
    elif depository == "CDSL":
        # CDSL: "BO Name: <NAME>" or "Sole/First Holder: <NAME>" or after BO ID block
        m = re.search(r"(?:BO\s*Name|Sole(?:\s*/\s*First)?\s*Holder)[:\s]+([A-Z][A-Z .]{2,80})", text)
        if m:
            info["name"] = m.group(1).strip()
        else:
            m = re.search(r"BO\s*ID[:\s]*[0-9 ]{12,20}\s*\n\s*([A-Z][A-Z .]{3,80})\n", text)
            if m:
                info["name"] = m.group(1).strip()
    else:
        # Fallback: look for "Dear <Name>" at start of greeting
        m = re.search(r"NSDL ID:[\s\d]+\n([A-Z][A-Z .]{3,80})\n", text)
        if m:
            info["name"] = m.group(1).strip()

    # Address — between name and "PINCODE: nnnnnn" (NSDL form)
    m = re.search(
        r"NSDL ID:[\s\d]+\n([A-Z][A-Z .]{3,80})\n([\s\S]+?PINCODE[:\s]+\d{6})",
        text,
    )
    if m:
        info["address"] = re.sub(r"\s+", " ", m.group(2)).strip()
    elif depository == "CDSL":
        # CDSL has "Address:" or address block after BO Name
        m = re.search(r"Address[:\s]+([\s\S]{10,300}?\d{6})", text)
        if m:
            info["address"] = re.sub(r"\s+", " ", m.group(1)).strip()

    return info


def _extract_statement_info(text: str, depository: Optional[str] = None) -> Dict[str, Any]:
    if depository is None:
        depository = _detect_depository(text)
    info: Dict[str, Any] = {
        "depository": depository,
        "id": None,
        "statement_type": "Consolidated Account Statement",
        "period": None,
    }
    if depository == "CDSL":
        # BO ID may be printed with spaces; normalise to digits-only.
        m = BO_ID_RE.search(text)
        if m:
            info["id"] = re.sub(r"\D", "", m.group(1))
    else:
        m = re.search(r"NSDL ID:\s*(\d+)", text)
        if m:
            info["id"] = m.group(1)

    # Period: prefer DD-MMM-YYYY (NSDL), then DD-MM-YYYY (CDSL), then "month of"
    m = PERIOD_RE.search(text)
    if m:
        info["period"] = f"{m.group(1)} to {m.group(2)}"
    else:
        m2 = PERIOD_DDMMYYYY_RE.search(text)
        if m2:
            info["period"] = f"{m2.group(1)} to {m2.group(2)}"
        else:
            m3 = re.search(r"for the month of ([A-Z][a-z]+ \d{4})", text)
            if m3:
                info["period"] = m3.group(1)
    return info


def _extract_total_value(text: str) -> float:
    # Look for "TOTAL\n1,23,28,692.85" or "Grand Total\n..."
    m = re.search(r"Grand Total\s*[\n\s]+([\d,]+\.\d{2})", text)
    if m:
        return _f(m.group(1))
    m = re.search(r"YOUR CONSOLIDATED PORTFOLIO VALUE\s*[\n\s\*₹]*([\d,]+\.\d{2})", text)
    if m:
        return _f(m.group(1))
    return 0.0


# ── Table type classifiers ─────────────────────────────────────────────
def _row_text(row: List[str]) -> str:
    return " ".join(str(c or "") for c in row)


def _classify_table(table: List[List[str]]) -> str:
    """Return a short label describing what this table contains."""
    if not table:
        return "empty"
    n_cols = max((len(r) for r in table), default=0)
    if n_cols == 0:
        return "empty"
    # Scan first ~6 rows so a continuation table whose first row is a
    # pledge-note fragment still gets classified by its body.
    sample_blob = " \n ".join(_row_text(r) for r in table[:6])
    blob = _row_text(table[0])
    if not table:
        return "unknown"

    # Signature scan over the sampled rows
    has_inf = bool(ISIN_MF_RE.search(sample_blob))
    has_ine = bool(ISIN_EQUITY_RE.search(sample_blob))
    has_sgb = bool(ISIN_SGB_RE.search(sample_blob))

    # CDSL header signatures (check before NSDL equity/folio/demat fallbacks
    # because CDSL tables are wider but have distinct header keywords).
    sample_lower = sample_blob.lower()
    cdsl_eq_header = (
        "security" in sample_lower
        and ("current" in sample_lower or "free bal" in sample_lower)
        and "folio" not in sample_lower
        and "scheme" not in sample_lower
    )
    cdsl_mf_header = (
        "scheme" in sample_lower
        and "folio" in sample_lower
        and ("valuation" in sample_lower or "invested" in sample_lower or "nav" in sample_lower)
    )
    if cdsl_eq_header and has_ine and n_cols >= 5:
        return "cdsl_equity"
    if cdsl_mf_header and has_inf and n_cols >= 5:
        return "cdsl_mf_folio"

    # Asset allocation: 3 cols, percentage in col 2
    if n_cols == 3 and any("%" in str(r[-1] or "") for r in table[:5]):
        if any(re.search(r"Equit|Mutual|Bond|Gold|Govern|Securit", str(r[0] or ""), re.I) for r in table[:5]):
            return "asset_allocation"

    # Portfolio value trend: 5 cols, month names in col 0
    if n_cols >= 4 and MONTH_RE.match(_clean(table[0][0])):
        return "portfolio_trend"

    # Accounts table: 4 cols, "Demat Account" / "Mutual Fund Folios" in col 0
    if n_cols == 4 and any(
        re.search(r"Demat Account|Mutual Fund Folio|Insurance|NPS", str(r[0] or ""), re.I)
        for r in table[:8]
    ):
        return "accounts"

    # Mutual fund folio table: ≥10 cols (very wide)
    if n_cols >= 10 and (has_inf or any("MF" in str(r[0] or "") for r in table[:3])):
        return "mf_folios"

    # SGB: 8 cols and ISIN starts with IN0020
    if has_sgb and n_cols >= 7:
        return "sgb"

    # Equity holdings: 6 cols, ISIN INE…
    if has_ine and n_cols == 6:
        return "equity"

    # Preference shares: 5 cols, "Preference" or "SUSPENDED" pattern
    if n_cols == 5 and (
        "preference" in blob.lower() or "suspended" in blob.lower() or "non convertible" in blob.lower()
    ):
        return "preference"

    # Mutual funds in demat: 5 cols, INF ISIN
    if has_inf and n_cols == 5:
        return "mf_demat"

    # MF transactions: 7 cols with "Purchase" / "SIP" / "Redemption" in col 1
    if n_cols == 7 and any(
        re.search(r"Purchase|Redempt|Switch|SIP|Dividend|IDCW|Sell|Buy", str(r[1] or ""), re.I)
        for r in table[:8]
    ):
        return "mf_transactions"

    # Demat transactions: dates in col 0 (DD-MMM-YYYY)
    if any(DATE_DDMMMYYYY_RE.search(str(r[0] or "")) for r in table[:8]):
        return "demat_transactions"

    return "unknown"


# ── Row → record extractors ────────────────────────────────────────────
def _eq_row_to_record(row: List[str]) -> Optional[Dict[str, Any]]:
    """Equity holdings table row.
    Schema seen in CAS:
      col0 = "<ISIN>\\n<NSE_SYMBOL.NSE>" (or just ISIN)
      col1 = "<COMPANY NAME>\\n<pledged note>"
      col2 = face_value
      col3 = num_shares (often duplicated with pledge counts via newlines)
      col4 = market_price
      col5 = value_inr
    """
    if not row or len(row) < 6:
        return None
    isin = _has_isin(str(row[0] or ""), ISIN_EQUITY_RE)
    if not isin:
        return None
    lines0 = _split_lines(row[0])
    stock_symbol = next((l for l in lines0 if l != isin and "." in l), None)
    name_lines = _split_lines(row[1])
    company_name = name_lines[0] if name_lines else ""
    market_price = _f(row[4])
    value_inr = _f(row[5])

    # Document AI sometimes merges 3-4 numbers (held + pledged + dp) into
    # col 3 separated by '\n'. Pick the line that — multiplied by
    # market_price — best matches value_inr; fall back to the first.
    candidate_lines = _split_lines(row[3])
    num_shares = 0
    pledged = 0
    if candidate_lines and market_price > 0 and value_inr > 0:
        target = value_inr / market_price
        best = min(
            candidate_lines,
            key=lambda l: abs(_f(l) - target) if _f(l) > 0 else 1e18,
        )
        num_shares = _i(best)
        pledged_lines = [_i(l) for l in candidate_lines if _i(l) and _i(l) != num_shares]
        pledged = pledged_lines[0] if pledged_lines else 0
    elif candidate_lines:
        num_shares = _i(candidate_lines[0])
        pledged = _i(candidate_lines[1]) if len(candidate_lines) > 1 else 0

    return {
        "isin": isin,
        "stock_symbol": stock_symbol,
        "company_name": company_name.strip(),
        "face_value_inr": _f(row[2]),
        "num_shares": num_shares,
        "pledged_shares": pledged,
        "market_price_inr": market_price,
        "value_inr": value_inr,
    }


def _pref_row_to_record(row: List[str]) -> Optional[Dict[str, Any]]:
    """Preference shares — the 5-column shape:
      col0 = "<COMPANY NAME>\\n<ISIN>\\nSUSPENDED"
      col1 = face_value
      col2 = num_shares
      col3 = market_price
      col4 = value_inr
    """
    if not row or len(row) < 5:
        return None
    blob = str(row[0] or "")
    isin = _has_isin(blob, ISIN_PREF_RE) or _first_isin(blob)
    if not isin:
        return None
    name = _split_lines(row[0])[0] if _split_lines(row[0]) else ""
    return {
        "isin": isin,
        "company_name": name.strip(),
        "face_value_inr": _f(row[1]),
        "num_shares": _i(_split_lines(row[2])[0] if _split_lines(row[2]) else 0),
        "market_price_inr": _f(row[3]),
        "value_inr": _f(row[4]),
        "note": "SUSPENDED" if "suspend" in blob.lower() else None,
    }


def _sgb_row_to_record(row: List[str]) -> Optional[Dict[str, Any]]:
    """SGB row — 8 cols: ISIN | issuer/series | coupon | maturity | units | face | market_per_unit | value
    """
    if not row or len(row) < 7:
        return None
    isin = _has_isin(_row_text(row), ISIN_SGB_RE)
    if not isin:
        return None
    issuer_lines = _split_lines(row[1])
    issuer = issuer_lines[0] if issuer_lines else ""
    series = " ".join(issuer_lines[1:]) if len(issuer_lines) > 1 else None
    return {
        "isin": isin,
        "series": series,
        "issuer": issuer,
        "coupon_rate_pct": _f(row[2]),
        "maturity_date": _iso_date(row[3]),
        "num_units": _i(row[4]),
        "face_value_per_unit_inr": _f(row[5]),
        "market_price_per_unit_inr": _f(row[6]) if len(row) > 6 else 0.0,
        "value_inr": _f(row[7]) if len(row) > 7 else 0.0,
    }


def _mf_demat_row_to_record(row: List[str]) -> Optional[List[Dict[str, Any]]]:
    """Mutual fund (in demat account) — 5 cols. Sometimes Document AI
    merges 2-3 contiguous rows into a single cell (multiple ISINs and
    fund names separated by '\\n' in cols 0-4). We split these out.
    Returns a LIST so the caller can extend its accumulator.
    """
    if not row or len(row) < 5:
        return None
    isin_lines = [l for l in _split_lines(row[0]) if ISIN_MF_RE.match(l)]
    if not isin_lines:
        return None
    fund_lines = [
        l for l in _split_lines(row[1])
        if l and not l.lower().startswith("of which pledged")
    ]
    units_lines = [_f(l) for l in _split_lines(row[2]) if _f(l) > 0]
    nav_lines = [_f(l) for l in _split_lines(row[3]) if _f(l) > 0]
    val_lines = [_f(l) for l in _split_lines(row[4]) if _f(l) > 0]

    out: List[Dict[str, Any]] = []
    for i, isin in enumerate(isin_lines):
        out.append(
            {
                "isin": isin,
                "fund_name": (fund_lines[i] if i < len(fund_lines) else "").strip(),
                "num_units": units_lines[i] if i < len(units_lines) else 0.0,
                "nav_inr": nav_lines[i] if i < len(nav_lines) else 0.0,
                "value_inr": val_lines[i] if i < len(val_lines) else 0.0,
            }
        )
    return out


def _folio_row_to_record(row: List[str]) -> Optional[Dict[str, Any]]:
    """MF folio row — 10-11 cols. Column meaning (from header):
      0  ISIN (+ optional UCC on second line)
      1  UCC (sometimes — when col 0 is just ISIN)
      2  ISIN Description / fund_name
      3  Folio No.
      4  No. of Units
      5  Average Cost Per Unit  (note: Doc AI flips col5↔col6 vs the
                                 printed header order — we auto-correct
                                 below using units × avg ≈ total)
      6  Total Cost
      7  Current NAV per unit
      8  Current Value
      9  Unrealised P/L
      10 Annualised Return %
    Document AI sometimes flattens UCC into col 0 (`ISIN\\nUCC`) yielding
    10 cells instead of 11, OR pads with a trailing empty cell yielding
    11 cells where col 0 is still merged. We detect the layout by
    looking at col 1: if it matches a UCC pattern, layout is "split";
    otherwise it's the merged variant.
    """
    if not row or len(row) < 8:
        return None
    blob = str(row[0] or "")
    isin = _has_isin(blob, ISIN_MF_RE)
    if not isin:
        return None
    lines0 = _split_lines(blob)
    ucc = next((l for l in lines0 if UCC_RE.match(l)), None)

    # Detect layout: split (col 1 = UCC) vs merged (col 1 = fund name)
    col1 = _clean(row[1]) if len(row) > 1 else ""
    is_split = bool(UCC_RE.match(col1))

    if is_split:
        # 0=ISIN, 1=UCC, 2=fund, 3=folio, 4=units, 5=avg, 6=tot, 7=nav, 8=val, 9=pnl, 10=ret
        if len(row) < 10:
            return None
        ucc = ucc or col1
        fund = _split_lines(row[2])[0] if _split_lines(row[2]) else ""
        folio = _clean(row[3])
        units = _f(row[4])
        avg_cost = _f(row[5])
        total_cost = _f(row[6])
        nav = _f(row[7])
        cur_val = _f(row[8])
        pnl = _f(row[9]) if len(row) > 9 else 0.0
        ann_ret = _f(row[10]) if len(row) > 10 else 0.0
    else:
        # 0=ISIN+UCC, 1=fund, 2=folio, 3=units, 4=avg, 5=tot, 6=nav, 7=val, 8=pnl, 9=ret
        fund = col1
        # If fund came multiline pick first non-empty line
        fund_lines = _split_lines(row[1])
        if fund_lines:
            fund = fund_lines[0]
        folio = _clean(row[2])
        units = _f(row[3])
        avg_cost = _f(row[4])
        total_cost = _f(row[5])
        nav = _f(row[6])
        cur_val = _f(row[7])
        pnl = _f(row[8]) if len(row) > 8 else 0.0
        ann_ret = _f(row[9]) if len(row) > 9 else 0.0

    # Sanity check — confirm units × avg ≈ total. If not, swap.
    if units > 0 and total_cost > 0 and avg_cost > 0:
        product = units * avg_cost
        if abs(product - total_cost) / max(total_cost, 1.0) > 0.2:
            if abs(units * total_cost - avg_cost) / max(avg_cost, 1.0) < 0.2:
                total_cost, avg_cost = avg_cost, total_cost

    # Backfill units when Doc AI mangled col 4 — derive from total/avg.
    if units == 0 and total_cost > 0 and avg_cost > 0:
        units = round(total_cost / avg_cost, 4)
    # Backfill units alternatively from current_value/nav.
    if units == 0 and cur_val > 0 and nav > 0:
        units = round(cur_val / nav, 4)

    fund = fund.strip()
    if not fund:
        return None

    # Folio must be all-digits (NSDL folios). Reject when col was misread.
    folio_digits = re.sub(r"\D", "", folio)
    if not folio_digits or len(folio_digits) < 4:
        return None
    folio = folio_digits

    return {
        "isin": isin,
        "fund_name": fund,
        "folio_number": folio,
        "ucc": ucc,
        "amc": _amc_from_fund(fund),
        "num_units": units,
        "total_cost_inr": total_cost,
        "avg_cost_per_unit_inr": avg_cost,
        "current_nav_inr": nav,
        "current_value_inr": cur_val,
        "unrealised_pnl_inr": pnl,
        "annualised_return_pct": ann_ret,
    }


# ── CDSL row extractors ────────────────────────────────────────────────
# CDSL CAS layouts differ from NSDL: equity rows are wider (typically
#   ISIN | Security | Current Qty | Frozen | Pledge | Pledge-Setup |
#   Free Bal | Price | Value
# ) and MF folio rows are narrower (typically
#   ISIN | Scheme Name | Folio No | Units | NAV | Invested | Valuation |
#   PnL | PnL%
# ). The invariant in both: the **last two numeric cells** are
# (price, value) or (NAV, valuation) — same as the legacy `cas_parser.py`
# CDSL extractors. We exploit that to be robust to Doc AI cell merges.


_CDSL_NAME_NOISE = re.compile(
    r"#?\s*EQUITY\s+SHARES?\s+(?:OF\s+)?R[SE]\.?\s*[\d/\-]+\s*(?:EACH|AFTER|WITH|NEW|SUB|SPLIT|CAPITAL|REDUCTION|HAVING|PREMIUM)?[^\n]*",
    re.I,
)


def _cdsl_clean_security_name(blob: str) -> str:
    """Strip CDSL 'EQUITY SHARES OF RS.X EACH' boilerplate; keep first
    alphabetic line that survives.
    """
    if not blob:
        return ""
    cleaned = _CDSL_NAME_NOISE.sub(" ", blob)
    for ln in _split_lines(cleaned):
        # Drop ISIN-only and pure-numeric lines.
        if ANY_ISIN_RE.fullmatch(ln):
            continue
        if re.fullmatch(r"[\d,.\-+/\s%]+", ln):
            continue
        # Drop residual boilerplate fragments.
        if re.fullmatch(r"(EQUITY|SHARES?|FV|EACH|HAVING|PREMIUM|FORMERLY|PRIVATE)\b.*", ln, re.I):
            continue
        return _clean(ln)
    return ""


def _row_numbers(row: List[str]) -> List[float]:
    """Extract every parseable positive number from a row, in cell order
    (cells walked left-to-right, multi-line cells walked top-to-bottom).
    Strips ISIN tokens first — otherwise digit runs inside ISINs (e.g.
    'INF179K01CR2' → 179, 1, 2) leak in and corrupt positional parses.
    """
    out: List[float] = []
    for cell in row:
        if not cell:
            continue
        scrub = ANY_ISIN_RE.sub(" ", str(cell))
        for tok in re.findall(r"-?\d[\d,]*\.?\d*", scrub):
            n = _f(tok)
            if n > 0:
                out.append(n)
    return out


def _cdsl_equity_row_to_record(row: List[str]) -> Optional[Dict[str, Any]]:
    """CDSL equity holdings row.

    Picks the row's ISIN (must be INE…), derives security name from the
    Security cell after stripping 'EQUITY SHARES OF RS.X EACH' noise, and
    treats the **last two positive numbers as (price, value)**. Quantity
    is preferred from the first integer that satisfies qty * price ≈ value
    (within 5%); falls back to round(value / price).
    """
    if not row:
        return None
    blob = _row_text(row)
    # CDSL equity tables occasionally include ETFs (INF ISINs) — accept
    # both prefixes; the caller routes INF rows into mutual_funds_demat.
    isin = _has_isin(blob, ISIN_EQUITY_RE) or _has_isin(blob, ISIN_MF_RE)
    if not isin:
        return None

    # Name: scan all cells, drop ISIN cell, prefer the longest cleaned line.
    name = ""
    for cell in row:
        cs = str(cell or "")
        if ANY_ISIN_RE.search(cs) and len(cs.strip()) <= 14:
            continue
        cand = _cdsl_clean_security_name(cs)
        if len(cand) > len(name):
            name = cand

    nums = _row_numbers(row)
    if len(nums) < 2:
        return None
    value = nums[-1]
    price = nums[-2]
    if price <= 0 or value <= 0:
        return None
    qty = round(value / price)
    # Cross-check: if any leading integer (e.g. "Current Qty") matches
    # value/price, prefer it — protects against Doc AI rounding loss.
    for n in nums[:-2]:
        if n == int(n) and 0 < n < 1_000_000 and abs(n * price - value) / value < 0.05:
            qty = int(n)
            break

    return {
        "isin": isin,
        "stock_symbol": None,
        "company_name": name,
        "face_value_inr": 0.0,  # CDSL CAS rarely surfaces face value as a discrete column
        "num_shares": int(qty),
        "pledged_shares": 0,
        "market_price_inr": price,
        "value_inr": value,
    }


def _cdsl_mf_folio_row_to_record(row: List[str]) -> Optional[Dict[str, Any]]:
    """CDSL MF folio row.

    Distinct from NSDL folios (which always carry an explicit Avg Cost
    and 10+ columns). CDSL folios are typically:
        ISIN | Scheme | Folio | Units | NAV | Invested | Valuation | PnL | PnL%
    Numeric layout: nums = [units, nav, invested, valuation, pnl, pnl%].
    We accept (units, nav, invested, valuation) by position with sanity
    checks; fall back to (nav, valuation) → derive units when only two
    numbers survive the row.
    """
    if not row:
        return None
    blob = _row_text(row)
    isin = _has_isin(blob, ISIN_MF_RE)
    if not isin:
        return None

    # Scheme name: first line of any non-ISIN text cell.
    name = ""
    for cell in row:
        cs = str(cell or "")
        if ANY_ISIN_RE.search(cs) and len(cs.strip()) <= 14:
            continue
        for ln in _split_lines(cs):
            if ANY_ISIN_RE.search(ln):
                continue
            if re.fullmatch(r"[\d,.\-+/\s%]+", ln):
                continue
            if FOLIO_NUM_RE.fullmatch(ln):
                continue
            if len(ln) > len(name):
                name = _clean(ln)
        if name:
            break

    # Folio: first all-digit cell or the digits pulled from a "12345/67" form.
    folio = ""
    for cell in row:
        cs = str(cell or "")
        for ln in _split_lines(cs):
            digits = re.sub(r"\D", "", ln)
            if 6 <= len(digits) <= 15 and not ANY_ISIN_RE.search(ln):
                folio = digits
                break
        if folio:
            break

    nums = _row_numbers(row)
    # Filter folio-shaped integers (>10M, no decimal) — they leak in when
    # the folio cell wasn't isolated.
    filtered = [n for n in nums if not (n == int(n) and n > 10_000_000)]

    units = nav = invested = value = 0.0
    if len(filtered) >= 4:
        units, nav, invested, value = filtered[0], filtered[1], filtered[2], filtered[3]
        # Doc AI sometimes flips Units ↔ Valuation. Re-order if units * nav
        # is wildly off but valuation / nav is plausible.
        if units > 0 and nav > 0 and value > 0:
            if abs(units * nav - value) / max(value, 1.0) > 0.2:
                derived = value / nav
                if derived > 0 and abs(derived - units) / max(units, 1.0) > 0.1:
                    units = round(derived, 4)
    elif len(filtered) >= 2:
        nav = filtered[-2]
        value = filtered[-1]
        units = round(value / nav, 4) if nav > 0 else 0.0

    if value <= 0 or not name or len(name) < 3:
        return None

    avg_cost = round(invested / units, 4) if units > 0 and invested > 0 else nav
    return {
        "isin": isin,
        "fund_name": name,
        "folio_number": folio or None,
        "ucc": None,
        "amc": _amc_from_fund(name),
        "num_units": units,
        "total_cost_inr": invested,
        "avg_cost_per_unit_inr": avg_cost,
        "current_nav_inr": nav,
        "current_value_inr": value,
        "unrealised_pnl_inr": (value - invested) if invested > 0 else 0.0,
        "annualised_return_pct": 0.0,
    }


def _amc_from_fund(name: str) -> str:
    """Best-effort AMC name extraction (mirrors claude_cas_mapper logic)."""
    if not name:
        return ""
    n = name.strip()
    for marker in [" Mutual Fund", " Asset Management", " AMC", " Fund"]:
        idx = n.lower().find(marker.lower())
        if idx > 0:
            return n[:idx].strip()
    parts = n.split()
    return " ".join(parts[:3])


def _mf_txn_row_to_record(
    row: List[str], scheme_ctx: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Mutual fund transaction row — 7 cols:
      col0 = date (DD-MMM-YYYY)
      col1 = description (Purchase / SIP / Redemption / IDCW / Stamp Duty)
      col2 = amount_inr
      col3 = stamp_duty_inr
      col4 = nav_inr
      col5 = price_inr
      col6 = units
    """
    if not row or len(row) < 7:
        return None
    date_iso = _iso_date(row[0])
    if not date_iso:
        return None
    desc = _clean(row[1])
    if not desc:
        return None
    txn_type = _classify_txn(desc)
    return {
        "isin": scheme_ctx.get("isin"),
        "fund_name": scheme_ctx.get("fund_name"),
        "folio_number": scheme_ctx.get("folio_number"),
        "date": date_iso,
        "transaction_type": txn_type,
        "description": desc,
        "amount_inr": _f(row[2]),
        "stamp_duty_inr": _f(row[3]),
        "nav_inr": _f(row[4]),
        "price_inr": _f(row[5]),
        "units": _f(row[6]),
    }


def _classify_txn(desc: str) -> str:
    s = desc.lower()
    if "sip" in s or "systematic" in s:
        return "SIP_PURCHASE"
    if "purchase" in s or "allotment" in s or "investment" in s or "buy" in s:
        return "PURCHASE"
    if "redempt" in s or "redeem" in s or "withdrawal" in s or "sell" in s:
        return "REDEMPTION"
    if "switch in" in s or "switch-in" in s:
        return "SWITCH_IN"
    if "switch out" in s or "switch-out" in s:
        return "SWITCH_OUT"
    if "dividend" in s or "idcw" in s:
        return "DIVIDEND"
    if "stamp" in s or "stt" in s or "tds" in s:
        return "STAMP_DUTY"
    return "OTHER"


# ── Asset allocation / trend / accounts ────────────────────────────────
def _parse_asset_allocation(table: List[List[str]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in table:
        if not r or len(r) < 3:
            continue
        cls = _clean(r[0])
        if not cls or cls.upper() == "TOTAL":
            continue
        out.append(
            {
                "asset_class": cls,
                "value_inr": _f(r[1]),
                "percentage": _f(r[2]),
            }
        )
    return out


def _parse_portfolio_trend(table: List[List[str]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in table:
        if not r or len(r) < 2:
            continue
        m = MONTH_RE.match(_clean(r[0]))
        if not m:
            continue
        out.append(
            {
                "month": m.group(1),
                "year": int(m.group(2)),
                "value_inr": _f(r[1]),
                "change_inr": _f(r[2]) if len(r) > 2 else 0.0,
                "change_pct": _f(r[3]) if len(r) > 3 else 0.0,
            }
        )
    return out


def _parse_accounts(table: List[List[str]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in table:
        if not r or len(r) < 4:
            continue
        type_str = _clean(r[0])
        if not type_str or type_str.lower() in ("total", "grand total"):
            continue
        broker_blob = str(r[1] or "")
        broker_lines = _split_lines(broker_blob)
        broker = broker_lines[0] if broker_lines else ""
        dp_id = None
        client_id = None
        m = re.search(r"DP\s*ID[:\s]*([A-Z0-9]+)", broker_blob)
        if m:
            dp_id = m.group(1)
        m = re.search(r"Client\s*ID[:\s]*(\d+)", broker_blob)
        if m:
            client_id = m.group(1)
        out.append(
            {
                "type": type_str,
                "broker": broker.strip(),
                "dp_id": dp_id,
                "client_id": client_id,
                "value_inr": _f(r[3]),
            }
        )
    return out


# ── Folio context for transactions ─────────────────────────────────────
def _detect_scheme_context(text: str, table_idx: int, all_tables: List[List[List[str]]]) -> Dict[str, Any]:
    """MF transaction tables don't repeat the ISIN/folio header in each
    row; instead a header line above the table reads:
       'ISIN: INF179K01WA6 - HDFC Mutual Fund - HDFC Balanced Advantage - Folio No - 35007279'
    We look at any sibling table with a single row that contains this
    pattern (table 29 in the sample) — but since Document AI doesn't
    preserve table-to-text positional anchors cleanly, we fall back to
    pulling all 'ISIN: ... Folio No - ...' headers from the text and
    using the closest one heuristically.
    """
    # Rather than positional lookup, return a placeholder — the calling
    # code will scan the text for ISIN headers and post-process txn ISINs.
    return {}


def _extract_mf_txn_headers(text: str) -> List[Dict[str, Any]]:
    """Pull every transaction-section header from the raw text. NSDL CAS
    transaction blocks lead with:
        'Folio No - 35007279\\nISIN: INF179K01WA6 - HDFC Mutual Fund -
         Scheme Name: GFGT - HDFC Balanced Advantage Fund - Direct
         Plan - Growth Option\\nOpening Balance ...'
    Order-preserved.
    """
    pattern = re.compile(
        r"Folio No\s*[-:]\s*(\S+)\s*\n\s*ISIN[:\s]+([A-Z0-9]{12})\s*-\s*([^\n]+)",
        re.I,
    )
    out: List[Dict[str, Any]] = []
    for m in pattern.finditer(text):
        folio = m.group(1).strip()
        isin = m.group(2).strip()
        rest = m.group(3).strip()
        # Rest looks like: "HDFC Mutual Fund - Scheme Name: GFGT - HDFC Balanced ..."
        amc = ""
        fund = rest
        # Try to split AMC vs fund_name
        m2 = re.match(r"(.+?)\s*-\s*Scheme Name[:\s]+\S+\s*-\s*(.+)", rest, re.I)
        if m2:
            amc = m2.group(1).strip()
            fund = m2.group(2).strip()
        else:
            # Fallback: AMC = first dash-separated chunk
            parts = [p.strip() for p in rest.split(" - ")]
            if parts:
                amc = parts[0]
                fund = " - ".join(parts[1:]) if len(parts) > 1 else rest
        out.append(
            {
                "isin": isin,
                "amc": amc,
                "fund_name": fund,
                "folio_number": folio,
            }
        )
    return out


# ── Main entry point ──────────────────────────────────────────────────
def normalize(docai_output: Dict[str, Any]) -> Dict[str, Any]:
    """Convert Document AI {text, tables} → Claude/CAS-Connect schema."""
    text = docai_output.get("text") or ""
    tables = docai_output.get("tables") or []

    depository = _detect_depository(text)
    out: Dict[str, Any] = {
        "statement_info": _extract_statement_info(text, depository=depository),
        "investor_info": _extract_investor_info(text, depository=depository),
        "portfolio_summary": {"total_value_inr": _extract_total_value(text), "asset_allocation": []},
        "portfolio_value_trend": [],
        "accounts": [],
        "holdings": {
            "equities": [],
            "preference_shares": [],
            "sovereign_gold_bonds": [],
            "mutual_funds_demat": [],
            "mutual_fund_folios": [],
        },
        "transactions": {
            "demat_transactions": [],
            "mutual_fund_transactions": [],
        },
    }

    mf_txn_headers = _extract_mf_txn_headers(text)
    mf_txn_header_idx = 0
    classifications: List[Tuple[int, str]] = []

    for idx, table in enumerate(tables):
        if not table:
            continue
        kind = _classify_table(table)
        classifications.append((idx, kind))

        if kind == "asset_allocation":
            out["portfolio_summary"]["asset_allocation"].extend(_parse_asset_allocation(table))
        elif kind == "portfolio_trend":
            out["portfolio_value_trend"].extend(_parse_portfolio_trend(table))
        elif kind == "accounts":
            out["accounts"].extend(_parse_accounts(table))
        elif kind == "equity":
            for r in table:
                rec = _eq_row_to_record(r)
                if rec:
                    out["holdings"]["equities"].append(rec)
        elif kind == "preference":
            for r in table:
                rec = _pref_row_to_record(r)
                if rec:
                    out["holdings"]["preference_shares"].append(rec)
        elif kind == "sgb":
            for r in table:
                rec = _sgb_row_to_record(r)
                if rec:
                    out["holdings"]["sovereign_gold_bonds"].append(rec)
        elif kind == "mf_demat":
            for r in table:
                recs = _mf_demat_row_to_record(r)
                if recs:
                    out["holdings"]["mutual_funds_demat"].extend(recs)
        elif kind == "mf_folios":
            for r in table:
                rec = _folio_row_to_record(r)
                if rec:
                    out["holdings"]["mutual_fund_folios"].append(rec)
        elif kind == "cdsl_equity":
            for r in table:
                rec = _cdsl_equity_row_to_record(r)
                if not rec:
                    continue
                # Route ETFs (INF ISIN — happens when a CDSL "Equity" table
                # accidentally swept in an ETF row) into the demat MF bucket
                # so downstream classifiers tag them correctly. CDSL ETFs
                # with INE-like ISINs stay in equities.
                if rec["isin"].startswith("INF"):
                    out["holdings"]["mutual_funds_demat"].append(
                        {
                            "isin": rec["isin"],
                            "fund_name": rec.get("company_name") or "",
                            "num_units": rec.get("num_shares") or 0,
                            "nav_inr": rec.get("market_price_inr") or 0.0,
                            "value_inr": rec.get("value_inr") or 0.0,
                        }
                    )
                else:
                    out["holdings"]["equities"].append(rec)
        elif kind == "cdsl_mf_folio":
            for r in table:
                rec = _cdsl_mf_folio_row_to_record(r)
                if rec:
                    out["holdings"]["mutual_fund_folios"].append(rec)
        elif kind == "mf_transactions":
            scheme_ctx = (
                mf_txn_headers[mf_txn_header_idx]
                if mf_txn_header_idx < len(mf_txn_headers)
                else {}
            )
            mf_txn_header_idx += 1
            for r in table:
                rec = _mf_txn_row_to_record(r, scheme_ctx)
                if rec:
                    out["transactions"]["mutual_fund_transactions"].append(rec)
        elif kind == "demat_transactions":
            # Best-effort capture for now; mapper currently drops these.
            for r in table:
                date_iso = _iso_date(r[0]) if r else None
                if date_iso:
                    out["transactions"]["demat_transactions"].append(
                        {
                            "date": date_iso,
                            "description": _clean(r[1]) if len(r) > 1 else "",
                            "raw": [_clean(c) for c in r],
                        }
                    )

    # Dedupe MF folio entries by (isin, folio_number) — Document AI sometimes
    # repeats the same folio across page boundaries with partial data.
    out["holdings"]["mutual_fund_folios"] = _dedupe_folios(
        out["holdings"]["mutual_fund_folios"]
    )

    # Recover MF-demat ISINs that Document AI failed to extract as table
    # cells but ARE present in the raw text stream.
    extras = _recover_missed_mf_demat(text, out["holdings"]["mutual_funds_demat"])
    if extras:
        out["holdings"]["mutual_funds_demat"].extend(extras)
        logger.info(f"NIVESH normalizer: recovered {len(extras)} MF-demat rows from text")

    logger.info(
        f"NIVESH normalizer: depository={depository} tables={len(tables)} "
        f"eq={len(out['holdings']['equities'])} "
        f"pref={len(out['holdings']['preference_shares'])} "
        f"sgb={len(out['holdings']['sovereign_gold_bonds'])} "
        f"mf_demat={len(out['holdings']['mutual_funds_demat'])} "
        f"folios={len(out['holdings']['mutual_fund_folios'])} "
        f"mf_txns={len(out['transactions']['mutual_fund_transactions'])}"
    )
    out["_classification"] = classifications
    return out


def _dedupe_folios(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for r in rows:
        key = (r.get("isin") or "", r.get("folio_number") or "")
        if key not in seen:
            seen[key] = r
        else:
            # Prefer record with higher current_value_inr (more complete)
            if _f(r.get("current_value_inr")) > _f(seen[key].get("current_value_inr")):
                seen[key] = r
    return list(seen.values())


# ── Text-based fallback for ISINs missed by Document AI tables ────────
# Pattern in raw text after a header row:
#     "<ISIN>\n<units>\n<nav>\n<value>\n<fund_name>"
# Used to recover holdings that Doc AI fails to detect as table cells
# (e.g., ETF rows with sparse formatting).
_MFD_TEXT_PATTERN = re.compile(
    r"\b(INF[A-Z0-9]{9})\b\s*\n\s*([\d,]+\.?\d*)\s*\n\s*([\d,]+\.\d{2,4})\s*\n\s*([\d,]+\.\d{2})\s*\n\s*([A-Z][^\n]+)",
    re.M,
)


def _recover_missed_mf_demat(text: str, already: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Find INF... ISINs in raw text that follow the
    `ISIN\\nunits\\nnav\\nvalue\\nname` pattern and are NOT yet in
    `already`. Append them as MF-demat holdings.
    """
    seen = {h["isin"] for h in already if h.get("isin")}
    extras: List[Dict[str, Any]] = []
    for m in _MFD_TEXT_PATTERN.finditer(text):
        isin = m.group(1)
        if isin in seen:
            continue
        units = _f(m.group(2))
        nav = _f(m.group(3))
        value = _f(m.group(4))
        name = m.group(5).strip()
        # Quick sanity: units * nav should be roughly value (within 5%)
        if units > 0 and nav > 0 and value > 0:
            product = units * nav
            if abs(product - value) / max(value, 1.0) > 0.1:
                continue  # suspicious — skip
        extras.append(
            {
                "isin": isin,
                "fund_name": name,
                "num_units": units,
                "nav_inr": nav,
                "value_inr": value,
            }
        )
        seen.add(isin)
    return extras
