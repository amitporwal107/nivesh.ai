"""NSE corp_actions.csv parser.

Headers (current rolling file):
    SYMBOL, SERIES, NAME OF COMPANY, FACE VALUE, PURPOSE,
    EX-DATE, RECORD DATE, BC START DATE, BC END DATE,
    ND START DATE, ND END DATE

`PURPOSE` is free-text from NSE — e.g. "DIV-RS 2 PER SHARE",
"BONUS 1:1", "STOCK SPLIT FROM RS 10 TO RS 5", "RIGHTS 1:5 @ 100".
We classify into ACTION_TYPE + extract structured fields where we
can. Unclassified rows are kept as action_type=OTHER (with raw
purpose preserved) so we never drop a CA event silently.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# INTERIM/FINAL/SPECIAL may sit on either side of DIVIDEND; "Re" (singular
# rupee) appears alongside Rs/INR/₹; amount can follow a "- " separator.
_DIV_RE = re.compile(
    r"(?:(?P<sub_pre>INTERIM|FINAL|SPECIAL)\s+)?"
    r"\bDIV(?:IDEND)?\b"
    r"(?:[\s-]*(?P<sub_post>INTERIM|FINAL|SPECIAL)\b)?"
    r"[\s-]*(?:RS\.?|INR\.?|RE\.?|₹)?\s*"
    r"(?P<amt>\d+(?:\.\d+)?)",
    re.I,
)
# Split FROM <pre> TO <post>, tolerating "/-" and "Per Share" between values
# (e.g. "From Rs 10/- Per Share To Re 1/- Per Share").
_SPLIT_RE = re.compile(
    r"\bSPLIT\b[^0-9]*(?:RS\.?|INR\.?|RE\.?|₹)?\s*(?P<pre>\d+(?:\.\d+)?)"
    r"[^0-9]*?(?:RS\.?|INR\.?|RE\.?|₹)?\s*(?P<post>\d+(?:\.\d+)?)",
    re.I,
)
_BONUS_RE = re.compile(r"BONUS\s+(?P<num>\d+)\s*:\s*(?P<den>\d+)", re.I)
_RIGHTS_RE = re.compile(r"RIGHTS\s+(?P<num>\d+)\s*:\s*(?P<den>\d+)", re.I)
_BUYBACK_RE = re.compile(r"BUY[\s-]?BACK", re.I)
_MERGER_RE = re.compile(r"\bMERGER\b|\bAMALGAMATION\b", re.I)
_DEMERGER_RE = re.compile(r"\bDEMERGER\b|\bSCHEME OF ARRANGEMENT\b", re.I)
_AGM_RE = re.compile(r"\bAGM\b", re.I)
_BOARD_RE = re.compile(r"BOARD MEETING|BOARD MTG", re.I)
_INTEREST_RE = re.compile(r"\bINTEREST\s+PAYMENT\b|\bCOUPON\b", re.I)
# REIT / InvIT cash payouts are filed as "Distribution - Rs X.XX Per Unit ...".
_DISTRIBUTION_RE = re.compile(r"\b(?:INCOME\s+)?DISTRIBUTION\b", re.I)
_AMOUNT_RE = re.compile(r"(?:RS\.?|INR\.?|RE\.?|₹)\s*(\d+(?:\.\d+)?)", re.I)


def _classify(purpose: str) -> tuple[str, Optional[str], dict[str, Any]]:
    """Returns (action_type, action_subtype, extracted_fields).

    Two-tier match: try the *structured* regexes first (they extract
    numeric fields like dividend amount, split ratio). If none match,
    fall through to keyword detection (type only, no extraction).
    Anything still unrecognised becomes OTHER.

    Without the keyword tier, NSE strings like 'Dividend' (no amount),
    'Annual General Meeting' (vs 'AGM'), 'Postal Ballot', 'EGM',
    'Open Offer' all fell to OTHER and tripped the
    other_ratio_not_dominant validation.
    """
    if not purpose:
        return "OTHER", None, {}
    p = purpose.strip()

    # ── Tier 1: structured regexes (with extraction) ────────────────
    m = _DIV_RE.search(p)
    if m:
        sub = (m.group("sub_pre") or m.group("sub_post") or "").upper() or None
        return "DIVIDEND", sub, {"dividend_amount": float(m.group("amt"))}

    # InvIT/REIT cash payout — "Distribution - Rs 3.50 Per Unit ...". Capture
    # the headline per-unit amount in dividend_amount so downstream cash-flow
    # logic treats it like a dividend.
    if _DISTRIBUTION_RE.search(p):
        amt_m = _AMOUNT_RE.search(p)
        extracted = {"dividend_amount": float(amt_m.group(1))} if amt_m else {}
        return "DISTRIBUTION", None, extracted

    m = _SPLIT_RE.search(p)
    if m:
        return "SPLIT", None, {
            "ratio": f"{m.group('pre')}:{m.group('post')}",
            "face_value_pre": float(m.group("pre")),
            "face_value_post": float(m.group("post")),
        }

    m = _BONUS_RE.search(p)
    if m:
        return "BONUS", None, {"ratio": f"{m.group('num')}:{m.group('den')}"}

    m = _RIGHTS_RE.search(p)
    if m:
        return "RIGHTS", None, {"ratio": f"{m.group('num')}:{m.group('den')}"}

    # ── Tier 2: keyword fallbacks (type-only, no extraction) ────────
    up = p.upper()

    if _INTEREST_RE.search(p):                                    return "INTEREST_PAYMENT", None, {}
    if _BUYBACK_RE.search(p):                                     return "BUYBACK",       None, {}
    if _DEMERGER_RE.search(p) or "SCHEME" in up:                  return "DEMERGER",      None, {}
    if _MERGER_RE.search(p):                                      return "MERGER",        None, {}
    if "OPEN OFFER" in up or "TENDER OFFER" in up:                return "OPEN_OFFER",    None, {}
    if "DELIST" in up:                                            return "DELISTING",     None, {}
    if "CAPITAL REDUCTION" in up or "REDUCTION OF CAPITAL" in up: return "CAPITAL_REDUCTION", None, {}
    if "SPIN" in up and "OFF" in up:                              return "SPIN_OFF",      None, {}
    if "ESOP" in up or "EMPLOYEE STOCK" in up:                    return "ESOP",          None, {}

    # Bare-keyword DIVIDEND/BONUS/RIGHTS/SPLIT (no amount/ratio in text)
    if "DIVIDEND" in up or up.startswith("DIV"):                  return "DIVIDEND",      None, {}
    if "BONUS" in up:                                             return "BONUS",         None, {}
    if "RIGHTS" in up:                                            return "RIGHTS",        None, {}
    if "SPLIT" in up or "SUB-DIVISION" in up:                     return "SPLIT",         None, {}

    # Meetings (AGM/EGM/Postal Ballot)
    if _AGM_RE.search(p) or "ANNUAL GENERAL MEETING" in up:       return "AGM",           None, {}
    if "EGM" in up or "EXTRA-ORDINARY GENERAL MEETING" in up \
            or "EXTRAORDINARY GENERAL MEETING" in up:             return "EGM",           None, {}
    if "POSTAL BALLOT" in up:                                     return "POSTAL_BALLOT", None, {}
    if _BOARD_RE.search(p):                                       return "BOARD_MEETING", None, {}

    return "OTHER", None, {}


def _parse_date(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = s.strip()
    if not s or s in ("-", "—"):
        return None
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _normalize_dash(v: Optional[str]) -> Optional[str]:
    """NSE uses '-' as the empty-cell sentinel. Coerce to None."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in ("-", "—", "NA", "N.A."):
        return None
    return s


def parse_corporate_actions(body: bytes) -> list[dict[str, Any]]:
    """Parse NSE corporate-actions response.

    NSE moved this endpoint from CSV
    (nsearchives.nseindia.com/content/equities/corp_actions.csv → 404)
    to JSON
    (www.nseindia.com/api/corporates-corporateActions?index=equities).
    Response is now a JSON array of objects with these fields:
        symbol, series, ind, faceVal, subject, exDate, recDate,
        bcStartDate, bcEndDate, ndStartDate, ndEndDate, caBroadcastDate,
        comp, isin

    `subject` is the free-text purpose used for action-type classification
    (same regex set as before).
    """
    import json
    text = body.decode("utf-8-sig", errors="replace").lstrip()

    # Backwards-compat: if NSE ever serves CSV again, detect and parse legacy.
    if not text.startswith(("[", "{")):
        return _parse_legacy_csv(body)

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"corporate_actions: invalid JSON ({e})") from e

    # Some NSE endpoints wrap arrays in {"data": [...]}.
    if isinstance(payload, dict):
        for key in ("data", "items", "rows"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise ValueError(f"corporate_actions: expected JSON array, got {type(payload).__name__}")

    out: list[dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        sym = (entry.get("symbol") or "").strip().upper()
        ex_date = _parse_date(_normalize_dash(entry.get("exDate")))
        if not (sym and ex_date):
            continue

        purpose = (entry.get("subject") or "").strip()
        action_type, sub, extracted = _classify(purpose)

        out.append({
            "symbol":            sym,
            "series":            (entry.get("series") or "").strip().upper() or None,
            "action_type":       action_type,
            "action_subtype":    sub,
            "purpose":           purpose or None,
            "ratio":             extracted.get("ratio"),
            "face_value_pre":    extracted.get("face_value_pre"),
            "face_value_post":   extracted.get("face_value_post"),
            "dividend_amount":   extracted.get("dividend_amount"),
            "record_date":       _parse_date(_normalize_dash(entry.get("recDate"))),
            "ex_date":           ex_date,
            "bc_start_date":     _parse_date(_normalize_dash(entry.get("bcStartDate"))),
            "bc_end_date":       _parse_date(_normalize_dash(entry.get("bcEndDate"))),
            "announcement_date": _parse_date(_normalize_dash(entry.get("caBroadcastDate"))),
        })
    return out


def _parse_legacy_csv(body: bytes) -> list[dict[str, Any]]:
    """Fallback for the old CSV format (now 404). Kept so historical
    archives can still be parsed if NSE ever republishes them."""
    text = body.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    headers = next(reader, None)
    if not headers:
        return []
    norm = [h.strip().upper() for h in headers]
    idx = {h: i for i, h in enumerate(norm)}

    def col(*names: str) -> Optional[int]:
        for n in names:
            if n in idx: return idx[n]
        return None

    sym_i = col("SYMBOL")
    purp_i = col("PURPOSE", "PURPOSE OF CORPORATE ACTION", "REMARKS")
    ex_i = col("EX-DATE", "EX DATE")
    if sym_i is None or purp_i is None or ex_i is None:
        raise ValueError(f"corp_actions CSV missing required columns. headers={norm}")

    out: list[dict[str, Any]] = []
    for r in reader:
        if not r or all(not c.strip() for c in r):
            continue
        try:
            sym = r[sym_i].strip().upper()
            purpose = r[purp_i].strip()
            ex_date = _parse_date(r[ex_i])
        except IndexError:
            continue
        if not (sym and ex_date):
            continue
        action_type, sub, extracted = _classify(purpose)
        out.append({
            "symbol":            sym,
            "series":            (r[col("SERIES")].strip().upper() if col("SERIES") is not None and col("SERIES") < len(r) else None) or None,
            "action_type":       action_type,
            "action_subtype":    sub,
            "purpose":           purpose,
            "ratio":             extracted.get("ratio"),
            "face_value_pre":    extracted.get("face_value_pre"),
            "face_value_post":   extracted.get("face_value_post"),
            "dividend_amount":   extracted.get("dividend_amount"),
            "record_date":       _parse_date(r[col("RECORD DATE")] if col("RECORD DATE") is not None and col("RECORD DATE") < len(r) else None),
            "ex_date":           ex_date,
            "bc_start_date":     _parse_date(r[col("BC START DATE")] if col("BC START DATE") is not None and col("BC START DATE") < len(r) else None),
            "bc_end_date":       _parse_date(r[col("BC END DATE")] if col("BC END DATE") is not None and col("BC END DATE") < len(r) else None),
            "announcement_date": None,
        })
    return out
