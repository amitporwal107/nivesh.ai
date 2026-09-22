"""Large-gap safety net over raw Kite bars -- task §1.c, PRD §9.1 "abnormal gaps" /
"corporate-action discontinuities".

Independent of the sourced demerger event list (events.py): computes the ordinary
open-vs-previous-close percentage gap for every bar of every symbol and flags the ones
beyond a configurable threshold (CONFIG["large_gap_threshold_pct"]). This is a CROSS-CHECK,
not a source of truth -- every flag is a REVIEW candidate. A flag can be a real demerger
the sourced list also has, a demerger/scheme the sourced list does not have, or something
else entirely (a circuit-to-circuit run in an illiquid stock, a -BE trade-to-trade auction
gap, a results/fraud/block-deal shock, bad data). Never treat a flag alone as confirmation
-- see events.py / data/demergers.csv for what is actually sourced-confirmed.
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from research.corporate_actions.config import CONFIG

GAP_COLUMNS = ("date", "prev_close", "open", "gap_pct")


def compute_gaps(bars: pd.DataFrame, *, date_column: str = "date",
                  open_column: str = "open", close_column: str = "close") -> pd.DataFrame:
    """Open-vs-previous-close % gap for every row of `bars` (ascending date order assumed,
    matching research.charting.bars' source-order contract). The first row has no prior
    close and gets NaN. Returns columns exactly GAP_COLUMNS plus `symbol` if present in
    `bars`. Does not filter or sort -- see flag_large_gaps for that."""
    out = pd.DataFrame({
        "date": bars[date_column].reset_index(drop=True),
        "prev_close": bars[close_column].shift(1).reset_index(drop=True),
        "open": bars[open_column].reset_index(drop=True),
    })
    out["gap_pct"] = (out["open"] - out["prev_close"]) / out["prev_close"] * 100.0
    if "symbol" in bars.columns:
        out.insert(0, "symbol", bars["symbol"].reset_index(drop=True))
    return out


def flag_large_gaps(bars: pd.DataFrame, *, threshold_pct: float | None = None,
                     config: dict | None = None, date_column: str = "date",
                     open_column: str = "open", close_column: str = "close") -> pd.DataFrame:
    """Rows of compute_gaps() whose |gap_pct| >= threshold_pct (default
    CONFIG["large_gap_threshold_pct"]), sorted by |gap_pct| descending. Empty frame (same
    columns) if `bars` has fewer than CONFIG["gap_detector_min_bars"] rows or nothing
    clears the threshold."""
    cfg = CONFIG if config is None else config
    threshold = cfg["large_gap_threshold_pct"] if threshold_pct is None else threshold_pct
    if len(bars) < cfg["gap_detector_min_bars"]:
        cols = ["symbol"] + list(GAP_COLUMNS) if "symbol" in bars.columns else list(GAP_COLUMNS)
        return pd.DataFrame(columns=cols)

    gaps = compute_gaps(bars, date_column=date_column, open_column=open_column, close_column=close_column)
    flagged = gaps[gaps["gap_pct"].abs() >= threshold].copy()
    return flagged.sort_values("gap_pct", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def scan_universe_for_large_gaps(
    symbol_frames: Iterable[tuple[str, pd.DataFrame]],
    *,
    threshold_pct: float | None = None,
    config: dict | None = None,
) -> pd.DataFrame:
    """Run flag_large_gaps over every (symbol, bars) pair -- e.g.
    `research.charting.bars.load_all()` -- and concatenate the results, sorted by
    |gap_pct| descending. This is the driver behind data/gap_review_candidates.csv
    (see build_demerger_events.py). Symbols with zero flags contribute nothing."""
    frames = []
    for symbol, df in symbol_frames:
        flagged = flag_large_gaps(df, threshold_pct=threshold_pct, config=config)
        if flagged.empty:
            continue
        flagged = flagged.copy()
        flagged.insert(0, "symbol", symbol)
        frames.append(flagged)
    if not frames:
        return pd.DataFrame(columns=["symbol", *GAP_COLUMNS])
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values("gap_pct", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)
