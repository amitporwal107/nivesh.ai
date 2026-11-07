"""Market-wide SPT settings an admin can change without a deploy (owner, 5 Nov 2026 ~06:50 IST: "make it configurable").

ONE DOCUMENT `spt_settings` {_id: "global"}, versioned: every change first writes a row to `spt_settings_versions`
(who, when, old, new, reason; status attempted → applied | superseded), then a compare-and-set on `version`.

    field                        env fallback                       default  range       read by
    min_adv_rs                   SPT_MIN_ADV_RS                     1 crore  0 – 1e12    slice A: the QUALIFIED liquidity
                                                                                         floor (opportunities/validate.policy)
    positional_window_sessions   SPT_POSITIONAL_WINDOW_SESSIONS     5        1 – 60      slice A: a positional
                                                                                         opportunity's window (signals/clock)
    validate_max_per_round       SPT_VALIDATE_MAX_PER_ROUND         60       1 – 1000    slice A: validations per round
                                                                                         (opportunities/runner)
    quote_max_age_s              SPT_QUOTE_MAX_AGE_S                120      5 – 600     slices B and C: a live quote older
                                                                                         than this prices / fills nothing

PRECEDENCE: a value stored here wins; else the environment variable; else the default. A stored value set to null is
removed (back to the env / default).

HOW THE OTHER MODULES READ IT (each of them already reads an `env` mapping): `overlay(env)` returns that mapping (os.environ
when None) with the stored values written over their env names. It is SYNCHRONOUS and reads this process's cache, which
`refresh(db)` reloads at most every CACHE_TTL_S: the A, B and C loops call it on every iteration on every worker (before
their leader check), an admin change refreshes the worker that served it at once, and B's request paths call it too. So
a change reaches every worker within about CACHE_TTL_S plus one loop period. An unreadable store keeps the last values
read (logged), so a database blip never swaps a tuned value for a default silently mid-session.
"""
from __future__ import annotations

import logging
import math
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

logger = logging.getLogger(__name__)

SETTINGS = "spt_settings"
SETTINGS_VERSIONS = "spt_settings_versions"
GLOBAL_ID = "global"
POLICY_VERSION = "spt-settings-v1"
CACHE_TTL_S = 30.0
MAX_REASON = 500

FIELDS: Dict[str, Dict[str, Any]] = {
    "min_adv_rs": {"env": "SPT_MIN_ADV_RS", "default": 10_000_000.0, "range": (0.0, 1e12), "integer": False,
                   "used_by": "slice A: the QUALIFIED liquidity floor (services/spt/opportunities/validate.policy)"},
    "positional_window_sessions": {"env": "SPT_POSITIONAL_WINDOW_SESSIONS", "default": 5, "range": (1, 60), "integer": True,
                                   "used_by": "slice A: a positional opportunity's consolidation window "
                                              "(services/spt/signals/clock.window_sessions)"},
    "validate_max_per_round": {"env": "SPT_VALIDATE_MAX_PER_ROUND", "default": 60, "range": (1, 1000), "integer": True,
                               "used_by": "slice A: validations per round (services/spt/opportunities/runner.max_per_round)"},
    "quote_max_age_s": {"env": "SPT_QUOTE_MAX_AGE_S", "default": 120.0, "range": (5.0, 600.0), "integer": False,
                        "used_by": "slice B (proposal prices, services/spt/proposals) and slice C (fills, "
                                   "services/spt/paper/config.quote_max_age_s)"},
}

_cache: Dict[str, Any] = {"at": None, "stored": {}, "version": 0}


class SettingsError(ValueError):
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


def _clean(field: str, value: Any) -> Any:
    spec = FIELDS[field]
    low, high = spec["range"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise SettingsError("invalid_number", f"{field} must be a number", field=field)
    if spec["integer"] and float(value) != int(value):
        raise SettingsError("invalid_number", f"{field} must be a whole number", field=field)
    if not low <= float(value) <= high:
        raise SettingsError("out_of_range", f"{field} must be between {low:g} and {high:g}", field=field)
    return int(value) if spec["integer"] else float(value)


def env_value(field: str, env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """{value, source} from the environment, else the default (an unreadable or out-of-range env value is ignored)."""
    spec = FIELDS[field]
    raw = (os.environ if env is None else env).get(spec["env"])
    if raw not in (None, ""):
        try:
            return {"value": _clean(field, float(raw)), "source": f"env {spec['env']}"}
        except (SettingsError, ValueError):
            logger.warning("spt settings: env %s is not usable; the default applies", spec["env"])
    return {"value": spec["default"], "source": "default"}


def effective(stored: Mapping[str, Any], env: Optional[Mapping[str, str]] = None) -> Dict[str, Dict[str, Any]]:
    out = {}
    for f in FIELDS:
        if stored.get(f) is not None:
            out[f] = {"value": stored[f], "source": f"{SETTINGS} (admin)"}
        else:
            out[f] = env_value(f, env)
    return out


def public(doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    stored = {f: (doc or {}).get("values", {}).get(f) for f in FIELDS}
    eff = effective(stored)
    return {"values": {f: v["value"] for f, v in eff.items()}, "sources": {f: v["source"] for f, v in eff.items()},
            "stored": {f: v for f, v in stored.items() if v is not None}, "version": int((doc or {}).get("version") or 0),
            "updated_at": (doc or {}).get("updated_at"), "updated_by": (doc or {}).get("updated_by"),
            "reason": (doc or {}).get("reason"),
            "fields": {f: {"env": s["env"], "default": s["default"], "range": list(s["range"]), "used_by": s["used_by"]}
                       for f, s in FIELDS.items()},
            "policy_version": POLICY_VERSION}


async def read(db) -> Dict[str, Any]:
    return public(await db[SETTINGS].find_one({"_id": GLOBAL_ID}))


async def versions(db, limit: int = 50) -> List[Dict[str, Any]]:
    n = max(1, min(int(limit), 200))
    rows = await db[SETTINGS_VERSIONS].find({"settings_id": GLOBAL_ID}).sort("at", -1).limit(n).to_list(n)
    for r in rows:
        r["version_id"] = str(r.pop("_id", ""))
    return rows


async def update(db, *, actor: str, changes: Any, reason: Any, expected_version: Any = None,
                 now: Optional[datetime] = None) -> Dict[str, Any]:
    """Set (or, with null, remove) stored values. Raises SettingsError (422 invalid_body / unknown_field /
    invalid_number / out_of_range / reason_required / reason_too_long / no_change; 409 concurrent_change)."""
    if not isinstance(changes, dict) or not changes:
        raise SettingsError("invalid_body", "send `values` with at least one setting")
    unknown = set(changes) - set(FIELDS)
    if unknown:
        raise SettingsError("unknown_field", f"unknown setting(s): {', '.join(sorted(unknown))}")
    text = "" if reason is None else str(reason).strip()
    if not text:
        raise SettingsError("reason_required", "a reason is required for a settings change", field="reason")
    if len(text) > MAX_REASON:
        raise SettingsError("reason_too_long", f"the reason must be at most {MAX_REASON} characters", field="reason")
    doc = await db[SETTINGS].find_one({"_id": GLOBAL_ID})
    before = public(doc)
    if expected_version is not None and expected_version != before["version"]:
        raise SettingsError("concurrent_change", f"the settings are at version {before['version']}", status=409)
    stored = dict(before["stored"])
    for f, v in changes.items():
        if v is None:
            stored.pop(f, None)
        else:
            stored[f] = _clean(f, v)
    if stored == before["stored"]:
        raise SettingsError("no_change", "the settings already have these values")
    moment = _iso(now)
    version = before["version"] + 1
    row_id = str(uuid.uuid4())
    after = public({"values": stored})
    await db[SETTINGS_VERSIONS].insert_one({
        "_id": row_id, "settings_id": GLOBAL_ID, "version": version, "version_before": before["version"], "at": moment,
        "actor": actor, "old": {"stored": before["stored"], "values": before["values"]},
        "new": {"stored": stored, "values": after["values"]}, "changed": sorted(changes), "reason": text,
        "status": "attempted", "policy_version": POLICY_VERSION})
    fields = {"values": stored, "version": version, "updated_at": moment, "updated_by": actor, "reason": text,
              "policy_version": POLICY_VERSION}
    if doc is None:
        try:
            await db[SETTINGS].insert_one({"_id": GLOBAL_ID, **fields})
            landed = True
        except Exception as e:  # noqa: BLE001 — a concurrent first change won (duplicate _id)
            logger.warning("spt settings: first insert refused (%s)", type(e).__name__)
            landed = False
    else:
        res = await db[SETTINGS].update_one({"_id": GLOBAL_ID, "version": before["version"]}, {"$set": fields})
        landed = bool(res.matched_count)
    await db[SETTINGS_VERSIONS].update_one({"_id": row_id}, {"$set": {"status": "applied" if landed else "superseded"}})
    if not landed:
        raise SettingsError("concurrent_change", "another change landed first; reload and retry", status=409)
    logger.warning("spt settings: %s changed %s (version %d): %s", actor, sorted(changes), version, text)
    await refresh(db, force=True)
    return await read(db)


# ── the process cache and the overlay ────────────────────────────────────────
async def refresh(db, *, force: bool = False) -> bool:
    """Reload the stored values when the cache is older than CACHE_TTL_S (or `force`). True when reloaded. Never raises:
    an unreadable store keeps the last values read."""
    at = _cache["at"]
    if not force and at is not None and time.monotonic() - at < CACHE_TTL_S:
        return False
    try:
        doc = await db[SETTINGS].find_one({"_id": GLOBAL_ID})
    except Exception as e:  # noqa: BLE001 — tuning values: the last ones read (or env / defaults) stay in force
        logger.warning("spt settings: not readable, keeping the last values (%s)", type(e).__name__)
        _cache["at"] = time.monotonic()
        return False
    _cache.update(at=time.monotonic(), stored={f: v for f, v in ((doc or {}).get("values") or {}).items()
                                               if f in FIELDS and v is not None},
                  version=int((doc or {}).get("version") or 0))
    return True


def overlay(env: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """`env` (os.environ when None) with the cached stored values written over their env names."""
    out = dict(os.environ if env is None else env)
    for f, v in (_cache.get("stored") or {}).items():
        out[FIELDS[f]["env"]] = str(v)
    return out


def value(field: str) -> Any:
    """One setting's effective value (cache, else env, else default). Synchronous."""
    stored = (_cache.get("stored") or {}).get(field)
    return stored if stored is not None else env_value(field)["value"]


def quote_max_age_s() -> float:
    return float(value("quote_max_age_s"))


def reset_cache() -> None:
    """Tests: forget what this process read."""
    _cache.update(at=None, stored={}, version=0)

