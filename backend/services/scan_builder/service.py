"""Running a validated scan: our data in (services.scan_builder.data), the engine's evaluation, the API's RunResult out.

The panel is cut to the scan's universe before evaluation (an F&O scan computes ~220 columns, not ~2,700), today's candle is
appended as the last row, and only stocks with a candle on that row are evaluated, so every row of a result is on the same
day (DESIGN.md §2 "Today-bar rule"). The evaluation is numpy work and runs in a thread so the event loop keeps serving.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from . import engine
from . import spec as specmod
from .data import SOURCE_PRICES, SOURCE_TODAY, BasePanel, Reference, ScanData, TodayOverlay

REFRESH_SECONDS = 10


def universe_symbols(key: str, base: BasePanel, ref: Reference) -> List[str]:
    """The panel symbols in a universe, in panel order."""
    if key == "cash":
        return list(base.symbols)
    if key == "fno":
        pool = ref.fno
    else:
        pool = ref.members.get(key) or set()
    return [s for s in base.symbols if s in pool]


def universe_sizes(base: Optional[BasePanel], ref: Reference) -> Dict[str, Optional[int]]:
    out: Dict[str, Optional[int]] = {}
    for key in specmod.UNIVERSES:
        if base is not None:
            out[key] = len(universe_symbols(key, base, ref))
        elif key == "cash":
            out[key] = None
        elif key == "fno":
            out[key] = len(ref.fno)
        else:
            out[key] = len(ref.members.get(key) or ())
    return out


def assemble(base: BasePanel, cols: List[int], overlay: TodayOverlay) -> engine.Panel:
    """The engine's panel: the universe's columns, plus today's row when the overlay has candles for a new day."""
    def take(a: np.ndarray) -> np.ndarray:
        return a[:, cols]

    o, h, l, c, v = (take(base.open), take(base.high), take(base.low), take(base.close), take(base.volume))
    dates = base.dates
    if overlay.mode != "eod" and overlay.bars:
        row = np.full((5, len(cols)), np.nan)
        pos = {j: k for k, j in enumerate(cols)}
        for j, bar in overlay.bars.items():
            k = pos.get(j)
            if k is not None:
                row[:, k] = bar
        o, h, l, c, v = (np.vstack([a, row[i][None, :]]) for i, a in enumerate((o, h, l, c, v)))
        dates = np.append(dates, np.datetime64(overlay.day.isoformat(), "D"))
    return engine.Panel(symbols=[base.symbols[j] for j in cols], dates=dates, open=o, high=h, low=l, close=c, volume=v)


def basis_text(overlay: TodayOverlay, base: BasePanel, used_rest: bool) -> str:
    eod = base.eod_date.strftime("%d %b %Y")
    if overlay.mode == "live":
        at = _ist_clock(overlay.quote_as_of)
        return (f"Kite live{(' at ' + at) if at else ''} (today's candle is still forming), over NSE end-of-day bars to {eod}, "
                f"split/bonus adjusted{'; stocks outside the live feed use Kite quotes read at most 30 s ago' if used_rest else ''}.")
    if overlay.mode == "kite_close":
        return (f"Kite close of {overlay.day.strftime('%d %b %Y')} (provisional until the exchange's end-of-day file), over NSE "
                f"end-of-day bars to {eod}, split/bonus adjusted.")
    return f"NSE end-of-day bars to {eod}, split/bonus adjusted (no candle for a later day is added)."


def _ist_clock(stamp: Optional[str]) -> Optional[str]:
    if not stamp:
        return None
    try:
        d = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    from services.kite_live_feed.config import IST
    return d.astimezone(IST).strftime("%H:%M:%S IST")


async def run(spec: Dict[str, Any], data: ScanData) -> Dict[str, Any]:
    """RunResult (DESIGN.md §4) for a VALIDATED spec. Raises data.DataUnavailable when prices cannot be read at all."""
    t0 = time.monotonic()
    base = await data.panel()
    ref = await data.reference()
    root = spec["filters"]["universe"]
    syms = universe_symbols(root, base, ref)
    cols = [base.index[s] for s in syms]
    overlay = await data.today(base, syms)
    panel = assemble(base, cols, overlay)
    last = panel.close[-1] if panel.close.size else np.array([])
    eligible = np.isfinite(last) if last.size else np.zeros(0, dtype=bool)
    if overlay.mode == "eod":
        # Every stock's latest candle must be the panel's last day, else it is a stale, suspended or delisted line.
        eligible = np.isfinite(panel.close[-1]) if panel.close.size else eligible
    pos = {s: i for i, s in enumerate(panel.symbols)}
    universes: Dict[str, np.ndarray] = {}
    for key in specmod.universes_in(spec):
        mask = np.zeros(len(panel.symbols), dtype=bool)
        for s in universe_symbols(key, base, ref):
            i = pos.get(s)
            if i is not None:
                mask[i] = True
        universes[key] = mask
    fundamentals: Dict[str, np.ndarray] = {}
    for fld in specmod.fundamentals_in(spec):
        vals = ref.fundamentals.get(fld) or {}
        fundamentals[fld] = np.array([vals.get(s, np.nan) for s in panel.symbols], dtype=float)
    res = await asyncio.to_thread(engine.evaluate, spec, panel, eligible=eligible, universes=universes,
                                  fundamentals=fundamentals)
    today_label = overlay.mode if overlay.mode != "eod" else "eod"
    rows = [{"symbol": panel.symbols[i], "name": ref.names.get(panel.symbols[i], ""), "values": vals, "today": today_label}
            for i, vals in zip(res["order"], res["values"])]
    used_rest = bool(overlay.counts.get("rest_quotes"))
    warnings = list(overlay.warnings)
    no_today = int(len(panel.symbols) - int(eligible.sum()))
    if overlay.mode == "eod" and no_today:
        warnings.append(f"{no_today} stock(s) have no candle on {overlay.day.isoformat()} (suspended, or not traded) and are left out.")
    elapsed = int((time.monotonic() - t0) * 1000)
    return {
        "ok": True,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_ms": elapsed,
        "basis": {"mode": overlay.mode, "day": overlay.day.isoformat(), "eod_date": base.eod_date.isoformat(),
                  "quote_as_of": overlay.quote_as_of, "text": basis_text(overlay, base, used_rest)},
        "sources": {"prices": SOURCE_PRICES, "today": SOURCE_TODAY.get(overlay.mode),
                    "fundamentals": (f"NIDP feature store, as of {ref.fundamentals_as_of}" if ref.fundamentals_as_of
                                     else "NIDP feature store")},
        "market": {"open": overlay.session_open, "refresh_seconds": REFRESH_SECONDS},
        "universe": {"key": root, "label": specmod.UNIVERSES[root], "size": len(panel.symbols)},
        "counts": {"universe": len(panel.symbols), "evaluated": res["counts"]["evaluated"], "matched": res["counts"]["matched"],
                   "shown": res["counts"]["shown"], "no_today_bar": no_today, "no_history": res["counts"]["no_history"]},
        "columns": res["columns"],
        "rows": rows,
        "nodes": res["nodes"],
        "warnings": warnings,
        "diagnostics": {"panel_source": data.panel_source, "rest_calls": data.rest.calls, **overlay.counts},
    }
