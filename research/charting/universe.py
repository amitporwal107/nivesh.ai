"""v1 research universe selection.

Rule (owner-approved v1): a symbol is IN the research universe iff it has >= min_bars
rows AND is not on the sealed ETF list AND (if a coverage gate is configured) does not
exceed the configured maximum number of interior calendar gaps.

The sealed ETF list (`/app/research/sealed/etf_symbols_kite_20260919.csv`, first column =
symbol, configurable via env `CHARTING_ETF_LIST`) is mandatory for ETF exclusion. A
name-based "ETF"/"BEES" substring filter is NOT an acceptable substitute: of the 456
symbols on the sealed list, only 103 contain "ETF" or "BEES" in their trading symbol —
353 (e.g. ABGSEC, ALPHA, BANKBETA) do not, and a substring filter would leak them into
the >=250-bar set (data-availability.md, Finding 1).
"""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Collection, Iterable

import pandas as pd

DEFAULT_ETF_LIST_PATH = "/app/research/sealed/etf_symbols_kite_20260919.csv"
ENV_ETF_LIST = "CHARTING_ETF_LIST"

MIN_BARS_DEFAULT = 250

EXCLUSION_REASONS = ("ETF", "INSUFFICIENT_BARS", "COVERAGE_GAP_TOO_LARGE")


def etf_list_path() -> Path:
    """Resolve the configured sealed ETF list path: env override, else the default."""
    return Path(os.environ.get(ENV_ETF_LIST, DEFAULT_ETF_LIST_PATH))


def load_etf_symbols(path: str | Path | None = None) -> frozenset[str]:
    """The sealed ETF list, first column, header-less, one symbol per line. Not built
    from a name pattern — see module docstring for why that would silently under-exclude.
    """
    p = Path(path) if path is not None else etf_list_path()
    symbols: set[str] = set()
    with open(p, newline="") as f:
        for row in csv.reader(f):
            if not row:
                continue
            symbol = row[0].strip()
            if symbol:
                symbols.add(symbol)
    return frozenset(symbols)


@dataclass(frozen=True)
class ExclusionReason:
    symbol: str
    reason: str  # one of EXCLUSION_REASONS
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class UniverseResult:
    included: tuple[str, ...]
    excluded: tuple[ExclusionReason, ...]

    def exclusion_reasons_for(self, symbol: str) -> tuple[ExclusionReason, ...]:
        """Every reason `symbol` was excluded (a symbol can fail more than one gate)."""
        return tuple(r for r in self.excluded if r.symbol == symbol)

    def excluded_symbols(self) -> frozenset[str]:
        return frozenset(r.symbol for r in self.excluded)


def build_universe(
    symbol_frames: Iterable[tuple[str, pd.DataFrame]],
    *,
    etf_symbols: frozenset[str] | None = None,
    min_bars: int = MIN_BARS_DEFAULT,
    max_missing_dates: int | None = None,
    calendar: Collection | None = None,
) -> UniverseResult:
    """Build the v1 research universe from (symbol, bars_frame) pairs, e.g.
    `research.charting.bars.load_all()`.

    Gates:
    - min_bars: row count (bars.py preserves duplicates verbatim, so this counts raw
      rows, matching how data-availability.md's "bars per symbol" was counted).
    - etf_symbols: sealed-list exclusion (see module docstring). Defaults to
      load_etf_symbols() if not supplied.
    - max_missing_dates + calendar: OPTIONAL minimum-coverage gate. When both are given,
      a symbol whose interior gap count (calendar dates strictly within
      [its first date, its last date] that it doesn't have — see
      research.charting.validate.build_trading_calendar / _check_missing_candle for the
      same "interior only" definition) exceeds max_missing_dates is excluded. Disabled
      (no coverage exclusions) when either is None — this is a new rule added for v1 with
      no independently-verified expected count yet, unlike min_bars/etf_symbols.

    A symbol can fail more than one gate; every failing gate is reported, not just the
    first. `included` is sorted; `excluded` preserves gate-check order per symbol.
    """
    if etf_symbols is None:
        etf_symbols = load_etf_symbols()
    calendar_set = set(calendar) if calendar is not None else None

    included: list[str] = []
    excluded: list[ExclusionReason] = []
    for symbol, df in symbol_frames:
        reasons: list[ExclusionReason] = []

        if symbol in etf_symbols:
            reasons.append(ExclusionReason(symbol, "ETF"))

        n = len(df)
        if n < min_bars:
            reasons.append(ExclusionReason(symbol, "INSUFFICIENT_BARS", {"bars": n, "minimum": min_bars}))

        if max_missing_dates is not None and calendar_set is not None and n > 0:
            lo, hi = df["date"].min(), df["date"].max()
            expected = {d for d in calendar_set if lo <= d <= hi}
            missing = len(expected - set(df["date"].tolist()))
            if missing > max_missing_dates:
                reasons.append(ExclusionReason(
                    symbol, "COVERAGE_GAP_TOO_LARGE", {"missing_dates": missing, "maximum": max_missing_dates},
                ))

        if reasons:
            excluded.extend(reasons)
        else:
            included.append(symbol)

    return UniverseResult(included=tuple(sorted(included)), excluded=tuple(excluded))
