"""Counterfactual: the staging desk cash entries (values copied from the read-only query output) evaluated by the
AI-trader risk governor against the ACTUAL book open at each entry time. Capital = the paper account's 10,00,000."""
import sys
sys.path.insert(0, "/work/backend")
from services.ai_trader.risk_governor import evaluate, Intent, Portfolio, Position, Market
CAP = 1_000_000.0
FS, CG = "Financial Services", "Capital Goods"
N = ("NORTHARC", 417, 280.66, 268.67, 304.64, FS)
I1 = ("ICICIBANK", 89, 1400.2, 1363.26, 1474.07, FS)
H = ("HAL", 25, 4989.0, 4822.25, 5322.51, CG)
pos = lambda t: Position(t[0], t[1], t[2], t[5])
steps = [("NORTHARC 10-19", N, []), ("ICICIBANK#1 10-20", I1, [N]), ("HAL#1 10-20", H, [N, I1]),
         ("HAL#2 10-20", H, [N, I1, H]), ("HAL#3 10-21", H, [I1, H, H]), ("ICICIBANK#2 10-21", I1, [I1, H, H, H])]
for label, t, book in steps:
    d = evaluate(Intent(t[0], t[1], t[2], t[3], t[4], sector=t[5]), Portfolio(capital=CAP, positions=[pos(b) for b in book]), Market())
    blocking = [(r.code, r.value, r.limit) for r in d.reasons if r.severity != "info"]
    print(f"{label:20} asked {t[1]:>4} -> {d.action:7} approved {d.approved_qty:>4}  {blocking}")
