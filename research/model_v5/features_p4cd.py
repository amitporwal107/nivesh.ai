"""Phase 4 feature groups C (breakout and continuation quality, 11) and D (tradeability and execution, 7):
PREREGISTRATION_P4_CD.md §3, FROZEN at 88455a35. Windows count the stock's own bars; "prior N" excludes D; every value
for D uses bars dated on or before D only (test_features_p4cd.py shocks the bars after D and checks nothing changes).

Readings of the frozen text (recorded in P4_CD_RESULTS.md):
- A breakout day t: close(t) > hi55p(t); where hi55p(t) does not exist yet (fewer than 55 prior bars) t is not one.
- "Within the last 10 bars" (bo_vol_last, bo_close_pos_last) = bars D-9..D; "within the last 10 bars, before D"
  (bo_follow_through) = bars D-10..D-1.
- bo_failed_120 / bo_held_120 need a full 120-bar prior window (NaN before); they count breakout days t in D-120..D-5.
  "Fell back" = any close in t+1..t+5 at or below hi55p(t).
- bo_gap_through_freq: breakout days in the prior 260 bars (fewer bars allowed); NaN below 3 such days.
- D windows (60 / 120 bars, including D) need that many bars (gaps need a previous close); NaN before.
- td_hist_*: past entries t in D-250..D-5 on the stock's own bars; entry = open of t+1; the frozen tbs_5_2 rule
  (labels.target_before_stop) over bars t+1..t+5; a gap-through stop = a STOP whose exit bar opened at or below the stop.
  The circuit-lock exclusion of the label builder is not applied to these historical outcomes.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset as DS  # noqa: E402
import features_p4 as FP  # noqa: E402
import labels as LB  # noqa: E402

from nidp.services.tpd_model.risk import costs as CC  # noqa: E402

GROUP_C = ("bo_dist_atr55", "bo_dist_atr20", "bo_dist_pct55", "bo_days_since", "bo_vol_last", "bo_close_pos_last",
           "bo_follow_through", "bo_failed_120", "bo_held_120", "bo_gap_through_freq", "bo_peer_share")
GROUP_D = ("td_log_value60", "td_slippage_pct", "td_gap_abs60", "td_gap_share60", "td_gap_down2_120", "td_hist_target",
           "td_hist_gapstop")
NEAR_HIGH = 0.97
MIN_HIST = 60


def _prior_max(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).shift(1).rolling(n, min_periods=n).max().to_numpy()


def _last_true_within(flag: np.ndarray, lo_off: int, hi_off: int) -> np.ndarray:
    """For each i, the largest j in [i - lo_off, i - hi_off] with flag[j], else -1."""
    n = len(flag)
    last = np.full(n, -1)
    run = -1
    for j in range(n):
        if flag[j]:
            run = j
        last[j] = run
    out = np.full(n, -1)
    for i in range(n):
        top = i - hi_off
        if top < 0:
            continue
        j = last[top]
        if j >= 0 and j >= i - lo_off:
            out[i] = j
    return out


def _window_count(flag: np.ndarray, lo_off: int, hi_off: int) -> np.ndarray:
    """For each i, the number of j in [i - lo_off, i - hi_off] (clipped at 0) with flag[j]."""
    cs = np.concatenate([[0], np.cumsum(flag.astype(int))])
    i = np.arange(len(flag))
    top, bot = i - hi_off, np.maximum(i - lo_off, 0)
    return np.where(top >= 0, cs[np.maximum(top, -1) + 1] - cs[np.minimum(bot, len(flag))], 0)


def symbol_features(g: pd.DataFrame, atr: np.ndarray, cost_model) -> dict:
    """Groups C (except the peer share) and D for one symbol's bars `g` (sorted by date)."""
    o, h, lo, c, v = (g[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    n = len(c)
    idx = np.arange(n)
    f = {}
    hi55p, hi20p = _prior_max(h, 55), _prior_max(h, 20)
    bo = np.where(np.isnan(hi55p), False, c > hi55p)
    f["bo_dist_atr55"] = (c - hi55p) / atr
    f["bo_dist_atr20"] = (c - hi20p) / atr
    f["bo_dist_pct55"] = c / hi55p - 1
    last260 = _last_true_within(bo, 259, 0)
    f["bo_days_since"] = np.where(last260 >= 0, idx - last260, np.nan)
    prior_v20 = pd.Series(v).shift(1).rolling(20, min_periods=20).mean().to_numpy()
    vr = v / np.where(prior_v20 > 0, prior_v20, np.nan)
    rng = h - lo
    close_pos = np.where(rng > 0, (c - lo) / np.where(rng > 0, rng, 1.0), 0.5)
    j10 = _last_true_within(bo, 9, 0)
    f["bo_vol_last"] = np.where(j10 >= 0, vr[np.maximum(j10, 0)], np.nan)
    f["bo_close_pos_last"] = np.where(j10 >= 0, close_pos[np.maximum(j10, 0)], np.nan)
    jb = _last_true_within(bo, 10, 1)
    f["bo_follow_through"] = np.where(jb >= 0, c / c[np.maximum(jb, 0)] - 1, np.nan)
    fail = np.zeros(n, dtype=bool)
    for t in np.flatnonzero(bo):
        nxt = c[t + 1:t + 6]
        fail[t] = len(nxt) == 5 and bool((nxt <= hi55p[t]).any())
    full120 = idx >= 120
    f["bo_failed_120"] = np.where(full120, _window_count(bo & fail, 120, 5), np.nan)
    f["bo_held_120"] = np.where(full120, _window_count(bo & ~fail, 120, 5), np.nan)
    gap_bo = bo & (o > np.nan_to_num(hi55p, nan=np.inf))
    nb = _window_count(bo, 260, 1)
    f["bo_gap_through_freq"] = np.where(nb >= 3, _window_count(gap_bo, 260, 1) / np.maximum(nb, 1), np.nan)
    f["_near_high"] = np.where(np.isnan(hi55p), np.nan, (c >= NEAR_HIGH * hi55p).astype(float))

    value = c * v
    med60 = pd.Series(value).rolling(60, min_periods=60).median().to_numpy()
    f["td_log_value60"] = np.log10(np.where(med60 > 0, med60, np.nan))
    v20 = pd.Series(value).rolling(20, min_periods=20).mean().to_numpy()
    f["td_slippage_pct"] = np.array([float(CC.slippage_pct(cost_model, x)) if np.isfinite(x) else np.nan for x in v20])
    pc = np.concatenate([[np.nan], c[:-1]])
    gap = o / pc - 1
    trp = (np.maximum(h, pc) - np.minimum(lo, pc)) / pc
    gabs = pd.Series(np.abs(gap)).rolling(60, min_periods=60).mean().to_numpy()
    f["td_gap_abs60"] = gabs
    f["td_gap_share60"] = gabs / pd.Series(trp).rolling(60, min_periods=60).mean().to_numpy()
    f["td_gap_down2_120"] = pd.Series(np.where(np.isnan(gap), np.nan, (gap <= -0.02).astype(float))).rolling(
        120, min_periods=120).mean().to_numpy()

    # historical target-before-stop outcomes of entries t (open of t+1), complete when t + 5 <= D
    k = np.arange(1, LB.SESSIONS + 1)
    have = idx + LB.SESSIONS <= n - 1
    t_ok = idx[have]
    win = t_ok[:, None] + k
    O, H, L, C = (a[win] for a in (o, h, lo, c))
    r = LB.target_before_stop(O[:, 0], O, H, L, C, 1.05, 0.98)
    target = np.zeros(n, dtype=bool)
    gapstop = np.zeros(n, dtype=bool)
    done = np.zeros(n, dtype=bool)
    done[t_ok] = True
    target[t_ok] = r["outcome"] == "TARGET"
    exit_open = O[np.arange(len(t_ok)), np.maximum(r["exit_k"], 0)]
    gapstop[t_ok] = (r["outcome"] == "STOP") & LB._down(exit_open, O[:, 0] * 0.98)
    cnt = _window_count(done, 250, 5)
    f["td_hist_target"] = np.where(cnt >= MIN_HIST, _window_count(target, 250, 5) / np.maximum(cnt, 1), np.nan)
    f["td_hist_gapstop"] = np.where(cnt >= MIN_HIST, _window_count(gapstop, 250, 5) / np.maximum(cnt, 1), np.nan)
    return f


def build(bars: pd.DataFrame, atr_pct: pd.DataFrame, cal: pd.DatetimeIndex, industry: dict, block: DS.Block,
          cost_model=None) -> pd.DataFrame:
    """Groups C and D for every (symbol, date) bar. `atr_pct`: columns symbol, date, atr_pct (the v4 feature)."""
    DS.guard_bars(bars.date, block)
    cost_model = cost_model or CC.load_cost_model(DS.COST_MODEL)
    b = bars.sort_values(["symbol", "date"]).reset_index(drop=True)
    b = b.merge(atr_pct[["symbol", "date", "atr_pct"]], on=["symbol", "date"], how="left", validate="1:1")
    parts = []
    for sym, g in b.groupby("symbol", sort=False):
        atr = g.atr_pct.to_numpy(float) / 100 * g.close.to_numpy(float)
        f = symbol_features(g, atr, cost_model)
        parts.append(pd.DataFrame(f, index=g.index).assign(symbol=sym, date=g.date.to_numpy()))
    out = pd.concat(parts).sort_index()
    near = out.pivot(index="date", columns="symbol", values="_near_high").reindex(pd.DatetimeIndex(cal, name="date"))
    syms = list(near.columns)
    share = FP._loo_mean(near, pd.Series({s: industry[s] for s in syms}))
    peer = share.stack(future_stack=True).rename("bo_peer_share")
    peer.index.names = ["date", "symbol"]
    peer = peer.reset_index()
    out = out.merge(peer, on=["date", "symbol"], how="left", validate="1:1")
    return out[["symbol", "date", *GROUP_C, *GROUP_D]]
