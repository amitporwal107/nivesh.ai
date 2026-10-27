"""The canonical TradePlan (Phase 2.1, docs/NIVESH_AI_LAB_PHASE_SUCCESS_CRITERIA.md; schema B §10 Q8a).

One backend object per tradeable idea, built from what the Strategy Builder already computes (candidates.py: the
entry, the invalidation and its basis, the scenario targets, the sizing, the desk cost card, the payoff) and, for an
F&O board idea, from the idea and the strategy-levels engine (services/strategy_levels.py). Nothing here computes a
level a second time: the AI scanner is the SETUP SOURCE (trigger, stop and how that stop was set, trade_planner
.stop_meta), the plan builder turns the setup into levels, and this module records them once, by id.

    plan_id      "tp_" + plan.digest(content): the same content always gives the same id. Content is everything
                 below except NOT_HASHED (when it was stored, its version, its owners, its provenance and the
                 derived lifecycle status), so two surfaces that show the same levels show the same id.
    entry        {price, order_type at_close | stop_trigger | limit_pullback | at_premium, desk_entry_rule
                 at_once | break_above | pullback_to, valid_for_sessions, reference_close, logic}
    stop         {price, method structural | atr | capital | premium | underlying | unknown, atr, atr_multiple,
                 distance_atr, swing_ref, measured_from, rationale, invalidation}
    r_per_unit   |entry − stop|
    targets      [{name, price, r_multiple, rule, primary}] — `primary` is the one a paper trade records
    size         {status, quantity, lots, lot_size, risk_budget_rs, risk_rs, risk_pct_of_equity, equity_basis, binding, missing}
    costs        the desk cost card (desk-cost-v2) breakdown of a round trip at the stop
    exit_plan    {stop, targets, primary_target, time, trailing, trend, options} — trailing / trend are placeholders
                 the exits branch (feat/p2-exits-backtest) fills; `options` is strategy_levels' premium stop / T1 / T2
    eligibility  {eligible, paper_eligible, state, reasons}; `state` is the plan's PROPOSED lifecycle state
    lifecycle    {status: "proposed"}; the status a reader sees is DERIVED from the linked trades
                 (routes/desk_trading GET /api/desk/trade-plans/{plan_id}, trade_lifecycle.plan_status)

Store: Mongo `trade_plans`, `_id = plan_id`, insert-once. A plan with new content but the same lineage (instrument,
segment, family, direction and setup day) is stored as the next VERSION with `supersedes` and a `revalidation`
record; a version that fails revalidation is stored not eligible, so it can be read but not traded.

Ideas, not recommendations; nothing here is sent to a broker.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from services import trade_lifecycle as lc

logger = logging.getLogger(__name__)

SCHEMA = "trade-plan-v1"
RULES_VERSION = "trade-plan-v1 (2026-10-27)"
COLLECTION = "trade_plans"
DESK_ENTRY_RULE = {"at_close": "at_once", "stop_trigger": "break_above", "limit_pullback": "pullback_to", "at_premium": "at_once"}
ORDER_TEXT = {
    "at_close": "at the session's close (the desk records it at once, inside that session's range)",
    "stop_trigger": "a buy-stop: enters when the price trades at or above the trigger",
    "limit_pullback": "a limit: enters when the price pulls back to the level",
    "at_premium": "every leg at its end-of-day premium (NSE F&O bhavcopy close)",
}
DEFAULT_ENTRY_WINDOW = 5          # sessions a conditional entry waits (services/desk_trading.DEFAULT_ENTRY_WINDOW)
STOP_METHODS = ("structural", "atr", "capital", "premium", "underlying", "unknown")
NOT_HASHED = ("plan_id", "_id", "created_at", "version", "supersedes", "revalidation", "owners", "lifecycle", "source",
              "events", "lineage_key", "stored", "store_error")
EXITS_OWNER = "feat/p2-exits-backtest"
PAPER_STATES = (lc.ELIGIBLE, lc.WAIT)
_TOL = 0.0005


def _digest(obj: Any, n: int = 16) -> str:
    from .plan import digest          # lazy: plan.py imports this module

    return digest(obj, n)


def r2(x: Any) -> Optional[float]:
    return None if x is None else round(float(x), 2)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── order type and R ─────────────────────────────────────────────────────────
def order_type_for(entry: float, close: Optional[float], *, bucket: Optional[str] = None, stage: Optional[str] = None) -> str:
    """Where the entry sits against the last close decides the order: above it a buy-stop (`stop_trigger`), below it a
    limit (`limit_pullback`), at it the close (`at_close`). The desk's own rule (frontend desk-trading.ts entryRuleFor,
    the scanner rounds to the paisa, hence 0.05% tolerance); without a close, the setup's stage or bucket decides."""
    if close is not None and close > 0:
        tol = close * _TOL
        if entry > close + tol:
            return "stop_trigger"
        if entry < close - tol:
            return "limit_pullback"
        return "at_close"
    st = (stage or "").upper()
    if st == "ACCUMULATION":
        return "limit_pullback"
    if st == "EARLY_BREAKOUT" or bucket in ("pre_breakout", "true_accumulation"):
        return "stop_trigger"
    return "at_close"


def r_multiple(price: float, entry: float, risk: float, up: bool) -> Optional[float]:
    if not risk:
        return None
    return round(((price - entry) if up else (entry - price)) / risk, 2)


def targets_with_r(entry: float, stop: float, levels: Sequence[Dict[str, Any]], up: bool, primary: str) -> List[Dict[str, Any]]:
    risk = abs(entry - stop)
    return [{"name": lv["name"], "price": r2(lv["price"]), "r_multiple": r_multiple(float(lv["price"]), entry, risk, up),
             "rule": lv.get("rule"), "primary": lv["name"] == primary}
            for lv in levels if lv.get("price") is not None]


def primary_target(tp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return next((t for t in tp.get("targets") or [] if t.get("primary")), None)


# ── eligibility ──────────────────────────────────────────────────────────────
_STATE_BY_STATUS = {"candidate": lc.ELIGIBLE, "wait": lc.WAIT, "no_trade": lc.REJECTED, "avoid": lc.REJECTED,
                    "insufficient_data": lc.NO_SETUP}


def eligibility(status: str, reasons: Sequence[Dict[str, Any]], *, conditional_entry: bool,
                extra: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """{eligible, paper_eligible, state, reasons}. A viable candidate is TRADE_ELIGIBLE; a candidate that waits for
    its trigger is WAIT_FOR_CONFIRMATION and may be recorded only with a conditional entry (the desk waits for the
    level); no_trade / avoid is REJECTED; insufficient_data is NO_SETUP. `extra` reasons (a validation problem, a
    direction conflict) make it REJECTED."""
    state = _STATE_BY_STATUS.get(status, lc.NO_SETUP)
    rs = [{"code": r.get("code"), "message": r.get("message")} for r in reasons if isinstance(r, dict)]
    if extra:
        state = lc.REJECTED
        rs += [{"code": r.get("code"), "message": r.get("message")} for r in extra]
    paper = state == lc.ELIGIBLE or (state == lc.WAIT and conditional_entry)
    return {"eligible": state in PAPER_STATES, "paper_eligible": paper, "state": state, "status": status, "reasons": rs}


# ── building ─────────────────────────────────────────────────────────────────
def _snapshot_refs(plan: Dict[str, Any], keys: Sequence[str]) -> List[Dict[str, Any]]:
    return [{"key": s.get("key"), "source": s.get("source"), "as_of": s.get("as_of"), "content_hash": s.get("content_hash")}
            for s in plan.get("source_snapshots") or [] if s.get("key") in keys and s.get("ok")]


def _risk_flags(c: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = [{"code": "warning", "message": w} for w in c.get("warnings") or []]
    sz = c.get("sizing") or {}
    if sz.get("status") == "incomplete":
        out.append({"code": "sizing_incomplete", "message": "Sizing needs " + ", ".join(sz.get("missing") or []) + "."})
    return out


def _exit_plan(stop: Dict[str, Any], targets: List[Dict[str, Any]], max_sessions: Optional[int],
               options: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    prim = next((t["name"] for t in targets if t.get("primary")), None)
    return {
        "stop": {"price": stop.get("price"), "method": stop.get("method")},
        "targets": [{"name": t["name"], "price": t["price"], "r_multiple": t["r_multiple"]} for t in targets],
        "primary_target": prim,
        "time": {"max_sessions": max_sessions, "basis": "the setup's maximum horizon in sessions, else the plan's horizon" if max_sessions else None},
        # Research options (decision D4): opt-in, versioned, evaluated by the exits branch. Recorded here as "not
        # enabled" so a reader never has to guess whether a trailing or trend exit applies.
        "trailing": {"enabled": False, "atr_multiple": None, "owner": EXITS_OWNER},
        "trend": {"enabled": False, "ma": None, "period": None, "owner": EXITS_OWNER},
        "options": options,
    }


def _size(c: Dict[str, Any], inputs: Dict[str, Any], lot: int) -> Dict[str, Any]:
    sz = c.get("sizing") or {}
    capital = inputs.get("capital")
    risk = sz.get("risk_at_stop_net_inr") if sz.get("risk_at_stop_net_inr") is not None else sz.get("risk_at_stop_inr")
    done = sz.get("status") == "complete"
    return {"status": sz.get("status"), "quantity": (sz.get("quantity") or 0) * lot if done else None,
            "lots": sz.get("quantity") if done and lot > 1 else None, "lot_size": lot,
            "risk_budget_rs": r2(sz.get("risk_budget_inr")), "risk_rs": r2(risk) if done else None,
            "risk_pct_of_equity": (round(float(risk) / float(capital) * 100, 3) if done and risk is not None and capital else None),
            "equity_basis": ("the capital stated in the plan inputs (the per-account paper-equity basis is Phase 1)"
                             if capital else None),
            "binding": sz.get("binding") if done else None, "missing": list(sz.get("missing") or []),
            "costs_included": bool(sz.get("costs_included"))}


def linear_plan(plan: Dict[str, Any], c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The TradePlan of a cash or futures candidate (candidates.linear_candidate, or a cash candidate waiting for its
    trigger). None when the candidate has no entry or no stop: nothing is invented."""
    from services import desk_trading as desk

    entry_b, inv = c.get("entry") or {}, (c.get("invalidation") or {}).get("technical") or {}
    entry, stop = entry_b.get("trigger"), inv.get("price")
    if entry is None or stop is None or not c.get("targets") or not c.get("legs"):
        return None
    up = c.get("direction") != "bearish"
    leg = c["legs"][0]
    lot = int(leg.get("lot_size") or 1)
    inputs = plan.get("inputs") or {}
    order = entry_b.get("order_type") or "at_close"
    targets = targets_with_r(float(entry), float(stop), c["targets"], up, "base")
    model = dict(desk.COST_MODEL)
    for k_in, k_model in (("slippage_pct", "slippage_pct_per_side"), ("brokerage_per_side", "brokerage_rs_per_side")):
        if (inputs.get("costs") or {}).get(k_in) is not None:
            model[k_model] = inputs["costs"][k_in]
    seg = "equity_delivery" if c["segment"] == "cash" else "futures"
    sz = c.get("sizing") or {}
    units = (sz.get("quantity") or 0) * lot if sz.get("status") == "complete" else lot
    stop_b = {"price": r2(stop), "method": inv.get("method") or "unknown", "atr": inv.get("atr"),
              "atr_multiple": inv.get("atr_multiple"), "distance_atr": inv.get("distance_atr"), "swing_ref": inv.get("swing_ref"),
              "measured_from": inv.get("measured_from"), "rationale": inv.get("basis"), "invalidation": inv.get("meaning")}
    # Decision D4: the time exit is the SETUP's maximum horizon in sessions (the scanner's timeframe_days_max, which the
    # desk rows send as max_hold_sessions since feat/p2-exits-backtest), else the plan's own horizon.
    tf = (c.get("setup") or {}).get("timeframe_days") or [None, None]
    max_sessions = tf[1] if isinstance(tf, list) and len(tf) == 2 and isinstance(tf[1], int) and tf[1] >= 1 else inputs.get("horizon_days")
    tp = {
        "schema": SCHEMA, "rules_version": RULES_VERSION, "strategy_rules_version": plan.get("rules_version"),
        "calculation_version": plan.get("calculation_version"),
        "strategy": {"segment": c["segment"], "family": c["family"], "label": c.get("label"), "direction": c.get("direction"),
                     "candidate_id": c["id"]},
        "instrument": {"symbol": (plan.get("underlying") or {}).get("symbol"), "segment": c["segment"], "lot_size": lot,
                       "expiry": leg.get("expiry"),
                       "legs": [{"kind": l.get("kind"), "side": l.get("side"), "lot_size": l.get("lot_size"), "expiry": l.get("expiry"),
                                 "entry_price": r2(l.get("entry_price"))} for l in c["legs"]]},
        "timeframe": {"horizon": inputs.get("horizon"), "sessions_max": max_sessions},
        "setup": c.get("setup"),
        "entry": {"price": r2(entry), "order_type": order, "desk_entry_rule": DESK_ENTRY_RULE[order],
                  "order_text": ORDER_TEXT[order], "valid_for_sessions": DEFAULT_ENTRY_WINDOW if order in ("stop_trigger", "limit_pullback") else None,
                  "reference_close": r2((plan.get("underlying") or {}).get("spot")), "logic": entry_b.get("logic")},
        "stop": stop_b,
        "r_per_unit": r2(abs(float(entry) - float(stop))),
        "targets": targets,
        "size": _size(c, inputs, lot),
        "costs": {"model": model.get("version"), "basis": f"a round trip of {units} unit(s) from the entry to the stop",
                  "units": units, "breakdown_at_stop": desk.round_trip_breakdown(units, float(entry), float(stop), model, segment=seg, long=up),
                  "excluded": ["DP charges", "income tax", "gap slippage beyond the cost card's slippage"]},
        "exit_plan": _exit_plan(stop_b, targets, max_sessions, None),
        "evidence_refs": _snapshot_refs(plan, ("scanner_bucket", "indicators", "scan_row", "futures", "buildup", "chain", "regime")),
        "risk_flags": _risk_flags(c),
        "eligibility": eligibility(c.get("status"), c.get("reasons") or [], conditional_entry=order in ("stop_trigger", "limit_pullback")),
        "data_as_of": plan.get("data_as_of"),
        "sent_to_broker": False,
    }
    tp["source"] = {"kind": "strategy_plan", "strategy_plan_id": plan.get("plan_id"), "candidate_id": c["id"]}
    return finalize(tp)


def _levels_request(underlying: str, reference: float, as_of: Optional[str], legs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    keys = ("kind", "side", "quantity", "lot_size", "entry_price", "expiry", "strike", "option_type", "price_source", "iv_pct")
    req: Dict[str, Any] = {"underlying": underlying, "reference_price": reference}
    if as_of:
        req["as_of"] = as_of
    req["legs"] = [{k: l.get(k) for k in keys if l.get(k) is not None} for l in legs]
    return req


def options_exit(levels: Optional[Dict[str, Any]], *, as_of: Optional[str], error: Optional[str] = None) -> Dict[str, Any]:
    """`exit_plan.options` from a strategy_levels answer, under strategy_levels' OWN names: the seam the exits work
    reads (services/desk_strategy_trades.premium_plan: kind, entry, planned_stop, target_1, target_2 per unit,
    unit_shares, version, greek_review {entry_delta_per_unit, view}). Also the underlying levels those premiums
    correspond to and the expiry flags. Stored at entry; EVALUATED by desk_strategy_trades (feat/p2-exits-backtest)."""
    if not levels or not levels.get("valid"):
        return {"status": "unavailable", "reason": error or ((levels or {}).get("reason") or "the levels engine gave no answer"),
                "evaluation": f"none: no premium levels ({EXITS_OWNER} evaluates them when present)"}
    prem, und, gr = levels.get("premium") or {}, levels.get("underlying") or {}, levels.get("greeks") or {}
    view = und.get("view")
    return {"status": "ok", "version": levels.get("version"), "as_of": as_of, "kind": prem.get("kind"),
            "entry": prem.get("entry"), "planned_stop": prem.get("planned_stop"), "target_1": prem.get("target_1"),
            "target_2": prem.get("target_2"), "unit_shares": (levels.get("unit") or {}).get("shares"),
            "underlying_stop": und.get("stop"), "underlying_t1": und.get("target"), "underlying_t2": und.get("target_2"),
            "greek_review": ({"entry_delta_per_unit": gr.get("net_delta_per_share"), "view": view, "review_when": gr.get("review_when")}
                             if gr.get("net_delta_per_share") is not None else None),
            "expiry_rule": "settle at intrinsic on the expiry date (services/desk_strategy_trades)",
            "expiry_flags": [f.get("code") for f in levels.get("flags") or []],
            "evaluation": f"on the whole structure's end-of-day marks by services/desk_strategy_trades.premium_plan ({EXITS_OWNER})"}


def compute_levels(underlying: str, reference: float, as_of: Optional[str], legs: Sequence[Dict[str, Any]],
                   refs: Dict[str, Any], today: date) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(strategy_levels answer, error) for a structure; one structure the engine cannot work out is reported, never
    dropped."""
    from services import strategy_levels

    try:
        return strategy_levels.compute(_levels_request(underlying, reference, as_of, legs), refs, today), None
    except Exception as exc:  # noqa: BLE001 — recorded on the plan as the reason, and logged
        logger.warning("trade_plan: levels for %s failed: %s: %s", underlying, type(exc).__name__, str(exc)[:200])
        return None, f"The levels could not be worked out ({type(exc).__name__})."


_DIRECTION_OF_VIEW = {"up": "bullish", "down": "bearish", "flat": "neutral"}


def structure_plan(*, underlying: str, reference: float, direction: str, family: str, label: Optional[str],
                   legs: Sequence[Dict[str, Any]], levels: Optional[Dict[str, Any]], levels_error: Optional[str],
                   as_of: Optional[str], data_as_of: Dict[str, Any], rules: Dict[str, Any], candidate_id: str,
                   status: str, reasons: Sequence[Dict[str, Any]], extra_rejections: Sequence[Dict[str, Any]] = (),
                   evidence_refs: Sequence[Dict[str, Any]] = (), risk_flags: Sequence[Dict[str, Any]] = (),
                   max_loss_rs: Optional[float] = None, capital_at_risk_rs: Optional[float] = None,
                   setup: Optional[Dict[str, Any]] = None, source: Optional[Dict[str, Any]] = None,
                   lineage: Optional[Dict[str, Any]] = None, underlying_stop: Optional[Dict[str, Any]] = None,
                   underlying_targets: Optional[Sequence[Dict[str, Any]]] = None, primary: str = "t1") -> Dict[str, Any]:
    """The TradePlan of an options structure: an F&O board idea, a plan builder's options candidate, or a roll. The
    stop a paper trade evaluates is the underlying's (stop.method "underlying", from the levels engine); the premium
    stop and T1 / T2 travel in exit_plan.options."""
    from services import desk_strategy_trades as strat
    from services import desk_trading as desk

    opt = options_exit(levels, as_of=as_of, error=levels_error)
    up = direction == "bullish"
    directional = direction in ("bullish", "bearish")
    # The underlying levels a paper trade of this structure records: the levels engine's (an F&O board idea, where the
    # row shows them), or the caller's (a plan builder candidate records its own invalidation and base level).
    if underlying_stop is not None:
        stop_u, stop_why = underlying_stop.get("price"), underlying_stop.get("rationale")
    else:
        stop_u, stop_why = opt.get("underlying_stop"), "the underlying price at which the whole structure is worth its planned premium stop (strategy_levels)"
    if underlying_targets is None:
        underlying_targets = [{"name": "t1", "price": opt.get("underlying_t1"),
                               "rule": "the underlying price at which the structure reaches its premium target 1 (strategy_levels)"},
                              {"name": "t2", "price": opt.get("underlying_t2"),
                               "rule": "the underlying price at which the structure reaches its premium target 2 (strategy_levels)"}]
    if not directional or (stop_u is not None and not ((stop_u < reference) if up else (stop_u > reference))):
        stop_u = None
    risk_u = abs(reference - stop_u) if stop_u is not None else None
    targets = []
    for lv in underlying_targets if directional else []:
        price = lv.get("price")
        if price is not None and ((price > reference) if up else (price < reference)):
            targets.append({"name": lv["name"], "price": r2(price),
                            "r_multiple": r_multiple(float(price), reference, risk_u, up) if risk_u else None,
                            "rule": lv.get("rule"), "primary": lv["name"] == primary})
    stop_b = {"price": r2(stop_u), "method": "underlying" if stop_u is not None else "premium",
              "premium_stop": opt.get("planned_stop"), "atr": None, "atr_multiple": None, "distance_atr": None,
              "swing_ref": None, "measured_from": r2(reference),
              "rationale": stop_why if stop_u is not None else "no underlying stop: the structure's premium stop and its max loss bound it",
              "invalidation": "the thesis is wrong if the underlying closes beyond this level"}
    clean = [{"kind": l.get("kind"), "side": l.get("side"), "lots": int(l.get("quantity") or l.get("lots") or 1),
              "lot_size": int(l.get("lot_size") or 1), "entry_price": r2(l.get("entry_price")), "expiry": l.get("expiry"),
              "strike": l.get("strike"), "option_type": l.get("option_type"), "price_source": l.get("price_source")}
             for l in legs]
    as_trade = {"legs": [{**l, "lots": l["lots"]} for l in clean], "cost_model": dict(desk.COST_MODEL)}
    try:
        breakdown = strat.strategy_cost_breakdown(as_trade, [l["entry_price"] for l in clean])
    except Exception as exc:  # noqa: BLE001 — a leg the card cannot price leaves the costs unknown, said so
        logger.warning("trade_plan: costs for %s failed: %r", underlying, exc)
        breakdown = None
    net = strat.net_premium(clean, [l["entry_price"] for l in clean])
    lot = clean[0]["lot_size"] if clean else None
    tp = {
        "schema": SCHEMA, "rules_version": RULES_VERSION, "strategy_rules_version": rules.get("board"),
        "calculation_version": rules.get("levels"),
        "strategy": {"segment": "options", "family": family, "label": label, "direction": direction, "candidate_id": candidate_id},
        "instrument": {"symbol": underlying, "segment": "options", "lot_size": lot,
                       "expiry": next((l["expiry"] for l in clean if l.get("expiry")), None), "legs": clean},
        "timeframe": {"horizon": "to expiry", "sessions_max": None},
        "setup": setup,
        "entry": {"price": None, "net_premium_rs": net, "order_type": "at_premium", "desk_entry_rule": "at_once",
                  "order_text": ORDER_TEXT["at_premium"], "valid_for_sessions": None, "reference_close": r2(reference),
                  "legs": [{"strike": l["strike"], "option_type": l["option_type"], "side": l["side"], "price": l["entry_price"]} for l in clean],
                  "logic": "Recorded at the legs' end-of-day premiums."},
        "stop": stop_b,
        "r_per_unit": r2(risk_u),
        "targets": targets,
        "size": {"status": "complete", "quantity": None, "lots": clean[0]["lots"] if clean else None, "lot_size": lot,
                 "risk_budget_rs": None, "risk_rs": r2(capital_at_risk_rs if capital_at_risk_rs is not None else (abs(max_loss_rs) if max_loss_rs is not None else None)),
                 "risk_pct_of_equity": None, "equity_basis": None, "binding": "the structure's lots",
                 "missing": ["capital (no equity basis on a board idea)"], "costs_included": capital_at_risk_rs is not None},
        "costs": {"model": dict(desk.COST_MODEL).get("version"), "basis": "every leg, entry and exit side, at the entry premiums",
                  "breakdown_round_trip_at_entry": breakdown, "excluded": ["exchange margin", "income tax"]},
        "exit_plan": _exit_plan(stop_b, targets, None, opt),
        "evidence_refs": list(evidence_refs),
        "risk_flags": list(risk_flags) + [{"code": f, "message": f} for f in opt.get("expiry_flags") or []],
        "eligibility": eligibility(status, reasons, conditional_entry=False, extra=extra_rejections),
        "data_as_of": data_as_of,
        "lineage": lineage,
        "sent_to_broker": False,
    }
    tp["source"] = source or {"kind": "regime_fit_board", "candidate_id": candidate_id}
    return finalize(tp)


def from_fno_idea(idea: Dict[str, Any], *, board_rules_version: Optional[str], refs: Dict[str, Any], today: date,
                  levels: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The TradePlan of one F&O board idea (POST /api/desk/strategy/top, regime_fit.ideas_for_underlying). `levels` is
    the strategy_levels answer when the caller already has it (the AI watchlist job); otherwise it is computed here
    with the same request and references the browser sends (ai_watchlist_build.payoff_request_for /
    levels_refs_for), so the board's levels and the plan's are one calculation."""
    direction = _DIRECTION_OF_VIEW.get(idea.get("view") or "")
    ref, legs = idea.get("reference_price"), idea.get("legs") or []
    if direction is None or ref is None or not legs:
        return None
    chain_day = (idea.get("data_as_of") or {}).get("chain")
    err = None
    if levels is None:
        levels, err = compute_levels(idea["underlying"], float(ref), chain_day, legs, refs, today)
    conflict = idea.get("conflicts_with_cash_setup")
    extra = ([{"code": "direction_conflict", "message": conflict.get("message")}] if conflict else [])
    cid = f"{idea['underlying']}:{idea.get('structure')}:{idea.get('expiry')}:" + "/".join(
        f"{l.get('side')}{l.get('strike')}{(l.get('option_type') or '')[:1]}" for l in legs)
    fit = idea.get("fit") or {}
    return structure_plan(
        underlying=idea["underlying"], reference=float(ref), direction=direction, family=idea.get("structure"),
        label=idea.get("name"), legs=legs, levels=levels, levels_error=err, as_of=chain_day,
        data_as_of={"chain": chain_day, "regime": (idea.get("data_as_of") or {}).get("regime")},
        rules={"board": board_rules_version, "levels": (levels or {}).get("version")}, candidate_id=cid,
        status="candidate", reasons=[], extra_rejections=extra,
        evidence_refs=[{"key": "regime_fit_board", "source": "POST /api/desk/strategy/top", "as_of": chain_day,
                        "content_hash": None, "fit_score": fit.get("score")},
                       {"key": "option_chain", "source": idea.get("price_source"), "as_of": chain_day, "content_hash": None}],
        risk_flags=([{"code": "conflicts_with_cash_setup", "message": conflict.get("message")}] if conflict else []),
        max_loss_rs=idea.get("max_loss"), capital_at_risk_rs=idea.get("capital_at_risk"),
        setup={"source": "regime_fit_board", "fit_score": fit.get("score"), "view": idea.get("view"),
               "expiry": idea.get("expiry"), "days_to_expiry": idea.get("days_to_expiry")})


def from_plan(plan: Dict[str, Any], today: date) -> Dict[str, Dict[str, Any]]:
    """{candidate id: TradePlan} for every candidate of a StrategyPlan that has levels: cash and futures through
    `linear_plan`, options and combinations through `structure_plan` (the levels engine on the candidate's legs)."""
    out: Dict[str, Dict[str, Any]] = {}
    und = plan.get("underlying") or {}
    for c in plan.get("candidates") or []:
        try:
            if c.get("segment") in ("cash", "futures"):
                tp = linear_plan(plan, c)
            elif c.get("legs") and und.get("spot") is not None and c.get("direction") in ("bullish", "bearish", "neutral"):
                fno_day = (plan.get("data_as_of") or {}).get("fno")
                levels, err = compute_levels(und["symbol"], float(und["spot"]), fno_day, c["legs"],
                                             {"put_wall": None, "call_wall": None, "expected_move": None}, today)
                tp = structure_plan(
                    underlying=und["symbol"], reference=float(und["spot"]), direction=c["direction"], family=c["family"],
                    label=c.get("label"), legs=c["legs"], levels=levels, levels_error=err, as_of=fno_day,
                    data_as_of=plan.get("data_as_of") or {}, rules={"board": plan.get("rules_version"), "levels": (levels or {}).get("version")},
                    candidate_id=c["id"], status=c.get("status"), reasons=c.get("reasons") or [],
                    evidence_refs=_snapshot_refs(plan, ("chain", "buildup", "futures", "indicators", "regime")),
                    risk_flags=_risk_flags(c), max_loss_rs=((c.get("payoff") or {}).get("expiry") or {}).get("max_loss"),
                    capital_at_risk_rs=(c.get("payoff") or {}).get("capital_at_risk"),
                    source={"kind": "strategy_plan", "strategy_plan_id": plan.get("plan_id"), "candidate_id": c["id"]},
                    # what the Builder shows and records for this structure (plan-data.ts strategyPaperBody)
                    underlying_stop={"price": ((c.get("invalidation") or {}).get("technical") or {}).get("price"),
                                     "rationale": ((c.get("invalidation") or {}).get("technical") or {}).get("basis")},
                    underlying_targets=[{"name": t["name"], "price": t.get("price"), "rule": t.get("rule")} for t in c.get("targets") or []],
                    primary="base", setup=c.get("setup"))
            else:
                tp = None
        except Exception as exc:  # noqa: BLE001 — one candidate's plan failing must not lose the others; logged
            logger.warning("trade_plan: candidate %s of %s failed: %r", c.get("id"), und.get("symbol"), exc)
            tp = None
        if tp is not None:
            out[c["id"]] = tp
    return out


# ── identity, validation, versions ───────────────────────────────────────────
def content(tp: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in tp.items() if k not in NOT_HASHED}


def lineage_key(tp: Dict[str, Any]) -> str:
    """Plans that are versions of one another: the same instrument, segment, family, direction and setup day."""
    st, ins, d = tp.get("strategy") or {}, tp.get("instrument") or {}, tp.get("data_as_of") or {}
    day = (tp.get("setup") or {}).get("signal_date") or d.get("price") or d.get("chain") or d.get("fno")
    return "tl_" + _digest({"symbol": ins.get("symbol"), "segment": st.get("segment"), "family": st.get("family"),
                            "direction": st.get("direction"), "day": day})


def finalize(tp: Dict[str, Any]) -> Dict[str, Any]:
    """Set the content id, the lineage key and the proposed lifecycle."""
    tp["plan_id"] = "tp_" + _digest(content(tp))
    tp["lineage_key"] = lineage_key(tp)
    tp["lifecycle"] = {"status": "proposed", "state": tp["eligibility"]["state"],
                       "derived_from": "the linked paper trades, on read (GET /api/desk/trade-plans/{plan_id})"}
    return tp


def validate(tp: Dict[str, Any]) -> List[Dict[str, str]]:
    """Revalidation: the plan's own numbers must agree with each other. [] when they do."""
    out: List[Dict[str, str]] = []

    def bad(code: str, message: str) -> None:
        out.append({"code": code, "message": message})

    if tp.get("schema") != SCHEMA:
        bad("schema", f"schema {tp.get('schema')} is not {SCHEMA}")
    if tp.get("plan_id") != "tp_" + _digest(content(tp)):
        bad("plan_id_mismatch", "the plan id does not match its content")
    d = (tp.get("strategy") or {}).get("direction")
    up = d != "bearish"
    stop = (tp.get("stop") or {}).get("price")
    if (tp.get("stop") or {}).get("method") not in STOP_METHODS:
        bad("stop_method", "the stop's method is not recorded")
    if (tp.get("strategy") or {}).get("segment") in ("cash", "futures"):
        entry = (tp.get("entry") or {}).get("price")
        if entry is None or entry <= 0:
            bad("entry", "no entry price")
        elif stop is None or (stop >= entry if up else stop <= entry):
            bad("stop_side", "the stop is not on the loss side of the entry")
        else:
            risk = abs(entry - stop)
            for t in tp.get("targets") or []:
                if (t["price"] <= entry) if up else (t["price"] >= entry):
                    bad("target_side", f"target {t['name']} is not on the profit side of the entry")
                elif t.get("r_multiple") is None or abs(r_multiple(t["price"], entry, risk, up) - t["r_multiple"]) > 0.011:
                    bad("r_multiple", f"target {t['name']}'s R multiple does not match its price")
        sz = tp.get("size") or {}
        if sz.get("status") == "complete" and sz.get("risk_rs") is not None and sz.get("risk_budget_rs") is not None \
                and sz["risk_rs"] > sz["risk_budget_rs"] + 0.01:
            bad("risk_over_budget", "the sized risk exceeds the risk budget")
    else:
        legs = (tp.get("instrument") or {}).get("legs") or []
        if not legs or any((l.get("entry_price") or 0) <= 0 for l in legs):
            bad("legs", "a leg has no premium")
        ref = (tp.get("entry") or {}).get("reference_close")
        if stop is not None and ref is not None and d in ("bullish", "bearish") and (stop >= ref if up else stop <= ref):
            bad("stop_side", "the underlying stop is not on the loss side of the reference price")
    if not tp.get("data_as_of"):
        bad("data_as_of", "no data timestamps")
    return out


async def store(db, tp: Dict[str, Any], owner: str, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Insert the plan once (`_id` = plan_id) and add `owner` to who may read it. A new plan whose lineage already has a
    version is stored as the next version (`supersedes`, `revalidation`); a revalidation failure is stored as not
    eligible (REJECTED), so it can be read but not traded. Returns the stored document."""
    from pymongo.errors import DuplicateKeyError

    col = db[COLLECTION]
    pid = tp["plan_id"]
    for _ in range(3):
        have = await col.find_one({"_id": pid})
        if have is not None:
            if owner not in (have.get("owners") or []):
                await col.update_one({"_id": pid}, {"$addToSet": {"owners": owner}})
                have["owners"] = (have.get("owners") or []) + [owner]
            return have
        latest = (await col.find({"lineage_key": tp["lineage_key"]}).sort("version", -1).to_list(1)) or [None]
        prev = latest[0]
        problems = validate(tp)
        stamp = (now or utcnow()).isoformat()
        doc = {**tp, "_id": pid, "version": (int(prev.get("version") or 1) + 1) if prev else 1,
               "supersedes": prev["plan_id"] if prev else None, "owners": [owner], "created_at": stamp,
               "revalidation": {"ok": not problems, "problems": problems, "at": stamp,
                                "after_approval": bool(prev) and await _approved(db, prev["plan_id"])},
               "events": []}
        if problems:
            doc["eligibility"] = eligibility(tp["eligibility"].get("status") or "no_trade", tp["eligibility"].get("reasons") or [],
                                             conditional_entry=False, extra=[{"code": "revalidation_failed",
                                                                              "message": "; ".join(p["message"] for p in problems)}])
            doc["lifecycle"] = {**doc["lifecycle"], "state": lc.REJECTED}
        try:
            await col.insert_one(doc)
            return doc
        except DuplicateKeyError:
            continue                      # another request stored it (or this version number) first: read again
    raise RuntimeError(f"trade plan {pid} could not be stored")


async def _approved(db, plan_id: str) -> bool:
    from services import desk_trading as desk

    return await db[desk.TRADES].count_documents({"trade_plan_id": plan_id}) > 0


async def store_many(db, plans: Sequence[Dict[str, Any]], owner: str) -> None:
    """Store each plan; one that cannot be stored is marked `stored: false` with the reason (and logged), so the
    surface still answers and the paper-trade route later says the plan is unknown instead of guessing."""
    import asyncio

    async def one(tp: Dict[str, Any]) -> None:
        try:
            doc = await store(db, tp, owner)
            tp["version"], tp["supersedes"], tp["stored"] = doc.get("version"), doc.get("supersedes"), True
            if doc.get("eligibility") != tp.get("eligibility"):
                tp["eligibility"], tp["lifecycle"] = doc["eligibility"], doc.get("lifecycle", tp["lifecycle"])
        except Exception as exc:  # noqa: BLE001 — reported on the plan and logged
            logger.warning("trade_plan: storing %s failed: %r", tp.get("plan_id"), exc)
            tp["stored"], tp["store_error"] = False, f"{type(exc).__name__}"
    await asyncio.gather(*(one(tp) for tp in plans))


async def load(db, plan_id: str, owner: str) -> Optional[Dict[str, Any]]:
    """The plan if `owner` may read it (they built it or it was built by a system job), else None."""
    if not isinstance(plan_id, str) or not plan_id.startswith("tp_") or len(plan_id) > 40:
        return None
    doc = await db[COLLECTION].find_one({"_id": plan_id})
    if doc is None:
        return None
    owners = doc.get("owners") or []
    if owner in owners or any(str(o).startswith("system:") for o in owners):
        return doc
    return None


# ── what a paper trade must carry ────────────────────────────────────────────
def canonical_levels(tp: Dict[str, Any]) -> Dict[str, Any]:
    """The levels every surface shows for this plan: {plan_id, entry, order_type, stop, stop_method, targets}."""
    return {"plan_id": tp["plan_id"], "entry": (tp.get("entry") or {}).get("price"),
            "entry_legs": (tp.get("entry") or {}).get("legs"),
            "order_type": (tp.get("entry") or {}).get("order_type"), "stop": (tp.get("stop") or {}).get("price"),
            "stop_method": (tp.get("stop") or {}).get("method"),
            "targets": [{"name": t["name"], "price": t["price"], "r_multiple": t["r_multiple"]} for t in tp.get("targets") or []]}


def cash_mismatches(tp: Dict[str, Any], doc: Dict[str, Any]) -> List[str]:
    """Where a cash paper trade's levels differ from its plan's. [] when they are the plan's."""
    out: List[str] = []
    prim = primary_target(tp)
    want = {"symbol": (tp.get("instrument") or {}).get("symbol"), "entry_price": (tp.get("entry") or {}).get("price"),
            "stop_price": (tp.get("stop") or {}).get("price"), "target_price": prim["price"] if prim else None,
            "entry_rule": (tp.get("entry") or {}).get("desk_entry_rule")}
    for k, v in want.items():
        got = doc.get(k)
        if isinstance(v, float) or isinstance(got, float):
            same = v is not None and got is not None and abs(float(v) - float(got)) < 0.005
        else:
            same = v == got
        if not same:
            out.append(f"{k}: the plan has {v}, the request {got}")
    if (tp.get("strategy") or {}).get("segment") != "cash":
        out.append("segment: the plan is not a cash plan")
    return out


def strategy_mismatches(tp: Dict[str, Any], doc: Dict[str, Any]) -> List[str]:
    """Where a strategy paper trade differs from its plan: underlying, direction, family, every leg (side, strike,
    type, expiry, lots, lot size, premium) and the underlying stop / target 1."""
    out: List[str] = []
    ins = tp.get("instrument") or {}
    if ins.get("symbol") != doc.get("underlying"):
        out.append(f"underlying: the plan has {ins.get('symbol')}, the request {doc.get('underlying')}")
    for k, plan_v in (("direction", (tp.get("strategy") or {}).get("direction")), ("family", (tp.get("strategy") or {}).get("family"))):
        if plan_v != doc.get(k) and not (k == "family" and doc.get(k) == "custom"):
            out.append(f"{k}: the plan has {plan_v}, the request {doc.get(k)}")

    def key(l: Dict[str, Any]) -> Tuple:
        return (l.get("side"), None if l.get("strike") is None else float(l["strike"]), l.get("option_type"), l.get("expiry"),
                int(l.get("lots") or 0), int(l.get("lot_size") or 0), round(float(l.get("entry_price") or 0), 2))
    if sorted(map(key, ins.get("legs") or [])) != sorted(map(key, doc.get("legs") or [])):
        out.append("legs: the request's legs are not the plan's")
    prim = primary_target(tp)
    for k, v in (("stop_underlying", (tp.get("stop") or {}).get("price") if (tp.get("stop") or {}).get("method") == "underlying" else None),
                 ("target_underlying", prim["price"] if prim else None)):
        got = doc.get(k)
        if (v is None) != (got is None) or (v is not None and abs(float(v) - float(got)) >= 0.005):
            out.append(f"{k}: the plan has {v}, the request {got}")
    return out


def plan_ref_of(tp: Dict[str, Any]) -> Dict[str, Any]:
    """What a trade records about its plan."""
    return {"plan_id": tp["plan_id"], "candidate_id": (tp.get("strategy") or {}).get("candidate_id"),
            "rules_version": tp.get("rules_version"), "version": tp.get("version"), "data_as_of": tp.get("data_as_of")}
