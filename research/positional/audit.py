"""Extreme-trade audit required before any verdict (PREREGISTRATION.md §7; owner's rule after H-A): for each arm, the
10 best and 10 worst closed trades by net P&L are checked against the raw daily bars.

Checks per trade:
  A. entry price inside the entry session's [low, high] widened by 2x the slippage bucket (fills include slippage);
  B. exit price inside the exit session's [low, high] widened the same way;
  C. volume > 0 on the entry and exit sessions;
  D. no close-to-close move beyond +/-20% inside the holding window (a possible unadjusted corporate action);
  E. the symbol is not an ETF (name contains 'ETF').
A trade failing any check is listed; an arm with a failing extreme trade is reported INVALID, not re-run.
run: /app/research/tpd3_forward/venv/bin/python audit.py <results json>
"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "phase1"))
import phase1_common as C  # noqa: E402

OUT = "/app/research/positional"
ARMS = ("E1", "E2", "E3", "C-E2", "C-E3", "D1")
WIDEN = 0.004          # 2 x the widest slippage bucket (0.20% per side)


def audit_arm(trades: pd.DataFrame, bars: pd.DataFrame, names: dict) -> dict:
    t = trades[trades.realised].copy()
    if t.empty:
        return {"checked": 0, "failures": []}
    t["net"] = t.net_pnl.astype(float)
    pick = pd.concat([t.nlargest(10, "net"), t.nsmallest(10, "net")]).drop_duplicates(["signal_id"])
    b = bars.set_index(["symbol", "date"]).sort_index()
    fails = []
    for r in pick.itertuples(index=False):
        sym, ed, xd = r.symbol, pd.Timestamp(r.entry_date), pd.Timestamp(r.exit_date)
        issues = []
        try:
            eb, xb = b.loc[(sym, ed)], b.loc[(sym, xd)]
        except KeyError:
            fails.append({"signal_id": r.signal_id, "issues": ["no bar for the entry or exit session"]})
            continue
        ep, xp = float(r.entry_price), float(r.exit_price)
        if not (eb.low * (1 - WIDEN) <= ep <= eb.high * (1 + WIDEN)):
            issues.append(f"A entry {ep} outside [{eb.low}, {eb.high}]")
        if not (xb.low * (1 - WIDEN) <= xp <= xb.high * (1 + WIDEN)):
            issues.append(f"B exit {xp} outside [{xb.low}, {xb.high}]")
        if eb.volume <= 0 or xb.volume <= 0:
            issues.append("C zero volume")
        win = bars[(bars.symbol == sym) & (bars.date >= ed) & (bars.date <= xd)].sort_values("date")
        prev = bars[(bars.symbol == sym) & (bars.date < ed)].sort_values("date").tail(1)
        closes = pd.concat([prev.close, win.close]).to_numpy()
        if len(closes) > 1:
            jumps = abs(closes[1:] / closes[:-1] - 1)
            if (jumps > 0.20).any():
                issues.append(f"D close-to-close move {100 * jumps.max():.1f}% in the window")
        if "ETF" in str(names.get(sym, "")).upper():
            issues.append("E ETF")
        if issues:
            fails.append({"signal_id": r.signal_id, "net_pnl": r.net, "issues": issues})
    return {"checked": int(len(pick)), "failures": fails}


def main(results_path: str):
    res = json.load(open(results_path))
    n5 = pd.read_csv(C.N500)
    names = dict(zip(n5.Symbol, n5["Company Name"]))
    bars = C.load_daily(set(n5.Symbol))
    out = {}
    for arm in ARMS:
        path = f"{OUT}/trades_{arm}.csv"
        tr = pd.read_csv(path, parse_dates=["entry_date", "exit_date"]) if os.path.exists(path) else pd.DataFrame()
        a = audit_arm(tr, bars, names) if len(tr) else {"checked": 0, "failures": []}
        a["status"] = "INVALID" if a["failures"] else "CLEAN"
        out[arm] = a
        print(arm, a["status"], a["checked"], a["failures"][:3])
    dest = results_path.replace(".json", "_audit.json")
    json.dump({"results": os.path.basename(results_path), "arms": out}, open(dest, "w"), indent=1, default=str)
    print(dest)


if __name__ == "__main__":
    main(sys.argv[1])
