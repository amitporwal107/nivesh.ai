"""Pattern validation v1 (PRD F5): how often a pattern's signals made money after costs, with small samples pulled
toward a base rate. Long signals only in v1 (delivery costs); short signals are counted and skipped, never faked.

Trade model (stated so the numbers can be reproduced): signal on session D -> buy at the next session's OPEN -> sell at
the CLOSE `horizon` sessions after that entry. Costs: bundled zerodha-equity-v1 delivery card, NSE, via
research.costs.engine.compute_round_trip. That card is effective from 2026-09-19, so earlier trades are costed at the
current card (allow_retroactive); every result says so in `cost_basis`."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Dict, List, Optional

from . import _research

LOW_SAMPLE_N = 30            # below this the hit rate is shrunk toward the base rate
BASE_RATE = 0.5              # the prior when no better base rate is supplied
NOTIONAL_INR = 100_000       # position size used to apply the cost card
COST_BASIS = "zerodha-equity-v1 delivery NSE (current card applied to historical trades)"


def _round_trip_net_pct(entry: float, exit_: float, buy_date: dt.date, sell_date: dt.date) -> float:
    from research.costs.engine import compute_round_trip
    qty = max(1, int(NOTIONAL_INR // entry))
    rec = compute_round_trip(
        buy_date=buy_date, sell_date=sell_date, qty=qty, entry_price=Decimal(str(entry)),
        exit_price=Decimal(str(exit_)), cost_path="bundled",
        cost_kwargs=dict(rule_id="zerodha-equity-v1", profile="delivery", exchange="NSE", dp_applies=True,
                         allow_retroactive=True),
    )
    return float(rec.net_before_tax / (Decimal(str(entry)) * qty))


def evaluate_events(events: List[Dict[str, Any]], bars_by_symbol: Dict[str, Any], horizon: int) -> Dict[str, Any]:
    """`events`: [{symbol, signal_date, direction: "long"|"short", regime?: str}]. Returns the per-pattern stats."""
    if horizon < 1:
        raise ValueError("horizon must be at least 1 session")
    _ctx, _regime, rw, _rs = _research.load()
    import pandas as pd

    trades: List[Dict[str, Any]] = []
    skipped = {"short_not_supported": 0, "sealed_window": 0, "no_bars": 0, "horizon_beyond_data": 0}
    for ev in events:
        if str(ev.get("direction", "long")).lower() != "long":
            skipped["short_not_supported"] += 1
            continue
        bars = bars_by_symbol.get(ev["symbol"])
        if bars is None or len(bars) == 0:
            skipped["no_bars"] += 1
            continue
        b = bars.copy()
        b["date"] = pd.to_datetime(b["date"]).dt.normalize()
        b = b.sort_values("date").reset_index(drop=True)
        sig = pd.Timestamp(ev["signal_date"]).normalize()
        pos = b.index[b["date"] > sig]
        if len(pos) == 0 or int(pos[0]) + horizon > len(b) - 1:
            skipped["horizon_beyond_data"] += 1
            continue
        i_in, i_out = int(pos[0]), int(pos[0]) + horizon
        # the whole span, signal day included, must be clear of the sealed block
        if rw.overlaps_sealed_gap(sig, b["date"].iloc[i_out]):
            skipped["sealed_window"] += 1
            continue
        entry, exit_ = float(b["open"].iloc[i_in]), float(b["close"].iloc[i_out])
        if entry <= 0 or exit_ <= 0:
            skipped["no_bars"] += 1
            continue
        net = _round_trip_net_pct(entry, exit_, b["date"].iloc[i_in].date(), b["date"].iloc[i_out].date())
        trades.append({"net_pct": net, "regime": ev.get("regime")})

    return {"horizon_sessions": horizon, "cost_basis": COST_BASIS, "skipped": skipped,
            **summarise(trades)}


def summarise(trades: List[Dict[str, Any]], base_rate: float = BASE_RATE) -> Dict[str, Any]:
    out = _stats([t["net_pct"] for t in trades], base_rate)
    regimes = sorted({t["regime"] for t in trades if t.get("regime")})
    out["by_regime"] = {r: _stats([t["net_pct"] for t in trades if t.get("regime") == r], base_rate) for r in regimes}
    return out


def _stats(net: List[float], base_rate: float) -> Dict[str, Any]:
    n = len(net)
    if n == 0:
        return {"n": 0, "hits": 0, "hit_rate": None, "shrunk_hit_rate": None, "expectancy_net_pct": None,
                "flags": ["NO_SAMPLE"]}
    hits = sum(1 for x in net if x > 0)
    raw = hits / n
    w = min(1.0, n / LOW_SAMPLE_N)
    return {
        "n": n, "hits": hits, "hit_rate": raw,
        "shrunk_hit_rate": w * raw + (1 - w) * base_rate,
        "expectancy_net_pct": sum(net) / n * 100.0,
        "flags": ["LOW_SAMPLE"] if n < LOW_SAMPLE_N else [],
    }
