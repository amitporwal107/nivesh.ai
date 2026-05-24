"""
v4 Recommendation schema augmentation.

Per docs/api-changes.md Decision 2 (approved 2026-05-24): adds
verb · priority_label · source_domain · effort · trade_off · impact
expected_impact · exclusive · scores · switch_target

to every action written into the plan_actions document, without
overwriting any field already populated by a more specific creator.

Augmentation runs at two boundaries:
  1. Pre-write — in action_plan_manager.generate_plan() so new plans
     persist the v4 shape from the start.
  2. Read-time — in get_active_plan() so legacy plans created before
     this change still render the v4 fields to the V4 frontend.

The helper also fixes two pre-v4 schema-drift bugs (gap-analysis Finding C.8):
  • HOLD synthetic action wrote "pending" lowercase → normalises to "PENDING"
  • FLAG synthetic action used `id` instead of `action_id` → adds dual support

All additions are non-destructive: existing fields are never overwritten.
Mobile app + V2/V3 web clients keep reading their existing fields unchanged.
"""

from typing import Any, Dict, List, Optional


# ── Stock vs fund verb buckets (PRD §7.4) ───────────────────────────────
# Stock verbs: Add · Exit · Trim · Hold
# Fund verbs:  Switch · Exit · Add · Merge · Hold

STOCK_ASSET_TYPES = {"EQUITY", "STOCK"}
FUND_ASSET_TYPES = {"MUTUAL_FUND", "FUND", "MF"}

VERB_BY_TYPE = {
    "EXIT": "EXIT",
    "ADD": "ADD",
    "TRIM": "TRIM",
    "HOLD": "HOLD",
    "REVIEW": "REVIEW",
    "SWITCH": "SWITCH",
    "MERGE": "MERGE",
    "HARVEST": "HARVEST",
    "RAISE_SIP": "RAISE_SIP",
}


# ── Priority label vocabularies ─────────────────────────────────────────
# Most dashboards: Critical / Optimise / Enhance
# Goals dashboard: Closes the gap / Closes most / Partial  (PRD §7.4)

PRIORITY_LABEL_DEFAULT = {
    1: "Critical", 2: "Optimise", 3: "Enhance",
    "high": "Critical", "HIGH": "Critical",
    "medium": "Optimise", "MEDIUM": "Optimise",
    "low": "Enhance", "LOW": "Enhance",
}

PRIORITY_LABEL_GOALS = {
    1: "Closes the gap", 2: "Closes most", 3: "Partial",
    "high": "Closes the gap", "HIGH": "Closes the gap",
    "medium": "Closes most", "MEDIUM": "Closes most",
    "low": "Partial", "LOW": "Partial",
}


# ── source_domain inference from reason_codes ───────────────────────────

REASON_CODE_DOMAIN: Dict[str, str] = {
    # Concentration domain
    "SECTOR_CONCENTRATION": "concentration",
    "AMC_CONCENTRATION": "concentration",
    "AMC_CONCENTRATION_EXIT": "concentration",
    "COMPANY_CONCENTRATION": "concentration",
    "STOCK_CONCENTRATION": "concentration",
    "PORTFOLIO_HEALTHY": "concentration",  # do-nothing HOLD lives here
    # Diversification domain
    "OVERLAP_CONSOLIDATION": "diversification",
    "REGULAR_DIRECT_DUPLICATE": "diversification",
    "COST_LEAK_SWITCH_TO_DIRECT": "diversification",
    "COST_LEAK_SWITCH": "diversification",
    "ALLOCATION_IMBALANCE": "diversification",
    "DEBT_UNDERWEIGHT": "diversification",
    # Risk domain
    "HIGH_BETA": "risk",
    "HIGH_VOLATILITY": "risk",
    "DOWNSIDE_RISK": "risk",
    # Performance domain
    "LOW_RETURN_EFFICIENCY": "performance",
    "UNDERPERFORMING_FUND": "performance",
    # Goals domain
    "GOAL_SHORTFALL": "goals",
    "GOAL_AT_RISK": "goals",
    "GOAL_SIP_INCREASE": "goals",
    "GOAL_SIP_STEP_UP": "goals",
    "GOAL_LUMPSUM_TOPUP": "goals",
    "GOAL_HORIZON_EXTENSION": "goals",
    # Tax domain
    "TAX_HARVEST": "tax",
    "TAX_STRUCTURING": "tax",
    "TAX_80C": "tax",
}


def _derive_source_domain(reason_codes: Optional[List[str]]) -> Optional[str]:
    """Map reason_codes → source_domain; first match wins."""
    if not reason_codes:
        return None
    for code in reason_codes:
        domain = REASON_CODE_DOMAIN.get(code)
        if domain:
            return domain
    # Heuristic prefixes for codes not in the explicit lookup
    for code in reason_codes:
        if code.startswith(("GOAL_", "SIP_")):
            return "goals"
        if code.startswith("TAX_"):
            return "tax"
        if code.startswith(("CONC", "SECTOR_", "AMC_", "GROUP_")):
            return "concentration"
        if code.startswith(("OVERLAP", "COST_LEAK", "DUPLICATE", "DIV_")):
            return "diversification"
        if code.startswith(("RISK_", "BETA_", "VOL_", "DRAWDOWN_")):
            return "risk"
        if code.startswith(("PERF_", "XIRR_", "RETURN_", "ALPHA_")):
            return "performance"
    return None


def _derive_verb(action_type: Optional[str], asset_type: Optional[str],
                 reason_codes: Optional[List[str]] = None) -> str:
    """PRD §7.4 verb vocabulary, asset-class aware.

    For funds: an EXIT whose reason_codes encode a swap → SWITCH; an EXIT
    whose codes encode a consolidation → MERGE. Otherwise verb == type.
    """
    t = (action_type or "REVIEW").upper()
    at = (asset_type or "").upper().replace("-", "_").replace(" ", "_")

    if reason_codes and t == "EXIT" and at in FUND_ASSET_TYPES:
        for code in reason_codes:
            if "SWITCH" in code or code == "REGULAR_DIRECT_DUPLICATE":
                return "SWITCH"
        for code in reason_codes:
            if "MERGE" in code or code == "OVERLAP_CONSOLIDATION":
                return "MERGE"

    return VERB_BY_TYPE.get(t, t)


def augment(action: Dict[str, Any]) -> Dict[str, Any]:
    """Augment a single action dict with v4 Recommendation fields.

    Idempotent: never overwrites a field already set. Safe to call on
    an already-augmented action.
    """
    if not isinstance(action, dict):
        return action

    # ── Bug fix: dual id/action_id support (FLAG action path) ──────────
    if "action_id" not in action and "id" in action:
        action["action_id"] = action["id"]
    if "id" not in action and "action_id" in action:
        action["id"] = action["action_id"]  # legacy clients reading `id`

    # ── Bug fix: normalise lowercase "pending" → "PENDING" (HOLD path) ─
    status = action.get("status")
    if isinstance(status, str) and status.strip().lower() == status.strip():
        canonical = {"pending": "PENDING", "in_progress": "IN_PROGRESS",
                     "completed": "COMPLETED", "skipped": "SKIPPED"}.get(status.strip().lower())
        if canonical:
            action["status"] = canonical

    reason_codes = action.get("reason_codes") or []

    # source_domain
    source_domain = action.get("source_domain") or _derive_source_domain(reason_codes)
    if source_domain:
        action["source_domain"] = source_domain

    # verb (PRD §7.4 vocabulary)
    if not action.get("verb"):
        action["verb"] = _derive_verb(action.get("type"), action.get("asset_type"), reason_codes)

    # priority_label
    if not action.get("priority_label"):
        priority = action.get("priority")
        if source_domain == "goals":
            label = PRIORITY_LABEL_GOALS.get(priority)
        else:
            label = PRIORITY_LABEL_DEFAULT.get(priority)
        if not label:
            label = str(priority).title() if priority is not None else "Review"
        action["priority_label"] = label

    # effort — default MEDIUM; per-rule overrides populate the precise value
    if not action.get("effort"):
        action["effort"] = "MEDIUM"

    # trade_off — mandatory per PRD §7.4; empty default until per-rule populates
    if "trade_off" not in action:
        action["trade_off"] = ""

    # impact envelope (label + value)
    if not action.get("impact"):
        action["impact"] = {"label": "Impact", "value": ""}

    # expected_impact — empty dict; populated by domain logic for each metric
    if "expected_impact" not in action:
        action["expected_impact"] = {}

    # exclusive — true for goals (mutually exclusive paths per PRD §7.4)
    if "exclusive" not in action:
        action["exclusive"] = source_domain == "goals"

    # scores + switch_target — null until NIDP populates them
    if "scores" not in action:
        action["scores"] = None
    if "switch_target" not in action:
        action["switch_target"] = None

    return action


def augment_all(actions: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    """Apply augment() in-place to every action in a list.

    Returns the same list reference. None / empty input is returned unchanged.
    """
    if not actions:
        return actions
    for action in actions:
        augment(action)
    return actions
