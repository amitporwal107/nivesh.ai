"""Research → Charts, LIVE source: daily bars for any NSE symbol, not just the frozen snapshot.

    GET /api/research/chart-live/{symbol}/ohlcv?start=&end=   → DaaS /prices/adjusted/{symbol}

Why this is a separate module from `research_chart.py`. That one serves the committed snapshot and
its docstring promises it reads "no DB, no network" — the guarantee that makes a research chart
reproducible and hash-checkable. Paper trades cannot use it: the snapshot is 50 large caps while the
paper engine selects for volatility (ATR ~7% of price), and the measured overlap with every paper
symbol on record is 0 of 10. So live symbols get their own route, their own provenance, and a
pit_status that never claims to be the frozen run. Mixing the two would leave the snapshot badge
asserting something untrue.

Bars come from `nidp.prices_eod_adjusted` (adj_* columns: split and bonus adjusted, price-return).
Raw bhavcopy prices are deliberately NOT served here: joining raw prices to anything adjusted reads a
1:6 split as -83%, which is a real defect this codebase has hit before.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Query

from feature_gate import require_feature
from routes.move_odds import _proxy

router = APIRouter(prefix="/api/research/chart-live", tags=["research_chart_live"])
FLAG = "charting"

SYMBOL_PATTERN = r"^[A-Z0-9&\-]{1,32}$"
SymbolPath = PathParam(..., pattern=SYMBOL_PATTERN)
MAX_BARS = 5_000            # the DaaS page ceiling; ~20 years of daily bars


def _bar(row: dict) -> Optional[list]:
    """One contract Bar: [date, o, h, l, c, v]. A row missing any leg is dropped, not patched --
    a candle built from three prices is indistinguishable from a real one once it is drawn."""
    d = row.get("as_of_date")
    o, h, l, c = row.get("adj_open"), row.get("adj_high"), row.get("adj_low"), row.get("adj_close")
    if d is None or None in (o, h, l, c):
        return None
    try:
        o, h, l, c = float(o), float(h), float(l), float(c)
        v = float(row.get("adj_volume") or 0.0)
    except (TypeError, ValueError):
        return None
    if min(o, h, l, c) <= 0 or h < max(o, c) or l > min(o, c):
        return None                      # an impossible bar is a data fault, not something to plot
    return [str(d)[:10], o, h, l, c, v]


@router.get("/{symbol}/ohlcv")
async def ohlcv(symbol: str = SymbolPath, start: Optional[str] = Query(None),
                end: Optional[str] = Query(None), limit: int = Query(MAX_BARS, ge=1, le=MAX_BARS),
                user: dict = Depends(require_feature(FLAG))) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    payload = await _proxy(f"/prices/adjusted/{symbol}", params)

    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="upstream_shape")
    if not rows:
        raise HTTPException(status_code=404, detail="no_bars_for_symbol")

    # DaaS returns newest-first for paging; a chart reads oldest-first.
    bars = [b for b in (_bar(r) for r in reversed(rows)) if b is not None]
    if not bars:
        raise HTTPException(status_code=404, detail="no_plottable_bars")

    dropped = len(rows) - len(bars)
    last = rows[0] if rows else {}
    return {
        "symbol": symbol,
        "timeframe": "1D",
        "bars": bars,
        # Never "PIT_VALIDATED": these bars are read live and are not part of any frozen run, so the
        # UI must not badge them with the snapshot's guarantees.
        "data_quality_status": "PARTIAL" if dropped else "VALID",
        "pit_status": "PIT_UNVERIFIED",
        "findings": ([{"date": bars[-1][0], "rule_id": "incomplete_bars_dropped",
                       "observed": {"dropped": dropped}}] if dropped else []),
        "provenance": {
            "provider": "nidp.prices_eod_adjusted",
            "series": "EQ",
            "adjustment_status": "SPLIT_BONUS_ADJUSTED",
            "last_bar_date": bars[-1][0],
            "source_mode": "live",
            "last_event_type": last.get("last_event_type"),
        },
    }
