"""The shared pre-trade risk gate: one decision, recorded, before any position-creating write.

`check(db, req)` runs every check in a fixed order and returns a RiskDecision (allow / block with reasons). It never
raises for a bad or unverifiable input: that is a block with a specific reason code. It raises in one case only —
the decision could not be written to `risk_decisions` (DecisionUnrecorded) — because the decision is the authority
for the write that follows, and an authority nobody can produce afterwards is not one. The caller then writes
nothing (the routes answer 503 risk_decision_unrecorded).

Checks, in order (CHECK_ORDER), each recorded in `checks[]` as pass / fail / skipped:
    controls         the kill switch and the trading halt (services/risk_controls.read); unreadable blocks
    mode             a known mode (services/execution_modes.MODES) that the policy allows; live needs the build to
                     have live execution AND the user a grant, and the policy still has to allow it
    structure        path, action, instrument, symbol and every leg well formed
    defined_risk     no naked short call or put, no futures-only structure, no unhedged futures exposure, one expiry
    lot_size         every futures / options leg's lot size equals the exchange lot (services/risk_gate/reference)
    expiry           every expiry is today or later AND listed
    caps             leg count, lots per leg, capital at risk per trade (policy.LIMITS)
    open_structures  the user's open desk structures stay under the cap (a new structure only)
A check whose inputs are unusable (an invalid structure) is skipped and says so; the structure check has already
blocked. Every check otherwise runs, so a block lists every reason, not only the first.

Capital at risk of a structure is its MAXIMUM LOSS AT EXPIRY at the recorded entry prices, before costs: the payoff
is piecewise linear in the underlying price S >= 0 with kinks only at the strikes, so with a non-negative slope as
S grows (no naked upside) its minimum is at S = 0 or at a strike. That is exact for a single-expiry structure; with
more than one expiry it is not computed (None, so the cap blocks as unknown).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from services import desk_strategy_trades as strat
from services import desk_trading as desk
from services import execution_modes as modes
from services import risk_controls as rc

from . import policy, reference
from .contract import ACTIONS, INSTRUMENTS, PATHS, Check, Reason, RiskDecision, RiskRequest, inputs_hash

logger = logging.getLogger(__name__)

CHECK_ORDER = ("controls", "mode", "structure", "defined_risk", "lot_size", "expiry", "caps", "open_structures")
MAX_USAGE_LISTED = 500


class DecisionUnrecorded(RuntimeError):
    """The decision could not be written to risk_decisions; nothing may be written on its authority."""


class _Run:
    def __init__(self) -> None:
        self.checks: List[Check] = []
        self.reasons: List[Reason] = []

    def record(self, check: str, failures: List[Tuple[str, str]], detail: Optional[str] = None) -> None:
        for code, message in failures:
            self.reasons.append(Reason(code=code, message=message, check=check))
        self.checks.append(Check(check=check, status="fail" if failures else "pass", detail=detail))

    def skip(self, check: str, why: str) -> None:
        self.checks.append(Check(check=check, status="skipped", detail=why))


# ── numbers ──────────────────────────────────────────────────────────────────
def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _whole(value: Any) -> Optional[int]:
    number = _finite(value)
    return int(number) if number is not None and number > 0 and number == int(number) else None


def _expiry_day(value: Any) -> Optional[date]:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


# ── structure ────────────────────────────────────────────────────────────────
def clean_legs(raw_legs: List[Any]) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]]]:
    """(legs with typed values, failures). A leg with any failure is left out of the legs."""
    legs: List[Dict[str, Any]] = []
    failures: List[Tuple[str, str]] = []
    for i, raw in enumerate(raw_legs, start=1):
        bad: List[Tuple[str, str]] = []
        if not isinstance(raw, dict):
            failures.append(("leg_invalid", f"Leg {i} is not a leg."))
            continue
        kind, side = raw.get("kind"), raw.get("side")
        lots, lot_size, entry = _whole(raw.get("lots")), _whole(raw.get("lot_size")), _finite(raw.get("entry_price"))
        if kind not in ("future", "option", "cash"):
            bad.append(("leg_kind_invalid", f"Leg {i}: the kind must be future, option or cash."))
        if side not in ("buy", "sell"):
            bad.append(("leg_side_invalid", f"Leg {i}: the side must be buy or sell."))
        if lots is None:
            bad.append(("leg_lots_invalid", f"Leg {i}: the lots must be a positive whole number."))
        if lot_size is None:
            bad.append(("leg_lot_size_invalid", f"Leg {i}: the lot size must be a positive whole number."))
        if entry is None or entry <= 0:
            bad.append(("leg_price_invalid", f"Leg {i}: the entry price must be a positive number."))
        expiry = strike = option_type = None
        if kind in ("future", "option"):
            expiry = _expiry_day(raw.get("expiry"))
            if expiry is None:
                bad.append(("leg_expiry_invalid", f"Leg {i}: the expiry must be a date (YYYY-MM-DD)."))
        if kind == "option":
            strike, option_type = _finite(raw.get("strike")), raw.get("option_type")
            if strike is None or strike <= 0:
                bad.append(("leg_strike_invalid", f"Leg {i}: an option needs a positive strike."))
            if option_type not in ("call", "put"):
                bad.append(("leg_option_type_invalid", f"Leg {i}: an option is a call or a put."))
        elif kind == "future" and (raw.get("strike") is not None or raw.get("option_type") is not None):
            bad.append(("leg_invalid", f"Leg {i}: a future has no strike or option type."))
        elif kind == "cash" and (lot_size not in (None, 1) or raw.get("expiry") is not None):
            bad.append(("leg_invalid", f"Leg {i}: a cash leg has a lot size of 1 and no expiry."))
        if bad:
            failures += bad
            continue
        legs.append({"kind": kind, "side": side, "lots": lots, "lot_size": lot_size, "entry_price": entry,
                     "expiry": expiry.isoformat() if expiry else None, "strike": strike, "option_type": option_type,
                     "qty": lots * lot_size, "sign": 1 if side == "buy" else -1})
    return legs, failures


def _structure(req: RiskRequest, run: _Run) -> Optional[List[Dict[str, Any]]]:
    """The cleaned legs ([] for cash), or None when the request is unusable."""
    failures: List[Tuple[str, str]] = []
    if req.path not in PATHS:
        failures.append(("path_unknown", f"Unknown path {req.path!r}."))
    if req.action not in ACTIONS:
        failures.append(("action_unknown", f"Unknown action {req.action!r}."))
    if req.instrument not in INSTRUMENTS:
        failures.append(("instrument_unknown", f"Unknown instrument {req.instrument!r}."))
    if not req.user_id.strip():
        failures.append(("user_unknown", "No user to check the position against."))
    if not isinstance(req.symbol, str) or not req.symbol.strip():
        failures.append(("symbol_missing", "No symbol or underlying."))
    legs: List[Dict[str, Any]] = []
    if req.instrument == "cash":
        if req.legs:
            failures.append(("cash_with_legs", "A cash position has no legs."))
        if req.quantity is not None and _whole(req.quantity) is None:
            failures.append(("quantity_invalid", "The quantity must be a positive whole number of shares."))
    elif req.instrument == "structure":
        if not req.legs:
            failures.append(("no_legs", "A structure needs at least one leg."))
        legs, leg_failures = clean_legs(req.legs)
        failures += leg_failures
        if legs and not leg_failures and all(leg["kind"] == "cash" for leg in legs):
            failures.append(("no_derivative_leg", "A structure needs at least one futures or options leg."))
    run.record("structure", failures)
    return None if failures else legs


# ── defined risk and capital at risk ─────────────────────────────────────────
def _slopes(legs: List[Dict[str, Any]]) -> Tuple[float, float]:
    """(payoff slope as S grows without bound, payoff slope as S falls to 0 counting futures and options only)."""
    up = down = 0.0
    for leg in legs:
        signed = leg["sign"] * leg["qty"]
        if leg["kind"] in ("future", "cash") or leg["option_type"] == "call":
            up += signed
        if leg["kind"] == "future":
            down += signed
        elif leg["option_type"] == "put":
            down -= signed
    return up, down


def defined_risk_failures(legs: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
    fno = [leg for leg in legs if leg["kind"] != "cash"]
    options = [leg for leg in fno if leg["kind"] == "option"]
    out: List[Tuple[str, str]] = []
    if len({leg["expiry"] for leg in fno}) > 1:
        out.append(("mixed_expiries", "Every futures and options leg must share one expiry; with two, the loss "
                                      "after the first expires is not defined by the structure."))
    if not options:
        out.append(("futures_only", "A futures-only structure has no defined maximum loss; hedge it with options."))
        return out
    up, down = _slopes(legs)
    if up < 0:
        if any(leg["option_type"] == "call" and leg["side"] == "sell" for leg in options):
            out.append(("naked_short_call", "Short calls are not covered: the loss grows without limit as the "
                                            "underlying rises."))
        else:
            out.append(("unhedged_future", "A short future is not covered by long calls: the loss grows without "
                                           "limit as the underlying rises."))
    if down > 0:
        short_puts = sum(leg["qty"] for leg in options if leg["option_type"] == "put" and leg["side"] == "sell")
        long_puts = sum(leg["qty"] for leg in options if leg["option_type"] == "put" and leg["side"] == "buy")
        if short_puts > long_puts:
            out.append(("naked_short_put", "Short puts are not covered by long puts of the same size."))
        elif not any(code == "unhedged_future" for code, _ in out):
            out.append(("unhedged_future", "A long future is not covered by long puts: the loss runs to the "
                                           "future's full value as the underlying falls."))
    return out


def _payoff(legs: List[Dict[str, Any]], spot: float) -> float:
    total = 0.0
    for leg in legs:
        if leg["kind"] in ("future", "cash"):
            value = spot
        elif leg["option_type"] == "call":
            value = max(spot - leg["strike"], 0.0)
        else:
            value = max(leg["strike"] - spot, 0.0)
        total += leg["sign"] * leg["qty"] * (value - leg["entry_price"])
    return total


def structure_capital_at_risk(legs: List[Dict[str, Any]]) -> Optional[float]:
    """Maximum loss at expiry, ₹ (see the module docstring). None when it is unbounded or not one expiry."""
    if not legs or len({leg["expiry"] for leg in legs if leg["kind"] != "cash"}) > 1:
        return None
    if _slopes(legs)[0] < 0:
        return None
    points = [0.0] + sorted({leg["strike"] for leg in legs if leg["kind"] == "option"})
    worst = min(_payoff(legs, s) for s in points)
    return round(max(0.0, -worst), 2)


def _defined_risk(req: RiskRequest, legs: Optional[List[Dict[str, Any]]], run: _Run) -> None:
    if legs is None:
        return run.skip("defined_risk", "the structure is not valid")
    if req.instrument == "cash":
        return run.record("defined_risk", [], "a long share position: the loss is limited to the capital deployed")
    if not policy.LIMITS.require_defined_risk:
        return run.record("defined_risk", [], "not required by the policy")
    run.record("defined_risk", defined_risk_failures(legs))


# ── exchange reference ───────────────────────────────────────────────────────
async def _references(req: RiskRequest, legs: Optional[List[Dict[str, Any]]], today: date) -> Dict[str, Dict[str, Any]]:
    if not legs or req.instrument != "structure":
        return {}
    expiries = {leg["expiry"] for leg in legs if leg["kind"] != "cash"}
    try:
        return await reference.lookup(req.symbol.strip().upper(), expiries, today)
    except Exception as e:  # noqa: BLE001 — fail closed: every leg is then unverifiable
        logger.error("risk_gate: contract reference failed for %s (%s)", req.symbol, type(e).__name__)
        return {}


def _lot_size(req: RiskRequest, legs, refs: Dict[str, Dict[str, Any]], run: _Run) -> None:
    if legs is None:
        return run.skip("lot_size", "the structure is not valid")
    if req.instrument == "cash":
        return run.skip("lot_size", "not applicable to a share position")
    failures = []
    for i, leg in enumerate(legs, start=1):
        if leg["kind"] == "cash":
            continue
        ref = refs.get(leg["expiry"]) or {}
        exchange_lot = ref.get("lot_size")
        if exchange_lot is None:
            why = ref.get("error") or "no source could be read"
            failures.append(("lot_size_unverified", f"Leg {i}: the exchange lot for the {leg['expiry']} expiry "
                                                    f"could not be confirmed ({why})."))
        elif leg["lot_size"] != exchange_lot:
            failures.append(("lot_size_mismatch", f"Leg {i}: lot size {leg['lot_size']} is not the exchange lot "
                                                  f"{exchange_lot} ({ref.get('source')}, {ref.get('as_of')})."))
    run.record("lot_size", failures)


def _expiry(req: RiskRequest, legs, refs: Dict[str, Dict[str, Any]], today: date, run: _Run) -> None:
    if legs is None:
        return run.skip("expiry", "the structure is not valid")
    if req.instrument == "cash":
        return run.skip("expiry", "not applicable to a share position")
    failures = []
    for expiry in sorted({leg["expiry"] for leg in legs if leg["kind"] != "cash"}):
        ref = refs.get(expiry) or {}
        if date.fromisoformat(expiry) < today:
            failures.append(("expiry_past", f"The {expiry} expiry is in the past."))
        elif ref.get("listed") is None:
            why = ref.get("error") or "no source could be read"
            failures.append(("expiry_unverified", f"The {expiry} expiry could not be confirmed as listed ({why})."))
        elif ref.get("listed") is False:
            failures.append(("expiry_not_listed", f"No contract is listed for the {expiry} expiry "
                                                  f"({ref.get('source')}, {ref.get('as_of')})."))
    run.record("expiry", failures)


# ── caps and the open book ───────────────────────────────────────────────────
def _capital(req: RiskRequest, legs: Optional[List[Dict[str, Any]]]) -> Optional[float]:
    given = _finite(req.capital_at_risk_rs)
    given = given if given is not None and given > 0 else None
    if req.instrument == "cash":
        return given
    computed = structure_capital_at_risk(legs or [])
    if computed is None:
        return None
    return max(computed, given) if given is not None else computed


def _caps(req: RiskRequest, legs: Optional[List[Dict[str, Any]]], run: _Run) -> Optional[float]:
    if legs is None:
        run.skip("caps", "the structure is not valid")
        return None
    limits = policy.LIMITS
    failures = []
    if req.instrument == "structure":
        if len(legs) > limits.max_legs:
            failures.append(("too_many_legs", f"{len(legs)} legs; the policy allows at most {limits.max_legs}."))
        for i, leg in enumerate(legs, start=1):
            if leg["kind"] != "cash" and leg["lots"] > limits.max_lots_per_leg:
                failures.append(("lots_per_leg_exceeded", f"Leg {i}: {leg['lots']} lots; the policy allows at most "
                                                          f"{limits.max_lots_per_leg} per leg."))
    capital = _capital(req, legs)
    if capital is None:
        failures.append(("capital_at_risk_unknown", "The capital at risk could not be worked out, so the cap "
                                                    "cannot be checked."))
    elif capital > limits.max_capital_at_risk_rs:
        failures.append(("capital_at_risk_exceeded", f"Capital at risk ₹{capital:,.2f} is above the per-trade cap "
                                                     f"of ₹{limits.max_capital_at_risk_rs:,.0f}."))
    run.record("caps", failures, None if capital is None else f"capital at risk ₹{capital:,.2f}")
    return capital


def _open_filter(user_id: str) -> Dict[str, Any]:
    return {"user_id": user_id, "kind": strat.KIND, "status": "open"}


def _counts_open(req: RiskRequest) -> bool:
    return req.instrument == "structure" and req.action == "open"


async def _count_open(db, req: RiskRequest) -> Optional[int]:
    """The user's open desk structures; None when they cannot be counted (the check then blocks)."""
    try:
        return int(await db[desk.TRADES].count_documents(_open_filter(req.user_id)))
    except Exception as e:  # noqa: BLE001 — fail closed
        logger.error("risk_gate: open structures unreadable for %s (%s)", req.user_id, type(e).__name__)
        return None


def _open_structures(req: RiskRequest, count: Optional[int], run: _Run) -> None:
    if not _counts_open(req):
        return run.skip("open_structures", "only a new structure counts towards the cap")
    limit = policy.LIMITS.max_open_structures
    if count is None:
        return run.record("open_structures", [("open_structures_unverified",
                                               "The open structures could not be counted.")])
    failures = []
    if count >= limit:
        failures.append(("open_structures_exceeded", f"{count} structures are open; the policy allows at most "
                                                     f"{limit}."))
    run.record("open_structures", failures, f"{count} open")


def _controls(state: Optional[Dict[str, Any]], run: _Run) -> None:
    """`state` is the snapshot's controls: None when they could not be read (an unreadable kill switch never reads as off)."""
    if state is None:
        return run.record("controls", [("controls_unreadable", "The kill switch and halt could not be read, so new "
                                                               "risk is refused.")])
    failures = []
    if state.get("kill_switch"):
        failures.append(("kill_switch_on", f"The kill switch is on ({state.get('reason') or 'no reason given'})."))
    if state.get("halted"):
        failures.append(("trading_halted", f"Trading is halted ({state.get('reason') or 'no reason given'})."))
    run.record("controls", failures)


def _mode(req: RiskRequest, live_allowed: Optional[bool], run: _Run) -> None:
    """`live_allowed` is the snapshot's answer to modes.is_live_allowed, read only for a live request."""
    if req.mode not in modes.MODES:
        return run.record("mode", [("mode_unknown", f"Unknown mode {req.mode!r}.")])
    if req.mode == "live" and not live_allowed:
        if not modes.LIVE_EXECUTION_AVAILABLE:
            return run.record("mode", [("live_execution_unavailable", "Live execution does not exist in this "
                                                                      "release.")])
        return run.record("mode", [("live_not_authorized", "This account holds no live authorization.")])
    if req.mode not in policy.LIMITS.allowed_modes:
        return run.record("mode", [("mode_not_allowed", f"The {req.mode} mode is not allowed by policy "
                                                        f"{policy.POLICY_VERSION}.")])
    run.record("mode", [])


# ── the decision ─────────────────────────────────────────────────────────────
# A decision is made in two steps. gather() reads everything outside the request that the checks depend on (the
# controls, the live grant, the exchange reference, the open-structure count) into one snapshot; decide() is a pure
# function of the request and that snapshot. The snapshot is stored with the decision, so replay.py can run decide()
# again on exactly what the gate saw and show whether the same code and policy reach the same outcome.
SNAPSHOT_VERSION = "decision-snapshot-v1"


def bson_safe(value: Any) -> Any:
    """A JSON round trip: dates and other non-JSON values become strings, so the snapshot stores and hashes the same."""
    return json.loads(json.dumps(value, default=str))


def snapshot_hash(snapshot: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


async def gather(db, req: RiskRequest, today: date) -> Dict[str, Any]:
    """Every outside read a decision depends on. Each read fails closed: an unreadable value is stored as None and the
    check that uses it blocks."""
    try:
        state = await rc.read(db, req.user_id)
        controls: Optional[Dict[str, Any]] = {"kill_switch": bool(state.get("kill_switch")),
                                              "halted": bool(state.get("halted")), "reason": state.get("reason")}
    except Exception:  # noqa: BLE001 — rc.read logs it; an unreadable kill switch must never read as off
        controls = None
    live_allowed = await modes.is_live_allowed(db, req.user_id) if req.mode == "live" else None
    legs = _structure(req, _Run())
    refs = await _references(req, legs, today)
    open_count: Any = (await _count_open(db, req)) if _counts_open(req) else "n/a"
    return bson_safe({"request": req.model_dump(), "today": today.isoformat(), "controls": controls,
                      "live_allowed": live_allowed, "references": refs, "open_structures": open_count})


def decide(req: RiskRequest, snapshot: Dict[str, Any]) -> Tuple[_Run, Optional[float]]:
    """The checks, in CHECK_ORDER, on the request and a gathered snapshot. No I/O."""
    run = _Run()
    today = date.fromisoformat(snapshot["today"])
    refs = snapshot.get("references") or {}
    _controls(snapshot.get("controls"), run)
    _mode(req, snapshot.get("live_allowed"), run)
    legs = _structure(req, run)
    _defined_risk(req, legs, run)
    _lot_size(req, legs, refs, run)
    _expiry(req, legs, refs, today, run)
    capital = _caps(req, legs, run)
    count = snapshot.get("open_structures")
    _open_structures(req, count if isinstance(count, int) else None, run)
    return run, capital


async def check(db, req: RiskRequest, *, now: Optional[datetime] = None) -> RiskDecision:
    moment = now or rc.utcnow()
    today = moment.astimezone(desk.IST).date()
    await rc.ensure_indexes(db)
    snapshot = await gather(db, req, today)
    run, capital = decide(req, snapshot)
    decision = RiskDecision(
        decision_id=str(uuid.uuid4()), outcome="block" if run.reasons else "allow", reasons=run.reasons,
        checks=run.checks, policy_version=policy.POLICY_VERSION, inputs_hash=inputs_hash(req),
        at=moment.astimezone(timezone.utc).isoformat(), correlation_id=req.correlation_id)
    await _persist(db, req, decision, capital, snapshot)
    return decision


async def _persist(db, req: RiskRequest, decision: RiskDecision, capital: Optional[float],
                   snapshot: Optional[Dict[str, Any]] = None) -> None:
    """The risk_decisions row: the fields rc.record_decision writes (so the stream reads the same), plus path, mode,
    inputs_hash, the checks, the actor and the snapshot the decision was made on. `outcome` uses that stream's words,
    allowed / blocked."""
    quantity = _whole(req.quantity) if req.instrument == "cash" else None
    row = {
        "_id": decision.decision_id,
        "user_id": req.user_id,
        "at": decision.at,
        "action": req.path,
        "outcome": "allowed" if decision.outcome == "allow" else "blocked",
        "symbol": req.symbol,
        "requested_qty": quantity,
        "approved_qty": None,
        "reasons": [r.model_dump() for r in decision.reasons],
        "limits_version": decision.policy_version,
        "policy_version": decision.policy_version,
        "correlation_id": decision.correlation_id,
        "detail": {"instrument": req.instrument, "action": req.action, "legs": len(req.legs),
                   "capital_at_risk_rs": capital},
        "path": req.path,
        "mode": req.mode,
        "inputs_hash": decision.inputs_hash,
        "checks": [c.model_dump() for c in decision.checks],
        "actor_id": req.actor_id,
        "source": "risk_gate",
    }
    if snapshot is not None:
        row.update({"snapshot": snapshot, "snapshot_version": SNAPSHOT_VERSION, "snapshot_hash": snapshot_hash(snapshot)})
    try:
        await db[rc.DECISIONS].insert_one(row)
    except Exception as e:  # noqa: BLE001 — re-raised: nothing may be written on an unrecorded decision
        logger.error("risk_gate: decision NOT recorded for %s (%s): path=%s outcome=%s", req.user_id,
                     type(e).__name__, req.path, decision.outcome)
        raise DecisionUnrecorded("the risk decision could not be recorded") from e
    if decision.outcome == "block":
        logger.warning("risk_gate: %s blocked for %s (%s): %s", req.path, req.user_id, req.symbol or "-",
                       ",".join(r.code for r in decision.reasons))


async def usage(db, user_id: str) -> Dict[str, Any]:
    """The user's open desk structures and their capital at risk (the same figure the cap uses). The total is None
    when any open structure's figure cannot be worked out: an unknown is never counted as zero."""
    docs = await db[desk.TRADES].find(_open_filter(user_id)).to_list(MAX_USAGE_LISTED)
    total, unknown = 0.0, 0
    for doc in docs:
        legs, failures = clean_legs(doc.get("legs") or [])
        capital = None if failures else structure_capital_at_risk(legs)
        if capital is None:
            unknown += 1
        else:
            total += capital
    return {"open_structures": len(docs), "capital_at_risk_rs": None if unknown else round(total, 2),
            "capital_at_risk_unknown": unknown}
