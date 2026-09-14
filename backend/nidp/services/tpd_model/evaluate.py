"""W3 evaluation: B2 metric cells and the B3-B6 verdicts from thresholds_lock.json.

A head is served only if every locked criterion that applies to it passed; a criterion that could not be
evaluated (no fixed baseline, no regime labels) counts as not passed. If p_up10_1d is not served, exposure is
blocked (lock failing_head.block_exposure_if_fails) and G-VALID is false.

    python -m nidp.services.tpd_model.evaluate --run <w3 run dir> --exports <dir> [--baseline <preds.pkl>]
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .metrics import (bootstrap_delta_p5, brier, calibration_deciles, log_loss, pr_auc, precision_at_k,
                      recall_at_k, roc_auc, sessions_with_hit)
from .report import LOCK_PATH, b3_verdict, b4_verdict, load_lock

MODELS = {"tpd3": "p_tpd3", "base_rate": "p_base_rate", "atr_only": "p_atr_only", "own_history_only": "p_own_history_only"}
COMPARATORS = ("atr_only", "own_history_only")
BASELINE_HEAD = "p_up10_1d"


def _metrics(frame: pd.DataFrame, col: str) -> dict[str, tuple[float, Optional[str]]]:
    y, p = frame["y"].to_numpy(float), frame[col].to_numpy(float)
    events = int(y.sum())
    constant = np.nanstd(p) == 0
    out = {"n": (float(len(y)), None), "events": (float(events), None), "base_rate": (float(y.mean()), None)}
    if constant:
        out["auc"] = (np.nan, "constant prediction has no ranking")
    elif events == 0:
        out["auc"] = (np.nan, "no events in period")
    else:
        out["auc"] = (roc_auc(y, p), None)
    out["pr_auc"] = (pr_auc(y, p), None) if events else (np.nan, "no events in period")
    for k in (5, 10, 20):
        out[f"p{k}"] = (precision_at_k(frame, col, "y", k), None)
    out["recall20"] = (recall_at_k(frame, col, "y", 20), None) if events else (np.nan, "no events in period")
    out["sessions_top5_hit"] = (sessions_with_hit(frame, col, "y", 5), None)
    out["brier"] = (brier(y, p), None)
    out["log_loss"] = (log_loss(y, p), None)
    out["log_loss_base_rate"] = (log_loss(y, frame["p_base_rate"].to_numpy(float)), None)
    return out


def metric_cells(preds: pd.DataFrame) -> pd.DataFrame:
    rows = []
    labelled = preds[preds["y"].notna()]
    for head, h in labelled.groupby("head", sort=True):
        for period, frame in [("overall", h), *sorted(h.groupby("month"))]:
            for model, col in MODELS.items():
                for metric, (value, reason) in _metrics(frame, col).items():
                    rows.append({"head": head, "period": period, "model": model, "metric": metric,
                                 "value": value, "reason": reason})
    return pd.DataFrame(rows)


def _cell(cells: pd.DataFrame, head: str, period: str, model: str, metric: str) -> float:
    m = cells[(cells["head"] == head) & (cells["period"] == period) & (cells["model"] == model) & (cells["metric"] == metric)]
    return float(m["value"].iloc[0])


def calibration_verdict(frame: pd.DataFrame, lock: dict) -> dict:
    bar = lock["b5_calibration"]
    y, p = frame["y"].to_numpy(float), frame["p_tpd3"].to_numpy(float)
    cal = calibration_deciles(y, p)
    top = cal.iloc[-1]
    inside = int(((cal["pred_mean"] >= cal["wilson_lo"]) & (cal["pred_mean"] <= cal["wilson_hi"])).sum())
    obs = y.mean()
    values = {
        "mean_pred_rel_err": abs(p.mean() - obs) / obs if obs else np.inf,
        "top_decile_rel_err": abs(top["pred_mean"] - top["obs_rate"]) / top["obs_rate"] if top["obs_rate"] else np.inf,
        "deciles_inside_wilson": inside,
        "logloss_below_base_rate": log_loss(y, p) < log_loss(y, frame["p_base_rate"].to_numpy(float)),
        "brier_skill_positive": brier(y, p) < brier(y, frame["p_base_rate"].to_numpy(float)),
    }
    checks = {
        "mean_pred_rel_err": values["mean_pred_rel_err"] <= bar["mean_pred_rel_err_max"],
        "top_decile_rel_err": values["top_decile_rel_err"] <= bar["top_decile_rel_err_max"],
        "deciles_inside_wilson": inside >= bar["deciles_pred_inside_wilson95_min"],
        "logloss_below_base_rate": bool(values["logloss_below_base_rate"]),
        "brier_skill_positive": bool(values["brier_skill_positive"]),
    }
    return {"pass": bool(all(checks.values())), "checks": {k: bool(v) for k, v in checks.items()},
            "values": {k: (float(v) if not isinstance(v, (bool, np.bool_)) else bool(v)) for k, v in values.items()},
            "deciles": cal.to_dict("records")}


def regime_verdict(frame: pd.DataFrame, regimes: pd.DataFrame, lock_path: Path = LOCK_PATH) -> dict:
    lock, _ = load_lock(lock_path)
    bar = lock["b6_regimes"]
    f = frame[frame["y"].notna()].merge(regimes[["as_of_date", "regime"]], on="as_of_date", how="inner")
    cells = {}
    for regime, g in f.groupby("regime"):
        events = int(g["y"].sum())
        entry = {"n": int(len(g)), "events": events}
        if events < bar["cell_min_events"]:
            entry["status"] = "INSUFFICIENT"
        else:
            auc = roc_auc(g["y"], g["p_tpd3"])
            best = max(roc_auc(g["y"], g[MODELS[c]]) for c in COMPARATORS)
            p5, base = precision_at_k(g, "p_tpd3", "y", 5), float(g["y"].mean())
            ok = (auc > best and auc >= bar["per_cell"]["auc_min"] and p5 >= bar["per_cell"]["p5_vs_cell_base_rate_min"] * base)
            entry.update(auc=auc, best_comparator_auc=best, p5=p5, base_rate=base, status="PASS" if ok else "FAIL")
        cells[regime] = entry
    insufficient = sum(c["status"] == "INSUFFICIENT" for c in cells.values())
    passed = bool(cells) and not any(c["status"] == "FAIL" for c in cells.values()) and insufficient <= len(cells) / 2
    return {"pass": passed, "cells": cells}


def evaluate(preds: pd.DataFrame, regimes: Optional[pd.DataFrame], baseline: Optional[pd.DataFrame],
             lock_path: Path = LOCK_PATH) -> dict:
    lock, sha = load_lock(lock_path)
    cells = metric_cells(preds)
    months = sorted(p for p in cells["period"].unique() if p != "overall")
    heads = {}
    for head, h in preds[preds["y"].notna()].groupby("head", sort=True):
        comps = {c: {"auc": _cell(cells, head, "overall", c, "auc"), "pr_auc": _cell(cells, head, "overall", c, "pr_auc")}
                 for c in COMPARATORS}
        beats = sum(_cell(cells, head, m, "tpd3", "auc") > max(_cell(cells, head, m, c, "auc") for c in COMPARATORS)
                    for m in months)
        summary = {"auc": _cell(cells, head, "overall", "tpd3", "auc"), "pr_auc": _cell(cells, head, "overall", "tpd3", "pr_auc"),
                   "p5": _cell(cells, head, "overall", "tpd3", "p5"), "base_rate": _cell(cells, head, "overall", "tpd3", "base_rate"),
                   "months_auc_beats_best_comparator": int(beats), "comparators": comps}
        entry = {"summary": summary, "b5": calibration_verdict(h, lock)}
        entry["b6"] = (regime_verdict(h, regimes, lock_path) if regimes is not None
                       else {"pass": False, "status": "NOT_EVALUATED", "reason": "regime labels not supplied"})
        if head == BASELINE_HEAD:
            if baseline is None:
                entry["b3"] = {"status": "NOT_EVALUATED", "reason": "fixed baseline predictions not supplied",
                               "non_inferior": False, "better": False}
            else:
                both = h.merge(baseline[["symbol", "target_session", "p_baseline"]], on=["symbol", "target_session"], how="inner")
                base_m = {"auc": roc_auc(both["y"], both["p_baseline"]), "p5": precision_at_k(both, "p_baseline", "y", 5)}
                new_m = {"auc": roc_auc(both["y"], both["p_tpd3"]), "p5": precision_at_k(both, "p_tpd3", "y", 5)}
                boot = bootstrap_delta_p5(both, "p_tpd3", "p_baseline", "y",
                                          resamples=lock["b3_p_up10_1d_vs_fixed_baseline"]["better"]["bootstrap"]["resamples"])
                entry["b3"] = {"status": "EVALUATED", "rows_compared": int(len(both)), "rows_tpd3": int(len(h)),
                               "tpd3": new_m, "baseline": base_m, "bootstrap": boot, **b3_verdict(new_m, base_m, boot, lock)}
            required = [entry["b3"]["non_inferior"], entry["b5"]["pass"], entry["b6"]["pass"]]
        else:
            entry["b4"] = b4_verdict(summary, lock)
            required = [entry["b4"]["pass"], entry["b5"]["pass"], entry["b6"]["pass"]]
        entry["served"] = bool(all(required))
        heads[head] = entry
    blocked = not heads.get(BASELINE_HEAD, {}).get("served", False)
    return {"lock_sha256": sha, "heads": heads, "exposure_blocked": blocked, "g_valid": not blocked,
            "policy": lock["failing_head"]}


def forward_excess_table(preds: pd.DataFrame, panel: pd.DataFrame, ks=(5, 10, 20), horizons=(1, 5, 21),
                         cost: float = 0.003) -> pd.DataFrame:
    """B7 'move is not investment': excess return of each head's daily top-k (probability desc, symbol asc) over
    the equal-weight mean of that day's scored universe. Entry at the target session's open, exit at the close
    H sessions after T, less a round-trip cost (K4, same rule as report.forward_returns). The t-statistic is the
    mean of monthly mean excess over its standard error across months (month-clustered)."""
    opens = panel.pivot_table(index="as_of_date", columns="symbol", values="open", aggfunc="first").sort_index()
    closes = panel.pivot_table(index="as_of_date", columns="symbol", values="close", aggfunc="first").reindex(opens.index)
    pos = {t: i for i, t in enumerate(opens.index)}
    O, C = opens.to_numpy(np.float64), closes.to_numpy(np.float64)
    col = {s: j for j, s in enumerate(opens.columns)}
    records = []
    for head, h in preds.groupby("head", sort=True):
        picks = {(k, H): [] for k in ks for H in horizons}
        for T, day in h.groupby("as_of_date", sort=True):
            i = pos[pd.Timestamp(T)]
            if i + 1 >= len(opens.index):
                continue
            day = day.sort_values(["p_tpd3", "symbol"], ascending=[False, True], kind="mergesort")
            j = np.array([col.get(s, -1) for s in day["symbol"]])
            valid = j >= 0
            entry = np.full(len(j), np.nan)
            entry[valid] = O[i + 1, j[valid]]
            month = pd.Timestamp(day["target_session"].iloc[0]).strftime("%Y-%m")
            for H in horizons:
                if i + H >= len(opens.index):
                    continue
                exit_ = np.full(len(j), np.nan)
                exit_[valid] = C[i + H, j[valid]]
                ret = exit_ / entry - 1 - cost
                excess = ret - np.nanmean(ret)
                for k in ks:
                    top = excess[:k]
                    picks[(k, H)].extend((month, v) for v in top[~np.isnan(top)])
        for (k, H), vals in picks.items():
            df = pd.DataFrame(vals, columns=["month", "excess"])
            monthly = df.groupby("month")["excess"].mean() if len(df) else pd.Series(dtype=float)
            t = (monthly.mean() / (monthly.std(ddof=1) / np.sqrt(len(monthly)))
                 if len(monthly) > 1 and monthly.std(ddof=1) > 0 else np.nan)
            records.append({"head": head, "k": k, "H": H, "n": int(len(df)),
                            "mean_excess": float(df["excess"].mean()) if len(df) else np.nan,
                            "t_month_clustered": float(t), "months": int(len(monthly))})
    return pd.DataFrame(records)


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp, date)):
        return str(o)
    return o


def main(argv: Optional[list[str]] = None) -> None:
    from .backtest import universe_by_session
    from .panel_source import select_nse_eq
    from .report import regime_labels

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--exports", type=Path, required=True)
    ap.add_argument("--baseline", type=Path, default=None)
    a = ap.parse_args(argv)
    lock, sha = load_lock()
    preds = pd.read_pickle(a.run / "predictions.pkl")
    raw = pd.read_csv(a.exports / "panel.csv.gz", parse_dates=["as_of_date"])
    panel = select_nse_eq(raw, set(pd.read_csv(a.exports / "etfs.csv")["symbol"]))
    scored_T = sorted(preds["as_of_date"].dt.date.unique())
    sessions = sorted(panel["as_of_date"].dt.date.unique())
    nxt = {sessions[i]: sessions[i + 1] for i in range(len(sessions) - 1)}
    members = {T: universe_by_session(panel, [nxt[T]])[nxt[T]] for T in scored_T}
    regimes = regime_labels(panel, members, scored_T)
    baseline = pd.read_pickle(a.baseline) if a.baseline else None
    verdict = evaluate(preds, regimes, baseline)
    cells = metric_cells(preds)
    cells.to_csv(a.run / "cells.csv", index=False)
    regimes.to_csv(a.run / "regimes.csv", index=False)
    b7 = forward_excess_table(preds[preds["y"].notna()], panel)
    b7.to_csv(a.run / "b7_forward_excess.csv", index=False)
    verdict["b7"] = {"present": bool(len(b7) == 36 and b7["n"].gt(0).all()), "cells": int(len(b7))}
    blob = json.dumps(_jsonable(verdict), indent=1)  # serialise fully before touching the file
    (a.run / "verdict.json").write_text(blob)
    print(json.dumps({"lock_sha256": sha, "exposure_blocked": verdict["exposure_blocked"], "g_valid": verdict["g_valid"],
                      "served": {h: e["served"] for h, e in verdict["heads"].items()}}, indent=1))


if __name__ == "__main__":
    main()
