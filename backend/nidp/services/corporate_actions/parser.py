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

_DIV_RE = re.compile(r"DIV(IDEND)?[\s-]*(?P<sub>INTERIM|FINAL|SPECIAL)?[\s-]*(RS\.?|INR\.?|₹)?\s*(?P<amt>\d+(?:\.\d+)?)", re.I)
_SPLIT_RE = re.compile(r"SPLIT.*?(?:RS\.?|INR\.?|₹)?\s*(?P<pre>\d+(?:\.\d+)?)\s*(?:TO|/)\s*(?:RS\.?|INR\.?|₹)?\s*(?P<post>\d+(?:\.\d+)?)", re.I)
_BONUS_RE = re.compile(r"BONUS\s+(?P<num>\d+)\s*:\s*(?P<den>\d+)", re.I)
_RIGHTS_RE = re.compile(r"RIGHTS\s+(?P<num>\d+)\s*:\s*(?P<den>\d+)", re.I)
_BUYBACK_RE = re.compile(r"BUY[\s-]?BACK", re.I)
_MERGER_RE = re.compile(r"\bMERGER\b|\bAMALGAMATION\b", re.I)
_DEMERGER_RE = re.compile(r"\bDEMERGER\b|\bSCHEME OF ARRANGEMENT\b", re.I)
_AGM_RE = re.compile(r"\bAGM\b", re.I)
_BOARD_RE = re.compile(r"BOARD MEETING|BOARD MTG", re.I)


def _classify(purpose: str) -> tuple[str, Optional[str], dict[str, Any]]:
    """Returns (action_type, action_subtype, extracted_fields)."""
    if not purpose:
        return "OTHER", None, {}
    p = purpose.strip()

    m = _DIV_RE.search(p)
    if m:
        return ("DIVIDEND", (m.group("sub") or "").upper() or None,
                {"dividend_amount": float(m.group("amt"))})

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

    if _BUYBACK_RE.search(p):  return "BUYBACK", None, {}
    if _DEMERGER_RE.search(p): return "DEMERGER", None, {}
    if _MERGER_RE.search(p):   return "MERGER", None, {}
    if _AGM_RE.search(p):      return "AGM", None, {}
    if _BOARD_RE.search(p):    return "BOARD_MEETING", None, {}

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


def parse_corporate_actions(body: bytes) -> list[dict[str, Any]]:
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
