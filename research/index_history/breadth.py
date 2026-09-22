"""Market-breadth indicators derived from our own Kite daily-bar universe (there is no
breadth feed in NIDP), for the research charting engine.

Source bars: gzip CSV parts at research/kite_history/day_2021/part-*.csv.gz
    (columns: symbol,instrument_token,date,open,high,low,close,volume,source_version;
    some parts are header-only — harmless, they just contribute no rows).

Per date this computes: advancers, decliners, unchanged, advance/decline ratio, % of
names above their SMA50 and SMA200, new-52-week-high/low counts, and the number of
names contributing (those with a valid prior-day close, i.e. usable in the adv/decl
tally that date).

Rules:
  - ETF exclusion: symbols in the sealed ETF list are dropped before any metric is
    computed (equities-only breadth). That list has NO header row.
  - Point-in-time: every date's value uses only bars dated on or before that date —
    rolling windows never look ahead.
  - Full-window-only: a name contributes to a rolling metric (SMA-above-price, new
    52-week high/low) only once it has accumulated the metric's FULL lookback window
    of its own prior bars; before that it is left out of that metric's numerator and
    denominator for that date. It can still count toward advance/decline as soon as it
    has one prior trading day.
  - Sealed window (2023-01-01..2024-07-31 inclusive, manifest.SEALED_START/END): no
    research value may be computed from it, as an output row OR as an input. Sealed bars
    are dropped before any metric is computed, and the series is split at the window:
    each symbol's rolling state (prior close, SMA, 52-week high/low) restarts after
    2024-07-31, so a post-sealed value exists only once that name has a full window of
    post-sealed bars (A/D from its 2nd post-sealed bar, SMA50 from its 50th, 52-week from
    its 252nd). Before the split, a 52-week lookback from Sept 2024 read ~11 months of
    sealed bars.
  - Blank != zero: new_52w_highs/lows are NaN (not 0) on a date where no name has a full
    high/low window, like pct_above_sma*.
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd

# Repo root two levels up, so both `python -m research.index_history.breadth` and a
# direct `python research/index_history/breadth.py` (run from anywhere) can resolve
# `research....` imports the same way.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from research.index_history.manifest import SEALED_END, is_sealed  # noqa: E402

SMA_WINDOWS: dict[str, int] = {"pct_above_sma50": 50, "pct_above_sma200": 200}
HIGH_LOW_WINDOW_DAYS = 252  # trading-day proxy for a 52-week high/low lookback

RAW_BAR_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume"]
BASE_BREADTH_COLUMNS = [
    "date", "advancers", "decliners", "unchanged", "advance_decline_ratio",
]
TAIL_BREADTH_COLUMNS = ["new_52w_highs", "new_52w_lows", "names_contributing"]


def breadth_columns(sma_windows: dict[str, int] = SMA_WINDOWS) -> list[str]:
    return BASE_BREADTH_COLUMNS + list(sma_windows.keys()) + TAIL_BREADTH_COLUMNS


def load_etf_symbols(path) -> set[str]:
    """The sealed ETF exclusion list has NO header row — every non-blank line is a
    symbol to exclude."""
    with open(path) as fh:
        return {line.strip() for line in fh if line.strip()}


def load_universe_bars(parts_glob: str, etf_symbols: Iterable[str] = ()) -> pd.DataFrame:
    """Concatenate every gzip CSV part (skipping empty/header-only ones), drop ETFs,
    de-duplicate (symbol, date), sort by symbol then date."""
    frames = []
    for path in sorted(glob.glob(parts_glob)):
        try:
            df = pd.read_csv(path, dtype={"symbol": str})
        except pd.errors.EmptyDataError:
            continue
        if df.empty:
            continue
        frames.append(df[RAW_BAR_COLUMNS])

    if not frames:
        return pd.DataFrame(columns=RAW_BAR_COLUMNS)

    out = pd.concat(frames, ignore_index=True)
    etf_set = set(etf_symbols)
    if etf_set:
        out = out[~out["symbol"].isin(etf_set)]
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out = out.drop_duplicates(subset=["symbol", "date"], keep="first")
    out = out.sort_values(["symbol", "date"]).reset_index(drop=True)
    return out


def _per_symbol_flags(g: pd.DataFrame, sma_windows: dict[str, int], high_low_window: int) -> pd.DataFrame:
    """One symbol's rows, sorted by date, with rolling point-in-time flag columns added.
    `min_periods=window` is what enforces "full window only" — pandas leaves earlier
    rows as NaN/not-eligible until the window is fully populated."""
    g = g.sort_values("date").copy()
    g["prev_close"] = g["close"].shift(1)
    g["has_prev"] = g["prev_close"].notna()

    for col, window in sma_windows.items():
        sma = g["close"].rolling(window, min_periods=window).mean()
        eligible = sma.notna()
        g[f"{col}__eligible"] = eligible
        g[f"{col}__above"] = eligible & (g["close"] > sma)

    if high_low_window and high_low_window > 0:
        roll_high = g["high"].rolling(high_low_window, min_periods=high_low_window).max()
        roll_low = g["low"].rolling(high_low_window, min_periods=high_low_window).min()
        hl_eligible = roll_high.notna()
        g["hl__eligible"] = hl_eligible
        g["is_new_high"] = hl_eligible & (g["high"] >= roll_high)
        g["is_new_low"] = hl_eligible & (g["low"] <= roll_low)
    else:
        g["hl__eligible"] = False
        g["is_new_high"] = False
        g["is_new_low"] = False

    return g


def compute_breadth(
    bars: pd.DataFrame,
    sma_windows: dict[str, int] = SMA_WINDOWS,
    high_low_window: int = HIGH_LOW_WINDOW_DAYS,
    drop_sealed_window: bool = True,
) -> pd.DataFrame:
    """`bars` columns: symbol, date ('YYYY-MM-DD' strings), open, high, low, close,
    volume — already ETF-filtered and de-duplicated (see load_universe_bars). Returns
    one row per date, ascending, per breadth_columns(sma_windows).

    `drop_sealed_window=False` is for tests only: sealed bars then stay in as ordinary
    inputs and rows, with no split at the window."""
    columns = breadth_columns(sma_windows)
    if bars.empty:
        return pd.DataFrame(columns=columns)

    if drop_sealed_window:
        bars = bars[~bars["date"].apply(is_sealed)]
        segment = bars["date"] > SEALED_END.isoformat()  # False = before, True = after
    else:
        segment = pd.Series(False, index=bars.index)

    per_symbol = [
        _per_symbol_flags(g, sma_windows, high_low_window)
        for _, g in bars.groupby([bars["symbol"], segment], sort=False)
    ]
    df = pd.concat(per_symbol, ignore_index=True)

    df["is_adv"] = df["has_prev"] & (df["close"] > df["prev_close"])
    df["is_dec"] = df["has_prev"] & (df["close"] < df["prev_close"])
    df["is_unch"] = df["has_prev"] & (df["close"] == df["prev_close"])

    agg_spec = {
        "advancers": ("is_adv", "sum"),
        "decliners": ("is_dec", "sum"),
        "unchanged": ("is_unch", "sum"),
        "names_contributing": ("has_prev", "sum"),
        "new_52w_highs": ("is_new_high", "sum"),
        "new_52w_lows": ("is_new_low", "sum"),
        "hl__eligible_n": ("hl__eligible", "sum"),
    }
    for col in sma_windows:
        agg_spec[f"{col}__eligible_n"] = (f"{col}__eligible", "sum")
        agg_spec[f"{col}__above_n"] = (f"{col}__above", "sum")

    out = df.groupby("date").agg(**agg_spec).reset_index()

    out["advance_decline_ratio"] = out.apply(
        lambda r: (r["advancers"] / r["decliners"]) if r["decliners"] else float("nan"), axis=1
    )
    no_hl_window = out["hl__eligible_n"] == 0
    out["new_52w_highs"] = out["new_52w_highs"].astype(float).mask(no_hl_window)
    out["new_52w_lows"] = out["new_52w_lows"].astype(float).mask(no_hl_window)
    for col in sma_windows:
        out[col] = out.apply(
            lambda r, c=col: (r[f"{c}__above_n"] / r[f"{c}__eligible_n"] * 100.0)
            if r[f"{c}__eligible_n"] else float("nan"),
            axis=1,
        )

    return out[columns].sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    import sys
    from datetime import datetime, timezone

    from research.index_history.manifest import (
        INTERVAL as _INTERVAL,
        SEALED_WINDOW as _SEALED_WINDOW,
        assert_no_sealed_dates,
        load_manifest,
        save_manifest,
        sha256_file,
        upsert_entry,
    )

    HERE = Path(__file__).resolve().parent
    DATA_DIR = HERE / "data"
    MANIFEST_PATH = HERE / "manifest.json"
    PARTS_GLOB = str(Path("/app/research/kite_history/day_2021/part-*.csv.gz"))
    ETF_LIST_PATH = Path("/app/research/sealed/etf_symbols_kite_20260919.csv")
    OUT_CSV = DATA_DIR / "BREADTH_UNIVERSE.csv"

    etf_symbols = load_etf_symbols(ETF_LIST_PATH)
    bars = load_universe_bars(PARTS_GLOB, etf_symbols)
    n_symbols = bars["symbol"].nunique() if not bars.empty else 0
    print(f"universe bars: {len(bars)} rows, {n_symbols} symbols "
          f"(excluded {len(etf_symbols)} ETF symbols from the sealed list)")

    result = compute_breadth(bars)
    assert_no_sealed_dates(result["date"])

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT_CSV, index=False)
    digest = sha256_file(OUT_CSV)

    manifest = load_manifest(MANIFEST_PATH)
    entry = {
        "index_name": "BREADTH_UNIVERSE",
        "instrument_token": None,
        "rows": len(result),
        "first_date": result["date"].iloc[0] if len(result) else None,
        "last_date": result["date"].iloc[-1] if len(result) else None,
        "sha256": digest,
        "source": "derived:kite_history/day_2021",
        "interval": _INTERVAL,
        "excluded_window": list(_SEALED_WINDOW),
        "universe_symbols": int(n_symbols),
        "excluded_etf_symbols": len(etf_symbols),
    }
    manifest = upsert_entry(manifest, "BREADTH_UNIVERSE.csv", entry)
    save_manifest(MANIFEST_PATH, manifest, generated_at=datetime.now(timezone.utc).isoformat())

    print(f"breadth rows: {len(result)}  first={entry['first_date']}  last={entry['last_date']}")
    print(f"wrote {OUT_CSV} sha256={digest[:12]}...")
    sys.exit(0)
