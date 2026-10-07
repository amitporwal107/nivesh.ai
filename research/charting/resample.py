"""Weekly/monthly OHLCV resampling for chart display — PRD docs/charting.md §38.7 ("Weekly and
monthly (P0, display only)"), §38.12 row W2, §38.13 acceptance criterion 7.

Computed ONCE at export time (`research/charting/export.py`) and written into the committed
snapshot, hashed with it (research/charting/SNAPSHOT_SCHEMA.md) — the chart API never resamples
at request time and the browser never recomputes a series it displays (§38.2, the Sim Lab rule).
Pattern detection stays on daily bars only; this module is display-only and is never fed to
`research.charting.patterns`.

Grouping (§38.7, literal spec text):
  - **Weekly** — NSE sessions grouped by ISO week (Monday-Friday). Two sessions are in the same
    weekly bar iff they share the same (ISO year, ISO week) — `pandas.Series.dt.isocalendar()`,
    which correctly handles the Dec/Jan boundary (e.g. 2024-12-30/31 fall in ISO week 1 of 2025,
    not week 53 of 2024).
  - **Monthly** — calendar months: two sessions are in the same monthly bar iff they share the
    same (year, month).
  - **Holidays are simply absent.** A period's bar is built only from the sessions that actually
    exist in the input frame; there is never a synthetic placeholder row for a day the exchange
    was closed (or a day the source data simply hasn't reached yet).

OHLCV aggregation, per period (§38.7): `open` = the period's FIRST session's open, `high` = max
high, `low` = min low, `close` = the period's LAST session's close, `volume` = sum of volume.
"First"/"last" are by date order, not input-row order (`bars.py` preserves source order rather
than re-sorting, and out-of-order rows are a real, if rare, condition it deliberately does not
fix — see its module docstring) — this module sorts by date before aggregating so a resampled
bar's open/close are never accidentally swapped by an unsorted or out-of-order input frame.

The bar's own `date` is the period's LAST session's date (never a synthetic period-start/end
label) — the same date whose close became this bar's close, and the date `series.py`'s indicators
(run on this same resampled frame afterwards, unchanged, per §38.7 "same series code") treat as
"now" for that bar.

**Incomplete flag.** The spec: "the trailing bar of the current week/month is flagged incomplete
... so the UI can mark it and never treat it as confirmation." This module has no independently
verified NSE trading-holiday calendar (research.charting.validate's own MISSING_CANDLE calendar
is only the union of dates the whole universe actually traded, which by construction ends at the
same date the daily series ends at — it cannot distinguish "this ISO week/month is genuinely over"
from "the source data simply hasn't caught up to the rest of the week/month yet"). The
conservative, spec-compliant choice is therefore purely structural and needs no calendar: the
LAST bar of the whole resampled series is always `incomplete=True`; every earlier bar — whose
period is provably over because at least one session from a LATER period already exists — is
`incomplete=False`.
"""
from __future__ import annotations

import pandas as pd

from research.charting.config import BARS_COLUMNS

TIMEFRAMES = ("1W", "1M")
RESAMPLED_COLUMNS = (*BARS_COLUMNS, "incomplete")


def _aggregate_groups(df: pd.DataFrame, group_keys: pd.Series) -> pd.DataFrame:
    """Shared OHLCV aggregation for both weekly and monthly grouping. `group_keys` is indexed the
    same way as `df` (both callers derive it directly from `df["date"]`, so the index is intact).
    `df` is sorted by date first (see module docstring) so `("open", "first")` / `("close",
    "last")` are genuinely the period's first/last session by date, not by whatever order the
    rows arrived in; `group_keys` is reordered by that same sort so each row still carries its
    own correct group label. `groupby(..., sort=False)` then preserves that chronological group
    order, and the final `sort_values("date")` is a belt-and-braces guarantee of ascending output
    regardless."""
    order = df.sort_values("date", kind="mergesort").index
    work = df.loc[order].reset_index(drop=True)
    work = work.assign(_grp=group_keys.loc[order].reset_index(drop=True))

    grouped = work.groupby("_grp", sort=False)
    out = grouped.agg(
        date=("date", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index(drop=True)
    out = out.sort_values("date", kind="mergesort").reset_index(drop=True)
    out["incomplete"] = False
    if len(out):
        out.loc[out.index[-1], "incomplete"] = True
    return out[list(RESAMPLED_COLUMNS)]


def resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """§38.7: NSE sessions grouped by ISO week (Monday-Friday). Returns a frame shaped like
    `BARS_COLUMNS` plus `incomplete` (bool), ascending by date, one row per ISO (year, week) that
    had at least one session in `df`. Empty in, empty (correctly shaped) out."""
    if df.empty:
        return df.reindex(columns=list(RESAMPLED_COLUMNS))
    iso = df["date"].dt.isocalendar()
    group_keys = (iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)).rename("_grp")
    return _aggregate_groups(df, group_keys)


def resample_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """§38.7: calendar months. Returns a frame shaped like `BARS_COLUMNS` plus `incomplete`
    (bool), ascending by date, one row per (year, month) that had at least one session in `df`.
    Empty in, empty (correctly shaped) out."""
    if df.empty:
        return df.reindex(columns=list(RESAMPLED_COLUMNS))
    group_keys = df["date"].dt.to_period("M").astype(str).rename("_grp")
    return _aggregate_groups(df, group_keys)


RESAMPLERS = {"1W": resample_weekly, "1M": resample_monthly}
