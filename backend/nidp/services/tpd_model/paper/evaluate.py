"""Evaluation (rules_v1.json evaluation): trade-level and daily portfolio-level results per mode, benchmarks, probability
buckets, cost sensitivity and the pre-registered 'established' rule. One sample and one portfolio at a time — forward
and replay are never pooled (TC-P12, TC-P18).

Overlap (PRD 14.1): confidence intervals are computed on the series of per-session cohort means, never on pooled trades.
EOD-1 cohorts do not overlap (session-clustered: sd/sqrt(n)); multi-session modes use Newey-West with lag = horizon - 1.
The daily portfolio series splits capital into one tranche per open cohort (horizon h -> h tranches of 1,00,000), marks
positions to market every session and never compounds.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from . import sim

MODE_LABEL = {"EOD-1": "close of the entry day (s1)", "EOD-3": "close of the third session (s3)", "EOD-5": "close of the fifth session (s5)",
              "FIXED": "no early exit, close of s6", "TARGET_STOP": "first barrier in s1–s6, else close of s6"}
HORIZON = {"EOD-1": 1, "EOD-3": 3, "EOD-5": 5, "FIXED": 6, "TARGET_STOP": 6}
BENCH_LABEL = {"MODEL": "Model top 5", "A_ALL": "A · every eligible stock", "A_RANDOM5": "A · seeded random five",
               "B_MATCHED": "B · matched five", "C_MOVEMENT": "C · movement only, no direction", "D_NIFTY50": "D · Nifty 50"}
MIN_SESSIONS = 60
Z = 1.959964


@dataclass
class SessionResult:
    prediction_date: date
    entry_session: date
    sessions: list                 # observed session dates (<= 6)
    universe: pd.DataFrame         # eligible rows with outcome columns (engine.simulate)
    arrays: dict                   # (n, 6) path arrays aligned with `universe`
    counts: bool


def newey_west_se(x: np.ndarray, lag: int) -> float:
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 2:
        return float("nan")
    if lag <= 0:
        return float(np.std(x, ddof=1) / np.sqrt(n))
    d = x - x.mean()
    var = float(d @ d) / n
    for j in range(1, min(lag, n - 1) + 1):
        var += 2.0 * (1.0 - j / (lag + 1.0)) * float(d[j:] @ d[:-j]) / n
    return float(np.sqrt(max(var, 0.0) / n))


def mean_ci(x: np.ndarray, lag: int) -> dict:
    x = np.asarray([v for v in x if v is not None and not np.isnan(v)], dtype=float)
    if len(x) == 0:
        return {"mean": None, "lo": None, "hi": None, "n": 0}
    se = newey_west_se(x, lag) if len(x) > 1 else float("nan")
    m = float(x.mean())
    return {"mean": m, "lo": None if np.isnan(se) else m - Z * se, "hi": None if np.isnan(se) else m + Z * se, "n": int(len(x))}


def _sel(u: pd.DataFrame) -> pd.DataFrame:
    return u[(u["selection_status"] == "SELECTED") & (u["status"] == "ENTERED")]


def trade_frame(results: list[SessionResult]) -> pd.DataFrame:
    rows = [r.universe.assign(entry_session=r.entry_session, prediction_date=r.prediction_date) for r in results]
    rows = [_sel(u) for u in rows]
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def daily_portfolio(results: list[SessionResult], mode: str, cost_pct: float, capital: float, slots: int) -> pd.DataFrame:
    """Mark-to-market P&L per calendar session for one mode, all cohorts overlapping (rules evaluation.portfolio_level)."""
    h = HORIZON[mode]
    per_pos = capital / slots
    pnl: dict = {}
    for r in results:
        u = r.universe
        mask = ((u["selection_status"] == "SELECTED") & (u["status"] == "ENTERED")).to_numpy()
        if not mask.any():
            continue
        rc = r.arrays["r_close"][mask]
        state = u.loc[mask, f"{mode}|state"].to_numpy()
        exit_idx = u.loc[mask, f"{mode}|exit_session_index"].to_numpy()
        gross = u.loc[mask, f"{mode}|gross_return"].to_numpy(dtype=float)
        for j in range(rc.shape[0]):
            prev = 0.0
            last = int(exit_idx[j]) if state[j] == "CLOSED" else min(len(r.sessions), h)
            for k in range(min(last, len(r.sessions))):
                d = r.sessions[k]
                is_exit = state[j] == "CLOSED" and k + 1 == last
                val = gross[j] if is_exit else rc[j, k]
                if np.isnan(val):
                    continue
                pnl[d] = pnl.get(d, 0.0) + (val - prev) * per_pos - (cost_pct / 100.0 * per_pos if is_exit else 0.0)
                prev = val
    if not pnl:
        return pd.DataFrame(columns=["session", "pnl", "ret", "cum_pnl"])
    s = pd.Series(pnl).sort_index()
    base = capital * h
    df = pd.DataFrame({"session": s.index, "pnl": s.values})
    df["ret"] = df["pnl"] / base
    df["cum_pnl"] = df["pnl"].cumsum()
    return df


def max_drawdown(cum: np.ndarray) -> float:
    if len(cum) == 0:
        return 0.0
    peak = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    return float(np.max(peak - cum))


def mode_block(results: list[SessionResult], bench: pd.DataFrame, mode: str, rules: dict) -> dict:
    cost = rules["costs"]["base_round_trip_pct"]
    capital = rules["allocation"]["capital_inr"]
    slots = rules["positions_per_portfolio"]
    t = trade_frame(results)
    closed = t[t[f"{mode}|state"] == "CLOSED"] if len(t) else t
    g = closed[f"{mode}|gross_return"].astype(float) if len(closed) else pd.Series(dtype=float)
    netr = g - cost / 100.0
    lag = HORIZON[mode] - 1
    # per-session cohort means (overlap-aware CI) and the paired difference against A_ALL
    cohort = closed.groupby("entry_session")[f"{mode}|gross_return"].mean() - cost / 100.0 if len(closed) else pd.Series(dtype=float)
    a = bench[(bench["benchmark"] == "A_ALL") & (bench["mode"] == mode) & (bench["state"] == "CLOSED")].set_index("entry_session")["net_mean"] if len(bench) else pd.Series(dtype=float)
    diff = (cohort - a.reindex(cohort.index)).dropna()
    ci = mean_ci(cohort.to_numpy(), lag)
    edge = mean_ci(diff.to_numpy(), lag)
    wins, losses = netr[netr > 0].sum(), -netr[netr < 0].sum()
    port = daily_portfolio(results, mode, cost, capital, slots)
    pr = port["ret"].to_numpy() if len(port) else np.array([])
    per_pos = capital / slots
    out = {
        "mode": mode, "label": MODE_LABEL[mode], "headline": mode == rules["headline_mode"].split(" ")[0],
        "closed_trades": int(len(closed)), "sessions": int(cohort.shape[0]),
        "gross_mean": float(g.mean()) if len(g) else None, "net_mean": float(netr.mean()) if len(g) else None,
        "net_median": float(netr.median()) if len(g) else None,
        "net_mean_050": float((g - 0.005).mean()) if len(g) else None, "net_mean_100": float((g - 0.010).mean()) if len(g) else None,
        "win_rate": float((netr > 0).mean()) if len(g) else None,
        "profit_factor": float(wins / losses) if losses > 0 else None,
        "mean_mfe": float(closed[f"{mode}|mfe"].astype(float).mean()) if len(closed) else None,
        "mean_mae": float(closed[f"{mode}|mae"].astype(float).mean()) if len(closed) else None,
        "target_hit_rate": float(closed[f"{mode}|target_hit"].astype(bool).mean()) if len(closed) else None,
        "total_net_inr": float(netr.sum() * per_pos) if len(g) else 0.0,
        "ci95": ci, "edge_vs_a_all": edge,
    }
    if mode == "TARGET_STOP":
        reasons = closed["TARGET_STOP|exit_reason"].astype(str) if len(closed) else pd.Series(dtype=str)
        out["target_before_stop_rate"] = float(reasons.str.startswith("target").mean()) if len(closed) else None
        out["stop_rate"] = float(reasons.str.startswith("stop").mean()) if len(closed) else None
    out["portfolio"] = {"sessions": int(len(port)), "mean_daily_return": float(pr.mean()) if len(pr) else None,
                        "volatility_daily": float(pr.std(ddof=1)) if len(pr) > 1 else None,
                        "sharpe_like": float(pr.mean() / pr.std(ddof=1) * np.sqrt(250)) if len(pr) > 1 and pr.std(ddof=1) > 0 else None,
                        "total_pnl_inr": float(port["pnl"].sum()) if len(port) else 0.0,
                        "max_drawdown_inr": max_drawdown(port["cum_pnl"].to_numpy()) if len(port) else 0.0,
                        "capital_base_inr": capital * HORIZON[mode]}
    out["established"] = bool(edge["n"] >= MIN_SESSIONS and edge["lo"] is not None and (edge["lo"] > 0 or edge["hi"] < 0))
    return out


def bucket_table(results: list[SessionResult], edges: list[float], cost_pct: float, selected_only: bool) -> list[dict]:
    frames = []
    for r in results:
        u = r.universe[(r.universe["status"] == "ENTERED") & (r.universe["EOD-1|state"] == "CLOSED")]
        if selected_only:
            u = u[u["selection_status"] == "SELECTED"]
        frames.append(u)
    if not frames:
        return []
    u = pd.concat(frames, ignore_index=True)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        b = u[(u["p_head"] >= lo) & ((u["p_head"] < hi) if hi < 1.0 else (u["p_head"] <= hi))]
        n = int(len(b))
        if n == 0:
            out.append({"lo": lo, "hi": hi, "n": 0})
            continue
        netr = b["EOD-1|gross_return"].astype(float) - cost_pct / 100.0
        lab = b["model_label_hit"].dropna().astype(bool)
        pred = float(b["p_head"].mean())
        obs = float(lab.mean()) if len(lab) else None
        out.append({"lo": lo, "hi": hi, "n": n, "predicted_mean": pred, "model_label_rate": obs,
                    "trade_target_rate": float(b["EOD-1|target_hit"].astype(bool).mean()),
                    "positive_rate": float((netr > 0).mean()), "net_mean": float(netr.mean()), "net_median": float(netr.median()),
                    "mae_mean": float(b["EOD-1|mae"].astype(float).mean()),
                    "calibration_error": None if obs is None else obs - pred})
    return out


def exception_counts(results: list[SessionResult]) -> dict:
    sel = [r.universe[r.universe["selection_status"] == "SELECTED"] for r in results]
    if not sel:
        return {"selected": 0}
    s = pd.concat(sel, ignore_index=True)
    flags: dict = {}
    for fl in s["flags"]:
        for f in fl:
            flags[f] = flags.get(f, 0) + 1
    return {"selected": int(len(s)), "entered": int((s["status"] == "ENTERED").sum()),
            "by_status": {k: int(v) for k, v in s["status"].value_counts().items()},
            "by_reason": {str(k): int(v) for k, v in s["reason"].dropna().value_counts().items()}, "flags": flags}


def evaluate(results: list[SessionResult], bench: pd.DataFrame, rules: dict, sample: str, portfolio: str, all_recorded: int) -> dict:
    counted = [r for r in results if r.counts]
    cost = rules["costs"]["base_round_trip_pct"]
    b = bench[bench["entry_session"].isin([r.entry_session for r in counted])] if len(bench) else bench
    modes = [mode_block(counted, b, m, rules) for m in sim.MODES]
    bench_summary = []
    for (bm, mode), g in (b[b["state"] == "CLOSED"].groupby(["benchmark", "mode"]) if len(b) else []):
        vals = g["net_mean"].dropna()
        bench_summary.append({"benchmark": bm, "label": BENCH_LABEL[bm], "mode": mode, "sessions": int(len(vals)),
                              "net_mean": float(vals.mean()) if len(vals) else None,
                              "hit_rate": float(np.average(g["target_hit_rate"].dropna(), weights=g.loc[g["target_hit_rate"].notna(), "n"])) if g["target_hit_rate"].notna().any() and g.loc[g["target_hit_rate"].notna(), "n"].sum() > 0 else None,
                              "positive_rate": float(np.average(g["positive_rate"].dropna(), weights=g.loc[g["positive_rate"].notna(), "n"])) if g["positive_rate"].notna().any() and g.loc[g["positive_rate"].notna(), "n"].sum() > 0 else None,
                              "trades": int(g["n"].sum())})
    edges = rules["evaluation"]["buckets"]
    head = next(m for m in modes if m["headline"])
    n_sessions = head["edge_vs_a_all"]["n"]
    if head["established"]:
        stmt = "The model's picks differ from every eligible stock on the headline mode with a 95% interval that excludes zero."
    elif n_sessions < MIN_SESSIONS:
        stmt = f"Not established: {n_sessions} counted sessions, fewer than the {MIN_SESSIONS} the pre-registration requires."
    else:
        stmt = "Not established: the 95% interval for the edge against every eligible stock includes zero."
    return {
        "sample": sample, "portfolio": portfolio, "rules_id": rules["rules_id"], "headline_mode": head["mode"],
        "as_of_session": str(max((r.sessions[-1] for r in results if r.sessions), default=None)),
        "sessions": {"recorded": all_recorded, "counted": len(counted), "with_closed_headline": head["sessions"],
                     "first_counted": str(min((r.entry_session for r in counted), default=None)),
                     "last_counted": str(max((r.entry_session for r in counted), default=None)),
                     "not_counted": [str(r.entry_session) for r in results if not r.counts]},
        "exceptions": exception_counts(counted),
        "modes": modes, "benchmarks": bench_summary,
        "buckets": {"universe": bucket_table(counted, edges, cost, False), "selected": bucket_table(counted, edges, cost, True)},
        "statement": {"established": head["established"], "text": stmt, "min_sessions": MIN_SESSIONS},
        "costs": {"base": cost, "sensitivity": rules["costs"]["sensitivity_round_trip_pct"]},
    }
