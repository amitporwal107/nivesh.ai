# Probe: the Top 10 / AI-watchlist "Paper trade" body for FEDERALBNK on 26 Oct (scanner levels 316.89 / 312.18 / 355.50,
# no entry_rule -> at_once), opened on the evening of 26 Oct, run over the real 26 Oct bar plus a hypothetical next session.
import sys
sys.path.insert(0, "/work/backend")
from datetime import date, datetime, timezone
from services import desk_trading as svc
now = datetime(2026, 10, 26, 14, 30, tzinfo=timezone.utc)   # 20:00 IST on 26 Oct
body = {"symbol": "FEDERALBNK", "quantity": 100, "entry_price": 316.89, "stop_price": 312.18, "target_price": 355.5,
        "source": {"kind": "scanner", "signal_date": "2026-10-26"}}
t = svc.new_trade("u1", body, now)
print("entry_rule stored:", t["entry_rule"])
real_26 = {"date": date(2026, 10, 26), "open": 341.0, "high": 344.8, "low": 337.2, "close": 344.4}
hypo_27 = {"date": date(2026, 10, 27), "open": 345.0, "high": 356.0, "low": 343.0, "close": 355.0}   # HYPOTHETICAL bar
sim = svc.simulate(t, [real_26, hypo_27])
print("entry_status", sim["entry_status"], "fill", sim["sim_entry_price"], "| exit", sim["exit"], "| flags", [f["code"] for f in sim["flags"]])
print("gross booked:", svc.realized_pnl(t, sim["exit"]["exit_price"]), "(a real buyer at the 26 Oct close 344.40 would have made", round((355.5 - 344.4) * 100, 2), ")")
t2 = svc.new_trade("u1", {**body, "entry_rule": "pullback_to"}, now)
sim2 = svc.simulate(t2, [real_26, hypo_27])
print("same levels with entry_rule pullback_to -> entry_status", sim2["entry_status"], "exit", sim2["exit"])
