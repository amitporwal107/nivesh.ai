"""Tests for the Phase 4 group A/B features on synthetic data only (PREREGISTRATION_P4_AB.md §11 deliverable 2).
run: /app/research/tpd3_forward/venv/bin/python -m pytest -q test_features_p4.py
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset as DS  # noqa: E402
import features_p4 as FP  # noqa: E402

from nidp.services.tpd_model.features import compute_features  # noqa: E402
from nidp.services.tpd_model.technical_ext import wilder_adx  # noqa: E402

CAL = pd.bdate_range("2021-01-01", periods=300)
IND = {"S1": "X", "S2": "X", "S3": "X", "S4": "X", "S5": "X", "T1": "Y", "T2": "Y", "T3": "Y",
       "U1": "Z", "U2": "Z", "U3": "Z", "U4": "Z"}
D_I = 250
D = CAL[D_I]


def _series(rng, n, start):
    c = start * np.cumprod(1 + rng.normal(0, 0.012, n))
    o = c * (1 + rng.normal(0, 0.004, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.005, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.005, n)))
    return o, h, lo, c


def make(seed=11):
    rng = np.random.default_rng(seed)
    rows = []
    for j, s in enumerate(IND):
        o, h, lo, c = _series(rng, len(CAL), 100 + 10 * j)
        v = rng.integers(1e5, 5e5, len(CAL)).astype(float)
        for i, d in enumerate(CAL):
            rows.append((s, d, o[i], h[i], lo[i], c[i], v[i]))
    bars = pd.DataFrame(rows, columns=["symbol", "date", "open", "high", "low", "close", "volume"])
    bars = bars[~((bars.symbol == "S5") & (bars.date == D))]                  # S5 has no bar on D
    bars = bars[~((bars.symbol == "U4") & (bars.date == CAL[D_I - 20]))]     # U4 lacks the bar 20 sessions back
    idx = {}
    for name, start in (("NIFTY 500", 10000), ("NIFTY 50", 15000), ("INDIA VIX", 15)):
        o, h, lo, c = _series(rng, len(CAL), start)
        idx[name] = pd.DataFrame({"open": o, "high": h, "low": lo, "close": c}, index=pd.DatetimeIndex(CAL, name="date"))
    return bars.reset_index(drop=True), idx


BLOCK = DS.Block("dev", CAL[0].date(), CAL[-6].date(), CAL[-1].date(), ("dev",))


@pytest.fixture(scope="module")
def built():
    bars, idx = make()
    return bars, idx, FP.build(bars, idx, CAL, IND, BLOCK).set_index(["symbol", "date"])


def close(bars, s, i):
    x = bars[(bars.symbol == s) & (bars.date == CAL[i])].close
    return float(x.iloc[0]) if len(x) else np.nan


def ret(bars, s, k, i=D_I):
    return close(bars, s, i) / close(bars, s, i - k) - 1


def test_columns_are_the_frozen_30():
    assert len(FP.GROUP_A) == 16 and len(FP.GROUP_B) == 14 and not set(FP.GROUP_A) & set(FP.GROUP_B)


def test_group_a_hand_computed(built):
    bars, idx, f = built
    row = f.loc[("S1", D)]
    c = idx["NIFTY 500"].close.to_numpy()
    r = np.diff(c) / c[:-1]
    assert row.mkt_ret20 == pytest.approx(c[D_I] / c[D_I - 20] - 1)
    assert row.mkt_ret60 == pytest.approx(c[D_I] / c[D_I - 60] - 1)
    assert row.mkt_dist_sma200 == pytest.approx(c[D_I] / c[D_I - 199:D_I + 1].mean() - 1)
    assert row.mkt_vol20 == pytest.approx(np.std(r[D_I - 20:D_I], ddof=1))
    assert row.mkt_vol_ratio == pytest.approx(np.std(r[D_I - 20:D_I], ddof=1) / np.std(r[D_I - 100:D_I], ddof=1))
    n5 = idx["NIFTY 500"]
    assert row.mkt_gap1 == pytest.approx(n5.open.iloc[D_I] / c[D_I - 1] - 1)
    assert row.mkt_range1 == pytest.approx((n5.high.iloc[D_I] - n5.low.iloc[D_I]) / c[D_I - 1])
    lo_i = D_I + 1 - 260 if D_I + 1 >= 260 else 0
    assert row.mkt_adx14 == pytest.approx(wilder_adx(n5.high.to_numpy()[lo_i:D_I + 1], n5.low.to_numpy()[lo_i:D_I + 1], c[lo_i:D_I + 1]))
    v = idx["INDIA VIX"].close.to_numpy()
    assert row.vix_close == pytest.approx(v[D_I]) and row.vix_chg5 == pytest.approx(v[D_I] / v[D_I - 5] - 1)
    c50 = idx["NIFTY 50"].close.to_numpy()
    assert row.size_rot20 == pytest.approx((c50[D_I] / c50[D_I - 20] - 1) - (c[D_I] / c[D_I - 20] - 1))
    # breadth: stocks with a bar on D; own last-20 average
    on_d = bars[bars.date == D].symbol
    above = []
    for s in on_d:
        own = bars[(bars.symbol == s) & (bars.date <= D)].close.to_numpy()
        above.append(own[-1] > own[-20:].mean())
    assert row.breadth_sma20 == pytest.approx(np.mean(above))
    days = []
    for i in range(D_I - 4, D_I + 1):
        ups = []
        for s in bars[bars.date == CAL[i]].symbol:
            own = bars[(bars.symbol == s) & (bars.date <= CAL[i])].close.to_numpy()
            ups.append(own[-1] > own[-2])
        days.append(np.mean(ups))
    assert row.breadth5 == pytest.approx(np.mean(days))
    # identical for every stock on the day
    assert f.xs(D, level="date")[list(FP.GROUP_A)].nunique().max() == 1


def test_group_b_relative_returns_and_peers(built):
    bars, idx, f = built
    c = idx["NIFTY 500"].close.to_numpy()
    s1 = f.loc[("S1", D)]
    assert s1.rs_mkt20 == pytest.approx(ret(bars, "S1", 20) - (c[D_I] / c[D_I - 20] - 1))
    peers = [ret(bars, s, 20) for s in ("S2", "S3", "S4")]                     # S5 has no bar on D
    assert s1.sec_ret20 == pytest.approx(np.mean(peers))
    assert s1.rs_sec20 == pytest.approx(ret(bars, "S1", 20) - np.mean(peers))
    assert np.isnan(f.loc[("T1", D)].sec_ret20)                                # only 2 peers in Y
    assert np.isnan(f.loc[("T1", D)].rs_sec5) and np.isnan(f.loc[("T1", D)].sec_breadth20)
    assert np.isnan(f.loc[("U4", D)].rs_mkt20)                                 # no bar 20 sessions back
    assert np.isnan(f.loc[("U1", D)].sec_ret20)                                # U4 missing -> 2 valid peers
    assert not np.isnan(f.loc[("U1", D)].sec_ret5)                             # but 3 peers for ret5
    assert ("S5", D) not in f.index


def test_sector_rank_breadth_volume_and_momentum_rank(built):
    bars, idx, f = built
    means = {g: np.nanmean([ret(bars, s, 20) for s in IND if IND[s] == g]) for g in ("X", "Y", "Z")}
    ranks = pd.Series(means).rank(pct=True)
    for s in ("S1", "T1", "U1"):
        assert f.loc[(s, D)].sec_rank20 == pytest.approx(ranks[IND[s]])

    def above20(s):
        own = bars[(bars.symbol == s) & (bars.date <= D)]
        if own.date.iloc[-1] != D:
            return np.nan
        own = own.close.to_numpy()
        return float(own[-1] > own[-20:].mean())
    assert f.loc[("S1", D)].sec_breadth20 == pytest.approx(np.nanmean([above20(s) for s in ("S2", "S3", "S4", "S5")]))

    def vratio(s):
        own = bars[(bars.symbol == s) & (bars.date <= D)]
        if own.date.iloc[-1] != D:
            return np.nan
        v = own.volume.to_numpy()
        return v[-1] / v[-21:-1].mean()
    assert f.loc[("S1", D)].rel_vol_sec == pytest.approx(vratio("S1") - np.median([vratio(s) for s in ("S2", "S3", "S4")]))
    r20 = pd.Series({s: ret(bars, s, 20) for s in IND}).dropna()
    assert f.loc[("S3", D)].mom_rank20 == pytest.approx(r20.rank(pct=True)["S3"])


def test_future_bars_do_not_change_past_values():
    bars, idx = make()
    base = FP.build(bars, idx, CAL, IND, BLOCK)
    b2 = bars.copy()
    m = b2.date > D
    b2.loc[m, ["open", "high", "low", "close"]] *= 1.7
    b2.loc[m, "volume"] *= 9
    i2 = {k: v.copy() for k, v in idx.items()}
    for v in i2.values():
        v.loc[v.index > D] *= 0.6
    shocked = FP.build(b2, i2, CAL, IND, BLOCK)
    a = base[base.date <= D].reset_index(drop=True)
    b = shocked[shocked.date <= D].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)
    assert not base[base.date > D].reset_index(drop=True).equals(shocked[shocked.date > D].reset_index(drop=True))


def test_bars_after_the_block_are_refused():
    bars, idx = make()
    short = DS.Block("dev", CAL[0].date(), CAL[200].date(), CAL[210].date(), ("dev",))
    with pytest.raises(DS.SealedDataError):
        FP.build(bars, idx, CAL, IND, short)
    cut = bars[bars.date <= CAL[210]]
    with pytest.raises(DS.SealedDataError):
        FP.build(cut, idx, CAL[:211], IND, short)                           # index frames still run past the block
    FP.build(cut, {k: v[v.index <= CAL[210]] for k, v in idx.items()}, CAL[:211], IND, short)


def test_daily_breadth_matches_v4(built):
    bars, _, _ = built
    b = DS.prepare(bars)
    panel = DS.to_panel(b)
    T = CAL[D_I - 3]
    v4 = compute_features(panel[panel.as_of_date <= T], T.date(), market_members=set(IND))
    assert FP.daily_breadth(bars.sort_values(["symbol", "date"]).reset_index(drop=True), CAL)[T] == pytest.approx(v4.breadth.iloc[0])


def test_adx_uses_the_last_260_index_sessions(built):
    _, idx, f = built
    i = 290
    n5 = idx["NIFTY 500"]
    h, lo, c = (n5[k].to_numpy() for k in ("high", "low", "close"))
    want = wilder_adx(h[i + 1 - 260:i + 1], lo[i + 1 - 260:i + 1], c[i + 1 - 260:i + 1])
    assert f.loc[("S1", CAL[i])].mkt_adx14 == pytest.approx(want)
    assert want != pytest.approx(wilder_adx(h[:i + 1], lo[:i + 1], c[:i + 1]), rel=1e-6)
