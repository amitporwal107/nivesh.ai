"""Selection framework — hard gates, overlap rejection, personalization, audit.

The deterministic retrieval-and-ranking layer behind the copilot Portfolio Builder
(docs/Nivesh_Selection_Framework.md). The builder (services.sleeve_builder) ranks a
candidate pool, then feeds it through here to enforce eligibility, de-duplicate by
holdings overlap, personalize to the user, cap by policy, and emit an audit record.

Everything here is a PURE function over plain dicts so the selection rules are
unit-testable WITHOUT a database. The governed numbers come from
config/allocation_policy.yaml (services.allocation_policy); the gate thresholds the
YAML does not declare come from the framework doc (PRD A3) and are module constants.

Honesty contract (CONTEXT.md §1): a gate whose input field is absent emits status
"not_evaluated" with reason "data_unavailable" — it is NEVER silently passed. A high
score can never override a failed gate (PRD B2/B3).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ── Gate thresholds (PRD A3; YAML declares none of these, so no conflict) ────────
# AUM floors: too-small funds are unstable. Debt floor is higher than equity.
GATE_AUM_FLOOR_CR: Dict[str, float] = {
    "equity": 500.0,
    "debt": 1000.0,
    "liquid": 1000.0,
    "gold": 50.0,   # gold ETFs/FoFs are structurally small — relaxed (matches goal_fund_picker)
}
GATE_MIN_TRACK_RECORD_YEARS = 3.0     # PRD A3: inception age >= 3y
GATE_MIN_MANAGER_TENURE_YEARS = 1.5   # PRD A3: tenure >= 18m

# Gates that need data not reliably available yet (holdings/AMC disclosures, events).
# We DECLARE them so output shows "not_evaluated" rather than implying a clean pass.
_DEFERRED_DEBT_GATES = ("debt_safety", "category_integrity")

_MISSING = object()  # sentinel: field absent from the candidate


def _num(cand: Dict[str, Any], *keys: str) -> Any:
    """First present, non-None numeric field among `keys`, else _MISSING."""
    for k in keys:
        v = cand.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return _MISSING


# ── Hard gates (binary eligibility) ──────────────────────────────────────────────
def evaluate_gates(cand: Dict[str, Any], *, asset_class: str) -> Dict[str, Any]:
    """Evaluate the MF eligibility gates for one candidate.

    Returns {"passed": bool, "gates": [{gate, status, reason}, ...]}.
    passed is False iff any gate has status "failed". "not_evaluated" never fails
    a candidate but is recorded so the output is honest about what was checked.
    """
    ac = (asset_class or "").lower()
    floor = GATE_AUM_FLOOR_CR.get(ac, GATE_AUM_FLOOR_CR["equity"])
    gates: List[Dict[str, Any]] = []

    def add(gate: str, ok: Optional[bool], reason: str = "") -> None:
        status = "not_evaluated" if ok is None else ("passed" if ok else "failed")
        gates.append({"gate": gate, "status": status, "reason": reason})

    # AUM floor
    aum = _num(cand, "aum_cr", "aum")
    if aum is _MISSING:
        add("aum_floor", None, "data_unavailable")
    else:
        add("aum_floor", aum >= floor, "" if aum >= floor else f"aum {aum:.0f}cr < {floor:.0f}cr floor")

    # Track record (inception age)
    age = _num(cand, "fund_age_years", "inception_age_years", "age_years")
    if age is _MISSING:
        add("track_record", None, "data_unavailable")
    else:
        ok = age >= GATE_MIN_TRACK_RECORD_YEARS
        add("track_record", ok, "" if ok else f"age {age:.1f}y < {GATE_MIN_TRACK_RECORD_YEARS:.0f}y")

    # Direct plan exists (a populated direct expense ratio, or a Direct scheme name)
    has_direct_er = cand.get("expense_ratio_direct") is not None
    name = str(cand.get("scheme_name") or "").lower()
    plan = cand.get("plan_type")
    if has_direct_er or "direct" in name:
        add("direct_plan", True)
    elif plan:
        # Only an EXPLICIT plan_type can fail this gate; a bare expense_ratio is
        # not evidence of the plan, so it must not flip the gate to "failed".
        add("direct_plan", plan == "direct", "" if plan == "direct" else "no direct plan")
    else:
        add("direct_plan", None, "data_unavailable")

    # Manager tenure
    ten = _num(cand, "manager_tenure_years", "fm_tenure_years", "manager_tenure")
    if ten is _MISSING:
        add("manager_tenure", None, "data_unavailable")
    else:
        ok = ten >= GATE_MIN_MANAGER_TENURE_YEARS
        add("manager_tenure", ok, "" if ok else f"tenure {ten:.1f}y < {GATE_MIN_MANAGER_TENURE_YEARS}y")

    # Debt-only gates we cannot evaluate yet — declared as not_evaluated, never silent-pass.
    if ac == "debt":
        for g in _DEFERRED_DEBT_GATES:
            add(g, None, "data_unavailable")

    passed = not any(g["status"] == "failed" for g in gates)
    return {"passed": passed, "gates": gates}


def filter_eligible(candidates: List[Dict[str, Any]], *, asset_class: str) -> Tuple[
    List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split candidates into (eligible, rejected). Rejected carry gate_failed reasons.

    Gates do NOT loosen by profile (PRD C2) — this function takes no profile.
    """
    eligible, rejected = [], []
    for c in candidates:
        res = evaluate_gates(c, asset_class=asset_class)
        enriched = {**c, "gate_results": res["gates"]}
        if res["passed"]:
            eligible.append(enriched)
        else:
            failed = [g for g in res["gates"] if g["status"] == "failed"]
            rejected.append({**enriched, "gate_failed": [g["gate"] for g in failed],
                             "gate_reason": "; ".join(g["reason"] for g in failed if g["reason"])})
    return eligible, rejected


# ── Overlap (PRD C4) ─────────────────────────────────────────────────────────────
def _normalize_weights(holdings: Dict[str, float]) -> Dict[str, float]:
    """Return holdings as fractions (0..1). Accepts either fractions or percentages."""
    if not holdings:
        return {}
    vals = [float(v) for v in holdings.values() if v is not None]
    if not vals or sum(vals) <= 0:
        return {}
    # A fraction can never exceed 1.0, so any weight > 1.0 means the dict is in
    # percentage units -> scale to fractions. (Sum-based detection mislabels a
    # concentrated fractional book whose partial sum exceeds 1.5.)
    scale = 100.0 if max(vals) > 1.0 else 1.0
    return {k: float(v) / scale for k, v in holdings.items() if v is not None}


def compute_overlap(holdings_a: Dict[str, float], holdings_b: Dict[str, float]) -> float:
    """overlap(A,B) = Σ min(weight_A[stock], weight_B[stock]) over common holdings.

    Weights normalized to fractions; result is 0..1. PRD C4.
    """
    a = _normalize_weights(holdings_a)
    b = _normalize_weights(holdings_b)
    common = set(a) & set(b)
    return sum(min(a[k], b[k]) for k in common)


def reject_overlapping(
    ranked: List[Dict[str, Any]],
    *,
    holdings_by_key: Dict[str, Dict[str, float]],
    threshold: float,
    key_field: str = "isin",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Walk `ranked` (best first); accept a candidate unless its holdings overlap
    an already-selected pick by more than `threshold`. PRD C4.

    Returns (selected, rejected). A candidate (or selected pick) with no holdings
    yields overlap "not_evaluated": the candidate is still accepted (we never
    silently drop on missing data), tagged overlap_status="not_evaluated".
    """
    selected: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for cand in ranked:
        ck = cand.get(key_field)
        ch = holdings_by_key.get(ck) if ck is not None else None
        if not ch:
            # Candidate's own holdings unknown -> overlap not computable; keep, tag honestly.
            selected.append({**cand, "overlap_status": "not_evaluated", "overlap_pct": None})
            continue
        worst = 0.0
        worst_against = None
        n_siblings = len(selected)
        compared = 0  # selected siblings we could actually compare against
        for sel in selected:
            sk = sel.get(key_field)
            sh = holdings_by_key.get(sk) if sk is not None else None
            if not sh:
                continue  # THIS pair is not evaluable — must not poison the others
            compared += 1
            ov = compute_overlap(ch, sh)
            if ov > worst:
                worst, worst_against = ov, sk
        if compared and worst > threshold:
            rejected.append({**cand, "overlap_pct": round(worst, 4),
                             "overlap_with": worst_against, "overlap_status": "rejected"})
        elif n_siblings == 0 or compared:
            # No siblings to conflict with, or compared against >=1 sibling and cleared.
            selected.append({**cand, "overlap_status": "evaluated", "overlap_pct": round(worst, 4)})
        else:
            # Siblings exist but none carried holdings -> genuinely nothing to compare.
            selected.append({**cand, "overlap_status": "not_evaluated", "overlap_pct": None})
    return selected, rejected


# ── Personalization (PRD C) ──────────────────────────────────────────────────────
def horizon_allows_equity(horizon_years: float) -> bool:
    """A goal under 3 years can never be routed to equity/long-duration (PRD C3)."""
    return float(horizon_years or 0) >= 3.0


def is_elss(sub_category: Optional[str]) -> bool:
    return "elss" in str(sub_category or "").lower()


def capacity_fund_cap(monthly_sip_rs: Optional[float], *, hard_cap: int) -> int:
    """Scale fund count to capacity (PRD C3): a ₹5k SIP gets 2–3 funds, not 12.

    Returns a count never exceeding the policy hard cap (max_holdings_per_sub_sleeve).
    None/0 SIP → hard cap (no capacity constraint known).
    """
    sip = float(monthly_sip_rs or 0)
    if sip <= 0:
        return hard_cap
    if sip <= 5000:
        cap = 2
    elif sip <= 15000:
        cap = 3
    else:
        cap = hard_cap
    return min(cap, hard_cap)


def intersect_buyable(
    candidates: List[Dict[str, Any]],
    buyable_isins: Optional[set],
    *,
    key_field: str = "isin",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Keep only instruments the user can actually transact (PRD C3 platform filter).

    `buyable_isins` None/empty → no filter applied (MVP fallback = treat all as
    buyable; see workspace decision NI-1). Returns (kept, dropped).
    """
    if not buyable_isins:
        return list(candidates), []
    kept, dropped = [], []
    for c in candidates:
        (kept if c.get(key_field) in buyable_isins else dropped).append(c)
    return kept, dropped


# ── Audit trail (PRD D4) ─────────────────────────────────────────────────────────
def build_audit_record(
    *,
    inputs: Dict[str, Any],
    selected: List[Dict[str, Any]],
    rejected: List[Dict[str, Any]],
    weights: Dict[str, Any],
    scoring_config_version: str,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Per-proposal audit record: inputs, gates passed/failed, scores, weights,
    scoring-config version, timestamp. Missing any field = a contract violation."""
    return {
        "inputs": inputs,
        "weights": weights,
        "scoring_config_version": scoring_config_version,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "picks": [
            {"isin": s.get("isin"), "scheme_name": s.get("scheme_name"),
             "score": s.get("quality_score", s.get("debt_score")),
             "gate_results": s.get("gate_results"),
             "overlap_status": s.get("overlap_status")}
            for s in selected
        ],
        "rejected": [
            {"isin": r.get("isin"), "scheme_name": r.get("scheme_name"),
             "gate_failed": r.get("gate_failed"), "gate_reason": r.get("gate_reason"),
             "overlap_status": r.get("overlap_status"), "overlap_pct": r.get("overlap_pct")}
            for r in rejected
        ],
    }


# ── Orchestration ────────────────────────────────────────────────────────────────
def select_for_sleeve(
    candidates: List[Dict[str, Any]],
    *,
    asset_class: str,
    monthly_sip_rs: Optional[float] = None,
    buyable_isins: Optional[set] = None,
    holdings_by_key: Optional[Dict[str, Dict[str, float]]] = None,
    overlap_threshold: float = 0.40,
    max_holdings: int = 3,
) -> Dict[str, Any]:
    """Full per-sleeve pipeline: buyable filter → hard gates → overlap rejection →
    capacity/policy cap. `candidates` must already be ranked best-first.

    Returns {selected, rejected, gate_results, dropped_non_buyable, cap_applied}.
    """
    buyable, non_buyable = intersect_buyable(candidates, buyable_isins)
    eligible, gate_rejected = filter_eligible(buyable, asset_class=asset_class)
    selected, overlap_rejected = reject_overlapping(
        eligible, holdings_by_key=holdings_by_key or {}, threshold=overlap_threshold)
    cap = capacity_fund_cap(monthly_sip_rs, hard_cap=max_holdings)
    capped = selected[:cap]
    return {
        "selected": capped,
        "rejected": gate_rejected + overlap_rejected,
        "dropped_non_buyable": non_buyable,
        "cap_applied": cap,
        "shortlist_size": len(selected),
    }
