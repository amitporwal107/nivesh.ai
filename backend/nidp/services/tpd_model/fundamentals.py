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
    "de_ratio", "interest_cover", "current_ratio", "pe_ttm", "pb", "cfo_pat", "days_since_results", "fund_missing",
)
OWNERSHIP_FEATURES = (
    "promoter_pct", "pledge_pct", "fii_pct", "dii_pct", "mf_pct",
    "promoter_chg_qoq", "pledge_chg_qoq", "fii_chg_qoq", "dii_chg_qoq", "mf_chg_qoq", "own_missing",
)
BALANCE_SHEET_COLUMNS = ("total_equity_cr", "long_term_debt_cr", "short_term_debt_cr", "current_assets_cr",
                         "current_liabilities_cr", "equity_share_capital_cr")
BALANCE_SHEET_MAX_AGE_DAYS = 550      # an annual balance sheet is ~14 months old just before the next one lands
CASH_FLOW_MAX_AGE_DAYS = 550
MF_COMPLETE_MONTH_MIN_SCHEMES = 2000  # a monthly MF-portfolio month with fewer scheme codes is a partial ingest, not the market
MF_PCT_MAX = 60.0                     # above this the share count is stale (bonus/split not yet in the capital), not real
SHARE_COUNT_DISAGREEMENT = 0.30       # capital/face-value vs PAT/EPS share counts differing by more -> a split; the period's own wins
EPS_MIN_FOR_SHARE_COUNT = 0.5         # below this EPS rounding (2 dp) makes PAT/EPS too noisy to count shares


def _known_by(frame: pd.DataFrame, T: date, column: str = "broadcast_at") -> pd.DataFrame:
    ts = pd.to_datetime(frame[column], utc=True)
    keep = ts.notna() & (ts <= pd.Timestamp(cutoff_ist(T)))
    return frame[keep.to_numpy()]


def _growth(series: np.ndarray, lag: int) -> float:
    if len(series) <= lag or not series[-1 - lag] > 0:
        return np.nan
    return float(series[-1] / series[-1 - lag] - 1)


def _ratio(num: float, den: float) -> float:
    return float(num / den) if den and np.isfinite(num) and np.isfinite(den) and den > 0 else np.nan


def _latest_balance_sheet(rows: pd.DataFrame, T: date) -> pd.Series:
    """Each balance-sheet column's most recent known value (annual rows carry them, quarterly rows mostly do not),
    ignoring anything older than BALANCE_SHEET_MAX_AGE_DAYS."""
    fresh = rows[rows["period_end"] >= pd.Timestamp(T) - pd.Timedelta(days=BALANCE_SHEET_MAX_AGE_DAYS)]
    fresh = fresh.sort_values(["period_end", "consolidated"], kind="mergesort")
    return fresh[list(BALANCE_SHEET_COLUMNS)].astype("float64").ffill().iloc[-1] if len(fresh) else pd.Series(np.nan, index=list(BALANCE_SHEET_COLUMNS))


def _share_count_cr(bs: pd.Series, last_q: pd.Series, face_value: Optional[float]) -> float:
    """Crore shares: capital / reference face value, unless the period's own PAT/EPS count disagrees by more than
    SHARE_COUNT_DISAGREEMENT (a split or bonus since the period), in which case the period's count wins."""
    ref = _ratio(bs["equity_share_capital_cr"], face_value) if face_value is not None else np.nan
    own = np.nan
    pat, eps = float(last_q["pat_cr"]), float(last_q["eps_basic"])
    if np.isfinite(pat) and np.isfinite(eps) and abs(eps) >= EPS_MIN_FOR_SHARE_COUNT and pat != 0 and pat / eps > 0:
        own = pat / eps
    if np.isfinite(ref) and (not np.isfinite(own) or abs(own / ref - 1) <= SHARE_COUNT_DISAGREEMENT):
        return ref
    return own


def _symbol_fundamentals(q: pd.DataFrame, allrows: pd.DataFrame, T: date, close: Optional[float],
                         face_value: Optional[float], cf: Optional[pd.DataFrame]) -> dict:
    q = q.sort_values(["period_end", "consolidated"], kind="mergesort").drop_duplicates("period_end", keep="last")
    rev, pat, eps = (q[c].to_numpy(np.float64) for c in ("revenue_from_ops_cr", "pat_cr", "eps_basic"))
    last = q.iloc[-1]
    bs = _latest_balance_sheet(allrows, T)
    debt = float(np.nansum([bs["long_term_debt_cr"], bs["short_term_debt_cr"]])) if bs[["long_term_debt_cr", "short_term_debt_cr"]].notna().any() else np.nan
    f = {
        "rev_yoy": _growth(rev, 4), "rev_qoq": _growth(rev, 1), "pat_yoy": _growth(pat, 4), "pat_qoq": _growth(pat, 1),
        "pat_accel": np.nan, "ebitda_margin": _ratio(last["ebitda_cr"], last["revenue_from_ops_cr"]),
        "pat_margin": _ratio(last["pat_cr"], last["revenue_from_ops_cr"]),
        "roe_ttm": _ratio(pat[-4:].sum(), bs["total_equity_cr"]) if len(pat) >= 4 else np.nan,
        "de_ratio": _ratio(debt, bs["total_equity_cr"]),
        "interest_cover": _ratio(last["pbt_cr"] + last["finance_costs_cr"], last["finance_costs_cr"]),
        "current_ratio": _ratio(bs["current_assets_cr"], bs["current_liabilities_cr"]),
        "pe_ttm": np.nan, "pb": np.nan, "cfo_pat": np.nan,
        "days_since_results": float((pd.Timestamp(T) - pd.to_datetime(last["broadcast_at"], utc=True).tz_convert("Asia/Kolkata").normalize().tz_localize(None)).days),
        "fund_missing": 0.0,
    }
    if len(pat) >= 6:
        prev_yoy = _growth(pat[:-1], 4)
        f["pat_accel"] = f["pat_yoy"] - prev_yoy if np.isfinite(f["pat_yoy"]) and np.isfinite(prev_yoy) else np.nan
    shares_cr = _share_count_cr(bs, last, face_value)
    f["shares_cr"] = shares_cr
    if close is not None and np.isfinite(close):
        if len(eps) >= 4:
            f["pe_ttm"] = _ratio(close, float(np.nansum(eps[-4:])))
        f["pb"] = _ratio(close, _ratio(bs["total_equity_cr"], shares_cr))
    if cf is not None and len(cf):
        c = cf[cf["period_end"] >= pd.Timestamp(T) - pd.Timedelta(days=CASH_FLOW_MAX_AGE_DAYS)]
        c = c.sort_values(["period_end", "consolidated"], kind="mergesort")
        if len(c):
            fy_end = c.iloc[-1]["period_end"]
            fy = q[(q["period_end"] <= fy_end) & (q["period_end"] > fy_end - pd.DateOffset(years=1))]
            if len(fy) == 4:
                f["cfo_pat"] = _ratio(float(c.iloc[-1]["cfo_cr"]), float(fy["pat_cr"].sum()))
    return f


def pit_fundamentals(financials: pd.DataFrame, symbols: Iterable[str], T: date,
                     close: Optional[Mapping[str, float]] = None, reference: Optional[pd.DataFrame] = None,
                     cashflow: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """One row per symbol: the fundamentals a reader could have computed at 15:30 IST on T.

    P&L series come from quarterly rows; balance-sheet fields from the latest known row of any period type
    (annual rows carry them); `reference` (symbol, face_value) gives the share count; `cashflow` rows need a
    broadcast_at (the results filing that carried them). Extra columns: latest_period_end, shares_cr."""
    symbols = list(symbols)
    known = _known_by(financials, T)
    known = known[known["symbol"].isin(symbols)]
    q = known[known["period_type"].eq("quarterly")] if "period_type" in known else known
    fv = {} if reference is None else reference.dropna(subset=["face_value"]).set_index("symbol")["face_value"].astype(float).to_dict()
    cf_known = None
    if cashflow is not None:
        cf_known = _known_by(cashflow, T)
        cf_known = cf_known[cf_known["symbol"].isin(symbols) & cf_known["cfo_cr"].notna()]
    empty = {c: np.nan for c in FUNDAMENTAL_FEATURES}
    empty["fund_missing"] = 1.0
    rows, ends = {}, {}
    for sym in symbols:
        g = q[q["symbol"] == sym]
        if g.empty:
            rows[sym], ends[sym] = {**empty, "shares_cr": np.nan}, pd.NaT
            continue
        rows[sym] = _symbol_fundamentals(g, known[known["symbol"] == sym], T, None if close is None else close.get(sym),
                                         fv.get(sym), None if cf_known is None else cf_known[cf_known["symbol"] == sym])
        ends[sym] = pd.Timestamp(g["period_end"].max())
    out = pd.DataFrame.from_dict(rows, orient="index", columns=[*FUNDAMENTAL_FEATURES, "shares_cr"]).astype("float64")
    out["latest_period_end"] = pd.Series(ends)
    out.index.name = "symbol"
    return out.loc[symbols]


def _mf_holding(mf: pd.DataFrame, T: date, shares_cr: Optional[float]) -> tuple[float, float]:
    """(mf_pct, mf_chg_qoq) from the latest COMPLETE monthly portfolio month landed by the cutoff on T; the change is
    against the latest complete month at least three months earlier. NaN without a credible share count."""
    if mf.empty or shares_cr is None or not np.isfinite(shares_cr) or shares_cr <= 0:
        return np.nan, np.nan
    m = mf[mf["month_schemes"] >= MF_COMPLETE_MONTH_MIN_SCHEMES].sort_values("as_of_month", kind="mergesort")
    if m.empty:
        return np.nan, np.nan
    cur = m.iloc[-1]
    pct = float(cur["mf_shares"]) / (shares_cr * 1e7) * 100.0
    if pct > MF_PCT_MAX:
        return np.nan, np.nan
    prior = m[m["as_of_month"] <= cur["as_of_month"] - pd.DateOffset(months=3)]
    chg = pct - float(prior.iloc[-1]["mf_shares"]) / (shares_cr * 1e7) * 100.0 if len(prior) else np.nan
    return pct, chg


def pit_ownership(shp: pd.DataFrame, symbols: Iterable[str], T: date, mf_monthly: Optional[pd.DataFrame] = None,
                  shares_cr: Optional[Mapping[str, float]] = None) -> pd.DataFrame:
    """Shareholding-pattern block by broadcast_at; MF holding from the monthly portfolio disclosures (`mf_monthly`:
    symbol, as_of_month, mf_shares (plan variants of one scheme counted once), month_schemes (distinct scheme codes in
    that month's file, the completeness measure), ingested_at) when given, else the pattern's own (empty) column."""
    symbols = list(symbols)
    s = _known_by(shp, T)
    s = s[s["symbol"].isin(symbols)].sort_values(["symbol", "period_end"], kind="mergesort")
    mf = None
    if mf_monthly is not None:
        mf = _known_by(mf_monthly, T, column="ingested_at")
        mf = mf[mf["symbol"].isin(symbols)]
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
        if mf is not None:
            r["mf_pct"], r["mf_chg_qoq"] = _mf_holding(mf[mf["symbol"] == sym], T, None if shares_cr is None else shares_cr.get(sym))
        r["own_missing"] = 0.0
        rows[sym] = r
    out = pd.DataFrame.from_dict(rows, orient="index", columns=list(OWNERSHIP_FEATURES)).astype("float64")
    out.index.name = "symbol"
    return out.loc[symbols]
