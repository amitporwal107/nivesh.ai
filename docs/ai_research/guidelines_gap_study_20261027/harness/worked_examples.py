"""Throwaway harness: run the PRD §8 worked examples A-H through the repo's own functions. Read-only; no network."""
import json, sys
from datetime import date
sys.path.insert(0, "/work/backend")

from services.strategy_plan.candidates import size_position, scenario_levels
from services.strategy_plan.engine import compute_payoff
from services.strategy_engine import backtest as bt

def j(x): return json.dumps(x, default=str)
CAP = 10_000_000.0   # large capital so the 25% allocation cap never binds
def inputs(budget): return {"risk_budget_inr": budget, "capital": CAP, "max_allocation_pct": 25.0}
def sz(budget, entry, stop, lot=1, unit="shares"):
    s = size_position(inputs(budget), risk_per_unit=abs(entry - stop), value_per_unit=entry, unit=unit, lot_units=lot, per_unit_label="x")
    return {k: s.get(k) for k in ("status", "quantity", "units", "risk_at_stop_inr", "binding", "reason")}
def lv(entry, stop, up=True):
    return {l["name"]: l["price"] for l in scenario_levels(entry, up, stop, None, None)}

# routes.positional._trade_scenario (desk single-trade calculator); import may fail for env reasons -> report
try:
    from routes.positional import _trade_scenario
except Exception as e:  # noqa
    _trade_scenario = None
    print("trade_scenario import failed:", type(e).__name__, str(e)[:200])
def ts(**kw):
    if _trade_scenario is None: return None
    r = _trade_scenario(**kw)
    return {"valid": r["valid"], "problems": [p["code"] for p in r.get("problems") or []],
            "qty": (r.get("sizing") or {}).get("quantity"), "binding": (r.get("sizing") or {}).get("binding"),
            "loss_at_stop": (r.get("outcomes") or {}).get("loss_at_stop"), "loss_at_stop_net": (r.get("outcomes") or {}).get("loss_at_stop_net"),
            "profit_at_target": (r.get("outcomes") or {}).get("profit_at_target"),
            "warnings": [w["code"] for w in r.get("warnings") or []]}

print("A size_position", j(sz(3000, 1005, 970)), "levels", j(lv(1005, 970)))
print("A trade_scenario", j(ts(entry=1005, stop=970, target=1075, capital=CAP, risk_budget=3000)))
print("B size_position", j(sz(2500, 882, 868)), "levels", j(lv(882, 868)))
print("C size_position", j(sz(2000, 522, 517)), "levels", j(lv(522, 517)), "ATR stop 522-2x2.5 =", 522 - 2 * 2.5)
print("D size_position", j(sz(2500, 675, 686)), "levels(short)", j(lv(675, 686, up=False)))
print("D trade_scenario", j(ts(entry=675, stop=686, target=653, capital=CAP, risk_budget=2500)))
print("E size_position(lot 100)", j(sz(2500, 1250, 1225, lot=100, unit="lots")), "levels", j(lv(1250, 1225)))
print("E trade_scenario(lot 100)", j(ts(entry=1250, stop=1225, target=1300, capital=CAP, risk_budget=2500, lot_size=100)))
print("G size_position(budget 2500 on A's levels)", j(sz(2500, 1005, 970)))

# F: bull call spread through the payoff engine, gross (costs 0) and with the engine's default costs
legs = [{"kind": "option", "side": "buy", "quantity": 1, "lot_size": 50, "entry_price": 220, "expiry": "2026-11-26", "strike": 25000, "option_type": "call"},
        {"kind": "option", "side": "sell", "quantity": 1, "lot_size": 50, "entry_price": 130, "expiry": "2026-11-26", "strike": 25200, "option_type": "call"}]
for label, costs in (("gross", {"slippage_pct": 0, "brokerage_per_side": 0}), ("default costs", None)):
    body = {"underlying": "NIFTY", "reference_price": 25000, "legs": legs, "grid": {"from_pct": -5, "to_pct": 5, "points": 201}, "as_of": "2026-10-26"}
    if costs: body["costs"] = costs
    r = compute_payoff(body, date(2026, 10, 26))
    ex = r["expiry"] or {}
    print("F payoff", label, j({"valid": r["valid"], "problems": r["problems"], "max_loss": ex.get("max_loss"), "max_profit": ex.get("max_profit"),
                                 "breakevens": ex.get("breakevens"), "net_premium": ex.get("net_premium"), "capital_at_risk": r.get("capital_at_risk")}))
    car = r.get("capital_at_risk")
    s = size_position(inputs(2500), risk_per_unit=car, value_per_unit=car, unit="lots", lot_units=1, per_unit_label="x")
    print("F sizing vs Rs2500 budget", label, j({k: s.get(k) for k in ("status", "quantity", "reason")}))

# H: ATR trailing stop in the DSL backtest exit logic
def trade():
    t = bt.BacktestTrade(symbol="X", entry_date=date(2026, 10, 1), entry_price=1000.0, score=None, stoploss_price=970.0, target_price=5000.0, quantity=10)
    t.__dict__["_atr"] = 20.0; t.__dict__["_high_water"] = 1000.0
    return t
t = trade()
out = bt._maybe_close_trade(t, date(2026, 10, 5), {"high": 1080, "low": 1045, "close": 1070}, sl_pct=0.03, target_rr=2, max_hold=30,
                            trailing_atr_mult=2.0, brokerage_inr=20, slippage_pct=0.0005)
print("H trail after bar(high 1080, low 1045)", j({"stop_now": t.stoploss_price, "closed": out is not None}))
t = trade()
out = bt._maybe_close_trade(t, date(2026, 10, 5), {"high": 1080, "low": 1035, "close": 1070}, sl_pct=0.03, target_rr=2, max_hold=30,
                            trailing_atr_mult=2.0, brokerage_inr=20, slippage_pct=0.0005)
print("H same bar sets high 1080 AND low 1035", j({"stop_now": t.stoploss_price, "exit_reason": t.exit_reason, "exit_price": t.exit_price}))
# Gap-through-stop: next bar opens 950 (row has no open field), low 940, stop 970
t = trade()
out = bt._maybe_close_trade(t, date(2026, 10, 5), {"open": 950, "high": 955, "low": 940, "close": 945}, sl_pct=0.03, target_rr=2, max_hold=30,
                            trailing_atr_mult=None, brokerage_inr=20, slippage_pct=0.0005)
print("gap-through-stop (open 950 < stop 970)", j({"exit_reason": t.exit_reason, "exit_price": round(t.exit_price, 4), "pnl_abs": round(t.pnl_abs, 2)}))
