"""Judging the walk-forward against the locked pass bars (thresholds_lock.json, NI-4).

Nothing here evaluates a head unless the committed lock file is present; its sha256 goes into every report so a
later edit to the bars is visible.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

LOCK_PATH = Path(__file__).with_name("thresholds_lock.json")
_EPS = 1e-12  # the lock's boundaries are inclusive; guard them against binary rounding


class LockMissingError(RuntimeError):
    """The pass bars were not locked; refusing to judge results."""


def load_lock(path: Path = LOCK_PATH) -> tuple[dict, str]:
    path = Path(path)
    if not path.exists():
        raise LockMissingError(f"{path} not found - lock the NI-4 pass bars before evaluating any head")
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def b4_verdict(m: dict, lock: dict) -> dict:
    bar = lock["b4_other_heads_ship"]
    best_pr = max(c["pr_auc"] for c in m["comparators"].values())
    checks = {
        "auc_min": m["auc"] >= bar["auc_min"] - _EPS,
        "pr_auc_vs_best_comparator": m["pr_auc"] >= bar["pr_auc_vs_best_comparator_min"] * best_pr * (1 - _EPS),
        "p5_vs_base_rate": m["p5"] >= bar["p5_vs_base_rate_min"] * m["base_rate"] * (1 - _EPS),
        "months_beating_best_comparator":
            m["months_auc_beats_best_comparator"] >= bar["months_beating_best_comparator_auc_min"],
    }
    return {"pass": bool(all(checks.values())), "checks": {k: bool(v) for k, v in checks.items()}}


def b3_verdict(new: dict, base: dict, boot: dict, lock: dict) -> dict:
    rule = lock["b3_p_up10_1d_vs_fixed_baseline"]
    ni, better = rule["non_inferior"], rule["better"]
    non_inferior = (new["p5"] >= base["p5"] - ni["p5_margin_pp"] / 100 - _EPS
                    and new["auc"] >= base["auc"] - ni["auc_margin"] - _EPS)
    is_better = (new["auc"] - base["auc"] >= better["delta_auc_min"] - _EPS
                 and new["p5"] - base["p5"] >= better["delta_p5_pp_min"] / 100 - _EPS
                 and boot["ci_lo"] > better["bootstrap"]["delta_p5_lower_gt"])
    return {"non_inferior": bool(non_inferior), "better": bool(non_inferior and is_better)}


def missing_cells(cells: pd.DataFrame) -> pd.DataFrame:
    """B2: a blank metric is acceptable only with a stated reason."""
    return cells[cells["value"].isna() & cells["reason"].isna()]


def _wilder_atr_pct(h: np.ndarray, lo: np.ndarray, c: np.ndarray, period: int = 14) -> np.ndarray:
    out = np.full(len(c), np.nan)
    if len(c) <= period:
        return out
    tr = np.maximum(h[1:] - lo[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(lo[1:] - c[:-1])))
    avg = tr[:period].mean()
    out[period] = avg
    for i in range(period, len(tr)):
        avg = (avg * (period - 1) + tr[i]) / period
        out[i + 1] = avg
    return out / c * 100


def regime_labels(panel: pd.DataFrame, members: dict, sessions: list[date]) -> pd.DataFrame:
    """Volatility x trend regime for each session T from bars dated on or before T only (lock b6_regimes).

    Volatility: median ATR%14 across the session's universe members; HIGH when above the expanding median of
    that series from the panel start through T. Trend: median 50-bar return across members; UP when > 0.
    Wilder ATR and trailing returns only look backwards, so later bars cannot change an earlier label.
    """
    last = pd.Timestamp(max(sessions))
    p = panel[panel["as_of_date"] <= last].sort_values(["symbol", "as_of_date"], kind="mergesort")
    atr, ret50 = {}, {}
    for sym, g in p.groupby("symbol", sort=False):
        h, lo, c = (g[col].to_numpy(np.float64) for col in ("high", "low", "close"))
        idx = pd.DatetimeIndex(g["as_of_date"])
        atr[sym] = pd.Series(_wilder_atr_pct(h, lo, c), index=idx)
        r = np.full(len(c), np.nan)
        if len(c) > 50:
            r[50:] = c[50:] / c[:-50] - 1
        ret50[sym] = pd.Series(r, index=idx)
    atr_df, ret_df = pd.DataFrame(atr).sort_index(), pd.DataFrame(ret50).sort_index()

    def cross_median(frame: pd.DataFrame) -> pd.Series:
        vals = {}
        for d, row in frame.iterrows():
            names = members.get(d.date())
            present = (row.reindex(names) if names is not None else row).dropna()
            vals[d] = float(present.median()) if len(present) else np.nan  # warm-up bars have no ATR yet
        return pd.Series(vals)

    vol, trend = cross_median(atr_df), cross_median(ret_df)
    expanding = vol.expanding().median()
    rows = []
    for T in sessions:
        t = pd.Timestamp(T)
        high = bool(vol.get(t, np.nan) > expanding.get(t, np.nan))
        up = bool(trend.get(t, np.nan) > 0)
        rows.append({"as_of_date": t, "vol_median_atr_pct": vol.get(t, np.nan),
                     "trend_median_ret50": trend.get(t, np.nan),
                     "regime": f"{'HIGH' if high else 'LOW'}_{'UP' if up else 'DOWN'}"})
    return pd.DataFrame(rows)


def forward_returns(panel: pd.DataFrame, T: date, symbols: list[str], horizons=(1, 5, 21),
                    cost: float = 0.003) -> pd.DataFrame:
    """K4: enter at the target session's open, exit at the close H sessions after T, less a round-trip cost;
    excess is over the equal-weight mean of the same measure across `symbols`."""
    sessions = pd.DatetimeIndex(sorted(panel["as_of_date"].unique()))
    i = sessions.get_loc(pd.Timestamp(T))
    out = pd.DataFrame(index=pd.Index(symbols, name="symbol"))
    if i + 1 >= len(sessions):
        return out
    bars = panel[panel["symbol"].isin(symbols)]
    entry = bars[bars["as_of_date"] == sessions[i + 1]].set_index("symbol")["open"].reindex(symbols)
    for H in horizons:
        if i + H >= len(sessions):
            out[f"ret_{H}"] = np.nan
        else:
            exit_close = bars[bars["as_of_date"] == sessions[i + H]].set_index("symbol")["close"].reindex(symbols)
            out[f"ret_{H}"] = exit_close / entry - 1 - cost
        out[f"excess_{H}"] = out[f"ret_{H}"] - out[f"ret_{H}"].mean()
    return out
