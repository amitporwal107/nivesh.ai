"""SPT account configuration: the account's mode and the SPT risk extras, versioned (DESIGN.md D3, D4; PRD §16.1, §26;
WF §25 items 21-22).

ONE CONFIG PER USER (`spt_account_config`, `_id` = user_id; DESIGN D3: account_id = user_id)
    mode     off (default, D4) | tracking | approval | auto. Nothing is proposed for an account in `off`.
    extras   the SPT policy values the PRD §26 table names that are NOT already a risk-profile limit:
             drawdown_ladder {reduce_at_pct 2, restrict_at_pct 4, halt_at_pct 6, reduce_factor 0.5}   PRD §9.7
             max_positions 10, max_new_per_day 5                                                       PRD §9.4, §26
             min_rr {positional 2.0}                                                                   PRD §26 "1:2"
             risk_pct {positional 0.5, intraday 0.35, fno 0.35}                                        PRD §9.4, §26
             stressed_gap_pct (default risk_gate.estimate.GAP_STRESS_PCT)                               PRD §9.2
             allocation_buckets_pct {equity_positional 45, equity_intraday 25, fno 20, reserve 10}     PRD §8.6
             min_adv_rs, max_adv_participation_pct, max_chase_pct, approval_expiry_minutes            SPT defaults
    version  +1 on every change; every change first writes a row to `spt_account_config_versions` (who, when, old,
             new, reason), so the history cannot be lost to a crash between the two writes (PRD §18 rule 15).

THE RISK PROFILE STAYS THE AUTHORITY (services/risk_profile.py): per-trade risk, open risk, position and sector
exposure, daily/weekly loss and drawdown are read from it, never copied here. An SPT risk % above the profile's
per-trade % is refused when set (`risk_pct_above_profile`) and capped when used (`effective_risk_pct`), so a later
tightening of the profile is never loosened by an older SPT value. `max_positions` cannot exceed the risk service's
own 10 (risk_governor gov-v1) and `max_adv_participation_pct` cannot exceed the governor's 5 %: a looser SPT value
would only be cut again by the service.

DEFAULTS NOT IN THE PRD (labelled `spt-default`, for the owner to confirm): max_chase_pct 1.0, min_adv_rs ₹1 crore,
max_adv_participation_pct 5.0, approval_expiry_minutes 30, max_new_per_day 5.

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
from typing import Any, Dict, List, Optional

from services.risk_gate import estimate as est

from . import constants as C

logger = logging.getLogger(__name__)

POLICY_VERSION = "spt-config-v1"
MAX_REASON = 500
MAX_VERSIONS_LISTED = 200
#: The risk service's own caps a looser SPT value could not get past (services/ai_trader/risk_governor.py gov-v1).
SERVICE_MAX_POSITIONS = 10
SERVICE_MAX_ADV_PCT = 5.0

DEFAULT_EXTRAS: Dict[str, Any] = {
    "drawdown_ladder": {"reduce_at_pct": 2.0, "restrict_at_pct": 4.0, "halt_at_pct": 6.0, "reduce_factor": 0.5},
    "max_positions": 10,
    "max_new_per_day": 5,
    "min_rr": {"positional": 2.0},
    "risk_pct": {"positional": 0.5, "intraday": 0.35, "fno": 0.35},
    "stressed_gap_pct": est.GAP_STRESS_PCT,
    "allocation_buckets_pct": {"equity_positional": 45.0, "equity_intraday": 25.0, "fno": 20.0, "reserve": 10.0},
    "min_adv_rs": 10_000_000.0,
    "max_adv_participation_pct": 5.0,
    "max_chase_pct": 1.0,
    "approval_expiry_minutes": 30,
}
DEFAULTS_SOURCE = {
    "drawdown_ladder": "PRD §9.7", "max_positions": "PRD §9.4 / §26", "min_rr": "PRD §26 (1:2)",
    "risk_pct": "PRD §9.4 / §26", "stressed_gap_pct": f"risk_gate.estimate.GAP_STRESS_PCT ({est.ESTIMATE_VERSION})",
    "allocation_buckets_pct": "PRD §8.6", "max_new_per_day": "spt-default (owner to confirm)",
    "min_adv_rs": "spt-default (owner to confirm)", "max_adv_participation_pct": "spt-default = governor gov-v1 max_adv_pct",
    "max_chase_pct": "spt-default (owner to confirm)", "approval_expiry_minutes": "spt-default (owner to confirm)",
}

#: (low, high, integer?) for every scalar leaf, by dotted path.
RANGES: Dict[str, tuple] = {
    "drawdown_ladder.reduce_at_pct": (0.1, 50.0, False),
    "drawdown_ladder.restrict_at_pct": (0.1, 50.0, False),
    "drawdown_ladder.halt_at_pct": (0.1, 50.0, False),
    "drawdown_ladder.reduce_factor": (0.05, 1.0, False),
    "max_positions": (1, SERVICE_MAX_POSITIONS, True),
    "max_new_per_day": (1, 50, True),
    "min_rr.positional": (1.0, 10.0, False),
    "risk_pct.positional": (0.05, 5.0, False),
    "risk_pct.intraday": (0.05, 5.0, False),
    "risk_pct.fno": (0.05, 5.0, False),
    "stressed_gap_pct": (est.GAP_STRESS_PCT, 20.0, False),
    "allocation_buckets_pct.equity_positional": (0.0, 100.0, False),
    "allocation_buckets_pct.equity_intraday": (0.0, 100.0, False),
    "allocation_buckets_pct.fno": (0.0, 100.0, False),
    "allocation_buckets_pct.reserve": (0.0, 100.0, False),
    "min_adv_rs": (0.0, 1e12, False),
    "max_adv_participation_pct": (0.01, SERVICE_MAX_ADV_PCT, False),
    "max_chase_pct": (0.0, 5.0, False),
    "approval_expiry_minutes": (1, 390, True),
}
HORIZON_RISK_KEY = {"positional": "positional", "intraday": "intraday", "fno": "fno"}


class ConfigError(ValueError):
    """A refused config change; `status` is the HTTP status the route answers (422, or 409 for a concurrent change)."""

    def __init__(self, code: str, message: str, *, status: int = 422, field: Optional[str] = None) -> None:
        super().__init__(message)
        self.code, self.status, self.field = code, status, field

    def detail(self) -> Dict[str, Any]:
        out = {"code": self.code, "message": str(self)}
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


def default_state(user_id: str) -> Dict[str, Any]:
    return {"user_id": user_id, "account_id": user_id, "mode": C.MODE_OFF, "version": 0,
            "extras": copy.deepcopy(DEFAULT_EXTRAS), "defaults_source": dict(DEFAULTS_SOURCE), "updated_at": None,
            "updated_by": None, "reason": None, "stored": False, "policy_version": POLICY_VERSION}


def public(doc: Optional[Dict[str, Any]], user_id: str) -> Dict[str, Any]:
    if not doc:
        return default_state(user_id)
    out = default_state(user_id)
    out.update(mode=doc.get("mode") or C.MODE_OFF, version=int(doc.get("version") or 0),
               extras=_merge(DEFAULT_EXTRAS, doc.get("extras") or {}), updated_at=doc.get("updated_at"),
               updated_by=doc.get("updated_by"), reason=doc.get("reason"), stored=True)
    return out


async def read(db, user_id: str) -> Dict[str, Any]:
    """The account's config (the defaults, said `stored: false`, when none is stored). Raises when the store cannot be
    read: a caller must not treat an unreadable config as `off` silently (the pipeline logs and skips the user)."""
    return public(await db[C.ACCOUNT_CONFIG].find_one({"_id": user_id}), user_id)


async def users_in_modes(db, modes, limit: int = 1000) -> List[Dict[str, Any]]:
    """Every stored config whose mode is one of `modes` (the pipeline's users)."""
    docs = await db[C.ACCOUNT_CONFIG].find({"mode": {"$in": list(modes)}}).to_list(limit)
    return [public(d, d.get("user_id") or d["_id"]) for d in docs]


# ── validation ───────────────────────────────────────────────────────────────
def _leaf_paths(d: Dict[str, Any], prefix: str = "") -> List[str]:
    out = []
    for k, v in d.items():
        p = f"{prefix}{k}"
        if isinstance(v, dict):
            out.extend(_leaf_paths(v, p + "."))
        else:
            out.append(p)
    return out


def _get(d: Dict[str, Any], path: str) -> Any:
    cur: Any = d
    for p in path.split("."):
        cur = cur[p]
    return cur


def _number(path: str, value: Any) -> float:
    low, high, integer = RANGES[path]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ConfigError("invalid_number", f"{path} must be a number", field=path)
    if integer and float(value) != int(value):
        raise ConfigError("invalid_number", f"{path} must be a whole number", field=path)
    if not low <= float(value) <= high:
        raise ConfigError("out_of_range", f"{path} must be between {low:g} and {high:g}", field=path)
    return int(value) if integer else round(float(value), 4)


def validate_extras(changes: Any, current: Dict[str, Any], *, profile_limits: Optional[Dict[str, float]]) -> Dict[str, Any]:
    """The extras after `changes` (a partial nested dict), validated as a whole. Raises ConfigError."""
    if not isinstance(changes, dict):
        raise ConfigError("invalid_body", "extras must be an object")
    allowed = set(_leaf_paths(DEFAULT_EXTRAS))
    for path in _leaf_paths(changes):
        if path not in allowed:
            raise ConfigError("unknown_field", f"unknown config field {path!r}", field=path)
    after = _merge(current, changes)
    for path in allowed:
        value = _get(after, path)
        cleaned = _number(path, value)
        parts = path.split(".")
        target = after
        for p in parts[:-1]:
            target = target[p]
        target[parts[-1]] = cleaned
    lad = after["drawdown_ladder"]
    if not lad["reduce_at_pct"] < lad["restrict_at_pct"] < lad["halt_at_pct"]:
        raise ConfigError("ladder_not_ascending", "the drawdown ladder must rise: reduce_at < restrict_at < halt_at",
                          field="drawdown_ladder")
    total = sum(float(v) for v in after["allocation_buckets_pct"].values())
    if abs(total - 100.0) > 0.01:
        raise ConfigError("buckets_must_sum_100", f"the allocation buckets must add up to 100 (they add up to {total:g})",
                          field="allocation_buckets_pct")
    if profile_limits is not None:
        cap = float(profile_limits["per_trade_risk_pct"])
        for key, pct in after["risk_pct"].items():
            if float(pct) > cap + 1e-9:
                raise ConfigError("risk_pct_above_profile",
                                  f"risk_pct.{key} {pct:g}% is above the risk profile's per-trade limit {cap:g}%; the "
                                  f"profile is the authority (tighten it here, or ask an admin to change the profile)",
                                  field=f"risk_pct.{key}")
    return after


def clean_reason(value: Any) -> Optional[str]:
    text = "" if value is None else str(value).strip()
    if len(text) > MAX_REASON:
        raise ConfigError("reason_too_long", f"the reason must be at most {MAX_REASON} characters", field="reason")
    return text or None


# ── the setter ───────────────────────────────────────────────────────────────
async def ensure_indexes(db) -> None:
    await db[C.ACCOUNT_CONFIG].create_index([("mode", 1)])
    await db[C.ACCOUNT_CONFIG_VERSIONS].create_index([("user_id", 1), ("at", -1)])


async def update(db, user_id: str, *, actor: str, mode: Any = None, extras: Any = None, reason: Any = None,
                 expected_version: Any = None, profile_limits: Optional[Dict[str, float]] = None,
                 now: Optional[datetime] = None) -> Dict[str, Any]:
    """Change the mode and/or extras. Returns the new public config. Raises ConfigError (422 codes: invalid_body,
    invalid_mode, unknown_field, invalid_number, out_of_range, ladder_not_ascending, buckets_must_sum_100,
    risk_pct_above_profile, reason_too_long, no_change; 409 concurrent_change).

    The version row is written BEFORE the config (status `attempted`), then marked `applied` once the compare-and-set on
    the version lands, or `superseded` when another change landed first."""
    if mode is None and extras is None:
        raise ConfigError("invalid_body", "send `mode` and/or `extras`")
    text = clean_reason(reason)
    doc = await db[C.ACCOUNT_CONFIG].find_one({"_id": user_id})
    before = public(doc, user_id)
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
    # A mode-only change never re-judges the stored extras: turning SPT off must always work, and a risk % the profile has
    # since tightened below is capped where it is used (effective_risk_pct).
    new_extras = before["extras"] if extras is None else validate_extras(extras, before["extras"],
                                                                        profile_limits=profile_limits)
    if new_mode == before["mode"] and new_extras == before["extras"]:
        raise ConfigError("no_change", "the config already has these values")
    changed = sorted([p for p in _leaf_paths(DEFAULT_EXTRAS) if _get(new_extras, p) != _get(before["extras"], p)]
                     + (["mode"] if new_mode != before["mode"] else []))
    moment = _iso(now)
    version = before["version"] + 1
    row_id = str(uuid.uuid4())
    await db[C.ACCOUNT_CONFIG_VERSIONS].insert_one({
        "_id": row_id, "user_id": user_id, "version": version, "version_before": before["version"], "at": moment,
        "actor": actor, "old": {"mode": before["mode"], "extras": before["extras"]},
        "new": {"mode": new_mode, "extras": new_extras}, "changed": changed, "reason": text, "status": "attempted",
        "policy_version": POLICY_VERSION})
    fields = {"user_id": user_id, "mode": new_mode, "extras": new_extras, "version": version, "updated_at": moment,
              "updated_by": actor, "reason": text, "policy_version": POLICY_VERSION}
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
    logger.warning("spt policy: %s changed %s for %s (version %d)", actor, changed, user_id, version)
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
