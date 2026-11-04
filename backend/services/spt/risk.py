"""The SPT risk decision (PRD §9, §9.9, §18; WF §10, §14, §19.3): SPT's own account checks, then the universal risk
service (services/risk_gate/service.py, path `spt_entry`), mapped to the PRD's decisions and recorded on the proposal.
The risk engine has the final word: no user approval and no AI output can bypass a hard limit (WF §10.4).

EVALUATE (`evaluate`), in order; the first group refuses BEFORE any reservation and without calling the service:
    SPT checks   controls      kill switch / trading halt (services/risk_controls via risk_book.controls) → HALT_ACCOUNT;
                               unreadable → BLOCKED (fail closed)
                 account       the risk book could not be read → BLOCKED
                 ladder        drawdown band (policy.ladder): restricted → BLOCKED drawdown_restricted, halt → HALT_ACCOUNT
                               drawdown_halt_ladder, unknown → BLOCKED drawdown_unknown (the reduce band is applied in sizing)
                 positions     open positions at config max_positions → BLOCKED max_positions
                 min_rr        R:R to T2 at the entry below config min_rr → REJECT rr_below_minimum
                 quantity      nothing allocated → REJECT no_quantity
                 stressed      the entry's stressed risk (sizing: stop loss + costs + stressed_gap_pct % gap) above the
                               open-risk room (profile max_open_risk_pct × equity − open risk) → BLOCKED
                               stressed_risk_exceeds_room
                 price         the live price older than SPT_QUOTE_MAX_AGE_S or missing → BLOCKED price_stale (WF §20)
    the service  EntryRequest(path "spt_entry", store "spt_orders", trade_id = the order id generated now, mode paper,
                 instrument cash, direction long, target = T2, cost_model = desk COST_MODEL), by `how`:
                   reserve  service.enter(reserve=True, accept_reduce=True)   auto mode; an approval (always fresh)
                   record   service.enter(reserve=False, accept_reduce=True)  approval mode's screening decision
                   dry      service.gather + service.decide, nothing written   tracking mode, POST /risk/validate-trade
MAPPING  allow → APPROVE (CONDITIONAL_APPROVAL for a LIMIT entry: the entry condition is not met yet, WF §10.3);
         reduce → APPROVE_REDUCED with the service's quantity; block → HALT_ACCOUNT when a reason is the kill switch, the
         halt or a drawdown halt; BLOCKED when a reason is account- or portfolio-level (controls, inputs/data, open risk,
         exposure, sector, daily / weekly loss, drawdown, funding, the reservation, the governor's MAX_POSITIONS /
         NET_EXPOSURE / SECTOR_LIMIT / DAILY_LOSS_HALT / VIX_DEFER); REJECT otherwise (the trade itself: levels, per-trade
         size, reward:risk, stop too wide, already held).
THE RECORD (WF §10.4) is stored on the proposal: decision_id, the service's decision id, reservation_id, order_id, reason
codes + explanations, requested / approved quantity, planned and stressed risk, open risk and exposure before / after,
policy versions (spt-risk, the service, the profile's limits_version, the SPT config version, sizing, allocation,
estimate), dry_run.

CHECK_MODIFICATION (slice C, DESIGN §4): only risk-increasing changes are judged (a wider stop, more quantity, removing
the stop); a risk-reducing or neutral change is APPROVED even under the kill switch or a halt (PRD §18 rules 12-14).
Recorded in `risk_decisions` (source spt_risk, path spt_modification). An increase whose decision cannot be recorded is
refused (fail closed, like the service's DecisionUnrecorded).

KILL_SWITCH_STATE (WF §19.3), read only. Precedence TRIGGERED > RESTRICTED > ACTIVE > DISABLED:
    TRIGGERED    risk_controls kill_switch or halted is on (a person set it), the controls cannot be read (fail
                 closed), the ladder's halt band, or the profile's drawdown halt (max_drawdown_pct)
    RESTRICTED   the ladder's restricted band, the drawdown unknown, the day's or the week's loss at or past the profile
                 limit, or that P&L unknown — new entries and risk-increasing changes are refused; exits continue
    ACTIVE       none of the above and the SPT mode is tracking / approval / auto (the reduce band is reported)
    DISABLED     none of the above and the SPT mode is off
    RESET_PENDING is NOT produced: risk_controls keeps no reset request (clearing is one admin action), so there is no
                 state that could honestly be called "pending".
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services import desk_trading as desk
from services import risk_controls as rc
from services.risk_gate import estimate as est
from services.risk_gate import service

from . import constants as C
from . import events
from . import policy, proposals

logger = logging.getLogger(__name__)

SOURCE = "spt.risk"
PATH = "spt_entry"
MOD_PATH = "spt_modification"
MOD_SOURCE = "spt_risk"
PIPELINE_ACTOR = "spt_pipeline"
KILL_SWITCH_MAPPING_VERSION = "spt-kill-switch-map-v1"

HALT_CODES = {"kill_switch_on", "trading_halted", "drawdown_halt", "drawdown_halt_ladder", "KILL_SWITCH", "HALTED",
              "DRAWDOWN_HALT"}
ACCOUNT_CHECKS = {"controls", "mode", "inputs", "open_risk", "exposure", "sector", "daily_loss", "weekly_loss",
                  "drawdown", "funding", "reservation"}
ACCOUNT_GOV_CODES = {"MAX_POSITIONS", "NET_EXPOSURE", "SECTOR_LIMIT", "DAILY_LOSS_HALT", "VIX_DEFER", "EVENT_BLACKOUT"}
APPROVED = (C.RISK_APPROVE, C.RISK_APPROVE_REDUCED, C.RISK_CONDITIONAL)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _f(x: Any) -> Optional[float]:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        return None
    return float(x)


def classify_block(reasons: List[Dict[str, Any]]) -> str:
    """HALT_ACCOUNT / BLOCKED / REJECT for a set of blocking reasons (module docstring)."""
    blocking = [r for r in reasons if r.get("severity") in service.BLOCKING] or reasons
    codes = {r.get("code") for r in blocking}
    if codes & HALT_CODES:
        return C.RISK_HALT
    if any(r.get("check") in ACCOUNT_CHECKS or r.get("code") in ACCOUNT_GOV_CODES for r in blocking):
        return C.RISK_BLOCKED
    return C.RISK_REJECT


def entry_request(*, proposal: Dict[str, Any], user_id: str, actor_id: str, quantity: int, order_id: str
                  ) -> service.EntryRequest:
    return service.EntryRequest(
        correlation_id=proposal["_id"], user_id=user_id, actor_id=actor_id, mode="paper", path=PATH, action="open",
        instrument="cash", symbol=proposal["symbol"], quantity=int(quantity), entry_price=float(proposal["entry"]["price"]),
        stop_price=float(proposal["stop_loss"]), target_price=float(proposal["target_2"]), direction="long",
        trade_id=order_id, store=C.ORDERS, cost_model=dict(desk.COST_MODEL))


def spt_checks(*, proposal: Dict[str, Any], state: Dict[str, Any], quantity: int, stressed_risk: Optional[float],
               price: Optional[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """SPT's own checks (module docstring). Pure. {checks[], reasons[], decision|None}."""
    checks: List[Dict[str, Any]] = []
    reasons: List[Dict[str, Any]] = []

    def fail(check: str, code: str, decision: str, message: str, value: Any = None, limit: Any = None) -> None:
        reasons.append({"code": code, "check": check, "severity": "block", "decision": decision, "message": message,
                        "value": value, "limit": limit, "source": "spt"})

    def done(check: str, detail: Optional[str] = None) -> None:
        failed = any(r["check"] == check for r in reasons)
        checks.append({"check": check, "status": "fail" if failed else "pass", "detail": detail, "source": "spt"})

    ctl = state.get("controls")
    if ctl is None:
        fail("controls", "controls_unreadable", C.RISK_BLOCKED, "The kill switch and halt could not be read, so new risk "
                                                                "is refused.")
    else:
        if ctl.get("kill_switch"):
            fail("controls", "kill_switch_on", C.RISK_HALT, f"The kill switch is on ({ctl.get('reason') or 'no reason given'}).")
        if ctl.get("halted"):
            fail("controls", "trading_halted", C.RISK_HALT, f"Trading is halted ({ctl.get('reason') or 'no reason given'}).")
    done("controls")
    if state.get("error"):
        fail("account", "account_unreadable", C.RISK_BLOCKED, state["error"])
    done("account")
    lad = state.get("ladder") or {}
    band = lad.get("band")
    if band == policy.LADDER_HALT:
        fail("ladder", "drawdown_halt_ladder", C.RISK_HALT, lad.get("text") or "Drawdown halt.", lad.get("drawdown_pct"),
             (lad.get("thresholds") or {}).get("halt_at_pct"))
    elif band == policy.LADDER_RESTRICTED:
        fail("ladder", "drawdown_restricted", C.RISK_BLOCKED, lad.get("text") or "Drawdown restricted.",
             lad.get("drawdown_pct"), (lad.get("thresholds") or {}).get("restrict_at_pct"))
    elif band in (policy.LADDER_UNKNOWN, None):
        fail("ladder", "drawdown_unknown", C.RISK_BLOCKED, lad.get("text") or "Drawdown is unknown.")
    done("ladder", f"band {band}")
    if not state.get("error") and state.get("positions_open") is not None \
            and int(state["positions_open"]) >= int(state["max_positions"]):
        fail("positions", "max_positions", C.RISK_BLOCKED, f"Open positions ({state['positions_open']}) are at the limit "
                                                           f"of {state['max_positions']}.", state["positions_open"],
             state["max_positions"])
    done("positions")
    rr = proposal.get("rr") or {}
    if _f(rr.get("t2")) is None or float(rr["t2"]) < float(rr.get("min_rr") or 0) - 1e-9:
        fail("min_rr", "rr_below_minimum", C.RISK_REJECT, f"Reward:risk to target 2 is {rr.get('t2')}; the minimum is "
                                                          f"{rr.get('min_rr')}.", rr.get("t2"), rr.get("min_rr"))
    done("min_rr", f"T2 {rr.get('t2')} vs {rr.get('min_rr')}")
    if int(quantity or 0) < 1:
        fail("quantity", "no_quantity", C.RISK_REJECT, "Sizing and allocation left no whole share.")
    done("quantity", f"{quantity} shares")
    cap, used = _f(state.get("open_risk_cap_rs")), _f(state.get("open_risk_rs"))
    if cap is not None and used is not None and stressed_risk is not None:
        room = cap - used
        if stressed_risk > room + 1e-6:
            fail("stressed", "stressed_risk_exceeds_room", C.RISK_BLOCKED,
                 f"The entry's stressed risk ₹{stressed_risk:,.2f} exceeds the open-risk room ₹{max(room, 0):,.2f}.",
                 round(stressed_risk, 2), round(room, 2))
        done("stressed", f"₹{stressed_risk:,.2f} vs room ₹{room:,.2f}")
    else:
        checks.append({"check": "stressed", "status": "skipped", "source": "spt",
                       "detail": "open-risk room unknown (the account check above blocks)"})
    p = price or {}
    if not p.get("ok"):
        fail("price", p.get("reason") or "price_unavailable", C.RISK_BLOCKED,
             f"No fresh live price ({p.get('reason') or 'price_unavailable'}): the entry cannot be judged on current data.")
    else:
        got = proposals._dt(p.get("received_at"))
        age = (now - got).total_seconds() if got else None
        if age is None or age > float(p.get("max_age_s") or proposals.QUOTE_MAX_AGE_S):
            fail("price", "price_stale", C.RISK_BLOCKED, f"The live price is {age if age is None else round(age)} s old; "
                                                         f"the budget is {p.get('max_age_s') or proposals.QUOTE_MAX_AGE_S:g} s.",
                 age, p.get("max_age_s"))
    done("price", f"age {p.get('age_s')} s")
    decision = None
    if reasons:
        ds = {r["decision"] for r in reasons}
        decision = C.RISK_HALT if C.RISK_HALT in ds else (C.RISK_BLOCKED if C.RISK_BLOCKED in ds else C.RISK_REJECT)
    return {"checks": checks, "reasons": reasons, "decision": decision}


def _planned(q: int, entry: float, stop: float) -> float:
    return round(q * (entry - stop) + (desk.round_trip_cost(q, entry, stop, desk.COST_MODEL) if q > 0 else 0.0), 2)


async def evaluate(db, *, user_id: str, proposal: Dict[str, Any], state: Dict[str, Any], quantity: int,
                   stressed_risk: Optional[float], price: Optional[Dict[str, Any]], actor_id: str, how: str,
                   order_id: Optional[str], now: datetime, emit: bool = True) -> Dict[str, Any]:
    """The decision record (module docstring). `how` is reserve | record | dry. Never raises for a refusal; raises only
    for a programming error (an unknown `how`)."""
    if how not in ("reserve", "record", "dry"):
        raise ValueError(f"unknown how {how!r}")
    config = state.get("config") or {}
    gap_pct = float(((config.get("extras") or {}).get("stressed_gap_pct")) or est.GAP_STRESS_PCT)
    entry, stop = float(proposal["entry"]["price"]), float(proposal["stop_loss"])
    rec: Dict[str, Any] = {
        "decision_id": str(uuid.uuid4()), "at": _iso(now), "decision": None, "account_id": user_id,
        "opportunity_id": proposal.get("opportunity_id"), "proposal_id": proposal["_id"], "symbol": proposal["symbol"],
        "actor_id": actor_id, "how": how, "dry_run": how == "dry", "order_id": order_id if how != "dry" else None,
        "entry_type": (proposal.get("entry") or {}).get("type"), "entry_price": entry, "stop_loss": stop,
        "target": proposal.get("target_2"), "requested_qty": int(quantity or 0), "approved_qty": 0,
        "risk_service_decision_id": None, "risk_service_outcome": None, "reservation_id": None,
        "reason_codes": [], "explanations": [], "reasons": [], "checks": [], "conditional": None,
        "planned_risk_rs": None, "stressed_risk_rs": stressed_risk, "estimated_risk_rs": None,
        "portfolio_risk_before_rs": state.get("open_risk_rs"), "portfolio_risk_after_rs": None,
        "exposure_before_rs": state.get("exposure_rs"), "exposure_after_rs": None,
        "policy_versions": {"spt_risk": C.SPT_RISK_VERSION, "risk_service": service.POLICY_VERSION,
                            "limits_version": (state.get("profile") or {}).get("limits_version"),
                            "config_version": config.get("version"), "config_policy": config.get("policy_version"),
                            "sizing": C.SIZING_VERSION, "allocation": C.ALLOCATION_VERSION,
                            "estimate": est.ESTIMATE_VERSION, "cost_model": desk.COST_MODEL.get("version")},
        "price_age_s": (price or {}).get("age_s"), "ladder": state.get("ladder"),
    }
    pre = spt_checks(proposal=proposal, state=state, quantity=quantity, stressed_risk=stressed_risk, price=price, now=now)
    rec["checks"] = list(pre["checks"])
    if pre["decision"] is not None:
        rec.update(decision=pre["decision"], reasons=pre["reasons"])
        return await _finish(db, rec, proposal, emit=emit)

    req = entry_request(proposal=proposal, user_id=user_id, actor_id=actor_id, quantity=int(quantity),
                        order_id=order_id or f"dry-{rec['decision_id']}")
    try:
        if how == "dry":
            snap = await service.gather(db, req, now)
            out = {"decision_id": None, "reservation_id": None, **service.decide(req, snap)}
        else:
            out = await service.enter(db, req, reserve=(how == "reserve"), accept_reduce=True, now=now)
    except service.DecisionUnrecorded:
        rec.update(decision=C.RISK_BLOCKED, reasons=[{"code": "decision_unrecorded", "check": "service", "severity": "block",
                                                       "message": "The risk decision could not be recorded, so nothing was "
                                                                  "reserved or written.", "source": "risk_service"}])
        return await _finish(db, rec, proposal, emit=emit)
    rec["risk_service_decision_id"] = out.get("decision_id")
    rec["risk_service_outcome"] = out.get("outcome")
    # what slice C keeps on the order (orders.create_entry_order reads budget, estimated_risk_rs, sector, approved_qty)
    rec["risk_service_decision"] = {**service.public(out), "sector": out.get("sector")} if how != "dry" else None
    rec["reservation_id"] = out.get("reservation_id")
    rec["checks"] += [{**c, "source": "risk_service"} for c in out.get("checks") or []]
    rec["reasons"] = [{**r, "source": "risk_service"} for r in out.get("reasons") or []]
    rec["estimated_risk_rs"] = out.get("estimated_risk_rs")
    rec["risk_service_budget"] = out.get("budget")
    rec["freshness"] = out.get("freshness")
    rec["sector"] = out.get("sector")
    outcome = out.get("outcome")
    if outcome in ("allow", "reduce"):
        q = int(out.get("approved_qty") or 0)
        if outcome == "reduce":
            rec["decision"] = C.RISK_APPROVE_REDUCED
        elif rec["entry_type"] == "LIMIT":
            rec["decision"] = C.RISK_CONDITIONAL
        else:
            rec["decision"] = C.RISK_APPROVE
        if rec["entry_type"] == "LIMIT":
            rec["conditional"] = {"type": "limit_entry", "price": entry,
                                  "text": f"Approved for a LIMIT entry at ₹{entry:,.2f}: it opens only if the price pulls "
                                          f"back to it before {proposal['entry'].get('expires_at')}."}
        rec["approved_qty"] = q
        rec["planned_risk_rs"] = _planned(q, entry, stop)
        rec["stressed_risk_rs"] = round(rec["planned_risk_rs"] + q * stop * gap_pct / 100.0, 2)
        before = _f(state.get("open_risk_rs"))
        tot = _f((out.get("estimated_risk_rs") or {}).get("total"))
        rec["portfolio_risk_after_rs"] = round(before + tot, 2) if before is not None and tot is not None else None
        eb = _f(state.get("exposure_rs"))
        rec["exposure_after_rs"] = round(eb + q * entry, 2) if eb is not None else None
        if how == "reserve" and not out.get("reservation_id"):
            rec["decision"] = C.RISK_BLOCKED                  # defensive: an approval without its reservation is no approval
            rec["reasons"].append({"code": "reservation_missing", "check": "reservation", "severity": "block",
                                   "message": "The risk service returned no reservation.", "source": "spt"})
            rec["approved_qty"] = 0
    else:
        rec["decision"] = classify_block(out.get("reasons") or [])
        rec["data_insufficient"] = all(r.get("check") == "inputs" for r in out.get("reasons") or []
                                       if r.get("severity") in service.BLOCKING)
    return await _finish(db, rec, proposal, emit=emit)


async def _finish(db, rec: Dict[str, Any], proposal: Dict[str, Any], *, emit: bool) -> Dict[str, Any]:
    shown = [r for r in rec["reasons"] if r.get("severity") != "info"]
    rec["reason_codes"] = [r["code"] for r in shown]
    rec["explanations"] = [r.get("message") for r in shown]
    if emit and not rec["dry_run"]:
        etype = "RISK_APPROVED" if rec["decision"] in APPROVED else "RISK_REJECTED"
        await events.emit(db, etype, idempotency_key=f"proposal:{proposal['_id']}:risk:{rec['decision_id']}",
                          source_service=SOURCE, correlation_id=proposal["_id"], account_id=rec["account_id"],
                          instrument_id=proposal.get("symbol"),
                          payload={k: rec.get(k) for k in ("decision_id", "decision", "proposal_id", "opportunity_id",
                                                            "requested_qty", "approved_qty", "reason_codes",
                                                            "risk_service_decision_id", "reservation_id", "order_id",
                                                            "planned_risk_rs", "stressed_risk_rs", "policy_versions")})
    return rec


# ── modifications (slice C) ──────────────────────────────────────────────────
def _pos_fields(position: Dict[str, Any]) -> Dict[str, Any]:
    qty = position.get("open_quantity", position.get("quantity_open", position.get("quantity")))
    avg = position.get("avg_entry_price", position.get("entry_avg", position.get("entry_price")))
    stop = position.get("stop_loss", position.get("stop_price"))
    return {"qty": int(qty) if _f(qty) is not None else None, "avg": _f(avg), "stop": _f(stop),
            "symbol": position.get("symbol"), "direction": position.get("direction") or "long"}


EXIT_RULE_KINDS = ("trailing", "trend_exit")


def normalize_change(change: Dict[str, Any]) -> Dict[str, Any]:
    """Slice C's form {kind, field, previous, new} (services/spt/paper/modify.py: kind stop_loss with new = the price or
    None to remove it; trailing / trend_exit with new = None to turn the rule off) in the flat form judged here."""
    kind = change.get("kind")
    if kind == "stop_loss":
        return {"remove_stop": True} if change.get("new") is None else {"stop_loss": change.get("new")}
    if kind in EXIT_RULE_KINDS:
        return {"exit_rule_off": kind} if change.get("new") is None else {"exit_rule_on": kind}
    return change


def classify_change(position: Dict[str, Any], change: Dict[str, Any]) -> Dict[str, Any]:
    """{risk_increasing, kind, new_qty, new_stop, add_qty, why}. Long positions (the only SPT kind tonight)."""
    change = normalize_change(change)
    p = _pos_fields(position)
    out = {"risk_increasing": False, "kind": "neutral", "new_qty": p["qty"], "new_stop": p["stop"], "add_qty": 0,
           "add_price": None, "why": "the change does not move the stop further away or add quantity"}
    if change.get("exit_rule_off"):
        # The loss at the stop is unchanged, but a protective exit is removed: judged as an increase (slice C's
        # classification), so the account's blocks apply; the per-trade and open-risk budgets are unaffected.
        return {**out, "risk_increasing": True, "kind": "exit_rule_off",
                "why": f"turns the {change['exit_rule_off']} exit off"}
    if change.get("exit_rule_on"):
        return {**out, "kind": "exit_rule_on", "why": f"turns the {change['exit_rule_on']} exit on"}
    if change.get("remove_stop"):
        return {**out, "risk_increasing": True, "kind": "remove_stop", "new_stop": None, "why": "removes the stop"}
    if "stop_loss" in change:
        new = _f(change.get("stop_loss"))
        if new is None:
            return {**out, "risk_increasing": True, "kind": "remove_stop", "new_stop": None, "why": "removes the stop"}
        out["new_stop"] = new
        if p["stop"] is not None and new < p["stop"] - 1e-9:
            out.update(risk_increasing=True, kind="wider_stop", why=f"moves the stop from {p['stop']:g} down to {new:g}")
        else:
            out.update(kind="tighter_stop", why="moves the stop closer (or sets one)")
    add = _f(change.get("add_quantity"))
    if add is not None and add > 0:
        out.update(risk_increasing=True, kind="add_quantity" if out["kind"] in ("neutral", "tighter_stop") else out["kind"] + "+add",
                   add_qty=int(add), add_price=_f(change.get("price")), new_qty=(p["qty"] or 0) + int(add),
                   why=(out["why"] if out["risk_increasing"] else "") + f"; adds {int(add)} shares")
    elif add is not None and add < 0:
        out.update(new_qty=max(0, (p["qty"] or 0) + int(add)))
        if not out["risk_increasing"]:
            out.update(kind="reduce_quantity", why="reduces the quantity")
    return out


async def check_modification(db, *, user_id: str, position: Dict[str, Any], change: Dict[str, Any],
                             now: Optional[datetime] = None) -> Dict[str, Any]:
    """{decision, reason_codes, explanations, decision_id, risk_increasing, kind} (module docstring). `change` is slice
    C's {kind: stop_loss | trailing | trend_exit, field, previous, new} (new None = remove the stop / turn the rule off),
    or any of {"stop_loss": price}, {"remove_stop": true}, {"add_quantity": n, "price": p}, {"add_quantity": -n}.
    Anything else (a target) does not increase the risk at the stop and is approved."""
    moment = now or desk.utcnow()
    cls = classify_change(position, change)
    p = _pos_fields(position)
    reasons: List[Dict[str, Any]] = []
    decision = C.RISK_APPROVE
    detail: Dict[str, Any] = {"position_id": position.get("_id") or position.get("position_id"), "change": change,
                              "classification": cls, "spt_risk_version": C.SPT_RISK_VERSION}

    def fail(code: str, dec: str, message: str, value: Any = None, limit: Any = None) -> None:
        nonlocal decision
        reasons.append({"code": code, "severity": "block", "decision": dec, "message": message, "value": value, "limit": limit})
        order = {C.RISK_APPROVE: 0, C.RISK_REJECT: 1, C.RISK_BLOCKED: 2, C.RISK_HALT: 3}
        if order[dec] > order.get(decision, 0):
            decision = dec

    if cls["risk_increasing"]:
        from . import allocation as alloc
        state = await alloc.account_state(db, user_id, now=moment)
        ctl = state.get("controls")
        if ctl is None:
            fail("controls_unreadable", C.RISK_BLOCKED, "The kill switch and halt could not be read.")
        elif ctl.get("kill_switch") or ctl.get("halted"):
            fail("kill_switch_on" if ctl.get("kill_switch") else "trading_halted", C.RISK_HALT,
                 "Risk-increasing changes are blocked while the kill switch / halt is on.")
        lad = state.get("ladder") or {}
        if lad.get("blocks_new_entries"):
            fail({"halt": "drawdown_halt_ladder", "restricted": "drawdown_restricted"}.get(lad.get("band"), "drawdown_unknown"),
                 C.RISK_HALT if lad.get("band") == policy.LADDER_HALT else C.RISK_BLOCKED, lad.get("text") or "Drawdown.")
        limits = (state.get("profile") or {}).get("limits") or {}
        for key, pct_key, code in (("day", "daily_loss_pct", "daily_loss_halt"), ("week", "weekly_loss_pct", "weekly_loss_halt")):
            pnl, start = _f(state.get(f"{key}_pnl_rs")), _f(state.get(f"{key}_start_equity_rs"))
            if pnl is None or not start:
                fail(f"{code.split('_halt')[0]}_unknown", C.RISK_BLOCKED, f"The {key}'s P&L is unknown.")
            elif limits and max(0.0, -pnl) / start * 100.0 >= float(limits[pct_key]) - 1e-9:
                fail(code, C.RISK_BLOCKED, f"The {key}'s loss is at or past the {limits[pct_key]:g}% limit.")
        if cls["kind"].startswith("remove_stop"):
            fail("stop_required", C.RISK_REJECT, "Every position keeps a stop loss (PRD §18 rule 2); removing it is refused.")
        equity = _f(state.get("equity_rs"))
        if equity is None:
            fail("equity_unknown", C.RISK_BLOCKED, "Paper equity is unknown, so the change cannot be measured.")
        elif not cls["kind"].startswith("remove_stop") and p["avg"] and cls["new_stop"] is not None and p["qty"] is not None:
            add_px = cls["add_price"] or p["avg"]
            new_qty = int(cls["new_qty"] or 0)
            new_avg = ((p["avg"] * p["qty"]) + add_px * cls["add_qty"]) / new_qty if new_qty else p["avg"]
            if cls["new_stop"] >= new_avg:
                pass                                       # the stop is above the average: no loss at the stop to judge
            else:
                new_risk = est.cash_risk(new_qty, new_avg, cls["new_stop"])["total"]
                old_risk = est.cash_risk(p["qty"], p["avg"], p["stop"])["total"] if p["stop"] is not None and p["stop"] < p["avg"] else 0.0
                per_trade = equity * float(limits["per_trade_risk_pct"]) / 100.0
                detail.update(new_risk_rs=new_risk, old_risk_rs=old_risk, per_trade_budget_rs=round(per_trade, 2))
                if new_risk > per_trade + 1e-6:
                    fail("per_trade_risk_exceeded", C.RISK_REJECT, f"The position's risk after the change ₹{new_risk:,.2f} "
                                                                   f"exceeds the per-trade budget ₹{per_trade:,.2f}.",
                         new_risk, round(per_trade, 2))
                room = _f(state.get("open_risk_cap_rs"))
                used = _f(state.get("open_risk_rs"))
                if room is not None and used is not None and new_risk - old_risk > room - used + 1e-6:
                    fail("open_risk_exceeded", C.RISK_BLOCKED, f"The added risk ₹{new_risk - old_risk:,.2f} exceeds the "
                                                               f"open-risk room ₹{max(room - used, 0):,.2f}.")
            if cls["add_qty"]:
                pos_cap = equity * float(limits["max_position_pct"]) / 100.0
                if new_qty * new_avg > pos_cap + 1e-6:
                    fail("position_exceeded", C.RISK_REJECT, f"The position's value after the add ₹{new_qty * new_avg:,.2f} "
                                                             f"exceeds the position limit ₹{pos_cap:,.2f}.")
                need = cls["add_qty"] * add_px
                if need > float(state.get("available_rs") or 0.0) + 1e-6:
                    fail("insufficient_paper_funds", C.RISK_BLOCKED, f"The add needs ₹{need:,.2f}; ₹"
                                                                     f"{float(state.get('available_rs') or 0):,.2f} is available.")
        elif p["avg"] is None or p["qty"] is None:
            fail("position_unreadable", C.RISK_REJECT, "The position's quantity or average price is missing.")
    rid = await rc.record_decision(
        db, user_id, action=MOD_PATH, path=MOD_PATH, source=MOD_SOURCE, now=moment, policy_version=C.SPT_RISK_VERSION,
        outcome="allowed" if decision == C.RISK_APPROVE else "blocked", symbol=p["symbol"],
        requested_qty=cls["new_qty"], approved_qty=cls["new_qty"] if decision == C.RISK_APPROVE else None,
        reasons=reasons, correlation_id=str(detail["position_id"] or ""), detail={**detail, "decision": decision})
    if rid is None and cls["risk_increasing"]:
        fail("decision_unrecorded", C.RISK_REJECT, "The decision could not be recorded, so the risk-increasing change is "
                                                   "refused.")
    return {"decision": decision, "reason_codes": [r["code"] for r in reasons],
            "explanations": [r["message"] for r in reasons] or [f"Allowed: the change {cls['why']}."],
            "decision_id": rid, "risk_increasing": cls["risk_increasing"], "kind": cls["kind"],
            "version": C.SPT_RISK_VERSION}


# ── kill switch state (WF §19.3) ─────────────────────────────────────────────
KILL_SWITCH_CACHE_S = 15.0
_ks_cache: Dict[str, Any] = {}


async def kill_switch_state(db, user_id: str, *, now: Optional[datetime] = None,
                            state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """{state, entries_blocked, blocking, kill_switch, halted, code, reason, reasons[], text, controls, ladder, mode,
    mapping_version} (module docstring). Reads only. Slice C (services/spt/paper/controls.entry_block) calls it as
    `kill_switch_state(db, user_id=...)` and blocks new entries when `entries_blocked` is true.

    Called that way (no `now`, no `state`), the account part (book, SPT P&L, ladder) is reused for KILL_SWITCH_CACHE_S
    seconds per user, because slice C asks on every monitor round; the kill switch and halt (risk_controls) are re-read
    on every call, so pressing the switch takes effect at once."""
    import time
    moment = now or desk.utcnow()
    if state is None:
        from . import allocation as alloc
        hit = _ks_cache.get(user_id) if now is None else None
        if hit is not None and time.monotonic() - hit[0] < KILL_SWITCH_CACHE_S:
            state = dict(hit[1])
            from services import risk_book
            state["controls"] = await risk_book.controls(db, user_id)
        else:
            state = await alloc.account_state(db, user_id, now=moment)
            if now is None:
                _ks_cache[user_id] = (time.monotonic(), state)
    cfg = state.get("config") or {}
    ctl = state.get("controls")
    reasons: List[Dict[str, str]] = []
    triggered = restricted = False
    if ctl is None:
        triggered = True
        reasons.append({"code": "controls_unreadable", "text": "The kill switch could not be read (fail closed)."})
    else:
        if ctl.get("kill_switch"):
            triggered = True
            reasons.append({"code": "kill_switch_on", "text": f"The kill switch is on: {ctl.get('reason') or 'no reason given'}."})
        if ctl.get("halted"):
            triggered = True
            reasons.append({"code": "trading_halted", "text": f"Trading is halted: {ctl.get('reason') or 'no reason given'}."})
    lad = state.get("ladder") or {}
    limits = (state.get("profile") or {}).get("limits") or {}
    dd = _f(state.get("drawdown_pct"))
    if lad.get("band") == policy.LADDER_HALT:
        triggered = True
        reasons.append({"code": "drawdown_halt_ladder", "text": lad.get("text") or ""})
    elif limits and dd is not None and dd >= float(limits["max_drawdown_pct"]) - 1e-9:
        triggered = True
        reasons.append({"code": "drawdown_halt", "text": f"Drawdown {dd:.2f}% is at the profile's {limits['max_drawdown_pct']:g}% halt."})
    if lad.get("band") == policy.LADDER_RESTRICTED:
        restricted = True
        reasons.append({"code": "drawdown_restricted", "text": lad.get("text") or ""})
    elif lad.get("band") in (policy.LADDER_UNKNOWN, None):
        restricted = True
        reasons.append({"code": "drawdown_unknown", "text": lad.get("text") or "Drawdown is unknown."})
    for key, pct_key, code in (("day", "daily_loss_pct", "daily_loss_halt"), ("week", "weekly_loss_pct", "weekly_loss_halt")):
        pnl, start = _f(state.get(f"{key}_pnl_rs")), _f(state.get(f"{key}_start_equity_rs"))
        if pnl is None or not start:
            restricted = True
            reasons.append({"code": f"{key}_loss_unknown", "text": f"The {key}'s P&L is unknown (fail closed)."})
        elif limits and max(0.0, -pnl) / start * 100.0 >= float(limits[pct_key]) - 1e-9:
            restricted = True
            reasons.append({"code": code, "text": f"The {key}'s loss {max(0.0, -pnl) / start * 100.0:.2f}% is at or past "
                                                  f"the {limits[pct_key]:g}% limit."})
    if triggered:
        st = "TRIGGERED"
    elif restricted:
        st = "RESTRICTED"
    elif (cfg.get("mode") or C.MODE_OFF) != C.MODE_OFF:
        st = "ACTIVE"
    else:
        st = "DISABLED"
    texts = {"TRIGGERED": "New paper entries and risk-increasing changes are refused; exits and monitoring continue.",
             "RESTRICTED": "New entries and risk-increasing changes are refused by a limit; exits continue.",
             "ACTIVE": "Armed: nothing is breached; new entries go through the risk engine.",
             "DISABLED": "The SPT mode is off for this account: nothing is proposed or ordered."}
    blocked = st in ("TRIGGERED", "RESTRICTED")
    return {"state": st, "entries_blocked": blocked, "blocking": blocked,
            "kill_switch": bool((ctl or {}).get("kill_switch")), "halted": bool((ctl or {}).get("halted")),
            "code": reasons[0]["code"] if blocked and reasons else None,
            "reason": "; ".join(r["text"] for r in reasons) if blocked else None,
            "reasons": reasons, "text": texts[st], "controls": ctl, "ladder": lad, "mode": cfg.get("mode"),
            "states": ["ACTIVE", "TRIGGERED", "RESTRICTED", "RESET_PENDING", "DISABLED"],
            "reset_pending_note": "RESET_PENDING is not produced: services/risk_controls keeps no reset request; clearing "
                                  "the switch is one admin action (PUT /api/admin/risk/{user_id}/kill-switch).",
            "mapping_version": KILL_SWITCH_MAPPING_VERSION}


# ── stress test (P1, PRD §9.2 stressed risk, §10.5 scenarios) ────────────────
STRESS_VERSION = "spt-stress-v1"
SECTOR_SHOCK_PCT = 5.0
MARKET_SHOCKS_PCT = (3.0, 5.0)


async def open_spt_book(db, user_id: str, state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The caller's open SPT exposure: every reservation on spt_orders (pending entries and filled positions), with its
    quantity, entry and stop from slice C's open position when one exists, else from the proposal's approved order."""
    book = state.get("book") or {}
    entries = [e for e in (book.get("reservations") or []) if e.get("store") == C.ORDERS]
    if not entries:
        return []
    ids = [e.get("trade_id") for e in entries]
    props = {p.get("order_id"): p for p in await db[C.PROPOSALS].find({"user_id": user_id, "order_id": {"$in": ids}})
             .to_list(len(ids))}
    positions: Dict[str, Dict[str, Any]] = {}
    for pos in await db[C.POSITIONS].find({"user_id": user_id, "state": {"$in": list(C.POS_OPEN_STATES)}}).to_list(500):
        oid = pos.get("entry_order_id") or pos.get("order_id")
        if oid:
            positions[oid] = pos
    out = []
    for e in entries:
        p = props.get(e.get("trade_id")) or {}
        pos = positions.get(e.get("trade_id"))
        if pos is not None:
            f = _pos_fields(pos)
            qty, entry, stop, src = f["qty"], f["avg"], f["stop"], "open position (spt_positions)"
        else:
            r = p.get("risk") or {}
            qty, entry, stop, src = r.get("approved_qty"), (p.get("entry") or {}).get("price"), p.get("stop_loss"), \
                "pending entry order (the proposal's approved order)"
        out.append({"order_id": e.get("trade_id"), "symbol": e.get("symbol"), "sector": e.get("sector"),
                    "quantity": qty, "entry": _f(entry), "stop": _f(stop), "exposure_rs": e.get("exposure_rs"),
                    "reserved_risk_rs": e.get("risk_rs"), "source": src})
    return out


def stress(rows: List[Dict[str, Any]], *, gap_pct: float, model: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Deterministic scenarios on the open SPT book (no optimiser; numpy sums). A row without quantity, entry or stop is
    listed under `unpriced` and left out of every total, never valued at a guess."""
    import numpy as np
    priced = [r for r in rows if r.get("quantity") and r.get("entry") and r.get("stop") is not None]
    unpriced = [r["order_id"] for r in rows if r not in priced]
    q = np.array([float(r["quantity"]) for r in priced])
    e = np.array([float(r["entry"]) for r in priced])
    s = np.array([float(r["stop"]) for r in priced])
    costs = np.array([desk.round_trip_cost(int(r["quantity"]), float(r["entry"]), float(r["stop"]), model or desk.COST_MODEL)
                      for r in priced])
    planned = q * np.maximum(e - s, 0.0) + costs
    stressed = planned + q * s * gap_pct / 100.0
    value = q * e
    per = [{**r, "planned_rs": round(float(pl), 2), "stressed_rs": round(float(st), 2), "value_rs": round(float(v), 2)}
           for r, pl, st, v in zip(priced, planned, stressed, value)]
    sectors: Dict[str, float] = {}
    for r, v in zip(priced, value):
        key = r.get("sector") or "unclassified"
        sectors[key] = sectors.get(key, 0.0) + float(v)
    sector_shock = {k: round(v * SECTOR_SHOCK_PCT / 100.0, 2) for k, v in sectors.items()}
    worst_sector = max(sector_shock.items(), key=lambda kv: kv[1]) if sector_shock else (None, 0.0)
    market = [{"shock_pct": -x, "beta": 1.0, "beta_assumed": True, "loss_rs": round(float(value.sum()) * x / 100.0, 2)}
              for x in MARKET_SHOCKS_PCT]
    return {"version": STRESS_VERSION, "positions": per, "unpriced": unpriced,
            "totals": {"planned_rs": round(float(planned.sum()), 2), "stressed_rs": round(float(stressed.sum()), 2),
                       "value_rs": round(float(value.sum()), 2)},
            "scenarios": [
                {"name": "gap_through_stop", "gap_pct": gap_pct, "planned_rs": round(float(planned.sum()), 2),
                 "stressed_rs": round(float(stressed.sum()), 2),
                 "text": f"Every position gaps {gap_pct:g}% through its stop and exits there (costs included)."},
                {"name": "sector_shock", "shock_pct": -SECTOR_SHOCK_PCT, "by_sector_rs": sector_shock,
                 "worst_sector": worst_sector[0], "worst_loss_rs": worst_sector[1],
                 "text": f"One sector falls {SECTOR_SHOCK_PCT:g}% (marked to market, stops not triggered)."},
                {"name": "market_shock", "results": market,
                 "text": "The market falls 3% / 5%; each position moves with beta 1 (assumed: no beta source is wired "
                         "into SPT yet), marked to market."}],
            "basis": "deterministic scenarios on the open SPT entries and positions; correlation and VaR are not "
                     "modelled in this release (DESIGN §9)"}
