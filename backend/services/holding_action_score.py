"""Holding Action Score (HAS) — portfolio-aware per-holding decision layer.

Sits on top of the V3 fund-level scores (Quality / Health / Exit / Add /
Switch) and adds three NEW portfolio-aware derived scores:

  1. Overlap Impact Score (OIS): weighted stock-level overlap of this fund
     vs the rest of the portfolio.
  2. Allocation Deviation Score (ADS): how far the holding's current weight
     is from its target weight (over-/under-weight).
  3. Tax Friction Score (TFS): tax cost as a fraction of holding value
     (with a STCG penalty bump).

These, combined with V3 scores and category-specific weight tuning, produce
a single Holding Action Score (0-100) that maps deterministically to
{HOLD / ADD / TRIM / SWITCH / EXIT} — then passes through the existing
guardrail set before being returned to the caller.

Everything is pure-Python; no DB / network. Callers feed already-computed
inputs, making the logic trivially unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Category-specific HAS weight profiles ────────────────────────────────
# Each profile sums to 1.0. See user-PRD for rationale.
HAS_WEIGHTS = {
    "equity": {
        "quality":     0.30,
        "health":      0.20,
        "exit_inv":    0.15,  # uses (100 - exit_score)
        "add":         0.15,
        "ois_inv":     0.10,  # uses (100 - ois_score)
        "ads":         0.05,
        "tfs_inv":     0.05,  # uses (100 - tfs_penalty)
    },
    "hybrid": {
        # Overlap less relevant for hybrid; reroute 5pp → Health.
        "quality":     0.30,
        "health":      0.25,
        "exit_inv":    0.15,
        "add":         0.15,
        "ois_inv":     0.05,
        "ads":         0.05,
        "tfs_inv":     0.05,
    },
    "debt": {
        # Overlap even less relevant; redirect to Health.
        "quality":     0.30,
        "health":      0.25,
        "exit_inv":    0.15,
        "add":         0.15,
        "ois_inv":     0.05,
        "ads":         0.05,
        "tfs_inv":     0.05,
    },
    "liquid": {
        # Parking funds — Quality (credit/duration) & Health (liquidity) only.
        "quality":     0.40,
        "health":      0.40,
        "exit_inv":    0.0,
        "add":         0.0,
        "ois_inv":     0.0,
        "ads":         0.10,
        "tfs_inv":     0.10,
    },
}

# HAS → action decision thresholds (after V3 composites + guardrails)
ACTION_THRESHOLDS = [
    (75.0, "HOLD"),    # ≥ 75
    (60.0, "HOLD"),    # 60 – 75
    (45.0, "TRIM"),    # 45 – 60
    (30.0, "SWITCH"),  # 30 – 45
    (0.0,  "EXIT"),    # < 30
]

# Guardrail thresholds (aligned with existing V3 engine)
HIGH_QUALITY_PROTECTION_Q = 75.0
HIGH_QUALITY_PROTECTION_H = 70.0
RECENT_INVESTMENT_DAYS = 180            # 6 months
OVERLAP_OVERRIDE_PCT = 80.0             # allow EXIT even with other guardrails
LOW_CONFIDENCE_THRESHOLD = 50.0


@dataclass
class HasResult:
    """Holding Action Score + derived decision payload."""
    has: Optional[float]
    action: str
    reason: str
    category: str
    components: Dict[str, Optional[float]] = field(default_factory=dict)
    weights_used: Dict[str, float] = field(default_factory=dict)
    ois_score: Optional[float] = None
    ads_score: Optional[float] = None
    ads_deviation_pp: Optional[float] = None
    tfs_penalty: Optional[float] = None
    guardrails: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 100.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has": self.has,
            "action": self.action,
            "reason": self.reason,
            "category": self.category,
            "components": self.components,
            "weights_used": self.weights_used,
            "ois_score": self.ois_score,
            "ads_score": self.ads_score,
            "ads_deviation_pp": self.ads_deviation_pp,
            "tfs_penalty": self.tfs_penalty,
            "guardrails": self.guardrails,
            "confidence": self.confidence,
        }


# ── 1. Overlap Impact Score ───────────────────────────────────────────────
def compute_ois(portfolio_overlap_pct: Optional[float]) -> Optional[float]:
    """OIS = the fund's weighted stock-level overlap with the rest of the
    portfolio, clamped 0–100. Higher = more duplicate exposure = worse.

    Typical interpretation (from the PRD):
      <30  = Good (low duplicate exposure)
      30–60 = Moderate
      >60  = Bad (duplicate exposure)
    """
    if portfolio_overlap_pct is None:
        return None
    return round(max(0.0, min(100.0, float(portfolio_overlap_pct))), 2)


# ── 2. Allocation Deviation Score ─────────────────────────────────────────
def compute_ads(
    current_weight_pct: Optional[float],
    target_weight_pct: Optional[float],
    penalty_per_pp: float = 5.0,
) -> Dict[str, Optional[float]]:
    """ADS = 100 - |deviation| × penalty_per_pp, clamped 0–100.

    Returns:
      deviation_pp  : current − target (+ve → overweight; −ve → underweight)
      penalty       : |deviation| × penalty_per_pp
      score         : 100 − penalty (clamped)
      stance        : 'overweight' | 'underweight' | 'on_target'
    """
    if current_weight_pct is None or target_weight_pct is None:
        return {"deviation_pp": None, "penalty": None, "score": None, "stance": None}
    dev = round(float(current_weight_pct) - float(target_weight_pct), 2)
    penalty = round(abs(dev) * penalty_per_pp, 2)
    score = round(max(0.0, min(100.0, 100.0 - penalty)), 2)
    if abs(dev) < 0.5:
        stance = "on_target"
    elif dev > 0:
        stance = "overweight"
    else:
        stance = "underweight"
    return {"deviation_pp": dev, "penalty": penalty, "score": score, "stance": stance}


# ── 3. Tax Friction Score ─────────────────────────────────────────────────
def compute_tfs(
    tax_cost_rs: Optional[float],
    holding_value_rs: Optional[float],
    is_stcg: bool = False,
    stcg_bump: float = 20.0,
) -> Dict[str, Optional[float]]:
    """TFS penalty scales with tax_cost / holding_value; +20 if STCG.

    penalty = clamp(tax_ratio × 200 + stcg_bump_if_stcg, 0, 100)

    Interpretation (from PRD):
      High gain + STCG   → 80–100  (huge friction — avoid realising)
      Low gain + LTCG    → 10–30   (minimal friction)
    """
    if tax_cost_rs is None or holding_value_rs is None or holding_value_rs <= 0:
        return {"tax_ratio": None, "penalty": None, "is_stcg": is_stcg}
    tax_ratio = max(0.0, float(tax_cost_rs) / float(holding_value_rs))
    base = tax_ratio * 200.0
    penalty = min(100.0, base + (stcg_bump if is_stcg else 0.0))
    penalty = round(max(0.0, penalty), 2)
    return {"tax_ratio": round(tax_ratio, 4), "penalty": penalty, "is_stcg": is_stcg}


# ── 4. Holding Action Score (composite) ───────────────────────────────────
def _component_inputs(
    quality: Optional[float],
    health: Optional[float],
    exit_score: Optional[float],
    add_score: Optional[float],
    ois_score: Optional[float],
    ads_score: Optional[float],
    tfs_penalty: Optional[float],
) -> Dict[str, Optional[float]]:
    """Transform raw V3 scores into the 7 HAS input channels (all 0–100)."""
    return {
        "quality":   quality,
        "health":    health,
        "exit_inv":  None if exit_score is None else max(0.0, min(100.0, 100.0 - exit_score)),
        "add":       add_score,
        "ois_inv":   None if ois_score is None else max(0.0, min(100.0, 100.0 - ois_score)),
        "ads":       ads_score,
        "tfs_inv":   None if tfs_penalty is None else max(0.0, min(100.0, 100.0 - tfs_penalty)),
    }


def compute_has(
    *,
    category: str,
    quality: Optional[float],
    health: Optional[float],
    exit_score: Optional[float] = None,
    add_score: Optional[float] = None,
    ois_score: Optional[float] = None,
    ads_score: Optional[float] = None,
    tfs_penalty: Optional[float] = None,
) -> Dict[str, Any]:
    """Composite 0-100 Holding Action Score per user PRD § 4.

    Category picks the weight profile. Missing components drop out and the
    remaining weights renormalise — so a partially-scored fund still gets a
    defensible HAS instead of a `None` bomb.

    Returns {score, components, effective_weights, category}.
    """
    cat = category if category in HAS_WEIGHTS else "equity"
    weights = HAS_WEIGHTS[cat]
    values = _component_inputs(
        quality=quality, health=health, exit_score=exit_score, add_score=add_score,
        ois_score=ois_score, ads_score=ads_score, tfs_penalty=tfs_penalty,
    )

    available = {k: (v, weights[k]) for k, v in values.items()
                 if v is not None and weights.get(k, 0) > 0}
    if not available:
        return {"score": None, "components": values, "effective_weights": {},
                "category": cat, "missing": list(values.keys())}

    total_w = sum(w for _, w in available.values())
    if total_w <= 0:
        return {"score": None, "components": values, "effective_weights": {},
                "category": cat, "missing": [k for k in values if values[k] is None]}

    score = sum(v * (w / total_w) for v, w in available.values())
    eff_weights = {k: round(w / total_w, 4) for k, (_v, w) in available.items()}
    missing = [k for k in values if values[k] is None and weights.get(k, 0) > 0]
    return {
        "score": round(max(0.0, min(100.0, score)), 2),
        "components": values,
        "effective_weights": eff_weights,
        "category": cat,
        "missing": missing,
    }


# ── 5. Guardrails ─────────────────────────────────────────────────────────
def evaluate_guardrails(
    *,
    quality: Optional[float],
    health: Optional[float],
    tax_cost_rs: Optional[float] = None,
    tax_benefit_rs: Optional[float] = None,
    holding_age_days: Optional[int] = None,
    overlap_pct: Optional[float] = None,
    confidence: float = 100.0,
) -> Dict[str, Any]:
    """Evaluate all 5 guardrails defined in the PRD.

    Returns:
      {
        block_exit: bool,
        allow_exit_override: bool,   # overlap >80% wins even if other blocks
        blocks: [list of reason strings that blocked exit],
        confidence_ok: bool,
        confidence: float,
      }
    """
    blocks: List[str] = []
    if quality is not None and health is not None \
            and quality >= HIGH_QUALITY_PROTECTION_Q \
            and health >= HIGH_QUALITY_PROTECTION_H:
        blocks.append("high_quality_protection")
    if tax_cost_rs is not None and tax_benefit_rs is not None \
            and float(tax_cost_rs) > float(tax_benefit_rs):
        blocks.append("tax_cost_exceeds_benefit")
    if holding_age_days is not None and holding_age_days < RECENT_INVESTMENT_DAYS:
        blocks.append("recent_investment")
    allow_override = bool(overlap_pct is not None and overlap_pct > OVERLAP_OVERRIDE_PCT)
    block_exit = bool(blocks) and not allow_override
    confidence_ok = confidence >= LOW_CONFIDENCE_THRESHOLD
    return {
        "block_exit": block_exit,
        "allow_exit_override": allow_override,
        "blocks": blocks,
        "confidence_ok": confidence_ok,
        "confidence": round(confidence, 2),
    }


# ── 6. Action mapping ─────────────────────────────────────────────────────
def map_has_to_action(
    has: Optional[float],
    guardrails: Dict[str, Any],
    *,
    add_score: Optional[float] = None,
) -> str:
    """Map HAS → action with guardrail overrides applied.

    Decision tree:
      HAS is None           → UNKNOWN
      HAS ≥ 75 & Add ≥ 70   → ADD
      HAS ≥ 60              → HOLD
      HAS 45–60             → TRIM
      HAS 30–45             → SWITCH (downgraded to REVIEW if low confidence)
      HAS < 30              → EXIT
      Post-filter:
        block_exit=True     → downgrade EXIT → REVIEW
        confidence_ok=False → downgrade EXIT/SWITCH → REVIEW
    """
    if has is None:
        return "UNKNOWN"
    if has >= 75.0:
        return "ADD" if (add_score is not None and add_score >= 70) else "HOLD"
    if has >= 60.0:
        return "HOLD"
    if has >= 45.0:
        return "TRIM"
    if has >= 30.0:
        action = "SWITCH"
    else:
        action = "EXIT"
    # Guardrails
    if action == "EXIT" and guardrails.get("block_exit"):
        action = "REVIEW"
    if not guardrails.get("confidence_ok", True) and action in ("EXIT", "SWITCH"):
        action = "REVIEW"
    return action


# ── 7. Human-readable reason ─────────────────────────────────────────────
_COMPONENT_LABELS = {
    "quality":  "fund quality",
    "health":   "fund health",
    "exit_inv": "exit pressure",
    "add":      "add-attractiveness",
    "ois_inv":  "portfolio overlap",
    "ads":      "allocation deviation",
    "tfs_inv":  "tax friction",
}


def build_holding_reason(
    has_result: Dict[str, Any],
    ads_result: Optional[Dict[str, Any]],
    guardrails: Dict[str, Any],
    action: str,
) -> str:
    """One-liner citing the top drivers of the action."""
    comps = has_result.get("components") or {}
    weights = has_result.get("effective_weights") or {}
    # Contribution = value × effective_weight. Surface strongest drag (lowest)
    # for TRIM/SWITCH/EXIT; strongest lift (highest) for HOLD/ADD.
    scored = [(k, comps[k] * weights[k]) for k in weights if comps.get(k) is not None]
    if not scored:
        return "Insufficient data."

    if action in ("EXIT", "SWITCH", "TRIM"):
        scored.sort(key=lambda x: x[1])  # weakest first
        driver_key, _ = scored[0]
        driver_label = _COMPONENT_LABELS.get(driver_key, driver_key)
        driver_val = comps[driver_key]
        base = f"{action.title()} — weakest driver: {driver_label} ({driver_val:.0f}/100)"
    else:
        scored.sort(key=lambda x: x[1], reverse=True)
        driver_key, _ = scored[0]
        driver_label = _COMPONENT_LABELS.get(driver_key, driver_key)
        driver_val = comps[driver_key]
        base = f"{action.title()} — strongest driver: {driver_label} ({driver_val:.0f}/100)"

    # Append ADS stance if meaningful
    if ads_result and ads_result.get("stance") in ("overweight", "underweight"):
        dev = ads_result.get("deviation_pp")
        base += f" · {ads_result['stance']} by {abs(dev):.1f}pp"

    # Append blocked-exit reason if EXIT was downgraded
    blocks = guardrails.get("blocks") or []
    if action == "REVIEW" and blocks:
        base += f" · blocked by guardrail: {blocks[0].replace('_', ' ')}"

    return base


# ── 8. Single entry-point for callers ─────────────────────────────────────
def build_holding_action(
    *,
    category: str,
    quality: Optional[float],
    health: Optional[float],
    exit_score: Optional[float] = None,
    add_score: Optional[float] = None,
    portfolio_overlap_pct: Optional[float] = None,
    current_weight_pct: Optional[float] = None,
    target_weight_pct: Optional[float] = None,
    tax_cost_rs: Optional[float] = None,
    tax_benefit_rs: Optional[float] = None,
    holding_value_rs: Optional[float] = None,
    is_stcg: bool = False,
    holding_age_days: Optional[int] = None,
    confidence: float = 100.0,
) -> HasResult:
    """One-shot: compute OIS + ADS + TFS + HAS + guardrails + action + reason."""
    ois = compute_ois(portfolio_overlap_pct)
    ads = compute_ads(current_weight_pct, target_weight_pct)
    tfs = compute_tfs(tax_cost_rs, holding_value_rs, is_stcg=is_stcg)

    has_res = compute_has(
        category=category,
        quality=quality, health=health,
        exit_score=exit_score, add_score=add_score,
        ois_score=ois, ads_score=ads["score"], tfs_penalty=tfs["penalty"],
    )
    guardrails = evaluate_guardrails(
        quality=quality, health=health,
        tax_cost_rs=tax_cost_rs, tax_benefit_rs=tax_benefit_rs,
        holding_age_days=holding_age_days,
        overlap_pct=portfolio_overlap_pct,
        confidence=confidence,
    )
    action = map_has_to_action(has_res["score"], guardrails, add_score=add_score)
    reason = build_holding_reason(has_res, ads, guardrails, action)

    return HasResult(
        has=has_res["score"],
        action=action,
        reason=reason,
        category=has_res["category"],
        components=has_res["components"],
        weights_used=has_res["effective_weights"],
        ois_score=ois,
        ads_score=ads["score"],
        ads_deviation_pp=ads["deviation_pp"],
        tfs_penalty=tfs["penalty"],
        guardrails=guardrails,
        confidence=confidence,
    )
