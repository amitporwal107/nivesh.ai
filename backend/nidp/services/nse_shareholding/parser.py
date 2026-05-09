"""NSE shareholding-pattern XBRL parser.

Same two-stage shape as nse_financials but a different taxonomy:

  • List endpoint: NSE corporate-share-holdings-master JSON
  • Each filing's XBRL document encodes Reg-31 shareholding facts —
    promoter group, public, FII, DII, mutual funds, etc.

The key SEBI Reg-31 element local-names we extract:
  • SubCategorisationOfShareholding…PercentageOfTotalNumberOfShares
  • Various aggregate-percentage tags grouped under
    `ShareholdingPatternOf{PromoterAndPromoterGroup, PublicShareholder}`
  • Pledged-shares aggregates

Strategy: like financials, look up element local-name (taxonomyversion-tolerant). For shareholding we additionally lean on
contextRef axis dimensions to distinguish category (Promoter / FII /
DII / etc.) — but in practice NSE's IND-AS filings expose direct
percentage tags for each category, which is what we use.
"""
from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)


# Element local-name → output column. Multiple local-names can map to
# the same column to cover taxonomy variations across years.
PERCENT_TAGS: Dict[str, str] = {
    # Promoter
    "PercentageOfShareholdingPromoter":                                 "promoter_pct",
    "ShareholdingPromoterPromoterGroupPercentage":                      "promoter_pct",
    "TotalPromoterAndPromoterGroupPercentage":                          "promoter_pct",
    "PercentageOfShareholdingPromoterAndPromoterGroup":                 "promoter_pct",

    # Pledged % (of total shares OR of promoter holding — context tells us which)
    "PercentageOfSharesPledgedOrOtherwiseEncumberedToTotalShares":      "promoter_pledged_to_total_pct",
    "PercentageOfShareholdingPledgedOrOtherwiseEncumbered":             "promoter_pledged_pct",

    # Institutional — public
    "PercentageOfShareholdingForeignPortfolioInvestors":                "fii_pct",
    "PercentageOfShareholdingForeignInstitutionalInvestors":            "fii_pct",
    "PercentageOfShareholdingMutualFunds":                              "mf_pct",
    "PercentageOfShareholdingInsuranceCompanies":                       "insurance_pct",
    "PercentageOfShareholdingBanks":                                    "bank_fi_pct",
    "PercentageOfShareholdingFinancialInstitutionsBanks":               "bank_fi_pct",
    "PercentageOfShareholdingCentralGovernmentStateGovernment":         "govt_holding_pct",
    "PercentageOfShareholdingCentralGovernmentStateGovernmentPresident": "govt_holding_pct",

    # Public aggregate
    "PercentageOfShareholdingPublicShareholders":                       "public_pct",
    "ShareholdingPublicShareholderPercentage":                          "public_pct",

    # Individual / retail / NRI / corporate
    "PercentageOfShareholdingIndividualShareholders":                   "individual_pct",
    "PercentageOfShareholdingNonResidentIndians":                       "nri_pct",
    "PercentageOfShareholdingBodiesCorporate":                          "bodies_corporate_pct",
}

SHARE_COUNT_TAGS: Dict[str, str] = {
    "TotalNumberOfShares":                                               "total_shares",
    "NumberOfSharesPromoterAndPromoterGroup":                            "promoter_shares",
    "NumberOfSharesPublicShareholders":                                  "public_shares",
    "NumberOfSharesPledgedOrOtherwiseEncumbered":                        "pledged_shares",
}

# BSE SHP v1.1 format (SEBI mandate from Dec-2025 onwards).
# Single tag, column determined by contextRef. Values are decimal fractions
# (0.4504 = 45.04%) — multiply by 100 when extracting.
_NEW_PCT_TAG = "ShareholdingAsAPercentageOfTotalNumberOfShares"
_NEW_SHARES_TAG = "NumberOfFullyPaidUpEquityShares"
_NEW_TOTAL_SHARES_CTX = "ShareholdingPattern_ContextI"
_NEW_CONTEXT_TO_COL: Dict[str, str] = {
    "ShareholdingOfPromoterAndPromoterGroup_ContextI": "promoter_pct",
    "PublicShareholding_ContextI":                     "public_pct",
    "InstitutionsForeign_ContextI":                    "fii_pct",
    "InstitutionsDomestic_ContextI":                   "dii_pct",
    "MutualFunds_ContextI":                            "mf_pct",
    "Banks_ContextI":                                  "bank_fi_pct",
    "NonResidentIndians_ContextI":                     "nri_pct",
    "IndividualsOrHinduUndividedFamily_ContextI":      "individual_pct",
}


def parse_filing_list(body: bytes) -> List[Dict[str, Any]]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        logger.warning("shareholding list JSON decode failed: %s", e)
        return []

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

        # SEBI Reg-31 disclosures have "asOnDate" rather than from/to
        period_end = (
            _parse_nse_date(r.get("asOnDate"))
            or _parse_nse_date(r.get("recordDate"))
            or _parse_nse_date(r.get("toDate"))
            or _parse_nse_date(r.get("date"))
        )
        if not period_end:
            continue

        out.append({
            "symbol":       symbol,
            "company_name": (r.get("companyName") or "").strip(),
            "period_end":   period_end.isoformat(),
            "filing_id":    str(r.get("seqNumber") or r.get("seqno") or ""),
            "xbrl_url":     xbrl_url,
            "broadcast_at": _parse_nse_datetime(r.get("broadcastDate") or r.get("submissionDate")),
        })
    return out


def parse_xbrl_document(body: bytes, manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    xml_bytes = _extract_xml(body)
    if xml_bytes is None:
        return []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        logger.warning("shareholding XBRL parse failed for %s: %s", manifest.get("symbol"), e)
        return []

    # Build context map: id → instant_date (Reg-31 facts are point-in-time)
    contexts: Dict[str, Optional[date]] = {}
    for ctx in _iter_local(root, "context"):
        cid = ctx.get("id")
        if not cid:
            continue
        period = _find_local(ctx, "period")
        if period is None:
            continue
        instant = _text_date(_find_local(period, "instant"))
        end = _text_date(_find_local(period, "endDate"))
        contexts[cid] = instant or end

    target_end = _parse_nse_date(manifest["period_end"])
    if not target_end:
        return []

    row = _empty_row(manifest)
    captured_any = False

    for elem in root.iter():
        local = _localname(elem.tag)
        col = PERCENT_TAGS.get(local) or SHARE_COUNT_TAGS.get(local)
        if not col:
            continue

        ctx_id = elem.get("contextRef")
        if not ctx_id or contexts.get(ctx_id) != target_end:
            continue

        # Some percent tags appear once per category dimension (e.g.
        # promoter_pledged appears in both Promoter and Public contexts);
        # filter to relevant contexts where we can.
        if col == "promoter_pledged_pct" and "promoter" not in ctx_id.lower():
            continue
        if col == "promoter_pledged_to_total_pct":
            # If the context isn't promoter-bound, this fact applies to
            # the total — keep it.
            pass

        try:
            raw = float((elem.text or "").strip())
        except (ValueError, AttributeError):
            continue

        if col in SHARE_COUNT_TAGS.values():
            row[col] = int(raw)
        else:
            row[col] = round(raw, 4)
        captured_any = True

    if not captured_any:
        # BSE SHP v1.1 format (SEBI Dec-2025 mandate): uses a single tag
        # ShareholdingAsAPercentageOfTotalNumberOfShares with contextRef
        # for categorisation. Values are decimal fractions (×100 = percent).
        for elem in root.iter():
            local = _localname(elem.tag)
            ctx_id = elem.get("contextRef", "")
            if local == _NEW_PCT_TAG and ctx_id in _NEW_CONTEXT_TO_COL:
                try:
                    raw = float((elem.text or "").strip())
                except (ValueError, AttributeError):
                    continue
                col = _NEW_CONTEXT_TO_COL[ctx_id]
                row[col] = round(raw * 100, 4)
                captured_any = True
            elif local == _NEW_SHARES_TAG and ctx_id == _NEW_TOTAL_SHARES_CTX:
                try:
                    row["total_shares"] = int(float((elem.text or "").strip()))
                    captured_any = True
                except (ValueError, AttributeError):
                    pass

    if not captured_any:
        return []

    # Public % fallback — derive from 100 − promoter when missing
    if row.get("public_pct") is None and row.get("promoter_pct") is not None:
        row["public_pct"] = round(100.0 - row["promoter_pct"], 4)

    return [row]


def _empty_row(manifest: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "symbol":          manifest["symbol"],
        "period_end":      manifest["period_end"],
        "promoter_pct":    None,
        "promoter_pledged_pct": None,
        "promoter_pledged_to_total_pct": None,
        "fii_pct":         None,
        "dii_pct":         None,
        "mf_pct":          None,
        "insurance_pct":   None,
        "bank_fi_pct":     None,
        "govt_holding_pct": None,
        "public_pct":      None,
        "individual_pct":  None,
        "nri_pct":         None,
        "bodies_corporate_pct": None,
        "total_shares":    None,
        "promoter_shares": None,
        "public_shares":   None,
        "pledged_shares":  None,
        "filing_id":       manifest.get("filing_id"),
        "xbrl_url":        manifest.get("xbrl_url"),
        "broadcast_at":    manifest.get("broadcast_at"),
    }


# ── XML helpers (shared shape with nse_financials) ──────────────────
_LOCAL_NAME_RE = re.compile(r"\{[^}]+\}")


def _localname(tag: str) -> str:
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


def _extract_xml(body: bytes) -> Optional[bytes]:
    if not body:
        return None
    head = body[:4]
    if head[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as zf:
                xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
                if not xml_names:
                    return None
                xml_names.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
                return zf.read(xml_names[0])
        except zipfile.BadZipFile:
            return None
    if head[:1] == b"<":
        return body
    return None
