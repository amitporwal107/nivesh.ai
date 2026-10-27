"""The per-account risk profile: the limits the universal risk service (services/risk_gate/service.py) enforces, the
capital basis they are measured against, and an audited setter (Phase 1 item 1.5, decision D1, owner defaults §9.3).

CAPITAL BASIS
Every percentage limit is measured against the account's PAPER EQUITY: paper cash plus the net unrealised P&L of the
open positions at their latest end-of-day marks (each position's P&L net of its estimated round-trip costs). Paper
cash starts at the account's starting capital, Rs 10,00,000 — a SIMULATION DEFAULT, labelled as such, not a figure
anyone chose for a real account — and moves only by closed trades' net P&L and by reconciliation entries
(services/paper_account.py). When any open position cannot be marked, equity is unknown and every limit that needs it
blocks (fail closed); it is never estimated from a partial sum.

THE LIMITS (owner defaults, 2026-10-27; `DEFINITIONS` below is the reference text the API and the screen show)
    per_trade_risk_pct   0.5   estimated risk of ONE new entry (stop loss + round-trip costs + gap stress,
                               services/risk_gate/estimate.py) as % of paper equity
    max_open_risk_pct    3     estimated risk of all open positions plus the new one, % of paper equity
    max_position_pct     10    market exposure (notional) of one position, % of paper equity
    max_sector_pct       25    market exposure of one sector, all positions in it plus the new one, % of paper equity
    daily_loss_pct       2     loss since the start of the IST trading day, realised + unrealised, net of costs, % of
                               start-of-day equity; at or past it new entries are blocked for the rest of the day
    weekly_loss_pct      4     the same from the start of the ISO week (Monday, IST), % of start-of-week equity
    max_drawdown_pct     10    fall from the configured equity peak (the starting capital, raised by every higher
                               equity observed, never lowered and never reset daily); at or past it new entries are
                               blocked until a person resets it — open positions are NOT closed
    min_reward_risk      1.5   planned reward : planned risk, both after estimated costs (reward = gain at the target
                               less costs; risk = loss at the stop plus costs)
Exposure and loss-at-stop are different limits on purpose: a tight stop on a large position keeps the loss small and
the exposure large, and the second is what a gap or a halt hits.

The engineering proposal (1 / 6 / 10 / 30 / 3 / 6 / 15 / 1.5) stays available as the named comparison profile
`engineering-comparison`; it is looser on every limit, so only an admin can switch an account to it.

THE SETTER (modelled on services/risk_controls.set_control)
A reason is required for every change. The account holder may TIGHTEN any limit; LOOSENING any one needs an admin
(the signed-in person; under impersonation the session owner). The audit row (who, when, every field before -> after,
the reason, the new version) is written BEFORE the profile changes, so a crash leaves a visible attempt, never a silent
change. The profile carries a version that every change increments (compare-and-set on it, so two concurrent changes
cannot both apply), and `effective_from` = the moment the change took effect. Decisions record `limits_version`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROFILES = "risk_profiles"
AUDIT = "risk_profile_audit"
PROFILE_POLICY_VERSION = "risk-profile-v1"
MAX_AUDIT_LISTED = 200

SIMULATION_STARTING_CAPITAL_RS = 1_000_000.0
STARTING_CAPITAL_LABEL = "simulation default (Rs 10,00,000): the paper account's opening cash, not a real account's capital"
CAPITAL_BASIS = "paper_equity"
CAPITAL_BASIS_TEXT = ("paper equity = paper cash + net unrealised P&L of the open positions at their latest end-of-day "
                      "marks (net of estimated round-trip costs); unknown when any open position cannot be marked")

FIELDS = ("per_trade_risk_pct", "max_open_risk_pct", "max_position_pct", "max_sector_pct", "daily_loss_pct",
          "weekly_loss_pct", "max_drawdown_pct", "min_reward_risk")
#: A larger value of these is LOOSER; for min_reward_risk a smaller value is looser.
HIGHER_IS_TIGHTER = {"min_reward_risk"}
RANGES = {
    "per_trade_risk_pct": (0.05, 5.0),
    "max_open_risk_pct": (0.1, 50.0),
    "max_position_pct": (0.5, 100.0),
    "max_sector_pct": (1.0, 100.0),
    "daily_loss_pct": (0.1, 20.0),
    "weekly_loss_pct": (0.1, 40.0),
    "max_drawdown_pct": (1.0, 50.0),
    "min_reward_risk": (0.5, 10.0),
}

OWNER_DEFAULT = "owner-default-2026-10-27"
ENGINEERING = "engineering-comparison"
NAMED: Dict[str, Dict[str, float]] = {
    OWNER_DEFAULT: {"per_trade_risk_pct": 0.5, "max_open_risk_pct": 3.0, "max_position_pct": 10.0,
                    "max_sector_pct": 25.0, "daily_loss_pct": 2.0, "weekly_loss_pct": 4.0, "max_drawdown_pct": 10.0,
                    "min_reward_risk": 1.5},
    ENGINEERING: {"per_trade_risk_pct": 1.0, "max_open_risk_pct": 6.0, "max_position_pct": 10.0,
                  "max_sector_pct": 30.0, "daily_loss_pct": 3.0, "weekly_loss_pct": 6.0, "max_drawdown_pct": 15.0,
                  "min_reward_risk": 1.5},
}
NAMED_TEXT = {
    OWNER_DEFAULT: "The product owner's paper-risk defaults (2026-10-27). Research defaults, not validated optimal values.",
    ENGINEERING: "The engineering proposal kept for comparison (study §7 D1). Looser on every limit.",
}

DEFINITIONS: Dict[str, Dict[str, str]] = {
    "per_trade_risk_pct": {
        "label": "Risk per trade",
        "basis": "estimated risk of the new entry = quantity x |entry - stop| + round-trip costs (desk-cost-v2) + gap "
                 "stress (services/risk_gate/estimate.py), as % of paper equity; options: maximum loss of the whole "
                 "structure from its payoff plus costs",
        "reset": "none: judged per entry",
        "breach": "the size is REDUCED to the largest valid quantity or lot count within the budget; if even the "
                  "smallest valid quantity exceeds it, the entry is BLOCKED (min_qty_exceeds_budget)"},
    "max_open_risk_pct": {
        "label": "Total open risk",
        "basis": "estimated risk reserved by every open position (paper_accounts.open_risk_rs, plus positions opened "
                 "before Phase 1 at their stored levels) plus the new entry, as % of paper equity",
        "reset": "falls as positions close, are cancelled or expire",
        "breach": "REDUCED to fit the remaining budget, else BLOCKED (open_risk_exceeded)"},
    "max_position_pct": {
        "label": "Position exposure",
        "basis": "market exposure (notional: quantity x entry for shares, futures notional and the options' capital "
                 "at risk for a structure) of the new position, as % of paper equity",
        "reset": "none: judged per entry",
        "breach": "REDUCED to fit, else BLOCKED (POSITION_SIZE / position_exceeded)"},
    "max_sector_pct": {
        "label": "Sector exposure",
        "basis": "market exposure of every open position in the instrument's sector (NSE industry classification) "
                 "plus the new one, as % of paper equity; a position with no known sector blocks the entry",
        "reset": "falls as positions in the sector close",
        "breach": "REDUCED to fit, else BLOCKED (sector_exceeded)"},
    "daily_loss_pct": {
        "label": "Daily loss halt",
        "basis": "loss since the start of the IST trading day: net realised P&L of trades closed today plus the "
                 "change in net unrealised P&L of the positions held since the previous session's close, as % of "
                 "start-of-day equity",
        "reset": "the next IST trading day (weekday calendar)",
        "breach": "new entries BLOCKED for the rest of the day (daily_loss_halt); open positions untouched"},
    "weekly_loss_pct": {
        "label": "Weekly loss halt",
        "basis": "the same loss measured from the close of the last session before Monday of the ISO week (IST), as "
                 "% of start-of-week equity",
        "reset": "Monday, IST",
        "breach": "new entries BLOCKED until the week resets (weekly_loss_halt); open positions untouched"},
    "max_drawdown_pct": {
        "label": "Drawdown halt",
        "basis": "fall of paper equity from the configured equity peak: the starting capital, raised by every higher "
                 "equity the risk service observes, never lowered",
        "reset": "never resets daily; only a person (an admin) resets the peak or loosens the limit",
        "breach": "new entries BLOCKED (drawdown_halt); open positions are NOT liquidated"},
    "min_reward_risk": {
        "label": "Minimum reward:risk",
        "basis": "(gain at the target - estimated costs) / (loss at the stop + estimated costs); options: maximum "
                 "gain at expiry over maximum loss, both after costs; unbounded gain passes",
        "reset": "none: judged per entry",
        "breach": "BLOCKED (reward_risk_too_low); an entry with no target where one is needed is BLOCKED "
                  "(target_required)"},
}


class ProfileError(ValueError):
    """Bad input to a profile change; the caller answers 422 (or 403 for `admin_required`)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def detail(self) -> Dict[str, Any]:
        return {"code": self.code, "message": str(self)}


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


def limits_version(name: str, version: int, limits: Dict[str, float]) -> str:
    """`rp-<version>-<hash8>`: the stored version counter and a hash of the values, so a decision names exactly the
    limits it was judged by even across accounts."""
    digest = hashlib.sha256(json.dumps({k: limits[k] for k in FIELDS}, sort_keys=True).encode()).hexdigest()[:8]
    return f"rp-{version}-{digest}"


def default_state(user_id: str) -> Dict[str, Any]:
    """An account with no stored profile: the owner defaults, said explicitly (`stored: false`)."""
    limits = dict(NAMED[OWNER_DEFAULT])
    return {
        "user_id": user_id,
        "profile": OWNER_DEFAULT,
        "limits": limits,
        "version": 0,
        "limits_version": limits_version(OWNER_DEFAULT, 0, limits),
        "capital_basis": CAPITAL_BASIS,
        "capital_basis_text": CAPITAL_BASIS_TEXT,
        "starting_capital_rs": SIMULATION_STARTING_CAPITAL_RS,
        "starting_capital_label": STARTING_CAPITAL_LABEL,
        "effective_from": None,
        "set_by": None,
        "set_at": None,
        "reason": None,
        "stored": False,
        "policy_version": PROFILE_POLICY_VERSION,
    }


def public(doc: Optional[Dict[str, Any]], user_id: str) -> Dict[str, Any]:
    if not doc:
        return default_state(user_id)
    limits = {k: float(doc.get("limits", {}).get(k, NAMED[OWNER_DEFAULT][k])) for k in FIELDS}
    version = int(doc.get("version") or 0)
    name = doc.get("profile") or "custom"
    return {
        **default_state(user_id),
        "profile": name,
        "limits": limits,
        "version": version,
        "limits_version": limits_version(name, version, limits),
        "starting_capital_rs": float(doc.get("starting_capital_rs") or SIMULATION_STARTING_CAPITAL_RS),
        "effective_from": doc.get("effective_from"),
        "set_by": doc.get("set_by"),
        "set_at": doc.get("set_at"),
        "reason": doc.get("reason"),
        "stored": True,
    }


async def read(db, user_id: str) -> Dict[str, Any]:
    """The profile; raises when the store cannot be read (the risk service then blocks: an unreadable limit is never
    read as the default)."""
    return public(await db[PROFILES].find_one({"user_id": user_id}), user_id)


def _number(field: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ProfileError("invalid_input", f"{field} must be a number")
    low, high = RANGES[field]
    if not low <= float(value) <= high:
        raise ProfileError("invalid_input", f"{field} must be between {low:g} and {high:g}")
    return round(float(value), 4)


def is_looser(field: str, before: float, after: float) -> bool:
    if field in HIGHER_IS_TIGHTER:
        return after < before
    return after > before


def plan_change(current: Dict[str, float], *, changes: Optional[Dict[str, Any]] = None,
                profile: Optional[str] = None) -> Dict[str, float]:
    """The limits after the change (validated). Exactly one of `changes` (some fields) or `profile` (a named set)."""
    if (changes is None) == (profile is None):
        raise ProfileError("invalid_input", "send either `changes` (some limits) or `profile` (a named profile)")
    if profile is not None:
        if profile not in NAMED:
            raise ProfileError("invalid_input", f"unknown profile; one of {', '.join(NAMED)}")
        after = dict(NAMED[profile])
    else:
        if not isinstance(changes, dict) or not changes:
            raise ProfileError("invalid_input", "`changes` must name at least one limit")
        unknown = set(changes) - set(FIELDS)
        if unknown:
            raise ProfileError("invalid_input", f"unknown limit(s): {', '.join(sorted(unknown))}")
        after = dict(current)
        for field, value in changes.items():
            after[field] = _number(field, value)
    if after["max_open_risk_pct"] < after["per_trade_risk_pct"]:
        raise ProfileError("invalid_input", "total open risk cannot be below the risk per trade")
    if after["weekly_loss_pct"] < after["daily_loss_pct"]:
        raise ProfileError("invalid_input", "the weekly loss halt cannot be below the daily loss halt")
    return after


async def set_limits(db, user_id: str, *, reason: Any, actor: str, actor_is_admin: bool,
                     changes: Optional[Dict[str, Any]] = None, profile: Optional[str] = None,
                     now: Optional[datetime] = None) -> Dict[str, Any]:
    """Change the account's limits. Returns the new public profile. Raises ProfileError: invalid_input,
    admin_required (a loosening by a non-admin), no_change, or concurrent_change (another change landed first)."""
    from services import risk_controls as rc            # the reason rule is the controls' own

    try:
        text = rc.clean_reason(reason, required=True)
    except rc.RiskControlError as e:
        raise ProfileError("invalid_input", str(e)) from e
    doc = await db[PROFILES].find_one({"user_id": user_id})
    before = public(doc, user_id)
    after = plan_change(before["limits"], changes=changes, profile=profile)
    changed = {f: {"before": before["limits"][f], "after": after[f]} for f in FIELDS if after[f] != before["limits"][f]}
    if not changed:
        raise ProfileError("no_change", "the limits are already set to these values")
    looser = sorted(f for f, c in changed.items() if is_looser(f, c["before"], c["after"]))
    if looser and not actor_is_admin:
        raise ProfileError("admin_required", "Only an admin can loosen a risk limit ("
                                             + ", ".join(DEFINITIONS[f]["label"] for f in looser)
                                             + "). You can tighten any limit yourself.")
    moment = _iso(now)
    version = before["version"] + 1
    name = profile or (doc or {}).get("profile") or OWNER_DEFAULT
    if profile is None and after != NAMED.get(name, {}):
        name = "custom"
    await db[AUDIT].insert_one({
        "_id": str(uuid.uuid4()),
        "user_id": user_id,
        "at": moment,
        "actor": actor,
        "actor_is_admin": bool(actor_is_admin),
        "action": "set_profile" if profile else "set_limits",
        "profile_before": before["profile"],
        "profile_after": name,
        "changes": changed,
        "loosened": looser,
        "reason": text,
        "version_before": before["version"],
        "version_after": version,
        "limits_version_after": limits_version(name, version, after),
        "effective_from": moment,
        "policy_version": PROFILE_POLICY_VERSION,
    })
    fields = {"limits": after, "profile": name, "version": version, "effective_from": moment, "set_by": actor,
              "set_at": moment, "reason": text, "policy_version": PROFILE_POLICY_VERSION}
    if doc is None:
        try:
            await db[PROFILES].insert_one({"_id": str(uuid.uuid4()), "user_id": user_id,
                                           "starting_capital_rs": SIMULATION_STARTING_CAPITAL_RS,
                                           "created_at": moment, **fields})
        except Exception as e:  # noqa: BLE001 — a concurrent first change won; nothing of ours applied
            raise ProfileError("concurrent_change", "another change to this profile landed first; reload and retry") from e
    else:
        res = await db[PROFILES].update_one({"user_id": user_id, "version": before["version"]}, {"$set": fields})
        if not res.matched_count:
            raise ProfileError("concurrent_change", "another change to this profile landed first; reload and retry")
    logger.warning("risk_profile: %s changed %s for %s (%s)", actor, sorted(changed), user_id, text)
    return await read(db, user_id)


async def audit_rows(db, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    cur = db[AUDIT].find({"user_id": user_id}).sort("at", -1).limit(min(limit, MAX_AUDIT_LISTED))
    rows = await cur.to_list(min(limit, MAX_AUDIT_LISTED))
    for r in rows:
        r.pop("_id", None)
    return rows


def catalogue() -> Dict[str, Any]:
    return {"definitions": DEFINITIONS, "named_profiles": {k: {"limits": v, "text": NAMED_TEXT[k]} for k, v in NAMED.items()},
            "ranges": {k: list(v) for k, v in RANGES.items()}, "fields": list(FIELDS),
            "capital_basis": CAPITAL_BASIS, "capital_basis_text": CAPITAL_BASIS_TEXT,
            "starting_capital_label": STARTING_CAPITAL_LABEL, "policy_version": PROFILE_POLICY_VERSION}
