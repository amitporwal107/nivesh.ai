"""v3 point-in-time fundamentals (PRD §17-18, 21-22, 25) and ownership (§23).

A quarterly filing or shareholding pattern is known on prediction day T only if its exchange broadcast timestamp
is at or before 15:30 IST on T. Rows without a timestamp are not usable: they contribute NaN, never a proxy date
(the same rule as the results-calendar gate). Growth needs the quarter a year earlier; acceleration is this
quarter's YoY growth minus the previous quarter's, so it needs six known quarters.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Mapping, Optional

import numpy as np
import pandas as pd

from .event_gate import cutoff_ist

FUNDAMENTAL_FEATURES = (
    "rev_yoy", "rev_qoq", "pat_yoy", "pat_qoq", "pat_accel", "ebitda_margin", "pat_margin", "roe_ttm",
    "de_ratio", "interest_cover", "current_ratio", "pe_ttm", "pb", "days_since_results", "fund_missing",
)
OWNERSHIP_FEATURES = (
    "promoter_pct", "pledge_pct", "fii_pct", "dii_pct", "mf_pct",
    "promoter_chg_qoq", "pledge_chg_qoq", "fii_chg_qoq", "dii_chg_qoq", "mf_chg_qoq", "own_missing",
)


def _known_by(frame: pd.DataFrame, T: date) -> pd.DataFrame:
    ts = pd.to_datetime(frame["broadcast_at"], utc=True)
    keep = ts.notna() & (ts <= pd.Timestamp(cutoff_ist(T)))
    return frame[keep.to_numpy()]


def _growth(series: np.ndarray, lag: int) -> float:
    if len(series) <= lag or not series[-1 - lag] > 0:
        return np.nan
    return float(series[-1] / series[-1 - lag] - 1)


def _ratio(num: float, den: float) -> float:
    return float(num / den) if den and np.isfinite(num) and np.isfinite(den) and den > 0 else np.nan


def _symbol_fundamentals(q: pd.DataFrame, T: date, close: Optional[float]) -> dict:
    q = q.sort_values(["period_end", "consolidated"], kind="mergesort").drop_duplicates("period_end", keep="last")
    rev, pat, eps = (q[c].to_numpy(np.float64) for c in ("revenue_from_ops_cr", "pat_cr", "eps_basic"))
    last = q.iloc[-1]
    f = {
        "rev_yoy": _growth(rev, 4), "rev_qoq": _growth(rev, 1), "pat_yoy": _growth(pat, 4), "pat_qoq": _growth(pat, 1),
        "pat_accel": np.nan, "ebitda_margin": _ratio(last["ebitda_cr"], last["revenue_from_ops_cr"]),
        "pat_margin": _ratio(last["pat_cr"], last["revenue_from_ops_cr"]),
        "roe_ttm": _ratio(pat[-4:].sum(), last["total_equity_cr"]) if len(pat) >= 4 else np.nan,
        "de_ratio": _ratio(float(np.nansum([last["long_term_debt_cr"], last["short_term_debt_cr"]])), last["total_equity_cr"]),
        "interest_cover": _ratio(last["pbt_cr"] + last["finance_costs_cr"], last["finance_costs_cr"]),
        "current_ratio": _ratio(last["current_assets_cr"], last["current_liabilities_cr"]),
        "pe_ttm": np.nan, "pb": np.nan,
        "days_since_results": float((pd.Timestamp(T) - pd.to_datetime(last["broadcast_at"], utc=True).tz_convert("Asia/Kolkata").normalize().tz_localize(None)).days),
        "fund_missing": 0.0,
    }
    if len(pat) >= 6:
        prev_yoy = _growth(pat[:-1], 4)
        f["pat_accel"] = f["pat_yoy"] - prev_yoy if np.isfinite(f["pat_yoy"]) and np.isfinite(prev_yoy) else np.nan
    if close is not None and np.isfinite(close):
        if len(eps) >= 4:
            f["pe_ttm"] = _ratio(close, float(np.nansum(eps[-4:])))
        shares_cr = _ratio(last["equity_share_capital_cr"], last["face_value"])  # crore shares
        bvps = _ratio(last["total_equity_cr"], shares_cr)
        f["pb"] = _ratio(close, bvps)
    return f


def pit_fundamentals(financials: pd.DataFrame, symbols: Iterable[str], T: date,
                     close: Optional[Mapping[str, float]] = None) -> pd.DataFrame:
    """One row per symbol: the fundamentals a reader could have computed at 15:30 IST on T."""
    symbols = list(symbols)
    q = financials[financials["period_type"].eq("quarterly")] if "period_type" in financials else financials
    q = _known_by(q, T)
    q = q[q["symbol"].isin(symbols)]
    empty = {c: np.nan for c in FUNDAMENTAL_FEATURES}
    empty["fund_missing"] = 1.0
    rows, ends = {}, {}
    for sym in symbols:
        g = q[q["symbol"] == sym]
        if g.empty:
            rows[sym], ends[sym] = dict(empty), pd.NaT
            continue
        rows[sym] = _symbol_fundamentals(g, T, None if close is None else close.get(sym))
        ends[sym] = pd.Timestamp(g["period_end"].max())
    out = pd.DataFrame.from_dict(rows, orient="index", columns=list(FUNDAMENTAL_FEATURES)).astype("float64")
    out["latest_period_end"] = pd.Series(ends)
    out.index.name = "symbol"
    return out.loc[symbols]


def pit_ownership(shp: pd.DataFrame, symbols: Iterable[str], T: date) -> pd.DataFrame:
    symbols = list(symbols)
    s = _known_by(shp, T)
    s = s[s["symbol"].isin(symbols)].sort_values(["symbol", "period_end"], kind="mergesort")
    cols = {"promoter_pct": "promoter_pct", "pledge_pct": "promoter_pledged_pct", "fii_pct": "fii_pct",
            "dii_pct": "dii_pct", "mf_pct": "mf_pct"}
    rows = {}
    for sym in symbols:
        g = s[s["symbol"] == sym]
        if g.empty:
            rows[sym] = {**{c: np.nan for c in OWNERSHIP_FEATURES}, "own_missing": 1.0}
            continue
        last = g.iloc[-1]
        prev = g.iloc[-2] if len(g) >= 2 else None
        r = {k: float(last[src]) if pd.notna(last[src]) else np.nan for k, src in cols.items()}
        for k, src in cols.items():
            r[k.replace("_pct", "_chg_qoq")] = (float(last[src] - prev[src]) if prev is not None and pd.notna(last[src]) and pd.notna(prev[src])
                                                 else np.nan)
        r["own_missing"] = 0.0
        rows[sym] = r
    out = pd.DataFrame.from_dict(rows, orient="index", columns=list(OWNERSHIP_FEATURES)).astype("float64")
    out.index.name = "symbol"
    return out.loc[symbols]
