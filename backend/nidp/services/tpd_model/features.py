"""Point-in-time features for prediction day T.

Every feature for T comes from a fixed window of the symbol's last WINDOW bars dated on or before T, using
the NIDP technical-indicator calculator (Wilder RSI/ATR seed from the window start, so a fixed bar count
keeps values reproducible), plus:
  * delivery lagged one session — T's delivery file lands after the next open (TECH-3);
  * results-meeting flags only when intimated by 15:30 IST on T (event_gate);
  * corporate-action factors only when ex-dated on or before T.
Changing anything dated after T, or any filing stamped after the cutoff, leaves the output bit-identical.

Fundamentals, sector and news features are deliberately absent: they measured no lift for this target in
the research walk-forward, and B8 requires an ablation before any is added.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from nidp.services.technical_indicator_engine import calculator as calc

from .corporate_actions import multipliers
from .event_gate import results_flag

WINDOW = 260
MOVE = 0.10

PRICE_FEATURES = (
    "rsi14", "atr_pct", "bb_width", "bb_pos", "ret1", "ret5", "ret20", "ret60", "vol_z20",
    "dist_52w_high", "dist_52w_low", "dist_swing20", "dist_sma20", "dist_sma50", "sma50_slope",
    "maxabs20", "turn_med20", "close_raw", "gap1", "range1",
    "n_gap_up_252", "n_high_up_252", "n_range10_252", "nbars",
)
DELIVERY_FEATURES = ("deliv_prev", "deliv_avg20", "deliv_trend10", "deliv_missing")
MARKET_FEATURES = ("mkt_ret1", "breadth")
EVENT_FEATURES = ("res_on_T", "res_on_D")
FEATURE_LIST = PRICE_FEATURES + DELIVERY_FEATURES + MARKET_FEATURES + EVENT_FEATURES

# The observable facts every surfaced row shows, always in this order (user decision D-UX3): results meeting
# on the target session, today's move, volume against its 20-day normal, typical daily range, and past
# +10% days — the strongest factors measured in the research walk-forward. Facts, not attributions.
INPUTS_ON_RECORD = ("res_on_D", "ret1", "vol_z20", "atr_pct", "n_high_up_252")


def _num(x: Optional[float]) -> float:
    return float("nan") if x is None else float(x)


def _next_weekday(T: date) -> date:
    d = T + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _symbol_features(w: pd.DataFrame, T: date, actions: Optional[pd.DataFrame]) -> tuple[dict, dict]:
    """Values and data dates for one symbol from its window `w` (sorted, last row dated T)."""
    sym_actions = None
    if actions is not None and len(actions):
        sym_actions = actions[actions["symbol"] == w["symbol"].iloc[0]]
    m = multipliers(w["as_of_date"], sym_actions, T)
    o = w["open"].to_numpy(dtype="float64") * m
    h = w["high"].to_numpy(dtype="float64") * m
    lo = w["low"].to_numpy(dtype="float64") * m
    c = w["close"].to_numpy(dtype="float64") * m
    vol = w["volume"].to_numpy(dtype="float64") / m
    dates = pd.DatetimeIndex(w["as_of_date"])
    n = len(c)

    f: dict[str, float] = {}
    f["rsi14"] = _num(calc.rsi(c))
    a = calc.atr(h, lo, c)
    f["atr_pct"] = a / c[-1] * 100 if a is not None and c[-1] else float("nan")
    f["bb_width"], f["bb_pos"] = map(_num, calc.bollinger(c))
    f["ret1"] = _num(calc.pct_return(c, 1))
    for b in (5, 20, 60):
        f[f"ret{b}"] = _num(calc.pct_return(c, b))
    f["vol_z20"] = _num(calc.volume_stats(vol)[1])
    f["dist_52w_high"], f["dist_52w_low"] = map(_num, calc.dist_52w(c, h, lo))
    f["dist_swing20"] = _num(calc.dist_from_level(float(c[-1]), calc.swing_high_low(h, lo)[0]))
    f["dist_sma20"] = _num(calc.dist_from_level(float(c[-1]), calc.sma(c, 20)))
    f["dist_sma50"] = _num(calc.dist_from_level(float(c[-1]), calc.sma(c, 50)))
    f["sma50_slope"] = _num(calc.sma_slope(c, 50))

    ret = np.full(n, np.nan)
    if n > 1:
        ret[1:] = (c[1:] / c[:-1] - 1) * 100
    last20 = ret[-20:]
    f["maxabs20"] = float(np.nanmax(np.abs(last20))) if np.count_nonzero(~np.isnan(last20)) >= 15 else float("nan")
    turn = w["turnover"].to_numpy(dtype="float64")[-20:]
    f["turn_med20"] = float(np.median(turn)) if len(turn) >= 10 else float("nan")
    f["close_raw"] = float(w["close"].iloc[-1])
    if n > 1:
        f["gap1"] = (o[-1] / c[-2] - 1) * 100
        f["range1"] = (h[-1] - lo[-1]) / c[-2] * 100
    else:
        f["gap1"] = f["range1"] = float("nan")

    # Past large-move days in the window, measured against the adjusted prior close; ex-dates are skipped
    # because the exchange's own move that day is an adjustment, not trading.
    ex_days = set()
    if sym_actions is not None and len(sym_actions):
        ex_days = {pd.Timestamp(d) for d in sym_actions["ex_date"] if pd.Timestamp(d) <= pd.Timestamp(T)}
    tail = slice(max(1, n - 252), n)
    prev = c[tail.start - 1:n - 1]
    ok = ~np.isin(dates[tail], list(ex_days)) if ex_days else np.ones(n - tail.start, dtype=bool)
    f["n_gap_up_252"] = float(np.sum(ok & (o[tail] / prev - 1 >= MOVE)))
    f["n_high_up_252"] = float(np.sum(ok & (h[tail] / prev - 1 >= MOVE)))
    f["n_range10_252"] = float(np.sum(ok & ((h[tail] - lo[tail]) / prev >= MOVE)))
    f["nbars"] = float(n)

    # Delivery for T is not published until after the next open, so only bars before T count.
    dl = w["deliverable_pct"].to_numpy(dtype="float64")[:-1]
    f["deliv_prev"] = float(dl[-1]) if len(dl) else float("nan")
    f["deliv_missing"] = 1.0 if (not len(dl) or math.isnan(dl[-1])) else 0.0
    avg, slope = calc.delivery_stats(dl) if len(dl) else (None, None)
    f["deliv_avg20"], f["deliv_trend10"] = _num(avg), _num(slope)

    dd = {name: T for name in PRICE_FEATURES}
    prev_date = dates[-2].date() if n > 1 else None
    dd.update({name: prev_date for name in DELIVERY_FEATURES})
    return f, dd


def _compute(panel: pd.DataFrame, T: date, events, actions, target_session: Optional[date]):
    cutoff = pd.Timestamp(T)
    p = panel[panel["as_of_date"] <= cutoff].sort_values(["symbol", "as_of_date"], kind="mergesort")
    on_t = set(p.loc[p["as_of_date"] == cutoff, "symbol"])
    D = target_session or _next_weekday(T)

    values: dict[str, dict] = {}
    meta: dict[str, dict] = {}
    for sym, g in p.groupby("symbol", sort=True):
        if sym not in on_t:
            continue
        f, dd = _symbol_features(g.tail(WINDOW), T, actions)
        values[sym], meta[sym] = f, {"data_date": dd, "source_ts": {}}

    # Only meetings dated T or D can set a flag, so filter the filings once rather than per symbol
    # (a real day with ~20k filings and ~2,100 symbols: 7.9 s -> 3.7 s). results_flag still decides each flag.
    by_symbol: dict[str, pd.DataFrame] = {}
    if events is not None:
        days = [pd.Timestamp(T), pd.Timestamp(D)]
        relevant = events[events["event_date"].isin(days) & events["symbol"].isin(values.keys())]
        by_symbol = {sym: g for sym, g in relevant.groupby("symbol", sort=False)}
        empty = events.iloc[0:0]

    rets = np.array([v["ret1"] for v in values.values()], dtype="float64")
    rets = rets[~np.isnan(rets)]
    mkt_ret1 = float(np.mean(rets)) if len(rets) else float("nan")
    breadth = float(np.mean(rets > 0)) if len(rets) else float("nan")

    for sym, f in values.items():
        f["mkt_ret1"], f["breadth"] = mkt_ret1, breadth
        meta[sym]["data_date"].update({"mkt_ret1": T, "breadth": T})
        for name, day in (("res_on_T", T), ("res_on_D", D)):
            if events is None:
                f[name], ts = float("nan"), None
            else:
                flag, ts = results_flag(by_symbol.get(sym, empty), sym, T, day)
                f[name] = float("nan") if flag is None else float(flag)
            meta[sym]["data_date"][name] = T
            meta[sym]["source_ts"][name] = ts

    frame = pd.DataFrame.from_dict(values, orient="index", columns=list(FEATURE_LIST)).astype("float64")
    frame.index.name = "symbol"
    return frame.sort_index(), meta


def compute_features(panel: pd.DataFrame, T: date, events: Optional[pd.DataFrame] = None,
                     actions: Optional[pd.DataFrame] = None, target_session: Optional[date] = None) -> pd.DataFrame:
    """Feature matrix for every symbol with a bar on T. `target_session` should come from the NSE
    calendar; without it the next weekday is assumed (correct only when no holiday intervenes)."""
    return _compute(panel, T, events, actions, target_session)[0]


def feature_vector(panel: pd.DataFrame, T: date, symbol: str, events: Optional[pd.DataFrame] = None,
                   actions: Optional[pd.DataFrame] = None, target_session: Optional[date] = None) -> dict:
    """The logged form of one symbol's features: {name: {"value", "data_date"[, "source_ts"]}}."""
    frame, meta = _compute(panel, T, events, actions, target_session)
    row = frame.loc[symbol]
    out = {}
    for name in FEATURE_LIST:
        cell = {"value": float(row[name]), "data_date": meta[symbol]["data_date"][name]}
        if name in EVENT_FEATURES:
            ts = meta[symbol]["source_ts"].get(name)
            cell["source_ts"] = None if ts is None else pd.Timestamp(ts).to_pydatetime()
        out[name] = cell
    return out
