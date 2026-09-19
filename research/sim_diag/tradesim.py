"""Mode B trade-isolated simulator (Consecutive-Session Simulation PRD v1.0 §6, §7 Mode B, §10, §11, §14).

Each trade is simulated alone at a fixed notional with the risk engine's own fill, stop, target and cost functions
(tpd_model/risk/execution.py and costs.py): Decimal prices, exact comparisons, circuit locks, paisa-rounded fills. It
shares no code with research/model_v5/labels.py, which reconcile.py compares it with, trade by trade.

Configuration A is the H#32 convention (PREREGISTRATION_P2_P3 §3-§4):
- entry at the s1 open;
- stop and target at 0.98 and 1.05 × the raw open;
- slippage from the decision day's value20 bucket, on both legs;
- at most 5 sessions, with a missing bar skipped;
- time exit at the last available close within s1..s5.

The other models in PROPOSED are the PRD §10-§11 proposal. They are tested here but are not frozen: nothing runs them
on market data before the matrix pre-registration (D5) is approved.

Entry bar: an entry inside the bar (buy-stop, limit, typical price) cannot know whether the bar's low came before or
after the fill. The bar is then evaluated from the entry price with the stop checked first, and flagged.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from dataclasses import dataclass, field, replace
from decimal import ROUND_FLOOR, Decimal
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.normpath(os.path.join(HERE, "..", "..", "backend"))
sys.path.insert(0, BACKEND)

from nidp.services.tpd_model.risk import costs as CC  # noqa: E402
from nidp.services.tpd_model.risk import execution as EX  # noqa: E402

D = Decimal
ENTRY_KIND = {"NEXT_OPEN": "MOO", "OPEN_CONFIRMATION": "BUY_STOP", "LIMIT_ENTRY": "LIMIT", "VWAP_PROXY": "TYPICAL"}
EXIT_REASON = {"GAP_THROUGH": "GAP_THROUGH_STOP", "STOP": "STOP_HIT", "TARGET": "TARGET_HIT",
               "GAP_OVER_TARGET": "TARGET_HIT", "TIME": "TIME_EXIT", "CARRIED": "LIQUIDITY_EXIT",
               "BLOCKED_STOP": "LIQUIDITY_EXIT"}     # a stop reached, then filled late because the session was locked


@dataclass(frozen=True)
class Spec:
    name: str
    entry: str = "NEXT_OPEN"                  # NEXT_OPEN | OPEN_CONFIRMATION | LIMIT_ENTRY | VWAP_PROXY
    stop: str = "FIXED"                       # FIXED | ATR | STRUCTURE | VOL_ADJ | NONE
    target: str = "FIXED"                     # FIXED | R_MULTIPLE | NONE
    stop_pct: Decimal = D("2")
    target_pct: Decimal = D("5")
    target_r: Decimal = D("2")
    atr_mult: Decimal = D("1.5")
    vol_mult: Decimal = D("1.5")
    structure_buffer_pct: Decimal = D("0.1")
    stop_bounds_pct: tuple = (D("1"), D("8"))  # STRUCTURE and VOL_ADJ stops are kept 1-8% below the entry
    confirm_buffer_pct: Decimal = D("0.1")
    limit_discount_pct: Decimal = D("0.5")
    max_chase_pct: Optional[Decimal] = None   # NO_ENTRY when the s1 open is more than this % above the D close
    notional: Decimal = D("50000")
    sessions: int = 5
    carry_sessions: int = 25                  # a position that cannot be sold (locked lower) is held until sellable
    costs_on: bool = True
    slippage_basis: str = "DECISION"          # DECISION (H#32: D's value20) | FILL (the engine: the fill day's value20)
    policy: str = "STOP_FIRST"
    participation_pct: Decimal = D("100")     # H#32 had no participation limit
    frozen: bool = False


CONFIG_A = Spec("A", frozen=True)
PROPOSED = {                                  # PRD §10-§11 proposal: NOT frozen, not run before D5 approval
    "B": Spec("B", stop="ATR", target="R_MULTIPLE", target_r=D("2")),
    "C": Spec("C", entry="OPEN_CONFIRMATION"),
    "E": Spec("E", costs_on=False),
    "H": Spec("H", stop="NONE", target="NONE"),
    "STRUCTURE": Spec("STRUCTURE", stop="STRUCTURE", target="R_MULTIPLE", target_r=D("2")),
    "VOL_ADJ": Spec("VOL_ADJ", stop="VOL_ADJ", target="R_MULTIPLE", target_r=D("2.5")),
    "LIMIT": Spec("LIMIT", entry="LIMIT_ENTRY"),
    "VWAP": Spec("VWAP", entry="VWAP_PROXY"),
}


@dataclass
class Window:
    """One (symbol, decision day D): the D bar facts and the calendar sessions after D (s1, s2, ...)."""
    symbol: str
    decision_date: dt.date
    d_close: Decimal
    d_high: Decimal
    d_low: Decimal
    value20_d: float
    atr_pct: float                             # ATR(14) as % of the D close (the v4 feature)
    sigma20: Optional[float] = None            # std of daily returns over 20 sessions to D (fraction)
    low10: Optional[Decimal] = None            # lowest low of the 10 sessions to D
    dates: list = field(default_factory=list)  # calendar sessions s1, s2, ... (s1..s5 plus carry sessions)
    bars: list = field(default_factory=list)   # Bar or None (no bar that session), aligned with dates
    value20_by_date: dict = field(default_factory=dict)


def dec(x) -> Decimal:
    return Decimal(repr(float(x)))


def _slip(spec: Spec, cm, w: Window, on: dt.date) -> Decimal:
    if not spec.costs_on:
        return D(0)
    if spec.slippage_basis == "DECISION":
        return CC.slippage_pct(cm, w.value20_d)
    if spec.slippage_basis == "FILL":
        if on not in w.value20_by_date:
            raise ValueError(f"{w.symbol}: no value20 on the fill day {on}")
        return CC.slippage_pct(cm, w.value20_by_date[on])
    raise ValueError(f"unknown slippage basis {spec.slippage_basis!r}")


def _bounded(base: Decimal, stop: Decimal, bounds: tuple) -> Decimal:
    lo, hi = bounds
    return min(max(stop, base * (1 - hi / 100)), base * (1 - lo / 100))


def levels(spec: Spec, w: Window, base: Decimal) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """(stop, target) from the raw entry price `base` (before slippage), unrounded as in the H#32 rule."""
    if spec.stop == "FIXED":
        stop = base * (1 - spec.stop_pct / 100)
    elif spec.stop == "ATR":
        stop = base - spec.atr_mult * dec(w.atr_pct) / 100 * w.d_close
    elif spec.stop == "STRUCTURE":
        if w.low10 is None:
            raise ValueError(f"{w.symbol}: STRUCTURE stop needs low10")
        stop = _bounded(base, w.low10 * (1 - spec.structure_buffer_pct / 100), spec.stop_bounds_pct)
    elif spec.stop == "VOL_ADJ":
        if w.sigma20 is None:
            raise ValueError(f"{w.symbol}: VOL_ADJ stop needs sigma20")
        stop = _bounded(base, base * (1 - spec.vol_mult * dec(w.sigma20)), spec.stop_bounds_pct)
    elif spec.stop == "NONE":
        stop = None
    else:
        raise ValueError(f"unknown stop model {spec.stop!r}")
    if spec.target == "FIXED":
        target = base * (1 + spec.target_pct / 100)
    elif spec.target == "R_MULTIPLE":
        if stop is None:
            raise ValueError("an R-multiple target needs a stop")
        target = base + spec.target_r * (base - stop)
    elif spec.target == "NONE":
        target = None
    else:
        raise ValueError(f"unknown target model {spec.target!r}")
    return stop, target


def _costs(spec: Spec, cm, side: str, value: Decimal, on: dt.date) -> dict:
    if not spec.costs_on:
        return {c: D(0) for c in CC.COMPONENTS} | {"total": D(0), "retroactive": False}
    return CC.fill_costs(cm, "delivery", "NSE", side, value, dp_applies=(side == "SELL"), on_date=on, allow_retroactive=True)


def pnl(spec: Spec, cm, entry_px: Decimal, exit_px: Decimal, qty: int, entry_date: dt.date, exit_date: dt.date) -> dict:
    buy, sell = entry_px * qty, exit_px * qty
    cb, cs = _costs(spec, cm, "BUY", buy, entry_date), _costs(spec, cm, "SELL", sell, exit_date)
    net = sell - buy - cb["total"] - cs["total"]
    return {"buy_value": buy, "sell_value": sell, "costs_buy": cb, "costs_sell": cs, "charges": cb["total"] + cs["total"],
            "net_inr": net, "net_ret": net / buy}


def _qty(notional: Decimal, price: Decimal) -> int:
    return max(1, int((notional / price).to_integral_value(rounding=ROUND_FLOOR)))


def _no_entry(spec: Spec, w: Window, reason: str, **kw) -> dict:
    return {"config": spec.name, "symbol": w.symbol, "decision_date": w.decision_date, "status": "NO_ENTRY",
            "entry_rejection_reason": reason, **kw}


def simulate(spec: Spec, w: Window, cm) -> dict:
    """One trade. Returns the trade record (PRD §10, §11, §14 fields) with its fills and the bars it used."""
    if not w.bars or w.bars[0] is None:
        return _no_entry(spec, w, "NO_BAR_S1")
    s1, s1_date = w.bars[0], w.dates[0]
    if spec.max_chase_pct is not None and s1.open > w.d_close * (1 + spec.max_chase_pct / 100):
        return _no_entry(spec, w, "MAX_CHASE", gap_pct=float(s1.open / w.d_close - 1))
    kind = ENTRY_KIND[spec.entry]
    trigger = EX.px(w.d_high * (1 + spec.confirm_buffer_pct / 100)) if kind == "BUY_STOP" else None
    limit = EX.px(w.d_close * (1 - spec.limit_discount_pct / 100)) if kind == "LIMIT" else None
    slip_in = _slip(spec, cm, w, s1_date)
    probe = EX.fill_entry(kind, s1, qty=1, slippage_pct=slip_in, participation_pct=D(100), trigger=trigger, limit=limit)
    if probe.status == "NO_FILL":
        return _no_entry(spec, w, probe.reason)
    if kind == "MOO":
        base = s1.open
    elif kind == "BUY_STOP":
        base = max(s1.open, trigger)
    elif kind == "LIMIT":
        base = min(s1.open, limit)
    else:
        base = (s1.high + s1.low + s1.close) / 3
    stop, target = levels(spec, w, base)
    if stop is not None and stop >= base:
        return _no_entry(spec, w, "STOP_AT_OR_ABOVE_ENTRY")
    if target is not None and target <= base:
        return _no_entry(spec, w, "TARGET_AT_OR_BELOW_ENTRY")
    qty = _qty(spec.notional, probe.price)
    fill = EX.fill_entry(kind, s1, qty=qty, slippage_pct=slip_in, participation_pct=spec.participation_pct,
                         trigger=trigger, limit=limit)
    if fill.status == "NO_FILL":
        return _no_entry(spec, w, fill.reason)
    qty = fill.qty
    entry_px = fill.price
    entry_exact = base * (1 + slip_in / 100)

    flags, used = [], []
    intrabar_entry = kind != "MOO" and base != s1.open     # a buy-stop gapped over, or a limit gapped under, fills at the open
    exit_i = exit_level = exit_fill = None
    exit_detail, ambiguous = None, False
    last_i = None
    blocked = False
    horizon = spec.sessions + spec.carry_sessions
    for i in range(min(horizon, len(w.bars))):
        b = w.bars[i]
        if b is None:
            if i < spec.sessions:
                flags.append(f"NO_BAR_S{i + 1}")
            continue
        used.append(i)
        slip_out = _slip(spec, cm, w, w.dates[i])
        if blocked:
            # D7 (owner approved 2026-09-20): a stop that could not be filled because the session was locked does not
            # keep the old stop - the position leaves at the first price the market offers
            if EX.locked_lower(b):
                flags.append(f"LOCKED_LOWER_FULLDAY_S{i + 1}")
                continue
            exit_i, exit_level, exit_detail = i, b.open, "BLOCKED_STOP"
            exit_fill = EX.px(b.open * (1 - slip_out / 100))
            break
        if i >= spec.sessions:                  # carried past s5 only because a sale was impossible: sell at the open
            if EX.locked_lower(b):
                flags.append(f"LOCKED_LOWER_{'FULLDAY' if b.high == b.low else 'PARTIAL'}_S{i + 1}")
                continue
            exit_i, exit_level, exit_detail = i, b.open, "CARRIED"
            exit_fill = EX.px(b.open * (1 - slip_out / 100))
            break
        eval_bar = b
        if i == 0 and intrabar_entry:
            eval_bar = replace(b, open=base)      # the fill happened inside the bar: evaluate from the entry, stop first
            flags.append("ENTRY_BAR_ORDER_UNKNOWN")
        x = EX.exit_on_bar(eval_bar, stop, target, slip_out, spec.policy)
        if x.fill is not None and x.fill.status == "NO_FILL":
            # the bar never left the band (high == low), so no sale was possible at any price
            flags.append(f"LOCKED_LOWER_FULLDAY_S{i + 1}")
            blocked = True
            last_i = i
            continue
        if x.fill is not None:
            exit_i, exit_level, exit_fill, exit_detail, ambiguous = i, x.level, x.fill.price, x.fill.reason, x.ambiguous
            break
        last_i = i
        if i == spec.sessions - 1 or not any(w.bars[j] is not None for j in range(i + 1, min(spec.sessions, len(w.bars)))):
            c = EX.close_exit(b, slip_out)
            if c.status == "NO_FILL":
                flags.append(f"LOCKED_LOWER_{'FULLDAY' if b.high == b.low else 'PARTIAL'}_CLOSE_S{i + 1}")
                continue                          # carried into the next sessions
            exit_i, exit_level, exit_fill, exit_detail = i, b.close, c.price, "TIME"
            break
    if exit_i is None:                           # never sellable within the carry sessions: listed, never priced
        return {"config": spec.name, "symbol": w.symbol, "decision_date": w.decision_date, "status": "UNRESOLVED",
                "exit_reason": "MANUAL_REVIEW_REQUIRED", "flags": ";".join(flags)}

    exit_date = w.dates[exit_i]
    slip_out = _slip(spec, cm, w, exit_date)
    exit_exact = exit_level * (1 - slip_out / 100)
    p = pnl(spec, cm, entry_px, exit_fill, qty, s1_date, exit_date)
    qty_exact = _qty(spec.notional, entry_exact)
    p_exact = pnl(spec, cm, entry_exact, exit_exact, qty_exact, s1_date, exit_date)
    held = [w.bars[j] for j in used if j <= exit_i]
    window5 = [w.bars[j] for j in range(min(spec.sessions, len(w.bars))) if w.bars[j] is not None]
    after = [w.bars[j] for j in range(exit_i + 1, min(spec.sessions, len(w.bars))) if w.bars[j] is not None]
    gross = (exit_level - base) * qty
    slippage_inr = (entry_px - base) * qty + (exit_level - exit_fill) * qty
    risk_ps = (entry_px - stop) if stop is not None else None
    atr_inr = dec(w.atr_pct) / 100 * w.d_close
    rec = {
        "config": spec.name, "symbol": w.symbol, "decision_date": w.decision_date, "status": "CLOSED",
        "entry_method": spec.entry, "order_kind": kind, "entry_date": s1_date,
        "signal_close": w.d_close, "next_session_open": s1.open, "gap_pct": float(s1.open / w.d_close - 1),
        "intended_entry": base, "actual_entry": entry_px, "entry_exact": entry_exact,
        "slippage_in_pct": slip_in, "slippage_bps_in": float((entry_px / base - 1) * 10000),
        "fill_status": fill.status, "fill_quantity": qty, "qty_exact": qty_exact,
        "stop_method": spec.stop, "target_method": spec.target, "initial_stop": stop, "initial_target": target,
        "risk_per_share": risk_ps, "reward_per_share": (target - entry_px) if target is not None else None,
        "risk_reward_ratio": float((target - entry_px) / risk_ps) if (target is not None and risk_ps) else None,
        "stop_distance_atr": float((base - stop) / atr_inr) if (stop is not None and atr_inr) else None,
        "target_distance_atr": float((target - base) / atr_inr) if (target is not None and atr_inr) else None,
        "exit_date": exit_date, "exit_session": exit_i + 1, "exit_detail": exit_detail,
        "exit_reason": EXIT_REASON[exit_detail], "exit_level": exit_level, "exit_price": exit_fill, "exit_exact": exit_exact,
        "slippage_out_pct": slip_out, "intrabar_ambiguous": ambiguous,
        "mfe_pct": float(max(b.high for b in held) / base - 1), "mae_pct": float(min(b.low for b in held) / base - 1),
        "path_max_high_pct": float(max(b.high for b in window5) / base - 1),
        "path_min_low_pct": float(min(b.low for b in window5) / base - 1),
        "high_after_exit_pct": float(max(b.high for b in after) / base - 1) if after else None,
        "close_last_pct": float(window5[-1].close / base - 1),
        "gross_inr": gross, "slippage_inr": slippage_inr, "charges_inr": p["charges"], "net_inr": p["net_inr"],
        "gross_ret": float(exit_level / base - 1), "net_ret": float(p["net_ret"]), "net_ret_exact": float(p_exact["net_ret"]),
        "initial_risk_inr": risk_ps * qty if risk_ps is not None else None,
        "r_multiple": float(p["net_inr"] / (risk_ps * qty)) if risk_ps else None,
        "costs_retroactive": bool(p["costs_buy"]["retroactive"] or p["costs_sell"]["retroactive"]),
        "flags": ";".join(flags), "bars_used": [w.dates[j] for j in used if j <= exit_i],
        "fills": [{"side": "BUY", "date": s1_date, "price": entry_px, "qty": qty, "value": p["buy_value"], **p["costs_buy"]},
                  {"side": "SELL", "date": exit_date, "price": exit_fill, "qty": qty, "value": p["sell_value"],
                   **p["costs_sell"]}],
    }
    return rec
