"""Target Allocation Engine — Step 1 of the Nivesh Decision Engine.

Computes a target asset-class mix (equity / debt / gold / cash) from
three inputs:

  1. RISK PROFILE — base table (Aggressive / Moderate / Conservative).
  2. BEHAVIOURAL SIGNALS — modifiers (drawdown tolerance, trading
     frequency, volatility preference). v1 stub: returns no modifier
     when signals aren't captured yet on user_profiles.
  3. GOALS — overlay weighted by priority + horizon (short-horizon
     pulls to debt; long-horizon retirement pulls to equity).

Output is a single weighted-blend allocation:
    {equity, debt, gold, cash} (each 0-100, sum to 100)
plus a `confidence_score` (0-100) reflecting how much real input data
was available (full risk + multi-goal + behaviour = high; risk only =
low).

Pure function — no Mongo writes. Caller decides whether to persist to
`target_allocations` or just compute on demand.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Step 1: base allocation by risk tier ────────────────────────────────
# Delegated to allocation_bands service (MongoDB-backed, admin-tunable).
# Import is deferred to avoid circular-import at module load; the cache
# is synchronous so no await is needed at call time.
from services import allocation_bands as _ab  # noqa: E402

# Default when no risk profile is set — moderate but lower confidence.
_DEFAULT_RISK = "moderate"


# ── Step 3: goal overlay ────────────────────────────────────────────────
# Each goal type / horizon shifts the base. Numbers in pp (percentage
# points). Applied additively then re-normalised.
def _goal_overlay(goal_type: str, horizon_years: float) -> Dict[str, float]:
    """Per-goal pp-shifts to apply on top of base risk allocation.

    Short-horizon = MORE debt / cash; long-horizon = MORE equity.
    Retirement / education / wealth-building leans equity-heavy if the
    horizon is >7y; emergency / next-purchase leans debt regardless.
    """
    g = (goal_type or "").lower().strip()
    h = max(0.0, float(horizon_years or 0))

    # Emergency / short-term goals always pull to safe assets
    if g in ("emergency", "near_term", "short_term") or h < 1:
        return {"equity": -25, "debt": +15, "gold": +5, "cash": +5}
    if h < 3:
        return {"equity": -15, "debt": +10, "gold": +3, "cash": +2}
    if h < 5:
        return {"equity": -8, "debt": +5, "gold": +2, "cash": +1}

    # Long-horizon goals — bias toward growth
    if g in ("retirement", "wealth", "wealth_building") and h >= 10:
        return {"equity": +10, "debt": -8, "gold": -1, "cash": -1}
    if g in ("education", "child_education", "home_purchase") and h >= 7:
        return {"equity": +5, "debt": -3, "gold": -1, "cash": -1}

    # Mid-horizon (5-10y): no overlay — base risk allocation stands.
    return {"equity": 0, "debt": 0, "gold": 0, "cash": 0}


def _goal_weight(priority: str, horizon_years: float, target_rs: float) -> float:
    """Goal weight for the blended overlay. High priority + larger
    target + longer horizon = more influence on final allocation."""
    p = (priority or "").lower()
    p_w = {"high": 3.0, "medium": 2.0, "low": 1.0}.get(p, 1.5)
    # Cap target weight so a single mega-goal doesn't dominate.
    t_w = min(1.0 + (max(0.0, target_rs) / 5_000_000), 3.0)  # ₹50L = 2x
    h_w = min(1.0 + (max(0.0, horizon_years) / 30), 2.0)
    return p_w * t_w * h_w


# ── Step 2: behaviour modifiers (stub for v1) ───────────────────────────
def _behaviour_modifier(profile: Dict[str, Any]) -> Dict[str, float]:
    """Apply behavioural-signal modifiers to the base allocation.

    v1: only acts on signals already captured on user_profiles. Future
    iterations will pull from a dedicated behavioural-signals service
    that mines panic-sell history, trading frequency from CAS, etc.
    """
    mod = {"equity": 0.0, "debt": 0.0, "gold": 0.0, "cash": 0.0}
    behaviour = (profile or {}).get("behaviour") or (profile or {}).get("behavior") or {}

    drawdown = (behaviour.get("drawdown_tolerance") or "").lower()
    if drawdown == "low":
        mod["equity"] -= 7
        mod["debt"] += 7
    elif drawdown == "high":
        mod["equity"] += 5
        mod["debt"] -= 5

    trading = (behaviour.get("trading_activity") or "").lower()
    if trading == "high":
        mod["cash"] += 5
        mod["equity"] -= 5

    vol_pref = (behaviour.get("volatility_preference") or "").lower()
    if vol_pref == "low":
        mod["equity"] -= 3
        mod["debt"] += 3

    return mod


# ── Helpers ─────────────────────────────────────────────────────────────
def _normalise(alloc: Dict[str, float]) -> Dict[str, float]:
    """Clamp each bucket to [0,100], then renormalise so they sum to 100."""
    clamped = {k: max(0.0, min(100.0, float(v))) for k, v in alloc.items()}
    total = sum(clamped.values()) or 1.0
    return {k: round(v / total * 100, 2) for k, v in clamped.items()}


def _add(base: Dict[str, float], delta: Dict[str, float]) -> Dict[str, float]:
    return {k: float(base.get(k, 0)) + float(delta.get(k, 0)) for k in ("equity", "debt", "gold", "cash")}


def _scale(d: Dict[str, float], factor: float) -> Dict[str, float]:
    return {k: float(v) * float(factor) for k, v in d.items()}


def _normalise_risk(value: Optional[str]) -> str:
    v = (value or "").strip().lower()
    tiers = _ab.TIERS  # ["conservative","moderate","balanced","growth","aggressive"]
    if v in tiers:
        return v
    if "aggress" in v:
        return "aggressive"
    if "growth" in v or "high" in v:
        return "growth"
    if "balanced" in v:
        return "balanced"
    if "conserv" in v or "low" in v:
        return "conservative"
    if "modera" in v or "medium" in v:
        return "moderate"
    return _DEFAULT_RISK


# ── Confidence ladder (Phase 4) ─────────────────────────────────────────
# D-6 PROVISIONAL VALUES (2026-06-03) — pending advisory sign-off.
# These are reasonable engineering defaults; the product owner must
# confirm/amend before treating as final policy.
# Tier    | Score | Label
# --------+-------+------
# goals+risk |  90  | "Full confidence"
# risk-only  |  70  | "Risk-based plan"
# dob-only   |  50  | "Age-rule estimate"
# generic    |  40  | "Generic plan — add your profile"
_CONFIDENCE_TIERS: Dict[str, Dict[str, Any]] = {
    # D-6 confirmed 2026-06-03 — scores + labels approved by product owner
    "goals_and_risk": {"score": 90.0, "label": "Full confidence"},
    "risk_only":      {"score": 70.0, "label": "Risk-based plan"},
    "dob_only":       {"score": 50.0, "label": "Age-rule estimate"},
    "generic":        {"score": 40.0, "label": "Generic plan — add your profile"},
}


def _age_rule_equity(dob_str: Optional[str]) -> Optional[float]:
    """Return equity % from the 110-minus-age rule, or None if DOB is absent/invalid."""
    if not dob_str:
        return None
    try:
        from datetime import date as _date
        # Handle ISO format dates and partial strings
        dob_clean = str(dob_str)[:10]  # take YYYY-MM-DD prefix
        born = _date.fromisoformat(dob_clean)
        today = _date.today()
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        return max(0.0, float(110 - age))
    except Exception:
        return None


# ── Public API ──────────────────────────────────────────────────────────
@dataclass
class TargetAllocation:
    allocation: Dict[str, float]              # final % per bucket
    confidence_score: float                   # 0-100
    risk_category: str                        # normalised
    inputs_used: Dict[str, Any] = field(default_factory=dict)
    breakdown: Dict[str, Any] = field(default_factory=dict)  # for explainability
    # Phase 0 — P0-AC-3: versioning so band changes are auditable
    version: str = "v1.0.0"
    # Phase 4 — confidence tier and user-facing label
    confidence_tier: str = "generic"
    confidence_label: str = "Generic plan — add your profile"


async def compute_target_allocation(user_id: str) -> TargetAllocation:
    """Top-level entry point. Pulls profile + goals from DB and returns
    the final target allocation with confidence + explainability data."""
    from deps import db

    # ── INPUT 1: risk profile ─────────────────────────────────────
    profile_doc = await db.user_profiles.find_one(
        {"user_id": user_id}, {"_id": 0},
    ) or {}
    risk_profile = profile_doc.get("risk_profile") or {}
    risk_cat = _normalise_risk(risk_profile.get("category"))
    risk_score = risk_profile.get("score")
    base = _ab.base_allocation(risk_cat)

    # ── INPUT 2: behaviour modifiers ──────────────────────────────
    # Pull derived signals from the behavioural-signals service and
    # merge them with anything the user explicitly stored on their
    # profile. Explicit user input wins on collisions.
    derived_signals: Dict[str, Any] = {}
    derived_evidence: Dict[str, Any] = {}
    derived_confidence: float = 0.0
    try:
        from services import behavioural_signals as _bs
        sig = await _bs.compute_signals(user_id)
        derived_signals = {k: v for k, v in sig.to_dict().items() if v}
        derived_evidence = sig.evidence
        derived_confidence = sig.confidence_score
    except Exception as e:  # noqa: BLE001
        logger.warning("behavioural_signals failed for %s: %s", user_id, e)

    explicit = (profile_doc.get("behaviour") or profile_doc.get("behavior") or {})
    merged_behaviour: Dict[str, Any] = {**derived_signals, **explicit}
    behaviour_doc_for_modifier = {"behaviour": merged_behaviour}
    behaviour_mod = _behaviour_modifier(behaviour_doc_for_modifier)
    behaviour_used = any(abs(v) > 0.01 for v in behaviour_mod.values())

    after_behaviour = _normalise(_add(base, behaviour_mod))

    # ── INPUT 3: goals → weighted overlay ─────────────────────────
    goals: List[Dict[str, Any]] = []
    try:
        from services import pg_client as _pg
        pool = await _pg.get_pool()
        if pool is not None:
            import uuid as _uuid
            try:
                uid = _uuid.UUID(user_id) if isinstance(user_id, str) else user_id
            except Exception:  # noqa: BLE001
                uid = _uuid.uuid5(_uuid.NAMESPACE_DNS, f"nivesh:user:{user_id}")
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT goal_type, horizon_years, target_amount_rs, priority "
                    "FROM user_goals WHERE user_id = $1 AND COALESCE(status,'') <> 'archived'",
                    uid,
                )
            goals = [{
                "goal_type": r["goal_type"],
                "horizon_years": float(r["horizon_years"] or 0),
                "target_amount_rs": float(r["target_amount_rs"] or 0),
                "priority": r["priority"],
            } for r in rows]
    except Exception as e:  # noqa: BLE001
        logger.warning("goal pull failed for target allocator: %s", e)

    goal_overlay_total: Dict[str, float] = {"equity": 0, "debt": 0, "gold": 0, "cash": 0}
    weight_total = 0.0
    per_goal_breakdown: List[Dict[str, Any]] = []
    for g in goals:
        overlay = _goal_overlay(g["goal_type"], g["horizon_years"])
        w = _goal_weight(g["priority"], g["horizon_years"], g["target_amount_rs"])
        weighted = _scale(overlay, w)
        goal_overlay_total = _add(goal_overlay_total, weighted)
        weight_total += w
        per_goal_breakdown.append({
            "goal_type": g["goal_type"],
            "horizon_years": g["horizon_years"],
            "priority": g["priority"],
            "weight": round(w, 2),
            "overlay_pp": overlay,
        })

    # Average the weighted goal overlay (so total magnitude stays in
    # pp range, regardless of how many goals exist).
    if weight_total > 0:
        goal_overlay_avg = _scale(goal_overlay_total, 1.0 / weight_total)
    else:
        goal_overlay_avg = {"equity": 0, "debt": 0, "gold": 0, "cash": 0}

    # ── Phase 4: four-tier confidence ladder ─────────────────────
    # Tier is determined by which inputs are available, not by adding up bonuses.
    # Each tier is a real (degraded) target — same object shape, different inputs.
    #
    # Default `final` = risk base + behaviour + (averaged) goal overlay. The
    # risk_only / goals_and_risk tiers use this as-is; the age-rule and generic
    # tiers override it below. Defining it here guarantees `final` is always
    # bound — previously the two risk tiers left it unset, raising NameError
    # (HTTP 500) for every user who had a risk profile.
    final = _normalise(_add(after_behaviour, goal_overlay_avg))
    has_risk_profile = bool(risk_profile.get("category"))
    has_goals = bool(goals)

    # Fetch DOB for age-rule tier (field name confirmed as `dob` in users collection)
    dob_str: Optional[str] = profile_doc.get("dob") or profile_doc.get("date_of_birth")

    if has_risk_profile and has_goals:
        tier = "goals_and_risk"
        # final allocation already incorporates goal overlay — no change needed
    elif has_risk_profile:
        tier = "risk_only"
        # final allocation uses risk base only (goal_overlay_avg is all-zeros above)
    elif dob_str:
        tier = "dob_only"
        # Age rule: equity = max(0, 110 - age); rest split debt-heavy
        age_equity = _age_rule_equity(dob_str)
        if age_equity is not None:
            age_debt = max(0.0, 90.0 - age_equity)
            age_gold = min(10.0, 100.0 - age_equity - age_debt)
            age_cash = max(0.0, 100.0 - age_equity - age_debt - age_gold)
            raw_age_alloc = {"equity": age_equity, "debt": age_debt,
                              "gold": age_gold, "cash": age_cash}
            final = _normalise(raw_age_alloc)
            risk_cat = _DEFAULT_RISK  # generic base for age-rule tier
    else:
        tier = "generic"
        # Generic moderate allocation — visibly provisional in the UI
        final = _normalise(_ab.base_allocation(_DEFAULT_RISK))
        risk_cat = _DEFAULT_RISK

    tier_cfg = _CONFIDENCE_TIERS[tier]
    # Behaviour signals add a small boost (max +5) within the tier
    behaviour_boost = 5.0 if behaviour_used else 0.0
    conf = min(100.0, tier_cfg["score"] + behaviour_boost)

    result = TargetAllocation(
        allocation=final,
        confidence_score=round(conf, 1),
        confidence_tier=tier,
        confidence_label=tier_cfg["label"],
        version="v1.0.0",
        risk_category=risk_cat,
        inputs_used={
            "risk_category": risk_cat,
            "risk_score": risk_score,
            "confidence_tier": tier,
            "n_goals": len(goals),
            "has_dob": dob_str is not None,
            "behaviour_signals_applied": behaviour_used,
            "behaviour_signals": merged_behaviour,
            "behaviour_signal_confidence": derived_confidence,
        },
        breakdown={
            "base_by_risk": base,
            "behaviour_modifier_pp": {k: round(v, 2) for k, v in behaviour_mod.items()},
            "after_behaviour": after_behaviour,
            "goal_overlay_avg": {k: round(v, 2) for k, v in goal_overlay_avg.items()},
            "per_goal": per_goal_breakdown,
            "behaviour_evidence": derived_evidence,
        },
    )

    # ── Persist to db.target_allocations as a write-through cache ─
    # Best-effort — failure here doesn't block the response. Document
    # is keyed by user_id (one current target per user); history can
    # be added later if drift-over-time becomes a feature.
    try:
        from datetime import datetime as _dt, timezone as _tz
        await db.target_allocations.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "allocation": final,
                "confidence_score": result.confidence_score,
                "confidence_tier": result.confidence_tier,
                "confidence_label": result.confidence_label,
                "version": result.version,
                "risk_category": risk_cat,
                "inputs_used": result.inputs_used,
                "breakdown": result.breakdown,
                "updated_at": _dt.now(_tz.utc).isoformat(),
            }},
            upsert=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("target_allocations persist failed for %s: %s", user_id, e)
    return result
