"""The Paper Trading policy: ONE view and ONE write over the two stores that hold an account's limits
(docs/scanner_paper_trading/UI_DESIGN_V2.md §3, §4 item 2, §7).

FIELDS (the §7 keys) and where each is stored:
    per_trade_risk_pct    risk profile  per_trade_risk_pct            (services/risk_profile.py)
    max_open_risk_pct     risk profile  max_open_risk_pct
    daily_loss_pct        risk profile  daily_loss_pct
    weekly_loss_pct       risk profile  weekly_loss_pct
    halt_at_pct           risk profile  max_drawdown_pct
    max_position_pct      risk profile  max_position_pct
    max_sector_pct        risk profile  max_sector_pct
    restrict_at_pct       SPT config    drawdown_ladder.restrict_at_pct (services/spt/policy.py)
    margin_util_pct       SPT config    margin_util_pct
    fno_max_loss_pct      SPT config    fno_max_loss_pct
    bucket_positional_pct SPT config    allocation_buckets_pct.equity_positional
    bucket_intraday_pct   SPT config    allocation_buckets_pct.equity_intraday
    bucket_fno_pct        SPT config    allocation_buckets_pct.fno
    max_positions         SPT config    max_positions
The unallocated reserve is derived: 100 − the three buckets. It is written to allocation_buckets_pct.reserve (SPT's
config requires the four to total 100), and its override is dropped when it equals the default.

THE COMBINED VERSION = the risk profile's `version` + the SPT config's `version`. Nothing new is stored: each counter
only ever rises, by one per change, so the sum strictly increases with every change to either store and names exactly one
state in the account's history. A PUT carries `expected_version` (the sum it was drafted on): a different sum → 409
version_conflict. Each store's own compare-and-set is then given the exact version read (risk_profile.set_limits
`expected_version`, policy.update `expected_version`), so a change landing between this check and the write is refused
by the store, never overwritten. A mode change (PUT …/config) moves the SPT counter, so it moves this version too.

THE WRITE (`write`), in this order — nothing is written until every check has passed:
    1. read both stores; expected_version must equal the combined version (409 version_conflict)
    2. validate every value: known key, a number or null, within its store's range (whole number for max_positions),
       the three buckets ≤ 100 (reserve ≥ 0), halt above restricted, and each store's own cross-rules (max open risk ≥
       risk per trade, weekly ≥ daily loss, the drawdown ladder rising) — 422 {code, field, message}
    3. permission: the account holder may tighten anything; loosening needs an admin (403 {code: admin_required,
       loosened: [keys]}) and a reason (422 reason_required). "Looser" is each store's own rule; for the buckets it is the
       reserve falling (SPT's rule), named by the bucket keys that rose
    4. write the two stores, one after the other. ORDER: the SPT config first when its new overrides are valid under the
       profile as it is now (then each store judges "looser" against the same state step 3 did); otherwise — a drawdown
       ladder that is valid only under the new halt — the risk profile first. If the second write fails, the first is
       RESTORED to what step 1 read (the profile through set_limits, the SPT config through policy.update with the old
       overrides; each with a "rollback" reason, as an admin action, compare-and-set on the version just written) and the
       request answers with the second store's refusal (409 version_conflict, its 403 / 422 code) or 500
       policy_write_failed, with rolled_back: true. A restore that cannot land answers 500 policy_rollback_failed and
       names what is left. In the profile-first order the SPT store judges its override against the NEW profile's
       defaults, so a restricted level above ⅔ of a lowered halt (and under ⅓ of the old one) is an admin's change.
    There is no multi-document transaction (staging Mongo is a single node, DESIGN D7): the restore is the compensation.

UNCHANGED VALUES: a value equal to the one in force is dropped before anything else — it is not a change, never pins an
SPT override and never rewrites the profile (a draft may send every field). Only a different value, or null, changes.

NULL = back to the default: an SPT field drops its override (the profile-derived default); a risk-profile field goes
back to the owner default profile's value (risk_profile.OWNER_DEFAULT).

REASON: every risk-profile change needs one (its own rule). The account holder's PUT may omit it when it only tightens;
the stored reason is then DEFAULT_REASON. A loosening needs a reason; the admin route always needs one.
"""
from __future__ import annotations

import copy
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from services import risk_profile

from . import policy

logger = logging.getLogger(__name__)

VIEW_VERSION = "paper-policy-v1"
DEFAULT_REASON = "Paper Trading › policy panel (no reason entered)"
RESERVE_PATH = "allocation_buckets_pct.reserve"
PROFILE, SPT = "risk_profile", "spt"
VERSION_BASIS = ("risk profile version + SPT config version (each rises by one per change, so the sum names one state "
                 "of the account's policy)")


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    store: str
    path: str
    unit: str
    step: float


FIELDS: Tuple[Field, ...] = (
    Field("per_trade_risk_pct", "Risk per trade", PROFILE, "per_trade_risk_pct", "%", 0.05),
    Field("max_open_risk_pct", "Max total open risk", PROFILE, "max_open_risk_pct", "%", 0.1),
    Field("daily_loss_pct", "Daily loss limit", PROFILE, "daily_loss_pct", "%", 0.1),
    Field("weekly_loss_pct", "Weekly loss limit", PROFILE, "weekly_loss_pct", "%", 0.1),
    Field("restrict_at_pct", "Drawdown restricted at", SPT, "drawdown_ladder.restrict_at_pct", "%", 0.1),
    Field("halt_at_pct", "Trading halt at", PROFILE, "max_drawdown_pct", "%", 0.1),
    Field("max_position_pct", "Max single stock", PROFILE, "max_position_pct", "%", 0.5),
    Field("max_sector_pct", "Max sector exposure", PROFILE, "max_sector_pct", "%", 0.5),
    Field("margin_util_pct", "Max margin utilization", SPT, "margin_util_pct", "%", 1.0),
    Field("fno_max_loss_pct", "F&O max loss per strategy", SPT, "fno_max_loss_pct", "%", 0.05),
    Field("bucket_positional_pct", "Equity positional", SPT, "allocation_buckets_pct.equity_positional", "%", 1.0),
    Field("bucket_intraday_pct", "Equity intraday", SPT, "allocation_buckets_pct.equity_intraday", "%", 1.0),
    Field("bucket_fno_pct", "F&O strategies", SPT, "allocation_buckets_pct.fno", "%", 1.0),
    Field("max_positions", "Max open positions", SPT, "max_positions", "", 1.0),
)
BY_KEY: Dict[str, Field] = {f.key: f for f in FIELDS}
KEYS: Tuple[str, ...] = tuple(f.key for f in FIELDS)
BUCKET_KEYS = ("bucket_positional_pct", "bucket_intraday_pct", "bucket_fno_pct")


class PolicyError(Exception):
    """A refused policy read or write; `status` is the HTTP status, `detail()` the body's detail."""

    def __init__(self, status: int, code: str, message: str, *, field: Optional[str] = None,
                 extra: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.status, self.code, self.field, self.extra = status, code, field, extra or {}

    def detail(self) -> Dict[str, Any]:
        return {"code": self.code, "field": self.field, "message": str(self), **self.extra}


# ── pure: values, defaults, ranges ───────────────────────────────────────────
def _num(x: Any) -> Optional[float]:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        return None
    return float(x)


def bounds(f: Field) -> Tuple[float, float, bool]:
    """(low, high, whole number?) from the field's own store."""
    if f.store == PROFILE:
        low, high = risk_profile.RANGES[f.path]
        return float(low), float(high), False
    low, high, integer = policy.RANGES[f.path]
    return float(low), float(high), bool(integer)


def combined_version(profile_pub: Dict[str, Any], spt_cfg: Dict[str, Any]) -> int:
    return int(profile_pub.get("version") or 0) + int(spt_cfg.get("version") or 0)


def values_of(profile_pub: Dict[str, Any], spt_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """The effective value of every key."""
    limits = profile_pub["limits"]
    out: Dict[str, Any] = {}
    for f in FIELDS:
        out[f.key] = limits[f.path] if f.store == PROFILE else policy._get(spt_cfg["extras"], f.path)
    return out


def defaults_of(spt_cfg: Dict[str, Any]) -> Dict[str, Any]:
    owner = risk_profile.NAMED[risk_profile.OWNER_DEFAULT]
    return {f.key: (owner[f.path] if f.store == PROFILE else policy._get(spt_cfg["defaults"], f.path)) for f in FIELDS}


def _looser_when(f: Field) -> str:
    if f.key in BUCKET_KEYS:
        return "reserve_falls"
    if f.store == PROFILE:
        return "lower" if f.path in risk_profile.HIGHER_IS_TIGHTER else "higher"
    return "lower" if f.path in policy.LOWER_IS_LOOSER else "higher"


def reserve_of(vals: Dict[str, Any]) -> Optional[float]:
    parts = [_num(vals.get(k)) for k in BUCKET_KEYS]
    return None if any(p is None for p in parts) else round(100.0 - sum(parts), 4)


def view(profile_pub: Dict[str, Any], spt_cfg: Dict[str, Any], state: Optional[Dict[str, Any]] = None
         ) -> Dict[str, Any]:
    """The GET body (§7) from the two stores' public states and, for `derived`, the account state
    (services/spt/allocation.account_state; None → the money figures are null with a reason). Pure."""
    vals = values_of(profile_pub, spt_cfg)
    defs = defaults_of(spt_cfg)
    overrides = spt_cfg.get("overrides") or {}
    fields: Dict[str, Any] = {}
    for f in FIELDS:
        low, high, _ = bounds(f)
        if f.store == PROFILE:
            overridden = abs(float(vals[f.key]) - float(defs[f.key])) > 1e-9
        else:
            overridden = policy._get(overrides, f.path) is not None
        fields[f.key] = {"value": vals[f.key], "default": defs[f.key], "min": low, "max": high, "step": f.step,
                         "unit": f.unit, "store": f.store, "overridden": overridden,
                         "loosen_needs_admin": True, "looser_when": _looser_when(f), "label": f.label,
                         "path": f.path}
    reserve = reserve_of(vals)
    equity = _num((state or {}).get("equity_rs"))
    open_risk = _num((state or {}).get("open_risk_rs"))
    derived: Dict[str, Any] = {"reserve_pct": reserve, "risk_budget_left_pct": None, "risk_budget_left_rs": None,
                               "per_trade_risk_rs": None, "equity_rs": equity, "reason": None}
    if equity is None or equity <= 0:
        why = (state or {}).get("error") or "; ".join((state or {}).get("equity_unknown_reasons") or []) \
            or ("the account was not read" if state is None else "no mark for an open position")
        derived["reason"] = f"Paper equity is unknown ({why}), so the rupee figures cannot be worked out."
    else:
        derived["per_trade_risk_rs"] = round(equity * float(vals["per_trade_risk_pct"]) / 100.0, 2)
        if open_risk is None:
            derived["reason"] = "The open risk could not be read."
        else:
            left_rs = equity * float(vals["max_open_risk_pct"]) / 100.0 - open_risk
            derived["risk_budget_left_rs"] = round(left_rs, 2)
            derived["risk_budget_left_pct"] = round(left_rs / equity * 100.0, 4)
    stamps = [(profile_pub.get("set_at"), profile_pub.get("set_by")), (spt_cfg.get("updated_at"), spt_cfg.get("updated_by"))]
    stamps = [s for s in stamps if s[0]]
    saved_at, saved_by = max(stamps, key=lambda s: str(s[0])) if stamps else (None, None)
    notes: List[str] = list(spt_cfg.get("warnings") or [])
    spt_halt = policy._get(spt_cfg["extras"], "drawdown_ladder.halt_at_pct")
    if spt_halt is not None and abs(float(spt_halt) - float(vals["halt_at_pct"])) > 1e-9:
        notes.append(f"The SPT drawdown ladder has its own halt override at {float(spt_halt):g}% (the policy's halt is the "
                     f"risk profile's {float(vals['halt_at_pct']):g}%); the lower of the two stops new entries first.")
    if reserve is not None and reserve < 5.0:
        notes.append(f"The unallocated reserve is {reserve:g}%, under the 5% the design keeps.")
    return {"account_id": spt_cfg.get("account_id") or profile_pub.get("user_id"),
            "version": combined_version(profile_pub, spt_cfg), "version_basis": VERSION_BASIS,
            "saved_at": saved_at, "saved_by": saved_by, "fields": fields, "derived": derived,
            "stores": {PROFILE: {"version": profile_pub.get("version"), "limits_version": profile_pub.get("limits_version"),
                                 "profile": profile_pub.get("profile"), "stored": profile_pub.get("stored")},
                       SPT: {"version": spt_cfg.get("version"), "policy_version": spt_cfg.get("policy_version"),
                             "mode": spt_cfg.get("mode"), "stored": spt_cfg.get("stored")}},
            "defaults_source": {f.key: (f"risk profile owner default ({risk_profile.OWNER_DEFAULT})" if f.store == PROFILE
                                        else (spt_cfg.get("defaults_source") or {}).get(f.path)) for f in FIELDS},
            "notes": notes, "view_version": VIEW_VERSION}


# ── pure: the plan of a write ────────────────────────────────────────────────
@dataclass
class Plan:
    profile_changes: Dict[str, float] = field(default_factory=dict)      # profile field → new value (only changed ones)
    spt_changes: Dict[str, Any] = field(default_factory=dict)            # nested extras for policy.update (None = drop)
    changed: List[str] = field(default_factory=list)                     # §7 keys whose value changes
    loosened: List[str] = field(default_factory=list)                    # §7 keys that loosen
    after_values: Dict[str, Any] = field(default_factory=dict)
    spt_first: bool = False                                              # write order (module docstring, THE WRITE 4)


def _bad(code: str, message: str, key: Optional[str]) -> PolicyError:
    return PolicyError(422, code, message, field=key)


def plan(profile_pub: Dict[str, Any], spt_cfg: Dict[str, Any], values: Any) -> Plan:
    """Validate `values` ({key: number | null}) against both stores and work out what each store must change. Pure.
    Raises PolicyError 422 (invalid_body, unknown_field, invalid_number, out_of_range, reserve_negative,
    halt_not_above_restricted, open_risk_below_per_trade, weekly_below_daily, ladder_not_ascending, no_change)."""
    if not isinstance(values, dict) or not values:
        raise _bad("invalid_body", "`values` must be an object naming at least one field", "values")
    for k in values:
        if k not in BY_KEY:
            raise _bad("unknown_field", f"unknown policy field {k!r}; one of {', '.join(KEYS)}", str(k))
    owner = risk_profile.NAMED[risk_profile.OWNER_DEFAULT]
    before_vals = values_of(profile_pub, spt_cfg)
    clean: Dict[str, Optional[float]] = {}
    for k, v in values.items():
        f = BY_KEY[k]
        if v is None:
            clean[k] = None
            continue
        x = _num(v)
        if x is None:
            raise _bad("invalid_number", f"{f.label} must be a number", k)
        low, high, integer = bounds(f)
        if integer and x != int(x):
            raise _bad("invalid_number", f"{f.label} must be a whole number", k)
        if not low - 1e-12 <= x <= high + 1e-12:
            raise _bad("out_of_range", f"{f.label} must be between {low:g} and {high:g}{f.unit}", k)
        clean[k] = int(x) if integer else round(x, 4)
    # A value equal to the one in force is not a change: it never pins an SPT override (so a draft that sends every
    # field keeps the profile-derived defaults flowing) and never rewrites the profile.
    clean = {k: v for k, v in clean.items() if v is None or abs(float(v) - float(before_vals[k])) > 1e-9}

    # the risk profile after the change
    before_limits = dict(profile_pub["limits"])
    after_limits = dict(before_limits)
    for k, v in clean.items():
        f = BY_KEY[k]
        if f.store == PROFILE:
            after_limits[f.path] = float(owner[f.path]) if v is None else float(v)
    if after_limits["max_open_risk_pct"] < after_limits["per_trade_risk_pct"] - 1e-12:
        raise _bad("open_risk_below_per_trade", "Max total open risk cannot be below the risk per trade.",
                   "max_open_risk_pct" if "max_open_risk_pct" in clean else "per_trade_risk_pct")
    if after_limits["weekly_loss_pct"] < after_limits["daily_loss_pct"] - 1e-12:
        raise _bad("weekly_below_daily", "The weekly loss limit cannot be below the daily loss limit.",
                   "weekly_loss_pct" if "weekly_loss_pct" in clean else "daily_loss_pct")
    profile_changes = {p: after_limits[p] for p in risk_profile.FIELDS if abs(after_limits[p] - before_limits[p]) > 1e-12}

    # the SPT config after the change, with its defaults re-derived from the profile AFTER the change
    spt_changes: Dict[str, Any] = {}
    for k, v in clean.items():
        f = BY_KEY[k]
        if f.store == SPT and k not in BUCKET_KEYS:
            policy._set(spt_changes, f.path, v)
    bucket_touched = [k for k in BUCKET_KEYS if k in clean]
    after_profile = {**profile_pub, "limits": after_limits}
    # defaults under the new profile (the buckets' defaults do not depend on it)
    new_defaults, _ = policy.profile_defaults(after_limits)
    if bucket_touched:
        eff: Dict[str, float] = {}
        for k in BUCKET_KEYS:
            f = BY_KEY[k]
            if k in clean:
                eff[k] = float(policy._get(new_defaults, f.path)) if clean[k] is None else float(clean[k])
                policy._set(spt_changes, f.path, clean[k])
            else:
                eff[k] = float(before_vals[k])
        total = sum(eff.values())
        if total > 100.0 + 1e-9:
            raise _bad("reserve_negative", f"The three buckets add up to {total:g}%; together they cannot exceed 100% "
                                           f"(the unallocated reserve would be {100.0 - total:g}%).", bucket_touched[0])
        reserve = round(100.0 - total, 4)
        default_reserve = float(policy._get(new_defaults, RESERVE_PATH))
        policy._set(spt_changes, RESERVE_PATH, None if abs(reserve - default_reserve) < 1e-9 else reserve)
    try:
        new_overrides = policy.apply_changes(spt_cfg.get("overrides") or {}, spt_changes) if spt_changes \
            else copy.deepcopy(spt_cfg.get("overrides") or {})
    except policy.ConfigError as e:                       # cannot happen after the checks above; mapped all the same
        raise _bad(e.code, str(e), next((k for k in KEYS if BY_KEY[k].path == e.field), e.field)) from e
    after_cfg = policy.public({"overrides": new_overrides, "mode": spt_cfg.get("mode"), "version": spt_cfg.get("version")},
                              spt_cfg.get("user_id") or "", after_profile)
    after_vals = values_of(after_profile, after_cfg)
    restrict = float(after_vals["restrict_at_pct"])
    halt = float(after_vals["halt_at_pct"])
    if not halt > restrict + 1e-9:
        raise _bad("halt_not_above_restricted", f"Halt threshold must sit above the restricted threshold (halt {halt:g}%, "
                                                f"restricted {restrict:g}%).",
                   "halt_at_pct" if "halt_at_pct" in clean else "restrict_at_pct")
    try:
        policy.validate_effective(after_cfg["extras"])
    except policy.ConfigError as e:
        key = "restrict_at_pct" if e.code == "ladder_not_ascending" else "bucket_positional_pct"
        raise _bad(e.code, str(e), key) from e
    changed = [k for k in KEYS if abs(float(after_vals[k]) - float(before_vals[k])) > 1e-9]
    if not profile_changes and new_overrides == (spt_cfg.get("overrides") or {}):
        raise _bad("no_change", "The policy already has these values.", None)
    loosened: List[str] = []
    for k in changed:
        f = BY_KEY[k]
        b, a = before_vals[k], after_vals[k]
        if k in BUCKET_KEYS:
            continue
        if f.store == PROFILE and risk_profile.is_looser(f.path, float(b), float(a)):
            loosened.append(k)
        elif f.store == SPT and policy.is_looser(f.path, b, a):
            loosened.append(k)
    rb, ra = reserve_of(before_vals), reserve_of(after_vals)
    if rb is not None and ra is not None and ra < rb - 1e-9:
        loosened += [k for k in BUCKET_KEYS if float(after_vals[k]) > float(before_vals[k]) + 1e-9]
    if not new_overrides == (spt_cfg.get("overrides") or {}):
        spt_out = spt_changes
    else:
        spt_out = {}
    # Order: the SPT config first when its new overrides are valid under the profile as it is NOW — then both stores
    # judge "looser" against the same state this plan did. Otherwise (a ladder valid only under the new profile) the
    # profile goes first.
    spt_first = False
    if spt_out and profile_changes:
        under_old = policy.public({"overrides": new_overrides}, spt_cfg.get("user_id") or "", profile_pub)
        try:
            policy.validate_effective(under_old["extras"])
            spt_first = True
        except policy.ConfigError:
            spt_first = False
    return Plan(profile_changes=profile_changes, spt_changes=spt_out, changed=changed,
                loosened=[k for k in KEYS if k in set(loosened)], after_values=after_vals, spt_first=spt_first)


# ── reads and the write ──────────────────────────────────────────────────────
async def _stores(db, user_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    try:
        profile_pub = await risk_profile.read(db, user_id)
    except Exception as e:  # noqa: BLE001 — the profile is the authority: an unreadable one is never read as default
        logger.error("policy_view: the risk profile of %s could not be read (%s)", user_id, type(e).__name__)
        raise PolicyError(503, "profile_unreadable", "The risk profile could not be read.") from e
    try:
        doc = await db[policy.C.ACCOUNT_CONFIG].find_one({"_id": user_id})
    except Exception as e:  # noqa: BLE001
        logger.error("policy_view: the SPT config of %s could not be read (%s)", user_id, type(e).__name__)
        raise PolicyError(503, "config_unreadable", "The SPT config could not be read.") from e
    return profile_pub, policy.public(doc, user_id, profile_pub)


async def _state(db, user_id: str, now) -> Optional[Dict[str, Any]]:
    from . import allocation
    try:
        return await allocation.account_state(db, user_id, now=now)
    except Exception as e:  # noqa: BLE001 — the policy still answers; `derived` says the money figures are unknown
        logger.warning("policy_view: account state of %s unreadable (%s)", user_id, type(e).__name__)
        return {"error": f"the account could not be read ({type(e).__name__})"}


async def read(db, user_id: str, *, now) -> Dict[str, Any]:
    profile_pub, spt_cfg = await _stores(db, user_id)
    return view(profile_pub, spt_cfg, await _state(db, user_id, now))


def _clean_reason(reason: Any) -> Optional[str]:
    text = "" if reason is None else str(reason).strip()
    limit = min(policy.MAX_REASON, 500)
    if len(text) > limit:
        raise PolicyError(422, "reason_too_long", f"The reason must be at most {limit} characters.", field="reason")
    return text or None


async def write(db, user_id: str, *, values: Any, expected_version: Any, reason: Any, actor: str,
                actor_is_admin: bool, require_reason: bool, now) -> Dict[str, Any]:
    """The combined write (module docstring). Returns the view after the write. Raises PolicyError."""
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise PolicyError(422, "invalid_number", "expected_version must be the whole-number version the draft was made "
                                                 "from", field="expected_version")
    text = _clean_reason(reason)
    if require_reason and not text:
        raise PolicyError(422, "reason_required", "A reason is required for this change.", field="reason")
    profile_pub, spt_cfg = await _stores(db, user_id)
    current = combined_version(profile_pub, spt_cfg)
    if expected_version != current:
        raise PolicyError(409, "version_conflict", f"The policy is at version {current}, not {expected_version}; reload "
                                                   "and redo the change.", extra={"current_version": current})
    p = plan(profile_pub, spt_cfg, values)
    if p.loosened and not actor_is_admin:
        labels = ", ".join(BY_KEY[k].label for k in p.loosened)
        raise PolicyError(403, "admin_required", f"Only an admin can loosen a limit ({labels}). You can tighten any limit "
                                                 "yourself.", extra={"loosened": p.loosened})
    if p.loosened and not text:
        raise PolicyError(422, "reason_required", "A reason is required to loosen a limit.", field="reason",
                          extra={"loosened": p.loosened})
    stored_reason = text or DEFAULT_REASON
    await policy.ensure_indexes(db)

    async def do_profile() -> Dict[str, Any]:
        return await risk_profile.set_limits(db, user_id, reason=stored_reason, actor=actor, actor_is_admin=actor_is_admin,
                                             changes=dict(p.profile_changes), now=now,
                                             expected_version=int(profile_pub["version"]))

    async def do_spt() -> Dict[str, Any]:
        return await policy.update(db, user_id, actor=actor, actor_is_admin=actor_is_admin, extras=p.spt_changes,
                                   reason=stored_reason, expected_version=int(spt_cfg["version"]), require_reason=False,
                                   now=now)

    steps: List[Tuple[str, Any]] = []
    if p.profile_changes:
        steps.append((PROFILE, do_profile))
    if p.spt_changes:
        steps.append((SPT, do_spt))
    if p.spt_first:
        steps.reverse()
    done: List[Tuple[str, Dict[str, Any]]] = []
    for name, do in steps:
        try:
            done.append((name, await do()))
        except Exception as e:  # noqa: BLE001 — every failure after a first write undoes that write
            code = str(getattr(e, "code", None) or type(e).__name__)
            for prev, written in done:
                await _undo(db, user_id, prev, written, profile_pub=profile_pub, spt_cfg=spt_cfg, actor=actor,
                            code=f"{name}: {code}", now=now)
            raise _mapped(e, name, rolled_back=bool(done)) from e
    logger.warning("policy_view: %s%s changed %s for %s", actor, " (admin)" if actor_is_admin else "", p.changed, user_id)
    return await read(db, user_id, now=now)


def _mapped(e: Exception, store: str, *, rolled_back: bool) -> PolicyError:
    """A store's refusal as the route's answer. `rolled_back`: an earlier write was undone, so nothing changed."""
    what = "risk profile" if store == PROFILE else "SPT config"
    extra = {"rolled_back": True, "written": []} if rolled_back else {}
    after = " The other part was restored, so nothing changed." if rolled_back else " Nothing was changed."
    status = getattr(e, "status", None) or (403 if getattr(e, "code", None) == "admin_required" else
                                            409 if getattr(e, "code", None) == "concurrent_change" else
                                            422 if isinstance(e, risk_profile.ProfileError) else None)
    code = getattr(e, "code", None)
    if status == 409 or code == "concurrent_change":
        return PolicyError(409, "version_conflict", f"The {what} changed while this was being saved; reload and redo the "
                                                    f"change.{after}", extra=extra)
    if status in (403, 422) and code:
        return PolicyError(status, code, f"The {what} refused the change: {str(e).rstrip('.')}.{after}",
                           field=getattr(e, "field", None),
                           extra={**(getattr(e, "extra", None) or {}), **extra})
    return PolicyError(500, "policy_write_failed", f"The {what} part of the policy could not be written "
                                                   f"({code or type(e).__name__}).{after}",
                       extra={"rolled_back": rolled_back, "written": []})


async def _undo(db, user_id: str, store: str, written: Dict[str, Any], *, profile_pub: Dict[str, Any],
                spt_cfg: Dict[str, Any], actor: str, code: str, now) -> None:
    """Put back what `store` held before this request (compare-and-set on the version just written). Raises
    policy_rollback_failed, naming what is left, when that cannot land."""
    why = f"rollback: the Paper Trading policy write failed ({code}); the values in force before it are restored"
    left: List[str] = []
    try:
        if store == PROFILE:
            restore = {f: profile_pub["limits"][f] for f in risk_profile.FIELDS
                       if abs(float(written["limits"][f]) - float(profile_pub["limits"][f])) > 1e-12}
            left = sorted(restore)
            await risk_profile.set_limits(db, user_id, reason=why, actor=f"{actor} (policy rollback)", actor_is_admin=True,
                                          changes=restore, now=now, expected_version=int(written["version"]))
        else:
            old = spt_cfg.get("overrides") or {}
            paths = sorted(set(policy._leaf_paths(written.get("overrides") or {})) | set(policy._leaf_paths(old)))
            reverse: Dict[str, Any] = {}
            for path in paths:
                if policy._get(written.get("overrides") or {}, path) != policy._get(old, path):
                    policy._set(reverse, path, policy._get(old, path))
            left = paths
            await policy.update(db, user_id, actor=f"{actor} (policy rollback)", actor_is_admin=True, extras=reverse,
                                reason=why, expected_version=int(written["version"]), require_reason=False, now=now)
    except Exception as e:  # noqa: BLE001 — loud: the store keeps the new values and the caller is told so
        logger.error("policy_view: ROLLBACK FAILED for %s on the %s (%s)", user_id, store, type(e).__name__)
        raise PolicyError(500, "policy_rollback_failed",
                          f"The policy write failed and its {'risk profile' if store == PROFILE else 'SPT config'} part "
                          f"could not be restored ({type(e).__name__}): it now holds the new values of "
                          f"{', '.join(left)}. Reload and correct it.",
                          extra={"rolled_back": False, "written": left}) from e
