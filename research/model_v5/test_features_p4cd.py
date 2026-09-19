"""Tests for the Phase 4 group C/D features on synthetic data only (PREREGISTRATION_P4_CD.md §9 deliverable 1).
The vectorised module is compared with a deliberately naive per-row reference written here, including an
independent scalar implementation of the frozen target-before-stop rule.
run: /app/research/tpd3_forward/venv/bin/python -m pytest -q test_features_p4cd.py
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset as DS  # noqa: E402
import features_p4cd as FC  # noqa: E402

from nidp.services.tpd_model.risk import costs as CC  # noqa: E402

CM = CC.load_cost_model(DS.COST_MODEL)
CAL = pd.bdate_range("2021-01-01", periods=420)
IND = {"A1": "X", "A2": "X", "A3": "X", "A4": "X", "B1": "Y", "B2": "Y", "B3": "Y"}
BLOCK = DS.Block("dev", CAL[0].date(), CAL[-6].date(), CAL[-1].date(), ("dev",))
NAN = np.nan


def series(seed, n=len(CAL), start=200.0, trend=0.0015, vol=0.02):
    """A trending random walk with frequent new highs, gaps and occasional large drops."""
    rng = np.random.default_rng(seed)
    c = start * np.cumprod(1 + trend + rng.normal(0, vol, n))
    gap = rng.normal(0, 0.012, n)
    gap[rng.random(n) < 0.04] -= 0.035
    o = np.concatenate([[start], c[:-1]]) * (1 + gap)
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.008, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.008, n)))
    v = rng.integers(2e5, 9e5, n).astype(float)
    return o, h, lo, c, v


def make(seed=3):
    rows, atr_rows = [], []
    for j, s in enumerate(IND):
        o, h, lo, c, v = series(seed + j, start=100 + 20 * j)
        atr = np.abs(np.random.default_rng(seed + 100 + j).normal(2.0, 0.4, len(CAL)))
        for i, d in enumerate(CAL):
            rows.append((s, d, o[i], h[i], lo[i], c[i], v[i]))
            atr_rows.append((s, d, atr[i]))
    bars = pd.DataFrame(rows, columns=["symbol", "date", "open", "high", "low", "close", "volume"])
    bars = bars[~((bars.symbol == "A4") & (bars.date == CAL[300]))].reset_index(drop=True)    # one missing bar
    atr = pd.DataFrame(atr_rows, columns=["symbol", "date", "atr_pct"])
    return bars, atr


# ---------- naive reference ----------

def ref_tbs(o, h, lo, c, t):
    """Scalar frozen rule: entry = open of t+1; per bar: open<=stop gap stop, open>=target gap target, low<=stop stop,
    high>=target target; else expire at the last close. Returns (outcome, gapstop)."""
    e = o[t + 1]
    tgt, stp = e * 1.05, e * 0.98
    for k in range(t + 1, t + 6):
        if o[k] <= stp * (1 + 1e-9):
            return "STOP", True
        if o[k] >= tgt * (1 - 1e-9):
            return "TARGET", False
        if lo[k] <= stp * (1 + 1e-9):
            return "STOP", False
        if h[k] >= tgt * (1 - 1e-9):
            return "TARGET", False
    return "EXPIRED", False


def ref_symbol(o, h, lo, c, v, atr_pct):
    n = len(c)
    atr = atr_pct / 100 * c
    hi55p = np.array([h[i - 55:i].max() if i >= 55 else NAN for i in range(n)])
    hi20p = np.array([h[i - 20:i].max() if i >= 20 else NAN for i in range(n)])
    bo = np.array([not np.isnan(hi55p[i]) and c[i] > hi55p[i] for i in range(n)])
    out = {k: np.full(n, NAN) for k in (*FC.GROUP_C, *FC.GROUP_D) if k != "bo_peer_share"}
    outcomes = {t: ref_tbs(o, h, lo, c, t) for t in range(n - 5)}
    for i in range(n):
        out["bo_dist_atr55"][i] = (c[i] - hi55p[i]) / atr[i]
        out["bo_dist_atr20"][i] = (c[i] - hi20p[i]) / atr[i]
        out["bo_dist_pct55"][i] = c[i] / hi55p[i] - 1
        js = [j for j in range(max(0, i - 259), i + 1) if bo[j]]
        out["bo_days_since"][i] = i - js[-1] if js else NAN
        js = [j for j in range(max(0, i - 9), i + 1) if bo[j]]
        if js:
            j = js[-1]
            out["bo_vol_last"][i] = v[j] / v[j - 20:j].mean() if j >= 20 else NAN
            out["bo_close_pos_last"][i] = (c[j] - lo[j]) / (h[j] - lo[j]) if h[j] > lo[j] else 0.5
        js = [j for j in range(max(0, i - 10), i) if bo[j]]
        if js:
            out["bo_follow_through"][i] = c[i] / c[js[-1]] - 1
        if i >= 120:
            ts = [t for t in range(i - 120, i - 4) if bo[t]]
            failed = [t for t in ts if (c[t + 1:t + 6] <= hi55p[t]).any()]
            out["bo_failed_120"][i], out["bo_held_120"][i] = len(failed), len(ts) - len(failed)
        ts = [t for t in range(max(0, i - 260), i) if bo[t]]
        if len(ts) >= 3:
            out["bo_gap_through_freq"][i] = np.mean([o[t] > hi55p[t] for t in ts])
        if i >= 59:
            val = c[i - 59:i + 1] * v[i - 59:i + 1]
            out["td_log_value60"][i] = np.log10(np.median(val))
        if i >= 19:
            out["td_slippage_pct"][i] = float(CC.slippage_pct(CM, np.mean(c[i - 19:i + 1] * v[i - 19:i + 1])))
        if i >= 60:
            g = [abs(o[t] / c[t - 1] - 1) for t in range(i - 59, i + 1)]
            tr = [(max(h[t], c[t - 1]) - min(lo[t], c[t - 1])) / c[t - 1] for t in range(i - 59, i + 1)]
            out["td_gap_abs60"][i] = np.mean(g)
            out["td_gap_share60"][i] = np.mean(g) / np.mean(tr)
        if i >= 120:
            out["td_gap_down2_120"][i] = np.mean([o[t] / c[t - 1] - 1 <= -0.02 for t in range(i - 119, i + 1)])
        ts = [t for t in range(max(0, i - 250), i - 4)]
        if len(ts) >= FC.MIN_HIST:
            res = [outcomes[t] for t in ts]
            out["td_hist_target"][i] = np.mean([r[0] == "TARGET" for r in res])
            out["td_hist_gapstop"][i] = np.mean([r[1] for r in res])
    return out


def test_group_sizes():
    assert len(FC.GROUP_C) == 11 and len(FC.GROUP_D) == 7 and not set(FC.GROUP_C) & set(FC.GROUP_D)


def test_module_matches_the_naive_reference():
    seen = {k: 0.0 for k in ("failed", "held", "gapstop", "target", "gapfreq", "follow")}
    for seed, trend in ((1, 0.0015), (2, 0.004), (3, 0.006), (4, -0.001)):
        o, h, lo, c, v = series(seed, trend=trend)
        atr_pct = np.abs(np.random.default_rng(seed).normal(2, 0.3, len(c)))
        g = pd.DataFrame({"open": o, "high": h, "low": lo, "close": c, "volume": v})
        got = FC.symbol_features(g, atr_pct / 100 * c, CM)
        want = ref_symbol(o, h, lo, c, v, atr_pct)
        for k, w in want.items():
            np.testing.assert_allclose(got[k], w, rtol=1e-12, atol=1e-12, equal_nan=True, err_msg=f"seed {seed} {k}")
        seen["failed"] += np.nansum(want["bo_failed_120"])
        seen["held"] += np.nansum(want["bo_held_120"])
        seen["gapstop"] += np.nansum(want["td_hist_gapstop"])
        seen["target"] += np.nansum(want["td_hist_target"])
        seen["gapfreq"] += np.nansum(want["bo_gap_through_freq"])
        seen["follow"] += np.isfinite(want["bo_follow_through"]).sum()
    assert all(v > 0 for v in seen.values()), seen             # the synthetic series exercise every branch


def test_hand_built_breakouts_and_the_completion_rule():
    n = 200
    h = np.full(n, 100.0); lo = np.full(n, 98.0); c = np.full(n, 99.0); o = np.full(n, 99.0); v = np.full(n, 1e5)
    # breakout at 130 that fails (close back at 99 on 132); breakout at 150 that holds; breakout at 197 (inside D-5)
    c[130], h[130] = 101.0, 101.5
    c[150:], h[150:], lo[150:], o[150:] = 103.0, 103.5, 102.5, 103.0
    c[197], h[197] = 110.0, 110.5
    g = pd.DataFrame({"open": o, "high": h, "low": lo, "close": c, "volume": v})
    f = FC.symbol_features(g, np.full(n, 2.0), CM)
    D = 199
    assert f["bo_failed_120"][D] == 1 and f["bo_held_120"][D] == 1            # 197 is not yet complete (t > D-5)
    assert f["bo_days_since"][D] == 2 and f["bo_follow_through"][D] == pytest.approx(103.0 / 110.0 - 1)   # from bar 197
    assert f["bo_failed_120"][155] == 1 and f["bo_held_120"][155] == 1        # 150 complete at 155
    assert f["bo_held_120"][154] == 0                                         # ... but not at 154
    assert np.isnan(f["bo_failed_120"][119]) and f["bo_failed_120"][120] == 0


def test_peer_share_is_leave_one_out_with_three_peers():
    bars, atr = make()
    out = FC.build(bars, atr, CAL, IND, BLOCK).set_index(["symbol", "date"])
    d = CAL[250]
    near = {}
    for s in IND:
        x = bars[(bars.symbol == s) & (bars.date <= d)]
        hi = x.high.to_numpy()[-56:-1].max()
        near[s] = float(x.close.iloc[-1] >= 0.97 * hi)
    assert out.loc[("A1", d)].bo_peer_share == pytest.approx(np.mean([near[s] for s in ("A2", "A3", "A4")]))
    assert np.isnan(out.loc[("B1", d)].bo_peer_share)                         # Y has 2 peers
    assert np.isnan(out.loc[("A1", CAL[300])].bo_peer_share)                  # A4 has no bar that day -> 2 peers


def test_future_bars_do_not_change_past_values():
    bars, atr = make()
    base = FC.build(bars, atr, CAL, IND, BLOCK)
    D = CAL[260]
    b2 = bars.copy()
    m = b2.date > D
    b2.loc[m, ["open", "high", "low", "close"]] *= np.random.default_rng(9).uniform(0.7, 1.4, (m.sum(), 1))
    b2.loc[m, "volume"] *= 5
    a2 = atr.copy()
    a2.loc[a2.date > D, "atr_pct"] *= 3
    shocked = FC.build(b2, a2, CAL, IND, BLOCK)
    x = base[base.date <= D].reset_index(drop=True)
    y = shocked[shocked.date <= D].reset_index(drop=True)
    pd.testing.assert_frame_equal(x, y)
    assert not base[base.date > D].reset_index(drop=True).equals(shocked[shocked.date > D].reset_index(drop=True))


def test_bars_after_the_block_are_refused():
    bars, atr = make()
    short = DS.Block("dev", CAL[0].date(), CAL[300].date(), CAL[310].date(), ("dev",))
    with pytest.raises(DS.SealedDataError):
        FC.build(bars, atr, CAL, IND, short)


def test_build_matches_symbol_features_for_every_stock():
    bars, atr = make()
    out = FC.build(bars, atr, CAL, IND, BLOCK)
    for s in ("A2", "A4", "B3"):
        g = bars[bars.symbol == s].sort_values("date").reset_index(drop=True)
        a = atr.set_index(["symbol", "date"]).loc[list(zip(g.symbol, g.date)), "atr_pct"].to_numpy()
        f = FC.symbol_features(g, a / 100 * g.close.to_numpy(), CM)
        mine = out[out.symbol == s].sort_values("date")
        for k in (*FC.GROUP_C, *FC.GROUP_D):
            if k != "bo_peer_share":
                np.testing.assert_allclose(mine[k].to_numpy(), f[k], equal_nan=True, err_msg=f"{s} {k}")
