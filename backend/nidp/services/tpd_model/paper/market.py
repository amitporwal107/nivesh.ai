"""Price access for the paper engine (rules_v1.json).

The NSE EQ panel (the same export v4 is scored on) as dense session x symbol arrays, the corporate-action multiplier of
every bar, and the per-(session, symbol) EOD statistics the rules name: ATR14, 10-session support, 20-session resistance,
20-session median turnover and the suspected-corporate-action window.

Adjustment. `mult[t, i]` is the product of the SPLIT/BONUS factors whose ex-date is after session t (the research
convention: a 1:1 bonus is 0.5 for earlier bars). Statistics are computed on fully adjusted bars and converted back to
the rupees of the prediction date by dividing by `mult` on that date. A factor ex-dated after the prediction date scales
every bar of a window ending on it by the same amount, so the rupee values equal an as-of-date adjustment exactly —
no information after the prediction date enters a level (TC-P13).

Calendar. Sessions are the panel's dates minus short sessions: a date whose total turnover is below 40% of the median
of the 20 sessions before it is a muhurat-style evening session and is never counted (1 Nov 2024 and 21 Oct 2025 sit at
18-19%; both Budget weekend sessions are full size and count). A session whose bar count is below 80% of the prior
median (tpd_model.panel_source.thin_sessions) is an incomplete ingest: a missing bar there is a data error, not a
suspension.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ..backtest import PRICE_EVENT_TYPES, corporate_actions_from_archive, suspected_actions
from ..panel_source import select_nse_eq, thin_sessions

SHORT_SESSION_FRAC = 0.40
ATR_N = 14
ATR_MIN_BARS = 15
SUPPORT_N = 10
RESIST_N = 20
LIQ_N = 20
LIQ_MIN_BARS = 15
CA_WINDOW = 20


def short_sessions(panel: pd.DataFrame, lookback: int = 20, frac: float = SHORT_SESSION_FRAC) -> set[pd.Timestamp]:
    tot = panel.groupby("as_of_date")["turnover"].sum().sort_index()
    out = set()
    for i, (d, v) in enumerate(tot.items()):
        prior = tot.iloc[max(0, i - lookback):i]
        if len(prior) >= 5 and v < frac * float(np.median(prior)):
            out.add(pd.Timestamp(d))
    return out


def wilder_atr(tr: np.ndarray, n: int = ATR_N, min_bars: int = ATR_MIN_BARS) -> np.ndarray:
    """Wilder's ATR over one symbol's bar sequence (NaN-free input). The first value is the mean of the first `n` true
    ranges, then ATR_t = (ATR_{t-1} * (n-1) + TR_t) / n. Values before `min_bars` bars are NaN."""
    out = np.full(len(tr), np.nan)
    if len(tr) < n:
        return out
    atr = float(np.mean(tr[:n]))
    out[n - 1] = atr
    for k in range(n, len(tr)):
        atr = (atr * (n - 1) + tr[k]) / n
        out[k] = atr
    out[: min_bars - 1] = np.nan
    return out


@dataclass
class Market:
    dates: pd.DatetimeIndex
    symbols: pd.Index
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    turnover: np.ndarray
    source: np.ndarray                 # object array: the bar's source label ('' when no bar)
    mult: np.ndarray
    atr_adj: np.ndarray                # ATR14 on adjusted bars
    support_adj: np.ndarray
    resist_adj: np.ndarray
    med_turnover: np.ndarray
    liq_bars: np.ndarray
    suspect: np.ndarray                # bool: unexplained open/prev-close jump on that bar
    suspect_window: np.ndarray         # bool: any suspect bar in the CA_WINDOW sessions ending here
    unfactored_event: np.ndarray       # bool: a known price event without a price factor ex-dated that session
    thin: set = field(default_factory=set)
    short: set = field(default_factory=set)

    # ── lookups ─────────────────────────────────────────────────────────────────────────────────────
    def t(self, d) -> Optional[int]:
        ts = pd.Timestamp(d)
        k = self.dates.searchsorted(ts)
        return int(k) if k < len(self.dates) and self.dates[k] == ts else None

    def i(self, symbol: str) -> Optional[int]:
        k = self.symbols.get_indexer([symbol])[0]
        return None if k < 0 else int(k)

    def sessions_from(self, d, n: int) -> list[pd.Timestamp]:
        k = self.dates.searchsorted(pd.Timestamp(d))
        return list(self.dates[k:k + n])

    def has_bar(self, t: int, i: int) -> bool:
        return not np.isnan(self.close[t, i])

    def prev_bar(self, t: int, i: int) -> Optional[int]:
        """The symbol's last bar strictly before session t."""
        col = self.close[:t, i]
        idx = np.flatnonzero(~np.isnan(col))
        return int(idx[-1]) if len(idx) else None


def load_panel(exports: Path) -> pd.DataFrame:
    raw = pd.read_csv(exports / "panel.csv.gz", parse_dates=["as_of_date"])
    etfs = set(pd.read_csv(exports / "etfs.csv")["symbol"])
    return select_nse_eq(raw, etfs)


def build_market(panel: pd.DataFrame, ca: pd.DataFrame) -> Market:
    """`panel`: select_nse_eq output. `ca`: the raw NSE corporate-action archive (inputs/tpd_ca_history.csv)."""
    factors, known = corporate_actions_from_archive(ca)
    short = short_sessions(panel)
    thin = {pd.Timestamp(d) for d in thin_sessions(panel)}
    p = panel[~panel["as_of_date"].isin(short)].copy()
    dates = pd.DatetimeIndex(sorted(p["as_of_date"].unique()))
    symbols = pd.Index(sorted(p["symbol"].unique()))

    def wide(col, fill=np.nan):
        w = p.pivot(index="as_of_date", columns="symbol", values=col).reindex(index=dates, columns=symbols)
        return w.to_numpy(dtype="float64") if fill is np.nan else w

    o, h, l, c = wide("open"), wide("high"), wide("low"), wide("close")
    vol, to = wide("volume"), wide("turnover")
    src = p.pivot(index="as_of_date", columns="symbol", values="source").reindex(index=dates, columns=symbols).fillna("").to_numpy(dtype=object)

    # corporate-action multipliers per bar
    mult = np.ones_like(c)
    col_of = {s: k for k, s in enumerate(symbols)}
    for sym, g in factors.groupby("symbol"):
        k = col_of.get(sym)
        if k is None:
            continue
        for ex, f in zip(pd.to_datetime(g["ex_date"]), g["factor"]):
            mult[dates < ex, k] *= float(f)

    # suspected (unexplained) corporate actions and known events without a factor
    susp = np.zeros_like(c, dtype=bool)
    s = suspected_actions(p, known)
    if s.empty:                                    # backtest.suspected_actions returns a frame without columns when there are none
        s = pd.DataFrame(columns=["symbol", "ex_date"])
    for sym, ex in zip(s["symbol"], pd.to_datetime(s["ex_date"])):
        k, t = col_of.get(sym), dates.searchsorted(ex)
        if k is not None and t < len(dates) and dates[t] == ex:
            susp[t, k] = True
    unf = np.zeros_like(c, dtype=bool)
    fkeys = set(zip(factors["symbol"], pd.to_datetime(factors["ex_date"])))
    ev = ca[ca["action_type"].isin(PRICE_EVENT_TYPES)][["symbol", "ex_date"]].dropna()
    for sym, ex in zip(ev["symbol"], pd.to_datetime(ev["ex_date"])):
        if (sym, ex) in fkeys:
            continue
        k = col_of.get(sym)
        t = dates.searchsorted(ex)
        if k is not None and t < len(dates):          # an ex-date on a non-session applies to the next session
            unf[t, k] = True

    # per-symbol statistics on adjusted bars (each symbol's own bar sequence; gaps are skipped, not filled)
    ah, al, ac = h * mult, l * mult, c * mult
    atr = np.full_like(c, np.nan)
    sup = np.full_like(c, np.nan)
    res = np.full_like(c, np.nan)
    for k in range(len(symbols)):
        rows = np.flatnonzero(~np.isnan(c[:, k]))
        if len(rows) == 0:
            continue
        hh, ll, cc = ah[rows, k], al[rows, k], ac[rows, k]
        prev = np.concatenate([[np.nan], cc[:-1]])
        tr = np.where(np.isnan(prev), hh - ll, np.maximum(hh, prev) - np.minimum(ll, prev))
        atr[rows, k] = wilder_atr(tr)
        sup[rows, k] = pd.Series(ll).rolling(SUPPORT_N, min_periods=SUPPORT_N).min().to_numpy()
        res[rows, k] = pd.Series(hh).rolling(RESIST_N, min_periods=RESIST_N).max().to_numpy()
    tow = pd.DataFrame(to)
    med = tow.rolling(LIQ_N, min_periods=LIQ_MIN_BARS).median().to_numpy()
    nb = tow.notna().astype(float).rolling(LIQ_N, min_periods=1).sum().to_numpy()
    sw = pd.DataFrame(susp.astype(float)).rolling(CA_WINDOW, min_periods=1).max().to_numpy() > 0
    return Market(dates=dates, symbols=symbols, open=o, high=h, low=l, close=c, volume=vol, turnover=to, source=src, mult=mult,
                  atr_adj=atr, support_adj=sup, resist_adj=res, med_turnover=med, liq_bars=nb, suspect=susp, suspect_window=sw,
                  unfactored_event=unf, thin=thin, short=short)
