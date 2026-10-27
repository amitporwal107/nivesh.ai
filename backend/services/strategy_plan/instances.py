"""Strategy instances: the structures a user builds in Trade Desk › Strategy Lab › Build a trade, saved as versions.
Pure (no I/O): request bodies in, the documents routes/strategy_instances.py stores out, or InstanceInputError.

The saved-plans store (POST /api/desk/strategy/plans) only accepts a plan the builder made, unchanged (its id is a digest
of its inputs), so it cannot hold a structure the user laid out or edited leg by leg. An instance can: it names the
template it started from (or none), the underlying, where it came from (a template, an AI Trader strategy, a saved plan,
a clone, or by hand) and an append-only list of versions. Each version is the legs and the wizard's settings exactly as
the user saved them; a version is never edited, a change is a new version. Nothing here prices, sizes or risk-checks a
structure (the payoff engine and the risk service do), and nothing is ever sent to a broker.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date
from typing import Any, Dict, List, Optional

from services import desk_trading as desk

from . import templates as tpl

COLLECTION = "desk_strategy_instances"
MAX_INSTANCES = 200
MAX_LISTED = 100
MAX_VERSIONS = 50
MIN_LEGS, MAX_LEGS = 1, 4
MAX_LOTS = 1000
MAX_LOT_SIZE = 100_000
MAX_CONFIG_BYTES = 4096
NAME_MAX, NOTE_MAX, REF_MAX, PRICE_SOURCE_MAX = 80, 300, 120, 120
SOURCE_KINDS = ("template", "ai_strategy", "saved_plan", "clone", "manual")
BODY_FIELDS = {"name", "template", "underlying", "source", "structure", "note"}
VERSION_FIELDS = {"structure", "note"}
STRUCT_FIELDS = {"legs", "config"}
LEG_FIELDS = {"kind", "side", "lots", "lot_size", "entry_price", "expiry", "strike", "option_type", "price_source"}
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class InstanceInputError(ValueError):
    """A body that cannot be stored: `code` for the client, `message` in words."""

    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code, self.message = code, message

    def detail(self) -> Dict[str, str]:
        return {"code": self.code, "message": self.message}


def _object(raw: Any, allowed: set, what: str) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise InstanceInputError("invalid_body", f"{what} must be a JSON object.")
    extra = sorted(set(raw) - allowed)
    if extra:
        raise InstanceInputError("unknown_field", f"{what} has fields this route does not take: {', '.join(extra)}.")
    return raw


def _text(raw: Any, field: str, limit: int, *, required: bool = False) -> Optional[str]:
    if raw is None:
        if required:
            raise InstanceInputError(f"invalid_{field}", f"{field} is required.")
        return None
    if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > limit:
        raise InstanceInputError(f"invalid_{field}", f"{field} must be text of 1 to {limit} characters.")
    return raw.strip()


def _whole(raw: Any, field: str, lo: int, hi: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not float(raw).is_integer() or not lo <= raw <= hi:
        raise InstanceInputError(f"invalid_{field}", f"{field} must be a whole number from {lo} to {hi}.")
    return int(raw)


def _positive(raw: Any, field: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw <= 0:
        raise InstanceInputError(f"invalid_{field}", f"{field} must be a number above 0.")
    return float(raw)


def _day(raw: Any, field: str) -> str:
    if not isinstance(raw, str) or not _DAY.match(raw):
        raise InstanceInputError(f"invalid_{field}", f"{field} must be a date, YYYY-MM-DD.")
    try:
        date.fromisoformat(raw)
    except ValueError:
        raise InstanceInputError(f"invalid_{field}", f"{field} is not a calendar date.") from None
    return raw


def clean_leg(raw: Any, i: int) -> Dict[str, Any]:
    leg = _object(raw, LEG_FIELDS, f"legs[{i}]")
    kind = leg.get("kind")
    if kind not in ("option", "future", "cash"):
        raise InstanceInputError("invalid_leg_kind", f"legs[{i}].kind must be option, future or cash.")
    side = leg.get("side")
    if side not in ("buy", "sell"):
        raise InstanceInputError("invalid_leg_side", f"legs[{i}].side must be buy or sell.")
    out: Dict[str, Any] = {
        "kind": kind, "side": side,
        "lots": _whole(leg.get("lots"), "lots", 1, MAX_LOTS),
        "lot_size": _whole(leg.get("lot_size"), "lot_size", 1, MAX_LOT_SIZE),
        "entry_price": _positive(leg.get("entry_price"), "entry_price"),
        "expiry": None, "strike": None, "option_type": None,
        "price_source": _text(leg.get("price_source"), "price_source", PRICE_SOURCE_MAX),
    }
    if kind == "cash":
        if leg.get("expiry") is not None or leg.get("strike") is not None or leg.get("option_type") is not None:
            raise InstanceInputError("invalid_cash_leg", f"legs[{i}]: a cash leg has no expiry, strike or option type.")
        return out
    out["expiry"] = _day(leg.get("expiry"), "expiry")
    if kind == "future":
        if leg.get("strike") is not None or leg.get("option_type") is not None:
            raise InstanceInputError("invalid_future_leg", f"legs[{i}]: a future has no strike or option type.")
        return out
    out["strike"] = _positive(leg.get("strike"), "strike")
    if leg.get("option_type") not in ("call", "put"):
        raise InstanceInputError("invalid_option_type", f"legs[{i}].option_type must be call or put.")
    out["option_type"] = leg["option_type"]
    return out


def clean_structure(raw: Any) -> Dict[str, Any]:
    s = _object(raw, STRUCT_FIELDS, "structure")
    legs = s.get("legs")
    if not isinstance(legs, list) or not MIN_LEGS <= len(legs) <= MAX_LEGS:
        raise InstanceInputError("invalid_leg_count", f"structure.legs must hold {MIN_LEGS} to {MAX_LEGS} legs.")
    config = s.get("config", {})
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise InstanceInputError("invalid_config", "structure.config must be an object.")
    try:
        size = len(json.dumps(config, separators=(",", ":"), allow_nan=False).encode())
    except (TypeError, ValueError):
        raise InstanceInputError("invalid_config", "structure.config must be plain JSON.") from None
    if size > MAX_CONFIG_BYTES:
        raise InstanceInputError("config_too_large", f"structure.config is larger than {MAX_CONFIG_BYTES} bytes.")
    return {"legs": [clean_leg(leg, i) for i, leg in enumerate(legs)], "config": config}


def _source(raw: Any) -> Dict[str, Optional[str]]:
    s = _object(raw, {"kind", "ref"}, "source")
    if s.get("kind") not in SOURCE_KINDS:
        raise InstanceInputError("invalid_source", f"source.kind must be one of {', '.join(SOURCE_KINDS)}.")
    return {"kind": s["kind"], "ref": _text(s.get("ref"), "source_ref", REF_MAX)}


def _version(n: int, structure: Dict[str, Any], note: Optional[str], at: str) -> Dict[str, Any]:
    return {"version": n, "saved_at": at, "structure": structure, "note": note}


def new_instance(user_id: str, raw: Any, *, instance_id: str, at: str) -> Dict[str, Any]:
    """The document for POST /api/desk/strategy/instances (version 1)."""
    body = _object(raw, BODY_FIELDS, "The body")
    template = body.get("template")
    if template is not None and template not in {e["name"] for e in tpl.CATALOG}:
        raise InstanceInputError("invalid_template", "template must be a name from GET /api/desk/strategy/templates, or null.")
    try:
        underlying = desk.clean_symbol(body.get("underlying"))
    except desk.DeskInputError:
        raise InstanceInputError("invalid_underlying", "underlying must be an NSE symbol.") from None
    structure = clean_structure(body.get("structure"))
    note = _text(body.get("note"), "note", NOTE_MAX)
    return {"_id": instance_id, "user_id": user_id, "name": _text(body.get("name"), "name", NAME_MAX),
            "template": template, "underlying": underlying, "source": _source(body.get("source")),
            "created_at": at, "updated_at": at, "latest_version": 1, "versions": [_version(1, structure, note, at)],
            "cloned_from": None}


def next_version(doc: Dict[str, Any], raw: Any, *, at: str) -> Dict[str, Any]:
    """The version POST /instances/{id}/versions appends (raises version_limit at MAX_VERSIONS)."""
    body = _object(raw, VERSION_FIELDS, "The body")
    if int(doc.get("latest_version") or 0) >= MAX_VERSIONS:
        raise InstanceInputError("version_limit", f"An instance holds at most {MAX_VERSIONS} versions; clone it to go on.")
    return _version(int(doc["latest_version"]) + 1, clean_structure(body.get("structure")),
                    _text(body.get("note"), "note", NOTE_MAX), at)


def clone_of(doc: Dict[str, Any], user_id: str, *, instance_id: str, at: str) -> Dict[str, Any]:
    """A new instance whose version 1 is a copy of `doc`'s latest version."""
    latest = max(doc["versions"], key=lambda v: v["version"])
    return {"_id": instance_id, "user_id": user_id, "name": doc.get("name"), "template": doc.get("template"),
            "underlying": doc["underlying"], "source": {"kind": "clone", "ref": f"{doc['_id']}@v{latest['version']}"},
            "created_at": at, "updated_at": at, "latest_version": 1,
            "versions": [_version(1, json.loads(json.dumps(latest["structure"])), latest.get("note"), at)],
            "cloned_from": {"id": doc["_id"], "version": latest["version"]}}


def public(doc: Dict[str, Any], *, latest_only: bool = False) -> Dict[str, Any]:
    versions: List[Dict[str, Any]] = sorted(doc.get("versions") or [], key=lambda v: v["version"])
    if latest_only:
        versions = versions[-1:]
    return {"id": doc["_id"], "name": doc.get("name"), "template": doc.get("template"), "underlying": doc.get("underlying"),
            "source": doc.get("source"), "created_at": doc.get("created_at"), "updated_at": doc.get("updated_at"),
            "latest_version": doc.get("latest_version"), "versions": versions, "cloned_from": doc.get("cloned_from"),
            "sent_to_broker": False}
