"""Selection and one session's simulation (rules_v1.json: eligibility, ranking, entry, allocation, sessions).

`PredictionSet` is one frozen EOD prediction (forward: a v4 snapshot; replay: one as_of_date of the early-window
walk-forward). `rank_universe` applies the eligibility filters with data dated on or before the prediction date only and
ranks the survivors; `simulate` adds the entry, levels, six-session path and every exit mode for each eligible row.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from . import sim
from .market import ATR_MIN_BARS, LIQ_MIN_BARS, Market

RULES_PATH = Path(__file__).with_name("rules_v1.json")
FILTERS = ("scored", "valid_ohlc", "fresh", "min_price", "min_traded_value", "ca_validated", "atr_available")
MIN_PRICE = 5.0
MIN_TURNOVER = 1.0e7
SIZE_GROUPS = ((100, "L"), (250, "M"))


def load_rules() -> dict:
    return json.loads(RULES_PATH.read_text())


@dataclass
class PredictionSet:
    sample: str
    prediction_date: date
    next_session: date
    prediction_timestamp: datetime
    data_cutoff: datetime
    model_version: str
    feature_version: str
    snapshot_sha256: str
    wide: pd.DataFrame                 # index symbol, columns = heads, values = probability
    counts: bool
    meta: dict = field(default_factory=dict)


def size_group(rank: int) -> str:
    for lim, g in SIZE_GROUPS:
        if rank <= lim:
            return g
    return "S"


def rank_universe(ps: PredictionSet, m: Market, portfolio: str, rules: dict, names: pd.DataFrame) -> pd.DataFrame:
    """The complete ranked universe for one portfolio (rules eligibility + ranking). Only bars dated <= prediction date."""
    cfg = rules["portfolios"][portfolio]
    w = ps.wide.dropna(subset=[cfg["head"]]).copy()
    w = w.reset_index().rename(columns={"index": "symbol"})
    w["p_head"] = w[cfg["head"]]
    w["p_opposite"] = w.get(cfg["opposite"])
    w["p_other"] = w.get(cfg["other_threshold"])
    w = w.sort_values(["p_head", "symbol"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
    w["model_rank"] = np.arange(1, len(w) + 1)
    t = m.t(ps.prediction_date)
    reasons, elig = [], []
    for sym in w["symbol"]:
        i = m.i(sym)
        e: dict = {}
        why = None
        if t is None or i is None or not m.has_bar(t, i):
            why = "valid_ohlc"
        else:
            o, h, l, c = m.open[t, i], m.high[t, i], m.low[t, i], m.close[t, i]
            e = {"close": round(float(c), 4), "med_turnover_20": None if np.isnan(m.med_turnover[t, i]) else float(m.med_turnover[t, i]),
                 "bars_20": int(m.liq_bars[t, i])}
            if not (o > 0 and h > 0 and l > 0 and c > 0 and l <= min(o, c) + 1e-9 and h >= max(o, c) - 1e-9):
                why = "valid_ohlc"
            elif t + 1 <= len(m.dates) and m.prev_bar(t + 1, i) != t:
                why = "fresh"
            elif c < MIN_PRICE:
                why = "min_price"
            elif np.isnan(m.med_turnover[t, i]) or m.liq_bars[t, i] < LIQ_MIN_BARS or m.med_turnover[t, i] < MIN_TURNOVER:
                why = "min_traded_value"
            elif m.suspect_window[t, i]:
                why = "ca_validated"
            elif np.isnan(m.atr_adj[t, i]):
                why = "atr_available"
        reasons.append(why)
        elig.append(e)
    w["exclusion_reason"] = reasons
    w["eligibility"] = elig
    ok = w["exclusion_reason"].isna()
    w["rank"] = pd.array([None] * len(w), dtype="Int64")
    w.loc[ok, "rank"] = np.arange(1, int(ok.sum()) + 1)
    n = rules["positions_per_portfolio"]
    w["selection_status"] = np.where(~ok, "EXCLUDED", np.where(w["rank"].fillna(10 ** 9).astype(int) <= n, "SELECTED", "NOT_SELECTED"))
    # size group: turnover rank within the eligible ranked universe (benchmark B)
    to = pd.Series([e.get("med_turnover_20") for e in elig], index=w.index, dtype="float64")
    sg = pd.Series([None] * len(w), index=w.index, dtype=object)
    order = w[ok].assign(_to=to[ok]).sort_values(["_to", "symbol"], ascending=[False, True], kind="mergesort").index
    for r, ix in enumerate(order, start=1):
        sg[ix] = size_group(r)
    w["size_group"] = sg
    nm = names.set_index("symbol")
    w["isin"] = w["symbol"].map(nm["isin"]) if "isin" in nm else None
    w["company_name"] = w["symbol"].map(nm["company_name"]) if "company_name" in nm else None
    w["sector"] = w["symbol"].map(nm["sector"]) if "sector" in nm else None
    w["portfolio_type"] = portfolio
    w["target_pct"] = cfg["target_pct"]
    return w


def session_inputs(m: Market, symbols: list[str], ps: PredictionSet) -> tuple[sim.SessionInputs, list[pd.Timestamp]]:
    s1 = m.t(ps.next_session)
    t0 = m.t(ps.prediction_date)
    cols = [m.i(s) for s in symbols]
    n = len(symbols)
    if s1 is None:
        sess = []
    else:
        sess = list(m.dates[s1:s1 + sim.WINDOW])
    k = len(sess)

    def grab(arr, fill=np.nan):
        out = np.full((n, sim.WINDOW), fill, dtype=arr.dtype if arr.dtype == bool else "float64")
        if k:
            for j, c in enumerate(cols):
                if c is not None:
                    out[j, :k] = arr[s1:s1 + k, c]
        return out

    mult = grab(m.mult, 1.0)
    mult[np.isnan(mult)] = 1.0
    prev_c = np.array([m.close[t0, c] if c is not None and t0 is not None else np.nan for c in cols])
    prev_m = np.array([m.mult[t0, c] if c is not None and t0 is not None else 1.0 for c in cols])
    to1 = np.array([m.turnover[s1, c] if c is not None and s1 is not None else np.nan for c in cols])
    x = sim.SessionInputs(open=grab(m.open), high=grab(m.high), low=grab(m.low), close=grab(m.close), volume=grab(m.volume), mult=mult,
                          turnover_s1=to1, prev_close_raw=prev_c, prev_mult=prev_m, sessions_present=k,
                          s1_thin=bool(k and sess[0] in m.thin), suspect=grab(m.suspect, False), unfactored=grab(m.unfactored_event, False))
    return x, sess


def simulate(ps: PredictionSet, m: Market, universe: pd.DataFrame, rules: dict) -> tuple[pd.DataFrame, dict]:
    """Entry, levels, path and exits for every eligible row of `universe` (one portfolio). Returns the eligible rows with
    outcome columns and a dict of (n, 6) path arrays keyed like sim.path_returns + running."""
    cfg = rules["portfolios"][universe["portfolio_type"].iloc[0]]
    alloc = rules["allocation"]["capital_inr"] / rules["positions_per_portfolio"]
    u = universe[universe["selection_status"] != "EXCLUDED"].reset_index(drop=True)
    x, sess = session_inputs(m, list(u["symbol"]), ps)
    ent = sim.resolve_entries(x, alloc)
    t0 = m.t(ps.prediction_date)
    cols = [m.i(s) for s in u["symbol"]]
    mult0 = np.array([m.mult[t0, c] for c in cols])
    atr = np.array([m.atr_adj[t0, c] for c in cols]) / mult0
    sup = np.array([m.support_adj[t0, c] for c in cols]) / mult0
    res = np.array([m.resist_adj[t0, c] for c in cols]) / mult0
    entry = ent["entry_price"].to_numpy(dtype="float64")
    lv = sim.levels(entry, atr, sup, res, cfg["atr_multiplier"], cfg["target_pct"])
    r = sim.path_returns(x, entry)
    run = sim.running(r)
    target_ret = lv["target_price"].to_numpy() / entry - 1.0
    stop_ret = lv["stop_loss_price"].to_numpy() / entry - 1.0
    ex = sim.exits(r, target_ret, stop_ret, len(sess))
    out = pd.concat([u, ent, lv], axis=1)
    out["sessions_observed"] = len(sess)
    out["session_dates"] = [[d.date() for d in sess]] * len(out)
    # the model's own label: s1 high vs the (adjusted) previous close, as v4's y
    prev_adj = ent["prev_close_adj"].to_numpy()
    s1_high = x.high[:, 0]
    with np.errstate(invalid="ignore"):
        lab = s1_high >= prev_adj * (1 + cfg["target_pct"] / 100.0) - 1e-9
    out["model_label_hit"] = np.where(np.isnan(s1_high) | np.isnan(prev_adj), None, lab).astype(object)
    # corporate-action review: an unexplained jump or a factor-less price event inside the observed window
    inside = (x.suspect[:, :len(sess)].any(axis=1) | x.unfactored[:, :len(sess)].any(axis=1)) if sess else np.zeros(len(out), bool)
    st = out["status"].to_numpy(dtype=object)
    reason = out["reason"].to_numpy(dtype=object)
    for j in np.flatnonzero(inside & (st == "ENTERED")):
        st[j], reason[j] = "CORPORATE_ACTION_REVIEW", "unexplained or unfactored corporate action inside the window"
    out["status"], out["reason"] = st, reason
    for mode, df in ex.items():
        for c in df.columns:
            out[f"{mode}|{c}"] = df[c].to_numpy()
    arrays = {**r, **run, "open": x.open, "high": x.high, "low": x.low, "close": x.close, "volume": x.volume}
    return out, arrays


def lifecycle(row: pd.Series, sessions_observed: int) -> str:
    """Trade state from the entry status and how much of the window has closed (PRD 9)."""
    if row["status"] != "ENTERED":
        return row["status"]
    if sessions_observed >= sim.WINDOW:
        return "EVALUATED"
    if sessions_observed == 1:
        return "ENTERED"
    return "MONITORING"
