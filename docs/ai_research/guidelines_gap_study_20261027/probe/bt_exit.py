# Probe the shipped backtest exit function (services/strategy_engine/backtest._maybe_close_trade). Pure; no I/O.
import sys
sys.path.insert(0, "/work/backend")
from datetime import date
from services.strategy_engine.backtest import BacktestTrade, _maybe_close_trade
def trade():
    t = BacktestTrade(symbol="X", entry_date=date(2026, 1, 1), entry_price=1000.0, score=0.0, stoploss_price=970.0, target_price=1200.0, quantity=1)
    t.__dict__["_atr"] = 20.0; t.__dict__["_high_water"] = 1000.0
    return t
kw = dict(sl_pct=0.03, target_rr=6.0, max_hold=30, trailing_atr_mult=2.0, brokerage_inr=0.0, slippage_pct=0.0)
# 1) PRD Example H: highest 1080, ATR 20, x2 -> trail 1040; a later bar that does not make a new high must not loosen it.
t = trade()
print("day2 bar H1080 L1050 ->", _maybe_close_trade(t, date(2026,1,2), {"high":1080,"low":1050,"close":1070}, **kw), "stop now", t.stoploss_price)
print("day3 bar H1060 L1045 ->", _maybe_close_trade(t, date(2026,1,3), {"high":1060,"low":1045,"close":1050}, **kw), "stop now", t.stoploss_price, "(never loosened)")
# 2) Same bar: high 1080 then low 1035. The bar's OWN high raises the stop to 1040 before its low is checked -> exit at 1040.
t = trade()
r = _maybe_close_trade(t, date(2026,1,2), {"high":1080,"low":1035,"close":1060}, **kw)
print("same-bar H1080 L1035 -> exit", r.exit_reason if r else None, "at", r.exit_price if r else None, "(assumes the high came before the low)")
# 3) Gap through the stop: bar opens/trades wholly below the stop -> filled AT the stop, not at the open.
t = trade()
r = _maybe_close_trade(t, date(2026,1,2), {"open":930,"high":940,"low":920,"close":925}, **{**kw, "trailing_atr_mult": None})
print("gap bar O930 H940 L920 (stop 970) -> exit", r.exit_reason, "at", r.exit_price)
# 4) Time exit counts calendar days, not sessions.
t = trade()
r = _maybe_close_trade(t, date(2026,1,31), {"high":1010,"low":990,"close":1000}, **{**kw, "trailing_atr_mult": None})
print("31 Jan (30 calendar days) -> exit", r.exit_reason if r else None, "holding_days", r.holding_days if r else None)
