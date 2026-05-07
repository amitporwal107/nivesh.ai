"""NSE financial-results parser.

Two-stage parse:

  1. parse_filing_list(body) — NSE JSON list endpoint
     /api/corporates-financial-results?index=equities&period=Quarterly
     Returns one manifest per filing: symbol, period dates, consolidation
     flag, audit flag, broadcast time, and the XBRL document URL.

  2. parse_xbrl_document(body, manifest) — one XBRL doc, one row
     Extracts a curated set of IND-AS facts by element local-name
     (taxonomy-version-agnostic). Resolves each fact's contextRef → the
     period it covers; picks the fact whose period matches the filing
     window. Scales raw values (per `decimals` attr) into ₹ crores.

Why local-name lookup beyond canonical XPath: the IND-AS taxonomy
ships under multiple namespaces across schedule revisions
(`in-capmkt`, `in-bse-fin`, `ind-as`, banking variants). Element
LOCAL-names are stable; namespaces are not. Stripping namespaces at
parse time gives us schema-version tolerance for free.

Edge cases handled:
  • XBRL doc served as ZIP — unwrap the inner .xml
  • decimals="-5" (lakhs) vs "-7" (crores) — scaled to crores uniformly
  • Multiple facts same name, different contexts — pick the one whose
    period_end matches the filing's `toDate`
  • Bank/NBFC filings (interest_earned, interest_expended) — separate
    column set populated when detected
  • `relatingTo` field denotes Standalone vs Consolidated; some filings
    have BOTH in one XBRL — we emit two rows
"""
from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


# ── Curated IND-AS element local-names → our column names ───────────
#
# Each entry: local-name → (column, scale_to_crores).
# scale_to_crores=True means apply `decimals` attribute scaling, then
# divide by 10^7 to land in crores. EPS / face-value are per-share, not
# scaled to crores.
INCOME_STMT_TAGS: Dict[str, str] = {
    "RevenueFromOperations":                              "revenue_from_ops_cr",
    "OtherIncome":                                        "other_income_cr",
    "Income":                                             "total_income_cr",
    "Expenses":                                           "total_expenses_cr",
    "FinanceCosts":                                       "finance_costs_cr",
    "DepreciationDepletionAndAmortisationExpense":        "depreciation_cr",
    "DepreciationAndAmortisationExpense":                 "depreciation_cr",
    "ProfitLossBeforeExceptionalItemsAndTax":             "pbt_before_exc_cr",
    "ExceptionalItemsBeforeTax":                          "exceptional_items_cr",
    "ProfitLossBeforeTax":                                "pbt_cr",
    "TaxExpense":                                         "tax_expense_cr",
    "ProfitLossForPeriodFromContinuingOperations":        "pat_continuing_cr",
    "ProfitLossFromDiscontinuedOperationsAfterTax":       "pat_discontinuing_cr",
    "ProfitLoss":                                         "pat_cr",
    "ProfitLossAttributableToOwnersOfParent":             "pat_attrib_owners_cr",
    "ProfitLossAttributableToNonControllingInterests":    "pat_attrib_minority_cr",
}

PER_SHARE_TAGS: Dict[str, str] = {
    "BasicEarningsLossPerShareFromContinuingOperations":  "eps_basic",
    "BasicEarningsLossPerShare":                          "eps_basic",
    "DilutedEarningsLossPerShareFromContinuingOperations": "eps_diluted",
    "DilutedEarningsLossPerShare":                        "eps_diluted",
    "FaceValueOfEquityShareCapital":                      "face_value",
    "ParValuePerShare":                                   "face_value",
}

BALANCE_SHEET_TAGS: Dict[str, str] = {
    "EquityShareCapital":                                 "equity_share_capital_cr",
    "OtherEquity":                                        "other_equity_cr",
    "Equity":                                             "total_equity_cr",
    "LongTermBorrowings":                                 "long_term_debt_cr",
    "ShortTermBorrowings":                                "short_term_debt_cr",
    "CashAndCashEquivalents":                             "cash_and_equiv_cr",
}

BANK_TAGS: Dict[str, str] = {
    "InterestEarned":   "interest_earned_cr",
    "InterestExpended": "interest_expended_cr",
}


# ── List endpoint parser ────────────────────────────────────────────
def parse_filing_list(body: bytes) -> List[Dict[str, Any]]:
    """Parse NSE corporates-financial-results JSON.

    Returns a list of manifest dicts, one per filing. Filings without
    an XBRL link are skipped (we cannot extract numeric facts from
    the PDF attachment without OCR).
    """
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        logger.warning("filing list JSON decode failed: %s", e)
        return []

    # NSE wraps the array under different keys across endpoints. Try
    # the common shapes.
    if isinstance(payload, dict):
        records = (
            payload.get("data")
            or payload.get("records")
            or payload.get("rows")
            or []
        )
    elif isinstance(payload, list):
        records = payload
    else:
        return []

    if not isinstance(records, list):
        return []

    out: List[Dict[str, Any]] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        symbol = (r.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        xbrl_url = (r.get("xbrl") or r.get("xbrlAttachment") or "").strip()
        if not xbrl_url or xbrl_url.lower() in ("-", "na", "n.a.", "none"):
            continue

        from_date = _parse_nse_date(r.get("fromDate") or r.get("from_date"))
        to_date = _parse_nse_date(r.get("toDate") or r.get("to_date"))
        if not to_date:
            continue

        relating_to = (r.get("relatingTo") or r.get("relatedTo") or "").strip().lower()
        consolidated = "consolidated" in relating_to

        audited_raw = (r.get("audited") or "").strip().lower()
        audited = True if audited_raw == "audited" else (False if audited_raw == "un-audited" else None)

        period_type = _infer_period_type(from_date, to_date)

        out.append({
            "symbol":         symbol,
            "company_name":   (r.get("companyName") or "").strip(),
            "period_start":   from_date.isoformat() if from_date else None,
            "period_end":     to_date.isoformat(),
            "period_type":    period_type,
            "consolidated":   consolidated,
            "audited":        audited,
            "filing_id":      str(r.get("seqNumber") or r.get("seqno") or r.get("broadcast") or ""),
            "xbrl_url":       xbrl_url,
            "broadcast_at":   _parse_nse_datetime(r.get("broadcastDate") or r.get("broadcastTimestamp")),
            "relating_to":    r.get("relatingTo") or "",
        })
    return out


def _parse_nse_date(s: Any) -> Optional[date]:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_nse_datetime(s: Any) -> Optional[str]:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).isoformat()
        except ValueError:
            continue
    return None


def _infer_period_type(start: Optional[date], end: Optional[date]) -> str:
    if not start or not end:
        return "UNKNOWN"
    days = (end - start).days
    if days <= 95:        return "QUARTERLY"
    if days <= 190:       return "HALF_YEARLY"
    if days <= 285:       return "NINE_MONTHS"
    if days <= 380:       return "ANNUAL"
    return "UNKNOWN"


# ── XBRL document parser ────────────────────────────────────────────
def parse_xbrl_document(body: bytes, manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse one XBRL filing document. Returns 0, 1, or 2 rows
    (1 row per consolidation flag found in the doc).

    The manifest gives us the expected period_end and the
    consolidation flag from the NSE list. Some filings actually
    contain BOTH standalone + consolidated facts in one XBRL — we
    emit a row per consolidation when both are present.
    """
    xml_bytes = _extract_xml(body)
    if xml_bytes is None:
        return []

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        logger.warning("XBRL parse failed for %s: %s", manifest.get("symbol"), e)
        return []

    # Build context map: id → (start_date, end_date, instant_date)
    contexts: Dict[str, Dict[str, Optional[date]]] = {}
    for ctx in _iter_local(root, "context"):
        ctx_id = ctx.get("id")
        if not ctx_id:
            continue
        period = _find_local(ctx, "period")
        if period is None:
            continue
        start = _text_date(_find_local(period, "startDate"))
        end   = _text_date(_find_local(period, "endDate"))
        instant = _text_date(_find_local(period, "instant"))
        contexts[ctx_id] = {"start": start, "end": end, "instant": instant}

    # Group facts by (column, consolidation) — picking the fact whose
    # period_end matches the manifest's period_end.
    target_end = _parse_nse_date(manifest["period_end"])
    if not target_end:
        return []

    # Two output rows max — one per consolidation flag observed.
    rows: Dict[bool, Dict[str, Any]] = {}

    def _ensure_row(consolidated: bool) -> Dict[str, Any]:
        if consolidated not in rows:
            rows[consolidated] = _empty_row(manifest, consolidated)
        return rows[consolidated]

    # Scan every element for a known local-name. This is O(elements);
    # XBRL docs are typically <50KB so it's negligible.
    for elem in root.iter():
        local = _localname(elem.tag)
        col = (
            INCOME_STMT_TAGS.get(local)
            or PER_SHARE_TAGS.get(local)
            or BALANCE_SHEET_TAGS.get(local)
            or BANK_TAGS.get(local)
        )
        if not col:
            continue

        ctx_id = elem.get("contextRef")
        if not ctx_id:
            continue
        ctx = contexts.get(ctx_id)
        if not ctx:
            continue

        # Period match: instant facts (BS) must equal target_end;
        # duration facts (IS) must end at target_end.
        ctx_end = ctx.get("end") or ctx.get("instant")
        if ctx_end != target_end:
            continue

        # Consolidation: NSE's IND-AS XBRL puts a dimension axis
        # `EquityClassesOfShareCapitalAxis` or similar — but the most
        # reliable signal is the context id naming: 'OneD' / 'TwelveD'
        # for standalone, 'OneD_Consolidated'/'TwelveD_Consolidated'
        # for consolidated. Fall back to the manifest hint.
        consolidated = _detect_consolidation(ctx_id, manifest["consolidated"])

        value = _scaled_value(elem, scale_to_crores=col not in PER_SHARE_TAGS.values())
        if value is None:
            continue

        row = _ensure_row(consolidated)
        # First-write-wins: if the same column was hit multiple times
        # (e.g. two TaxExpense fragments — current + deferred), the
        # XBRL will already aggregate at the right level. If not, the
        # later fact will be a sub-component; skip.
        if row.get(col) is None:
            row[col] = value

    # Derive ebitda where possible: total_income − (total_expenses − D&A − interest)
    for row in rows.values():
        if (row.get("total_income_cr") is not None
                and row.get("total_expenses_cr") is not None):
            adj = row["total_expenses_cr"] - (row.get("depreciation_cr") or 0) - (row.get("finance_costs_cr") or 0)
            row["ebitda_cr"] = round(row["total_income_cr"] - adj, 4)

        # Total equity fallback: equity_share_capital + other_equity
        if (row.get("total_equity_cr") is None
                and row.get("equity_share_capital_cr") is not None
                and row.get("other_equity_cr") is not None):
            row["total_equity_cr"] = round(
                row["equity_share_capital_cr"] + row["other_equity_cr"], 4
            )

        # Bank NIM derivation
        if (row.get("interest_earned_cr") and row.get("interest_expended_cr")):
            ie = row["interest_earned_cr"]
            if ie > 0:
                row["nim_pct"] = round((ie - row["interest_expended_cr"]) / ie * 100, 4)

    return list(rows.values())


def _empty_row(manifest: Dict[str, Any], consolidated: bool) -> Dict[str, Any]:
    """Skeleton row pre-filled with manifest fields. Numeric columns
    default to None and are filled by parser."""
    return {
        "symbol":           manifest["symbol"],
        "period_end":       manifest["period_end"],
        "period_start":     manifest.get("period_start"),
        "period_type":      manifest.get("period_type") or "UNKNOWN",
        "consolidated":     consolidated,
        "audited":          manifest.get("audited"),
        "filing_id":        manifest.get("filing_id"),
        "xbrl_url":         manifest.get("xbrl_url"),
        "broadcast_at":     manifest.get("broadcast_at"),
        # Numeric columns — filled by tag scan
        "revenue_from_ops_cr":      None,
        "other_income_cr":          None,
        "total_income_cr":          None,
        "total_expenses_cr":        None,
        "ebitda_cr":                None,
        "finance_costs_cr":         None,
        "depreciation_cr":          None,
        "pbt_before_exc_cr":        None,
        "exceptional_items_cr":     None,
        "pbt_cr":                   None,
        "tax_expense_cr":           None,
        "pat_continuing_cr":        None,
        "pat_discontinuing_cr":     None,
        "pat_cr":                   None,
        "pat_attrib_owners_cr":     None,
        "pat_attrib_minority_cr":   None,
        "eps_basic":                None,
        "eps_diluted":              None,
        "face_value":               None,
        "equity_share_capital_cr":  None,
        "other_equity_cr":          None,
        "total_equity_cr":          None,
        "long_term_debt_cr":        None,
        "short_term_debt_cr":       None,
        "cash_and_equiv_cr":        None,
        "interest_earned_cr":       None,
        "interest_expended_cr":     None,
        "nim_pct":                  None,
    }


# ── XML helpers ─────────────────────────────────────────────────────
_LOCAL_NAME_RE = re.compile(r"\{[^}]+\}")


def _localname(tag: str) -> str:
    """Strip {namespace} prefix from an ElementTree tag."""
    return _LOCAL_NAME_RE.sub("", tag)


def _iter_local(root: ET.Element, local: str):
    for e in root.iter():
        if _localname(e.tag) == local:
            yield e


def _find_local(parent: ET.Element, local: str) -> Optional[ET.Element]:
    for e in parent:
        if _localname(e.tag) == local:
            return e
    return None


def _text_date(elem: Optional[ET.Element]) -> Optional[date]:
    if elem is None or not elem.text:
        return None
    s = elem.text.strip()[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _scaled_value(elem: ET.Element, *, scale_to_crores: bool) -> Optional[float]:
    """Extract numeric value, applying `decimals` and unit scaling.

    XBRL `decimals="-N"` means raw value is precise to 10^N rupees.
    To get rupees we keep raw as-is (decimals doesn't change the
    number, only its precision). Then to crores: ÷ 10^7.

    For per-share facts (EPS, face value), no crore scaling.
    """
    txt = (elem.text or "").strip()
    if not txt:
        return None
    try:
        raw = float(txt)
    except ValueError:
        return None

    # Skip non-INR units (USD, EUR, etc.) — defensive guard
    unit = elem.get("unitRef") or ""
    if unit and "INR" not in unit.upper() and not _is_per_share_unit(unit):
        return None

    if scale_to_crores:
        return round(raw / 1e7, 4)
    return round(raw, 4)


def _is_per_share_unit(unit: str) -> bool:
    u = unit.upper()
    return "PERSHARE" in u or "EPS" in u or "INRPERSHARES" in u or u == "PURE"


def _detect_consolidation(ctx_id: str, manifest_hint: bool) -> bool:
    """Heuristic: NSE XBRL contexts often encode consolidation in the
    id. If unambiguous, use that; else fall back to the manifest."""
    cid = ctx_id.lower()
    if "consolidated" in cid:
        return True
    if "standalone" in cid:
        return False
    return manifest_hint


def _extract_xml(body: bytes) -> Optional[bytes]:
    """Body may be:
       • Raw XML (starts with '<?xml' or '<')
       • A ZIP containing one or more XML files (starts with 'PK')
       • HTML error page (skip)
    """
    if not body:
        return None
    head = body[:4]
    if head[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as zf:
                xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
                if not xml_names:
                    return None
                # Prefer the largest XML — instance document beats schema
                xml_names.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
                return zf.read(xml_names[0])
        except zipfile.BadZipFile:
            return None
    if head[:1] == b"<":
        return body
    return None
