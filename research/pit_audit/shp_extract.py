"""Shareholding-pattern (SHP) category percentages from NSE XBRL, both formats (CAT-01, CMP-07).

Why not nidp.services.nse_shareholding.parser.parse_xbrl_document as-is (documented deficiencies, not modified):
- DEF-8: it returns no rows for the pre-mid-2025 SHP format (contexts without "_Context", e.g. `InstitutionsDomesticI`,
  values in PERCENT), so every Sep-24 / Dec-24 / Mar-25 filing in the sample came back empty.
- DEF-9: its current-format map expects `MutualFunds_ContextI`; filings use `MutualFundsOrUTI_ContextI`, so mf_pct is
  None for every filing.
Both formats carry `ShareholdingAsAPercentageOfTotalNumberOfShares`, one fact per category context. The SCALE is read
from the filing's own TOTAL fact (`ShareholdingPattern_ContextI` / `ShareholdingPatternI`): 1 means the categories are
fractions (current format, 0.0726 = 7.26%), 100 means percent (older format, and mid-2025 transition filings such as
HINDUNILVR Jun-25 that use the new contexts with percent values). Checks: promoter + public must not exceed the total,
and the remainder (SEBI category C, non-promoter non-public: employee trusts, depositary receipts) must be <= 5 pp;
otherwise UNRESOLVED. A company with no promoter context gets promoter_pct None (flagged), never 0.
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/app/.claude/worktrees/paper-engine/backend")
from nidp.services.nse_financials import parser as P  # noqa: E402  (shared XML helpers only)

TAG = "ShareholdingAsAPercentageOfTotalNumberOfShares"
FORMATS = {  # format -> {context id: metric}
    "current": {"ShareholdingOfPromoterAndPromoterGroup_ContextI": "promoter_pct",
                "InstitutionsForeign_ContextI": "fii_pct", "InstitutionsDomestic_ContextI": "dii_pct",
                "MutualFundsOrUTI_ContextI": "mf_pct", "PublicShareholding_ContextI": "public_pct"},
    "pre_2025": {"ShareholdingOfPromoterAndPromoterGroupI": "promoter_pct", "InstitutionsForeignI": "fii_pct",
                 "InstitutionsDomesticI": "dii_pct", "MutualFundsOrUtiI": "mf_pct",
                 "PublicShareholdingI": "public_pct"},
}
TOTAL_CTX = {"current": "ShareholdingPattern_ContextI", "pre_2025": "ShareholdingPatternI"}
SUM_TOL, MAX_CATEGORY_C = 0.05, 5.0
EXTRACTOR_VERSION = "shp_extract-0.1.2"


def extract(body: bytes) -> dict:
    """{"status": OK|UNRESOLVED|UNPARSEABLE, "format", "values": {metric: percent or None}, "reason"}."""
    xml = P._extract_xml(body)
    if xml is None:
        return {"status": "UNPARSEABLE", "format": None, "values": {}, "reason": "no XML payload"}
    try:
        root = P.ET.fromstring(xml)
    except P.ET.ParseError as e:
        return {"status": "UNPARSEABLE", "format": None, "values": {}, "reason": f"XML parse error: {e}"}
    facts = {}
    for el in root.iter():
        if P._localname(el.tag) == TAG and el.get("contextRef"):
            facts.setdefault(el.get("contextRef"), (el.text or "").strip())
    found = [f for f, c in TOTAL_CTX.items() if c in facts]
    if len(found) != 1:
        return {"status": "UNRESOLVED", "format": None, "scale": None, "values": {},
                "reason": f"total-shareholding context not identified ({found})"}
    fmt = found[0]
    try:
        total = float(facts[TOTAL_CTX[fmt]])
    except ValueError:
        return {"status": "UNRESOLVED", "format": fmt, "scale": None, "values": {}, "reason": "total not numeric"}
    scale = {1.0: ("fraction", 100.0), 100.0: ("percent", 1.0)}.get(round(total, 6))
    if scale is None:
        return {"status": "UNRESOLVED", "format": fmt, "scale": None, "values": {}, "reason": f"total = {total}, not 1 or 100"}
    values = {}
    for cid, metric in FORMATS[fmt].items():
        try:
            values[metric] = round(float(facts[cid]) * scale[1], 6) if facts.get(cid) not in (None, "") else None
        except ValueError:
            values[metric] = None
    p, u = values.get("promoter_pct"), values.get("public_pct")
    if u is None:
        return {"status": "UNRESOLVED", "format": fmt, "scale": scale[0], "values": {}, "reason": "public shareholding missing"}
    residual = round(100.0 - u - (p or 0.0), 6)
    if residual < -SUM_TOL or residual > MAX_CATEGORY_C:
        return {"status": "UNRESOLVED", "format": fmt, "scale": scale[0], "values": {},
                "reason": f"promoter + public = {round((p or 0.0) + u, 4)} vs total 100 (residual {residual})"}
    return {"status": "OK", "format": fmt, "scale": scale[0], "values": values, "category_c_residual_pp": residual,
            "no_promoter_context": p is None, "reason": None, "extractor_version": EXTRACTOR_VERSION}
