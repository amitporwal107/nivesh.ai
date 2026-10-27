"""Candidate generation for the Strategy Builder (PRD §16.4, §16.5, §16.7, §17.5). Deterministic and pure.

Rules are versioned (rules.STRATEGY_RULES_VERSION) and their constants live in rules.RULES. Every candidate gets its exact
legs, runs through `compute_payoff` (never a second payoff calculation here), and is sized from the user's risk budget.

The options rules start from the Options & Futures Lab's browser rules and are ported so the server and the browser agree:
    frontend-v5/src/pages/CopilotApp/screens/tradingdesk/FnoStrategies.tsx
        strategyNames  (rule 1: build-up -> strategy names)       -> FAMILY_BY_DIRECTION / build-up gate below
        levelsFrom     (rule 2: stop and target from the walls)   -> levels_from
        spreadStrike   (rule 3: short strike at the wall or the edge of the expected move) -> spread_strike
        iron condor    (spot strictly between the walls, each wall at least one expected move away) -> condor_ok
The UI rules stay until the Strategy Builder screen replaces them.

Candidate status: candidate (viable) | wait | no_trade | insufficient_data | avoid. `reasons` lists {code, message}.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from services import desk_cost_card
from services import desk_trading as desk_costs
from services.option_pricing import RISK_FREE_RATE
from services.positional_engine import setup_rules

from .engine import compute_payoff
from .evidence import day10, events_in_horizon, num, snap
from .rules import RULES

SEGMENTS = ("cash", "futures", "options", "combination")


def r2(x: Any) -> Optional[float]:
    return None if x is None else round(float(x), 2)


def reason(code: str, message: str, **extra: Any) -> Dict[str, Any]:
    return {"code": code, "message": message, **extra}


# ── levels ───────────────────────────────────────────────────────────────────

def levels_from(entry: float, up: bool, put_wall: Optional[float], call_wall: Optional[float], move: Optional[float]) -> Dict[str, Any]:
    """FnoStrategies.tsx levelsFrom (rule 2): a long idea stops at the put wall and aims at the call wall (a short one the
    other way round); a wall on the wrong side of the price is replaced by the edge of the expected move."""
    below, above = (put_wall, call_wall) if up else (call_wall, put_wall)
    stop_ok = below is not None and ((below < entry) if up else (below > entry))
    target_ok = above is not None and ((above > entry) if up else (above < entry))
    stop = below if stop_ok else (entry - move if up else entry + move) if move is not None else None
    target = above if target_ok else (entry + move if up else entry - move) if move is not None else None
    return {"stop": stop if stop is not None and stop > 0 else None, "target": target if target is not None and target > 0 else None,
            "stop_from": ("the put wall" if up else "the call wall") if stop_ok else "the edge of the expected move",
            "target_from": ("the call wall" if up else "the put wall") if target_ok else "the edge of the expected move"}


def scenario_levels(entry: float, up: bool, stop: float, atr: Optional[float], near_level: Optional[float],
                    base_override: Optional[float] = None) -> List[Dict[str, Any]]:
    """Conservative / base / optimistic underlying levels from documented rules (rules.RULES['targets']). Scenarios, not forecasts.

    conservative  the nearest 20-session resistance (support for a short) at least min_resistance_atr x ATR beyond the entry and
                  nearer than the base level; else entry +/- 1 x ATR (when nearer than the base level); else the base level.
    base          the wall / expected-move target (FnoStrategies rule 2) when it is on the right side, else entry +/- 2 x the stop distance.
    optimistic    entry +/- 3 x the stop distance (never nearer than the base).
    `gate` marks the level the reward : risk gate reads: the conservative level when a real resistance caps the move, else the base."""
    T, sg = RULES["targets"], (1 if up else -1)
    risk = abs(entry - stop)
    use_override = base_override is not None and (base_override - entry) * sg > 0
    base = base_override if use_override else entry + sg * T["base_reward_multiple"] * risk
    base_rule = "the wall / expected-move target (FnoStrategies rule 2)" if use_override else f"{T['base_reward_multiple']:g} x the stop distance"
    d_base = abs(base - entry)
    near_ok = (near_level is not None and (near_level - entry) * sg > 0
               and abs(near_level - entry) >= T["min_resistance_atr"] * (atr or 0.0) and abs(near_level - entry) < d_base)
    atr_lvl = entry + sg * T["conservative_atr_multiple"] * atr if atr else None
    if near_ok:
        cons, cons_rule, gate_cons = near_level, "the nearest 20-session " + ("resistance" if up else "support"), True
    elif atr_lvl is not None and abs(atr_lvl - entry) < d_base:
        cons, cons_rule, gate_cons = atr_lvl, f"{T['conservative_atr_multiple']:g} x ATR(14) (no resistance at least {T['min_resistance_atr']:g} x ATR away)", False
    else:
        cons, cons_rule, gate_cons = base, "the base level (nothing nearer)", False
    opt_price = entry + sg * T["optimistic_reward_multiple"] * risk
    if abs(opt_price - entry) < d_base:
        opt_price = base
    return [{"name": "conservative", "price": r2(cons), "rule": cons_rule, "gate": gate_cons},
            {"name": "base", "price": r2(base), "rule": base_rule, "gate": not gate_cons},
            {"name": "optimistic", "price": r2(opt_price), "rule": f"{T['optimistic_reward_multiple']:g} x the stop distance", "gate": False}]


# ── sizing (PRD §16.5) ───────────────────────────────────────────────────────

def _cost_model(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """The plan's cost inputs as a desk cost-model snapshot (services/desk_trading.COST_MODEL, the desk cost card): the
    request's `costs` (slippage_pct, brokerage_per_side) where given, the card for the rest, statutory charges always.
    So the plan sizes with the costs a paper trade of it records. (The payoff engine's own net figures, payoff.py, still
    charge slippage and brokerage only: a separate change, said in the PR.)"""
    c = inputs.get("costs") or {}
    model = dict(desk_costs.COST_MODEL)
    if c.get("slippage_pct") is not None:
        model["slippage_pct_per_side"] = c["slippage_pct"]
    if c.get("brokerage_per_side") is not None:
        model["brokerage_rs_per_side"] = c["brokerage_per_side"]
    return model


def size_position(inputs: Dict[str, Any], *, risk_per_unit: Optional[float], value_per_unit: Optional[float], unit: str,
                  lot_units: int = 1, per_unit_label: str,
                  cost_at_stop: Optional[Callable[[int], float]] = None) -> Dict[str, Any]:
    """units = the most whole lots whose loss at the stop after costs fits the risk budget, capped by
    floor(capital x max allocation % / (value per unit x lot units)). Incomplete, with the formula and the missing inputs,
    when any input is missing. Never a guessed quantity.

    `cost_at_stop(units)` is the estimated round-trip cost at the stop of a linear position (cash, futures), from the
    pricing function the paper trade books with (services/desk_trading.round_trip_cost, the desk cost card); the lots
    are found exactly against it (services/desk_cost_card.max_lots_within). Sizing on the gross stop distance alone let
    the loss after costs exceed the budget (PRD Example A: 85 shares, ₹3,098.94 against ₹3,000). None when
    `risk_per_unit` is already a net figure (an option structure's worst loss including costs)."""
    budget, capital = inputs.get("risk_budget_inr"), inputs.get("capital")
    if budget is None and inputs.get("risk_pct") is not None and capital:
        budget = capital * inputs["risk_pct"] / 100.0
    alloc = inputs["max_allocation_pct"]
    out: Dict[str, Any] = {"status": "incomplete", "unit": unit, "formula": RULES["sizing"]["formula"],
                           "risk_budget_inr": budget, "capital_inr": capital, "max_allocation_pct": alloc,
                           "risk_per_unit": r2(risk_per_unit), "risk_basis": per_unit_label, "value_per_unit": r2(value_per_unit),
                           "lot_units": lot_units, "missing": [], "quantity": None}
    if budget is None:
        out["missing"].append("risk_budget_inr (or risk_pct together with capital)")
    if not capital:
        out["missing"].append("capital")
    if risk_per_unit is None or risk_per_unit <= 0:
        out["missing"].append("risk per unit (a stop distance or a defined max loss)")
    if value_per_unit is None or value_per_unit <= 0:
        out["missing"].append("value per unit")
    if out["missing"]:
        return out
    if cost_at_stop is not None:
        by_risk = desk_cost_card.max_lots_within(budget, risk_per_unit, lot_units, cost_at_stop)
    else:
        by_risk = math.floor(budget / (risk_per_unit * lot_units))
    by_cap = math.floor(capital * alloc / 100.0 / (value_per_unit * lot_units))
    n = max(0, min(by_risk, by_cap))
    out.update(status="complete" if n >= 1 else "too_small", quantity=n, units=n * lot_units, by_risk_budget=by_risk, by_allocation_cap=by_cap,
               binding="risk_budget" if by_risk <= by_cap else "allocation_cap",
               risk_at_stop_inr=r2(n * lot_units * risk_per_unit), deployed_inr=r2(n * lot_units * value_per_unit),
               costs_included=cost_at_stop is not None)
    if cost_at_stop is not None:
        costs = cost_at_stop(n * lot_units) if n >= 1 else 0.0
        out.update(costs_at_stop_inr=r2(costs), risk_at_stop_net_inr=r2(n * lot_units * risk_per_unit + costs))
    if n < 1:
        out["reason"] = "The risk budget or the allocation cap buys less than one share/lot."
    return out


# ── payoff glue ──────────────────────────────────────────────────────────────

def run_payoff(ctx: Dict[str, Any], underlying_ref: float, legs: List[Dict[str, Any]], scenarios: List[Dict[str, Any]],
               as_of: Optional[str], pre_expiry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"underlying": ctx["symbol"], "reference_price": underlying_ref, "legs": legs,
                            "grid": {"from_pct": -25, "to_pct": 25, "points": 121},
                            "scenarios": [{"name": s["name"], "underlying_price": s["price"]} for s in scenarios if s.get("price")]}
    if ctx["inputs"].get("costs"):
        body["costs"] = ctx["inputs"]["costs"]
    if as_of:
        body["as_of"] = as_of
    if pre_expiry:
        body["pre_expiry"] = pre_expiry
    return compute_payoff(body, ctx["today"])


def _gate(levels: List[Dict[str, Any]]) -> str:
    return next((l["name"] for l in levels if l.get("gate")), "base")


def _scn(res: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    if not res.get("valid"):
        return None
    return next((s for s in res["expiry"]["scenarios"] if s["name"] == name), None)


def reward_risk(res: Dict[str, Any], linear: bool, gate: str = "base") -> Dict[str, Any]:
    """Reward : risk gross and net at the gate level. Reward = P&L at that scenario level; risk = the loss at the stop scenario
    (cash and futures) or the position's max loss (defined-risk options). Expiry payoff, costs per the payoff calculation."""
    stop = _scn(res, "stop")
    empty = {"gross": None, "net": None, "level": gate, "reward_gross": None, "reward_net": None, "risk_gross": None, "risk_net": None, "by_level": {}}
    if not res.get("valid") or _scn(res, gate) is None:
        return empty
    if linear:
        rg, rn = (-stop["gross"], -stop["net"]) if stop else (None, None)
    else:
        rn = res.get("capital_at_risk")
        ml = res["expiry"].get("max_loss")
        rg = -ml if ml is not None else None

    def ratio(a: Optional[float], b: Optional[float]) -> Optional[float]:
        return round(a / b, 2) if a is not None and b is not None and b > 0 else None
    by = {n: {"gross": ratio(_scn(res, n)["gross"], rg), "net": ratio(_scn(res, n)["net"], rn)} for n in ("conservative", "base", "optimistic") if _scn(res, n)}
    g = _scn(res, gate)
    return {"gross": ratio(g["gross"], rg), "net": ratio(g["net"], rn), "level": gate, "reward_gross": g["gross"], "reward_net": g["net"],
            "risk_gross": r2(rg), "risk_net": r2(rn), "by_level": by,
            "basis": f"reward = P&L at the {gate} scenario level; risk = loss at the stop (cash, futures) or the max loss (options); expiry payoff; "
                     "the gate uses the net ratio when costs are known"}


def apply_rr_gate(c: Dict[str, Any], inputs: Dict[str, Any]) -> None:
    rr = c["risk_reward"]
    got = rr.get("net") if rr.get("net") is not None else rr.get("gross")
    lvl = rr.get("level")
    if got is None:
        c["status"] = "insufficient_data"
        c["reasons"].append(reason("risk_not_calculable", "Reward : risk could not be calculated (no valid payoff, stop or conservative level)."))
    elif got < inputs["min_reward_risk"]:
        c["status"] = "no_trade"
        c["reasons"].append(reason("reward_risk_below_minimum", f"Reward : risk {got:g} at the {lvl} level is below the minimum {inputs['min_reward_risk']:g}"
                                   + (" (the default, change it in the inputs)." if "min_reward_risk" in inputs["defaults_applied"] else "."), reward_risk=got,
                                   minimum=inputs["min_reward_risk"]))


def base_candidate(segment: str, family: str, label: str, direction: str) -> Dict[str, Any]:
    return {"id": f"{segment}:{family}", "segment": segment, "family": family, "label": label, "direction": direction,
            "status": "candidate", "reasons": [], "why_qualifies": [], "conflicts": [], "missing": [], "legs": [], "entry": None,
            "invalidation": None, "targets": [], "risk_reward": {"gross": None, "net": None}, "sizing": None, "payoff": None,
            "options_selection": None, "warnings": [], "actionable": False, "sent_to_broker": False}


def not_viable(segment: str, family: str, label: str, direction: str, status: str, *reasons: Dict[str, Any]) -> Dict[str, Any]:
    c = base_candidate(segment, family, label, direction)
    c["status"] = status
    c["reasons"] = list(reasons)
    return c


# ── cash ─────────────────────────────────────────────────────────────────────

def cash_candidates(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    d = ctx["direction"]
    if d == "bearish":
        return [not_viable("cash", "avoid", "Avoid / bearish watch", d, "avoid",
                           reason("long_only", "Cash plans are long only in this release (short cash needs a valid instrument and workflow). The bearish view is recorded as avoid / watch; no cash entry."))]
    if d != "bullish":
        return [not_viable("cash", "none", "No cash strategy", d, "no_trade",
                           reason("no_cash_strategy", f"A {d} view has no cash-equity strategy (cash is long only)."))]
    sb = snap(ctx["snaps"], "scanner_bucket")
    if not sb["ok"]:
        return [not_viable("cash", "scanner", "Cash plan", d, "insufficient_data",
                           reason("scanner_unavailable", f"The scanner's setup for this stock could not be read: {sb['error']}"))]
    bucket, it = (sb["data"] or {}).get("bucket"), (sb["data"] or {}).get("item") or {}
    stage_note = None
    if bucket is None and (sb["data"] or {}).get("pick_stage"):
        # A scanner pick that is not in the watchlist has no bucket; its stage says where it stands (the desk's own mapping:
        # BREAKOUT is confirmed, EARLY_BREAKOUT is awaiting, anything else is forming). The bucket is not invented: the note says so.
        st = str(sb["data"]["pick_stage"]).upper()
        bucket = {"BREAKOUT": "breakout_confirmed", "EARLY_BREAKOUT": "pre_breakout"}.get(st, "true_accumulation")
        stage_note = f"The stock is a scanner pick (stage {st}) that is not in the watchlist buckets; its stage is read as {bucket.replace('_', ' ')}."
    if bucket is None:
        bull = chartink_bullish_hits(ctx)
        if bull:
            return [chartink_cash_candidate(ctx, bull)]
    if bucket is None:
        return [not_viable("cash", "scanner", "Cash plan", d, "no_trade",
                           reason("no_setup", "The scanner lists the stock in none of its buckets (breakout confirmed, pre-breakout, true accumulation, trend continuation): no cash setup."))]
    sbd = sb["data"] or {}
    pick = sbd.get("pick") or {}
    spot, atr = ctx["spot"], ctx["atr"]
    setup = setup_view(sbd, bucket, it, ctx)
    if bucket in ("pre_breakout", "true_accumulation"):
        # The setup has not triggered: the plan is the trade AT the trigger, waiting for it (WAIT_FOR_CONFIRMATION). The
        # trigger is the scanner pick's entry when there is one (its stop was set from that entry), else the bucket's level.
        trig = num(pick.get("entry_price")) or num(it.get("trigger_price"))
        waiting = reason("setup_not_triggered", f"The scanner bucket is {bucket.replace('_', ' ')}: the setup has not triggered.")
        stop = num(it.get("stop_price"))
        logic = (f"Wait for a close above {trig:g} on volume at least {RULES['rvol_confirm']:g}x average." if trig else "Wait for a close above resistance on rising volume.")
        if trig is None or stop is None or stop <= 0 or stop >= trig:
            c = not_viable("cash", "breakout_watch", "Wait for breakout confirmation", d, "wait", waiting)
            c["entry"] = {"trigger": trig, "logic": logic, "zone": None}
            c["setup"] = setup
            return [c]
        meta = scanner_stop_meta(sbd, bucket, it, trig, stop, atr)
        order = order_type_for_setup(trig, spot, bucket, pick.get("stage"))
        c = linear_candidate(ctx, "cash", "breakout_watch", "Wait for breakout confirmation", True, trig, stop, stop_basis_text(meta, stop, "the scanner's stop"),
                             None, logic, unit_kind="cash", lot=1, expiry=None, price_source="the scanner's trigger (not yet traded)",
                             why=[f"Scanner bucket {bucket.replace('_', ' ')} (rules {ctx.get('scan_rules_version')}).", f"Trigger {trig:g}."]
                             + ([stage_note] if stage_note else []), stop_meta=meta, order_type=order, setup=setup, logic_exact=True)
        if c["status"] == "candidate":
            c["status"] = "wait"
            c["reasons"].append(waiting)
        return [c]
    family = "breakout_continuation" if bucket == "breakout_confirmed" else "pullback_in_uptrend"
    label = "Breakout continuation (long)" if family == "breakout_continuation" else "Pullback in an uptrend (long)"
    if spot is None:
        return [not_viable("cash", family, label, d, "insufficient_data", reason("no_price", "No last close: the entry cannot be set."))]
    stop = num(it.get("stop_price"))
    meta = scanner_stop_meta(sbd, bucket, it, spot, stop, atr) if stop is not None else None
    stop_basis = stop_basis_text(meta, stop, "the scanner's stop") if meta else None
    if stop is None or stop <= 0 or stop >= spot:
        hyp = ctx["hyp"]
        stop = num(hyp.get("stop")) if hyp else None
        meta = chart_stop_meta(hyp, spot, atr)
        stop_basis = "the chart engine's ATR stop (2 x ATR(14), or 20-session support when closer but at least 0.5 ATR away)"
        if stop is None or stop >= spot:
            return [not_viable("cash", family, label, d, "insufficient_data", reason("risk_not_calculable", "No stop below the price could be derived (scanner stop and ATR stop are both missing)."))]
    return [linear_candidate(ctx, "cash", family, label, True, spot, stop, stop_basis, None, f"Last close {spot:g} ({ctx['spot_source']})",
                             unit_kind="cash", lot=1, expiry=None, price_source=ctx["spot_source"],
                             why=[f"Scanner bucket {bucket.replace('_', ' ')} (rules {ctx.get('scan_rules_version')}).",
                                  f"Trigger / reference level {num(it.get('trigger_price'))}."] + ([stage_note] if stage_note else []) if it else [],
                             stop_meta=meta, order_type="at_close", setup=setup)]


# ── the setup source and the stop's method (N13) ─────────────────────────────
# The AI scanner is the SETUP SOURCE: it says which setup it saw (bucket, stage, trigger) and where its stop sits and
# by which rule. The plan turns that into levels; the method travels as data so no label is ever guessed (the plan
# used to call the scanner's 1.5 x ATR stop "2 x ATR").
_BUCKET_REF = {"breakout_confirmed": ("trigger_price", "the breakout level"), "pre_breakout": ("trigger_price", "the breakout level"),
               "true_accumulation": ("close_price", "the close"), "trend_continuation": ("ema_20", "the 20-day EMA")}


def order_type_for_setup(entry: float, close: Optional[float], bucket: Optional[str], stage: Optional[str]) -> str:
    from .trade_plan import order_type_for
    return order_type_for(entry, close, bucket=bucket, stage=stage)


def setup_view(sbd: Dict[str, Any], bucket: Optional[str], it: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    pick = sbd.get("pick") or {}
    return {"source": "ai_scanner", "bucket": bucket, "stage": pick.get("stage") or it.get("stage"), "signal_date": pick.get("signal_date"),
            "trigger": num(pick.get("entry_price")) or num(it.get("trigger_price")), "scanner_stop": num(it.get("stop_price")),
            "scanner_target": num(pick.get("target_price")), "rules_version": ctx.get("scan_rules_version"),
            "timeframe_days": [pick.get("timeframe_days_min"), pick.get("timeframe_days_max")] if pick.get("timeframe_days_max") else None}


def scanner_stop_meta(sbd: Dict[str, Any], bucket: Optional[str], it: Dict[str, Any], entry: float, stop: float,
                      atr: Optional[float]) -> Dict[str, Any]:
    """How the scanner set this stop. A pick's stop: trade_planner.stop_meta on the pick's own entry, stop, ATR and
    swing low. A watchlist row's stop: the bucket's reference level minus 1.5 x ATR (routes/positional get_watchlist),
    with the ATR it implies. `distance_atr` is the distance from THIS plan's entry."""
    from services.positional_engine import setup_rules, trade_planner

    pick = sbd.get("pick") or {}
    p_entry, p_stop = num(pick.get("entry_price")), num(pick.get("stoploss"))
    if p_entry and p_stop and abs(p_stop - stop) < 0.005:
        m = dict(trade_planner.stop_meta(p_entry, p_stop, num(pick.get("atr_14")), num(pick.get("swing_low_20"))))
        m["measured_from"] = p_entry
        a = m.get("atr") or atr
    else:
        mult = setup_rules.WATCHLIST["stop_atr_multiple"]
        key, name = _BUCKET_REF.get(bucket or "", ("trigger_price", "the trigger"))
        ref = num(it.get(key))
        a = (ref - stop) / mult if ref is not None and ref > stop else None
        m = {"method": "atr" if a else "unknown", "atr_multiple": mult if a else None, "atr": r2(a), "swing_ref": None,
             "measured_from": ref, "measured_from_name": name,
             "rule": f"{name} minus {mult:g} x ATR(14) (the scanner's {bucket or 'watchlist'} rule; the ATR is the one the stop implies)"}
    m["distance_atr"] = round((entry - stop) / a, 3) if a else None
    return m


def chart_stop_meta(hyp: Optional[Dict[str, Any]], entry: Optional[float], atr: Optional[float]) -> Dict[str, Any]:
    """The chart engine's hypothetical stop (routes/research_chart ATR_2X_STOP): 2 x ATR(14), or the 20-session support."""
    hyp = hyp or {}
    structural = hyp.get("stop_basis") == "support20"
    stop = num(hyp.get("stop"))
    mult = ((hyp.get("constants") or {}).get("atr_multiple")) or 2.0
    return {"method": "structural" if structural else "atr", "atr_multiple": None if structural else mult, "atr": r2(atr),
            "swing_ref": stop if structural else None, "measured_from": entry,
            "distance_atr": round((entry - stop) / atr, 3) if atr and entry is not None and stop is not None else None,
            "rule": f"the chart engine's {hyp.get('rule') or 'ATR_2X_STOP'} rule: {mult:g} x ATR(14) below the close, or the 20-session support when closer but at least 0.5 ATR away"}


def stop_basis_text(meta: Optional[Dict[str, Any]], stop: Optional[float], who: str) -> str:
    """The stop's rationale in words, written FROM the method data (never a fixed label)."""
    if not meta or stop is None:
        return f"{who}"
    if meta.get("method") == "atr" and meta.get("atr_multiple"):
        frm = meta.get("measured_from")
        return (f"{who} ({stop:g}): {meta['atr_multiple']:g} x ATR(14) below {frm:g}" + (f" (ATR {meta['atr']:g})" if meta.get("atr") else "")
                if frm is not None else f"{who} ({stop:g}): {meta['atr_multiple']:g} x ATR(14)")
    if meta.get("method") == "structural" and meta.get("swing_ref") is not None:
        return f"{who} ({stop:g}): just under the 20-session swing low / support {meta['swing_ref']:g}"
    return f"{who} ({stop:g}): the rule that set it could not be identified from the stored figures"


def chartink_bullish_hits(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The enabled bullish Chartink scans that listed the stock (empty when Chartink is off, unavailable or did not list it)."""
    ck = snap(ctx["snaps"], "chartink")
    return [h for h in ((ck["data"] or {}).get("hits") or []) if h.get("direction") == "bullish"] if ck["ok"] else []


def chartink_cash_candidate(ctx: Dict[str, Any], hits: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A cash candidate for a stock the AI scanner lists in no bucket but an enabled bullish Chartink scan listed. The levels come from the chart engine's
    ATR rule (ATR_2X_STOP), as for any stock without a scanner pick; the scan is the user's own and is not validated. The plan gates still decide the status."""
    C = RULES["chartink"]
    d, spot, hyp = ctx["direction"], ctx["spot"], ctx["hyp"]
    family, label = C["cash_family"], "Chartink screen signal (long)"
    if spot is None:
        return not_viable("cash", family, label, d, "insufficient_data", reason("no_price", "No last close: the entry cannot be set."))
    stop = num(hyp.get("stop")) if hyp else None
    if stop is None or stop <= 0 or stop >= spot:
        return not_viable("cash", family, label, d, "insufficient_data", reason("risk_not_calculable", "No stop below the price could be derived (the ATR rule needs 15 usable sessions)."))
    ck = snap(ctx["snaps"], "chartink")["data"] or {}
    rule = f"{hyp.get('rule')} v{hyp.get('version')}" if hyp.get("rule") else "ATR_2X_STOP"
    stop_basis = f"the chart engine's ATR stop (rule {rule}: 2 x ATR(14), or 20-session support when closer but at least 0.5 ATR away); {C['levels_label']}"
    names = ", ".join(str(h.get("name")) for h in hits)
    c = linear_candidate(ctx, "cash", family, label, True, spot, stop, stop_basis, None, f"Last close {spot:g} ({ctx['spot_source']})",
                         unit_kind="cash", lot=1, expiry=None, price_source=ctx["spot_source"],
                         why=[f"Listed by {len(hits)} enabled bullish Chartink scan(s): {names} (fetched {ck.get('fetched_at')}).",
                              "The AI scanner lists the stock in none of its buckets; the entry is the last close and the levels follow the ATR rule."],
                         stop_meta=chart_stop_meta(hyp, spot, ctx["atr"]), order_type="at_close",
                         setup={"source": "chartink", "bucket": None, "stage": None, "signal_date": None, "trigger": None,
                                "scans": [h.get("name") for h in hits], "fetched_at": ck.get("fetched_at")})
    c["warnings"].append(C["levels_label"][0].upper() + C["levels_label"][1:] + ".")
    return c


def linear_candidate(ctx: Dict[str, Any], segment: str, family: str, label: str, up: bool, entry: float, stop: float, stop_basis: str,
                     base_override: Optional[float], entry_note: str, *, unit_kind: str, lot: int, expiry: Optional[str],
                     price_source: Optional[str], why: List[str], stop_meta: Optional[Dict[str, Any]] = None,
                     order_type: str = "at_close", setup: Optional[Dict[str, Any]] = None, logic_exact: bool = False) -> Dict[str, Any]:
    c = base_candidate(segment, family, label, ctx["direction"])
    inputs, atr = ctx["inputs"], ctx["atr"]
    near = ctx["resistance"] if up else ctx["support"]
    levels = scenario_levels(entry, up, stop, atr, near, base_override)
    risk_unit = abs(entry - stop)
    unit_name = "share" if unit_kind == "cash" else "lot"
    model, segment = _cost_model(inputs), ("equity_delivery" if unit_kind == "cash" else "futures")

    def cost_at_stop(units: int) -> float:
        # The desk's own pricing (services/desk_trading.round_trip_cost, the desk cost card), so the plan, the paper
        # trade's estimate and its realised costs at the stop agree to the paisa.
        return desk_costs.round_trip_cost(units, entry, stop, model, segment=segment, long=up)

    sizing = size_position(inputs, risk_per_unit=risk_unit, value_per_unit=entry, unit=unit_name + "s", lot_units=lot,
                           per_unit_label=("entry minus stop, per unit, plus the estimated round-trip costs at the stop "
                                           "(brokerage, STT, exchange charge, SEBI fee, stamp duty, GST and slippage, as "
                                           "the paper trade records them); DP charges, income tax and gap slippage are "
                                           "not included"),
                           cost_at_stop=cost_at_stop)
    if sizing["status"] == "complete":
        sizing["costs_breakdown_at_stop"] = desk_costs.round_trip_breakdown(sizing["quantity"] * lot, entry, stop, model,
                                                                            segment=segment, long=up)
    qty = sizing["quantity"] if sizing["status"] == "complete" else 1
    leg = {"kind": unit_kind, "side": "buy" if up else "sell", "quantity": qty, "lot_size": lot, "entry_price": entry,
           "expiry": expiry, "price_source": price_source}
    res = run_payoff(ctx, ctx["spot"] or entry, [leg], [{"name": "stop", "price": stop}] + levels, ctx["as_of"])
    risk_u = abs(entry - stop)
    for lv in levels:                       # targets labelled in R (decision D4): reward over the stop distance
        lv["r_multiple"] = round(abs(lv["price"] - entry) / risk_u, 2) if lv.get("price") is not None and risk_u else None
    from .trade_plan import DESK_ENTRY_RULE
    c.update(why_qualifies=why, sizing=sizing, payoff=res, legs=[leg], targets=levels, setup=setup,
             entry={"trigger": r2(entry), "zone": None, "order_type": order_type, "desk_entry_rule": DESK_ENTRY_RULE[order_type],
                    "logic": entry_note if logic_exact else entry_note + ("; a close above the trigger on volume confirms it" if up else "; a close below the trigger confirms it")},
             invalidation={"technical": {"price": r2(stop), "basis": stop_basis, "meaning": "the thesis is wrong if price closes beyond this level",
                                         **({k: stop_meta.get(k) for k in ("method", "atr", "atr_multiple", "distance_atr", "swing_ref", "measured_from", "rule")}
                                            if stop_meta else {"method": "unknown"})},
                           "execution_stop": {"price": r2(stop), "note": "A stop order does not guarantee the fill: a gap or thin trading can fill beyond it, so the loss can exceed the figure shown."}},
             risk_reward=reward_risk(res, True, _gate(levels)))
    if not res.get("valid"):
        c["status"] = "insufficient_data"
        c["reasons"].append(reason("payoff_invalid", "The payoff could not be calculated: " + "; ".join(p["code"] for p in res.get("problems", []))))
    else:
        c["warnings"] += [w["message"] for w in res.get("warnings", []) if w.get("code") != "grid_defaulted"]
        if sizing["status"] == "incomplete":
            c["warnings"].append("Sizing is incomplete (" + ", ".join(sizing["missing"]) + "): the payoff is shown for 1 " + unit_name + ".")
        elif sizing["status"] == "too_small":
            c["status"] = "no_trade"
            c["reasons"].append(reason("sizing_zero", sizing["reason"]))
        if risk_unit < RULES["targets"]["min_stop_atr"] * (atr or 0):
            c["warnings"].append(f"The stop is closer than {RULES['targets']['min_stop_atr']:g} x ATR to the entry: it may sit inside normal noise.")
        if segment == "futures":
            c["warnings"].append("Futures losses can exceed the initial margin; the plan does not estimate margin, so the notional is used for the allocation cap.")
    if c["status"] == "candidate":
        apply_rr_gate(c, inputs)
    return c


# ── futures ──────────────────────────────────────────────────────────────────

def pick_future(ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    fu = snap(ctx["snaps"], "futures")
    if not fu["ok"]:
        return None
    asof = day10(fu["as_of"] or ctx["as_of"])
    contracts = (fu["data"] or {}).get("futures") or []
    mn = RULES["futures"]["min_days_to_expiry"]
    for f in contracts:
        if asof and day10(f.get("expiry")) and (date.fromisoformat(f["expiry"]) - date.fromisoformat(asof)).days >= mn:
            return f
    return None


def buildup_gate(segment: str, fam: str, label: str, ctx: Dict[str, Any], up: bool) -> Optional[Dict[str, Any]]:
    """The futures build-up rule shared by the futures candidate and the futures + put combination: the right build-up, confirmed
    by the cash market. A not-viable candidate (with its reason) when it fails, None when it passes."""
    d = ctx["direction"]
    bu = snap(ctx["snaps"], "buildup")
    if not bu["ok"]:
        return not_viable(segment, fam, label, d, "insufficient_data", reason("buildup_unavailable", f"The F&O build-up row could not be read: {bu['error']}"))
    row = bu["data"] or {}
    lab, cc = row.get("label"), row.get("cash_confirmation")
    want = "long_buildup" if up else "short_buildup"
    if lab != want:
        text = {"short_covering": "Short covering is a rise on falling open interest: it is not fresh buying, so it is a wait, not a trade.",
                "long_unwinding": "Long unwinding is a fall on falling open interest: it is not fresh selling, so it is a wait, not a trade."}.get(lab)
        if lab in ("short_buildup", "long_buildup"):
            return not_viable(segment, fam, label, d, "no_trade", reason("buildup_opposes_view", f"The futures build-up is {lab}, the opposite of the {d} view."))
        return not_viable(segment, fam, label, d, "wait", reason("no_fresh_buildup", text or f"The futures build-up is {lab or 'unavailable'}: no fresh-position signal for a {d} view."))
    if cc != "confirms":
        return not_viable(segment, fam, label, d, "wait", reason("cash_not_confirming", "Cash confirmation is " + (f"'{cc}': the cash market did not move with the futures." if cc else "unavailable (a flat or missing cash move).") + " Wait for the cash market to confirm."))
    return None


def futures_candidates(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    d = ctx["direction"]
    if d not in ("bullish", "bearish"):
        return [not_viable("futures", "none", "No futures strategy", d, "no_trade", reason("no_directional_view", f"A {d} view has no futures strategy (futures are directional)."))]
    up = d == "bullish"
    fam = "long_buildup_continuation" if up else "short_buildup_continuation"
    label = "Long futures: build-up with cash confirmation" if up else "Short futures: build-up with cash confirmation"
    bu, fu = snap(ctx["snaps"], "buildup"), snap(ctx["snaps"], "futures")
    blocked = buildup_gate("futures", fam, label, ctx, up)
    if blocked:
        return [blocked]
    row = bu["data"] or {}
    lab = row.get("label")
    if not fu["ok"]:
        return [not_viable("futures", fam, label, d, "insufficient_data", reason("futures_unavailable", f"The futures contracts could not be read: {fu['error']}"))]
    near = pick_future(ctx)
    lot = (fu["data"] or {}).get("lot_size") or ((snap(ctx["snaps"], "chain")["data"] or {}).get("lot_size") if snap(ctx["snaps"], "chain")["ok"] else None)
    if near is None or num(near.get("settle")) is None:
        return [not_viable("futures", fam, label, d, "insufficient_data", reason("future_unpriced", f"No futures contract with a settle price and at least {RULES['futures']['min_days_to_expiry']} days to expiry."))]
    if not lot:
        return [not_viable("futures", fam, label, d, "insufficient_data", reason("lot_size_unknown", "The contract's lot size is not in the data: the position cannot be sized or priced."))]
    entry, spot = float(near["settle"]), ctx["spot"]
    s = (snap(ctx["snaps"], "chain")["data"] or {}).get("summary") if snap(ctx["snaps"], "chain")["ok"] else None
    s = s or {}
    pw, cw = (s.get("max_put_oi") or {}).get("strike"), (s.get("max_call_oi") or {}).get("strike")
    lv = levels_from(entry, up, pw, cw, s.get("expected_move"))
    atr = ctx["atr"]
    stop, stop_basis = lv["stop"], f"{lv['stop_from']} (FnoStrategies rule 2)"
    wall = lv["stop_from"] != "the edge of the expected move"
    fmeta: Dict[str, Any] = {"method": "structural" if wall else "expected_move", "atr": r2(atr), "atr_multiple": None,
                             "swing_ref": stop if wall else None, "measured_from": entry,
                             "rule": f"{lv['stop_from']} (FnoStrategies rule 2)"}
    if stop is None and ctx["hyp"] and spot is not None and num(ctx["hyp"].get("stop")) is not None:
        off = spot - ctx["hyp"]["stop"]
        stop, stop_basis = (entry - off if up else entry + off), "the chart engine's 2 x ATR stop distance applied to the futures price"
        fmeta = {**chart_stop_meta(ctx["hyp"], spot, atr), "measured_from": entry}
    if stop is not None and atr:
        fmeta["distance_atr"] = round(abs(entry - stop) / atr, 3)
    if stop is None or (stop >= entry if up else stop <= entry):
        return [not_viable("futures", fam, label, d, "insufficient_data", reason("risk_not_calculable", "No stop on the correct side of the entry could be derived."))]
    c = linear_candidate(ctx, "futures", fam, label, up, entry, stop, stop_basis, lv["target"],
                         f"Futures settle {entry:g} ({near['expiry']} contract, NSE F&O bhavcopy {fu['as_of']})",
                         unit_kind="future", lot=int(lot), expiry=near["expiry"], price_source=f"NSE F&O bhavcopy settle, {fu['as_of']}",
                         why=[f"Futures OI build-up is {lab}, confirmed by the cash market (a heuristic, not proof of intent).",
                              f"Contract {near['expiry']}, lot size {lot}, basis {near.get('basis')}."],
                         stop_meta=fmeta, order_type="at_close",
                         setup={"source": "fno_buildup", "bucket": lab, "stage": row.get("cash_confirmation"), "signal_date": fu["as_of"], "trigger": None})
    if "expiry_week" in (row.get("risk_flags") or []):
        c["warnings"].append("Expiry week: rollover and expiry effects can distort the build-up reading." + (" Rollover flag set." if "rollover" in row["risk_flags"] else ""))
    return [c]


# ── options ──────────────────────────────────────────────────────────────────

def pick_expiry(expiries: List[Dict[str, Any]], horizon_days: int, requested: Optional[str] = None) -> Tuple[Optional[str], str]:
    """(expiry, why) among the listed expiries ({expiry, days_to_expiry}, nearest first). The nearest expiry that outlasts the
    horizon and has at least min_days_to_expiry days (at most max_days_to_expiry), or the one the user asked for."""
    O = RULES["options"]
    if requested:
        hit = next((e for e in expiries if e.get("expiry") == requested), None)
        return (requested, "the expiry the user asked for") if hit else (None, f"the requested expiry {requested} is not listed")
    need = max(O["min_days_to_expiry"], horizon_days + 1)
    for e in expiries:
        if need <= e.get("days_to_expiry", -1) <= O["max_days_to_expiry"]:
            return e["expiry"], f"the nearest listed expiry with at least {need} days (horizon {horizon_days} days + 1, minimum {O['min_days_to_expiry']}) and at most {O['max_days_to_expiry']}"
    return None, f"no listed expiry has between {need} and {O['max_days_to_expiry']} days to expiry"


def _median(xs: List[float]) -> Optional[float]:
    return statistics.median(xs) if xs else None


def iv_fences(strikes: List[Dict[str, Any]]) -> Optional[Tuple[float, float]]:
    ivs = [s[side]["iv"] for s in strikes for side in ("call", "put") if s.get(side) and num(s[side].get("iv")) is not None]
    if len(ivs) < RULES["options"]["iv_min_sample"]:
        return None
    q = statistics.quantiles(ivs, n=4, method="inclusive")
    k, iqr = RULES["options"]["iv_fence_k"], q[2] - q[0]
    return q[0] - k * iqr, q[2] + k * iqr


def leg_view(row: Optional[Dict[str, Any]], side: str, strikes: List[Dict[str, Any]], fences: Optional[Tuple[float, float]]) -> Dict[str, Any]:
    """The contract's end-of-day facts and liquidity / IV flags. `blockers` stop the leg; `flags` are warnings."""
    s = (row or {}).get(side) or {}
    O = RULES["options"]
    oi, vol, close, iv = s.get("oi"), s.get("volume"), num(s.get("close")), num(s.get("iv"))
    med_oi = _median([x[side]["oi"] for x in strikes if x.get(side) and x[side].get("oi")])
    med_vol = _median([x[side]["volume"] for x in strikes if x.get(side) and x[side].get("volume")])
    flags: List[str] = []
    blockers: List[str] = []
    if close is None or close <= 0:
        blockers.append("missing_premium")
    if not oi:
        blockers.append("zero_open_interest")
    if not vol:
        blockers.append("no_trades_today")
    if oi and med_oi and oi < med_oi * O["low_oi_pct_of_median"] / 100:
        flags.append("low_oi")
    if vol and med_vol and vol < med_vol * O["low_volume_pct_of_median"] / 100:
        flags.append("low_volume")
    if iv is None:
        flags.append("missing_iv")
    elif fences and not fences[0] <= iv <= fences[1]:
        flags.append("abnormal_iv")
    if iv is not None and s.get("delta") is None:
        flags.append("missing_greeks")
    return {"close": close, "oi": oi, "volume": vol, "iv": iv, "delta": s.get("delta"), "flags": flags, "blockers": blockers,
            "median_oi": med_oi, "median_volume": med_vol}


def spread_strike(chain: Dict[str, Any], up: bool) -> Optional[Dict[str, Any]]:
    """FnoStrategies.tsx spreadStrike (rule 3): the short strike of a spread is the wall when it sits on the right side of the ATM
    strike and inside the expected move; else the listed strike nearest the edge of the expected move (right side of ATM)."""
    s = chain["summary"]
    atm = s.get("atm_strike")
    if atm is None:
        return None
    wall = (s.get("max_call_oi") if up else s.get("max_put_oi")) or {}
    wall = wall.get("strike")
    spot = s.get("spot") if s.get("spot") is not None else atm
    em = s.get("expected_move")
    edge = (spot + em if up else spot - em) if em is not None else None
    if wall is not None and (wall > atm if up else wall < atm) and (edge is None or (wall <= edge if up else wall >= edge)):
        return {"strike": wall, "from": "wall"}
    if edge is None:
        return None
    side = [r["strike"] for r in chain["strikes"] if (r["strike"] > atm if up else r["strike"] < atm)]
    if not side:
        return None
    return {"strike": min(side, key=lambda k: abs(k - edge)), "from": "move"}


def condor_ok(chain: Dict[str, Any]) -> Tuple[bool, str, Optional[float], Optional[float]]:
    """The neutral rule from FnoStrategies.tsx, tightened as in the PRD brief: spot strictly between the put wall and the call
    wall, and each wall at least one expected move away from the spot. Needs the expected move."""
    s = chain["summary"]
    sp, sc = (s.get("max_put_oi") or {}).get("strike"), (s.get("max_call_oi") or {}).get("strike")
    spot, em = s.get("spot"), s.get("expected_move")
    if sp is None or sc is None or spot is None:
        return False, "The put wall, the call wall or the spot is missing.", sp, sc
    if not sp < spot < sc:
        return False, f"The price {spot:g} is not strictly between the put wall {sp:g} and the call wall {sc:g}.", sp, sc
    if em is None:
        return False, "The expected move is unavailable, so the walls cannot be tested against it.", sp, sc
    m = RULES["options"]["condor_wall_min_expected_moves"] * em
    if sc - spot < m or spot - sp < m:
        return False, f"The expected move (±{em:g}) reaches past a wall ({sp:g} - {sc:g}).", sp, sc
    return True, f"Spot {spot:g} is inside the walls {sp:g} - {sc:g}, each at least {RULES['options']['condor_wall_min_expected_moves']:g} expected move (±{em:g}) away.", sp, sc


def _neighbour(strikes: List[float], k: float, step: int) -> Optional[float]:
    i = strikes.index(k) + step
    return strikes[i] if 0 <= i < len(strikes) else None


def _option_leg(chain_asof: str, expiry: str, lot: int, rowmap: Dict[float, Dict[str, Any]], strike: float, otype: str, side: str,
                lots: int, view: Dict[str, Any]) -> Dict[str, Any]:
    leg = {"kind": "option", "side": side, "quantity": lots, "lot_size": lot, "entry_price": view["close"], "expiry": expiry,
           "strike": strike, "option_type": otype, "price_source": f"NSE F&O bhavcopy close, {chain_asof}"}
    if view["iv"] is not None:
        leg["iv_pct"] = view["iv"]
    return leg


def structure_legs(family: str, plan: Dict[str, Any], rowmap: Dict[float, Dict[str, Any]], strikes: List[float], chain: Dict[str, Any],
                   up: bool) -> Optional[List[Tuple[float, str, str]]]:
    """[(strike, option_type, side)] for the family, or None when a needed strike does not exist."""
    if family == "long_call":
        return [(plan["k"], "call", "buy")]
    if family == "long_put":
        return [(plan["k"], "put", "buy")]
    if family == "bull_call_spread":
        return [(plan["long"], "call", "buy"), (plan["short"], "call", "sell")]
    if family == "bear_put_spread":
        return [(plan["long"], "put", "buy"), (plan["short"], "put", "sell")]
    if family == "iron_condor":
        lp, lc = plan["long_put"], plan["long_call"]
        if lp is None or lc is None:
            return None
        return [(lp, "put", "buy"), (plan["short_put"], "put", "sell"), (plan["short_call"], "call", "sell"), (lc, "call", "buy")]
    return None


def build_options_variant(ctx: Dict[str, Any], chain: Dict[str, Any], family: str, plan: Dict[str, Any], tag: str) -> Dict[str, Any]:
    """Price one concrete strike set through compute_payoff and sum up its liquidity flags. Returns a variant record."""
    S = chain["summary"]
    strikes_rows = chain["strikes"]
    rowmap = {r["strike"]: r for r in strikes_rows}
    ks = sorted(rowmap)
    fences = iv_fences(strikes_rows)
    lot = chain.get("lot_size")
    if not lot and snap(ctx["snaps"], "futures")["ok"]:
        lot = (snap(ctx["snaps"], "futures")["data"] or {}).get("lot_size")
    spec = structure_legs(family, plan, rowmap, ks, chain, ctx["direction"] == "bullish")
    rec: Dict[str, Any] = {"tag": tag, "family": family, "plan": plan, "legs": [], "views": [], "blockers": [], "flags": [], "payoff": None, "metrics": None}
    if spec is None or any(k is None or k not in rowmap for k, _, _ in spec):
        rec["blockers"].append("strike_not_listed")
        return rec
    for k, otype, side in spec:
        v = leg_view(rowmap[k], otype, strikes_rows, fences)
        v.update(strike=k, option_type=otype, side=side)
        rec["views"].append(v)
        rec["blockers"] += [f"{b}@{k:g}{otype[0].upper()}E" for b in v["blockers"]]
        rec["flags"] += [f"{f}@{k:g}{otype[0].upper()}E" for f in v["flags"]]
    if rec["blockers"] or not lot:
        if not lot:
            rec["blockers"].append("lot_size_unknown")
        return rec
    legs = [_option_leg(chain["asof"], S["expiry"], int(lot), rowmap, v["strike"], v["option_type"], v["side"], 1, v) for v in rec["views"]]
    rec["legs"] = legs
    # structure sanity: a debit spread must cost something and less than its width
    if family in ("bull_call_spread", "bear_put_spread"):
        width = abs(plan["short"] - plan["long"])
        debit = rec["views"][0]["close"] - rec["views"][1]["close"]
        if not 0 < debit < width:
            rec["blockers"].append("spread_price_inconsistent")
            return rec
    return rec


def _delay(chain_asof: str, ref: Optional[str]) -> bool:
    return bool(ref and chain_asof and chain_asof < ref)


def options_candidates(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    d, snaps = ctx["direction"], ctx["snaps"]
    if d == "vol_expansion":
        return [not_viable("options", "none", "No options strategy", d, "no_trade",
                           reason("volatility_long_not_supported", "A volatility-expansion view needs a long straddle/strangle, which this release does not offer (only documented defined-risk templates; no volatility thesis has been validated)."))]
    fams = {"bullish": ["long_call", "bull_call_spread"], "bearish": ["long_put", "bear_put_spread"], "neutral": ["iron_condor"], "vol_contraction": ["iron_condor"]}[d]
    ch = snap(snaps, "chain")
    ex = snap(snaps, "expiries")
    if not ch["ok"]:
        return [not_viable("options", f, FAMILY_LABEL[f], d, "insufficient_data", reason("no_valid_chain", f"No valid option chain: {ch['error']}")) for f in fams]
    chain = dict(ch["data"] or {})
    chain["asof"] = ch["as_of"] or (chain.get("summary") or {}).get("as_of")
    if not chain.get("strikes") or not chain.get("summary"):
        return [not_viable("options", f, FAMILY_LABEL[f], d, "insufficient_data", reason("no_valid_chain", "The option chain has no strikes.")) for f in fams]
    out = []
    for f in fams:
        if f in ("bull_call_spread", "bear_put_spread", "iron_condor") and not ctx["inputs"]["allow_multi_leg"]:
            out.append(not_viable("options", f, FAMILY_LABEL[f], d, "no_trade", reason("multi_leg_not_allowed", "Multi-leg structures are switched off in the inputs.")))
            continue
        out.append(one_options_candidate(ctx, chain, ex, f))
    return out


FAMILY_LABEL = {"long_call": "Long call", "long_put": "Long put", "bull_call_spread": "Bull call spread (debit)",
                "bear_put_spread": "Bear put spread (debit)", "iron_condor": "Iron condor (defined risk)"}


def _plans(family: str, chain: Dict[str, Any], up: bool) -> Optional[Dict[str, Any]]:
    """{'preferred': plan, 'alternatives': [plan...], 'why': str, 'alt_why': [..]} or {'error': (code, msg)}."""
    S, ks = chain["summary"], sorted(r["strike"] for r in chain["strikes"])
    atm = S.get("atm_strike")
    if atm is None or atm not in ks:
        return {"error": ("no_atm_strike", "The chain has no ATM strike (no spot).")}
    if family in ("long_call", "long_put"):
        call = family == "long_call"
        otm = _neighbour(ks, atm, 1 if call else -1)
        pref = {"k": atm}
        alts = [{"k": otm}] if otm is not None else []
        return {"preferred": pref, "alternatives": alts,
                "why": f"The ATM {'call' if call else 'put'} ({atm:g}): the strike nearest the spot, the most responsive to the underlying for its premium; the premium is the whole risk.",
                "alt_why": [f"One strike out of the money ({otm:g}): cheaper, but needs a larger move to pay off."] if otm is not None else []}
    if family in ("bull_call_spread", "bear_put_spread"):
        far = spread_strike(chain, up)
        if far is None:
            return {"error": ("no_short_strike", "The chain gives no short strike (no wall on the right side of the ATM strike and no expected move).")}
        pref = {"long": atm, "short": far["strike"]}
        alts = []
        other = None
        side_ks = [k for k in ks if (k > atm if up else k < atm)]
        # alternative: the one-step-nearer short strike when the wall is far, else the next strike beyond the preferred one
        nearer = _neighbour(ks, far["strike"], -1 if up else 1)
        beyond = _neighbour(ks, far["strike"], 1 if up else -1)
        for cand in (beyond, nearer):
            if cand is not None and cand != atm and (cand > atm if up else cand < atm):
                other = cand
                break
        if other is not None:
            alts.append({"long": atm, "short": other})
        why = (f"Long the ATM {atm:g}, short {far['strike']:g}: " + (f"the {'call' if up else 'put'} wall (rule 3, FnoStrategies.tsx), inside the expected move, so the short leg sits where the market has the most open interest."
                                                                    if far["from"] == "wall" else "the listed strike nearest the edge of the expected move (the wall lies outside it)."))
        return {"preferred": pref, "alternatives": alts, "why": why,
                "alt_why": [f"Short {other:g} instead: a {'wider' if abs(other - atm) > abs(far['strike'] - atm) else 'narrower'} spread with a {'higher' if abs(other - atm) > abs(far['strike'] - atm) else 'lower'} cap and cost."] if other is not None else []}
    ok, why, sp, sc = condor_ok(chain)
    if not ok:
        return {"error": ("condor_rule_fails", why)}
    lp, lc = _neighbour(ks, sp, -1), _neighbour(ks, sc, 1)
    lp2, lc2 = (_neighbour(ks, lp, -1) if lp is not None else None), (_neighbour(ks, lc, 1) if lc is not None else None)
    pref = {"short_put": sp, "long_put": lp, "short_call": sc, "long_call": lc}
    alts = [{"short_put": sp, "long_put": lp2, "short_call": sc, "long_call": lc2}] if lp2 is not None and lc2 is not None else []
    return {"preferred": pref, "alternatives": alts,
            "why": f"Short strikes at the walls {sp:g} / {sc:g}, wings one strike beyond. {why}",
            "alt_why": ["Wings two strikes beyond the short strikes: more protection, a smaller credit and a larger max loss."] if alts else []}


def variant_summary(ctx: Dict[str, Any], chain: Dict[str, Any], rec: Dict[str, Any], up: bool, levels: List[Dict[str, Any]], stop: Optional[float],
                    pre: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not rec["legs"] or rec["blockers"]:
        return rec
    scen = ([{"name": "stop", "price": stop}] if stop else []) + levels
    rec["payoff"] = run_payoff(ctx, chain["summary"].get("spot") or ctx["spot"], rec["legs"], scen, chain["asof"], pre)
    res = rec["payoff"]
    if res.get("valid"):
        e = res["expiry"]
        rec["metrics"] = {"max_loss": e["max_loss"], "max_profit": e["max_profit"], "profit_unbounded": e["profit_unbounded"], "breakevens": e["breakevens"],
                          "net_premium": e["net_premium"], "capital_at_risk": res["capital_at_risk"], "risk_reward": reward_risk(res, False, _gate(levels))}
    return rec


def one_options_candidate(ctx: Dict[str, Any], chain: Dict[str, Any], ex: Dict[str, Any], family: str) -> Dict[str, Any]:
    d, inputs = ctx["direction"], ctx["inputs"]
    up = d == "bullish"
    S = chain["summary"]
    label = FAMILY_LABEL[family]
    c = base_candidate("options", family, label, d)
    plans = _plans(family, chain, up)
    if "error" in plans:
        code, msg = plans["error"]
        c["status"] = "no_trade"
        c["reasons"].append(reason(code, msg))
        return c
    delayed = _delay(chain["asof"], ctx["ref_session"])
    # underlying levels (stop and scenario levels)
    spot = S.get("spot") or ctx["spot"]
    pw, cw, em = (S.get("max_put_oi") or {}).get("strike"), (S.get("max_call_oi") or {}).get("strike"), S.get("expected_move")
    stop, levels, stop_basis = None, [], None
    if family == "iron_condor":
        if spot and em:
            levels = [{"name": "conservative", "price": r2(spot + em), "rule": "spot + 1 expected move (the price drifts to the upper edge of the expected range)", "gate": True},
                      {"name": "base", "price": r2(spot), "rule": "the price is unchanged", "gate": False},
                      {"name": "optimistic", "price": r2(spot), "rule": "the price is unchanged (a range structure's best case)", "gate": False}]
    elif spot:
        lv = levels_from(spot, up, pw, cw, em)
        stop = lv["stop"]
        stop_basis = f"{lv['stop_from']} (FnoStrategies rule 2)"
        if stop is None and ctx["hyp"] and num(ctx["hyp"].get("stop")) is not None:
            stop, stop_basis = (ctx["hyp"]["stop"] if up else 2 * spot - ctx["hyp"]["stop"]), "the chart engine's 2 x ATR stop distance"
        if stop is not None and (stop >= spot if up else stop <= spot):
            stop = None
        if stop is not None:
            levels = scenario_levels(spot, up, stop, ctx["atr"], ctx["resistance"] if up else ctx["support"], lv["target"])
    if not levels:
        c["status"] = "insufficient_data"
        c["reasons"].append(reason("risk_not_calculable", "No underlying stop or scenario levels could be derived (no spot, walls or expected move)."))
        return c
    # pre-expiry block date: the end of the horizon, only before expiry
    pre = None
    horizon_end = (date.fromisoformat(chain["asof"]) + timedelta(days=ctx["inputs"]["horizon_days"])).isoformat() if chain.get("asof") else None
    if horizon_end and horizon_end < S["expiry"]:
        pre = {"date": horizon_end, "iv_shift_pct": 0, "rate_pct": round(RISK_FREE_RATE * 100, 4)}
    pref = variant_summary(ctx, chain, build_options_variant(ctx, chain, family, plans["preferred"], "preferred"), up, levels, stop, pre)
    alts = [variant_summary(ctx, chain, build_options_variant(ctx, chain, family, a, f"alternative {i + 1}"), up, levels, stop, pre)
            for i, a in enumerate(plans["alternatives"])]
    selection = {
        "expiry": S["expiry"], "days_to_expiry": S.get("days_to_expiry"), "expiry_why": ctx.get("expiry_why"),
        "eligible_expiries": [{"expiry": e["expiry"], "days_to_expiry": e["days_to_expiry"]} for e in (ex["data"] or {}).get("expiries", [])] if ex["ok"] else None,
        "eligible_expiries_note": None if ex["ok"] else f"Expiry list unavailable: {ex['error']}",
        "eligible_strikes": [r["strike"] for r in chain["strikes"]], "strikes_source": f"NSE F&O bhavcopy via /api/fno/{ctx['symbol']}/chain, as of {chain['asof']} (end of day)",
        "chosen": plans["preferred"], "why": plans["why"],
        "rule": "Thesis direction, then liquidity (open interest and volume as the proxy), premium, expiry and defined risk. A strike is never chosen only because it is cheap or has high open interest.",
        "alternatives": [{"plan": a["plan"], "why": w, "blockers": a["blockers"], "flags": a["flags"], "metrics": a["metrics"]} for a, w in zip(alts, plans["alt_why"])],
        "preferred_flags": pref["flags"], "preferred_leg_facts": [{k: v[k] for k in ("strike", "option_type", "side", "close", "oi", "volume", "iv", "delta", "median_oi", "median_volume")} for v in pref["views"]],
        "iv_fences": iv_fences(chain["strikes"]), "liquidity_proxy": "open interest and volume (the end-of-day file has no bid/ask)",
        "stale": delayed, "chain_as_of": chain["asof"], "reference_session": ctx["ref_session"]}
    c.update(options_selection=selection, targets=levels, legs=pref["legs"])
    if stop is not None:
        c["invalidation"] = {"technical": {"price": r2(stop), "basis": stop_basis, "meaning": "the directional thesis is wrong beyond this underlying level"},
                             "execution_stop": {"price": None, "note": "A long option's loss is limited to the premium; a defined-risk spread's to its max loss. No stop order is assumed."}}
    elif family == "iron_condor":
        c["invalidation"] = {"technical": {"price": None, "basis": "a close beyond either short strike", "short_put": plans["preferred"]["short_put"], "short_call": plans["preferred"]["short_call"], "meaning": "the range thesis is wrong"},
                             "execution_stop": {"price": None, "note": "Max loss is defined by the wings; no stop order is assumed."}}
    c["entry"] = {"trigger": r2(spot), "zone": None, "logic": f"Premiums are the {chain['asof']} closes (end of day, never live); re-price before acting. Debits/credits shown are per unit."}
    c["why_qualifies"] = [plans["why"]]
    c["warnings"].append("Bid/ask is not in the end-of-day file: premiums are the day's close, not an executable price.")
    if delayed:
        c["warnings"].append(f"Delayed/historical: the chain is from {chain['asof']}, before the last completed session {ctx['ref_session']}. Not a current actionable strike.")
        c["label_note"] = "Delayed/historical options analysis, not a current actionable strike"
    if pref["blockers"]:
        c["payoff"] = pref["payoff"]
        c["status"] = "no_trade"
        codes = sorted({b.split("@")[0] for b in pref["blockers"]})
        legs_txt = ", ".join(pref["blockers"])
        if "missing_premium" in codes:
            c["reasons"].append(reason("legs_unpriced", f"A leg has no closing price, so it is not built ({legs_txt}). A premium is never guessed."))
        if {"zero_open_interest", "no_trades_today"} & set(codes):
            c["reasons"].append(reason("illiquid_leg", f"A leg has no open interest or did not trade on {chain['asof']} ({legs_txt}): its close is not a market price."))
        if {"strike_not_listed", "lot_size_unknown", "spread_price_inconsistent"} & set(codes):
            c["reasons"].append(reason("legs_unpriced", f"The structure cannot be priced reliably ({legs_txt})."))
        return c
    res = pref["payoff"]
    if not res or not res.get("valid"):
        c["status"] = "insufficient_data"
        c["reasons"].append(reason("payoff_invalid", "The payoff could not be calculated: " + "; ".join(p["code"] for p in (res or {}).get("problems", []))))
        return c
    # sizing: lots from the defined max loss per lot
    car = res["capital_at_risk"]
    outlay = abs(res["expiry"]["net_premium"]) if res["expiry"]["net_premium"] is not None else None
    sizing = size_position(inputs, risk_per_unit=car, value_per_unit=max(outlay or 0.0, car or 0.0), unit="lots", lot_units=1,
                           per_unit_label="worst net loss of one lot (max loss plus costs), from the payoff calculation")
    lots = sizing["quantity"] if sizing["status"] == "complete" else 1
    if lots != 1:
        legs = [dict(l, quantity=lots) for l in pref["legs"]]
        res = run_payoff(ctx, spot, legs, ([{"name": "stop", "price": stop}] if stop else []) + levels, chain["asof"], pre)
        c["legs"] = legs
    c.update(payoff=res, sizing=sizing, risk_reward=reward_risk(res, False, _gate(levels)))
    if sizing["status"] == "incomplete":
        c["warnings"].append("Sizing is incomplete (" + ", ".join(sizing["missing"]) + "): the payoff is shown for 1 lot.")
    elif sizing["status"] == "too_small":
        c["status"] = "no_trade"
        c["reasons"].append(reason("sizing_zero", sizing["reason"]))
    for f in pref["flags"]:
        c["warnings"].append(f"Flag {f.split('@')[0]} on {f.split('@')[1]}: " + FLAG_TEXT.get(f.split("@")[0], ""))
    pe = res.get("pre_expiry")
    if pre is None:
        c["warnings"].append("No pre-expiry estimate: the horizon ends on or after the expiry, where the expiry payoff applies.")
    elif pe and pe.get("unavailable"):
        c["warnings"].append("The pre-expiry estimate is unavailable: " + "; ".join(u["reason"] for u in pe["unavailable"]) + " No volatility is assumed.")
    if c["status"] == "candidate":
        apply_rr_gate(c, inputs)
    if c["status"] == "candidate" and delayed:
        c["status"] = "wait"
        c["reasons"].append(reason("stale_chain", f"The chain is from {chain['asof']}, before the last completed session {ctx['ref_session']}: delayed/historical, not a current actionable strike. Refresh the F&O data before acting."))
    return c


FLAG_TEXT = {"low_oi": "open interest is below the chain's typical strike; exits may be hard.",
             "low_volume": "volume is below the chain's typical strike; the close may not be representative.",
             "missing_iv": "no implied volatility could be worked out; no pre-expiry estimate for this leg.",
             "missing_greeks": "Greeks are missing.",
             "abnormal_iv": "implied volatility is outside the chain's own interquartile fences (Tukey, k=1.5): a rich or cheap contract, or a bad print."}


# ── combinations: cash legs together with F&O legs (all defined risk) ─────────

COMBO_ORDER = ("covered_call", "protective_put", "collar", "futures_protective_put")
COMBO_LABEL = {"covered_call": "Covered call (shares + short call)", "protective_put": "Protective put (shares + long put)",
               "collar": "Collar (shares + long put + short call)", "futures_protective_put": "Futures + protective put (synthetic long call)"}


def results_in_horizon(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [e for e in events_in_horizon(ctx["snaps"], ctx["as_of"], ctx["inputs"]["horizon_days"]) if e.get("event_type") == "quarterly_results"]


def hedge_reason(ctx: Dict[str, Any]) -> Tuple[bool, str]:
    """(needed, why). Insurance needs a reason: results inside the horizon, or high gap risk (the scanner's risk class)."""
    res = results_in_horizon(ctx)
    if res:
        return True, f"Results are scheduled on {day10(res[0]['event_date'])}, inside the {ctx['inputs']['horizon_days']}-day horizon"
    sr = snap(ctx["snaps"], "scan_row")
    rc = (sr["data"] or {}).get("risk_class") if sr["ok"] else None
    if rc is None and ctx["atr"] and ctx["spot"]:
        pct = ctx["atr"] / ctx["spot"] * 100
        rc = "high" if pct > setup_rules.RISK_BANDS["high_above_pct"] else "not high"
    if rc == "high":
        return True, f"The stock's risk class is high (ATR(14) above {setup_rules.RISK_BANDS['high_above_pct']:g}% of the close): gap risk"
    return False, "no results date inside the horizon and the risk class is not high"


def scanner_stop(ctx: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    """The long idea's stop below the last close: the scanner's, else the chart engine's ATR stop. (None, None) when neither exists."""
    sb, spot = snap(ctx["snaps"], "scanner_bucket"), ctx["spot"]
    it = ((sb["data"] or {}).get("item") or {}) if sb["ok"] else {}
    stop = num(it.get("stop_price"))
    if spot is not None and stop is not None and 0 < stop < spot:
        return stop, f"the scanner's stop ({stop:g})"
    stop = num(ctx["hyp"].get("stop")) if ctx["hyp"] else None
    if spot is not None and stop is not None and 0 < stop < spot:
        return stop, "the chart engine's ATR stop (2 x ATR(14), or 20-session support when closer)"
    return None, None


def short_call_strike(chain: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """rules.combinations.short_call_strike: the call wall when above the ATM strike, else the first strike at or beyond spot + one expected move."""
    S, ks = chain["summary"], sorted(r["strike"] for r in chain["strikes"])
    atm, em = S.get("atm_strike"), S.get("expected_move")
    spot = S.get("spot") if S.get("spot") is not None else atm
    cw = (S.get("max_call_oi") or {}).get("strike")
    if cw is not None and atm is not None and cw > atm and cw in ks:
        return {"strike": cw, "from": "the call wall"}
    if em is not None and spot is not None:
        beyond = [k for k in ks if k >= spot + em]
        if beyond:
            return {"strike": beyond[0], "from": "the first strike at or beyond one expected move"}
    return None


def long_put_strike(chain: Dict[str, Any], stop: float) -> Optional[float]:
    """rules.combinations.long_put_strike: the listed out-of-the-money put strike nearest the stop."""
    S = chain["summary"]
    spot = S.get("spot") if S.get("spot") is not None else S.get("atm_strike")
    otm = sorted(r["strike"] for r in chain["strikes"] if spot is not None and r["strike"] < spot and r.get("put"))
    return min(otm, key=lambda k: abs(k - stop)) if otm else None


def combo_blocker_reasons(blockers: List[str], asof: str) -> List[Dict[str, Any]]:
    codes = sorted({b.split("@")[0] for b in blockers})
    txt = ", ".join(blockers)
    out = []
    if "missing_premium" in codes:
        out.append(reason("legs_unpriced", f"A leg has no closing price, so it is not built ({txt}). A premium is never guessed."))
    if {"zero_open_interest", "no_trades_today"} & set(codes):
        out.append(reason("illiquid_leg", f"A leg has no open interest or did not trade on {asof} ({txt}): its close is not a market price."))
    if {"strike_not_listed", "lot_size_unknown", "future_unpriced", "future_expiry_mismatch"} & set(codes):
        out.append(reason("legs_unpriced", f"The structure cannot be priced reliably ({txt})."))
    return out


NOT_FNO_TEXT = ("The stock is not in the NSE F&O segment (nidp.security_reference_daily.fno_eligible is false): it has no futures or options, "
                "so only the cash idea applies.")


def combo_candidates(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    d, C = ctx["direction"], RULES["combinations"]
    fams = [f for f in COMBO_ORDER if d in C["views"][f]]
    if not fams:
        return [not_viable("combination", "none", "No combination strategy", d, "no_trade",
                           reason("no_combination_for_view", f"A {d} view has no combination strategy: they hold the shares long (bullish or neutral views only)."))]
    sr = snap(ctx["snaps"], "scan_row")
    if sr["ok"] and (sr["data"] or {}).get("fno_eligible") is False:
        return [not_viable("combination", "none", "No combination strategy", d, "no_trade",
                           reason("not_fno_eligible", NOT_FNO_TEXT))]
    ch = snap(ctx["snaps"], "chain")
    if not ch["ok"]:
        return [not_viable("combination", f, COMBO_LABEL[f], d, "insufficient_data", reason("no_valid_chain", f"No valid option chain: {ch['error']}")) for f in fams]
    chain = dict(ch["data"] or {})
    chain["asof"] = ch["as_of"] or (chain.get("summary") or {}).get("as_of")
    if not chain.get("strikes") or not chain.get("summary"):
        return [not_viable("combination", f, COMBO_LABEL[f], d, "insufficient_data", reason("no_valid_chain", "The option chain has no strikes.")) for f in fams]
    return [one_combo_candidate(ctx, chain, f) for f in fams]


def _deployed(legs: List[Dict[str, Any]]) -> float:
    """Capital one structure ties up: shares and futures at their entry value (a future's notional, as for the futures candidate) plus the
    net premium paid (premium received reduces it)."""
    tot = 0.0
    for l in legs:
        units = l["quantity"] * l["lot_size"]
        tot += (l["entry_price"] * units) * (1 if l["side"] == "buy" else -1) if l["kind"] == "option" else l["entry_price"] * units
    return tot


def one_combo_candidate(ctx: Dict[str, Any], chain: Dict[str, Any], family: str) -> Dict[str, Any]:
    d, inputs, C = ctx["direction"], ctx["inputs"], RULES["combinations"]
    label, S = COMBO_LABEL[family], chain["summary"]
    snaps = ctx["snaps"]
    c = base_candidate("combination", family, label, d)
    c["event_hedged"] = family in C["event_hedged"]

    def fail(status: str, *reasons: Dict[str, Any]) -> Dict[str, Any]:
        c["status"] = status
        c["reasons"] += list(reasons)
        return c

    if family == "futures_protective_put":
        blocked = buildup_gate("combination", family, label, ctx, True)
        if blocked:
            blocked["event_hedged"] = True
            return blocked
    need, why_need = hedge_reason(ctx)
    if family in C["needs_hedge_reason"] and not need:
        return fail("no_trade", reason("not_indicated", f"{label} is for a stock with event or gap risk, and here there is none ({why_need}): insurance would be a cost without a reason."
                                       + (" The plain long future carries the idea." if family == "futures_protective_put" else "")))
    spot = ctx["spot"]
    if spot is None:
        return fail("insufficient_data", reason("no_price", "No last close: the shares leg cannot be priced."))
    stop, stop_basis = scanner_stop(ctx)
    if stop is None:
        return fail("insufficient_data", reason("risk_not_calculable", "No stop below the price could be derived (scanner stop and ATR stop are both missing)."))
    fu = snap(snaps, "futures")
    lot = chain.get("lot_size") or ((fu["data"] or {}).get("lot_size") if fu["ok"] else None)
    if not lot:
        return fail("insufficient_data", reason("lot_size_unknown", "The contract's lot size is not in the data: the position cannot be sized or priced."))
    lot = int(lot)
    rows = chain["strikes"]
    rowmap = {r["strike"]: r for r in rows}
    fences = iv_fences(rows)
    plan: Dict[str, Any] = {}
    specs: List[Tuple[float, str, str]] = []
    if family in ("covered_call", "collar"):
        sc = short_call_strike(chain)
        if sc is None:
            return fail("no_trade", reason("no_short_strike", "The chain gives no short call strike (no call wall above the ATM strike and no strike beyond one expected move)."))
        plan["short_call"], plan["short_call_from"] = sc["strike"], sc["from"]
        specs.append((sc["strike"], "call", "sell"))
    if family in ("protective_put", "collar", "futures_protective_put"):
        kp = long_put_strike(chain, stop)
        if kp is None:
            return fail("no_trade", reason("no_put_strike", "The chain lists no out-of-the-money put to buy."))
        plan["long_put"] = kp
        specs.insert(0, (kp, "put", "buy"))
    views, blockers, flags = [], [], []
    for k, otype, side in specs:
        v = leg_view(rowmap[k], otype, rows, fences)
        v.update(strike=k, option_type=otype, side=side)
        views.append(v)
        blockers += [f"{b}@{k:g}{otype[0].upper()}E" for b in v["blockers"]]
        flags += [f"{f}@{k:g}{otype[0].upper()}E" for f in v["flags"]]
    fut = None
    if family == "futures_protective_put":
        fut = next((f for f in ((fu["data"] or {}).get("futures") or []) if fu["ok"] and f.get("expiry") == S.get("expiry")), None)
        if fut is None:
            blockers.append("future_expiry_mismatch")
        elif num(fut.get("settle")) is None:
            blockers.append("future_unpriced")
        else:
            if not fut.get("oi"):
                blockers.append("zero_open_interest@future")
            if not fut.get("volume"):
                blockers.append("no_trades_today@future")
    asof = chain["asof"]
    if blockers:
        return fail("no_trade", *combo_blocker_reasons(blockers, asof))
    levels = scenario_levels(spot, True, stop, ctx["atr"], ctx["resistance"], None)
    scen = [{"name": "stop", "price": stop}] + levels

    def make_legs(lots: int) -> List[Dict[str, Any]]:
        if fut is not None:
            legs = [{"kind": "future", "side": "buy", "quantity": lots, "lot_size": lot, "entry_price": float(fut["settle"]), "expiry": S["expiry"],
                     "price_source": f"NSE F&O bhavcopy settle, {fu['as_of']}"}]
        else:
            legs = [{"kind": "cash", "side": "buy", "quantity": lots * lot, "lot_size": 1, "entry_price": spot, "expiry": None, "price_source": ctx["spot_source"]}]
        return legs + [_option_leg(asof, S["expiry"], lot, rowmap, v["strike"], v["option_type"], v["side"], lots, v) for v in views]

    legs1 = make_legs(1)
    res1 = run_payoff(ctx, spot, legs1, scen, asof)
    if not res1.get("valid"):
        return fail("insufficient_data", reason("payoff_invalid", "The payoff could not be calculated: " + "; ".join(p["code"] for p in res1.get("problems", []))))
    st1 = _scn(res1, "stop")
    loss1 = -st1["net"] if st1 else None
    basis = "loss of one lot if the price reaches the stop, from the payoff calculation (costs included)"
    if loss1 is None or loss1 <= 0:
        loss1, basis = (spot - stop) * lot, "the cash stop distance x lot size (the premium received covers the loss at the stop, so it is not counted against the budget)"
    sizing = size_position(inputs, risk_per_unit=loss1, value_per_unit=_deployed(legs1), unit="lots", lot_units=1, per_unit_label=basis)
    lots = sizing["quantity"] if sizing["status"] == "complete" else 1
    legs = make_legs(lots) if lots != 1 else legs1
    res = res1 if lots == 1 else run_payoff(ctx, spot, legs, scen, asof)
    rr = reward_risk(res, True, _gate(levels))
    delayed = _delay(asof, ctx["ref_session"])
    cw, pw = (S.get("max_call_oi") or {}).get("strike"), (S.get("max_put_oi") or {}).get("strike")
    prem = {(v["option_type"], v["side"]): v["close"] for v in views}
    shares = f"{lots * lot} shares"
    why_by = {
        "covered_call": f"Bullish-to-neutral view: sell the {plan.get('short_call', 0):g} call ({plan.get('short_call_from')}) against {shares} to collect {prem.get(('call', 'sell'), 0):g} a share; the upside is capped at that strike.",
        "protective_put": f"{why_need}: buy the {plan.get('long_put', 0):g} put (nearest the stop, {stop_basis}) so the loss on {shares} cannot go below that strike.",
        "collar": f"{why_need}: buy the {plan.get('long_put', 0):g} put and sell the {plan.get('short_call', 0):g} call ({plan.get('short_call_from')}); the call premium offsets part of the put's cost, and the upside is capped.",
        "futures_protective_put": f"The futures build-up is long and confirmed by the cash market, and {why_need[0].lower() + why_need[1:]}: the {plan.get('long_put', 0):g} put limits the future's loss, a synthetic long call.",
    }
    c.update(legs=legs, targets=levels, payoff=res, sizing=sizing, risk_reward=rr, why_qualifies=[why_by[family]],
             entry={"trigger": r2(spot), "zone": None, "logic": f"{'Futures' if fut is not None else 'Shares'} at {r2(fut['settle'] if fut is not None else spot):g} ({legs[0]['price_source']}); premiums are the {asof} closes (end of day, never live); re-price before acting."},
             invalidation={"technical": {"price": r2(stop), "basis": stop_basis, "meaning": "the thesis is wrong if price closes beyond this level"},
                           "execution_stop": {"price": None, "note": "A long put defines the downside at its strike; a sold call caps the upside. No stop order is assumed."}},
             options_selection={"expiry": S["expiry"], "days_to_expiry": S.get("days_to_expiry"), "expiry_why": ctx.get("expiry_why"), "eligible_expiries": None,
                                "eligible_expiries_note": "See the options candidates for the listed expiries.",
                                "eligible_strikes": [r["strike"] for r in rows], "strikes_source": f"NSE F&O bhavcopy via /api/fno/{ctx['symbol']}/chain, as of {asof} (end of day)",
                                "chosen": plan, "why": why_by[family], "rule": "; ".join(f"{k}: {C[k]}" for k in ("short_call_strike", "long_put_strike", "shares", "future") if k in C),
                                "alternatives": [], "preferred_flags": flags,
                                "preferred_leg_facts": [{k: v[k] for k in ("strike", "option_type", "side", "close", "oi", "volume", "iv", "delta", "median_oi", "median_volume")} for v in views],
                                "iv_fences": fences, "liquidity_proxy": "open interest and volume (the end-of-day file has no bid/ask)", "stale": delayed,
                                "chain_as_of": asof, "reference_session": ctx["ref_session"], "call_wall": cw, "put_wall": pw})
    c["warnings"].append("Bid/ask is not in the end-of-day file: premiums are the day's close, not an executable price.")
    c["warnings"].append("No pre-expiry estimate for combination structures in this release: the expiry payoff applies.")
    held = [r for r in ((snap(snaps, "portfolio")["data"] or []) if snap(snaps, "portfolio")["ok"] else []) if isinstance(r, dict) and str(r.get("nse_symbol") or "").upper() == ctx["symbol"]]
    if held:
        c["warnings"].append(f"Your portfolio already lists {ctx['symbol']}: the shares leg is that position priced at the last close ({spot:g}), not at your cost.")
    for f in flags:
        c["warnings"].append(f"Flag {f.split('@')[0]} on {f.split('@')[1]}: " + FLAG_TEXT.get(f.split("@")[0], ""))
    if sizing["status"] == "incomplete":
        c["warnings"].append("Sizing is incomplete (" + ", ".join(sizing["missing"]) + "): the payoff is shown for 1 lot.")
    elif sizing["status"] == "too_small":
        c["status"] = "no_trade"
        c["reasons"].append(reason("sizing_zero", sizing["reason"]))
    stop_s = _scn(res, "stop")
    if c["status"] == "candidate":
        if stop_s is not None and stop_s["net"] >= 0:
            c["warnings"].append("Reward : risk is undefined here: the premium received covers the loss at the stop, so there is no loss to divide by. The gate is not applied; read max loss and capital at risk.")
        else:
            apply_rr_gate(c, inputs)
    if c["status"] == "candidate" and delayed:
        c["status"] = "wait"
        c["reasons"].append(reason("stale_chain", f"The chain is from {asof}, before the last completed session {ctx['ref_session']}: delayed/historical, not a current actionable strike. Refresh the F&O data before acting."))
    return c


# ── dispatch ─────────────────────────────────────────────────────────────────

def generate(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    want = ctx["inputs"]["instrument"]
    out: List[Dict[str, Any]] = []
    sr = snap(ctx["snaps"], "scan_row")
    no_fno = sr["ok"] and (sr["data"] or {}).get("fno_eligible") is False
    if want in ("cash", "all"):
        out += cash_candidates(ctx)
    for seg, fn in (("futures", futures_candidates), ("options", options_candidates)):
        if want in (seg, "all"):
            out += [not_viable(seg, "none", f"No {seg} strategy", ctx["direction"], "no_trade", reason("not_fno_eligible", NOT_FNO_TEXT))] if no_fno else fn(ctx)
    if want == "combination" or (want == "all" and ctx["inputs"].get("include_combinations", True)):
        out += combo_candidates(ctx)
    return out
