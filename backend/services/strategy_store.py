"""The shared strategy store, v2: the document a Strategy Lab structure (or, from Phase 1.3, a Copilot strategy) is saved
as, in the Strategy Builder tables (owner decision D1, 2026-10-28). The routes are in routes/strategy_builder.py.

The v2 document (`strategy_versions.definition`, told apart from the v1 equity DSL by `schema_version == "2"`) is the
one the Strategy Lab wizard sends (frontend-v5 tradingdesk/strategy/instance-store.ts `definitionOf`; pinned in
frontend-v5/e2e/fixtures/contract-strategy-store-v2.json):

    schema_version "2", name, market "NSE", underlying {symbol, kind index|stock}, template_id (desk catalog) | null,
    timeframe "1d", legs [1..MAX_STRATEGY_LEGS], entry {type "manual", assumption}, exit {…}, build_constraints {…},
    sizing {lots}

A leg is concrete as the wizard lays it out (expiry `specific` date, strike `fixed` value) or rule-based as the Copilot
and the backtests will write it (expiry nearest_weekly | nearest_monthly | next_monthly | same_as a leg; strike atm |
atm_offset_points | atm_offset_strikes). Fields are an allow-list: an unknown field is refused, never dropped. A valid
document is stored exactly as sent.

Validation reports EVERY problem as {field, code, message} (PRD §13.3: each issue next to its field). Whether a
structure may be backtested or paper traded is a separate, derived answer (`checks`), never stored: the desk's
defined-risk rule (services/desk_strategy_trades.check_defined_risk) decides, so a naked short option is saved as a
draft and marked `blocking_for: ["backtest", "paper"]` (owner decision D2; question Q4 taken as recommended).

Pure functions, plus two reads: `resolve_version_ref` (Postgres, for the desk's paper-trade `strategy_ref`) and
`count_open_paper_trades` (Mongo, for PAPER LIVE).
"""
from __future__ import annotations

import json
import logging
import math
import re
import uuid
from datetime import date
from typing import Any, Dict, Iterable, List, Optional

from services import desk_trading as desk
from services import desk_strategy_trades as desk_strat
from services.strategy_limits import MAX_STRATEGY_LEGS, MIN_STRATEGY_LEGS
from services.strategy_plan import templates as tpl

logger = logging.getLogger(__name__)

SCHEMA_V2 = "2"
MAX_STRATEGIES_PER_USER = 200
MAX_VERSIONS_PER_STRATEGY = 50
NAME_MAX = 80
DESCRIPTION_MAX = 500
CHANGE_SUMMARY_MAX = 300
ASSUMPTION_MAX = 300
PRICE_SOURCE_MAX = 120
BUILD_CONSTRAINTS_MAX_BYTES = 4096
MAX_LOTS = 1000
MAX_SHARES = 100_000
MAX_LOT_SIZE = 100_000
MAX_OFFSET_STRIKES = 50
CREATE_SOURCES = ("user", "ai", "template")
BLOCKING_FOR = ["backtest", "paper"]

TOP_FIELDS = ("schema_version", "name", "market", "underlying", "template_id", "timeframe", "legs", "entry", "exit",
              "build_constraints", "sizing")
REQUIRED_TOP = ("schema_version", "name", "market", "underlying", "timeframe", "legs", "entry")
LEG_FIELDS = ("leg_id", "instrument", "side", "lots", "shares", "lot_size_at_save", "expiry", "strike",
              "entry_price_at_save", "relationship")
EXIT_FIELDS = ("profit_target_pct_of_net_debit", "stop_loss_pct_of_net_debit", "time_exit_sessions",
               "close_before_expiry_sessions")
BUILD_FIELDS = ("max_loss_rs", "max_capital_rs", "stop_underlying", "strike_rule", "chain_as_of")
STRIKE_RULE_FIELDS = ("rule", "anchor_strikes", "width_strikes", "target_delta")
INSTRUMENTS = ("STOCK", "FUTURE", "CALL", "PUT")
EXPIRY_RULES = ("specific", "nearest_weekly", "nearest_monthly", "next_monthly", "same_as")
STRIKE_RULES = ("fixed", "atm", "atm_offset_points", "atm_offset_strikes")
BUILD_RULES = ("atm", "otm", "itm", "delta", "manual")
_LEG_ID = re.compile(r"^[A-Za-z0-9_-]{1,8}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

STRATEGY_REF_FIELDS = ("strategy_id", "version_id")
STRATEGY_REF_UNKNOWN = ("strategy_ref must name one of your saved strategy versions: "
                        "{strategy_id, version_id} from the strategy store.")


class StoreInputError(ValueError):
    """A request the store refuses: `code` for the client, `message` in words, `problems` [{field, code, message}]."""

    def __init__(self, code: str, message: str, *, problems: Optional[List[Dict[str, str]]] = None,
                 field: Optional[str] = None, status: int = 422, extra: Optional[Dict[str, Any]] = None):
        super().__init__(code)
        self.code, self.message, self.status = code, message, status
        self.problems = problems or []
        self.field = field
        self.extra = extra or {}

    def detail(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.field:
            out["field"] = self.field
        if self.problems:
            out["problems"] = self.problems
        out.update(self.extra)
        return out


# ── the v2 document ──────────────────────────────────────────────────────────
def is_v2(definition: Any) -> bool:
    return isinstance(definition, dict) and definition.get("schema_version") == SCHEMA_V2


class _Report:
    def __init__(self) -> None:
        self.problems: List[Dict[str, str]] = []

    def add(self, field: str, code: str, message: str) -> None:
        self.problems.append({"field": field, "code": code, "message": message})


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _whole(r: _Report, v: Any, field: str, lo: int, hi: int, code: str) -> bool:
    # A whole number is an int (JSON 1, not 1.0 and not "1" or true): the wizard sends ints.
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        r.add(field, code, f"{field} must be a whole number from {lo} to {hi}.")
        return False
    return True


def _object(r: _Report, raw: Any, field: str, allowed: Iterable[str]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        r.add(field, "invalid_object", f"{field} must be an object.")
        return None
    for k in raw:
        if k not in allowed:
            r.add(f"{field}.{k}" if field else str(k), "unknown_field", f"{k} is not a field of {field or 'the document'}.")
    return raw


def _text(r: _Report, v: Any, field: str, limit: int, *, allow_empty: bool = False) -> None:
    if not isinstance(v, str) or (not allow_empty and not v.strip()) or len(v) > limit:
        what = "0" if allow_empty else "1"
        r.add(field, "invalid_text", f"{field} must be text of {what} to {limit} characters.")


def _day(r: _Report, v: Any, field: str) -> None:
    if not isinstance(v, str) or not _DAY.match(v):
        r.add(field, "invalid_date", f"{field} must be a date, YYYY-MM-DD.")
        return
    try:
        date.fromisoformat(v)
    except ValueError:
        r.add(field, "invalid_date", f"{field} is not a calendar date.")


def _optional_positive(r: _Report, v: Any, field: str, hi: Optional[float] = None) -> None:
    if v is None:
        return
    if not _is_number(v) or v <= 0 or (hi is not None and v > hi):
        r.add(field, "invalid_number", f"{field} must be null or a number above 0" + (f" and at most {hi}." if hi else "."))


def _optional_whole(r: _Report, v: Any, field: str, lo: int, hi: int) -> None:
    if v is not None:
        _whole(r, v, field, lo, hi, "invalid_number")


def _expiry(r: _Report, raw: Any, field: str, leg_ids: List[str], own_id: Any) -> None:
    e = _object(r, raw, field, ("rule", "date", "leg_id"))
    if e is None:
        return
    rule = e.get("rule")
    if rule not in EXPIRY_RULES:
        r.add(f"{field}.rule", "invalid_expiry_rule", f"{field}.rule must be one of {', '.join(EXPIRY_RULES)}.")
        return
    allowed = {"specific": {"rule", "date"}, "same_as": {"rule", "leg_id"}}.get(rule, {"rule"})
    for k in e:
        if k not in allowed:
            r.add(f"{field}.{k}", "unknown_field", f"{k} is not a field of a {rule} expiry.")
    if rule == "specific":
        _day(r, e.get("date"), f"{field}.date")
    elif rule == "same_as":
        target = e.get("leg_id")
        if target == own_id or target not in leg_ids:
            r.add(f"{field}.leg_id", "unknown_leg", f"{field}.leg_id must name another leg of this strategy.")


def _strike(r: _Report, raw: Any, field: str) -> None:
    s = _object(r, raw, field, ("rule", "value"))
    if s is None:
        return
    rule = s.get("rule")
    if rule not in STRIKE_RULES:
        r.add(f"{field}.rule", "invalid_strike_rule", f"{field}.rule must be one of {', '.join(STRIKE_RULES)}.")
        return
    if rule == "atm":
        if "value" in s:
            r.add(f"{field}.value", "unknown_field", "An atm strike has no value.")
        return
    v = s.get("value")
    if rule == "fixed" and not (_is_number(v) and v > 0):
        r.add(f"{field}.value", "invalid_strike", f"{field}.value must be a strike above 0.")
    elif rule == "atm_offset_points" and not _is_number(v):
        r.add(f"{field}.value", "invalid_strike", f"{field}.value must be a number of points from ATM.")
    elif rule == "atm_offset_strikes" and (isinstance(v, bool) or not isinstance(v, int)
                                           or not -MAX_OFFSET_STRIKES <= v <= MAX_OFFSET_STRIKES):
        r.add(f"{field}.value", "invalid_strike",
              f"{field}.value must be a whole number of strikes from -{MAX_OFFSET_STRIKES} to {MAX_OFFSET_STRIKES}.")


def _leg(r: _Report, raw: Any, i: int, leg_ids: List[str], underlying_kind: Any) -> None:
    f = f"legs[{i}]"
    leg = _object(r, raw, f, LEG_FIELDS)
    if leg is None:
        return
    leg_id = leg.get("leg_id")
    if not isinstance(leg_id, str) or not _LEG_ID.match(leg_id):
        r.add(f"{f}.leg_id", "invalid_leg_id", "leg_id must be 1 to 8 letters, digits, - or _.")
    elif leg_ids.index(leg_id) != i:
        r.add(f"{f}.leg_id", "duplicate_leg_id", f"leg_id {leg_id} is used by another leg.")
    instrument = leg.get("instrument")
    if instrument not in INSTRUMENTS:
        r.add(f"{f}.instrument", "invalid_instrument", f"instrument must be one of {', '.join(INSTRUMENTS)}.")
    if leg.get("side") not in ("BUY", "SELL"):
        r.add(f"{f}.side", "invalid_side", "side must be BUY or SELL.")
    if instrument == "STOCK":
        if underlying_kind == "index":
            r.add(f"{f}.instrument", "stock_leg_on_index", "An index cannot be held as shares; use a FUTURE or an option.")
        if "lots" in leg:
            r.add(f"{f}.lots", "lots_not_allowed_for_stock", "A STOCK leg is sized in shares, not lots.")
        if "shares" not in leg:
            r.add(f"{f}.shares", "shares_required", "A STOCK leg needs shares.")
        else:
            _whole(r, leg["shares"], f"{f}.shares", 1, MAX_SHARES, "invalid_shares")
        if leg.get("lot_size_at_save") != 1 or isinstance(leg.get("lot_size_at_save"), bool):
            r.add(f"{f}.lot_size_at_save", "invalid_lot_size", "A STOCK leg's lot_size_at_save is 1.")
        if leg.get("expiry") is not None:
            r.add(f"{f}.expiry", "expiry_not_allowed", "A STOCK leg has no expiry.")
        if leg.get("strike") is not None:
            r.add(f"{f}.strike", "strike_not_allowed", "A STOCK leg has no strike.")
    elif instrument in ("FUTURE", "CALL", "PUT"):
        if "shares" in leg:
            r.add(f"{f}.shares", "shares_only_for_stock", "Only a STOCK leg is sized in shares.")
        if "lots" not in leg:
            r.add(f"{f}.lots", "lots_required", f"A {instrument} leg needs lots.")
        else:
            _whole(r, leg["lots"], f"{f}.lots", 1, MAX_LOTS, "invalid_lots")
        _whole(r, leg.get("lot_size_at_save"), f"{f}.lot_size_at_save", 1, MAX_LOT_SIZE, "invalid_lot_size")
        if leg.get("expiry") is None:
            r.add(f"{f}.expiry", "expiry_required", f"A {instrument} leg needs an expiry.")
        else:
            _expiry(r, leg["expiry"], f"{f}.expiry", leg_ids, leg_id)
        if instrument == "FUTURE":
            if leg.get("strike") is not None:
                r.add(f"{f}.strike", "strike_not_allowed", "A FUTURE leg has no strike.")
        elif leg.get("strike") is None:
            r.add(f"{f}.strike", "strike_required", f"A {instrument} leg needs a strike.")
        else:
            _strike(r, leg["strike"], f"{f}.strike")
    price = leg.get("entry_price_at_save")
    if price is not None:
        p = _object(r, price, f"{f}.entry_price_at_save", ("value", "source"))
        if p is not None:
            if not (_is_number(p.get("value")) and p["value"] > 0):
                r.add(f"{f}.entry_price_at_save.value", "invalid_price", "entry_price_at_save.value must be above 0.")
            _text(r, p.get("source"), f"{f}.entry_price_at_save.source", PRICE_SOURCE_MAX, allow_empty=True)
    rel = leg.get("relationship")
    if rel is not None:
        o = _object(r, rel, f"{f}.relationship", ("covers",))
        if o is not None and (o.get("covers") == leg_id or o.get("covers") not in leg_ids):
            r.add(f"{f}.relationship.covers", "unknown_leg", "relationship.covers must name another leg.")


def validate_definition(raw: Any) -> List[Dict[str, str]]:
    """Every problem with a v2 document, [] when it is valid."""
    r = _Report()
    if not isinstance(raw, dict):
        r.add("definition", "invalid_definition", "The definition must be an object.")
        return r.problems
    for k in raw:
        if k not in TOP_FIELDS:
            r.add(str(k), "unknown_field", f"{k} is not a field of a v2 strategy.")
    for k in REQUIRED_TOP:
        if k not in raw:
            r.add(k, "required", f"{k} is required.")
    if "schema_version" in raw and raw["schema_version"] != SCHEMA_V2:
        r.add("schema_version", "invalid_schema_version", 'schema_version must be "2".')
    if "name" in raw:
        _text(r, raw["name"], "name", NAME_MAX)
    if "market" in raw and raw["market"] != "NSE":
        r.add("market", "invalid_market", "market must be NSE.")
    if "timeframe" in raw and raw["timeframe"] != "1d":
        r.add("timeframe", "timeframe_not_supported", "Only daily (1d) strategies are supported; there is no intraday history.")
    kind = None
    if "underlying" in raw:
        u = _object(r, raw["underlying"], "underlying", ("symbol", "kind"))
        if u is not None:
            try:
                desk.clean_symbol(u.get("symbol"))
            except desk.DeskInputError:
                r.add("underlying.symbol", "invalid_underlying", "underlying.symbol must be an NSE symbol.")
            kind = u.get("kind")
            if kind not in ("index", "stock"):
                r.add("underlying.kind", "invalid_underlying_kind", "underlying.kind must be index or stock.")
    template = raw.get("template_id")
    if template is not None and template not in {e["name"] for e in tpl.CATALOG}:
        r.add("template_id", "invalid_template", "template_id must be a name from GET /api/desk/strategy/templates, or null.")
    if "legs" in raw:
        legs = raw["legs"]
        if not isinstance(legs, list):
            r.add("legs", "invalid_legs", "legs must be a list.")
        elif len(legs) < MIN_STRATEGY_LEGS:
            r.add("legs", "no_legs", f"A strategy has at least {MIN_STRATEGY_LEGS} leg.")
        elif len(legs) > MAX_STRATEGY_LEGS:
            r.add("legs", "too_many_legs", f"A strategy has at most {MAX_STRATEGY_LEGS} legs.")
        else:
            ids = [leg.get("leg_id") if isinstance(leg, dict) else None for leg in legs]
            for i, leg in enumerate(legs):
                _leg(r, leg, i, ids, kind)
    if "entry" in raw:
        e = _object(r, raw["entry"], "entry", ("type", "assumption"))
        if e is not None:
            if e.get("type") != "manual":
                r.add("entry.type", "entry_type_not_supported",
                      'entry.type must be "manual" for now; rule-based entries arrive with the Copilot (Phase 1.3).')
            else:
                _text(r, e.get("assumption"), "entry.assumption", ASSUMPTION_MAX)
    if raw.get("exit") is not None:
        x = _object(r, raw["exit"], "exit", EXIT_FIELDS)
        if x is not None:
            _optional_positive(r, x.get("profit_target_pct_of_net_debit"), "exit.profit_target_pct_of_net_debit", 1000)
            _optional_positive(r, x.get("stop_loss_pct_of_net_debit"), "exit.stop_loss_pct_of_net_debit", 100)
            _optional_whole(r, x.get("time_exit_sessions"), "exit.time_exit_sessions", 1, 250)
            _optional_whole(r, x.get("close_before_expiry_sessions"), "exit.close_before_expiry_sessions", 0, 20)
    if raw.get("build_constraints") is not None:
        bc_raw = raw["build_constraints"]
        try:
            size = len(json.dumps(bc_raw, separators=(",", ":"), allow_nan=False).encode())
        except (TypeError, ValueError):
            size = None
            r.add("build_constraints", "invalid_object", "build_constraints must be plain JSON.")
        if size is not None and size > BUILD_CONSTRAINTS_MAX_BYTES:
            r.add("build_constraints", "build_constraints_too_large",
                  f"build_constraints is larger than {BUILD_CONSTRAINTS_MAX_BYTES} bytes.")
        bc = _object(r, bc_raw, "build_constraints", BUILD_FIELDS)
        if bc is not None:
            for k in ("max_loss_rs", "max_capital_rs", "stop_underlying"):
                _optional_positive(r, bc.get(k), f"build_constraints.{k}")
            if bc.get("chain_as_of") is not None:
                _day(r, bc["chain_as_of"], "build_constraints.chain_as_of")
            if bc.get("strike_rule") is not None:
                sr = _object(r, bc["strike_rule"], "build_constraints.strike_rule", STRIKE_RULE_FIELDS)
                if sr is not None:
                    if sr.get("rule") not in BUILD_RULES:
                        r.add("build_constraints.strike_rule.rule", "invalid_build_rule",
                              f"strike_rule.rule must be one of {', '.join(BUILD_RULES)}.")
                    _whole(r, sr.get("anchor_strikes"), "build_constraints.strike_rule.anchor_strikes",
                           -MAX_OFFSET_STRIKES, MAX_OFFSET_STRIKES, "invalid_number")
                    _whole(r, sr.get("width_strikes"), "build_constraints.strike_rule.width_strikes",
                           0, MAX_OFFSET_STRIKES, "invalid_number")
                    td = sr.get("target_delta")
                    if td is not None and not (_is_number(td) and 0 <= td <= 1):
                        r.add("build_constraints.strike_rule.target_delta", "invalid_number",
                              "strike_rule.target_delta must be null or a number from 0 to 1.")
    if raw.get("sizing") is not None:
        s = _object(r, raw["sizing"], "sizing", ("lots",))
        if s is not None:
            # The wizard's lots setting: lots for an F&O template, SHARES for a cash one (its stepper goes to 100,000).
            _whole(r, s.get("lots"), "sizing.lots", 1, MAX_SHARES, "invalid_lots")
    return r.problems


def clean_definition(raw: Any) -> Dict[str, Any]:
    """The document to store (exactly as sent), or StoreInputError(invalid_definition) with every problem."""
    problems = validate_definition(raw)
    if problems:
        raise StoreInputError("invalid_definition", "The strategy cannot be saved: " + problems[0]["message"],
                              problems=problems)
    return raw


# ── derived answers (never stored) ───────────────────────────────────────────
def asset_class_of(definition: Dict[str, Any]) -> str:
    kinds = {leg["instrument"] for leg in definition["legs"]}
    if kinds == {"STOCK"}:
        return "STOCK"
    return "MIXED" if "STOCK" in kinds else "FNO"


def _expiry_key(leg: Dict[str, Any], by_id: Dict[str, Dict[str, Any]], depth: int = 0) -> Optional[str]:
    e = leg.get("expiry")
    if not isinstance(e, dict):
        return None
    if e.get("rule") == "specific":
        return e.get("date")
    if e.get("rule") == "same_as" and depth < MAX_STRATEGY_LEGS and e.get("leg_id") in by_id:
        return _expiry_key(by_id[e["leg_id"]], by_id, depth + 1)
    return "rule:" + str(e.get("rule"))


def _desk_legs(definition: Dict[str, Any]) -> List[Dict[str, Any]]:
    by_id = {leg["leg_id"]: leg for leg in definition["legs"]}
    out = []
    for leg in definition["legs"]:
        kind = {"STOCK": "cash", "FUTURE": "future"}.get(leg["instrument"], "option")
        out.append({"kind": kind, "side": leg["side"].lower(),
                    "option_type": {"CALL": "call", "PUT": "put"}.get(leg["instrument"]),
                    "lots": leg["shares"] if kind == "cash" else leg["lots"],
                    "lot_size": 1 if kind == "cash" else leg["lot_size_at_save"],
                    "expiry": _expiry_key(leg, by_id)})
    return out


_BLOCKING_MESSAGES = {
    "unbounded_loss": "This structure loses without limit if the underlying rises (net short calls, futures or shares).",
    "naked_short_put": "A short put here is not covered by a long put of the same size or more.",
    "short_futures_not_supported": "A futures-only structure that sells a future has no limit on its loss.",
    "mixed_option_expiries": "The option legs expire on different dates (a calendar or diagonal).",
}
_BLOCKING_SUFFIX = (" It can be saved as a draft, but it is not backtested or paper traded in this release "
                    "(no historical margin model; owner decision D2).")


def checks(definition: Dict[str, Any]) -> List[Dict[str, Any]]:
    """What this valid v2 structure can be used for, from the desk's defined-risk rule (owner decision D2). Each check is
    {code, severity blocking|warning|info, blocking_for, field, message}. Derived on every read, never stored."""
    try:
        verdict = desk_strat.check_defined_risk(_desk_legs(definition))
    except desk.DeskInputError as exc:
        if exc.code == "cash_only_use_share_trade":
            return [{"code": "cash_only", "severity": "info", "blocking_for": [], "field": "legs",
                     "message": "Only shares: record it on the desk as a share trade, not as a structure."}]
        message = _BLOCKING_MESSAGES.get(exc.code, exc.message or exc.code) + _BLOCKING_SUFFIX
        return [{"code": exc.code, "severity": "blocking", "blocking_for": list(BLOCKING_FOR), "field": "legs",
                 "message": message}]
    if verdict.get("futures_exposure"):
        return [{"code": "futures_exposure", "severity": "warning", "blocking_for": [], "field": "legs",
                 "message": verdict.get("note") or desk_strat.FUTURES_HEDGED_NOTE}]
    return []


def _walk(before: Any, after: Any, path: str, out: List[Dict[str, Any]]) -> None:
    if isinstance(before, dict) and isinstance(after, dict):
        for k in sorted(set(before) | set(after)):
            if k == "legs" and not path and isinstance(before.get(k), list) and isinstance(after.get(k), list):
                _walk_legs(before[k], after[k], out)
            else:
                _walk(before.get(k), after.get(k), f"{path}.{k}" if path else str(k), out)
        return
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        for i, (b, a) in enumerate(zip(before, after)):
            _walk(b, a, f"{path}[{i}]", out)
        return
    if before != after or type(before) is not type(after):
        if before == after and _is_number(before) and _is_number(after):
            return                                     # 1 and 1.0 are the same number
        out.append({"path": path, "before": before, "after": after})


def _walk_legs(before: List[Any], after: List[Any], out: List[Dict[str, Any]]) -> None:
    def key(leg: Any, i: int) -> str:
        return str(leg.get("leg_id")) if isinstance(leg, dict) and leg.get("leg_id") is not None else f"#{i}"
    b = {key(leg, i): leg for i, leg in enumerate(before)}
    a = {key(leg, i): leg for i, leg in enumerate(after)}
    order = [key(leg, i) for i, leg in enumerate(before)] + [k for k in (key(leg, i) for i, leg in enumerate(after)) if k not in b]
    for k in order:
        _walk(b.get(k), a.get(k), f"legs[{k}]", out)


def diff(before: Dict[str, Any], after: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Field-by-field differences between two documents: [{path, before, after}], legs keyed by leg_id
    (`legs[L2].strike.value`), a whole leg when one is added or removed, in a fixed order."""
    out: List[Dict[str, Any]] = []
    _walk(before, after, "", out)
    return out


def fingerprint(body: Any) -> str:
    """The desk's request fingerprint (services/desk_trading.request_fingerprint): a replayed Idempotency-Key with a
    different body is told apart from a retry."""
    return desk.request_fingerprint(body)


def clean_idempotency_key(raw: Any) -> Optional[str]:
    """The desk's rule for the Idempotency-Key header (8 to 64 letters, digits or . _ : -), as a StoreInputError."""
    try:
        return desk.clean_idempotency_key(raw)
    except desk.DeskInputError as exc:
        raise StoreInputError(exc.code, exc.message or exc.code, field="Idempotency-Key") from None


# ── the desk's paper-trade link (PAPER LIVE) ─────────────────────────────────
def clean_strategy_ref(raw: Any) -> Dict[str, str]:
    """`strategy_ref {strategy_id, version_id}` on POST /api/desk/paper-trades, shape only."""
    if not isinstance(raw, dict) or set(raw) != set(STRATEGY_REF_FIELDS):
        raise StoreInputError("invalid_strategy_ref", STRATEGY_REF_UNKNOWN, field="strategy_ref")
    try:
        return {k: str(uuid.UUID(str(raw[k]))) for k in STRATEGY_REF_FIELDS}
    except (TypeError, ValueError):
        raise StoreInputError("invalid_strategy_ref", STRATEGY_REF_UNKNOWN, field="strategy_ref") from None


async def resolve_version_ref(uid: str, raw: Any) -> Dict[str, Any]:
    """The caller's own, not archived, strategy version a paper trade cites: {strategy_id, version_id, version_no,
    underlying}. Unknown, archived and another user's are the same 422 (no existence leak)."""
    from services import pg_client                     # the desk imports this module; the pool is only needed here
    ref = clean_strategy_ref(raw)
    try:
        pool = await pg_client.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT v.id, v.version_no, v.definition, s.id AS strategy_id
                     FROM strategy_versions v JOIN strategies s ON s.id = v.strategy_id
                    WHERE v.id = $1 AND s.id = $2 AND s.owner_id = $3 AND NOT s.is_archived""",
                uuid.UUID(ref["version_id"]), uuid.UUID(ref["strategy_id"]), uid)
    except Exception as exc:  # noqa: BLE001 — the store is down: say so, never record a trade with an unchecked link
        logger.exception("strategy store: could not resolve a paper trade's strategy_ref")
        raise StoreInputError("strategy_store_unavailable", "The strategy store could not be read; nothing was recorded.",
                              field="strategy_ref", status=503) from exc
    if row is None:
        raise StoreInputError("invalid_strategy_ref", STRATEGY_REF_UNKNOWN, field="strategy_ref")
    definition = row["definition"]
    if isinstance(definition, str):
        definition = json.loads(definition)
    underlying = ((definition or {}).get("underlying") or {}).get("symbol") if is_v2(definition) else None
    return {"strategy_id": str(row["strategy_id"]), "version_id": str(row["id"]), "version_no": int(row["version_no"]),
            "underlying": underlying}


async def count_open_paper_trades(uid: str, strategy_ids: List[str]) -> Dict[str, int]:
    """Open desk paper trades per strategy that cite one of its versions (PAPER LIVE). One read of the user's open
    trades (at most services/desk_trading.MAX_OPEN_TRADES)."""
    if not strategy_ids:
        return {}
    from deps import db                                # Mongo; imported here so the pure functions need no app config
    counts: Dict[str, int] = {}
    cursor = db[desk.TRADES].find({"user_id": uid, "status": "open", "strategy_ref.strategy_id": {"$in": list(strategy_ids)}},
                                  {"strategy_ref": 1})
    async for doc in cursor:
        sid = ((doc.get("strategy_ref") or {}).get("strategy_id"))
        if sid:
            counts[sid] = counts.get(sid, 0) + 1
    return counts


def problems_with_prefix(problems: List[Dict[str, str]], prefix: str) -> List[Dict[str, str]]:
    """A document's problems as fields of the request body (`definition.legs[0].lots`)."""
    return [{**p, "field": f"{prefix}.{p['field']}" if p["field"] != prefix else prefix} for p in problems]
