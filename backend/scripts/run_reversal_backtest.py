"""Run the point-in-time reversal backtest (services/positional_engine/reversal_backtest.py) on files and write a report.

    python scripts/run_reversal_backtest.py --panel panel_history.csv.gz --warehouse wh_prices.csv \
        --industry wh_ind.csv --reference wh_ref.csv --actions tpd_ca_history.csv --out report.json

Inputs (read only): the NSE daily-file history (symbol, as_of_date, series, open, high, low, close, prev_close, volume),
the warehouse's nidp.prices_eod export (symbol, as_of_date, series, open_price, high_price, low_price, close_price,
prev_close, volume; preferred on overlapping dates), the NSE corporate-action history (splits and bonuses are
back-adjusted; dividends and rights are not), NSE industry per symbol and the ETF flag. Research only.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.positional_engine import reversal_backtest as bt  # noqa: E402
from services.positional_engine import reversal_rules as rr  # noqa: E402


def _f(x: str):
    return float(x) if x not in ("", None) else None


def _open(p: str):
    return gzip.open(p, "rt", newline="") if p.endswith(".gz") else open(p, newline="")


def load(panel: str, warehouse: str, reference: str, industry: str):
    rows: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    n_panel = n_wh = 0
    with _open(panel) as fh:
        for r in csv.DictReader(fh):
            if r["series"] != "EQ" or not r["close"]:
                continue
            rows[r["symbol"]][r["as_of_date"]] = {"d": r["as_of_date"], "o": _f(r["open"]), "h": _f(r["high"]), "l": _f(r["low"]),
                                                  "c": _f(r["close"]), "pc": _f(r["prev_close"]), "v": _f(r["volume"])}
            n_panel += 1
    with _open(warehouse) as fh:
        for r in csv.DictReader(fh):
            if r["series"] not in ("EQ", "BE") or not r["close_price"]:
                continue
            rows[r["symbol"]][r["as_of_date"]] = {"d": r["as_of_date"], "o": _f(r["open_price"]), "h": _f(r["high_price"]),
                                                  "l": _f(r["low_price"]), "c": _f(r["close_price"]), "pc": _f(r["prev_close"]),
                                                  "v": _f(r["volume"])}
            n_wh += 1
    etf = set()
    with open(reference, newline="") as fh:
        for r in csv.DictReader(fh):
            if r["is_etf"] in ("t", "true", "True", "1"):
                etf.add(r["symbol"])
    ind = {}
    with open(industry, newline="") as fh:
        for r in csv.DictReader(fh):
            ind[r["symbol"]] = r["industry"]
    by_sym: Dict[str, List[Dict[str, Any]]] = {}
    for sym, d in rows.items():
        if sym in etf:
            continue
        bars = [b for _, b in sorted(d.items()) if None not in (b["o"], b["h"], b["l"], b["c"]) and b["c"] > 0 and b["o"] > 0]
        # keep only stocks that ever traded at least the liquidity floor on one day (a necessary condition for the universe)
        if bars and max((b["c"] * (b["v"] or 0)) / 1e7 for b in bars) >= bt.UNIVERSE["min_traded_value_cr_20d"]:
            by_sym[sym] = bars
    return by_sym, ind, {"panel_rows": n_panel, "warehouse_rows": n_wh, "etf_symbols_dropped": len(etf),
                         "symbols_loaded": len(by_sym)}


def load_actions(path: str) -> List[Dict[str, Any]]:
    out = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            if r["action_type"] not in ("SPLIT", "BONUS") or r["series"] != "EQ" or not r["ex_date"]:
                continue
            f = bt.action_factor(r["action_type"], r["ratio"], _f(r["face_value_pre"]), _f(r["face_value_post"]))
            if f:
                out.append({"symbol": r["symbol"], "ex_date": r["ex_date"], "factor": f, "type": r["action_type"], "ratio": r["ratio"]})
    return out


def report(rec: Dict[str, Any], thresholds=(10.0, 15.0, 20.0)) -> Dict[str, Any]:
    ev = rec["events"]
    uf = rec["universe_fwd"]
    ts = sorted(uf)
    blocks = bt.split_blocks(ts)
    mom = bt.momentum_events(rec)
    out: Dict[str, Any] = {"version": bt.BACKTEST_VERSION, "rules_version": rr.RULES_VERSION, "coverage": rec["coverage"],
                           "blocks": {k: {"from": rec["calendar"][a], "to": rec["calendar"][b]} for k, (a, b) in blocks.items()},
                           "adjustments": rec["adjustments"], "universe": bt.UNIVERSE,
                           "costs": bt.COST_SCENARIOS, "cooldown_sessions": bt.COOLDOWN_SESSIONS, "results": {}}
    sets: Dict[str, Dict[float, List]] = {}
    for v in bt.VARIANTS[:-1]:
        sets[v] = {p: bt.select(ev, v, p) for p in thresholds}
    for v, byp in sets.items():
        out["results"][v] = {}
        for p, es in byp.items():
            out["results"][v][str(p)] = {
                "events_total": len(es), "symbols": len({e["symbol"] for e in es}), "dates": len({e["t"] for e in es}),
                "all": {f"h{h}": {sc: bt.stats(es, uf, h, sc, boot=(sc == "base")) for sc in bt.COST_SCENARIOS} for h in bt.HORIZONS},
                "blocks": {name: {f"h{h}": bt.stats(bt.in_block(es, blk, 0 if name == "out_of_sample" else max(bt.HORIZONS)), uf, h, "base")
                                  for h in bt.HORIZONS} for name, blk in blocks.items()}}
    out["results"]["momentum_continuation"] = {"events_total": len(mom), "symbols": len({e["symbol"] for e in mom}),
        "all": {f"h{h}": {sc: bt.stats(mom, uf, h, sc, boot=(sc == "base")) for sc in bt.COST_SCENARIOS} for h in bt.HORIZONS},
        "blocks": {name: {f"h{h}": bt.stats(bt.in_block(mom, blk, 0 if name == "out_of_sample" else max(bt.HORIZONS)), uf, h, "base")
                          for h in bt.HORIZONS} for name, blk in blocks.items()}}
    # market regime split for the 15 % technical reversal, 10-session horizon
    base15 = sets["technical_reversal"][15.0]
    out["regime_split_technical_reversal_15_h10"] = {
        r: bt.stats([e for e in base15 if rec["regime"].get(e["t"]) == r], uf, 10, "base") for r in ("uptrend", "downtrend")}
    out["sector_quadrant_split_technical_reversal_15_h10"] = {
        q: bt.stats([e for e in base15 if e["quadrant"] == q], uf, 10, "base") for q in ("leading", "improving", "weakening", "lagging", "unknown")}
    # variant choice from train + validation only (never reads out of sample)
    by_var = {v: {b: out["results"][v]["15.0"]["blocks"][b]["h10"] for b in ("train", "validation") if b in blocks}
              for v in bt.VARIANTS[:-1]}
    out["selected_variant_train_validation_h10_15pct"] = bt.choose_variant(by_var)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", required=True)
    ap.add_argument("--warehouse", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--industry", required=True)
    ap.add_argument("--actions", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--first-signal", default=None)
    ap.add_argument("--last-signal", default=None)
    a = ap.parse_args()
    by_sym, ind, load_info = load(a.panel, a.warehouse, a.reference, a.industry)
    print("loaded", load_info, flush=True)
    actions = load_actions(a.actions)
    print("actions", len(actions), flush=True)
    rec = bt.run(by_sym, ind, actions=actions, first_signal=a.first_signal, last_signal=a.last_signal)
    rep = report(rec)
    rep["load"] = load_info
    json.dump(rep, open(a.out, "w"), indent=1, default=str)
    print("events", len(rec["events"]), "momentum", len(rec["momentum"]), "coverage", rec["coverage"], flush=True)


if __name__ == "__main__":
    main()
