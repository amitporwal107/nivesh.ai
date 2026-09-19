"""Phase 4 feature groups A (market regime, 16) and B (sector-relative strength and stock-relative momentum, 14):
PREREGISTRATION_P4_AB.md §3, FROZEN at ac54c1b4. Every value for decision day D uses bars dated on or before D only
(rolling windows and shifts are causal; cross-sections use day D alone); test_features_p4.py checks that changing any
bar after D leaves D's values unchanged.

Conventions (fixed by the pre-registration or by the v4 code they extend):
- ret_k = close(D) / close(k calendar sessions before D) - 1 on the NSE calendar (the NIFTY 500 session list); NaN if
  the stock has no bar on either date. Index returns use each index's own session series.
- Peers = the other universe members of the stock's industry with the needed values (leave-one-out); fewer than 3 -> NaN.
- A stock's own 20/50-session average is over its own last 20/50 bars (as v4's calc.sma); it counts only with that many.
- Standard deviations use pandas' default ddof = 1. ADX(14) is technical_ext.wilder_adx on the last 260 index sessions
  (the v4 WINDOW), as the v4 extensions compute it for stocks.
- The one-day breadth is v4's: the share of universe stocks with a bar on D whose one-day return is positive.
"""
from __future__ import annotations

import os
import sys
import warnings

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset as DS  # noqa: E402

from nidp.services.tpd_model.features import WINDOW  # noqa: E402
from nidp.services.tpd_model.technical_ext import wilder_adx  # noqa: E402

GROUP_A = ("mkt_ret5", "mkt_ret20", "mkt_ret60", "mkt_dist_sma50", "mkt_dist_sma200", "mkt_adx14", "mkt_vol20",
           "mkt_vol_ratio", "mkt_gap1", "mkt_range1", "vix_close", "vix_chg5", "breadth_sma20", "breadth_sma50",
           "breadth5", "size_rot20")
GROUP_B = ("rs_mkt5", "rs_mkt20", "rs_mkt60", "sec_ret5", "sec_ret20", "sec_ret60", "rs_sec5", "rs_sec20", "rs_sec60",
           "sec_rank20", "sec_breadth20", "rel_vol_sec", "mom_rank20", "mom_rank60")
MIN_PEERS = 3
INDEX_FILE = os.path.join(DS.OUT, "index_p4.csv")


def load_index(block: DS.Block, path: str = INDEX_FILE) -> dict:
    """{name: DataFrame(date index; open, high, low, close)} for NIFTY 500, NIFTY 50, INDIA VIX, cut at the block end."""
    x = pd.read_csv(path, parse_dates=["date"])
    DS.guard_bars(x.date, block, "index bars")
    return {n: g.set_index("date").sort_index()[["open", "high", "low", "close"]] for n, g in x.groupby("index")}


def _wide(bars: pd.DataFrame, cal: pd.DatetimeIndex, col: str) -> pd.DataFrame:
    return bars.pivot(index="date", columns="symbol", values=col).reindex(cal)


def _own_sma(bars: pd.DataFrame, n: int) -> pd.Series:
    """Each stock's mean of its own last n closes (NaN until it has n bars), aligned to `bars`."""
    return bars.groupby("symbol", sort=False).close.transform(lambda s: s.rolling(n, min_periods=n).mean())


def daily_breadth(bars: pd.DataFrame, cal: pd.DatetimeIndex) -> pd.Series:
    """v4 `breadth`: share of stocks with a bar on D (and a prior bar) whose own one-day return is positive."""
    r1 = bars.close / bars.groupby("symbol", sort=False).close.shift(1) - 1
    w = pd.DataFrame({"date": bars.date, "up": (r1 > 0).astype(float).where(r1.notna())})
    return w.groupby("date").up.mean().reindex(cal)


def group_a(bars: pd.DataFrame, idx: dict, cal: pd.DatetimeIndex) -> pd.DataFrame:
    """The 16 regime features for every calendar date (index = date)."""
    n5, n50, vix = idx["NIFTY 500"], idx["NIFTY 50"], idx["INDIA VIX"]
    c = n5.close
    r = c.pct_change()
    out = pd.DataFrame(index=n5.index)
    for k in (5, 20, 60):
        out[f"mkt_ret{k}"] = c / c.shift(k) - 1
    out["mkt_dist_sma50"] = c / c.rolling(50, min_periods=50).mean() - 1
    out["mkt_dist_sma200"] = c / c.rolling(200, min_periods=200).mean() - 1
    h, lo, cc = (n5[k].to_numpy(float) for k in ("high", "low", "close"))
    out["mkt_adx14"] = [wilder_adx(h[max(0, i + 1 - WINDOW):i + 1], lo[max(0, i + 1 - WINDOW):i + 1],
                                   cc[max(0, i + 1 - WINDOW):i + 1]) for i in range(len(cc))]
    out["mkt_vol20"] = r.rolling(20, min_periods=20).std()
    out["mkt_vol_ratio"] = out.mkt_vol20 / r.rolling(100, min_periods=100).std()
    out["mkt_gap1"] = n5.open / c.shift(1) - 1
    out["mkt_range1"] = (n5.high - n5.low) / c.shift(1)
    v = vix.close
    out = out.join(pd.DataFrame({"vix_close": v, "vix_chg5": v / v.shift(5) - 1}), how="left")
    out["size_rot20"] = (n50.close / n50.close.shift(20) - 1).reindex(out.index) - out.mkt_ret20
    out = out.reindex(cal)
    for n in (20, 50):
        above = (bars.close > _own_sma(bars, n)).astype(float).where(_own_sma(bars, n).notna())
        out[f"breadth_sma{n}"] = above.groupby(bars.date).mean().reindex(cal)
    out["breadth5"] = daily_breadth(bars, cal).rolling(5, min_periods=5).mean()
    out.index.name = "date"
    return out[list(GROUP_A)]


def _loo_mean(X: pd.DataFrame, ind: pd.Series) -> pd.DataFrame:
    """Leave-one-out equal-weight mean of each column's industry peers per row (date); NaN below MIN_PEERS peers."""
    out = pd.DataFrame(np.nan, index=X.index, columns=X.columns)
    for _, cols in ind.groupby(ind).groups.items():
        sub = X[list(cols)]
        valid = sub.notna()
        s, n = sub.sum(axis=1, min_count=0), valid.sum(axis=1)
        own, own_n = sub.fillna(0.0), valid.astype(float)
        peers = n.to_numpy()[:, None] - own_n.to_numpy()
        vals = (s.to_numpy()[:, None] - own.to_numpy()) / np.where(peers > 0, peers, np.nan)
        out[list(cols)] = np.where(peers >= MIN_PEERS, vals, np.nan)
    return out


def group_b(bars: pd.DataFrame, idx: dict, cal: pd.DatetimeIndex, industry: dict) -> pd.DataFrame:
    """The 14 relative-strength features for every (symbol, date) bar (long format)."""
    C = _wide(bars, cal, "close")
    syms = list(C.columns)
    ind = pd.Series({s: industry[s] for s in syms})
    mkt = idx["NIFTY 500"].close
    feats = {}
    for k in (5, 20, 60):
        rk = C / C.shift(k) - 1
        m = (mkt / mkt.shift(k) - 1).reindex(cal)
        sec = _loo_mean(rk, ind)
        feats[f"rs_mkt{k}"] = rk.sub(m, axis=0)
        feats[f"sec_ret{k}"] = sec
        feats[f"rs_sec{k}"] = rk - sec
        if k == 20:
            ret20 = rk
        if k == 60:
            ret60 = rk
    # industry 20-session return over all members, ranked among industries on each day
    sec_all = pd.DataFrame({g: ret20[list(cols)].mean(axis=1) for g, cols in ind.groupby(ind).groups.items()})
    rank = sec_all.rank(axis=1, pct=True)
    feats["sec_rank20"] = pd.DataFrame({s: rank[ind[s]] for s in syms}, index=cal)
    above = _wide(bars.assign(a=(bars.close > _own_sma(bars, 20)).astype(float).where(_own_sma(bars, 20).notna())),
                  cal, "a")
    feats["sec_breadth20"] = _loo_mean(above, ind)
    prior20 = bars.groupby("symbol", sort=False).volume.transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean())
    vr = (bars.volume / prior20).replace([np.inf, -np.inf], np.nan)          # a zero prior average has no ratio
    ratio = _wide(bars.assign(vr=vr), cal, "vr")
    feats["rel_vol_sec"] = ratio - _loo_median(ratio, ind)
    feats["mom_rank20"] = ret20.rank(axis=1, pct=True)
    feats["mom_rank60"] = ret60.rank(axis=1, pct=True)
    long = pd.concat({name: f.stack(future_stack=True) for name, f in feats.items()}, axis=1)
    long.index.names = ["date", "symbol"]
    have = pd.MultiIndex.from_frame(bars[["date", "symbol"]])
    return long.reindex(have).reset_index()[["symbol", "date", *GROUP_B]]


def _loo_median(X: pd.DataFrame, ind: pd.Series) -> pd.DataFrame:
    """Median of each column's industry peers per row, leaving the column itself out; NaN below MIN_PEERS peers."""
    out = pd.DataFrame(np.nan, index=X.index, columns=X.columns)
    for _, cols in ind.groupby(ind).groups.items():
        cols = list(cols)
        A = X[cols].to_numpy(float)
        res = np.full(A.shape, np.nan)
        for j in range(len(cols)):
            others = np.delete(A, j, axis=1)
            cnt = np.sum(~np.isnan(others), axis=1)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)          # all-NaN rows -> NaN, dropped by cnt below
                med = np.nanmedian(others, axis=1) if others.shape[1] else np.full(len(A), np.nan)
            res[:, j] = np.where(cnt >= MIN_PEERS, med, np.nan)
        out[cols] = res
    return out


def build(bars: pd.DataFrame, idx: dict, cal: pd.DatetimeIndex, industry: dict, block: DS.Block) -> pd.DataFrame:
    """Groups A and B for every (symbol, date) bar in `bars` (long format). Refuses bars after the block end."""
    DS.guard_bars(bars.date, block)
    for name, x in idx.items():
        DS.guard_bars(pd.Series(x.index), block, f"{name} bars")
    bars = bars.sort_values(["symbol", "date"]).reset_index(drop=True)
    a = group_a(bars, idx, cal)
    b = group_b(bars, idx, cal, industry)
    return b.merge(a.reset_index(), on="date", how="left")[["symbol", "date", *GROUP_A, *GROUP_B]]
