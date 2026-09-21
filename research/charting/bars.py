"""Load Kite daily OHLCV bars — research/charting data-loading layer.

Source: gzip CSV parts written by `research/kite_history/pull_daily.py`, one row per
(symbol, date), columns `symbol,instrument_token,date,open,high,low,close,volume,source_version`.
Some parts are header-only (a fetch run in which every remaining symbol had already been
marked OK/EMPTY, so nothing new was written that run — see pull_daily.py's `done` skip set).

Directory is configurable via env `CHARTING_KITE_DAILY_DIR` (default: the absolute path
pull_daily.py writes to, /app/research/kite_history/day_2021).

Design decision — row order is NOT re-sorted here. Kite's historical API is fetched in
chronological windows and pull_daily.py appends rows in fetch order, so real data already
arrives ascending by date (verified against the real files: every symbol's rows are
contiguous within its part file and already non-decreasing by date). This loader trusts
and preserves that source order rather than imposing a sort, because a silent re-sort
would erase the one signal that lets `research.charting.validate` detect an OUT_OF_ORDER
bar (PRD §9.1) — sorting rows back into order IS a fix, and fixing bad rows is
validate.py's job, not this module's. Duplicate dates are likewise preserved verbatim
(see DUPLICATE_TIMESTAMP in validate.py) rather than deduplicated here — a real example
exists in the data: symbol CLEDUCATE has two rows each for 2023-11-01..2023-11-06's
Nov-1..Nov-6 dates in the source file.

Do not silently drop or fix bad rows in this module. That is validate.py's job.
"""
from __future__ import annotations

import functools
import gzip
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pandas as pd

from research.charting.config import BARS_COLUMNS

ENV_VAR = "CHARTING_KITE_DAILY_DIR"
DEFAULT_KITE_DAILY_DIR = "/app/research/kite_history/day_2021"

# Columns present in the source CSV parts (superset of BARS_COLUMNS).
_RAW_COLUMNS = ("symbol", "instrument_token", "date", "open", "high", "low", "close", "volume", "source_version")
_NUMERIC_COLUMNS = ("open", "high", "low", "close", "volume")


def source_dir() -> Path:
    """Resolve the configured Kite daily-bars directory: env override, else the default
    pull_daily.py writes to."""
    return Path(os.environ.get(ENV_VAR, DEFAULT_KITE_DAILY_DIR))


def _resolve(directory: str | Path | None) -> Path:
    return Path(directory) if directory is not None else source_dir()


def _part_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("part-*.csv.gz"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_part(path: Path) -> pd.DataFrame:
    """Read one gzip CSV part verbatim: no filtering, no sort, no dedup. A header-only
    part yields an empty (but correctly typed) frame."""
    with gzip.open(path, "rt", newline="") as f:
        df = pd.read_csv(f, dtype={"symbol": str, "source_version": str}, usecols=list(_RAW_COLUMNS))
    for col in _NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="raise")
    df["date"] = pd.to_datetime(df["date"], errors="raise")
    return df[list(_RAW_COLUMNS)]


@functools.lru_cache(maxsize=8)
def _load_raw_concat(directory_str: str) -> pd.DataFrame:
    """Every part file in `directory_str`, concatenated, symbol column intact, in file-then-
    row order. Cached per resolved directory so a research script that calls load_symbol
    (or load_all) many times against the same real ~230MB source doesn't re-read and
    re-parse gzip on every call.
    """
    d = Path(directory_str)
    frames = [raw for raw in (_read_part(p) for p in _part_files(d)) if not raw.empty]
    if not frames:
        return pd.DataFrame(columns=list(_RAW_COLUMNS))
    return pd.concat(frames, ignore_index=True)


def _select_bars_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df.loc[:, list(BARS_COLUMNS)].reset_index(drop=True)


def load_symbol(symbol: str, directory: str | Path | None = None) -> pd.DataFrame:
    """Every raw row for one symbol, in source order (see module docstring), typed to
    exactly BARS_COLUMNS. Duplicate dates, gaps and any other bad rows are preserved
    verbatim; research.charting.validate is where they get flagged. Returns an empty
    (but correctly typed) frame if the symbol is not present under `directory`.
    """
    d = _resolve(directory)
    raw = _load_raw_concat(str(d))
    match = raw.loc[raw["symbol"] == symbol]
    return _select_bars_columns(match)


def load_all(directory: str | Path | None = None) -> Iterator[tuple[str, pd.DataFrame]]:
    """Iterate (symbol, bars_frame) for every symbol found under `directory`, each frame
    typed to exactly BARS_COLUMNS in source row order, symbols visited in sorted order.
    A generator (not a dict) so the whole universe never has to be resident as N separate
    DataFrames at once; callers that want a dict can do `dict(load_all())`.
    """
    d = _resolve(directory)
    raw = _load_raw_concat(str(d))
    if raw.empty:
        return
    for symbol, group in raw.groupby("symbol", sort=True):
        yield str(symbol), _select_bars_columns(group)


@dataclass(frozen=True)
class PartFileProvenance:
    path: str
    sha256: str
    row_count: int  # data rows, excluding the header
    source_versions: tuple[str, ...]


@dataclass(frozen=True)
class LoadProvenance:
    """PRD §32.10 provenance manifest for a load of the Kite daily-bars directory:
    source directory, every part file read (with its SHA-256 and row count), the total
    row count and distinct symbol count, and every source_version value seen.
    """
    source_dir: str
    files: tuple[PartFileProvenance, ...]
    total_row_count: int
    symbol_count: int
    source_versions: tuple[str, ...]


def provenance(directory: str | Path | None = None) -> LoadProvenance:
    """Provenance metadata for every part file in `directory` (PRD §32.10). Independent
    of load_symbol/load_all (reads each file's own bytes for its hash) so a caller can
    record the manifest once per run alongside whatever subset of symbols it actually used.
    """
    d = _resolve(directory)
    files: list[PartFileProvenance] = []
    total_rows = 0
    versions: set[str] = set()
    symbols: set[str] = set()
    for p in _part_files(d):
        raw = _read_part(p)
        row_count = len(raw)
        file_versions = tuple(sorted(raw["source_version"].dropna().unique().tolist()))
        files.append(PartFileProvenance(path=str(p), sha256=_sha256(p), row_count=row_count, source_versions=file_versions))
        total_rows += row_count
        versions.update(file_versions)
        symbols.update(raw["symbol"].unique().tolist())
    return LoadProvenance(
        source_dir=str(d),
        files=tuple(files),
        total_row_count=total_rows,
        symbol_count=len(symbols),
        source_versions=tuple(sorted(versions)),
    )
