"""v4 early-read evaluation (thresholds_lock_v4_early_window.json): ranking, calibration and the high-confidence
(>= 50%) bin for each of the four heads. Informational: nothing is served from an early read."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .evaluate import calibration_verdict
from .metrics import precision_at_k, roc_auc, wilson


def high_confidence_verdict(frame: pd.DataFrame, bar: dict) -> dict:
    """Rows at or above the threshold: INSUFFICIENT below `min_rows_to_judge`, else calibrated if the mean predicted
    probability lies inside the Wilson 95% interval of the realised rate, useful if the realised rate >= 0.40."""
    hi = frame[(frame["p_tpd3"] >= bar["threshold"]) & frame["y"].notna()]
    n, k = int(len(hi)), int(hi["y"].sum())
    out = {"threshold": bar["threshold"], "rows": n, "events": k,
           "months_with_rows": int(pd.to_datetime(hi["target_session"]).dt.to_period("M").nunique()) if n else 0,
           "symbols": int(hi["symbol"].nunique()) if n else 0}
    if n < bar["min_rows_to_judge"]:
        rate = float(k / n) if n else float("nan")
        return {**out, "realised_rate": rate, "mean_p": float(hi["p_tpd3"].mean()) if n else float("nan"),
                "wilson95": list(wilson(k, n)) if n else [float("nan"), float("nan")], "status": "INSUFFICIENT",
                "calibrated": False, "useful": False, "pass": False}
    rate, mean_p = k / n, float(hi["p_tpd3"].mean())
    lo, up = wilson(k, n)
    calibrated, useful = bool(lo <= mean_p <= up), bool(rate >= 0.40)
    return {**out, "realised_rate": float(rate), "mean_p": mean_p, "wilson95": [float(lo), float(up)], "status": "JUDGED",
            "calibrated": calibrated, "useful": useful, "pass": calibrated and useful}


def evaluate_v4_frames(preds: pd.DataFrame, lock: dict) -> dict:
    bars = lock["bars"]
    heads = {}
    for head in lock["heads"]:
        h = preds[(preds["head"] == head) & preds["y"].notna()]
        auc = roc_auc(h["y"], h["p_tpd3"])
        comp = {c: roc_auc(h["y"], h[c]) for c in ("p_atr_only", "p_own_history_only") if c in h and h[c].nunique() > 1}
        best = max(comp.values()) if comp else float("nan")
        ranking_pass = bool(auc >= bars["ranking_all_heads"]["auc_min"][head] and (not comp or auc > best))
        cal = calibration_verdict(h, {"b5_calibration": bars["calibration_all_heads"]})
        heads[head] = {"rows": int(len(h)), "events": int(h["y"].sum()), "base_rate": float(h["y"].mean()), "auc": float(auc),
                       "p5": float(precision_at_k(h, "p_tpd3", "y", 5)), "p10": float(precision_at_k(h, "p_tpd3", "y", 10)),
                       "comparator_auc": comp, "best_comparator_auc": float(best), "ranking_pass": ranking_pass,
                       "calibration": {k: v for k, v in cal.items() if k != "deciles"}, "deciles": cal["deciles"],
                       "high_confidence_50": high_confidence_verdict(h, bars["high_confidence_50"]),
                       "max_p": float(h["p_tpd3"].max()),
                       "rows_by_p_band": {f"{lo:.2f}-{hi:.2f}": {"rows": int(((h["p_tpd3"] >= lo) & (h["p_tpd3"] < hi)).sum()),
                                                                 "realised": float(h.loc[(h["p_tpd3"] >= lo) & (h["p_tpd3"] < hi), "y"].mean()) if ((h["p_tpd3"] >= lo) & (h["p_tpd3"] < hi)).any() else None}
                                          for lo, hi in ((0.0, 0.05), (0.05, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.4), (0.4, 0.5), (0.5, 0.6), (0.6, 1.01))}}
    sessions = preds.loc[preds["y"].notna(), "target_session"].nunique()
    return {"lock_role": lock["role"], "graded_sessions": int(sessions), "heads": heads, "status": "EARLY_READ", "served": False,
            "note": "early read: informs the v4 forward test, serves nothing"}
