"""Value comparison and difference classification (plan §4-§5; CMP-01..08, TOL-01..06).

`tolerance` answers "do two numbers match within the configured tolerance?"; `materiality` answers "is the gap
economically significant?" — reported separately. `classify` explains a Trendlyne value against the NSE record:
RESTATEMENT is only ever assigned when a later filing's comparative column proves the change; an unexplained gap is
UNRESOLVED / DIFFERS_UNEXPLAINED.
"""
from __future__ import annotations

import json
import math
import os
from typing import Optional

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "comparison.json")


def load_config(path: str = CONFIG) -> dict:
    with open(path) as f:
        return json.load(f)


def _num(x) -> Optional[float]:
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def tolerance(metric: str, a, b, cfg: dict) -> str:
    """WITHIN_TOLERANCE / OUTSIDE_TOLERANCE / UNRESOLVED (a missing value never compares as zero)."""
    a, b = _num(a), _num(b)
    if a is None or b is None:
        return "UNRESOLVED"
    c = cfg[metric]
    scale = max(abs(a), abs(b))
    tol = c["abs"] if scale < c.get("zero_band", 0) else max(c["abs"], c["rel"] * scale)
    return "WITHIN_TOLERANCE" if abs(a - b) <= tol + 1e-12 else "OUTSIDE_TOLERANCE"


def materiality(metric: str, a, b, cfg: dict) -> dict:
    a, b = _num(a), _num(b)
    if a is None or b is None:
        return {"result": "UNRESOLVED", "sign_change": None, "review_required": True}
    c = cfg[metric]
    sign_change = (a > 0 > b) or (a < 0 < b)
    material = False
    if c.get("materiality_abs") is not None and abs(a - b) > c["materiality_abs"]:
        material = True
    if c.get("materiality_rel") is not None:
        denom = max(abs(a), abs(b))
        if denom == 0:
            material = material or (a != b)
        elif abs(a - b) / denom > c["materiality_rel"]:
            material = True
    return {"result": "MATERIAL_DIFFERENCE" if material else "IMMATERIAL", "sign_change": sign_change,
            "review_required": bool(sign_change or material)}


def _rounds_to(metric: str, a: float, b: float, cfg: dict) -> bool:
    """True when the gap is within half a displayed unit (a value shown at d decimals is exact to +/-0.5*10^-d).
    Python's round() is not used: binary floats make half-way cases (75.05 -> 75.0 or 75.1) arbitrary."""
    d = cfg.get("rounding_display_decimals", {}).get(metric)
    return d is not None and abs(a - b) <= 0.5 * 10 ** -d + 1e-9


def classify(metric: str, trendlyne, first_filed, latest_known=None, *, other_basis=None, other_period_values=(),
             other_definition_values=(), restatement_evidence: Optional[dict] = None,
             cfg: Optional[dict] = None) -> dict:
    """Explain `trendlyne` against the NSE values for the same (symbol, period, basis).

    first_filed: value in the first filing; latest_known: value from the latest revision or later comparative column;
    other_basis: the other consolidation basis' first-filed value; other_period_values: values of neighbouring periods;
    other_definition_values: [(label, value)] of the same filing under another definition (total income, interest
    earned, owners' profit) — a match there is DEFINITION_DIFFERENCE, and it also explains a missing first_filed;
    restatement_evidence: {"later_filing_id", "comparative_value"} when a later filing re-reports this period.
    """
    cfg = cfg or load_config()
    tl, ff, lk = _num(trendlyne), _num(first_filed), _num(latest_known)
    out = {"metric": metric, "trendlyne": tl, "as_filed_value": ff, "latest_known_value": lk,
           "tolerance_vs_first_filed": tolerance(metric, tl, ff, cfg),
           "tolerance_vs_latest": tolerance(metric, tl, lk, cfg) if lk is not None else None,
           "materiality_vs_first_filed": materiality(metric, tl, ff, cfg), "revision_type": "NONE",
           "difference_type": "UNRESOLVED", "reconciliation_status": "DIFFERS_UNEXPLAINED", "explanation": None}
    if tl is not None and ff is None:
        m = _definition_match(metric, tl, other_definition_values, cfg)
        if m:
            out.update(difference_type="DEFINITION_DIFFERENCE", reconciliation_status="DIFFERS_EXPLAINED",
                       explanation=f"no as-filed {metric} tag; matches {m}")
            return out
    if tl is None or ff is None:
        out["explanation"] = "missing value (never read as zero)"
        return out
    changed = lk is not None and tolerance(metric, ff, lk, cfg) == "OUTSIDE_TOLERANCE"
    if changed:
        out["revision_type"] = "RESTATEMENT" if restatement_evidence else "FILING_REVISION"
    if out["tolerance_vs_first_filed"] == "WITHIN_TOLERANCE":
        exact = tl == ff
        out.update(difference_type="NO_DIFFERENCE" if exact and not changed else "FIRST_FILED_MATCH",
                   reconciliation_status="MATCH_FIRST_FILED")
        if not exact and _rounds_to(metric, tl, ff, cfg):
            out["explanation"] = "equal after display rounding"
        return out
    if changed and out["tolerance_vs_latest"] == "WITHIN_TOLERANCE":
        if restatement_evidence:
            out.update(difference_type="RESTATEMENT", reconciliation_status="MATCH_LATEST_REVISION",
                       explanation=f"matches later comparative in filing {restatement_evidence.get('later_filing_id')}")
        else:
            out.update(difference_type="LATEST_REVISION_MATCH", reconciliation_status="MATCH_LATEST_REVISION")
        return out
    if _rounds_to(metric, tl, ff, cfg):
        out.update(difference_type="ROUNDING", reconciliation_status="DIFFERS_EXPLAINED", explanation="display rounding")
        return out
    for k in (-7, -5, -2, 2, 5, 7):  # rupees / lakhs / crores / thousands scale slips
        if ff != 0 and tolerance(metric, tl, ff * 10 ** k, cfg) == "WITHIN_TOLERANCE":
            out.update(difference_type="UNIT_CONVERSION", reconciliation_status="DIFFERS_EXPLAINED",
                       explanation=f"matches as-filed x 1e{k}")
            return out
    ob = _num(other_basis)
    if ob is not None and tolerance(metric, tl, ob, cfg) == "WITHIN_TOLERANCE":
        out.update(difference_type="DEFINITION_DIFFERENCE", reconciliation_status="DIFFERS_EXPLAINED",
                   explanation="matches the other consolidation basis")
        return out
    m = _definition_match(metric, tl, other_definition_values, cfg)
    if m:
        out.update(difference_type="DEFINITION_DIFFERENCE", reconciliation_status="DIFFERS_EXPLAINED",
                   explanation=f"matches {m}")
        return out
    for label, v in other_period_values:
        if _num(v) is not None and tolerance(metric, tl, v, cfg) == "WITHIN_TOLERANCE":
            out.update(difference_type="PERIOD_MAPPING", reconciliation_status="DIFFERS_EXPLAINED",
                       explanation=f"matches period {label}")
            return out
    out["explanation"] = "no configured explanation matched"
    return out


def _definition_match(metric: str, tl: float, candidates, cfg: dict) -> Optional[str]:
    for label, v in candidates:
        if _num(v) is not None and tolerance(metric, tl, v, cfg) == "WITHIN_TOLERANCE":
            return label
    return None
