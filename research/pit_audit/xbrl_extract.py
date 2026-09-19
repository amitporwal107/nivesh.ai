"""Quarter-exact metric extraction from NSE results XBRL (legacy Reg-33 `in-bse-fin` and Integrated `in-capmkt`).

Why not nidp.services.nse_financials.parser.parse_xbrl_document as-is (documented deficiencies, not modified):
- DEF-2: it matches contexts on END date only, first write wins. In legacy XBRL the year-to-date context (e.g. `FourD`)
  DECLARES the quarter's dates while its reported-period facts say otherwise (NH Q2 FY25: FourD context 07-01..09-30,
  DateOfStartOfReportingPeriod 2024-04-01). Only the per-context reported-period facts identify the quarter.
- DEF-6: its PAT map knows `ProfitLoss` but these taxonomies report `ProfitLossForPeriod`, so pat_cr came back None.
Reused from the parser: _extract_xml, _iter_local, _find_local, _localname, _scaled_value (units and scaling).

Output: one dict per (context, basis) whose reported period equals the requested quarter; ambiguity -> UNRESOLVED.
"""
from __future__ import annotations

import datetime as dt
import sys
from typing import Optional

sys.path.insert(0, "/app/.claude/worktrees/paper-engine/backend")
from nidp.services.nse_financials import parser as P  # noqa: E402

METRICS = {  # audit metric -> ordered candidate tags (first present wins; the tag used is recorded)
    # Banking taxonomy has no RevenueFromOperations: revenue stays None there (never substituted); the bank
    # candidates below are recorded separately so a provider's choice can be classified as DEFINITION_DIFFERENCE.
    "revenue_cr": ("RevenueFromOperations",),
    "pat_cr": ("ProfitLossForPeriod", "ProfitLoss", "ProfitLossForThePeriod",  # Banking taxonomy
               "ProfitLossAfterTax"),                                           # General-insurance taxonomy
    "eps_basic": ("BasicEarningsLossPerShareFromContinuingOperations", "BasicEarningsLossPerShare",
                  "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                  "BasicEarningsPerShareAfterExtraordinaryItems"),  # last = Banking taxonomy
    # explanatory metrics (CMP-05): providers may report total income, interest earned, owners' profit or EPS including
    # discontinued operations instead (HINDUNILVR Dec-25 28.12 vs continuing 9.03; ABB Mar-26 84.18 vs 16.14)
    "eps_basic_total": ("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",),
    "total_income_cr": ("Income",),
    "interest_earned_cr": ("InterestEarned",),
    "pat_owners_cr": ("ProfitOrLossAttributableToOwnersOfParent", "ProfitLossAttributableToOwnersOfParent",
                      "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates"),
}
MONETARY = {"revenue_cr", "pat_cr", "total_income_cr", "interest_earned_cr", "pat_owners_cr"}
EXTRACTOR_VERSION = "xbrl_extract-0.1.2"


def _date(s: Optional[str]) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(str(s).strip()[:10])
    except (TypeError, ValueError):
        return None


def contexts_with_reported_periods(root) -> dict:
    """context id -> {"ctx_start", "ctx_end", "reported_start", "reported_end", "basis"}."""
    ctx = {}
    for c in P._iter_local(root, "context"):
        cid = c.get("id")
        period = P._find_local(c, "period")
        if not cid or period is None:
            continue
        s, e, i = (P._find_local(period, k) for k in ("startDate", "endDate", "instant"))
        end_el = e if e is not None else i
        ctx[cid] = {"ctx_start": _date(s.text) if s is not None else None,
                    "ctx_end": _date(end_el.text) if end_el is not None else None,
                    "reported_start": None, "reported_end": None, "basis": None}
    for el in root.iter():
        cid = el.get("contextRef")
        if cid not in ctx:
            continue
        name = P._localname(el.tag)
        if name == "DateOfStartOfReportingPeriod":
            ctx[cid]["reported_start"] = _date(el.text)
        elif name == "DateOfEndOfReportingPeriod":
            ctx[cid]["reported_end"] = _date(el.text)
        elif name == "NatureOfReportStandaloneConsolidated":
            ctx[cid]["basis"] = (el.text or "").strip().upper() or None
    return ctx


def extract(body: bytes, period_start: dt.date, period_end: dt.date) -> dict:
    """{"status": OK|UNRESOLVED|UNPARSEABLE, "rows": [{context, basis, metrics..., tags_used}], "reason"}."""
    xml = P._extract_xml(body)
    if xml is None:
        return {"status": "UNPARSEABLE", "rows": [], "reason": "no XML payload"}
    try:
        root = P.ET.fromstring(xml)
    except P.ET.ParseError as e:
        return {"status": "UNPARSEABLE", "rows": [], "reason": f"XML parse error: {e}"}
    ctx = contexts_with_reported_periods(root)
    quarter = [cid for cid, c in ctx.items() if c["reported_start"] == period_start and c["reported_end"] == period_end]
    if not quarter:
        return {"status": "UNRESOLVED", "rows": [], "reason": "no context reports the requested quarter"}
    rows = {cid: {"context": cid, "basis": ctx[cid]["basis"], "tags_used": {}} for cid in quarter}
    for el in root.iter():
        cid = el.get("contextRef")
        if cid not in rows:
            continue
        name = P._localname(el.tag)
        for metric, tags in METRICS.items():
            if name not in tags:
                continue
            prev = rows[cid]["tags_used"].get(metric)
            if prev is not None and tags.index(prev) <= tags.index(name):
                continue  # keep the higher-priority tag
            v = P._scaled_value(el, scale_to_crores=metric in MONETARY)
            if v is not None:
                rows[cid][metric] = v
                rows[cid]["tags_used"][metric] = name
    by_basis: dict = {}
    for r in rows.values():
        by_basis.setdefault(r["basis"], []).append(r)
    ambiguous = [b for b, rs in by_basis.items()
                 if len(rs) > 1 and len({tuple(sorted((k, r.get(k)) for k in METRICS)) for r in rs}) > 1]
    if ambiguous:
        return {"status": "UNRESOLVED", "rows": list(rows.values()), "reason": f"conflicting quarter contexts for {ambiguous}"}
    return {"status": "OK", "rows": [rs[0] for rs in by_basis.values()], "reason": None, "extractor_version": EXTRACTOR_VERSION}
