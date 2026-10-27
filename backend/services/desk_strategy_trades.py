"""Smart trading desk — instrument-aware paper trades: futures and option strategies (PRD §17.2 #7, §17.6, §17.7).

A strategy paper trade is a record the user keeps, in the same Mongo collection as the share trades
(`desk_paper_trades`) with `kind: "strategy"`; a document without `kind` is a cash share trade and is untouched by
anything here. Nothing here places, changes or cancels an order and nothing imports a broker.

Document (besides `_id`, `user_id`, `status`, `opened_at`, `closed_at`, `created_at`, `updated_at`, as the cash trade):
    kind "strategy" · underlying · symbol (= underlying, so the shared reads keep working) · direction
    ("bullish" | "bearish" | "neutral") · family (controlled list `FAMILIES`) · strategy_plan_id (optional string
    reference to a saved StrategyPlan) · reference_price (the underlying's last close when recorded) ·
    stop_underlying / target_underlying (the underlying levels that invalidate / fulfil the plan, optional) ·
    legs[] {kind future|option|cash, side buy|sell, lots (shares for cash), lot_size, entry_price, expiry, strike,
            option_type call|put, price_source} · signal {signal_at, source_refs[], rule_version, model_version,
            evidence_summary} · entry_rule "at_once" · max_hold_sessions · rules_version "desk-paper-v3" ·
    cost_model · entry_record_hash · events[] (the lifecycle: created, entered, exit_rule_fired, closed).
IMMUTABLE once saved: signal, legs, underlying, direction, family, reference/stop/target levels, entry_record_hash.
Only `close_strategy_trade` writes to a stored strategy trade, and only the closing fields (never those).

Marks (end of day, nothing is filled in):
    future leg   the contract's settle_price that session (nidp.fno_bhavcopy through the data platform's
                 GET /v1/fno/{symbol}/history)
    option leg   the contract's close_price that session — NEVER its settle_price: on an option's expiry day the NSE
                 F&O bhavcopy's settle_price column holds the UNDERLYING's price, not a premium (56 of 56 legs checked
                 on staging), and for a contract that did not trade it is the exchange's theoretical price, so marking
                 at it shows a P&L nobody could have taken. On its expiry date the leg is SETTLED at intrinsic value
                 against the underlying's closing price that day (call: max(U − K, 0), put: max(K − U, 0)); U is the
                 underlying's end-of-day close (nidp.prices_eod), else the bhavcopy's own underlying_price on the
                 expiry date, else the leg stays unsettled and says so
    cash leg     the underlying's end-of-day close
    A leg with no row on a session keeps its last mark and is flagged `no_mark`; before its first row it has no
    mark and the strategy has no P&L. A missing price is never replaced by the entry price or by zero.
P&L per leg = (mark − entry) × lots × lot_size × (+1 buy, −1 sell); the strategy's is the sum of its legs.
Costs: services/strategy_engine's model per leg per side: slippage % of the traded value + flat brokerage; the exit
side is charged for every leg, including at expiry settlement (conservative), and on an open trade it is estimated at
the last marks.

Exit rules (end of day, in this order, from the first session strictly after the IST date the trade was opened; the
underlying's levels are evaluated by services/exit_rules.step, exit-rules-v1, the function the cash trades and the
backtest use):
    stop      the underlying's bar touches `stop_underlying` (bullish: low <= stop; bearish: high >= stop), or opens
              through it (flagged `gap_through_stop`); both stop and target inside one session count as the stop
              (a daily bar does not show which came first); then the PREMIUM stop (below)
    target    the underlying's bar touches `target_underlying`; then the premium target 1
    expiry    every leg that has an expiry has been settled
    time      `max_hold_sessions` sessions held
    manual    the user closes it, at the last marks
    Premium levels (Phase 2.6): when the trade stores the strategy_levels plan at entry (`exit_plan.options`: kind
    debit|credit, entry, planned_stop, target_1, target_2, unit_shares, version; the parallel TradePlan work stores it,
    feat/p2-trade-plan-lifecycle), the WHOLE structure is evaluated on its end-of-day marks each session: a debit
    structure worth no more than planned_stop a unit (a credit one costing at least planned_stop a unit to buy back)
    closes as `stop`, worth at least target_1 (costing at most target_1) as `target`, with `exit_basis: "premium"`.
    target_2 is shown, not acted on: partial exits are not modelled. Without that field, only the rules above apply.
    The Greek review (`exit_plan.options.greek_review`) is a FLAG event, never an exit: the structure's net delta per
    unit (Black-76 at each option's close-price implied volatility, the underlying's close carried to expiry) crossing
    the strategy_levels review level is flagged once.
    The legs are closed at that session's marks (end-of-day settle / close), never at the underlying's touch price:
    the touch is intraday, the option marks are not, and the trade says so (`exit_marked_at_session_marks`).
MFE / MAE are the highest / lowest end-of-session strategy P&L from the first session held through the exit session.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from services import desk_cost_card as cost_card
from services import desk_trading as base
from services import exit_rules as er
from services import option_pricing as op
from services import paper_account
from services.copilot_tools import daas_client

logger = logging.getLogger(__name__)

KIND = "strategy"
RULES_VERSION = "desk-paper-v3"
DIRECTIONS = ("bullish", "bearish", "neutral")
# family → display name. A controlled list; "custom" is for a structure that fits none of them (it is still risk-checked).
FAMILIES = {
    "long_future": "Long future", "short_future": "Short future",
    "long_call": "Long call", "long_put": "Long put",
    "bull_call_spread": "Bull call spread", "bear_put_spread": "Bear put spread",
    "bull_put_spread": "Bull put spread", "bear_call_spread": "Bear call spread",
    "long_straddle": "Long straddle", "long_strangle": "Long strangle",
    "iron_condor": "Iron condor", "iron_butterfly": "Iron butterfly",
    "covered_call": "Covered call", "protective_put": "Protective put", "collar": "Collar",
    "hedged_future": "Hedged future", "custom": "Custom structure",
}
MIN_LEGS, MAX_LEGS = 1, 4
MAX_LOTS = 1_000_000
MAX_LOT_SIZE = 100_000
MAX_SOURCE_REFS = 10
EVIDENCE_MAX = 1000
TEXT_MAX = 200
SIGNAL_FIELDS = {"signal_at", "source_refs", "rule_version", "model_version", "evidence_summary"}
LEG_FIELDS = {"kind", "side", "lots", "lot_size", "entry_price", "expiry", "strike", "option_type", "price_source"}
STRATEGY_FIELDS = {"kind", "underlying", "direction", "family", "strategy_plan_id", "reference_price", "stop_underlying",
                   "target_underlying", "legs", "signal", "entry_rule", "max_hold_sessions", "note"}
MAX_FLAGS = 60

MARK_BASIS_TEXT = {
    "settle": "the contract's end-of-day settle price",
    "close": "the contract's end-of-day close (an option is never marked at its settle price)",
    "expiry_intrinsic": "settled at intrinsic value against the underlying's close on the expiry date",
    "final_settle": "the future's final settle price on its expiry date",
    "underlying_close": "the underlying's end-of-day close",
}
LEG_MARK_SOURCE = "NSE F&O bhavcopy (nidp.fno_bhavcopy via the data platform), end of day"
UNBOUNDED_NOTE = ("Futures losses can exceed the margin posted; this record is a simulation and the loss is not capped "
                  "by the structure.")
FUTURES_HEDGED_NOTE = ("This structure holds a future: margin calls, gaps and daily mark-to-market are not modelled, so it is "
                       "not treated as defined risk even where an option caps the payoff at expiry.")
EXIT_TEXT = {
    "stop": "The underlying's end-of-day bar touched the plan's invalidation level.",
    "target": "The underlying's end-of-day bar touched the plan's target level.",
    "premium_stop": "The whole structure's value on the end-of-day marks reached its premium stop (strategy_levels).",
    "premium_target": "The whole structure's value on the end-of-day marks reached its premium target 1 (strategy_levels).",
    "expiry": "Every leg with an expiry has expired and been settled.",
    "time": "Held for the most sessions the plan allows.",
    "manual": "Closed by you at the last end-of-day marks.",
}
SESSION_MARKS_NOTE = ("The legs are closed at that session's end-of-day marks, not at the underlying's intraday touch price.")

# DaaS contract-history read (nidp/services/daas_api/routers/fno.py, contract_history)
HISTORY_PAGE = 5000
HISTORY_TIMEOUT_S = 20.0


# ── validation ───────────────────────────────────────────────────────────────
Err = base.DeskInputError


def _text(raw: Any, code: str, *, limit: int = TEXT_MAX, required: bool = True) -> Optional[str]:
    if raw is None:
        if required:
            raise Err(code)
        return None
    if not isinstance(raw, str) or base._CONTROL_RE.search(raw):
        raise Err(code)
    out = raw.strip()
    if not out:
        if required:
            raise Err(code)
        return None
    if len(out) > limit:
        raise Err(code)
    return out


def _day_text(raw: Any, code: str) -> date:
    if not isinstance(raw, str) or len(raw) != 10:
        raise Err(code)
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise Err(code) from None


def clean_leg(raw: Any, today: date) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise Err("invalid_leg")
    if set(raw) - LEG_FIELDS:
        raise Err("unknown_field")
    kind = raw.get("kind")
    if kind not in ("future", "option", "cash"):
        raise Err("invalid_leg_kind")
    side = raw.get("side")
    if side not in ("buy", "sell"):
        raise Err("invalid_leg_side")
    lots = base._whole(raw.get("lots"), 1, MAX_LOTS, "invalid_lots")
    lot_size = base._whole(raw.get("lot_size"), 1, MAX_LOT_SIZE, "invalid_lot_size")
    entry = base.clean_price(raw.get("entry_price"), "invalid_entry_price")
    source = _text(raw.get("price_source"), "invalid_price_source")
    expiry = strike = option_type = None
    if kind == "cash":
        if lot_size != 1:
            raise Err("invalid_lot_size")                      # a share is a share: quantity is `lots`
        if raw.get("expiry") is not None or raw.get("strike") is not None or raw.get("option_type") is not None:
            raise Err("invalid_cash_leg")
        if side == "sell":
            raise Err("short_cash_not_supported")
    else:
        expiry = _day_text(raw.get("expiry"), "invalid_expiry")
        if expiry < today:
            raise Err("expiry_in_past")
        if kind == "future":
            if raw.get("strike") is not None or raw.get("option_type") is not None:
                raise Err("invalid_future_leg")
        else:
            strike = base.clean_price(raw.get("strike"), "invalid_strike")
            option_type = raw.get("option_type")
            if option_type not in ("call", "put"):
                raise Err("invalid_option_type")
    return {"kind": kind, "side": side, "lots": lots, "lot_size": lot_size, "entry_price": entry,
            "expiry": expiry.isoformat() if expiry else None, "strike": strike, "option_type": option_type,
            "price_source": source}


def _qty(leg: Dict[str, Any]) -> int:
    return int(leg["lots"]) * int(leg["lot_size"])


def _sign(leg: Dict[str, Any]) -> int:
    return 1 if leg["side"] == "buy" else -1


def check_defined_risk(legs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The defined-risk rule (this release has no short naked options and no short futures-only structure). Raises
    DeskInputError(code) for a structure that breaks it; returns {"defined_risk": bool, "futures_exposure": bool,
    "note": str|None} otherwise.

    Rule, on the payoff at expiry (piecewise linear in the underlying price S >= 0):
      * ANY futures leg makes the structure NOT defined risk (`defined_risk: False`, with a note): a future is marked
        to market daily, can gap, and its loss can exceed the margin posted. This used to return True for a
        futures-only structure, a short future included (study A, R15 / probe D1);
      * a structure with only cash/future legs that SELLS a future is refused → `short_futures_not_supported`
        (owner decision D2, 2026-10-27: futures shorts only after the shared risk service treats them as unbounded,
        with margin and gap stress); a long futures-only structure is allowed and needs a stop on the underlying
        (`new_strategy_trade`, `futures_stop_required`);
      * with any option leg every option leg shares one expiry, and the payoff's slope as S → ∞ must not be negative
        (net short call/future/cash quantity above the long calls would lose without limit upward) → `unbounded_loss`;
      * every short put must be covered by long puts of the same size or more (otherwise the loss, though capped by
        the strike, is a naked short put) → `naked_short_put`.
    The slope: cash/future ± quantity, calls ± quantity, puts 0. Written to match the payoff engine's loss_unbounded
    test (services/strategy_plan); that package is a separate change."""
    options = [leg for leg in legs if leg["kind"] == "option"]
    futures = [leg for leg in legs if leg["kind"] == "future"]
    futures_exposure = bool(futures)
    if all(leg["kind"] == "cash" for leg in legs):
        raise Err("cash_only_use_share_trade")
    if not options:
        if any(leg["side"] == "sell" for leg in futures):
            raise Err("short_futures_not_supported", "A futures-only structure that sells a future has no limit on its "
                                                     "loss; short futures are not recorded until the shared risk service "
                                                     "can size them (margin and gap stress).")
        return {"defined_risk": False, "futures_exposure": True, "note": UNBOUNDED_NOTE}
    if len({leg["expiry"] for leg in options}) > 1:
        raise Err("mixed_option_expiries")
    slope = 0
    for leg in legs:
        if leg["kind"] == "option" and leg["option_type"] == "put":
            continue
        slope += _sign(leg) * _qty(leg)
    if slope < 0:
        raise Err("unbounded_loss")
    long_puts = sum(_qty(leg) for leg in options if leg["option_type"] == "put" and leg["side"] == "buy")
    short_puts = sum(_qty(leg) for leg in options if leg["option_type"] == "put" and leg["side"] == "sell")
    if short_puts > long_puts:
        raise Err("naked_short_put")
    return {"defined_risk": not futures_exposure, "futures_exposure": futures_exposure,
            "note": FUTURES_HEDGED_NOTE if futures_exposure else None}


def structure_key(doc: Dict[str, Any]) -> str:
    """What makes two strategy trades the SAME open structure: the underlying and the legs (kind, side, lots, lot size,
    expiry, strike, option type), in any order. Prices and price sources are left out, so recording the same spread
    again at another premium is still a duplicate (routes/desk_trading.py refuses it while the first is open)."""
    legs = sorted(json.dumps([leg["kind"], leg["side"], int(leg["lots"]), int(leg["lot_size"]), leg.get("expiry"),
                              None if leg.get("strike") is None else float(leg["strike"]), leg.get("option_type")])
                  for leg in doc["legs"])
    digest = hashlib.sha256(json.dumps([doc["underlying"], legs], separators=(",", ":")).encode()).hexdigest()
    return f"{KIND}:{doc['underlying']}:{digest[:32]}"


async def check_exchange_lots(doc: Dict[str, Any], today: Optional[date] = None) -> None:
    """Every futures / options leg's lot size must be the exchange lot, read from the risk gate's reference
    (services/risk_gate/reference.lookup: today's NFO instrument list, else the NSE F&O bhavcopy). The route runs this
    when the F&O risk gate does not judge the structure (its flag off), so a structure is never recorded at a made-up
    lot size (study A, probe D2: NIFTY at lot size 1 reserved Rs 25,000). Fails CLOSED: a lot that cannot be confirmed
    raises `lot_size_unverified` with the reason; a wrong one raises `lot_size_mismatch` with the exchange lot."""
    from services.risk_gate import reference          # here, not at the top: services.risk_gate imports this module

    legs = [(i, leg) for i, leg in enumerate(doc["legs"], start=1) if leg["kind"] != "cash"]
    if not legs:
        return
    day = today or base.ist_date(doc["opened_at"])
    try:
        refs = await reference.lookup(doc["underlying"], {leg["expiry"] for _, leg in legs}, day)
    except Exception as e:  # noqa: BLE001 — fail closed: every leg is then unverifiable, and the reason says so
        logger.error("desk_strategy: exchange lot reference failed for %s (%s)", doc["underlying"], type(e).__name__)
        refs = {}
    wrong: List[str] = []
    unknown: List[str] = []
    for i, leg in legs:
        ref = refs.get(leg["expiry"]) or {}
        lot = ref.get("lot_size")
        if lot is None:
            unknown.append(f"Leg {i}: the exchange lot for the {leg['expiry']} expiry could not be confirmed "
                           f"({ref.get('error') or 'no source could be read'}).")
        elif int(leg["lot_size"]) != int(lot):
            wrong.append(f"Leg {i}: lot size {leg['lot_size']} is not the exchange lot {lot} "
                         f"({ref.get('source')}, {ref.get('as_of')}).")
    if wrong:
        raise Err("lot_size_mismatch", " ".join(wrong + unknown))
    if unknown:
        raise Err("lot_size_unverified", " ".join(unknown) + " Nothing was recorded; try again when the exchange "
                                                             "reference can be read.")


def clean_signal(raw: Any, now: datetime) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise Err("invalid_signal")
    if set(raw) - SIGNAL_FIELDS:
        raise Err("unknown_field")
    signal_at = base.clean_signal_at(raw.get("signal_at"), now)
    if signal_at is None:
        raise Err("invalid_signal_at")
    rule_version = base.clean_strategy_version(raw.get("rule_version"))
    if rule_version is None:
        raise Err("invalid_rule_version")
    model_version = None
    if raw.get("model_version") is not None:
        try:
            model_version = base.clean_strategy_version(raw.get("model_version"))
        except Err:
            raise Err("invalid_model_version") from None
    refs_raw = raw.get("source_refs")
    refs: List[Dict[str, Optional[str]]] = []
    if refs_raw is not None:
        if not isinstance(refs_raw, list) or len(refs_raw) > MAX_SOURCE_REFS:
            raise Err("invalid_source_refs")
        for ref in refs_raw:
            if not isinstance(ref, dict) or set(ref) - {"kind", "ref", "as_of"}:
                raise Err("invalid_source_refs")
            kind = ref.get("kind")
            if not isinstance(kind, str) or not base._KIND_RE.match(kind):
                raise Err("invalid_source_refs")
            try:
                value = _text(ref.get("ref"), "invalid_source_refs", limit=120)
                as_of = _text(ref.get("as_of"), "invalid_source_refs", limit=40, required=False)
            except Err:
                raise Err("invalid_source_refs") from None
            refs.append({"kind": kind, "ref": value, "as_of": as_of})
    evidence = _text(raw.get("evidence_summary"), "invalid_evidence_summary", limit=EVIDENCE_MAX)
    return {"signal_at": signal_at, "source_refs": refs, "rule_version": rule_version,
            "model_version": model_version, "evidence_summary": evidence}


def _level(raw: Any, code: str) -> Optional[float]:
    return None if raw is None else base.clean_price(raw, code)


def record_hash(doc: Dict[str, Any]) -> str:
    """SHA-256 over the parts of the trade that must never change after it is saved."""
    core = {k: doc.get(k) for k in ("underlying", "direction", "family", "strategy_plan_id", "reference_price",
                                      "stop_underlying", "target_underlying", "legs", "signal", "entry_rule", "opened_at")}
    return hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def new_strategy_trade(user_id: str, body: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """A strategy paper-trade document from a request body; raises DeskInputError(code)."""
    body = base._object(body, STRATEGY_FIELDS)
    moment = now or base.utcnow()
    today = moment.astimezone(base.IST).date()
    underlying = base.clean_symbol(body.get("underlying"))
    direction = body.get("direction")
    if direction not in DIRECTIONS:
        raise Err("invalid_direction")
    family = body.get("family")
    if family not in FAMILIES:
        raise Err("invalid_family")
    plan_id = _text(body.get("strategy_plan_id"), "invalid_strategy_plan_id", limit=64, required=False)
    reference = base.clean_price(body.get("reference_price"), "invalid_reference_price")
    stop = _level(body.get("stop_underlying"), "invalid_stop_underlying")
    target = _level(body.get("target_underlying"), "invalid_target_underlying")
    if direction == "neutral":
        if stop is not None or target is not None:
            raise Err("levels_not_supported_neutral")
    elif direction == "bullish":
        if stop is not None and stop >= reference:
            raise Err("stop_not_below_reference")
        if target is not None and target <= reference:
            raise Err("target_not_above_reference")
    else:
        if stop is not None and stop <= reference:
            raise Err("stop_not_above_reference")
        if target is not None and target >= reference:
            raise Err("target_not_below_reference")
    legs_raw = body.get("legs")
    if not isinstance(legs_raw, list) or not MIN_LEGS <= len(legs_raw) <= MAX_LEGS:
        raise Err("invalid_leg_count")
    legs = [clean_leg(leg, today) for leg in legs_raw]
    risk = check_defined_risk(legs)
    if risk["futures_exposure"] and stop is None:
        # A future has no defined loss, so the plan's invalidation level on the underlying is what ends it.
        raise Err("futures_stop_required", "A structure with a futures leg needs a stop on the underlying "
                                           "(stop_underlying): a future's loss is not capped by the structure.")
    rule = body.get("entry_rule")
    if rule is not None and rule != "at_once":
        if rule not in base.ENTRY_RULES:
            raise Err("invalid_entry_rule")
        raise Err("entry_rule_not_supported")             # a conditional entry would need an option price the data cannot give
    max_hold = None
    if body.get("max_hold_sessions") is not None:
        max_hold = base._whole(body.get("max_hold_sessions"), 1, base.MAX_HOLD_SESSIONS, "invalid_max_hold")
    signal = clean_signal(body.get("signal"), moment)
    stamp = base._iso(moment)
    for index, leg in enumerate(legs):
        leg["index"] = index
    doc = {
        "_id": str(uuid.uuid4()),
        "user_id": user_id,
        "kind": KIND,
        "underlying": underlying,
        "symbol": underlying,
        "direction": direction,
        "family": family,
        "strategy_plan_id": plan_id,
        "reference_price": reference,
        "stop_underlying": stop,
        "target_underlying": target,
        "legs": legs,
        "signal": signal,
        "entry_rule": "at_once",
        "entry_window_sessions": None,
        "max_hold_sessions": max_hold,
        "note": base.clean_note(body.get("note")),
        "rules_version": RULES_VERSION,
        "cost_model": dict(base.COST_MODEL),
        "risk": risk,
        "opened_at": stamp,
        "status": "open",
        "closed_at": None,
        "exit_price": None,
        "exit_reason": None,
        "exit_session": None,
        "exit_note": None,
        "realized_pnl_rs": None,
        "created_at": stamp,
        "updated_at": stamp,
    }
    doc["entry_record_hash"] = record_hash(doc)
    doc["events"] = [
        {"type": "created", "at": stamp, "session": None, "text": "Strategy paper trade recorded with its signal and legs; saved as they are, never edited."},
        {"type": "entered", "at": stamp, "session": None, "text": "Entry assumed at the recorded leg prices (at once); not checked against a bar."},
    ]
    return doc


# ── labels ───────────────────────────────────────────────────────────────────
def _fmt_num(value: float) -> str:
    return f"{value:g}"


def _day_label(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')}"


def leg_label(leg: Dict[str, Any]) -> str:
    side = "Buy" if leg["side"] == "buy" else "Sell"
    if leg["kind"] == "cash":
        return f"{side} {leg['lots']} shares"
    unit = "lot" if leg["lots"] == 1 else "lots"
    if leg["kind"] == "future":
        return f"{side} {leg['lots']} {unit} future {_day_label(leg['expiry'])}"
    kind = "call" if leg["option_type"] == "call" else "put"
    return f"{side} {leg['lots']} {unit} {kind} {_fmt_num(leg['strike'])} {_day_label(leg['expiry'])}"


def legs_summary(doc: Dict[str, Any]) -> str:
    """"Bull call spread 1300/1360 · 27 Oct · 2 lots" — the family, the strikes, the expiry, the lots."""
    legs = doc["legs"]
    name = FAMILIES.get(doc.get("family"), "Strategy")
    strikes = sorted({leg["strike"] for leg in legs if leg["kind"] == "option"})
    expiries = sorted({leg["expiry"] for leg in legs if leg.get("expiry")})
    lots = sorted({leg["lots"] for leg in legs})
    parts = [name + (" " + "/".join(_fmt_num(s) for s in strikes) if strikes else "")]
    if expiries:
        parts.append(_day_label(expiries[0]) + (f" +{len(expiries) - 1}" if len(expiries) > 1 else ""))
    parts.append(f"{lots[0]} lot{'s' if lots[0] != 1 else ''}" if len(lots) == 1 else "mixed lots")
    return " · ".join(parts)


# ── the simulation ───────────────────────────────────────────────────────────
def _positive(value: Any) -> Optional[float]:
    return base._positive(value)


def _flag(code: str, text: str, session: Optional[date] = None, price: Optional[float] = None, leg: Optional[int] = None) -> Dict[str, Any]:
    out = base._flag(code, text, session, price)
    out["leg"] = leg
    return out


def _intrinsic(leg: Dict[str, Any], spot: float) -> float:
    strike = float(leg["strike"])
    return max(spot - strike, 0.0) if leg["option_type"] == "call" else max(strike - spot, 0.0)


def rows_by_day(rows: List[Dict[str, Any]]) -> Dict[date, Dict[str, Any]]:
    out: Dict[date, Dict[str, Any]] = {}
    for row in rows or []:
        day = base._day(row.get("as_of_date")) if isinstance(row, dict) else None
        if day is not None:
            out[day] = row
    return out


def _leg_pnl(leg: Dict[str, Any], mark: Optional[float]) -> Optional[float]:
    if mark is None:
        return None
    return round((mark - float(leg["entry_price"])) * _qty(leg) * _sign(leg), 2)


def simulate_strategy(trade: Dict[str, Any], bars: List[Dict[str, Any]], leg_rows: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Run the marks and exit rules over end-of-day data. `bars` are the underlying's session bars (oldest first, as
    desk_trading.session_bars); `leg_rows[i]` are the rows of leg i's contract from the data platform's history read
    (cash legs: []). Returns {entry_status, observations, held_sessions, checked_through, legs: [state per leg],
    gross_pnl_rs, mfe_rs, mae_rs, last_mark_session, flags, exit (or None)}. Never writes."""
    legs = trade["legs"]
    opened = base.ist_date(trade["opened_at"])
    stop, target = trade.get("stop_underlying"), trade.get("target_underlying")
    direction = trade.get("direction")
    max_hold = trade.get("max_hold_sessions")
    by_day = [rows_by_day(rows) for rows in leg_rows]
    bar_by_day = {b["date"]: b for b in bars}
    flags: List[Dict[str, Any]] = []
    states = [{"mark": None, "mark_date": None, "mark_basis": None, "settled": False, "exit_mark": None, "missing_run": False}
              for _ in legs]
    out: Dict[str, Any] = {"entry_status": "assumed", "observations": 0, "held_sessions": 0, "checked_through": None,
                           "legs": states, "gross_pnl_rs": None, "mfe_rs": None, "mae_rs": None,
                           "last_mark_session": None, "flags": flags, "exit": None,
                           "structure_value_per_unit": None, "exit_rules_version": er.VERSION}
    plan = premium_plan(trade)
    rules = er.Rules(side="short" if direction == "bearish" else "long",
                     target=target if direction in ("bullish", "bearish") else None,
                     max_hold_sessions=int(max_hold) if max_hold else None)
    level_state = er.start(float(trade.get("reference_price") or 1.0),
                           stop if direction in ("bullish", "bearish") else None, rules)
    if bars:
        timeline = [b["date"] for b in bars if b["date"] > opened]
    else:
        timeline = sorted({d for rows in by_day for d in rows if d > opened})
        flags.append(_flag("underlying_bars_missing",
                           "The underlying has no end-of-day bars on record, so its stop and target were not checked "
                           "and expiry settlement uses the bhavcopy's own underlying price."))
    pnl_path: List[float] = []
    for day in timeline:
        bar = bar_by_day.get(day)
        if bar is not None and (bar["high"] is None or bar["low"] is None):
            flags.append(_flag("bar_missing_high_low",
                               "This session has no high or low on record; later sessions are not checked until it does.", day))
            break
        out["observations"] += 1
        out["held_sessions"] += 1
        out["checked_through"] = day
        for i, leg in enumerate(legs):
            st = states[i]
            if st["settled"]:
                continue
            row = by_day[i].get(day)
            expiry = date.fromisoformat(leg["expiry"]) if leg.get("expiry") else None
            if leg["kind"] == "cash":
                close = _positive(bar["close"]) if bar else None
                if close is not None:
                    st.update(mark=close, mark_date=day, mark_basis="underlying_close", missing_run=False)
                else:
                    _note_missing(flags, st, i, day, "The underlying has no close this session")
                continue
            if expiry is not None and day >= expiry:
                _settle_leg(flags, st, i, leg, expiry, bar_by_day, by_day[i], day)
                continue                                        # settled, or not possible yet: the last mark stays (flagged)
            mark, basis = None, None
            if row is not None:
                if leg["kind"] == "future":
                    mark, basis = _positive(row.get("settle_price")), "settle"
                else:
                    # An option is marked at its CLOSE only (see the module docstring: its settle_price is the
                    # underlying's price on an expiry day and a theoretical price when it did not trade).
                    mark, basis = _positive(row.get("close_price")), "close"
            if mark is not None:
                st.update(mark=mark, mark_date=day, mark_basis=basis, missing_run=False)
            else:
                _note_missing(flags, st, i, day, "No price for this contract in the bhavcopy this session")
        marks_known = all(st["mark"] is not None for st in states)
        gross = round(sum(_leg_pnl(leg, st["mark"]) for leg, st in zip(legs, states)), 2) if marks_known else None
        out["gross_pnl_rs"] = gross
        if gross is not None:
            pnl_path.append(gross)
            out["mfe_rs"], out["mae_rs"] = max(pnl_path), min(pnl_path)
            out["last_mark_session"] = day
        if plan is not None:
            out["structure_value_per_unit"] = structure_value_per_unit(legs, states, plan)
            _greek_review(trade, plan, legs, states, bar, by_day, day, flags)
        level_state, exit_ = _exit_for_session(trade, bar, day, direction, stop, target, states, legs, out, flags, max_hold,
                                               level_state, rules, plan)
        if exit_ is not None:
            out["exit"] = exit_
            for st in states:
                st["exit_mark"] = st["mark"]
            return out
    for st in states:
        st.pop("missing_run", None)
    return out


def _note_missing(flags: List[Dict[str, Any]], st: Dict[str, Any], index: int, day: date, why: str) -> None:
    if st["missing_run"] or len(flags) >= MAX_FLAGS:
        return
    st["missing_run"] = True
    kept = f"; it keeps its last mark ({_rupees_or_dash(st['mark'])}, {st['mark_date'].isoformat()})" if st["mark"] is not None else "; it has no mark yet"
    flags.append(_flag("no_mark", f"Leg {index + 1}: {why}{kept}. Not filled in from any other price.", day, st["mark"], index))


def _rupees_or_dash(value: Optional[float]) -> str:
    return "—" if value is None else base._rupees(value)


def _settle_leg(flags, st, index, leg, expiry: date, bar_by_day, rows: Dict[date, Dict[str, Any]], day: date) -> None:
    """Settle an expired leg: a future at its final settle price on the expiry date, an option at intrinsic value
    against the underlying's close on the expiry date. Leaves it unsettled (and says why) when that price is unknown."""
    expiry_row = rows.get(expiry)
    if leg["kind"] == "future":
        final = _positive(expiry_row.get("settle_price")) if expiry_row else None
        if final is None:
            if len(flags) < MAX_FLAGS and not st.get("unsettled_flagged"):
                st["unsettled_flagged"] = True
                flags.append(_flag("settlement_unavailable", f"Leg {index + 1}: the future has no settle price on its expiry date "
                                   f"({expiry.isoformat()}); it keeps its last mark.", day, st["mark"], index))
            return
        st.update(mark=final, mark_date=expiry, mark_basis="final_settle", settled=True, missing_run=False)
        flags.append(_flag("expiry_settled", f"Leg {index + 1}: the future expired {expiry.isoformat()}, settled at {base._rupees(final)}.", day, final, index))
        return
    expiry_bar = bar_by_day.get(expiry)
    spot = _positive(expiry_bar["close"]) if expiry_bar else None
    source = "the underlying's end-of-day close"
    if spot is None and expiry_row is not None:
        spot = _positive(expiry_row.get("underlying_price"))
        source = "the bhavcopy's underlying price"
    if spot is None:
        if len(flags) < MAX_FLAGS and not st.get("unsettled_flagged"):
            st["unsettled_flagged"] = True
            flags.append(_flag("settlement_unavailable", f"Leg {index + 1}: no underlying close is on record for the expiry "
                               f"({expiry.isoformat()}); it keeps its last mark and is not settled.", day, st["mark"], index))
        return
    value = round(_intrinsic(leg, spot), 2)
    st.update(mark=value, mark_date=expiry, mark_basis="expiry_intrinsic", settled=True, missing_run=False)
    flags.append(_flag("expiry_settled",
                       f"Leg {index + 1}: expired {expiry.isoformat()}, settled at intrinsic value {base._rupees(value)} against "
                       f"{source} ({base._rupees(spot)}).", day, value, index))


def _exit_for_session(trade, bar, day, direction, stop, target, states, legs, out, flags, max_hold,
                      level_state: er.State, rules: er.Rules, plan: Optional[Dict[str, Any]]):
    """(the level state after this session, the exit or None). Order: the underlying's stop (exit_rules.step: gap,
    then intrabar touch) → the premium stop → the underlying's target → premium target 1 → expiry → time."""
    expired = any(leg.get("expiry") for leg in legs) and all(st["settled"] for leg, st in zip(legs, states) if leg.get("expiry"))
    step_ex: Optional[Dict[str, Any]] = None
    if bar is not None:
        # The session count is the trade's own (a session without an underlying bar still counts as held).
        level_state = replace(level_state, sessions_held=out["held_sessions"] - 1)
        try:
            level_state, step_ex = er.step(level_state, bar, rules, expired=expired)
        except er.IncompleteBar:
            step_ex = None
        if step_ex is not None:
            level_state = replace(level_state, closed=False)          # the legs, not the step, decide the close
    elif (stop is not None or target is not None) and not any(f["code"] == "underlying_bar_missing" for f in flags):
        flags.append(_flag("underlying_bar_missing", "The underlying has no end-of-day bar this session; its stop and target "
                           "were not checked for it.", day))
    premium = _premium_exit(plan, out.get("structure_value_per_unit"))
    reason: Optional[str] = None
    basis: Optional[str] = None
    note: Optional[str] = None
    kind = step_ex["reason"] if step_ex else None
    if kind == "stop":
        reason, basis = "stop", "underlying"
        if step_ex["both_in_range"]:
            note = base.BOTH_IN_RANGE_NOTE
            flags.append(_flag("both_in_range", base.BOTH_IN_RANGE_NOTE, day))
        if step_ex["gapped"]:
            flags.append(_flag("gap_through_stop", f"The underlying opened at {base._rupees(bar['open'])}, beyond the invalidation "
                               "level: a real exit would have been worse than the session's closing marks may show.", day, bar["open"]))
    elif premium == "stop":
        reason, basis, note = "stop", "premium", EXIT_TEXT["premium_stop"]
    elif kind == "target":
        reason, basis = "target", "underlying"
    elif premium == "target":
        reason, basis, note = "target", "premium", EXIT_TEXT["premium_target"]
    elif kind == "expiry" or (bar is None and expired):
        reason = "expiry"
    elif kind == "time" or (bar is None and max_hold and out["held_sessions"] >= int(max_hold)):
        reason = "time"
    if reason is None:
        return level_state, None
    flags.append(_flag("exit_marked_at_session_marks", SESSION_MARKS_NOTE, day))
    return level_state, {"exit_reason": reason, "exit_session": day, "exit_note": note or EXIT_TEXT[reason], "exit_basis": basis}


# ── premium levels and the Greek review (Phase 2.6) ─────────────────────────
def premium_plan(trade: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The strategy_levels plan stored on the trade at entry (`exit_plan.options`), normalised, or None when the trade
    has none (then only the underlying, expiry and time rules apply). THE SEAM with the TradePlan work: it reads
    kind (debit|credit), entry, planned_stop, target_1, target_2 (per unit), unit_shares, version, greek_review — the
    names strategy_levels.compute returns. A structure with a non-option leg gets no premium levels."""
    ep = trade.get("exit_plan")
    opts = ep.get("options") if isinstance(ep, dict) else None
    if not isinstance(opts, dict):
        return None
    if any(leg.get("kind") != "option" for leg in trade.get("legs") or []):
        return None
    kind = opts.get("kind")
    entry, stop = _positive(opts.get("entry")), _positive(opts.get("planned_stop"))
    t1, t2 = _positive(opts.get("target_1")), _positive(opts.get("target_2"))
    unit = _positive(opts.get("unit_shares"))
    if kind not in ("debit", "credit") or entry is None or stop is None or unit is None:
        return None
    return {"kind": kind, "entry_per_unit": entry, "stop_per_unit": stop, "t1_per_unit": t1, "t2_per_unit": t2,
            "unit_shares": unit, "version": opts.get("version"), "source": "exit_plan.options",
            "greek_review": opts.get("greek_review") if isinstance(opts.get("greek_review"), dict) else None}


def public_premium_plan(plan: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return None if plan is None else {k: v for k, v in plan.items() if k != "greek_review"}


def structure_value_per_unit(legs: List[Dict[str, Any]], states: List[Dict[str, Any]], plan: Dict[str, Any]) -> Optional[float]:
    """The whole structure on its marks, per unit: a debit structure's sale value, a credit structure's buy-back cost.
    None while any leg has no mark (nothing is assumed)."""
    if any(st["mark"] is None for st in states):
        return None
    value = sum(_sign(leg) * float(st["mark"]) * _qty(leg) for leg, st in zip(legs, states)) / plan["unit_shares"]
    return round(value if plan["kind"] == "debit" else -value, 4)


def _premium_exit(plan: Optional[Dict[str, Any]], value: Optional[float]) -> Optional[str]:
    if plan is None or value is None:
        return None
    if plan["kind"] == "debit":
        if value <= plan["stop_per_unit"]:
            return "stop"
        if plan["t1_per_unit"] is not None and value >= plan["t1_per_unit"]:
            return "target"
    else:
        if value >= plan["stop_per_unit"]:
            return "stop"
        if plan["t1_per_unit"] is not None and value <= plan["t1_per_unit"]:
            return "target"
    return None


GREEK_KEEP = 0.30           # strategy_levels.S["delta_keep"]: review when a directional delta falls to 30 % of its entry
GREEK_NEUTRAL_LIMIT = 0.20  # strategy_levels.S["neutral_delta_limit"]


def net_delta_per_unit(legs: List[Dict[str, Any]], states: List[Dict[str, Any]], spot: Optional[float], day: date,
                       unit: float) -> Optional[float]:
    """The structure's net delta per unit at this session's close: each option's Black-76 delta at the implied
    volatility of its close mark, the forward taken as the underlying's close carried to expiry (option_pricing's
    last-resort forward: dividends ignored). None when any input is missing or a volatility cannot be solved."""
    if spot is None:
        return None
    total = 0.0
    for leg, st in zip(legs, states):
        if leg["kind"] != "option" or st["mark"] is None or st["settled"]:
            return None
        t = op.year_fraction(op.days_between(day, date.fromisoformat(leg["expiry"])))
        if t <= 0:
            return None
        kind = "CE" if leg["option_type"] == "call" else "PE"
        fwd = spot * math.exp(op.RISK_FREE_RATE * t)
        vol = op.implied_vol(kind, float(st["mark"]), fwd, float(leg["strike"]), t)
        d = op.delta(kind, fwd, float(leg["strike"]), t, vol) if vol else None
        if d is None:
            return None
        total += _sign(leg) * d * _qty(leg)
    return total / unit


def _greek_review(trade, plan, legs, states, bar, by_day, day, flags) -> None:
    """Flag (once) the session the structure's net delta crosses its review level; never an exit."""
    rule = plan.get("greek_review")
    if not rule or any(f["code"] == "greek_review" for f in flags):
        return
    d0 = rule.get("entry_delta_per_unit")
    if not isinstance(d0, (int, float)) or isinstance(d0, bool):
        return
    spot = _positive(bar["close"]) if bar else None
    if spot is None:
        spot = next((_positive(rows.get(day, {}).get("underlying_price")) for rows in by_day if rows.get(day)), None)
    delta = net_delta_per_unit(legs, states, spot, day, plan["unit_shares"])
    if delta is None:
        return
    view = rule.get("view") or trade.get("direction")
    if view == "bullish":
        crossed, level = delta < GREEK_KEEP * d0, f"below {round(GREEK_KEEP * d0, 3)}"
    elif view == "bearish":
        crossed, level = delta > GREEK_KEEP * d0, f"above {round(GREEK_KEEP * d0, 3)}"
    else:
        crossed, level = abs(delta) > GREEK_NEUTRAL_LIMIT, f"beyond ±{GREEK_NEUTRAL_LIMIT}"
    if crossed and len(flags) < MAX_FLAGS:
        flags.append(_flag("greek_review", f"Net delta {round(delta, 3)} a unit is {level} (entry {round(d0, 3)}): the "
                           "strategy_levels Greek rule says review the position. A flag, not an exit.", day, round(delta, 4)))


# ── costs and money figures ─────────────────────────────────────────────────
LEG_SEGMENT = {"future": "futures", "option": "options", "cash": "equity_delivery"}


def strategy_cost_breakdown(trade: Dict[str, Any], exit_marks: List[Optional[float]]) -> Optional[Dict[str, float]]:
    """Round-trip estimated costs in rupees, every leg, entry side and exit side: {brokerage, stt, exchange, sebi, stamp,
    gst, slippage, total}. Under the desk cost card (desk-cost-v2) each leg is priced by its segment (futures, options
    on the premium, a cash leg as equity delivery), the entry side as the leg's own side and the exit side as the
    opposite (services/desk_cost_card.py); under the flat model the trade was opened with (desk-flat-v1, or no model)
    only slippage and brokerage. None when any leg has no exit mark (nothing is assumed)."""
    if any(m is None for m in exit_marks):
        return None
    model = trade.get("cost_model") or base.COST_MODEL_FLAT_V1
    sides = []
    for leg, mark in zip(trade["legs"], exit_marks):
        qty = _qty(leg)
        if cost_card.is_card(model):
            seg, buy = LEG_SEGMENT[leg["kind"]], leg["side"] == "buy"
            sides.append(cost_card.order_side(seg, "BUY" if buy else "SELL", float(leg["entry_price"]) * qty, model))
            sides.append(cost_card.order_side(seg, "SELL" if buy else "BUY", float(mark) * qty, model))
        else:
            sides.append(base.round_trip_breakdown(qty, float(leg["entry_price"]), float(mark), model))
    return cost_card.add(*sides)


def strategy_costs(trade: Dict[str, Any], exit_marks: List[Optional[float]]) -> Optional[float]:
    """The total of `strategy_cost_breakdown`, or None."""
    breakdown = strategy_cost_breakdown(trade, exit_marks)
    return breakdown["total"] if breakdown else None


def exposure_rs(doc: Dict[str, Any]) -> Optional[float]:
    """An UPPER BOUND on what an open strategy can lose, ₹, for the risk governor's book. None when a leg
    is missing a field the bound needs.

    Why this exists: the governor builds its portfolio from desk trades and used to keep only
    `kind in (None, "cash")`, so every multi-leg F&O position — stored with kind="strategy" — was invisible
    to it. A user with ten option structures open read as an empty book with a full risk budget. The
    governor measures a position as quantity x price, so a strategy needs one money figure.

    The bound, deliberately conservative (a governor should refuse rather than permit when unsure):
      * cash and futures legs contribute their full notional (lots x lot size x entry price); a futures
        loss is limited only by the price reaching zero, so notional is the honest measure.
      * a lone option leg contributes the premium paid. `check_defined_risk` forbids naked shorts, so a
        single option leg is always bought and the premium is the whole risk.
      * two or more option legs contribute the strike span x the largest leg quantity. Max loss on a
        vertical is the span less the credit (or the debit paid), so the span is a true upper bound. For a
        four-leg structure it is the OUTER span and therefore overstates a condor, whose real risk is one
        wing. That is the safe direction for a limit check; it is not a P&L figure and is not shown as one.
    """
    legs = doc.get("legs") or []
    total = 0.0

    def qty(leg: Dict[str, Any]) -> Optional[float]:
        lots, size = leg.get("lots"), leg.get("lot_size")
        return None if lots is None or size is None else float(lots) * float(size)

    options = [l for l in legs if l.get("kind") == "option"]
    for leg in legs:
        if leg.get("kind") == "option":
            continue
        q, price = qty(leg), leg.get("entry_price")
        if q is None or price is None:
            return None
        total += q * float(price)

    if len(options) == 1:
        q, price = qty(options[0]), options[0].get("entry_price")
        if q is None or price is None:
            return None
        total += q * float(price)
    elif options:
        strikes = [l.get("strike") for l in options]
        qs = [qty(l) for l in options]
        if any(s is None for s in strikes) or any(q is None for q in qs):
            return None
        total += (max(strikes) - min(strikes)) * max(qs)

    return round(total, 2)


def net_premium(legs: List[Dict[str, Any]], prices: List[Optional[float]]) -> Optional[float]:
    """Cash the option legs bring in (sold) or take out (bought) at those prices, ₹: negative = a debit.
    None without option legs or when an option leg has no price."""
    total, any_option = 0.0, False
    for leg, price in zip(legs, prices):
        if leg["kind"] != "option":
            continue
        if price is None:
            return None
        any_option = True
        total += -_sign(leg) * float(price) * _qty(leg)
    return round(total, 2) if any_option else None


# ── writes (idempotent: the status is part of the filter) ────────────────────
async def close_strategy_trade(db, trade: Dict[str, Any], *, exit_reason: str, exit_session: Optional[date],
                               exit_note: Optional[str], sim: Dict[str, Any], now: Optional[datetime] = None,
                               exit_basis: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], bool]:
    """(the trade as stored afterwards, True when THIS call closed it). Writes the closing fields only: the signal,
    legs and levels are never in the update. Never touches a trade that is not open."""
    stamp = base._iso(now or base.utcnow())
    legs = trade["legs"]
    exit_marks = [st["mark"] for st in sim["legs"]]
    gross = sim["gross_pnl_rs"]
    breakdown = strategy_cost_breakdown(trade, exit_marks)
    costs = breakdown["total"] if breakdown else None
    exit_legs = [{"index": i, "exit_mark": st["mark"], "mark_date": st["mark_date"].isoformat() if st["mark_date"] else None,
                  "mark_basis": st["mark_basis"], "pnl_rs": _leg_pnl(leg, st["mark"])}
                 for i, (leg, st) in enumerate(zip(legs, sim["legs"]))]
    events = list(trade.get("events") or [])
    session_text = exit_session.isoformat() if exit_session else None
    for f in sim.get("flags") or []:
        if f.get("code") == "greek_review":
            events.append({"type": "greek_review", "at": stamp, "session": f.get("session"), "text": f.get("text")})
    if exit_reason != "manual":
        events.append({"type": "exit_rule_fired", "at": stamp, "session": session_text, "reason": exit_reason,
                       "text": exit_note or EXIT_TEXT.get(exit_reason, exit_reason)})
    events.append({"type": "closed", "at": stamp, "session": session_text, "reason": exit_reason,
                   "text": f"Closed ({exit_reason})" + (f" on the {session_text} session." if session_text else ".")})
    change = {
        "status": "closed",
        "closed_at": stamp,
        "exit_reason": exit_reason,
        "exit_session": session_text,
        "exit_note": exit_note,
        "exit_legs": exit_legs,
        "exit_basis": exit_basis,
        "structure_value_per_unit": sim.get("structure_value_per_unit"),
        "exit_rules_version": sim.get("exit_rules_version"),
        "realized_pnl_rs": gross,
        "costs_rs": costs,
        "costs_breakdown": breakdown,
        "net_pnl_rs": round(gross - costs, 2) if gross is not None and costs is not None else None,
        "open_key": None,              # frees the structure for a new trade (routes/desk_trading.py duplicate rule)
        "mfe_rs": sim["mfe_rs"], "mae_rs": sim["mae_rs"],
        "observations": sim["observations"], "held_sessions": sim["held_sessions"],
        "entry_status": "assumed",
        "flags": list(sim["flags"]),
        "checked_through": sim["checked_through"].isoformat() if sim["checked_through"] else None,
        "events": events,
        "updated_at": stamp,
    }
    owner = {"_id": trade["_id"], "user_id": trade["user_id"]}
    res = await db[base.TRADES].update_one({**owner, "status": "open"}, {"$set": change})
    if res.matched_count:
        # As the cash close (desk_trading.close_trade): the account gets back exactly what this structure
        # reserved when it was opened (its capital at risk), plus or minus its net P&L. Here rather than in the
        # route so an exit-rule close (apply_exits, from the list read or the evening script) frees the capital
        # too; only the call that matched the open trade releases, so a racing second close releases nothing.
        await paper_account.release(db, trade["user_id"], trade.get("paper_reserved_rs"),
                                    net_pnl=change["net_pnl_rs"], trade_id=trade["_id"], symbol=trade.get("symbol"))
        return {**trade, **change}, True
    return await db[base.TRADES].find_one(owner), False


# ── data platform reads ──────────────────────────────────────────────────────
async def fetch_contract_rows(underlying: str, leg: Dict[str, Any], start: date) -> List[Dict[str, Any]]:
    """The leg's contract rows from `start`, oldest first, through GET /v1/fno/{symbol}/history. [] when the
    platform has none; raises PricesUnavailable when it could not be read."""
    if leg["kind"] == "cash":
        return []
    if not daas_client.is_configured():
        raise base.PricesUnavailable("the data platform is not configured")
    params: Dict[str, Any] = {"kind": leg["kind"], "expiry": leg["expiry"], "start": start.isoformat(), "limit": HISTORY_PAGE, "offset": 0}
    if leg["kind"] == "option":
        params.update(strike=leg["strike"], option_type="CE" if leg["option_type"] == "call" else "PE")
    rows: List[Dict[str, Any]] = []
    for _ in range(base.MAX_PAGES):
        try:
            body = await daas_client._get(f"/fno/{quote(underlying, safe='')}/history", params=params, timeout=HISTORY_TIMEOUT_S)
        except daas_client.DaasError as exc:
            raise base.PricesUnavailable(str(exc)) from exc
        if body is None:
            return []
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            raise base.PricesUnavailable(f"unexpected answer from /fno/{underlying}/history")
        rows.extend(r for r in data if isinstance(r, dict))
        next_offset = (body.get("pagination") or {}).get("next_offset")
        if next_offset is None:
            return rows
        params = {**params, "offset": int(next_offset)}
    raise base.PricesUnavailable(f"too many rows for {underlying} {leg['expiry']}")


async def fetch_inputs(trade: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[List[Dict[str, Any]]]]:
    """(the underlying's end-of-day bars, each leg's contract rows) for one open strategy trade."""
    opened = base.ist_date(trade["opened_at"])
    bars_task = base.fetch_bars(trade["underlying"], opened - timedelta(days=base.LOOKBACK_DAYS))
    rows_tasks = [fetch_contract_rows(trade["underlying"], leg, opened) for leg in trade["legs"]]
    bars, *rows = await asyncio.gather(bars_task, *rows_tasks)
    return bars, rows


async def apply_exits(db, trades: List[Dict[str, Any]], *, persist: bool = True
                      ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, str]]:
    """Run the exit rules over open strategy trades. (trades as they now stand, {id: simulate result},
    {id: error code} for trades whose prices could not be read). Exits are written with the status in the filter."""
    gate = asyncio.Semaphore(base.FETCH_CONCURRENCY)
    sims: Dict[str, Any] = {}
    errors: Dict[str, str] = {}

    async def one(trade: Dict[str, Any]) -> None:
        try:
            async with gate:
                bars, rows = await fetch_inputs(trade)
            sims[trade["_id"]] = simulate_strategy(trade, bars, rows)
        except base.PricesUnavailable as exc:
            logger.warning("desk_strategy: no prices for strategy trade %s: %s", trade["_id"], exc)
            errors[trade["_id"]] = base.PRICES_UNAVAILABLE
        except Exception as exc:  # noqa: BLE001 — one trade's surprise must not lose every other trade's marks
            logger.exception("desk_strategy: simulating %s failed: %r", trade["_id"], exc)
            errors[trade["_id"]] = base.PRICES_UNAVAILABLE

    open_trades = [t for t in trades if t.get("status") == "open"]
    await asyncio.gather(*(one(t) for t in open_trades))
    out: List[Dict[str, Any]] = []
    for trade in trades:
        sim = sims.get(trade["_id"])
        if trade.get("status") != "open" or sim is None or sim["exit"] is None or not persist:
            out.append(trade)
            continue
        try:
            stored, mine = await close_strategy_trade(db, trade, **sim["exit"], sim=sim)
        except Exception as exc:  # noqa: BLE001 — one failed write must not leave every other trade unmanaged
            # Left open (the close filters on status, so the next run retries it safely) and reported to the job.
            logger.exception("desk_strategy: closing %s by the %s rule failed: %r", trade["_id"], sim["exit"]["exit_reason"], exc)
            sim["close_failed"] = True
            out.append(trade)
            continue
        if mine:
            logger.info("desk_strategy: trade %s (%s) closed by the %s rule on %s", trade["_id"], trade["underlying"],
                        sim["exit"]["exit_reason"], sim["exit"]["exit_session"])
        if stored is not None:
            out.append(stored)
    return out, sims, errors


# ── responses ────────────────────────────────────────────────────────────────
def public_leg(leg: Dict[str, Any], mark: Optional[float], mark_date: Optional[str], basis: Optional[str],
               pnl: Optional[float], flags: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "index": leg["index"], "kind": leg["kind"], "side": leg["side"], "lots": leg["lots"], "lot_size": leg["lot_size"],
        "entry_price": leg["entry_price"], "expiry": leg.get("expiry"), "strike": leg.get("strike"),
        "option_type": leg.get("option_type"), "price_source": leg.get("price_source"), "label": leg_label(leg),
        "mark": mark, "mark_date": mark_date, "mark_basis": basis,
        "mark_basis_text": MARK_BASIS_TEXT.get(basis) if basis else None,
        "mark_source": LEG_MARK_SOURCE if leg["kind"] != "cash" else base.SOURCE,
        "pnl_rs": pnl,
        "flags": [f for f in flags if f.get("leg") == leg["index"]],
    }


def public_strategy_trade(doc: Dict[str, Any], sim: Optional[Dict[str, Any]] = None, mark_error: Optional[str] = None,
                          detail: bool = False) -> Dict[str, Any]:
    """The route's JSON for one strategy trade. An open trade's marks, P&L and flags come from this read's
    simulate_strategy(); a closed trade's from what was stored when it closed. Null where unknown, never 0."""
    is_open = doc.get("status") == "open"
    legs = doc["legs"]
    if is_open:
        states = sim["legs"] if sim else [None] * len(legs)
        marks = [s["mark"] if s else None for s in states]
        mark_dates = [s["mark_date"].isoformat() if s and s["mark_date"] else None for s in states]
        bases = [s["mark_basis"] if s else None for s in states]
        flags = list(sim["flags"]) if sim else []
        gross = sim["gross_pnl_rs"] if sim else None
        breakdown = strategy_cost_breakdown(doc, marks) if gross is not None else None
        costs = breakdown["total"] if breakdown else None
        mfe, mae = (sim["mfe_rs"], sim["mae_rs"]) if sim else (None, None)
        observations = sim["observations"] if sim else None
        held = sim["held_sessions"] if sim else None
        checked = sim["checked_through"].isoformat() if sim and sim["checked_through"] else None
        costs_basis = (f"entry and exit sides, every leg; the exit side estimated at the last marks; {base.costs_text(doc.get('cost_model'))}"
                       if costs is not None else None)
        pnls = [_leg_pnl(leg, m) for leg, m in zip(legs, marks)]
    else:
        exits = {e["index"]: e for e in (doc.get("exit_legs") or [])}
        marks = [exits.get(i, {}).get("exit_mark") for i in range(len(legs))]
        mark_dates = [exits.get(i, {}).get("mark_date") for i in range(len(legs))]
        bases = [exits.get(i, {}).get("mark_basis") for i in range(len(legs))]
        pnls = [exits.get(i, {}).get("pnl_rs") for i in range(len(legs))]
        flags = list(doc.get("flags") or [])
        gross, costs = doc.get("realized_pnl_rs"), doc.get("costs_rs")
        breakdown = doc.get("costs_breakdown")
        mfe, mae = doc.get("mfe_rs"), doc.get("mae_rs")
        observations, held, checked = doc.get("observations"), doc.get("held_sessions"), doc.get("checked_through")
        costs_basis = (f"entry and exit sides, every leg, at the closing marks; {base.costs_text(doc.get('cost_model'))}"
                       if costs is not None else None)
    net = round(gross - costs, 2) if gross is not None and costs is not None else None
    entries = [leg["entry_price"] for leg in legs]
    out = {
        "id": doc["_id"], "kind": KIND, "symbol": doc["underlying"], "underlying": doc["underlying"],
        "direction": doc["direction"], "family": doc["family"], "family_name": FAMILIES.get(doc["family"], doc["family"]),
        "summary_text": legs_summary(doc), "strategy_plan_id": doc.get("strategy_plan_id"),
        "reference_price": doc.get("reference_price"), "stop_underlying": doc.get("stop_underlying"),
        "target_underlying": doc.get("target_underlying"), "note": doc.get("note"),
        "opened_at": doc["opened_at"], "status": doc["status"], "closed_at": doc.get("closed_at"),
        "exit_reason": doc.get("exit_reason"), "exit_session": doc.get("exit_session"), "exit_note": doc.get("exit_note"),
        "entry_rule": doc.get("entry_rule") or "at_once", "entry_status": "assumed", "max_hold_sessions": doc.get("max_hold_sessions"),
        "rules_version": doc.get("rules_version"), "cost_model": doc.get("cost_model") or dict(base.COST_MODEL_FLAT_V1),
        "risk": doc.get("risk"),
        "signal": doc["signal"], "entry_record_hash": doc.get("entry_record_hash"),
        "entry_record_intact": doc.get("entry_record_hash") == record_hash(doc),
        "legs": [public_leg(leg, marks[i], mark_dates[i], bases[i], pnls[i], flags) for i, leg in enumerate(legs)],
        "net_premium_rs": net_premium(legs, entries),
        "mark_premium_rs": net_premium(legs, marks),
        "net_premium_basis": "premium paid (negative) or received (positive) by the option legs at entry, lots × lot size",
        "gross_pnl_rs": gross, "costs_rs": costs, "costs_breakdown": breakdown, "costs_basis": costs_basis, "net_pnl_rs": net,
        "unrealized_pnl_rs": gross if is_open else None,
        "realized_pnl_rs": None if is_open else doc.get("realized_pnl_rs"),
        "mfe_rs": mfe, "mae_rs": mae, "observations": observations, "held_sessions": held, "checked_through": checked,
        "last_mark_date": max((d for d in mark_dates if d), default=None),
        "mark_error": mark_error if is_open else None,
        "flags": flags,
        "event_count": len(doc.get("events") or []),
        "premium_plan": public_premium_plan(premium_plan(doc)),
        "structure_value_per_unit": (sim.get("structure_value_per_unit") if sim else None) if is_open else doc.get("structure_value_per_unit"),
        "exit_basis": None if is_open else doc.get("exit_basis"),
    }
    if detail:
        out["events"] = list(doc.get("events") or [])
    return out
