"""NSE equity allowlist — filters ETFs / REITs / InvITs out of the universe.

The bhavcopy ships every cash-segment instrument (EQ + BE), which includes
~440 ETFs (NIFTYBEES, BANKBEES, AMC-branded variants like HDFCNEXT50 /
AXISGOLD) and a handful of REITs. Those are not candidates for the
positional engine — it is built around equity price action.

We use NSE's official equity-listing CSV (data/equity_list.csv) as the
allowlist. Every row carries an `INE*` ISIN — the marker for equity. ETFs
use `INF*` ISINs and are absent from this file.

Usage:
    from services.positional_engine import equity_universe
    if equity_universe.is_equity("NIFTYBEES"):  # → False
        ...
"""
from __future__ import annotations

import csv
import logging
import os
from typing import Optional, Set

logger = logging.getLogger(__name__)

# Resolves to /app/backend/data/equity_list.csv in this repo layout.
_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "equity_list.csv",
)

_allowlist: Optional[Set[str]] = None


def _load(path: str = _DEFAULT_PATH) -> Set[str]:
    """Read the NSE equity-listing CSV into an upper-cased symbol set.

    Best-effort: if the file is missing the loader returns an empty set
    and the filter is a no-op (callers fall back to the unfiltered
    universe rather than blowing up).
    """
    out: Set[str] = set()
    if not os.path.exists(path):
        logger.warning("equity_universe: %s missing — filter is a no-op", path)
        return out
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return out
        # First column is SYMBOL in the official NSE CSV.
        for row in reader:
            if not row:
                continue
            sym = (row[0] or "").strip().upper()
            if sym:
                out.add(sym)
    logger.info("equity_universe: loaded %d equity symbols", len(out))
    return out


def get_allowlist() -> Set[str]:
    global _allowlist
    if _allowlist is None:
        _allowlist = _load()
    return _allowlist


def is_equity(symbol: str) -> bool:
    """True if `symbol` is on the NSE equity-listing CSV. Falls back to True
    when the CSV is missing so the engine doesn't go silent in environments
    where the allowlist hasn't been seeded yet."""
    al = get_allowlist()
    if not al:
        return True   # no allowlist → don't filter anything
    return symbol.upper().strip() in al


def filter_equities(symbols):
    """Return only the symbols that are on the equity allowlist."""
    al = get_allowlist()
    if not al:
        return list(symbols)
    return [s for s in symbols if s.upper().strip() in al]


def reload() -> int:
    """Force-reload the allowlist. Returns the new size. Used by tests
    and admin endpoints when the CSV is updated at runtime."""
    global _allowlist
    _allowlist = _load()
    return len(_allowlist)
