"""v4 results-print block: the quarter a company filed after the open on T, read at the freeze-time cutoff.

Most results are broadcast after 15:30, so the 15:30 cutoff the other blocks use deliberately ignores them even
though the snapshot is frozen at 20:45, before the next open. This block reads filings broadcast in
(09:15, 20:30] IST on T — the ones whose reaction session is D — and describes the print against the company's own
earlier, already-known quarters. A filing with no exchange timestamp is unknown, never proxied.
"""
from __future__ import annotations

from datetime import date, time
from typing import Iterable

import numpy as np
import pandas as pd

from .event_gate import cutoff_ist

RESULTS_PRINT_FEATURES = ("filed_today", "filed_pat_yoy", "filed_rev_yoy", "filed_pat_qoq", "filed_loss", "filed_turnaround",
                          "filed_margin_chg", "hours_since_filing")
FREEZE_CUTOFF = time(20, 30)   # the nightly snapshot runs at 20:45; anything broadcast by 20:30 is in its export
OPEN = time(9, 15)


def _growth(cur: float, prev: float) -> float:
    return float(cur / prev - 1) if np.isfinite(cur) and np.isfinite(prev) and cur > 0 and prev > 0 else np.nan


def results_print(financials: pd.DataFrame, symbols: Iterable[str], T: date) -> pd.DataFrame:
    symbols = list(symbols)
    q = financials[financials["period_type"].eq("quarterly")] if "period_type" in financials else financials
    q = q[q["symbol"].isin(symbols)].copy()
    ts = pd.to_datetime(q["broadcast_at"], utc=True)
    lo, hi = pd.Timestamp(cutoff_ist(T, at=OPEN)), pd.Timestamp(cutoff_ist(T, at=FREEZE_CUTOFF))
    q["_ts"] = ts
    known = q[ts.notna() & (ts <= hi)]
    today = known[known["_ts"] > lo].sort_values(["symbol", "period_end", "consolidated"], kind="mergesort").drop_duplicates("symbol", keep="last")
    out = pd.DataFrame(np.nan, index=pd.Index(symbols, name="symbol"), columns=list(RESULTS_PRINT_FEATURES), dtype="float64")
    out["filed_today"] = 0.0
    for _, f in today.iterrows():
        sym, pe = f["symbol"], f["period_end"]
        hist = known[(known["symbol"] == sym) & (known["period_end"] < pe)].sort_values(["period_end", "consolidated"], kind="mergesort").drop_duplicates("period_end", keep="last").set_index("period_end")
        yago = (pe - pd.DateOffset(years=1)) + pd.offsets.QuarterEnd(0)
        qago = (pe - pd.DateOffset(months=3)) + pd.offsets.QuarterEnd(0)
        pat, rev = float(f["pat_cr"]), float(f["revenue_from_ops_cr"])
        py = float(hist.loc[yago, "pat_cr"]) if yago in hist.index else np.nan
        ry = float(hist.loc[yago, "revenue_from_ops_cr"]) if yago in hist.index else np.nan
        pq = float(hist.loc[qago, "pat_cr"]) if qago in hist.index else np.nan
        out.loc[sym, "filed_today"] = 1.0
        out.loc[sym, "filed_pat_yoy"] = _growth(pat, py)
        out.loc[sym, "filed_rev_yoy"] = _growth(rev, ry)
        out.loc[sym, "filed_pat_qoq"] = _growth(pat, pq)
        out.loc[sym, "filed_loss"] = float(np.isfinite(pat) and pat < 0)
        out.loc[sym, "filed_turnaround"] = float(np.isfinite(pat) and pat > 0 and np.isfinite(py) and py < 0)
        out.loc[sym, "filed_margin_chg"] = (pat / rev - py / ry) if all(np.isfinite(v) for v in (pat, rev, py, ry)) and rev > 0 and ry > 0 else np.nan
        out.loc[sym, "hours_since_filing"] = float((hi - f["_ts"]).total_seconds() / 3600.0)
    return out.astype("float64")
