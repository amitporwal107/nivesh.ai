"""Positional study — the single pre-registered run (docs/ai_research/tpd3/positional/PREREGISTRATION.md, FROZEN
fe60155f). Builds the signals, runs the engine for each arm (primary, 2x slippage stress, stop ablation) and 200
random-entry controls per arm, and writes /app/research/positional/results_<stamp>.json with every input hash.
Run it ONCE:  /app/research/tpd3_forward/venv/bin/python run.py
`--signals-only` builds and COUNTS the signals (sample sizes, D1 mapping stats) and stops before any simulation, so the
data plumbing can be checked without seeing a single outcome. There is deliberately no other partial mode.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import multiprocessing as mp
import os
import subprocess
import sys
import time
from decimal import Decimal

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(HERE, "..", "..", "backend"))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "pit_audit"))

from nidp.services.tpd_model.risk import config as RC  # noqa: E402
from nidp.services.tpd_model.risk import costs as CC  # noqa: E402
from nidp.services.tpd_model.risk import engine as EN  # noqa: E402

import controls as K  # noqa: E402
import report as R  # noqa: E402
import signals as S  # noqa: E402
import snapshot as SN  # noqa: E402

OUT = "/app/research/positional"
FROZEN_CONFIG_HASH = "2289cfcf89598c31175d247e95a1bf22bb0193eeaf881c379d494173a5cf58f0"
EXITS = {"breakeven_at_r": Decimal("1"), "trail_at_r": Decimal("2"), "trail_atr_mult": Decimal("2"), "max_sessions": 5,
         "cost_estimate_pct_for_sizing": Decimal("0.30")}
SEEDS = range(1, 201)
ARM_ORDER = ("E1", "E2", "E3", "C-E2", "C-E3", "D1")

_G: dict = {}          # per-process shared state (fork)


def _run(sig, stops=True, slip=Decimal(1)):
    return EN.run(sig, None, _G["cfg"], _G["cm"], _G["sectors"], EXITS, allow_retroactive_costs=True,
                  stops_active=stops, slippage_mult=slip, prepared=_G["prepared"])


def _control(args):
    arm, seed = args
    rs = K.random_signals(arm, _G["arm_trades"][arm], _G["panel"], _G["sessions"], seed)
    if rs is None or len(rs) == 0:
        return arm, seed, None, 0
    res = _run(rs)
    t = res.trades
    closed = t[t.realised] if len(t) else t
    return arm, seed, (float(closed.r_multiple.mean()) if len(closed) else None), int(len(closed))


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--signals-only", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    t0 = time.time()
    cfg = RC.load_config("RISK-POS-1")
    assert RC.config_hash(cfg) == FROZEN_CONFIG_HASH, "RISK-POS-1 changed since the freeze"
    cm = CC.load_cost_model("zerodha-equity-v1")
    import pit_policy as P
    rule = P.load_policy()["categories"]["nse_filed_results"]["rule"]
    assert P.rule_complete_and_approved(rule), "R-NSE-RES-1 not approved: D1 must be BLOCKED"
    panel, eod, d1_stats, sectors = S.build_all(rule)
    idx = S.C.load_index()
    snap = SN.snapshots(set(panel.symbol))
    csig = SN.snapshot_signals(panel, snap, idx)
    signals = pd.concat([eod, csig], ignore_index=True)
    signals = signals[signals.symbol.isin(sectors)].reset_index(drop=True)
    bars = panel[["symbol", "date", "open", "high", "low", "close", "volume", "value20"]]
    print(f"panel {len(panel):,} rows {panel.symbol.nunique()} symbols {panel.date.min().date()}..{panel.date.max().date()}; "
          f"signals {signals.groupby('arm').size().to_dict()}; D1 {d1_stats}; snapshot rows {len(snap):,} "
          f"({time.time() - t0:.0f}s)", flush=True)
    if a.signals_only:
        by_month = signals.assign(m=pd.to_datetime(signals.date).dt.strftime("%Y-%m")).groupby(["arm", "m"]).size()
        print(by_month.unstack(0).fillna(0).astype(int).to_string())
        return None
    _G.update(cfg=cfg, cm=cm, sectors=sectors, prepared=EN.prepare_bars(bars), panel=panel,
              sessions=sorted(panel.date.dt.date.unique()))
    arms, arm_trades = {}, {}
    for arm in ARM_ORDER:
        s = signals[signals.arm == arm]
        prim = _run(s)
        stress = _run(s, slip=Decimal(2))
        abl = _run(s, stops=False)
        arm_trades[arm] = prim.trades if len(prim.trades) else pd.DataFrame(columns=["entry_date", "symbol", "realised", "exit_reason"])
        arms[arm] = {"signals": int(len(s)), "primary": R.metrics(prim, float(cfg.capital_inr), idx),
                     "stress_2x_slippage": R.metrics(stress, float(cfg.capital_inr), idx),
                     "stop_ablation": R.metrics(abl, float(cfg.capital_inr), idx)}
        os.makedirs(OUT, exist_ok=True)
        prim.trades.to_csv(f"{OUT}/trades_{arm}.csv", index=False)
        prim.equity.to_csv(f"{OUT}/equity_{arm}.csv", index=False)
        print(f"{arm}: signals {len(s)} closed {arms[arm]['primary']['trades_closed']} net "
              f"{arms[arm]['primary']['net_return_pct']:.2f}% ({time.time() - t0:.0f}s)", flush=True)
    _G["arm_trades"] = arm_trades
    jobs = [(arm, seed) for arm in ARM_ORDER for seed in SEEDS]
    with mp.get_context("fork").Pool(a.workers) as pool:
        ctl = pool.map(_control, jobs, chunksize=4)
    rand = {arm: [m for (x, _, m, _) in ctl if x == arm] for arm in ARM_ORDER}
    for arm in ARM_ORDER:
        arms[arm]["decision"] = R.verdict(arms[arm]["primary"], arms[arm]["stress_2x_slippage"], rand[arm])
    commit = subprocess.run(["git", "-C", HERE, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    out = {"generated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).isoformat(timespec="seconds"),
           "code_commit": commit, "prereg": "docs/ai_research/tpd3/positional/PREREGISTRATION.md @ fe60155f",
           "risk_config": {"id": cfg.config_id, "hash": RC.config_hash(cfg)}, "cost_model": cm.cost_model_id,
           "costs_retroactive": True, "exits": {k: str(v) for k, v in EXITS.items()}, "seeds": [SEEDS.start, SEEDS.stop - 1],
           "inputs": {"panel_sha256": sha(panel[["symbol", "date", "open", "high", "low", "close", "volume"]].astype(str).values.tolist()),
                      "signals_sha256": sha(signals.astype(str).values.tolist()),
                      "panel_range": [str(panel.date.min().date()), str(panel.date.max().date())],
                      "symbols": int(panel.symbol.nunique()), "snapshot_symbols": int(snap.symbol.nunique())},
           "d1_stats": d1_stats, "arms": arms, "runtime_s": round(time.time() - t0)}
    print(json.dumps({arm: arms[arm]["decision"]["provisional_verdict"] for arm in ARM_ORDER}), flush=True)
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    path = f"{OUT}/results_{stamp}.json"
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1, default=str)
    print(path, hashlib.sha256(open(path, "rb").read()).hexdigest())
    return out


if __name__ == "__main__":
    main()
