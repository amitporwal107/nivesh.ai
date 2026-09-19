"""Builds the Simulation Lab page (the owner's Nivesh V5 design, 2026-09-19) from one run directory.

Every number on the page is read from the run's ledgers; nothing is typed in. Tabs that need runs which do not exist
yet (matrix A-H, comparison, permutations) say so instead of showing sample data. The page embeds Kite-derived prices,
so it is an internal file: it is written next to the run, not published."""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "lab_template.html")


def _num(x):
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return None if not np.isfinite(x) else float(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, pd.Timestamp):
        return str(x.date())
    return x


def _records(df: pd.DataFrame, cols) -> list:
    d = df.reindex(columns=cols)
    return [{k: _num(v) for k, v in zip(cols, row)} for row in d.itertuples(index=False, name=None)]


def build(run_dir: str) -> str:
    j = lambda n: json.load(open(os.path.join(run_dir, n)))  # noqa: E731
    res, score, modea = j("results.json"), j("scorecard.json"), j("mode_a.json")
    dq_replay, dq_year, corr = j("dq_sessions_replay.json"), j("dq_sessions_2022.json"), j("pick_correlations_replay.json")
    cand = pd.read_csv(os.path.join(run_dir, "candidates_replay.csv"), float_precision="round_trip")
    aud = pd.read_csv(os.path.join(run_dir, "audit_A_2022.csv"), float_precision="round_trip")
    rec = pd.read_csv(os.path.join(run_dir, "reconciliation_A.csv"), float_precision="round_trip")
    bars = pd.read_csv(os.path.join(run_dir, "bars_used_replay.csv"), float_precision="round_trip")
    expo = pd.read_csv(os.path.join(run_dir, "exposure_A.csv"))
    attempts = sorted(f for f in os.listdir(os.path.dirname(run_dir)) if f.startswith("run_attempt") and f.endswith(".log"))
    cand_cols = ["date", "rank", "symbol", "isin", "industry", "tbs_probability", "tbs_probability_calibrated_in_sample",
                 "direction_probability", "movement_probability", "value20", "atr_pct", "selection_status",
                 "rejection_reason", "entry_price", "stop_price", "target_price", "position_size", "risk_per_trade",
                 "prediction_id"]
    aud_cols = ["trade_id", "signal_date", "entry_date", "symbol", "model_rank", "tbs_probability", "movement_probability",
                "signal_close", "gap_pct", "intended_entry", "actual_entry", "slippage_bps_in", "initial_stop",
                "initial_target", "quantity", "initial_risk_inr", "stop_distance_atr", "mfe_pct", "mae_pct",
                "path_max_high_pct", "close_last_pct", "exit_date", "exit_session", "exit_level", "exit_price",
                "exit_reason", "exit_detail", "intrabar_ambiguous", "gross_inr", "slippage_inr", "charges_inr", "net_inr",
                "net_ret", "r_multiple", "dq_status", "dq_flags", "reconciliation", "raw_bar_check", "rc1_primary",
                "rc1_primary_excl_unreviewed_flags", "rc1_all"]
    rec_bad = rec[~rec.ok.astype(bool)]
    data = {
        "results": res, "scorecard": score, "modeA": modea, "dqReplay": dq_replay,
        "dqYear": {d: {"status": v["status"], "fail": v["fail_reasons"], "special": v["special_session"]} for d, v in dq_year.items()},
        "corr": corr, "candidates": _records(cand, cand_cols), "audit": _records(aud, aud_cols),
        "recMismatch": _records(rec_bad, list(rec.columns)), "recN": int(len(rec)),
        "bars": _records(bars, ["trade_id", "date", "open", "high", "low", "close", "volume", "source_file"]),
        "exposure": _records(expo, list(expo.columns)),
        "attempts": [{"file": a, "tail": open(os.path.join(os.path.dirname(run_dir), a)).read().strip().splitlines()[-1][:300]}
                     for a in attempts],
    }
    html = open(TEMPLATE).read().replace("/*__DATA__*/null", json.dumps(data, default=str, separators=(",", ":")))
    out = os.path.join(run_dir, "SimulationLab.html")
    with open(out, "w") as fh:
        fh.write(html)
    return out


if __name__ == "__main__":
    print(build(sys.argv[1]))
