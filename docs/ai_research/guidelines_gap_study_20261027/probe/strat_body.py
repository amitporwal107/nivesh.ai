# Probe: does the body the F&O "Paper trade" button sends (top-actions.ts paperTradeBodyFor) pass new_strategy_trade?
import sys
sys.path.insert(0, "/work/backend")
from datetime import datetime, timezone
from services import desk_strategy_trades as strat
now = datetime(2026, 10, 27, 6, 0, tzinfo=timezone.utc)
body = {"kind": "strategy", "underlying": "NIFTY", "direction": "bullish", "family": "bull_call_spread",
        "reference_price": 25000.0,
        "legs": [{"kind": "option", "side": "buy", "lots": 1, "lot_size": 75, "entry_price": 220.0, "expiry": "2026-11-25",
                  "strike": 25000.0, "option_type": "call", "price_source": "eod chain"},
                 {"kind": "option", "side": "sell", "lots": 1, "lot_size": 75, "entry_price": 130.0, "expiry": "2026-11-25",
                  "strike": 25200.0, "option_type": "call", "price_source": "eod chain"}],
        "note": "Top by regime - fit 7.5"}
try:
    doc = strat.new_strategy_trade("u1", body, now)
    print("ACCEPTED", doc["status"], doc["stop_underlying"], doc["target_underlying"], doc["max_hold_sessions"])
except strat.Err as e:
    print("REFUSED code =", e.code)
body["signal"] = {"signal_at": "2026-10-26", "rule_version": "regime-fit-v1", "evidence_summary": "fit"}
doc = strat.new_strategy_trade("u1", body, now)
print("WITH SIGNAL ACCEPTED", doc["status"], "stop", doc["stop_underlying"], "target", doc["target_underlying"], "max_hold", doc["max_hold_sessions"], "events", [e["type"] for e in doc["events"]])
