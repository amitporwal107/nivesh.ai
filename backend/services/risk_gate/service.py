"""The universal risk-decision service (Phase 1, items 1.1-1.7): ONE decision, recorded, before ANY position is written,
on every entry path — the desk cash and strategy POST, the journal create and ENTRY fill, the AI-trader signals and
confirm. It grows the F&O risk gate (gate.py: controls, mode, structure, defined risk, exchange lot, expiry) and runs
the AI-trader governor (services/ai_trader/risk_governor.evaluate) as one of its checks; it is not a third engine.

    enter(db, EntryRequest)  ->  decision {decision_id, outcome allow|reduce|block, requested_qty|lots,
                                           approved_qty|lots, reasons[{code, check, severity, value, limit, message}],
                                           checks[], estimated_risk_rs{gross, costs, gap_stress, total, stop_based},
                                           budget{...}, policy_version, limits_version, inputs_hash, snapshot_hash,
                                           reservation_id, correlation_id, freshness{...}}

MANDATORY. No flag turns any of the checks below off. The KNOWN_FEATURES flag `fno_risk_gate` now gates ONLY the
rollout of ADDITIONAL F&O structure checks (check `fno_additional`: the gate's fixed caps of 4 legs, 10 lots per leg,
Rs 2 lakh capital at risk per structure and 10 open structures, and its stricter refusal of futures-only and unhedged
futures structures). Every core check runs whatever the flag says, so no API or UI path can bypass them.

SERVER-RESOLVED INPUTS ONLY (services/risk_gate/inputs.py, services/risk_book.py): the instrument's last close and its
date, its sector, its average traded value, the exchange lot and listed expiry, the market state (India VIX, regime),
the account's equity, peak, open book and period P&L, and the risk profile. The request carries only what the user
asked for: the instrument, the quantity or legs and the levels. A client value for any resolved input is never read.

CHECKS (CHECK_ORDER; each recorded as pass / fail / skipped with a detail). A block lists every failing reason.
    controls        kill switch and trading halt; unreadable -> block
    mode            a known mode the policy allows (live refused: services/execution_modes.LIVE_EXECUTION_AVAILABLE)
    structure       the request is well formed
    levels          a stop on the right side (every path, the journal included), a target where reward:risk needs one
    inputs          every required input known and fresh (services/data_freshness): last close, sector, market state,
                    average traded value (shares), equity and its marks, the open book; the entry within
                    MAX_ENTRY_DISTANCE_PCT of the last close
    defined_risk    structures: the desk's defined-risk rule (no unbounded upside, no naked short put, one option
                    expiry, no short futures-only)
    lot_size        structures: every futures/options lot is the exchange lot (unverifiable -> block)
    expiry          structures: every expiry listed and not past (unverifiable -> block)
    per_trade_risk  estimated risk (services/risk_gate/estimate.py: stop loss + costs + gap stress) within
                    per_trade_risk_pct of equity: REDUCE to the largest valid quantity / lot count, or BLOCK when the
                    smallest valid one exceeds the budget (min_qty_exceeds_budget). An add (journal fill) must stay
                    within the original plan's reserved budget (add_exceeds_original_budget)
    reward_risk     (reward - costs) / (stop loss + costs) >= min_reward_risk
    governor        shares: risk_governor.evaluate on the server-resolved intent and the shared book, with the
                    profile's limits (stop distance, already held, positions, position size, net exposure, sector,
                    liquidity, VIX, regime, drawdown halt); halt / reject / defer -> block, reduce -> reduce
    position        structures: market exposure within max_position_pct of equity
    open_risk       open estimated risk + this entry within max_open_risk_pct of equity (reduce / block)
    exposure        total market exposure within the governor's net-exposure limit (structures; shares: governor)
    sector          the sector's market exposure + this entry within max_sector_pct of equity (reduce / block)
    correlation     SKIPPED, said so: no reliable return-correlation source for paper positions exists; same-sector
                    exposure (check sector) is the concentration control
    daily_loss      day P&L (realised + unrealised, net) known and the loss below daily_loss_pct of start-of-day equity
    weekly_loss     the same for the ISO week
    drawdown        drawdown from the configured equity peak known and below max_drawdown_pct (new entries only;
                    nothing is liquidated)
    funding         the paper account's available cash covers the position's funding
    fno_additional  (flag) the additional F&O structure checks above
Outcome: block when any reason blocks; else reduce when the approved size is below the request; else allow.

RECORDED AND RESERVED. The decision row (risk_decisions, source "risk_service") is written BEFORE anything else: a
decision that cannot be recorded raises DecisionUnrecorded (the route answers 503 and writes nothing). Then, when the
decision allows (or reduces and the caller accepts the reduced size), the reservation is taken atomically on the
paper account (services/paper_account.reserve_entry) under reservation_id = decision_id. A reservation the account
refuses (another entry took the budget first) is recorded as a second, blocking row that `supersedes` the first.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from services import data_freshness as fresh
from services import desk_strategy_trades as strat
from services import desk_trading as desk
from services import execution_modes as modes
from services import paper_account as acct
from services import risk_book
from services import risk_controls as rc
from services import risk_profile
from services.ai_trader import risk_governor as gov

from . import estimate as est
from . import gate, inputs, policy, reference

logger = logging.getLogger(__name__)

POLICY_VERSION = "universal-risk-v1"
SNAPSHOT_VERSION = "risk-service-snapshot-v1"
SOURCE = "risk_service"
PATHS = ("desk_paper_trade", "journal_create", "journal_fill", "ai_trader_signal", "ai_trader_confirm")
ACTIONS = ("open", "add")
INSTRUMENTS = ("cash", "structure")
MAX_ENTRY_DISTANCE_PCT = 20.0
#: Freshness budgets, in sessions (services/data_freshness): the last close and the market state.
LAST_CLOSE_BUDGET = 2
MARKET_STATE_BUDGET = 2
CHECK_ORDER = ("controls", "mode", "structure", "levels", "inputs", "defined_risk", "lot_size", "expiry",
               "per_trade_risk", "reward_risk", "governor", "position", "open_risk", "exposure", "sector",
               "correlation", "daily_loss", "weekly_loss", "drawdown", "funding", "fno_additional")
BLOCKING = ("block", "halt", "reject", "defer")
CORRELATION_TEXT = ("not checked: no reliable return-correlation source exists for paper positions (the MF engine's "
                    "graph.correlations covers funds, not shares); same-sector exposure (check sector) is the "
                    "concentration control in this release")
EVENT_TEXT = ("event window not checked: no event-calendar read is wired into decisions in this release (the "
              "governor's EVENT_BLACKOUT rule stays unset)")


class DecisionUnrecorded(RuntimeError):
    """The decision could not be written to risk_decisions; nothing may be written on its authority."""


class EntryRequest(BaseModel):
    """One position-creating write before it happens. Only what the user asked for; nothing the server resolves."""
    model_config = ConfigDict(extra="forbid")

    correlation_id: str
    user_id: str
    actor_id: str
    mode: str
    path: str
    action: str = "open"
    instrument: str = "cash"
    symbol: Optional[str] = None
    quantity: Optional[float] = None            # shares (cash); None for a journal plan (notional_rs instead)
    notional_rs: Optional[float] = None         # a journal plan's capital: the planned quantity is worked out here
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    legs: List[Dict[str, Any]] = Field(default_factory=list)
    direction: Optional[str] = None
    reference_price: Optional[float] = None
    stop_underlying: Optional[float] = None
    target_underlying: Optional[float] = None
    trade_id: Optional[str] = None              # the id the position will be written under
    store: str = desk.TRADES
    cost_model: Optional[Dict[str, Any]] = None  # the server's own snapshot (desk COST_MODEL), set by the route
    add_plan: Optional[Dict[str, Any]] = None    # an add (journal fill): the plan it must stay within, from the server
    fno_additional: bool = False                 # the fno_risk_gate rollout flag, judged by the route on the session


def inputs_hash(req: EntryRequest) -> str:
    core = req.model_dump(exclude={"correlation_id", "trade_id"})
    return hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def snapshot_hash(snapshot: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _f(x: Any) -> Optional[float]:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        return None
    return float(x)


def _whole(x: Any) -> Optional[int]:
    v = _f(x)
    return int(v) if v is not None and v > 0 and v == int(v) else None


# ── gather: every outside read, into one JSON-safe snapshot ──────────────────
async def gather(db, req: EntryRequest, now: datetime) -> Dict[str, Any]:
    """Each read fails closed: an unreadable value is stored as None (with its reason) and the check that needs it
    blocks."""
    today = fresh.ist_today(now)
    snap: Dict[str, Any] = {"request": req.model_dump(), "now": now.astimezone(timezone.utc).isoformat(),
                            "today": today.isoformat()}
    snap["controls"] = await risk_book.controls(db, req.user_id)
    snap["live_allowed"] = (await modes.is_live_allowed(db, req.user_id)) if req.mode == "live" else None
    try:
        snap["book"] = await risk_book.read(db, req.user_id, now=now, sector_of=inputs.sector_of)
        snap["book_error"] = None
    except Exception as e:  # noqa: BLE001 — fail closed: every limit that needs the book blocks
        logger.error("risk_service: the book of %s could not be read (%s)", req.user_id, type(e).__name__)
        snap["book"], snap["book_error"] = None, f"the account and positions could not be read ({type(e).__name__})"
    sym = (req.symbol or "").strip().upper()
    inst = await inputs.instrument(sym, today) if sym else {"bars": [], "last_close": None, "error": "no symbol"}
    bars = inst.pop("bars", None) or []
    snap["instrument"] = {**inst, "last_close_freshness": fresh.assess(
        inst.get("source") or inputs.BARS_SOURCE, inst.get("last_close_as_of"), budget_sessions=LAST_CLOSE_BUDGET, now=now,
        have_value=inst.get("last_close") is not None)}
    if inst.get("error"):
        snap["instrument"]["last_close_freshness"]["reason"] = inst["error"]
    snap["instrument"]["last_session"] = (
        {"date": bars[-1]["date"].isoformat(), "low": bars[-1]["low"], "high": bars[-1]["high"]} if bars else None)
    snap["sector"] = await inputs.sector_of(sym) if sym else {"sector": None, "error": "no symbol"}
    snap["market"] = await inputs.market_state()
    snap["market"]["freshness"] = fresh.assess(snap["market"].get("source") or inputs.MARKET_SOURCE,
                                               snap["market"].get("as_of"), budget_sessions=MARKET_STATE_BUDGET, now=now,
                                               have_value=snap["market"].get("vix") is not None
                                               and snap["market"].get("regime") is not None)
    if snap["market"].get("error"):
        snap["market"]["freshness"]["reason"] = snap["market"]["error"]
    refs: Dict[str, Any] = {}
    open_structures: Any = "n/a"
    if req.instrument == "structure":
        legs, failures = gate.clean_legs(req.legs)
        if legs and not failures and sym:
            expiries = {leg["expiry"] for leg in legs if leg["kind"] != "cash"}
            try:
                refs = await reference.lookup(sym, expiries, today)
            except Exception as e:  # noqa: BLE001 — fail closed: unverifiable
                logger.error("risk_service: contract reference failed for %s (%s)", sym, type(e).__name__)
                refs = {}
        if req.fno_additional and req.action == "open":
            open_structures = await gate._count_open(db, gate_req(req))
    snap["references"] = refs
    snap["open_structures"] = open_structures
    return gate.bson_safe(snap)


def gate_req(req: EntryRequest):
    """The gate's own request shape, for the gate checks reused here."""
    from .contract import RiskRequest
    return RiskRequest(correlation_id=req.correlation_id, user_id=req.user_id, actor_id=req.actor_id, mode=req.mode,
                       path=req.path, action=req.action, instrument=req.instrument, symbol=req.symbol,
                       legs=[dict(leg) for leg in req.legs], quantity=req.quantity if req.instrument == "cash" else None,
                       capital_at_risk_rs=None)


# ── decide: the checks, pure ─────────────────────────────────────────────────
class _Run:
    def __init__(self) -> None:
        self.checks: List[Dict[str, Any]] = []
        self.reasons: List[Dict[str, Any]] = []

    def reason(self, check: str, code: str, message: str, *, severity: str = "block", value: Any = None,
               limit: Any = None) -> None:
        self.reasons.append({"code": code, "check": check, "severity": severity, "value": value, "limit": limit,
                             "message": message})

    def done(self, check: str, detail: Optional[str] = None, *, status: Optional[str] = None) -> None:
        failed = any(r["check"] == check and r["severity"] in BLOCKING for r in self.reasons)
        self.checks.append({"check": check, "status": status or ("fail" if failed else "pass"), "detail": detail})

    def skip(self, check: str, why: str) -> None:
        self.checks.append({"check": check, "status": "skipped", "detail": why})

    def blocked(self) -> bool:
        return any(r["severity"] in BLOCKING for r in self.reasons)


def _pct(part: Optional[float], whole: Optional[float]) -> Optional[float]:
    return None if part is None or not whole else round(part / whole * 100.0, 4)


def _scaled_legs(legs: List[Dict[str, Any]], lots: Optional[int]) -> List[Dict[str, Any]]:
    """Every derivative leg at `lots` lots; None = the legs as requested (legs with different lot counts cannot be
    scaled together, so such a structure is judged only at its requested size)."""
    if lots is None:
        return [dict(leg) for leg in legs]
    return [{**leg, "lots": lots} if leg.get("kind") != "cash" else dict(leg) for leg in legs]


def _structure_doc(req: EntryRequest, legs: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"kind": strat.KIND, "legs": legs, "underlying": req.symbol, "direction": req.direction,
            "stop_underlying": req.stop_underlying, "cost_model": req.cost_model or desk.COST_MODEL}


def decide(req: EntryRequest, snap: Dict[str, Any]) -> Dict[str, Any]:
    """The checks in CHECK_ORDER on the request and its snapshot. No I/O. Returns the decision body (no ids)."""
    run = _Run()
    profile = (snap.get("book") or {}).get("profile")
    limits = (profile or {}).get("limits") or {}
    book = snap.get("book")
    model = req.cost_model or desk.COST_MODEL
    sym = (req.symbol or "").strip().upper()
    cash = req.instrument == "cash"

    # controls
    ctl = snap.get("controls")
    if ctl is None:
        run.reason("controls", "controls_unreadable", "The kill switch and halt could not be read, so new risk is "
                                                     "refused.", severity="halt")
    else:
        if ctl.get("kill_switch"):
            run.reason("controls", "kill_switch_on", f"The kill switch is on ({ctl.get('reason') or 'no reason given'}).",
                       severity="halt")
        if ctl.get("halted"):
            run.reason("controls", "trading_halted", f"Trading is halted ({ctl.get('reason') or 'no reason given'}).",
                       severity="halt")
    run.done("controls")

    # mode
    if req.mode not in modes.MODES:
        run.reason("mode", "mode_unknown", f"Unknown mode {req.mode!r}.")
    elif req.mode == "live" and not snap.get("live_allowed"):
        run.reason("mode", "live_execution_unavailable" if not modes.LIVE_EXECUTION_AVAILABLE else "live_not_authorized",
                   "Live execution does not exist in this release." if not modes.LIVE_EXECUTION_AVAILABLE
                   else "This account holds no live authorization.")
    elif req.mode not in policy.LIMITS.allowed_modes:
        run.reason("mode", "mode_not_allowed", f"The {req.mode} mode is not allowed.")
    run.done("mode")

    # structure
    if req.path not in PATHS:
        run.reason("structure", "path_unknown", f"Unknown path {req.path!r}.")
    if req.action not in ACTIONS:
        run.reason("structure", "action_unknown", f"Unknown action {req.action!r}.")
    if req.instrument not in INSTRUMENTS:
        run.reason("structure", "instrument_unknown", f"Unknown instrument {req.instrument!r}.")
    if not req.user_id.strip():
        run.reason("structure", "user_unknown", "No user to check the position against.")
    if not sym:
        run.reason("structure", "symbol_missing", "No symbol or underlying.")
    legs: List[Dict[str, Any]] = []
    requested_lots: Optional[int] = None
    if cash:
        if req.quantity is None and req.notional_rs is None:
            run.reason("structure", "quantity_missing", "No quantity.")
        if req.quantity is not None and _whole(req.quantity) is None:
            run.reason("structure", "quantity_invalid", "The quantity must be a positive whole number of shares.")
        if req.notional_rs is not None and (_f(req.notional_rs) or 0) <= 0:
            run.reason("structure", "notional_invalid", "The capital planned must be positive.")
        if req.quantity is not None and (_f(req.entry_price) or 0) <= 0:
            run.reason("structure", "entry_invalid", "The entry price must be positive.")
    elif req.instrument == "structure":
        clean, failures = gate.clean_legs(req.legs)
        for code, message in failures:
            run.reason("structure", code, message)
        if not req.legs:
            run.reason("structure", "no_legs", "A structure needs at least one leg.")
        elif clean and not failures and all(leg["kind"] == "cash" for leg in clean):
            run.reason("structure", "no_derivative_leg", "A structure needs a futures or options leg.")
        legs = [dict(leg) for leg in req.legs] if not failures else []
        requested_lots = est.common_lots(legs) if legs else None
    run.done("structure")
    malformed = run.blocked() and any(r["check"] == "structure" for r in run.reasons)

    # planned quantity and entry
    inst = snap.get("instrument") or {}
    last_close = _f(inst.get("last_close"))
    entry = _f(req.entry_price)
    requested_qty = _whole(req.quantity) if cash else None
    if cash and req.quantity is None and req.notional_rs is not None:
        # A journal plan: capital only. Its quantity and entry are the last close's (server-resolved).
        entry = last_close
        requested_qty = int(math.floor(float(req.notional_rs) / last_close)) if last_close else None
    stop, target = _f(req.stop_price), _f(req.target_price)

    # levels
    if cash and not malformed:
        if stop is None or stop <= 0:
            run.reason("levels", "stop_required", "Every entry needs a stop (stop price above 0).")
        elif entry is not None and stop >= entry:
            run.reason("levels", "stop_not_below_entry", "The stop must be below the entry for a long.", value=stop,
                       limit=entry)
        if req.action == "open":
            if target is None or target <= 0:
                run.reason("levels", "target_required", "A target is needed to check reward against risk.")
            elif entry is not None and target <= entry:
                run.reason("levels", "target_not_above_entry", "The target must be above the entry.", value=target,
                           limit=entry)
    has_future = any(leg.get("kind") == "future" for leg in legs)
    if not cash and not malformed and has_future:
        if req.stop_underlying is None:
            run.reason("levels", "futures_stop_required", "A structure with a futures leg needs a stop on the "
                                                          "underlying.")
        if req.target_underlying is None:
            run.reason("levels", "target_required", "A structure with a futures leg needs a target on the underlying "
                                                    "to check reward against risk.")
    run.done("levels")

    # inputs: present and fresh
    fresh_rec = {"last_close": inst.get("last_close_freshness"), "sector": None, "market": None, "equity": None}
    lc = inst.get("last_close_freshness") or {}
    if not lc.get("ok"):
        code = "last_close_stale" if lc.get("age_sessions") is not None else "last_close_unknown"
        run.reason("inputs", code, f"The last close of {sym or 'the instrument'} is not usable: "
                                   f"{lc.get('reason') or 'unknown'}.", value=lc.get("as_of"), limit=lc.get("budget"))
    ref_px = entry if cash else _f(req.reference_price)
    if lc.get("ok") and last_close and ref_px:
        dist = abs(ref_px - last_close) / last_close * 100.0
        if dist > MAX_ENTRY_DISTANCE_PCT:
            run.reason("inputs", "entry_far_from_market", f"The {'entry' if cash else 'reference price'} is "
                                                          f"{dist:.1f}% from the last close ({last_close:g}).",
                       value=round(dist, 2), limit=MAX_ENTRY_DISTANCE_PCT)
    sec = snap.get("sector") or {}
    sector = sec.get("sector")
    fresh_rec["sector"] = fresh.known(sec.get("source") or inputs.SECTOR_SOURCE, sector, as_of=sec.get("as_of"),
                                      reason_missing=sec.get("error") or "no sector")
    if not sector:
        run.reason("inputs", "sector_unknown", f"The sector of {sym or 'the instrument'} is unknown "
                                               f"({sec.get('error') or 'no classification'}), so the sector limit "
                                               f"cannot be checked.")
    mk = snap.get("market") or {}
    fresh_rec["market"] = mk.get("freshness")
    mf = mk.get("freshness") or {}
    if not mf.get("ok"):
        code = "market_state_stale" if mf.get("age_sessions") is not None and mk.get("vix") is not None else "market_state_unknown"
        run.reason("inputs", code, f"The market state (India VIX and regime) is not usable: {mf.get('reason') or 'unknown'}.",
                   value=mk.get("as_of"), limit=mf.get("budget"))
    if cash and inst.get("adv_rs") is None and not malformed:
        run.reason("inputs", "liquidity_unknown", f"The average traded value of {sym or 'the instrument'} is unknown, "
                                                  f"so the liquidity limit cannot be checked.")
    if profile is None:
        run.reason("inputs", "account_unreadable", snap.get("book_error") or "The account could not be read.")
    eq = (book or {}).get("equity") or {}
    equity = _f(eq.get("equity_rs"))
    fresh_rec["equity"] = {"source": "paper account + end-of-day marks (services/risk_book.py)",
                           "as_of": eq.get("marks_as_of"), "fno_marks_as_of": eq.get("fno_marks_as_of"),
                           "ok": equity is not None, "reason": "; ".join(eq.get("unknown_reasons") or []) or None}
    if book is not None and equity is None:
        run.reason("inputs", "equity_unknown", "Paper equity is unknown, so no limit can be measured: "
                                               + ("; ".join(eq.get("unknown_reasons") or []) or "unknown") + ".")
    if book is not None and book["open"]["legacy_risk_unknown"]:
        run.reason("inputs", "open_risk_unknown", "The risk of open position(s) "
                                                  f"{', '.join(book['open']['legacy_risk_unknown'])} cannot be worked "
                                                  f"out, so total open risk is unknown.")
    run.done("inputs", f"last close {inst.get('last_close')} ({inst.get('last_close_as_of')}); sector {sector}; "
                       f"VIX {mk.get('vix')} regime {mk.get('regime')} ({mk.get('as_of')}); equity {equity}")

    # defined risk, lot size, expiry (structures)
    if not cash and legs and not malformed:
        try:
            typed_legs, _ = gate.clean_legs(legs)
            strat.check_defined_risk(typed_legs)            # the desk's rule, on the gate's typed legs
        except desk.DeskInputError as e:
            run.reason("defined_risk", e.code, e.message or f"The structure is not defined risk ({e.code}).")
        except Exception as e:  # noqa: BLE001 — a leg the desk validator refuses
            run.reason("defined_risk", "structure_invalid", f"The structure could not be checked ({type(e).__name__}).")
        run.done("defined_risk")
        g = gate._Run()
        typed, _ = gate.clean_legs(legs)
        gr = gate_req(req)
        gate._lot_size(gr, typed, snap.get("references") or {}, g)
        gate._expiry(gr, typed, snap.get("references") or {}, date.fromisoformat(snap["today"]), g)
        for r in g.reasons:
            run.reason(r.check, r.code, r.message)
        run.done("lot_size")
        run.done("expiry")
    else:
        for c in ("defined_risk", "lot_size", "expiry"):
            run.skip(c, "a share position" if cash else "the structure is not valid")

    # sizing: per-trade risk
    budget: Dict[str, Any] = {"capital_basis": risk_profile.CAPITAL_BASIS, "equity_rs": equity,
                              "starting_capital_rs": (profile or {}).get("starting_capital_rs"),
                              "starting_capital_label": risk_profile.STARTING_CAPITAL_LABEL}
    approved_qty = requested_qty
    approved_lots = requested_lots
    estimate: Optional[Dict[str, Any]] = None

    def cash_est(q: int) -> Dict[str, Any]:
        return est.cash_risk(q, entry, stop, model)

    def struct_est(lots: Optional[int]) -> Optional[Dict[str, Any]]:
        e, _ = est.structure_risk(_scaled_legs(legs, lots), direction=req.direction, stop_underlying=req.stop_underlying,
                                  model=model)
        return e

    sizable = (not malformed and equity is not None and profile is not None
               and ((cash and approved_qty and entry and stop and stop < entry) or (not cash and legs)))
    if sizable:
        per_budget = equity * limits["per_trade_risk_pct"] / 100.0
        budget.update(per_trade_pct=limits["per_trade_risk_pct"], per_trade_budget_rs=round(per_budget, 2))
        if req.action == "add" and req.add_plan:
            plan = req.add_plan
            cum_risk = est.cash_risk(int(plan["cumulative_qty"]), float(plan["cumulative_avg"]), stop, model)["total"] \
                if cash and plan.get("cumulative_qty") and stop and stop < float(plan["cumulative_avg"]) else None
            budget.update(add_plan_risk_rs=plan.get("reserved_risk_rs"), add_cumulative_risk_rs=cum_risk,
                          add_plan_notional_rs=plan.get("plan_notional_rs"),
                          add_cumulative_notional_rs=plan.get("cumulative_notional_rs"))
            if cum_risk is None:
                run.reason("per_trade_risk", "add_risk_unknown", "The position's risk after this fill cannot be worked "
                                                                 "out (no stop below the average price).")
            elif plan.get("reserved_risk_rs") is not None and cum_risk > float(plan["reserved_risk_rs"]) + 1e-6:
                run.reason("per_trade_risk", "add_exceeds_original_budget",
                           "This fill takes the position's estimated risk above the budget reserved for the plan.",
                           value=cum_risk, limit=plan["reserved_risk_rs"])
            if plan.get("plan_notional_rs") is not None and float(plan.get("cumulative_notional_rs") or 0) \
                    > float(plan["plan_notional_rs"]) + 1e-6:
                run.reason("per_trade_risk", "add_exceeds_original_budget",
                           "This fill takes the capital deployed above the plan's capital.",
                           value=plan.get("cumulative_notional_rs"), limit=plan["plan_notional_rs"])
            estimate = cash_est(approved_qty)
        elif cash:
            estimate = cash_est(approved_qty)
            if estimate["total"] > per_budget + 1e-9:
                fit = est.max_cash_qty(per_budget, entry, stop, approved_qty, model)
                if fit < 1:
                    run.reason("per_trade_risk", "min_qty_exceeds_budget",
                               "Even one share's estimated risk exceeds the per-trade budget.",
                               value=cash_est(1)["total"], limit=round(per_budget, 2))
                else:
                    run.reason("per_trade_risk", "per_trade_risk_exceeded",
                               f"Estimated risk Rs {estimate['total']:,.2f} exceeds the per-trade budget "
                               f"Rs {per_budget:,.2f}; at most {fit} shares fit.", severity="reduce",
                               value=estimate["total"], limit=round(per_budget, 2))
                    approved_qty = fit
        else:
            estimate, why = est.structure_risk(_scaled_legs(legs, requested_lots), direction=req.direction,
                                               stop_underlying=req.stop_underlying, model=model)
            if estimate is None:
                run.reason("per_trade_risk", "risk_unknown", f"The structure's risk cannot be estimated: {why}.")
            if estimate is not None and estimate["total"] > per_budget + 1e-9:
                fit = est.max_structure_multiple(legs, per_budget, direction=req.direction,
                                                 stop_underlying=req.stop_underlying, model=model) if requested_lots else 0
                if fit < 1:
                    one = struct_est(1) if requested_lots else estimate
                    run.reason("per_trade_risk", "min_lot_exceeds_budget",
                               "The smallest valid size (one lot per leg) exceeds the per-trade budget.",
                               value=(one or estimate)["total"], limit=round(per_budget, 2))
                else:
                    run.reason("per_trade_risk", "per_trade_risk_exceeded",
                               f"Estimated risk Rs {estimate['total']:,.2f} exceeds the per-trade budget "
                               f"Rs {per_budget:,.2f}; at most {fit} lot(s) per leg fit.", severity="reduce",
                               value=estimate["total"], limit=round(per_budget, 2))
                    approved_lots = fit
        run.done("per_trade_risk")
    else:
        run.skip("per_trade_risk", "not sized: the request or a required input is not usable (reasons above)")

    def cur_est() -> Optional[Dict[str, Any]]:
        if not sizable:
            return None
        if cash:
            return cash_est(approved_qty) if approved_qty else None
        return struct_est(approved_lots) if (approved_lots or requested_lots is None) else estimate

    # reward : risk after costs
    if sizable and not run.blocked() and req.action == "open":
        e1 = cur_est()
        if cash and target and e1:
            reward = est.cash_reward(approved_qty, entry, target, model)
            rr = reward / e1["stop_based"] if e1["stop_based"] > 0 else None
        elif not cash and e1:
            reward, why = est.structure_reward(_scaled_legs(legs, approved_lots) if approved_lots else legs,
                                               direction=req.direction, target_underlying=req.target_underlying, model=model)
            rr = None if reward is None else (reward / e1["stop_based"] if e1["stop_based"] > 0 else None)
            if reward is None and why.startswith("unbounded"):
                rr = float("inf")
        else:
            rr = None
        budget.update(reward_risk=None if rr is None or rr == float("inf") else round(rr, 4),
                      min_reward_risk=limits["min_reward_risk"])
        if rr is None:
            run.reason("reward_risk", "reward_risk_unknown", "Reward against risk could not be worked out.")
        elif rr < limits["min_reward_risk"] - 1e-9:
            run.reason("reward_risk", "reward_risk_too_low",
                       f"Reward:risk after costs is {rr:.2f}; the minimum is {limits['min_reward_risk']:g}.",
                       value=round(rr, 4), limit=limits["min_reward_risk"])
        run.done("reward_risk", None if rr is None else ("unbounded gain" if rr == float("inf") else f"{rr:.2f}"))
    else:
        run.skip("reward_risk", "an add to a planned position" if req.action == "add" else "not sized")

    # the governor (shares)
    mkt = snap.get("market") or {}
    dd = (book or {}).get("drawdown_pct")
    if cash and sizable and not malformed:
        g_limits = gov.Limits(max_risk_per_trade_pct=limits["per_trade_risk_pct"], max_position_pct=limits["max_position_pct"],
                              max_sector_pct=limits["max_sector_pct"], max_drawdown_pct=limits["max_drawdown_pct"],
                              min_reward_risk=limits["min_reward_risk"], max_daily_loss_pct=limits["daily_loss_pct"])
        intent = gov.Intent(symbol=sym, quantity=int(approved_qty), entry_price=float(entry), stop_price=stop,
                            target_price=target if req.action == "open" else entry * 10, sector=sector,
                            avg_daily_value=_f(inst.get("adv_rs")))
        positions = risk_book.governor_positions(book)
        if req.action == "add":
            positions = [p for p in positions if p.symbol != sym]        # an add judges the plan, not "already held"
        portfolio = gov.Portfolio(capital=equity, positions=positions, realized_pnl_today=0.0, drawdown_pct=dd,
                                  kill_switch=bool((ctl or {}).get("kill_switch")), halted=bool((ctl or {}).get("halted")))
        verdict = gov.evaluate(intent, portfolio, gov.Market(vix=_f(mkt.get("vix")), regime=mkt.get("regime")), g_limits)
        for r in verdict.reasons:
            if r.code in ("KILL_SWITCH", "HALTED", "DRAWDOWN_UNKNOWN"):
                continue                                  # judged by the controls and drawdown checks
            sev = r.severity if r.severity in ("halt", "reject", "defer", "reduce") else "info"
            run.reason("governor", r.code, r.text, severity=sev, value=r.value, limit=r.limit)
        if verdict.action in ("approve", "reduce", "hedge") and verdict.approved_qty < approved_qty:
            approved_qty = verdict.approved_qty
        run.done("governor", f"{verdict.action} {verdict.approved_qty} of {verdict.requested_qty} ({gov.LIMITS_VERSION}, "
                             f"daily loss judged by check daily_loss)")
    else:
        run.skip("governor", "share entries only" if not cash else "not sized")

    # portfolio budgets
    if sizable and book is not None and not malformed:
        open_ = book["open"]
        open_risk_cap = equity * limits["max_open_risk_pct"] / 100.0
        exposure_cap = equity * gov.DEFAULT_LIMITS.max_net_exposure_pct / 100.0
        sector_cap = equity * limits["max_sector_pct"] / 100.0
        position_cap = equity * limits["max_position_pct"] / 100.0

        def exposure_of(q_or_lots: Optional[int]) -> float:
            if cash:
                return round(q_or_lots * entry, 2)
            return float(strat.exposure_rs(_structure_doc(req, _scaled_legs(legs, q_or_lots))) or 0.0)

        sector_before = float(open_["sector_rs"].get(sector, 0.0)) + float(open_["unclassified_exposure_rs"]) if sector else None
        budget.update(open_risk_before_rs=open_["risk_rs"], open_risk_cap_rs=round(open_risk_cap, 2),
                      open_risk_pct_limit=limits["max_open_risk_pct"], exposure_before_rs=open_["exposure_rs"],
                      exposure_cap_rs=round(exposure_cap, 2), position_cap_rs=round(position_cap, 2),
                      position_pct_limit=limits["max_position_pct"], sector=sector, sector_before_rs=sector_before,
                      sector_cap_rs=round(sector_cap, 2), sector_pct_limit=limits["max_sector_pct"],
                      open_positions_before=open_["positions"], max_open_positions=gov.DEFAULT_LIMITS.max_open_positions)

        def shrink(check: str, code: str, room: float, measure, unit_text: str) -> None:
            """Reduce the size until `measure(size) <= room`; block when even the smallest size does not fit."""
            nonlocal approved_qty, approved_lots
            cur = approved_qty if cash else approved_lots
            if cash and not cur:
                return
            if measure(cur) <= room + 1e-9:
                return
            if cur is None:                    # legs with different lot counts: judged at the requested size only
                run.reason(check, code, f"The structure does not fit the {unit_text} left (Rs {max(room, 0):,.2f}) "
                                        f"and its legs cannot be scaled together.", value=round(measure(None), 2),
                           limit=round(max(room, 0), 2))
                return
            fit = est._largest(int(cur), lambda n: measure(n) <= room + 1e-9)
            if fit < 1:
                run.reason(check, code, f"Even the smallest valid size does not fit the {unit_text} left "
                                        f"(Rs {max(room, 0):,.2f}).", value=round(measure(1), 2), limit=round(max(room, 0), 2))
                return
            run.reason(check, code, f"Size reduced to {fit} to fit the {unit_text} left (Rs {room:,.2f}).",
                       severity="reduce", value=round(measure(cur), 2), limit=round(room, 2))
            if cash:
                approved_qty = fit
            else:
                approved_lots = fit

        def risk_of(n: Optional[int]) -> float:
            e = cash_est(n) if cash else struct_est(n)
            return float(e["total"]) if e else float("inf")

        if not cash and req.action == "open":
            shrink("position", "position_exceeded", position_cap, exposure_of, "position exposure limit")
            run.done("position")
        else:
            run.skip("position", "shares: the governor's POSITION_SIZE limit")
        if req.action == "open" or not (req.add_plan and req.add_plan.get("reserved_risk_rs") is not None):
            shrink("open_risk", "open_risk_exceeded", open_risk_cap - float(open_["risk_rs"]), risk_of, "open-risk budget")
        run.done("open_risk")
        if not cash:
            shrink("exposure", "exposure_exceeded", exposure_cap - float(open_["exposure_rs"]), exposure_of,
                   "market-exposure budget")
            run.done("exposure")
        else:
            run.skip("exposure", "shares: the governor's NET_EXPOSURE limit")
        if sector and req.action == "open":
            shrink("sector", "sector_exceeded", sector_cap - float(sector_before or 0.0), exposure_of,
                   f"{sector} sector budget")
        run.done("sector", f"{sector}: Rs {sector_before} before")
        if req.action == "open" and int(open_["positions"]) >= gov.DEFAULT_LIMITS.max_open_positions and not cash:
            run.reason("position", "max_positions", "Open positions are at the limit.", value=open_["positions"],
                       limit=gov.DEFAULT_LIMITS.max_open_positions)
        size = approved_qty if cash else approved_lots
        new_exposure = exposure_of(size) if (size or not cash) else 0.0
        if req.action == "add" and req.add_plan and req.add_plan.get("reserved_risk_rs") is not None:
            new_exposure = 0.0
        budget.update(new_exposure_rs=round(new_exposure, 2))
    else:
        for c in ("position", "open_risk", "exposure", "sector"):
            run.skip(c, "not sized")
    run.skip("correlation", CORRELATION_TEXT)

    # period losses and drawdown
    if book is not None and profile is not None:
        for check, key, pct_key, code in (("daily_loss", "day", "daily_loss_pct", "daily_loss"),
                                          ("weekly_loss", "week", "weekly_loss_pct", "weekly_loss")):
            p = book[key]
            pnl, start_eq = _f(p.get("pnl_rs")), _f(p.get("start_equity_rs"))
            budget.update({f"{key}_pnl_rs": pnl, f"{key}_start_equity_rs": start_eq, f"{key}_start": p.get("start"),
                           f"{key}_loss_pct_limit": limits[pct_key]})
            if pnl is None or not start_eq:
                run.reason(check, f"{code}_unknown", f"The {key}'s P&L is unknown, so the {key} loss halt cannot be "
                                                    f"checked: " + ("; ".join(p.get("unknown_reasons") or []) or "unknown") + ".")
            else:
                loss_pct = max(0.0, -pnl) / start_eq * 100.0
                budget[f"{key}_loss_pct"] = round(loss_pct, 4)
                if loss_pct >= limits[pct_key] - 1e-9:
                    run.reason(check, f"{code}_halt", f"The {key}'s loss is {loss_pct:.2f}% of start-of-{key} equity; "
                                                      f"new entries are halted at {limits[pct_key]:g}%.",
                               value=round(loss_pct, 4), limit=limits[pct_key])
            run.done(check)
        budget.update(drawdown_pct=dd, drawdown_pct_limit=limits["max_drawdown_pct"], peak_rs=book["peak"]["peak_rs"])
        if dd is None:
            run.reason("drawdown", "drawdown_unknown", "Drawdown is unknown (" + ("; ".join(eq.get("unknown_reasons") or [])
                                                                                  or "equity unknown") + "), so the "
                                                       "drawdown halt cannot be checked.")
        elif dd >= limits["max_drawdown_pct"] - 1e-9:
            run.reason("drawdown", "drawdown_halt", f"Drawdown is {dd:.2f}% from the equity peak; new entries are halted "
                                                    f"at {limits['max_drawdown_pct']:g}%. Open positions are not closed.",
                       value=dd, limit=limits["max_drawdown_pct"])
        run.done("drawdown")
    else:
        for c, code in (("daily_loss", "daily_loss_unknown"), ("weekly_loss", "weekly_loss_unknown"),
                        ("drawdown", "drawdown_unknown")):
            run.reason(c, code, "The account could not be read, so this limit cannot be checked.")
            run.done(c)

    # funding
    funding = 0.0
    if not malformed and book is not None:
        size = approved_qty if cash else approved_lots
        if req.action == "add" and req.add_plan and req.add_plan.get("reserved_risk_rs") is not None:
            funding = 0.0
        elif req.path == "journal_create":
            funding = float(approved_qty or 0) * float(entry or 0)
        elif cash:
            funding = float(size or 0) * float(entry or 0)
        elif legs:
            funding = float(strat.exposure_rs(_structure_doc(req, _scaled_legs(legs, size))) or 0.0)
        available = float(book["account"]["available_rs"])
        budget.update(funding_rs=round(funding, 2), available_rs=round(available, 2))
        if funding > available + 1e-9:
            run.reason("funding", "insufficient_paper_funds", f"The position needs Rs {funding:,.2f}; the paper account "
                                                              f"has Rs {available:,.2f} available.",
                       value=round(funding, 2), limit=round(available, 2))
        run.done("funding")
    else:
        run.skip("funding", "not sized")

    # additional F&O structure checks (rollout flag)
    if not cash and req.fno_additional and legs and not malformed:
        typed, _ = gate.clean_legs(_scaled_legs(legs, approved_lots or requested_lots))
        for code, message in gate.defined_risk_failures(typed):
            run.reason("fno_additional", code, message)
        g = gate._Run()
        gr = gate_req(req).model_copy(update={"legs": _scaled_legs(legs, approved_lots or requested_lots)})
        gate._caps(gr, typed, g)
        count = snap.get("open_structures")
        gate._open_structures(gr, count if isinstance(count, int) else None, g)
        for r in g.reasons:
            run.reason("fno_additional", r.code, r.message)
        run.done("fno_additional", f"{policy.POLICY_VERSION} caps and open-structure limit")
    else:
        run.skip("fno_additional", "the fno_risk_gate rollout flag is off for this user (core checks ran)"
                 if not cash else "share entries")

    # outcome
    blocked = run.blocked()
    final_est = cur_est()
    if blocked:
        outcome = "block"
        a_qty, a_lots = 0 if cash else None, 0 if not cash else None
    else:
        a_qty = approved_qty if cash else None
        a_lots = approved_lots if not cash else None
        reduced = (cash and requested_qty is not None and (approved_qty or 0) < requested_qty) or \
                  (not cash and requested_lots is not None and (approved_lots or 0) < requested_lots)
        outcome = "reduce" if reduced else "allow"
    open_risk_after = None
    if book is not None and final_est is not None and outcome != "block":
        add_free = req.action == "add" and req.add_plan and req.add_plan.get("reserved_risk_rs") is not None
        open_risk_after = round(float(book["open"]["risk_rs"]) + (0.0 if add_free else float(final_est["total"])), 2)
    budget["open_risk_after_rs"] = open_risk_after
    planned_entry = entry if cash else None
    return {
        "outcome": outcome,
        "requested_qty": requested_qty, "approved_qty": a_qty,
        "requested_lots": requested_lots, "approved_lots": a_lots,
        "planned_entry_price": planned_entry,
        "approved_notional_rs": round(a_qty * planned_entry, 2) if a_qty and planned_entry else None,
        "reasons": run.reasons, "checks": run.checks,
        "estimated_risk_rs": final_est or estimate,
        "budget": budget,
        "freshness": fresh_rec,
        "sector": sector,
        "limits_version": (profile or {}).get("limits_version"),
        "profile": (profile or {}).get("profile"),
    }


# ── record and reserve ───────────────────────────────────────────────────────
async def _persist(db, req: EntryRequest, body: Dict[str, Any], *, decision_id: str, at: str,
                   snapshot: Optional[Dict[str, Any]], supersedes: Optional[str] = None,
                   reservation_id: Optional[str] = None) -> None:
    row = {
        "_id": decision_id, "user_id": req.user_id, "at": at, "action": req.path, "path": req.path,
        "outcome": {"allow": "allowed", "reduce": "reduced", "block": "blocked"}[body["outcome"]],
        "symbol": (req.symbol or "").strip().upper() or None,
        "requested_qty": body.get("requested_qty"), "approved_qty": body.get("approved_qty"),
        "requested_lots": body.get("requested_lots"), "approved_lots": body.get("approved_lots"),
        "reasons": body["reasons"], "checks": body["checks"],
        "estimated_risk_rs": body.get("estimated_risk_rs"), "budget": body.get("budget"),
        "freshness": body.get("freshness"),
        "policy_version": POLICY_VERSION, "limits_version": body.get("limits_version"),
        "estimate_version": est.ESTIMATE_VERSION, "correlation_id": req.correlation_id,
        "inputs_hash": inputs_hash(req), "mode": req.mode, "actor_id": req.actor_id, "source": SOURCE,
        "trade_id": req.trade_id, "store": req.store, "reservation_id": reservation_id,
        "detail": {"instrument": req.instrument, "action": req.action, "legs": len(req.legs),
                   "sector": body.get("sector"), "fno_additional": req.fno_additional},
    }
    if supersedes:
        row["supersedes"] = supersedes
    if snapshot is not None:
        row.update(snapshot=snapshot, snapshot_version=SNAPSHOT_VERSION, snapshot_hash=snapshot_hash(snapshot))
    try:
        await db[rc.DECISIONS].insert_one(row)
    except Exception as e:  # noqa: BLE001 — re-raised: nothing may be written on an unrecorded decision
        logger.error("risk_service: decision NOT recorded for %s (%s): path=%s outcome=%s", req.user_id,
                     type(e).__name__, req.path, body["outcome"])
        raise DecisionUnrecorded("the risk decision could not be recorded") from e
    if body["outcome"] != "allow":
        logger.warning("risk_service: %s %s for %s (%s): %s", req.path, body["outcome"], req.user_id, row["symbol"] or "-",
                       ",".join(r["code"] for r in body["reasons"] if r["severity"] != "info"))


def _caps(body: Dict[str, Any], book: Dict[str, Any]) -> Dict[str, Any]:
    """The reservation's caps: the decision's rupee caps, net of the legacy positions the account counters do not hold."""
    b, o = body["budget"], book["open"]
    sector = body.get("sector")
    legacy_sector = sum(float(p.get("exposure_rs") or 0.0) for p in book["positions"]
                        if not p["reserved"] and (p.get("sector") == sector or not p.get("sector")))
    return {"open_risk_cap_rs": round(float(b["open_risk_cap_rs"]) - float(o["legacy_risk_rs"]), 2),
            "exposure_cap_rs": round(float(b["exposure_cap_rs"]) - float(o["legacy_exposure_rs"]), 2),
            "sector_cap_rs": round(float(b["sector_cap_rs"]) - legacy_sector, 2),
            "max_positions": int(b["max_open_positions"]) - int(o["legacy_positions"])}


async def _exists(db, entry: Dict[str, Any]) -> bool:
    store = entry.get("store") or desk.TRADES
    return await db[store].find_one({"_id": entry.get("trade_id")}) is not None


async def enter(db, req: EntryRequest, *, reserve: bool = True, accept_reduce: bool = False,
                now: Optional[datetime] = None) -> Dict[str, Any]:
    """Decide, record, and (when the decision allows, or reduces and `accept_reduce`) reserve. Returns the decision;
    raises DecisionUnrecorded. Never raises for a bad input: that is a block with a reason."""
    moment = now or desk.utcnow()
    await rc.ensure_indexes(db)
    if reserve:
        try:
            # The age of a reservation is judged on the clock that stamped it (the real one, paper_account._iso), never
            # on an injected decision time: a decision clock ahead of it would read an in-flight reservation as old.
            await acct.sweep_orphans(db, req.user_id, exists=lambda e: _exists(db, e))
        except Exception as e:  # noqa: BLE001 — a failed sweep leaves the budget conservative, never looser
            logger.warning("risk_service: orphan sweep failed for %s (%s)", req.user_id, type(e).__name__)
    snapshot = await gather(db, req, moment)
    body = decide(req, snapshot)
    decision_id = str(uuid.uuid4())
    at = moment.astimezone(timezone.utc).isoformat()
    take = reserve and (body["outcome"] == "allow" or (body["outcome"] == "reduce" and accept_reduce))
    await _persist(db, req, body, decision_id=decision_id, at=at, snapshot=snapshot,
                   reservation_id=decision_id if take else None)
    out = {"decision_id": decision_id, "at": at, "correlation_id": req.correlation_id, "policy_version": POLICY_VERSION,
           "inputs_hash": inputs_hash(req), "snapshot_hash": snapshot_hash(snapshot), "reservation_id": None, **body}
    if not take:
        return out
    book = snapshot["book"]
    cash = req.instrument == "cash"
    est_total = float((body.get("estimated_risk_rs") or {}).get("total") or 0.0)
    add_free = req.action == "add" and req.add_plan and req.add_plan.get("reserved_risk_rs") is not None
    if add_free:
        return out                                            # an add within its plan's reservation reserves nothing new
    entry = {"id": decision_id, "trade_id": req.trade_id, "store": req.store, "path": req.path,
             "kind": "cash" if cash else "structure", "symbol": (req.symbol or "").strip().upper(),
             "sector": body.get("sector"), "funding_rs": float(body["budget"].get("funding_rs") or 0.0),
             "risk_rs": est_total, "exposure_rs": float(body["budget"].get("new_exposure_rs") or 0.0),
             "positions": 0 if req.action == "add" else 1, "held": cash and req.action == "open"}
    try:
        await acct.reserve_entry(db, req.user_id, entry, _caps(body, book))
    except acct.ReservationRefused as refused:
        codes = refused.which or ["reservation_refused"]
        lost = {**body, "outcome": "block", "approved_qty": 0 if cash else None, "approved_lots": None if cash else 0,
                "reasons": body["reasons"] + [{"code": c, "check": "reservation", "severity": "block", "value": None,
                                               "limit": None, "message": "Another entry took this budget between the "
                                               "decision and the reservation; nothing was reserved."} for c in codes]}
        second = str(uuid.uuid4())
        await _persist(db, req, lost, decision_id=second, at=desk.utcnow().astimezone(timezone.utc).isoformat(),
                       snapshot=None, supersedes=decision_id)
        return {**out, **lost, "decision_id": second, "supersedes": decision_id, "reservation_id": None}
    out["reservation_id"] = decision_id
    return out


async def release_unused(db, user_id: str, decision: Dict[str, Any], *, reason: str) -> bool:
    """Give back a reservation whose position was never written (insert failed, duplicate, cap, refused by the desk)."""
    rid = decision.get("reservation_id")
    if not rid:
        return False
    return await acct.cancel_reservation(db, user_id, rid, reason=reason)


# ── HTTP ─────────────────────────────────────────────────────────────────────
def public(decision: Dict[str, Any]) -> Dict[str, Any]:
    """What a client is told about a decision (the snapshot stays on the record)."""
    keys = ("decision_id", "outcome", "requested_qty", "approved_qty", "requested_lots", "approved_lots",
            "approved_notional_rs", "planned_entry_price", "reasons", "estimated_risk_rs", "budget", "policy_version",
            "limits_version", "correlation_id", "reservation_id", "freshness", "inputs_hash")
    return {k: decision.get(k) for k in keys}


def refusal(decision: Dict[str, Any]) -> HTTPException:
    """409 risk_blocked (with every reason) or 409 risk_reduce (with the approved size; nothing was written)."""
    body = public(decision)
    if decision["outcome"] == "reduce":
        size = (f"{decision['approved_qty']} shares" if decision.get("approved_qty") is not None
                else f"{decision.get('approved_lots')} lot(s) per leg")
        return HTTPException(status_code=409, detail={
            "code": "risk_reduce", **body,
            "message": f"The risk policy allows at most {size}. Nothing was recorded; submit again at that size."})
    blocking = [r for r in decision["reasons"] if r["severity"] in BLOCKING]
    return HTTPException(status_code=409, detail={
        "code": "risk_blocked", **body,
        "message": "; ".join(r["message"] for r in blocking[:3]) or "Refused by the risk policy."})


def unrecorded(correlation_id: str) -> HTTPException:
    return HTTPException(status_code=503, detail={
        "code": "risk_decision_unrecorded", "correlation_id": correlation_id,
        "message": "The risk decision could not be recorded, so nothing was written. Try again."})


async def enforce(db, req: EntryRequest, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """For a path that writes only at the size asked for (the desk, the journal): the decision when it ALLOWS (with
    its reservation taken); otherwise raises 409 risk_blocked / risk_reduce, or 503 when it could not be recorded."""
    try:
        decision = await enter(db, req, reserve=True, accept_reduce=False, now=now)
    except DecisionUnrecorded:
        raise unrecorded(req.correlation_id)
    if decision["outcome"] != "allow":
        raise refusal(decision)
    return decision


def stamp(doc: Dict[str, Any], decision: Dict[str, Any]) -> Dict[str, Any]:
    """Put the decision's ids on the document about to be written."""
    doc["correlation_id"] = decision["correlation_id"]
    doc["risk_decision_id"] = decision["decision_id"]
    doc["risk_reservation_id"] = decision.get("reservation_id")
    doc["risk_policy_version"] = POLICY_VERSION
    doc["risk_limits_version"] = decision.get("limits_version")
    doc["risk_sector"] = decision.get("sector")
    doc["estimated_risk_rs"] = decision.get("estimated_risk_rs")
    return doc
