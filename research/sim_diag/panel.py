"""Bar store for the simulators: per-symbol bars (the dataset build's prepared bars), the calendar, and the trade
windows (decision-day facts + the calendar sessions after D) that tradesim.simulate consumes."""
from __future__ import annotations

import numpy as np
import pandas as pd

import tradesim as TS

STRUCTURE_LOOKBACK, SIGMA_LOOKBACK = 10, 20


def enrich(bars: pd.DataFrame) -> pd.DataFrame:
    """Adds sigma20 (std of daily close returns over 20 bars to D, ddof 1), low10 (lowest low of 10 bars to D) and
    vol_med20 (median volume of the 20 bars before D, for the volume checks)."""
    d = bars.copy()
    g = d.groupby("symbol", sort=False)
    d["ret1"] = d.close / d.prev_close - 1
    d["sigma20"] = g.ret1.transform(lambda s: s.rolling(SIGMA_LOOKBACK).std())
    d["low10"] = g.low.transform(lambda s: s.rolling(STRUCTURE_LOOKBACK).min())
    d["vol_med20"] = g.volume.transform(lambda s: s.shift(1).rolling(20).median())
    return d


class BarStore:
    def __init__(self, bars: pd.DataFrame, cal: pd.DatetimeIndex):
        self.cal = cal
        self.pos = {d: i for i, d in enumerate(cal)}
        self.by_symbol = {s: g.set_index("date") for s, g in bars.groupby("symbol", sort=False)}

    def bar(self, symbol: str, date: pd.Timestamp):
        g = self.by_symbol.get(symbol)
        if g is None or date not in g.index:
            return None
        r = g.loc[date]
        pc = r.prev_close
        return TS.EX.Bar(TS.dec(r.open), TS.dec(r.high), TS.dec(r.low), TS.dec(r.close), int(r.volume),
                         None if pd.isna(pc) else TS.dec(pc))

    def row(self, symbol: str, date: pd.Timestamp):
        g = self.by_symbol.get(symbol)
        return None if g is None or date not in g.index else g.loc[date]

    def sessions_after(self, date: pd.Timestamp, n: int) -> list:
        i = self.pos[pd.Timestamp(date)]
        return list(self.cal[i + 1:i + 1 + n])

    def window(self, symbol: str, date: pd.Timestamp, atr_pct: float, n_after: int = 10) -> TS.Window:
        d = self.row(symbol, date)
        if d is None:
            raise KeyError(f"{symbol} has no bar on the decision day {date.date()}")
        dates = self.sessions_after(date, n_after)
        g = self.by_symbol[symbol]
        return TS.Window(
            symbol=symbol, decision_date=pd.Timestamp(date).date(), d_close=TS.dec(d.close), d_high=TS.dec(d.high),
            d_low=TS.dec(d.low), value20_d=float(d.value20), atr_pct=float(atr_pct),
            sigma20=None if pd.isna(d.sigma20) else float(d.sigma20),
            low10=None if pd.isna(d.low10) else TS.dec(d.low10),
            dates=[x.date() for x in dates], bars=[self.bar(symbol, x) for x in dates],
            value20_by_date={x.date(): float(g.loc[x, "value20"]) for x in dates if x in g.index})

    def forward(self, symbol: str, date: pd.Timestamp, k: int = 5) -> dict:
        """Mode A forward path from the s1 open: returns after 1..k sessions, best and worst move (no execution rules)."""
        dates = self.sessions_after(date, k)
        rows = [self.row(symbol, x) for x in dates]
        if not rows or rows[0] is None:
            return {}
        o = float(rows[0].open)
        have = [r for r in rows if r is not None]
        out = {f"r{j + 1}": (float(r.close) / o - 1 if r is not None else np.nan) for j, r in enumerate(rows)}
        out["r_last"] = float(have[-1].close) / o - 1
        out["mfe"] = max(float(r.high) for r in have) / o - 1
        out["mae"] = min(float(r.low) for r in have) / o - 1
        return out
