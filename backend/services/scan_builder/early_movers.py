"""Early movers: the top rule of the 3 Nov 2026 early-signals study, as a live list (docs/scan_builder/DESIGN.md §10).

Study: docs/scan_builder/early_signals/study_20261103.md (branch feat/scan-dashboard-early-signals; 30 sessions of Kite 5-minute
candles, 21 Sep–3 Nov 2026, 1,593 liquid NSE stocks). Its best early indicator of a ≥ 5 % rise from the open:

    volume so far ≥ 5 × its usual by now   AND   price ≥ 2 % over today's open

"Its usual by now" = the stock's 20-session average daily volume × the share of a day's volume the market usually trades by
that time (VOLUME_CURVE, the median share by 5-minute mark over the study's 20 training sessions, 21 Sep–19 Oct). The study
evaluated every 15 minutes from 09:30, so the list starts at 09:30. Universe as the study: 20-session average volume ≥ 50,000
and price ≥ 20. After the close the whole day's volume is compared with the 20-session average (share 1).

Owner, 3 Nov ~20:50 IST: add this rule as a list that raises alerts like the other scans (signals.py records it).
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

RVOL_MIN = 5.0
OVER_OPEN_MIN_PCT = 2.0
ADV_SESSIONS = 20
ADV_MIN_SESSIONS = 10
ADV_MIN = 50_000
PRICE_MIN = 20.0
START = (9, 30)                         # the study's first evaluation step
OPEN_MIN = 9 * 60 + 15
STUDY = "the 3 Nov 2026 early-signals study (30 sessions, docs/scan_builder/early_signals)"

# Cumulative share of a session's volume traded by the end of each 5-minute candle (09:15–09:20 … 15:25–15:30).
VOLUME_CURVE = (0.03553, 0.06181, 0.08484, 0.10626, 0.12597, 0.14353, 0.16078, 0.17653, 0.19150, 0.20633, 0.22129,
                0.23460, 0.24812, 0.26147, 0.27389, 0.28666, 0.29993, 0.31201, 0.32352, 0.33431, 0.34525, 0.35618, 0.36755,
                0.37900, 0.39054, 0.40119, 0.41286, 0.42425, 0.43439, 0.44531, 0.45569, 0.46562, 0.47607, 0.48612, 0.49634,
                0.50663, 0.51631, 0.52619, 0.53649, 0.54589, 0.55496, 0.56429, 0.57438, 0.58488, 0.59522, 0.60526, 0.61536,
                0.62426, 0.63409, 0.64331, 0.65290, 0.66240, 0.67144, 0.68206, 0.69284, 0.70256, 0.71272, 0.72395, 0.73477,
                0.74552, 0.75734, 0.76878, 0.78037, 0.79253, 0.80482, 0.81769, 0.83156, 0.84693, 0.86363, 0.88624, 0.91496,
                0.93926, 0.95631, 0.97474, 1.00000)


def usual_share(ist: datetime, live: bool) -> Optional[float]:
    """Share of a day's volume usually traded by `ist` (linear inside a 5-minute candle); 1.0 when not live (a full day);
    None before START during the session."""
    if not live:
        return 1.0
    if (ist.hour, ist.minute) < START:
        return None
    m = ist.hour * 60 + ist.minute + ist.second / 60.0 - OPEN_MIN
    slot = min(len(VOLUME_CURVE) - 1, int(m // 5))
    prev = VOLUME_CURVE[slot - 1] if slot > 0 else 0.0
    frac = min(1.0, max(0.0, (m - 5 * slot) / 5.0))
    return prev + (VOLUME_CURVE[slot] - prev) * frac


def rows(symbols: List[str], open_: np.ndarray, close: np.ndarray, volume_today: np.ndarray, volume_hist: np.ndarray,
         eligible: np.ndarray, share: float) -> List[List[Any]]:
    """[symbol, % over open, price, volume, volume × usual] for the stocks passing the rule, largest volume multiple first.
    volume_hist is the (K, N) daily volume BEFORE today (most recent last)."""
    hist = volume_hist[-ADV_SESSIONS:]
    with np.errstate(all="ignore"):
        n = np.sum(np.isfinite(hist), axis=0)
        adv = np.where(n >= ADV_MIN_SESSIONS, np.nanmean(hist, axis=0), np.nan)
        usual = adv * share
        rvol = volume_today / usual
        over = (close - open_) / open_ * 100.0
    ok = (eligible & np.isfinite(rvol) & np.isfinite(over) & (adv >= ADV_MIN) & (close >= PRICE_MIN)
          & (rvol >= RVOL_MIN) & (over >= OVER_OPEN_MIN_PCT))
    out = []
    for j in np.flatnonzero(ok):
        out.append([symbols[j], round(float(over[j]), 2), round(float(close[j]), 2), int(volume_today[j]),
                    round(float(rvol[j]), 2)])
    out.sort(key=lambda r: -r[4])
    return out


def criteria(ist: datetime, live: bool, share: Optional[float]) -> List[Dict[str, Any]]:
    when = ist.strftime("%H:%M")
    if not live:
        vol = (f"The day's volume ≥ {RVOL_MIN:g} × its 20-session average (after the close the whole day counts)")
    elif share is None:
        vol = f"Volume so far ≥ {RVOL_MIN:g} × its usual by now — the list starts at 09:30, the study's first step"
    else:
        vol = (f"Volume so far ≥ {RVOL_MIN:g} × its usual by {when} (20-session average daily volume × {share:.1%}, the share "
               f"of a day's volume usually traded by then)")
    return [
        {"text": f"Universe: NSE stocks with a 20-session average volume ≥ {ADV_MIN:,} and price ≥ {PRICE_MIN:g}",
         "level": 0, "applied": True, "note": None},
        {"text": vol, "level": 0, "applied": share is not None, "note": None if share is not None else "not applied — before 09:30"},
        {"text": f"Price ≥ {OVER_OPEN_MIN_PCT:g} % over today's open", "level": 0, "applied": True, "note": None},
        {"text": f"Rule from {STUDY}", "level": 0, "applied": True, "note": None},
    ]


def finite(v: Any) -> bool:
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False
