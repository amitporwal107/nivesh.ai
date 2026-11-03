"""Split/bonus adjustment of the scanner's raw bhavcopy bars (`stock_ohlcv`).

`stock_ohlcv` holds raw NSE prices, so a split or bonus is a price break: KOTAKBANK closes 2133.30 on 2026-01-13 and
421.00 on 2026-01-14 (5:1 split). Every SMA, ATR, return, swing level and volume baseline whose window straddles it is
wrong until the break leaves the window (study C, N2: 91 symbols had a >= 20% adjustment step in the scanner's window).

Two steps, smallest sound combination (trade-off in the PR notes):

1. **Warehouse factors.** `nidp.prices_eod_adjusted.cumulative_adj_factor` (through DaaS `/prices/adjusted/bulk`, the
   path copilot_tools/backtest.py already uses) is the product of every split/bonus factor ex-dated after the bar. Each
   bar is put on the scale of the latest bar the warehouse has a factor for: price x f(bar) / f(anchor), volume / that
   ratio. Bars after the anchor (the evening run's own session: `price_adjuster` runs at 22:30 IST, after the 19:45
   scan) keep the anchor's scale. A bar the warehouse has no row for takes the factor of the next warehouse session.
2. **Residual break guard.** A one-session close move of 40% or more that is still there after step 1 is an action
   the warehouse has not applied (an ex-date on the run's own session, a corporate action missing from
   `nidp.corporate_actions`, a symbol the warehouse does not adjust). The bars before it are on another price scale,
   so they are dropped, exactly as routes/research_chart.py `_adjustment_break` does. A symbol left with too few bars
   is not scored that day.
"""
from __future__ import annotations

import bisect
import logging
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

BREAK_MOVE = 0.4             # routes/research_chart.py BREAK_MOVE: NSE circuits stop at 20%, so 40% is not a market move
FACTOR_LOOKBACK_DAYS = 400   # covers the 260-bar window the pipeline loads
BULK_CHUNK = 300             # DaaS /prices/adjusted/bulk: max symbols per call

BASIS_ADJUSTED = "warehouse_adjusted"
BASIS_RAW = "raw_no_factors"


class FactorsUnavailable(RuntimeError):
    """The warehouse adjustment factors could not be read: features would straddle unadjusted breaks."""


async def load_factors(symbols: Iterable[str], start: date, end: date) -> Dict[str, Dict[date, float]]:
    """{symbol: {date: cumulative_adj_factor}} from the warehouse for [start, end]. A symbol the warehouse has no
    adjusted rows for is absent. Raises FactorsUnavailable when any chunk cannot be read."""
    from services.copilot_tools import daas_client

    syms = sorted({s.upper() for s in symbols if s})
    out: Dict[str, Dict[date, float]] = {}
    for i in range(0, len(syms), BULK_CHUNK):
        chunk = syms[i:i + BULK_CHUNK]
        try:
            data = await daas_client.get_adjusted_prices_bulk(chunk, start.isoformat(), end.isoformat(), timeout=60.0)
        except daas_client.DaasError as e:
            raise FactorsUnavailable(f"adjusted prices for {len(chunk)} symbols: {e}") from e
        for sym, rows in (data or {}).items():
            per: Dict[date, float] = {}
            for r in rows or []:
                try:
                    d = date.fromisoformat(str(r.get("as_of_date"))[:10])
                    f = float(r.get("cumulative_adj_factor"))
                except (TypeError, ValueError):
                    continue
                if f > 0:
                    per[d] = f
            if per:
                out[str(sym).upper()] = per
    return out


def _scale(bar: dict, ratio: float) -> dict:
    out = dict(bar)
    for k in ("open", "high", "low", "close"):
        if out.get(k) is not None:
            out[k] = float(out[k]) * ratio
    if out.get("volume") is not None:
        out["volume"] = int(round(float(out["volume"]) / ratio))
    return out


def adjustment_break(bars: List[dict]) -> Optional[int]:
    """Index of the latest bar whose close is >= BREAK_MOVE away from the one before it, or None."""
    for i in range(len(bars) - 1, 0, -1):
        prev, cur = bars[i - 1].get("close"), bars[i].get("close")
        if prev and cur and prev > 0 and abs(float(cur) / float(prev) - 1) >= BREAK_MOVE:
            return i
    return None


def adjust_bars(bars: List[dict], factors: Optional[Dict[date, float]]) -> Tuple[List[dict], dict]:
    """(bars on one price scale, info). `bars` ascending by bar_date, as ohlcv_store.load_bars returns them.

    info = {price_basis, factor_steps, break_truncated_at, bars_dropped}; it is stored with the features so every
    scored row says how its prices were treated.
    """
    info = {"price_basis": BASIS_RAW, "factor_steps": 0, "break_truncated_at": None, "bars_dropped": 0}
    if not bars:
        return [], info
    out = list(bars)
    known = sorted(d for d in (factors or {}) if d <= bars[-1]["bar_date"])
    if known:
        anchor = factors[known[-1]]
        out, prev_ratio = [], None
        for b in bars:
            f = factors.get(b["bar_date"])
            if f is None:
                i = bisect.bisect_right(known, b["bar_date"])
                f = factors[known[i]] if i < len(known) else anchor
            ratio = f / anchor
            if prev_ratio is not None and ratio != prev_ratio:
                info["factor_steps"] += 1
            prev_ratio = ratio
            out.append(b if ratio == 1.0 else _scale(b, ratio))
        info["price_basis"] = BASIS_ADJUSTED
    cut = adjustment_break(out)
    if cut is not None:
        info["break_truncated_at"] = out[cut]["bar_date"].isoformat()
        info["bars_dropped"] = cut
        out = out[cut:]
    return out, info
