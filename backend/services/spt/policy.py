"""SPT account configuration: the account's mode and the SPT risk extras (DESIGN.md D3, D4; PRD §16.1, §26; WF §25
items 21-22), with the owner's decisions of 5 Nov 2026 ~06:50 IST:
  "Risk Limits make in configurable. The default is as per user risk profile we have already designed for it. And for
   each user make it configurable so admin can change it." · "Agree and make it configurable" (the SPT defaults).

ONE CONFIG PER USER (`spt_account_config`, `_id` = user_id; DESIGN D3: account_id = user_id)
    mode       off (default, D4) | tracking | approval | auto. Nothing is proposed for an account in `off`.
    overrides  ONLY the values set for this account (a sparse nested dict). The effective `extras` are worked out on
               EVERY read as  defaults(the user's risk profile NOW) ⊕ overrides,  so a later profile change flows
               through to every value the account has not overridden. A leaf set to null in a change removes its
               override (back to the default).
    version    +1 on every change; every change first writes a row to `spt_account_config_versions` (who, admin or
               not, when, old and new effective extras + overrides + mode, what was loosened, reason; status attempted →
               applied | superseded), so the history cannot be lost to a crash between the two writes (PRD §18 rule 15).

DEFAULTS (`profile_defaults`): where SPT overlaps the risk profile (services/risk_profile.read) the profile decides:
    drawdown_ladder.halt_at_pct      = profile max_drawdown_pct
    drawdown_ladder.restrict_at_pct  = 2/3 of it, reduce_at_pct = 1/3 of it (the PRD §9.7 2/4/6 proportions), 2 dp
    min_rr.positional                = profile min_reward_risk
    risk_pct.positional              = profile per_trade_risk_pct; risk_pct.intraday and .fno = 0.7 × it (the PRD
                                       §9.4 0.35/0.5), 4 dp
  Everything else is the SPT default, owner-approved 5 Nov 2026: drawdown_ladder.reduce_factor 0.5, max_positions 10,
  max_new_per_day 5, max_chase_pct 1.0, min_adv_rs ₹1 crore, max_adv_participation_pct 5, approval_expiry_minutes 30,
  allocation_buckets_pct 45/25/20/10, stressed_gap_pct (risk_gate.estimate.GAP_STRESS_PCT). `defaults_source` names
  the profile field or "spt-default (owner-approved 5 Nov 2026)" for every leaf.
  F&O extras (Paper Trading v2, docs/scanner_paper_trading/UI_DESIGN_V2.md §3, 5 Nov 2026):
    fno_max_loss_pct  one F&O structure's maximum loss, % of paper equity = profile per_trade_risk_pct × 0.7, the same
                      derivation as risk_pct.fno (owner rule 5 Nov: defaults come from the user's risk profile; PRD §9.4 /
                      §26 "F&O strategy risk 0.35 %"); 0.35 for the owner-default profile
    margin_util_pct   70: the most of paper equity the open F&O structures' exchange margin may use, from the owner's
                      Paper Trading v2 design (5 Nov); the PRD has no figure; configurable
  For the owner-default profile (0.5 / 10 / 1.5): ladder 3.33 / 6.67 / 10, min R:R 1.5, risk 0.5 / 0.35 / 0.35.

WHO MAY CHANGE WHAT (the services/risk_profile model): the account holder may change the mode and TIGHTEN any value;
LOOSENING any value needs an admin (the signed-in person; 403 `admin_required`), and a loosening needs a reason.
Looser, per field (judged on the EFFECTIVE value before and after, so removing an override counts by the value it
falls back to):
    higher is looser   risk_pct.*, drawdown_ladder.reduce_at_pct / restrict_at_pct / halt_at_pct / reduce_factor,
                       max_positions, max_new_per_day, max_adv_participation_pct, max_chase_pct, approval_expiry_minutes,
                       margin_util_pct, fno_max_loss_pct
    lower is looser    min_rr.positional, min_adv_rs, stressed_gap_pct, allocation_buckets_pct.reserve
    neither            allocation_buckets_pct.equity_positional / equity_intraday / fno (moving room between buckets;
                       the reserve and the sum of 100 decide how much is ever allocated)
An admin may set any value within RANGES. A risk % above the profile's per-trade % is accepted from an admin but is
capped where it is used (`effective_risk_pct`; `warnings` says so): the profile's per-trade limit is enforced by the
universal risk service whatever SPT says. `max_positions` cannot exceed the risk service's own 10 and
`max_adv_participation_pct` the governor's 5 % (a looser SPT value would only be cut again by the service).

THE DRAWDOWN LADDER (`ladder`): drawdown below reduce_at → normal; reduce_at..restrict_at → the SPT risk % times
reduce_factor; restrict_at..halt_at → RESTRICTED (new entries blocked); at or past halt_at → HALT (new entries refused,
the account halted for SPT). Exits and risk-reducing changes are never refused by any band. Unknown drawdown → the
band is `unknown` and new entries are blocked (fail closed).
"""
from __future__ import annotations

import copy
import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from services import risk_profile
from services.risk_gate import estimate as est

from . import constants as C

logger = logging.getLogger(__name__)

POLICY_VERSION = "spt-config-v2"
MAX_REASON = 500
MAX_VERSIONS_LISTED = 200
OWNER_APPROVED = "spt-default (owner-approved 5 Nov 2026)"
#: The risk service's own caps a looser SPT value could not get past (services/ai_trader/risk_governor.py gov-v1).
SERVICE_MAX_POSITIONS = 10
SERVICE_MAX_ADV_PCT = 5.0
#: intraday and F&O risk as a fraction of the positional risk (PRD §9.4: 0.35 % against 0.50 %).
SHORTER_RISK_FRACTION = 0.7

SPT_DEFAULTS: Dict[str, Any] = {
    "drawdown_ladder": {"reduce_factor": 0.5},
    "max_positions": 10,
    "max_new_per_day": 5,
    "stressed_gap_pct": est.GAP_STRESS_PCT,
    "allocation_buckets_pct": {"equity_positional": 45.0, "equity_intraday": 25.0, "fno": 20.0, "reserve": 10.0},
    "min_adv_rs": 10_000_000.0,
    "max_adv_participation_pct": 5.0,
    "max_chase_pct": 1.0,
    "approval_expiry_minutes": 30,
    "margin_util_pct": 70.0,
}
#: margin_util_pct is not a PRD value (module docstring): its source says where it came from.
EXTRA_SOURCE = {"margin_util_pct": "owner's Paper Trading v2 design (5 Nov); PRD has no figure; configurable"}
PROFILE_SOURCE = {
    "drawdown_ladder.reduce_at_pct": "risk profile max_drawdown_pct × 1/3",
    "drawdown_ladder.restrict_at_pct": "risk profile max_drawdown_pct × 2/3",
    "drawdown_ladder.halt_at_pct": "risk profile max_drawdown_pct",
    "min_rr.positional": "risk profile min_reward_risk",
    "risk_pct.positional": "risk profile per_trade_risk_pct",
    "risk_pct.intraday": f"risk profile per_trade_risk_pct × {SHORTER_RISK_FRACTION:g}",
    "risk_pct.fno": f"risk profile per_trade_risk_pct × {SHORTER_RISK_FRACTION:g}",
    "fno_max_loss_pct": f"risk profile per_trade_risk_pct × {SHORTER_RISK_FRACTION:g} (PRD §9.4)",
}

#: (low, high, integer?) for every leaf, by dotted path.
RANGES: Dict[str, tuple] = {
    "drawdown_ladder.reduce_at_pct": (0.1, 50.0, False),
    "drawdown_ladder.restrict_at_pct": (0.1, 50.0, False),
    "drawdown_ladder.halt_at_pct": (0.1, 50.0, False),
    "drawdown_ladder.reduce_factor": (0.05, 1.0, False),
    "max_positions": (1, SERVICE_MAX_POSITIONS, True),
    "max_new_per_day": (1, 50, True),
    "min_rr.positional": (0.0, 10.0, False),            # the profile's own range (0 = reward must cover the costs)
    "risk_pct.positional": (0.01, 5.0, False),
    "risk_pct.intraday": (0.01, 5.0, False),
    "risk_pct.fno": (0.01, 5.0, False),
    "stressed_gap_pct": (est.GAP_STRESS_PCT, 20.0, False),
    "allocation_buckets_pct.equity_positional": (0.0, 100.0, False),
    "allocation_buckets_pct.equity_intraday": (0.0, 100.0, False),
    "allocation_buckets_pct.fno": (0.0, 100.0, False),
    "allocation_buckets_pct.reserve": (0.0, 100.0, False),
    "min_adv_rs": (0.0, 1e12, False),
    "max_adv_participation_pct": (0.01, SERVICE_MAX_ADV_PCT, False),
    "max_chase_pct": (0.0, 5.0, False),
    "approval_expiry_minutes": (1, 390, True),
    "margin_util_pct": (1.0, 100.0, False),
    "fno_max_loss_pct": (0.01, 5.0, False),
}
LEAVES = tuple(RANGES)
HIGHER_IS_LOOSER = {"risk_pct.positional", "risk_pct.intraday", "risk_pct.fno", "drawdown_ladder.reduce_at_pct",
                    "drawdown_ladder.restrict_at_pct", "drawdown_ladder.halt_at_pct", "drawdown_ladder.reduce_factor",
                    "max_positions", "max_new_per_day", "max_adv_participation_pct", "max_chase_pct",
                    "approval_expiry_minutes", "margin_util_pct", "fno_max_loss_pct"}
LOWER_IS_LOOSER = {"min_rr.positional", "min_adv_rs", "stressed_gap_pct", "allocation_buckets_pct.reserve"}
NEUTRAL = set(LEAVES) - HIGHER_IS_LOOSER - LOWER_IS_LOOSER
HORIZON_RISK_KEY = {"positional": "positional", "intraday": "intraday", "fno": "fno"}


class ConfigError(ValueError):
    """A refused config change; `status` is the HTTP status the route answers (422; 403 admin_required; 409
    concurrent_change; 503 profile_unreadable)."""

    def __init__(self, code: str, message: str, *, status: int = 422, field: Optional[str] = None,
                 extra: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.code, self.status, self.field, self.extra = code, status, field, extra or {}

    def detail(self) -> Dict[str, Any]:
        out = {"code": self.code, "message": str(self), **self.extra}
        if self.field:
            out["field"] = self.field
        return out


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


def _merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _get(d: Dict[str, Any], path: str) -> Any:
    cur: Any = d
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _set(d: Dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = d
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def _unset(d: Dict[str, Any], path: str) -> None:
    parts = path.split(".")
    cur = d
    for p in parts[:-1]:
        if not isinstance(cur.get(p), dict):
            return
        cur = cur[p]
    cur.pop(parts[-1], None)
    if len(parts) > 1 and not cur:                      # drop an emptied group
        _unset(d, ".".join(parts[:-1]))


def _leaf_paths(d: Dict[str, Any], prefix: str = "") -> List[str]:
    out = []
    for k, v in d.items():
        p = f"{prefix}{k}"
        if isinstance(v, dict) and p not in RANGES:
            out.extend(_leaf_paths(v, p + "."))
        else:
            out.append(p)
    return out


# ── defaults from the risk profile ───────────────────────────────────────────
def profile_limits_of(profile: Optional[Dict[str, Any]]) -> Dict[str, float]:
    return dict((profile or {}).get("limits") or risk_profile.NAMED[risk_profile.OWNER_DEFAULT])


def profile_defaults(limits: Dict[str, float]) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """(the default extras for these profile limits, {leaf path: its source})."""
    dd = float(limits["max_drawdown_pct"])
    per_trade = float(limits["per_trade_risk_pct"])
    out = copy.deepcopy(SPT_DEFAULTS)
    out["drawdown_ladder"].update(reduce_at_pct=round(dd / 3.0, 2), restrict_at_pct=round(dd * 2.0 / 3.0, 2),
                                  halt_at_pct=round(dd, 2))
    out["min_rr"] = {"positional": float(limits["min_reward_risk"])}
    out["risk_pct"] = {"positional": round(per_trade, 4), "intraday": round(per_trade * SHORTER_RISK_FRACTION, 4),
                       "fno": round(per_trade * SHORTER_RISK_FRACTION, 4)}
    out["fno_max_loss_pct"] = round(per_trade * SHORTER_RISK_FRACTION, 4)
    sources = {p: PROFILE_SOURCE.get(p) or EXTRA_SOURCE.get(p) or OWNER_APPROVED for p in LEAVES}
    return out, sources


def _clean_overrides(raw: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for p in _leaf_paths(raw):
        v = _get(raw, p)
        if p in RANGES and v is not None:
            _set(out, p, v)
    return out


def _warnings(extras: Dict[str, Any], limits: Dict[str, float]) -> List[str]:
    w = []
    lad = extras["drawdown_ladder"]
    if not lad["reduce_at_pct"] < lad["restrict_at_pct"] < lad["halt_at_pct"]:
        w.append("drawdown_ladder thresholds do not rise (an override and the profile's default cross); the ladder is "
                 "read halt first, then restricted, then reduce")
    for k, v in extras["risk_pct"].items():
        if float(v) > float(limits["per_trade_risk_pct"]) + 1e-9:
            w.append(f"risk_pct.{k} {v:g}% is above the risk profile's per-trade {limits['per_trade_risk_pct']:g}%: "
                     f"capped at the profile's value where it is used")
    return w


def public(doc: Optional[Dict[str, Any]], user_id: str, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The effective config of `doc` under `profile` (the risk profile's public state; the owner defaults when None)."""
    limits = profile_limits_of(profile)
    defaults, sources = profile_defaults(limits)
    overrides = _clean_overrides((doc or {}).get("overrides"))
    extras = _merge(defaults, overrides)
    return {"user_id": user_id, "account_id": user_id, "mode": (doc or {}).get("mode") or C.MODE_OFF,
            "version": int((doc or {}).get("version") or 0), "extras": extras, "overrides": overrides,
            "defaults": defaults, "defaults_source": sources,
            "profile": {"profile": (profile or {}).get("profile") or risk_profile.OWNER_DEFAULT,
                        "limits_version": (profile or {}).get("limits_version"), "limits": limits,
                        "stored": bool((profile or {}).get("stored"))},
            "warnings": _warnings(extras, limits), "updated_at": (doc or {}).get("updated_at"),
            "updated_by": (doc or {}).get("updated_by"), "reason": (doc or {}).get("reason"), "stored": doc is not None,
            "policy_version": POLICY_VERSION}


def default_state(user_id: str, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """An account with no stored config (pure: the owner-default profile unless one is given)."""
    return public(None, user_id, profile)


async def _profile(db, user_id: str) -> Dict[str, Any]:
    try:
        return await risk_profile.read(db, user_id)
    except Exception as e:  # noqa: BLE001 — the profile is the authority: an unreadable one is never read as default
        logger.error("spt policy: the risk profile of %s could not be read (%s)", user_id, type(e).__name__)
        raise ConfigError("profile_unreadable", "The risk profile could not be read.", status=503) from e


async def read(db, user_id: str) -> Dict[str, Any]:
    """The account's effective config, against its risk profile as it is NOW. Raises when a store cannot be read (the
    pipeline logs and skips the user; a route answers 503)."""
    doc = await db[C.ACCOUNT_CONFIG].find_one({"_id": user_id})
    return public(doc, user_id, await _profile(db, user_id))


async def users_in_modes(db, modes, limit: int = 1000) -> List[Dict[str, Any]]:
    """Every stored config whose mode is one of `modes` (the pipeline's users), each against its own profile."""
    docs = await db[C.ACCOUNT_CONFIG].find({"mode": {"$in": list(modes)}}).to_list(limit)
    out = []
    for d in docs:
        uid = d.get("user_id") or d["_id"]
        out.append(public(d, uid, await _profile(db, uid)))
    return out


# ── validation and the setter ────────────────────────────────────────────────
def _number(path: str, value: Any) -> float:
    low, high, integer = RANGES[path]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ConfigError("invalid_number", f"{path} must be a number", field=path)
    if integer and float(value) != int(value):
        raise ConfigError("invalid_number", f"{path} must be a whole number", field=path)
    if not low <= float(value) <= high:
        raise ConfigError("out_of_range", f"{path} must be between {low:g} and {high:g}", field=path)
    return int(value) if integer else round(float(value), 4)


def apply_changes(overrides: Dict[str, Any], changes: Any) -> Dict[str, Any]:
    """The overrides after `changes` (a partial nested dict; a null leaf removes that override). Raises ConfigError."""
    if not isinstance(changes, dict) or not changes:
        raise ConfigError("invalid_body", "extras must be an object naming at least one value")
    out = copy.deepcopy(overrides)
    for path in _leaf_paths(changes):
        if path not in RANGES:
            raise ConfigError("unknown_field", f"unknown config field {path!r}", field=path)
        v = _get(changes, path)
        if v is None:
            _unset(out, path)
        else:
            _set(out, path, _number(path, v))
    return out


def validate_effective(extras: Dict[str, Any]) -> None:
    lad = extras["drawdown_ladder"]
    if not lad["reduce_at_pct"] < lad["restrict_at_pct"] < lad["halt_at_pct"]:
        raise ConfigError("ladder_not_ascending", "the drawdown ladder must rise: reduce_at < restrict_at < halt_at "
                                                  f"(now {lad['reduce_at_pct']:g} / {lad['restrict_at_pct']:g} / "
                                                  f"{lad['halt_at_pct']:g})", field="drawdown_ladder")
    total = sum(float(v) for v in extras["allocation_buckets_pct"].values())
    if abs(total - 100.0) > 0.01:
        raise ConfigError("buckets_must_sum_100", f"the allocation buckets must add up to 100 (they add up to {total:g})",
                          field="allocation_buckets_pct")


def is_looser(path: str, before: Any, after: Any) -> bool:
    if before is None or after is None or before == after:
        return False
    if path in HIGHER_IS_LOOSER:
        return float(after) > float(before)
    if path in LOWER_IS_LOOSER:
        return float(after) < float(before)
    return False


def clean_reason(value: Any) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    if len(text) > MAX_REASON:
        raise ConfigError("reason_too_long", f"the reason must be at most {MAX_REASON} characters", field="reason")
    return text or None


async def ensure_indexes(db) -> None:
    await db[C.ACCOUNT_CONFIG].create_index([("mode", 1)])
    await db[C.ACCOUNT_CONFIG_VERSIONS].create_index([("user_id", 1), ("at", -1)])


async def update(db, user_id: str, *, actor: str, actor_is_admin: bool = False, mode: Any = None, extras: Any = None,
                 reason: Any = None, expected_version: Any = None, require_reason: bool = False,
                 now: Optional[datetime] = None) -> Dict[str, Any]:
    """Change the mode and/or the overrides (module docstring). Returns the new public config. Raises ConfigError:
    422 invalid_body / invalid_mode / unknown_field / invalid_number / out_of_range / ladder_not_ascending /
    buckets_must_sum_100 / reason_required / reason_too_long / no_change; 403 admin_required (a loosening by a
    non-admin); 409 concurrent_change; 503 profile_unreadable.

    The version row is written BEFORE the config (status `attempted`), then marked `applied` once the compare-and-set on
    the version lands, or `superseded` when another change landed first."""
    if mode is None and extras is None:
        raise ConfigError("invalid_body", "send `mode` and/or `extras`")
    text = clean_reason(reason)
    if require_reason and not text:
        raise ConfigError("reason_required", "a reason is required for this change", field="reason")
    doc = await db[C.ACCOUNT_CONFIG].find_one({"_id": user_id})
    profile = await _profile(db, user_id)
    before = public(doc, user_id, profile)
    if expected_version is not None:
        if isinstance(expected_version, bool) or not isinstance(expected_version, int):
            raise ConfigError("invalid_number", "expected_version must be a whole number", field="expected_version")
        if expected_version != before["version"]:
            raise ConfigError("concurrent_change", f"the config is at version {before['version']}, not "
                                                   f"{expected_version}; reload and retry", status=409)
    new_mode = before["mode"]
    if mode is not None:
        if mode not in C.MODES:
            raise ConfigError("invalid_mode", f"mode must be one of {', '.join(C.MODES)}", field="mode")
        new_mode = mode
    # A mode-only change never re-judges the stored values: turning SPT off must always work.
    new_overrides = before["overrides"] if extras is None else apply_changes(before["overrides"], extras)
    after_extras = _merge(before["defaults"], new_overrides)
    if extras is not None:
        validate_effective(after_extras)
    if new_mode == before["mode"] and new_overrides == before["overrides"]:
        raise ConfigError("no_change", "the config already has these values")
    changed = sorted(p for p in LEAVES if _get(after_extras, p) != _get(before["extras"], p))
    looser = sorted(p for p in changed if is_looser(p, _get(before["extras"], p), _get(after_extras, p)))
    if looser and not actor_is_admin:
        raise ConfigError("admin_required", "Only an admin can loosen an SPT limit (" + ", ".join(looser) + "). You can "
                                            "tighten any limit yourself.", status=403, extra={"loosened": looser})
    if looser and not text:
        raise ConfigError("reason_required", "a reason is required to loosen a limit", field="reason",
                          extra={"loosened": looser})
    moment = _iso(now)
    version = before["version"] + 1
    row_id = str(uuid.uuid4())
    await db[C.ACCOUNT_CONFIG_VERSIONS].insert_one({
        "_id": row_id, "user_id": user_id, "version": version, "version_before": before["version"], "at": moment,
        "actor": actor, "actor_is_admin": bool(actor_is_admin),
        "old": {"mode": before["mode"], "extras": before["extras"], "overrides": before["overrides"]},
        "new": {"mode": new_mode, "extras": after_extras, "overrides": new_overrides},
        "changed": changed + (["mode"] if new_mode != before["mode"] else []),
        "overrides_changed": new_overrides != before["overrides"], "loosened": looser,
        "profile_limits_version": before["profile"]["limits_version"], "reason": text, "status": "attempted",
        "policy_version": POLICY_VERSION})
    fields = {"user_id": user_id, "mode": new_mode, "overrides": new_overrides, "version": version,
              "updated_at": moment, "updated_by": actor, "updated_by_admin": bool(actor_is_admin), "reason": text,
              "policy_version": POLICY_VERSION}
    landed = True
    if doc is None:
        try:
            await db[C.ACCOUNT_CONFIG].insert_one({"_id": user_id, "created_at": moment, **fields})
        except Exception as e:  # noqa: BLE001 — a concurrent first change won (duplicate _id)
            logger.warning("spt policy: first config insert for %s refused (%s)", user_id, type(e).__name__)
            landed = False
    else:
        res = await db[C.ACCOUNT_CONFIG].update_one({"_id": user_id, "version": before["version"]}, {"$set": fields})
        landed = bool(res.matched_count)
    await db[C.ACCOUNT_CONFIG_VERSIONS].update_one({"_id": row_id}, {"$set": {"status": "applied" if landed else "superseded"}})
    if not landed:
        raise ConfigError("concurrent_change", "another change to this config landed first; reload and retry", status=409)
    logger.warning("spt policy: %s%s changed %s for %s (version %d)", actor, " (admin)" if actor_is_admin else "",
                   changed + (["mode"] if new_mode != before["mode"] else []), user_id, version)
    return await read(db, user_id)


async def versions(db, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    n = max(1, min(int(limit), MAX_VERSIONS_LISTED))
    rows = await db[C.ACCOUNT_CONFIG_VERSIONS].find({"user_id": user_id}).sort("at", -1).limit(n).to_list(n)
    for r in rows:
        r["version_id"] = str(r.pop("_id", ""))
    return rows


# ── derived values ───────────────────────────────────────────────────────────
def effective_risk_pct(config: Dict[str, Any], horizon: str, profile_limits: Dict[str, float],
                       ladder_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The risk % a new entry of `horizon` is sized with: the SPT value, capped at the profile's per-trade % (never
    looser), times the ladder's factor in the reduce band. Returns {pct, configured_pct, profile_pct, factor, capped}."""
    configured = float(config["extras"]["risk_pct"][HORIZON_RISK_KEY.get(horizon, "positional")])
    profile_pct = float(profile_limits["per_trade_risk_pct"])
    base = min(configured, profile_pct)
    factor = float((ladder_state or {}).get("factor") or 1.0)
    return {"pct": round(base * factor, 6), "configured_pct": configured, "profile_pct": profile_pct, "factor": factor,
            "capped_by_profile": configured > profile_pct + 1e-12}


LADDER_NORMAL, LADDER_REDUCE, LADDER_RESTRICTED, LADDER_HALT, LADDER_UNKNOWN = (
    "normal", "reduce", "restricted", "halt", "unknown")


def ladder(drawdown_pct: Optional[float], config: Dict[str, Any]) -> Dict[str, Any]:
    """The drawdown band (module docstring). {band, drawdown_pct, factor, blocks_new_entries, thresholds}."""
    lad = config["extras"]["drawdown_ladder"]
    out = {"drawdown_pct": drawdown_pct, "thresholds": dict(lad), "factor": 1.0, "blocks_new_entries": False}
    if drawdown_pct is None:
        return {**out, "band": LADDER_UNKNOWN, "blocks_new_entries": True,
                "text": "Drawdown is unknown (equity could not be marked), so new entries are blocked."}
    dd = float(drawdown_pct)
    if dd >= lad["halt_at_pct"] - 1e-9:
        return {**out, "band": LADDER_HALT, "blocks_new_entries": True,
                "text": f"Drawdown {dd:.2f}% is at or past the halt level {lad['halt_at_pct']:g}%: new entries are refused."}
    if dd >= lad["restrict_at_pct"] - 1e-9:
        return {**out, "band": LADDER_RESTRICTED, "blocks_new_entries": True,
                "text": f"Drawdown {dd:.2f}% is in the restricted band ({lad['restrict_at_pct']:g}%–{lad['halt_at_pct']:g}%): "
                        f"new entries are blocked; exits continue."}
    if dd >= lad["reduce_at_pct"] - 1e-9:
        return {**out, "band": LADDER_REDUCE, "factor": float(lad["reduce_factor"]),
                "text": f"Drawdown {dd:.2f}% is in the reduce band ({lad['reduce_at_pct']:g}%–{lad['restrict_at_pct']:g}%): "
                        f"new trade risk is multiplied by {lad['reduce_factor']:g}."}
    return {**out, "band": LADDER_NORMAL, "text": f"Drawdown {dd:.2f}% is below {lad['reduce_at_pct']:g}%: normal risk."}
