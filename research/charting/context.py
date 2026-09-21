"""Market & sector context — PRD docs/charting.md §15 (Market and Sector Context),
project plan CHART-S29 (market context) / CHART-S30 (sector relative strength) / T09
(benchmark history from index instruments). This is the "package B" data layer for
§15: the raw NIFTY 500 market-index level and per-sector equal-weight index level, on
any given date, point-in-time honest about what it does and does not know.

Scope boundary (resolved up front, so it isn't rediscovered later): §15.1/§15.2 list a
much larger *derived* feature set — benchmark return over 1/5/20/60 sessions, SMA20/
50/200 position, RSI/ADX, market breadth/regime, gap conditions, sector relative
strength/trend/volatility, stock-return-minus-sector-return, sector breadth — and
§15.3 gives those derived features a POSITIVE/NEUTRAL/NEGATIVE/MIXED/UNAVAILABLE
status vocabulary. This module does NOT compute that feature set. It is the raw-data
layer underneath it (the same relationship `research.charting.series` has to
`research.charting.bars`): a later indicator module computes §15.1/§15.2 features from
the series this module exposes. This module's own status vocabulary is therefore the
narrower `STATUS_OK` / `STATUS_UNAVAILABLE` (plain data availability) plus
`lifecycle.DataQualityStatus.PIT_UNVERIFIED` (reused as-is from the existing §9.2
vocabulary for the sector series' point-in-time caveat) — not the §15.3 list, which
belongs to whatever module computes market/sector *regime*.

Two data-integrity rules drive every design choice below:

1. **Never fabricate a value.** No interpolation, no forward-fill, no reindexing onto
   a daily calendar. A date with no row in the underlying source is UNAVAILABLE, full
   stop — including the two real market-index CSVs' own internal gaps (weekends,
   holidays) and, especially, the gap between them.

2. **The sealed 2023-01-01..2024-07-31 out-of-sample test block is off-limits.**
   `.claude/workspace/charting-pattern-engine/spec.md` / `test-plan.md` and
   `docs/ai_research/TPD_PROJECT_STATUS_2026-09-19.md:255` ("Jan 2023 - Jul 2024 can be
   used once") establish this as a fixed, project-wide sealed window, reused across
   multiple studies (see MEMORY: TPD sealed tests, model v5 phases). It is hardcoded
   here as `SEALED_GAP_START`/`SEALED_GAP_END`, NOT derived from wherever these two
   particular market-index files happen to end/start (a future refresh of either file
   must not silently move this boundary), and it is enforced for BOTH market and
   sector queries — even a sector index built from per-symbol bars that happen to
   cover that period (e.g. Kite daily bars, which run continuously from 2021) must not
   surface a value for a date inside this window through this module.

Sector point-in-time gap (unavoidable, not hidden): `research/screener_nr6/
sector_master.csv` carries only TODAY's sector classification. There is no historical
sector-membership data anywhere in this repo's research data, so applying today's
sector to a historical date is a real point-in-time integrity gap — a stock that
changed sector, got added/dropped, or was reclassified is silently mis-bucketed for
any date before that change. Every sector-index value this module produces therefore
carries `pit_status=PIT_UNVERIFIED`; no function here ever drops or hides that field.

Universe boundary: `build_sector_index()` takes a caller-supplied `{symbol: bars}`
mapping — this module does not itself load per-symbol price history. "Each pattern's
universe constituents" is necessarily pattern-specific (already assembled by the
caller via `research.charting.bars.load_all()` + `research.charting.universe`), and
loading the full ~2,900-symbol bar set on every context query would make this module a
heavy, hidden dependency of every lookup. Keeping that assembly out of this module
also means this file has zero coupling to `bars.py`/`universe.py`/`patterns.py`.
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import pandas as pd

from research.charting.lifecycle import DataQualityStatus

# ── Source paths (env-overridable; matches bars.py / universe.py convention) ────

ENV_MARKET_OHLC_PATH = "CHARTING_MARKET_OHLC_PATH"
DEFAULT_MARKET_OHLC_PATH = "/app/research/model_v5/index_p4.csv"

ENV_MARKET_CLOSE_PATH = "CHARTING_MARKET_CLOSE_PATH"
DEFAULT_MARKET_CLOSE_PATH = "/app/research/phase1/nifty500_index_daily.csv"

ENV_SECTOR_MASTER_PATH = "CHARTING_SECTOR_MASTER_PATH"
DEFAULT_SECTOR_MASTER_PATH = "/app/research/screener_nr6/sector_master.csv"

# index_p4.csv stacks three indices under one `index` column (NIFTY 500, NIFTY 50,
# INDIA VIX — verified, ~870 rows each, all sharing the 2019-07-01..2022-12-30 span).
# This is the one filter value the charting engine's market context cares about.
MARKET_INDEX_NAME = "NIFTY 500"

SOURCE_OHLC_FULL = "OHLC_FULL"
SOURCE_CLOSE_ONLY = "CLOSE_ONLY"

# Project-wide sealed out-of-sample test block — see module docstring rule 2. Fixed
# calendar constants, deliberately NOT derived from loaded file coverage.
SEALED_GAP_START = pd.Timestamp("2023-01-01")
SEALED_GAP_END = pd.Timestamp("2024-07-31")

STATUS_OK = "OK"
STATUS_UNAVAILABLE = "UNAVAILABLE"

REASON_SEALED_GAP = "SEALED_GAP"
REASON_BEFORE_COVERAGE = "BEFORE_COVERAGE"
REASON_AFTER_COVERAGE = "AFTER_COVERAGE"
REASON_NO_DATA_FOR_DATE = "NO_DATA_FOR_DATE"
REASON_UNKNOWN_SECTOR = "UNKNOWN_SECTOR"
REASON_NO_SECTOR_RESOLVABLE = "NO_SECTOR_RESOLVABLE"


def _resolve_path(env_var: str, default: str, path: str | Path | None) -> Path:
    if path is not None:
        return Path(path)
    return Path(os.environ.get(env_var, default))


def market_ohlc_path(path: str | Path | None = None) -> Path:
    """Resolve the OHLC-shaped market-index source path: explicit arg, else env
    override, else the default (index_p4.csv)."""
    return _resolve_path(ENV_MARKET_OHLC_PATH, DEFAULT_MARKET_OHLC_PATH, path)


def market_close_path(path: str | Path | None = None) -> Path:
    """Resolve the close-only market-index source path: explicit arg, else env
    override, else the default (nifty500_index_daily.csv)."""
    return _resolve_path(ENV_MARKET_CLOSE_PATH, DEFAULT_MARKET_CLOSE_PATH, path)


def sector_master_path(path: str | Path | None = None) -> Path:
    """Resolve the sector-master source path: explicit arg, else env override, else
    the default (sector_master.csv)."""
    return _resolve_path(ENV_SECTOR_MASTER_PATH, DEFAULT_SECTOR_MASTER_PATH, path)


def is_sealed_gap(date) -> bool:
    """True if `date` falls in the project-wide sealed out-of-sample test block
    (2023-01-01..2024-07-31 inclusive — see module docstring, rule 2). A fixed
    calendar rule, independent of which market-index files happen to be loaded."""
    ts = pd.Timestamp(date).normalize()
    return SEALED_GAP_START <= ts <= SEALED_GAP_END


def _normalize_dates(s: pd.Series) -> pd.Series:
    """Parse a date column to naive, midnight-normalized timestamps. Source B's dates
    carry an IST (+05:30) offset; the offset is dropped (not converted) so the stored
    calendar date matches the source's own wall-clock date, matching source A's plain
    (already tz-naive) dates."""
    parsed = pd.to_datetime(s)
    if getattr(parsed.dt, "tz", None) is not None:
        parsed = parsed.dt.tz_localize(None)
    return parsed.dt.normalize()


# ── Market index ─────────────────────────────────────────────────────────────


def load_market_index_ohlc(path: str | Path | None = None) -> pd.DataFrame:
    """Load the full-OHLC market-index source (index_p4.csv), filtered to
    `MARKET_INDEX_NAME`. Verified real range: 2019-07-01..2022-12-30 (870 rows),
    matching the expected range exactly. Raises ValueError if the filtered rows
    contain a duplicate date (would indicate the source changed shape)."""
    p = market_ohlc_path(path)
    df = pd.read_csv(p)
    df = df[df["index"] == MARKET_INDEX_NAME].copy()
    df["date"] = _normalize_dates(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    if df["date"].duplicated().any():
        raise ValueError(f"{p}: duplicate dates for index={MARKET_INDEX_NAME!r} after filtering")
    df["source"] = SOURCE_OHLC_FULL
    return df[["date", "open", "high", "low", "close", "source"]]


def load_market_index_close(path: str | Path | None = None) -> pd.DataFrame:
    """Load the close-only market-index source (nifty500_index_daily.csv). Verified
    real range: 2024-08-01..2026-09-18 (530 rows), matching the expected range
    exactly. `open`/`high`/`low` are NaN throughout (never fabricated from `close`)."""
    p = market_close_path(path)
    df = pd.read_csv(p)
    df["date"] = _normalize_dates(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    if df["date"].duplicated().any():
        raise ValueError(f"{p}: duplicate dates")
    for col in ("open", "high", "low"):
        df[col] = float("nan")
    df["source"] = SOURCE_CLOSE_ONLY
    return df[["date", "open", "high", "low", "close", "source"]]


def load_market_index(
    ohlc_path: str | Path | None = None, close_path: str | Path | None = None
) -> pd.DataFrame:
    """The merged NIFTY 500 market-index series this module exposes: source A's
    full-OHLC range concatenated with source B's close-only range, columns `date,
    open, high, low, close, source`, ascending, unique dates.

    NOT reindexed onto a daily calendar and NOT forward-filled: a date with no row in
    either source (a non-trading day, or the sealed gap between the two files) simply
    has no row here. `market_value_at()` is what turns "no row" into an explicit
    UNAVAILABLE status; this function never guesses a value.

    Raises ValueError if the two sources' date ranges overlap (they don't, as of the
    verified real files — 2022-12-30 vs 2024-08-01 — but overlap would mean silently
    picking one source over the other, which this function refuses to do).
    """
    a = load_market_index_ohlc(ohlc_path)
    b = load_market_index_close(close_path)
    overlap = set(a["date"]) & set(b["date"])
    if overlap:
        sample = sorted(overlap)[:3]
        raise ValueError(
            f"market index sources overlap on {len(overlap)} date(s), e.g. {sample} "
            "— refusing to silently prefer one source over the other"
        )
    return pd.concat([a, b], ignore_index=True).sort_values("date").reset_index(drop=True)


@dataclass(frozen=True)
class MarketContext:
    """Result of a market-index lookup for one date (see `market_value_at`).
    `status` is `STATUS_OK` or `STATUS_UNAVAILABLE`. `close`/`source` are populated
    only when `status == STATUS_OK`. `reason` (one of the `REASON_*` constants) is
    populated only when `status == STATUS_UNAVAILABLE`.
    """

    date: pd.Timestamp
    status: str
    close: float | None = None
    source: str | None = None
    reason: str | None = None


def market_value_at(date, market_df: pd.DataFrame | None = None) -> MarketContext:
    """Look up the NIFTY 500 market-index close for one date.

    `market_df` defaults to `load_market_index()` (loaded fresh from the real source
    files) when omitted; a caller doing many lookups should load once and pass it in.

    Returns `STATUS_UNAVAILABLE` (never an interpolated/forward-filled value) when:
      - `date` falls in the sealed 2023-01-01..2024-07-31 OOS block -> `REASON_SEALED_GAP`;
      - `date` is before the earliest loaded row -> `REASON_BEFORE_COVERAGE`;
      - `date` is after the latest loaded row -> `REASON_AFTER_COVERAGE`;
      - `date` is inside the loaded coverage span but has no row (e.g. a weekend or
        market holiday) -> `REASON_NO_DATA_FOR_DATE`.
    """
    ts = pd.Timestamp(date).normalize()
    if is_sealed_gap(ts):
        return MarketContext(date=ts, status=STATUS_UNAVAILABLE, reason=REASON_SEALED_GAP)

    if market_df is None:
        market_df = load_market_index()

    if market_df.empty:
        return MarketContext(date=ts, status=STATUS_UNAVAILABLE, reason=REASON_NO_DATA_FOR_DATE)

    lo, hi = market_df["date"].min(), market_df["date"].max()
    if ts < lo:
        return MarketContext(date=ts, status=STATUS_UNAVAILABLE, reason=REASON_BEFORE_COVERAGE)
    if ts > hi:
        return MarketContext(date=ts, status=STATUS_UNAVAILABLE, reason=REASON_AFTER_COVERAGE)

    row = market_df.loc[market_df["date"] == ts]
    if row.empty:
        return MarketContext(date=ts, status=STATUS_UNAVAILABLE, reason=REASON_NO_DATA_FOR_DATE)

    r = row.iloc[0]
    return MarketContext(date=ts, status=STATUS_OK, close=float(r["close"]), source=str(r["source"]))


# ── Sector master / mapping ──────────────────────────────────────────────────


def load_sector_map(path: str | Path | None = None) -> dict[str, str]:
    """symbol -> TODAY's sector, from sector_master.csv (see module docstring's PIT
    caveat before using this for anything historical).

    Rows with a blank `sector` field are excluded from the returned mapping: a real
    data-quality gap in the source file (verified: 1,625 of 2,619 rows, ~62%, have an
    empty `sector`) — see `sector_master_stats()` to inspect the gap directly rather
    than trusting a number here that may drift as the file is updated.
    """
    p = sector_master_path(path)
    mapping: dict[str, str] = {}
    with open(p, newline="") as f:
        for row in csv.DictReader(f):
            symbol = (row.get("symbol") or "").strip()
            sector = (row.get("sector") or "").strip()
            if symbol and sector:
                mapping[symbol] = sector
    return mapping


@dataclass(frozen=True)
class SectorMasterStats:
    total_rows: int
    mapped: int
    blank_sector: int


def sector_master_stats(path: str | Path | None = None) -> SectorMasterStats:
    """Diagnostic counts for sector_master.csv — surfaces the blank-sector data gap
    instead of leaving it invisible inside `load_sector_map()`'s silent filtering."""
    p = sector_master_path(path)
    total = 0
    blank = 0
    with open(p, newline="") as f:
        for row in csv.DictReader(f):
            total += 1
            if not (row.get("sector") or "").strip():
                blank += 1
    return SectorMasterStats(total_rows=total, mapped=total - blank, blank_sector=blank)


def sector_of(symbol: str, sector_map: Mapping[str, str] | None = None) -> str | None:
    """TODAY's sector for `symbol`, or None if unmapped or blank in sector_master.csv.
    `sector_map` defaults to `load_sector_map()` when omitted."""
    if sector_map is None:
        sector_map = load_sector_map()
    return sector_map.get(symbol)


# ── Sector index (CHART-S30) ─────────────────────────────────────────────────


def _require_columns(df: pd.DataFrame, cols, *, symbol: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"bars frame for {symbol!r} is missing required column(s): {missing}")


def build_sector_index(
    symbol_bars: Mapping[str, pd.DataFrame],
    sector_map: Mapping[str, str],
    *,
    base_value: float = 100.0,
) -> dict[str, pd.DataFrame]:
    """Equal-weight sector index, per sector, per date (CHART-S30), built from a
    caller-supplied universe of `{symbol: bars}` pairs — e.g. one pattern's universe
    constituents, already loaded via `research.charting.bars` and filtered via
    `research.charting.universe`. This function does not load bars itself (see module
    docstring, "Universe boundary").

    Method: each constituent's `close` series is independently normalized to
    `base_value` at ITS OWN first available row (not a shared universe start date — a
    constituent with a shorter history still contributes from its own first bar
    instead of requiring back-filled history nobody has). A symbol's rows are sorted
    by date and de-duplicated (keep last) before normalizing, since bars.py preserves
    duplicate dates verbatim and this function cannot average two conflicting values
    for the same symbol on the same date. The sector index value for a date is the
    plain arithmetic mean of every constituent's normalized value that has a row on
    that date; `n_constituents` records how many contributed.

    PIT integrity (read before using this — see module docstring for the full
    rationale): `sector_map` is expected to be TODAY's classification. This function
    has no access to historical sector membership, so every returned row carries
    `pit_status=DataQualityStatus.PIT_UNVERIFIED.value` — never drop or hide this
    column downstream.

    Returns `{sector_name: DataFrame[date, value, n_constituents, pit_status]}`, one
    frame per sector actually represented among `symbol_bars`' keys (via
    `sector_map`), ascending by date. A symbol absent from `sector_map`, or with an
    empty bars frame, is silently skipped (not an error — a pattern's universe will
    routinely include symbols sector_master.csv has no sector for).
    """
    by_sector: dict[str, list[pd.Series]] = {}
    for symbol, df in symbol_bars.items():
        sector = sector_map.get(symbol)
        if not sector or df is None or df.empty:
            continue
        _require_columns(df, ("date", "close"), symbol=symbol)

        s = df[["date", "close"]].dropna(subset=["close"])
        s = s.sort_values("date").drop_duplicates(subset="date", keep="last")
        if s.empty:
            continue

        first_close = s["close"].iloc[0]
        if pd.isna(first_close) or first_close == 0:
            continue

        normalized = s.set_index("date")["close"] / first_close * base_value
        by_sector.setdefault(sector, []).append(normalized)

    result: dict[str, pd.DataFrame] = {}
    for sector, series_list in by_sector.items():
        combined = pd.concat(series_list, axis=1)
        value = combined.mean(axis=1, skipna=True)
        n_constituents = combined.notna().sum(axis=1)
        out = pd.DataFrame({
            "date": value.index,
            "value": value.to_numpy(),
            "n_constituents": n_constituents.to_numpy(),
            "pit_status": DataQualityStatus.PIT_UNVERIFIED.value,
        })
        result[sector] = out.sort_values("date").reset_index(drop=True)
    return result


@dataclass(frozen=True)
class SectorContext:
    """Result of a sector-index lookup for one date (see `sector_value_at`). `status`
    is `STATUS_OK` or `STATUS_UNAVAILABLE`. `value`/`n_constituents`/`pit_status` are
    populated only when `status == STATUS_OK` — `pit_status` is always
    `DataQualityStatus.PIT_UNVERIFIED.value` on success (see module docstring).
    `reason` (one of the `REASON_*` constants) is populated only when
    `status == STATUS_UNAVAILABLE`.
    """

    date: pd.Timestamp
    status: str
    sector: str | None = None
    value: float | None = None
    n_constituents: int | None = None
    pit_status: str | None = None
    reason: str | None = None


def sector_value_at(
    date, sector: str, sector_indices: Mapping[str, pd.DataFrame]
) -> SectorContext:
    """Look up one sector's equal-weight index value for one date from an
    already-built `sector_indices` map (`build_sector_index()`'s return value).

    Always `STATUS_UNAVAILABLE` (`REASON_SEALED_GAP`) for the sealed
    2023-01-01..2024-07-31 OOS block, regardless of whether the caller's underlying
    per-symbol bars happen to cover that period — see module docstring, rule 2.
    `STATUS_UNAVAILABLE` (`REASON_UNKNOWN_SECTOR`) if `sector` is not a key of
    `sector_indices` (or that sector's frame is empty); (`REASON_NO_DATA_FOR_DATE`) if
    the sector exists but has no row for `date` (no constituent had data that day).
    """
    ts = pd.Timestamp(date).normalize()
    if is_sealed_gap(ts):
        return SectorContext(date=ts, status=STATUS_UNAVAILABLE, sector=sector, reason=REASON_SEALED_GAP)

    frame = sector_indices.get(sector)
    if frame is None or frame.empty:
        return SectorContext(date=ts, status=STATUS_UNAVAILABLE, sector=sector, reason=REASON_UNKNOWN_SECTOR)

    row = frame.loc[frame["date"] == ts]
    if row.empty:
        return SectorContext(date=ts, status=STATUS_UNAVAILABLE, sector=sector, reason=REASON_NO_DATA_FOR_DATE)

    r = row.iloc[0]
    return SectorContext(
        date=ts,
        status=STATUS_OK,
        sector=sector,
        value=float(r["value"]),
        n_constituents=int(r["n_constituents"]),
        pit_status=str(r["pit_status"]),
    )


# ── Combined public query interface (CHART-S29/S30/T09) ─────────────────────


@dataclass(frozen=True)
class ContextResult:
    """Return shape of `get_context()` — the public market + sector context query
    other charting-engine modules call. `market` and `sector` are independently a
    `MarketContext` / `SectorContext`; each carries its own OK/UNAVAILABLE status, so
    a sector-resolution failure never affects the market result and vice versa."""

    date: pd.Timestamp
    market: MarketContext
    sector: SectorContext


def get_context(
    date,
    *,
    market_df: pd.DataFrame | None = None,
    symbol: str | None = None,
    sector: str | None = None,
    sector_indices: Mapping[str, pd.DataFrame] | None = None,
    sector_map: Mapping[str, str] | None = None,
) -> ContextResult:
    """Point-in-time market & sector context for one date — the public query
    interface CHART-S29/S30/T09 exist to provide; other modules (pattern geometry,
    §34 early scoring, a later §15 indicator layer) call this rather than re-deriving
    index lookups themselves.

    Parameters:
      date: the calendar date to look up.
      market_df: a pre-loaded merged market index (`load_market_index()`'s return
        shape). Defaults to loading fresh from the real source files when omitted —
        a caller doing many lookups should load once and pass it in.
      symbol / sector: how to resolve which sector to look up. An explicit `sector=`
        is used as-is; otherwise, if `symbol=` is given, its sector is resolved via
        `sector_map` (default: `load_sector_map()`, TODAY's classification — see
        module docstring's PIT caveat). If neither resolves to a sector, the sector
        half of the result is `STATUS_UNAVAILABLE` (`REASON_NO_SECTOR_RESOLVABLE`).
      sector_indices: a pre-built `build_sector_index()` map. Required to get an
        actual sector value — this function does not build a sector index itself
        (that needs a specific pattern's universe of per-symbol bars, which only the
        caller has). Omitting it (with a sector resolved) yields
        `STATUS_UNAVAILABLE` (`REASON_UNKNOWN_SECTOR`).
      sector_map: symbol -> sector mapping for resolving `symbol` (see above).

    Returns a `ContextResult`. Never raises for a date/sector it cannot resolve —
    every failure mode is an explicit `STATUS_UNAVAILABLE` with a `reason`.
    """
    ts = pd.Timestamp(date).normalize()
    market = market_value_at(ts, market_df)

    resolved_sector = sector
    if resolved_sector is None and symbol is not None:
        resolved_sector = sector_of(symbol, sector_map)

    if resolved_sector is None:
        sector_result = SectorContext(date=ts, status=STATUS_UNAVAILABLE, reason=REASON_NO_SECTOR_RESOLVABLE)
    elif sector_indices is None:
        sector_result = SectorContext(
            date=ts, status=STATUS_UNAVAILABLE, sector=resolved_sector, reason=REASON_UNKNOWN_SECTOR
        )
    else:
        sector_result = sector_value_at(ts, resolved_sector, sector_indices)

    return ContextResult(date=ts, market=market, sector=sector_result)
