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


def refit_verdict(v4: pd.DataFrame, v4d: pd.DataFrame, rule: dict) -> dict:
    """The pre-registered v4d-vs-v4 read (thresholds_lock_v4d_forward.json 'comparison_with_v4'). Both frames are graded
    rows (head, symbol, target_session, p_tpd3, y). Only sessions graded in BOTH models count; each model's own top-k
    list per session is scored, and the per-session difference in hits is bootstrapped over sessions."""
    head, k = rule["primary_head"], int(rule["top_k"])
    def prep(f):
        f = f[(f["head"] == head) & f["y"].notna()]
        return f.assign(target_session=pd.to_datetime(f["target_session"]))
    a, b = prep(v4), prep(v4d)
    both = sorted(set(a["target_session"]) & set(b["target_session"]))
    a, b = a[a["target_session"].isin(both)], b[b["target_session"].isin(both)]
    def hits(f):
        return f.sort_values(["target_session", "p_tpd3", "symbol"], ascending=[True, False, True], kind="mergesort") \
                .groupby("target_session").head(k).groupby("target_session")["y"].sum()
    diff = (hits(b) - hits(a)).reindex(both).to_numpy(dtype=float)
    out = {"head": head, "top_k": k, "paired_sessions": len(both), "outcome": "INCONCLUSIVE", "reason": ""}
    if len(both) < int(rule["read_at_paired_sessions"]):
        out["reason"] = f"fewer than {rule['read_at_paired_sessions']} paired sessions ({len(both)})"
        return out
    rng = np.random.default_rng(int(rule["bootstrap"]["seed"]))
    n = int(rule["bootstrap"]["resamples"])
    boots = np.array([diff[rng.integers(0, len(diff), len(diff))].mean() for _ in range(n)])
    lo, hi = float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))
    auc_a, auc_b = roc_auc(a["y"], a["p_tpd3"]), roc_auc(b["y"], b["p_tpd3"])
    out.update(mean_diff_hits_per_session=float(diff.mean()), ci95=[lo, hi], hit_rate_v4=float(hits(a).sum() / (k * len(both))),
               hit_rate_v4d=float(hits(b).sum() / (k * len(both))), auc_v4=auc_a, auc_v4d=auc_b)
    auc_ok = not (auc_b < auc_a - float(rule["auc_margin"]))
    # calibration guard in the high band (added from the 2025 history, where the nightly refit's >= 30% +5% calls
    # realised 26.8% against 31.5% for the monthly refit): judged only when both models have enough rows in the band
    g = rule.get("high_band_calibration_guard")
    cal_ok, cal = True, None
    if g:
        ba, bb = a[a["p_tpd3"] >= float(g["band_min"])], b[b["p_tpd3"] >= float(g["band_min"])]
        cal = {"rows_v4": int(len(ba)), "rows_v4d": int(len(bb))}
        if len(ba) >= int(g["min_rows"]) and len(bb) >= int(g["min_rows"]):
            err_a, err_b = abs(float(ba["p_tpd3"].mean()) - float(ba["y"].mean())), abs(float(bb["p_tpd3"].mean()) - float(bb["y"].mean()))
            cal.update(abs_err_v4=err_a, abs_err_v4d=err_b, judged=True)
            cal_ok = err_b <= err_a + float(g["max_extra_abs_error"])
        else:
            cal["judged"] = False
    out["high_band_calibration"] = cal
    if lo >= float(rule["non_inferiority_hits_per_session"]) and auc_ok and cal_ok:
        out.update(outcome="PROMOTE", reason="v4d is non-inferior on top-k hits, AUC and high-band calibration; the fresher model is preferred")
    elif hi < 0 or not auc_ok or not cal_ok:
        out.update(outcome="KEEP_V4", reason="v4d is worse on top-k hits" if hi < 0 else ("v4d AUC is below v4 by more than the margin" if not auc_ok
                                                                                          else "v4d's high-band calibration error exceeds v4's by more than the margin"))
    else:
        out["reason"] = "the interval spans the non-inferiority margin"
    return out
