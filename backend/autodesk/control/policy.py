"""Policy rules (PRD §5.1, §10.1): defaults, most-restrictive merge, and who may loosen what.

Defaults are the risk-profile defaults (services.risk_profile OWNER_DEFAULT, owner decisions of 27 Oct and 5 Nov), as
encoded in contracts.PolicyBody. A user may tighten any limit; making a limit looser than the default needs an admin
(the risk-profile rule the owner chose for paper trading).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..contracts import AutonomyRules, PolicyBody

# lower value = stricter
UPPER_LIMITS = ("per_trade_risk_pct", "open_risk_pct", "position_pct", "sector_pct", "daily_loss_pct",
                "weekly_loss_pct", "max_drawdown_pct", "max_margin_utilization_pct", "max_proposals_per_session",
                "max_legs", "max_lots_per_leg", "max_data_age_sessions")
# higher value = stricter (a higher futures margin estimate is the more conservative one)
LOWER_LIMITS = ("min_reward_risk", "credit_min_width_fraction", "min_signal_score", "min_days_to_expiry",
                "min_adv_rs", "futures_margin_pct")
LISTS = ("allowed_segments", "allowed_strategies")       # fewer = stricter


def default_policy_body() -> PolicyBody:
    return PolicyBody()


def from_risk_limits(limits: dict[str, Any]) -> PolicyBody:
    """Map a services.risk_profile limits dict (percent fields) onto a policy. Unknown keys are ignored."""
    m = {"per_trade_risk_pct": "per_trade_risk_pct", "open_risk_pct": "open_risk_pct", "position_pct": "position_pct",
         "sector_pct": "sector_pct", "daily_loss_pct": "daily_loss_pct", "weekly_loss_pct": "weekly_loss_pct",
         "max_drawdown_pct": "max_drawdown_pct", "min_reward_risk": "min_reward_risk"}
    data = PolicyBody().model_dump()
    for src, dst in m.items():
        if limits.get(src) is not None:
            data[dst] = Decimal(str(limits[src]))
    data["source"] = "risk-profile"
    return PolicyBody.model_validate(data)


def is_looser(base: PolicyBody, new: PolicyBody) -> list[str]:
    """Fields where `new` is looser than `base`."""
    out: list[str] = []
    for f in UPPER_LIMITS:
        if getattr(new, f) > getattr(base, f):
            out.append(f)
    for f in LOWER_LIMITS:
        if getattr(new, f) < getattr(base, f):
            out.append(f)
    for f in LISTS:
        if set(getattr(new, f)) - set(getattr(base, f)):
            out.append(f)
    if base.require_traded_legs and not new.require_traded_legs:
        out.append("require_traded_legs")
    a, b = base.autonomy, new.autonomy
    if b.auto_approve and not a.auto_approve:
        out.append("autonomy.auto_approve")
    if b.max_risk_pct > a.max_risk_pct:
        out.append("autonomy.max_risk_pct")
    if b.min_signal_score < a.min_signal_score:
        out.append("autonomy.min_signal_score")
    if set(b.strategies) - set(a.strategies):
        out.append("autonomy.strategies")
    return out


def validate_change(old: PolicyBody, new: PolicyBody, *, is_admin: bool) -> None:
    """Raise PermissionError when a non-admin makes any limit looser than the default. Tightening, and loosening
    back towards the default, are allowed for the user."""
    looser = is_looser(default_policy_body(), new)
    if looser and not is_admin:
        raise PermissionError("looser than the default needs an admin: " + ", ".join(looser))


def effective(*bodies: PolicyBody) -> PolicyBody:
    """The most restrictive combination of the applicable policies (tenant, account, strategy, segment)."""
    if not bodies:
        return default_policy_body()
    data = bodies[0].model_dump()
    for b in bodies[1:]:
        for f in UPPER_LIMITS:
            data[f] = min(data[f], getattr(b, f))
        for f in LOWER_LIMITS:
            data[f] = max(data[f], getattr(b, f))
        for f in LISTS:
            data[f] = [x for x in data[f] if x in getattr(b, f)]
        data["require_traded_legs"] = data["require_traded_legs"] or b.require_traded_legs
        a = data["autonomy"]
        data["autonomy"] = {"auto_approve": a["auto_approve"] and b.autonomy.auto_approve,
                            "max_risk_pct": min(a["max_risk_pct"], b.autonomy.max_risk_pct),
                            "min_signal_score": max(a["min_signal_score"], b.autonomy.min_signal_score),
                            "strategies": [s for s in a["strategies"] if s in b.autonomy.strategies]}
    data["source"] = "effective(" + ", ".join(b.source for b in bodies) + ")"
    data["autonomy"] = AutonomyRules.model_validate(data["autonomy"])
    return PolicyBody.model_validate(data)
