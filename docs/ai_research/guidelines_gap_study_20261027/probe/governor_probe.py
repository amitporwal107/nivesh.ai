"""Probe the pure risk functions on the clean checkout (read-only mount, no network)."""
import sys, json
sys.path.insert(0, "/work/backend")
from services.ai_trader.risk_governor import evaluate, Intent, Portfolio, Position, Market, DEFAULT_LIMITS
from services.risk_gate import gate
from services.risk_gate.contract import RiskRequest
from services import desk_strategy_trades as strat

def show(label, d):
    print(f"{label}: action={d.action} req={d.requested_qty} approved={d.approved_qty} codes={[r.code for r in d.reasons]}")

# P1: PRD Example A sized by the governor at capital 3,00,000 (1% = 3,000 budget), all context unknown
cap = 300_000.0
i = Intent("EXA", quantity=85, entry_price=1005, stop_price=970, target_price=1075)
show("P1 ExampleA, drawdown/VIX/regime/sector/ADV unknown", evaluate(i, Portfolio(capital=cap), Market()))
# P2: risk per trade with costs: governor's approved risk vs net loss at stop using desk cost model
from services.strategy_engine.backtest import DEFAULT_SLIPPAGE_PCT, DEFAULT_BROKERAGE_INR
q=85; gross=q*(1005-970); costs = q*1005*DEFAULT_SLIPPAGE_PCT + DEFAULT_BROKERAGE_INR + q*970*DEFAULT_SLIPPAGE_PCT + DEFAULT_BROKERAGE_INR
print(f"P2 qty 85: gross risk {gross:.2f} vs budget {cap*0.01:.2f}; net-of-cost loss at stop {gross+costs:.2f} (slip {DEFAULT_SLIPPAGE_PCT}, brokerage {DEFAULT_BROKERAGE_INR}/side) -> exceeds budget: {gross+costs > cap*0.01}")
# P3: gap stress: same position, open gaps 10% below the stop
gap_fill = 970*0.90
print(f"P3 gap-through-stop to {gap_fill:.1f}: loss {q*(1005-gap_fill):.2f} = {q*(1005-gap_fill)/cap*100:.2f}% of capital (governor limit 1%) -- no gap stress in governor")
# P4: drawdown 40% but drawdown unknown flag vs known
show("P4a drawdown known 40%", evaluate(i, Portfolio(capital=cap, drawdown_pct=40.0), Market()))
show("P4b drawdown None (unmarked F&O open)", evaluate(i, Portfolio(capital=cap, drawdown_pct=None), Market()))
# P5: total open risk: 9 open positions each with full 1% risk -> governor has no open-risk sum; exposure cap only
pos = [Position(f"S{k}", 30, 1000.0, sector=f"SEC{k}") for k in range(9)]  # 9 x 30k = 2.7L gross = 90% of 3L
show("P5 9 open positions, gross 90% of capital", evaluate(Intent("NEW", 85, 1005, 970, 1075, sector="X"), Portfolio(capital=cap, positions=pos), Market()))
# P6: inflated capital (user-chosen initial_capital up to 1e10) -> 1% of a fake number
show("P6 initial_capital=1e8 (paper account is 10L)", evaluate(Intent("EXA", 2857, 1005, 970, 1075), Portfolio(capital=1e8), Market()))
# P7: realised daily loss uses realised P&L only: unrealised -10% of capital does not halt
show("P7 realised today 0, (unrealised loss invisible)", evaluate(i, Portfolio(capital=cap, realized_pnl_today=0.0), Market()))
show("P7b realised today -9000 (3%)", evaluate(i, Portfolio(capital=cap, realized_pnl_today=-9000.0), Market()))

# Risk gate: pure decide() on snapshots
snap = lambda req, refs=None, opn="n/a": gate.bson_safe({"request": req.model_dump(), "today": "2026-10-27", "controls": {"kill_switch": False, "halted": False, "reason": None}, "live_allowed": None, "references": refs or {}, "open_structures": opn})
cash = RiskRequest(correlation_id="c", user_id="u", actor_id="u", mode="paper", path="desk_paper_trade", action="open", instrument="cash", symbol="EXA", quantity=85, capital_at_risk_rs=85*1005)
run, capv = gate.decide(cash, snap(cash))
print("G1 cash 85 x 1005 (notional as capital at risk):", "block" if run.reasons else "allow", capv, [c.check+":"+c.status for c in run.checks])
big = RiskRequest(correlation_id="c", user_id="u", actor_id="u", mode="paper", path="desk_paper_trade", action="open", instrument="cash", symbol="EXA", quantity=199, capital_at_risk_rs=199*1005)
run, capv = gate.decide(big, snap(big))
print("G2 cash 199 x 1005 notional 199,995 with stop 970 (risk 6,965 = 2.3% of 3L):", "block" if run.reasons else "allow", capv)
legs = [{"kind":"option","side":"buy","lots":1,"lot_size":50,"entry_price":220,"expiry":"2026-11-25","strike":25000,"option_type":"call"},
        {"kind":"option","side":"sell","lots":1,"lot_size":50,"entry_price":130,"expiry":"2026-11-25","strike":25200,"option_type":"call"}]
st = RiskRequest(correlation_id="c", user_id="u", actor_id="u", mode="paper", path="desk_paper_trade", action="open", instrument="structure", symbol="NIFTY", legs=legs)
refs = {"2026-11-25": {"listed": True, "lot_size": 50, "source": "probe", "as_of": "2026-10-27", "error": None}}
run, capv = gate.decide(st, snap(st, refs, 0))
print("G3 PRD Example F bull call spread (max loss 4,500 vs PRD budget 2,500):", "block" if run.reasons else "allow", "capital_at_risk", capv)
run, capv = gate.decide(st, snap(st, {}, 0))
print("G4 same, exchange reference unreadable:", "block" if run.reasons else "allow", [r.code for r in run.reasons])
# desk strategy trade without the gate: short future allowed? and its reservation
sf = {"kind":"strategy","underlying":"NIFTY","direction":"bearish","family":"short_future","reference_price":25000,
      "legs":[{"kind":"future","side":"sell","lots":1,"lot_size":75,"entry_price":25000,"expiry":"2026-11-25","price_source":"probe"}],
      "signal":{"signal_at":"2026-10-26","rule_version":"probe","evidence_summary":"probe"}}
try:
    doc = strat.new_strategy_trade("u", sf)
    print("D1 desk validator, short future (gate OFF path): accepted; risk:", doc["risk"], "; reservation exposure_rs:", strat.exposure_rs(doc))
except Exception as e:
    print("D1 desk validator refused:", type(e).__name__, getattr(e, "code", e))
sfl = dict(sf); sfl["legs"] = [dict(sf["legs"][0], lot_size=1)]
doc = strat.new_strategy_trade("u", sfl)
print("D2 same with lot_size=1 (NIFTY exchange lot is not 1): accepted, exposure_rs", strat.exposure_rs(doc))
req_sf = RiskRequest(correlation_id="c", user_id="u", actor_id="u", mode="paper", path="desk_paper_trade", action="open", instrument="structure", symbol="NIFTY", legs=sf["legs"])
run, capv = gate.decide(req_sf, snap(req_sf, {"2026-11-25": {"listed": True, "lot_size": 75, "source": "probe", "as_of": "2026-10-27", "error": None}}, 0))
print("G5 gate ON, short future:", "block" if run.reasons else "allow", [r.code for r in run.reasons])
