"""Evaluation metrics (test-plan §2.4). Lists are ranked per target session by probability descending with
ties broken by symbol, and precision@k is pooled: hits in each session's top-k over the sum of min(k, eligible)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score


def _top_k(frame: pd.DataFrame, p: str, k: int) -> pd.DataFrame:
    ranked = frame.sort_values(["target_session", p, "symbol"], ascending=[True, False, True], kind="mergesort")
    return ranked.groupby("target_session", sort=False).head(k)


def precision_at_k(frame: pd.DataFrame, p: str, y: str, k: int) -> float:
    return float(_top_k(frame, p, k)[y].mean())


def recall_at_k(frame: pd.DataFrame, p: str, y: str, k: int) -> float:
    events = frame[y].sum()
    return float(_top_k(frame, p, k)[y].sum() / events) if events else float("nan")


def sessions_with_hit(frame: pd.DataFrame, p: str, y: str, k: int) -> float:
    return float(_top_k(frame, p, k).groupby("target_session")[y].max().mean())


def roc_auc(y, p) -> float:
    y = np.asarray(y)
    return float(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else float("nan")


def pr_auc(y, p) -> float:
    y = np.asarray(y)
    return float(average_precision_score(y, p)) if y.sum() > 0 else float("nan")


def brier(y, p) -> float:
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def log_loss(y, p) -> float:
    y, p = np.asarray(y, float), np.clip(np.asarray(p, float), 1e-12, 1 - 1e-12)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    phat = k / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return centre - half, centre + half


def calibration_deciles(y, p) -> pd.DataFrame:
    df = pd.DataFrame({"y": np.asarray(y, float), "p": np.asarray(p, float)})
    df["decile"] = pd.qcut(df["p"].rank(method="first"), 10, labels=False)
    out = df.groupby("decile").agg(n=("y", "size"), events=("y", "sum"), pred_mean=("p", "mean"), obs_rate=("y", "mean"))
    ci = [wilson(int(e), int(n)) for e, n in zip(out["events"], out["n"])]
    out["wilson_lo"], out["wilson_hi"] = [c[0] for c in ci], [c[1] for c in ci]
    return out.reset_index()


def _monthly_p5_parts(frame: pd.DataFrame, p: str, y: str) -> pd.DataFrame:
    top = _top_k(frame, p, 5)
    return top.groupby(top["target_session"].dt.strftime("%Y-%m"))[y].agg(hits="sum", slots="size")


def bootstrap_delta_p5(frame: pd.DataFrame, p_new: str, p_old: str, y: str, resamples: int = 2000,
                       seed: int = 7, ci: float = 0.95) -> dict:
    """Pooled p@5 difference (new - old) with a month-block bootstrap CI: whole months are resampled, which
    keeps the within-month dependence (a volatile month lifts every model at once)."""
    new, old = _monthly_p5_parts(frame, p_new, y), _monthly_p5_parts(frame, p_old, y)
    months = new.index.intersection(old.index)
    hn, sn = new.loc[months, "hits"].to_numpy(float), new.loc[months, "slots"].to_numpy(float)
    ho, so = old.loc[months, "hits"].to_numpy(float), old.loc[months, "slots"].to_numpy(float)
    delta = hn.sum() / sn.sum() - ho.sum() / so.sum()
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(months), size=(resamples, len(months)))
    boot = hn[draws].sum(1) / sn[draws].sum(1) - ho[draws].sum(1) / so[draws].sum(1)
    lo, hi = np.quantile(boot, [(1 - ci) / 2, 1 - (1 - ci) / 2])
    return {"delta": float(delta), "ci_lo": float(lo), "ci_hi": float(hi), "resamples": resamples, "seed": seed,
            "months": len(months)}
