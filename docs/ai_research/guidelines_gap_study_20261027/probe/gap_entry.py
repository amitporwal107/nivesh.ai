# Probe: a break_above paper trade whose entry session OPENS above the trigger. Pure functions only.
import sys, asyncio
sys.path.insert(0, "/work/backend")
from datetime import date, datetime, timezone
from services import desk_trading as svc
now = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
t = svc.new_trade("u1", {"symbol": "TEST", "quantity": 100, "entry_price": 100.0, "stop_price": 95.0, "target_price": 110.0,
                         "entry_rule": "break_above"}, now)
bars = [
    {"date": date(2026, 10, 20), "open": 99.0, "high": 99.5, "low": 98.0, "close": 99.0},
    {"date": date(2026, 10, 21), "open": 104.0, "high": 106.0, "low": 103.0, "close": 105.0},   # gaps above the trigger: fill = open 104
    {"date": date(2026, 10, 22), "open": 106.0, "high": 111.0, "low": 105.0, "close": 110.5},   # target 110 touched
]
sim = svc.simulate(t, bars)
print("entry_status", sim["entry_status"], "| sim fill", sim["sim_entry_price"], "| exit", sim["exit"]["exit_reason"], sim["exit"]["exit_price"], "| flags", [f["code"] for f in sim["flags"]])
print("gross P&L close_trade books = realized_pnl(trade, exit) =", svc.realized_pnl(t, sim["exit"]["exit_price"]),
      "| P&L from the simulated fill =", round((sim["exit"]["exit_price"] - sim["sim_entry_price"]) * t["quantity"], 2))
class FakeColl:
    async def update_one(self, *a, **k):
        class R: matched_count = 1
        return R()
    async def find_one(self, *a, **k): return {"user_id": "u1"}
    async def insert_one(self, *a, **k): return None
class FakeDB(dict):
    def __getitem__(self, k): return FakeColl()
stored, mine = asyncio.run(svc.close_trade(FakeDB(), t, **sim["exit"], sim=sim))
print("close_trade stored: realized_pnl_rs", stored["realized_pnl_rs"], "costs_rs", stored["costs_rs"], "net", stored["net_pnl_rs"], "sim_entry_price", stored["sim_entry_price"])
