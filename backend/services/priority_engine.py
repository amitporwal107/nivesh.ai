"""MFD Action Prioritization Engine — "Which client should I act on today?"

Per the approved 5-factor formula:

    priority_score =
        0.30 * portfolio_weakness
      + 0.25 * risk_factor
      + 0.20 * aum_factor          # log-scaled so big clients don't dominate
      + 0.15 * recency_factor
      + 0.10 * recommendation_severity

Output bucket:
    > 0.7  → HIGH   (🔴)
    0.4-0.7 → MEDIUM (🟡)
    < 0.4  → LOW    (🟢)

Every score is accompanied by a `reasons` array for explainability — the
UI renders these as bullet points inside the priority chip tooltip so the
MFD understands *why* a client bubbled to the top.

This module is **pure Python** — it takes already-computed signals from
the existing engine (portfolio_score, risk_score, recommendations) and
combines them. No engine rebuild.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# Factor weights — approved starter set.
W_WEAKNESS = 0.30
W_RISK     = 0.25
W_AUM      = 0.20
W_RECENCY  = 0.15
W_REC_SEV  = 0.10

# Bucket thresholds (priority score).
HIGH_THRESHOLD   = 0.70
MEDIUM_THRESHOLD = 0.40

# Reference AUM for log-scale normalisation. Anything at/above this becomes
# 1.0 on the AUM axis. ₹10 Cr is a sensible ceiling for retail-HNI land;
# higher than that still wins but with diminishing returns.
AUM_REFERENCE_RS = 10_00_00_000.0


def _normalised_aum(aum_rs: Optional[float]) -> float:
    """log(aum+1) / log(reference+1) — caps at 1.0."""
    if not aum_rs or aum_rs <= 0:
        return 0.0
    return min(1.0, math.log(aum_rs + 1.0) / math.log(AUM_REFERENCE_RS + 1.0))


def _days_since(iso_ts: Optional[str]) -> Optional[int]:
    if not iso_ts:
        return None
    try:
        t = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None
    return (datetime.now(timezone.utc) - t).days


# Map the engine's existing recommendation verbs → severity 0-1.
_RECOMMENDATION_SEVERITY = {
    "exit":          1.0,
    "reduce":        0.8,
    "switch":        0.7,
    "rebalance":     0.5,
    "increase_sip":  0.5,
    "sip_increase":  0.5,
    "top_up":        0.4,
    "add_more":      0.35,
    "add":           0.3,
    "hold":          0.1,
    "":              0.1,
}

# Verb preference order used to pick a *single* dominant action when the
# client has multiple open recommendations — we want the most urgent one
# to win the CTA on the dashboard row.
_VERB_PRIORITY = [
    "exit", "reduce", "switch", "increase_sip", "sip_increase",
    "rebalance", "top_up", "add_more", "add", "hold",
]


def _recommendation_severity(recommendations: List[Dict[str, Any]]) -> float:
    """Take the max severity across the client's active recommendations.
    If none, returns 0.1 (= "no action"). Uses the `action` or `type`
    field on each rec; matches against lowercase keyword tokens."""
    if not recommendations:
        return _RECOMMENDATION_SEVERITY[""]
    best = 0.0
    for r in recommendations:
        verb = str(r.get("action") or r.get("type") or r.get("kind") or "").lower()
        for key, sev in _RECOMMENDATION_SEVERITY.items():
            if key and key in verb:
                best = max(best, sev)
    return best or _RECOMMENDATION_SEVERITY[""]


def _dominant_verb(recommendations: List[Dict[str, Any]]) -> Optional[str]:
    """Pick the single most-urgent verb across active recommendations.
    Returns canonical form ("exit" / "switch" / "rebalance" /
    "increase_sip" / "add" / etc) or None if nothing is open."""
    if not recommendations:
        return None
    seen = set()
    for r in recommendations:
        verb = str(r.get("action") or r.get("type") or r.get("kind") or "").lower()
        for key in _RECOMMENDATION_SEVERITY:
            if key and key in verb:
                seen.add(key)
    for key in _VERB_PRIORITY:
        if key in seen:
            # Collapse synonyms for the UI.
            if key == "sip_increase":
                return "increase_sip"
            if key == "top_up":
                return "add_more"
            return key
    return None


@dataclass
class PriorityResult:
    score: float                     # 0..1
    bucket: str                      # "high" | "medium" | "low"
    factors: Dict[str, float]        # normalised 0..1 per input
    reasons: List[str]               # human-readable bullets
    dominant_action: Optional[str] = None  # canonical verb (exit/switch/rebalance/increase_sip/add_more/add)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "bucket": self.bucket,
            "factors": {k: round(v, 3) for k, v in self.factors.items()},
            "reasons": self.reasons,
            "dominant_action": self.dominant_action,
        }


def compute_priority(
    *,
    portfolio_score: Optional[float] = None,    # 0..100 from V3 engine
    risk_score: Optional[float] = None,         # 0..100 from existing engine
    aum_rs: Optional[float] = None,
    last_reviewed_at: Optional[str] = None,     # ISO timestamp
    recommendations: Optional[List[Dict[str, Any]]] = None,
    client_name: Optional[str] = None,
) -> PriorityResult:
    """Combine the 5 signals into a single priority score + explainability."""
    # Portfolio weakness — inverse of score. Unknown → 0.5 (neutral, not
    # extreme) so new clients don't auto-bubble to the top just because
    # they're unscored.
    if portfolio_score is None:
        weakness = 0.5
    else:
        weakness = max(0.0, min(1.0, (100.0 - float(portfolio_score)) / 100.0))

    if risk_score is None:
        risk = 0.3                                    # default "moderate"
    else:
        risk = max(0.0, min(1.0, float(risk_score) / 100.0))

    aum = _normalised_aum(aum_rs)

    days = _days_since(last_reviewed_at)
    if days is None:
        # Never reviewed — treat as 30-day-stale (caps at 1.0).
        recency = 1.0
    else:
        recency = min(1.0, max(0.0, days / 30.0))

    rec_sev = _recommendation_severity(recommendations or [])
    dominant = _dominant_verb(recommendations or [])

    score = (
        W_WEAKNESS * weakness
        + W_RISK    * risk
        + W_AUM     * aum
        + W_RECENCY * recency
        + W_REC_SEV * rec_sev
    )

    if score >= HIGH_THRESHOLD:
        bucket = "high"
    elif score >= MEDIUM_THRESHOLD:
        bucket = "medium"
    else:
        bucket = "low"

    # ── Explainability — build bullets only for factors that meaningfully
    # pushed the client up the queue. The UI renders these inside a tooltip.
    reasons: List[str] = []
    if portfolio_score is not None and portfolio_score < 70:
        reasons.append(
            f"Portfolio score is low ({portfolio_score:.0f}/100)"
        )
    if risk_score is not None and risk_score >= 60:
        reasons.append(f"High exposure risk ({risk_score:.0f}/100)")
    if aum_rs and aum_rs >= 10_00_000:       # ≥ ₹10 L signals business impact
        reasons.append(
            f"Book impact: AUM ₹{_fmt_rs(aum_rs)}"
        )
    if days is None:
        reasons.append("Not yet reviewed — first visit pending")
    elif days >= 30:
        reasons.append(f"Not reviewed in {days} days")
    if rec_sev >= 0.7:
        reasons.append("Urgent recommendation pending (exit / switch)")
    elif rec_sev >= 0.4:
        reasons.append("Rebalancing recommendation pending")
    # Always have at least one reason so the tooltip isn't empty.
    if not reasons:
        reasons.append("Stable portfolio, no urgent action")

    return PriorityResult(
        score=score, bucket=bucket,
        factors={
            "portfolio_weakness": weakness,
            "risk": risk,
            "aum": aum,
            "recency": recency,
            "recommendation_severity": rec_sev,
        },
        reasons=reasons,
        dominant_action=dominant,
    )


def _fmt_rs(n: float) -> str:
    """Human-readable INR for reasons strings."""
    if n >= 1e7:
        return f"{n / 1e7:.2f} Cr"
    if n >= 1e5:
        return f"{n / 1e5:.2f} L"
    return f"{int(round(n)):,}"
