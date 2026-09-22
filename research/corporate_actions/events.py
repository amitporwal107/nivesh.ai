"""Demerger event list: dataclass + loader for data/demergers.csv.

PRD §37.5: "Demergers are a corporate-action regime break ... Sessions T-5..T+5 are
excluded from ordinary validation; pre- and post-demerger histories are separate regimes,
never spliced." The window is anchored on the ex_date (see module docstring in
research/corporate_actions/__init__.py and regime.py) -- record_date is stored alongside
because NSE's own feed carries both and they occasionally differ by a day, but §37.5 says
"around the ex-date", so ex_date is what regime.py anchors on.

An event is usable by regime.py (i.e. actually causes a regime break) only when both:
  category == "DEMERGER"   -- excludes rows NSE buckets under the same action_type whose
                               `subject` describes a different action (see below)
  verified == True          -- a source this session actually read confirms the event

`category == "NCRPS_BONUS_SCHEME"` rows (RADIOCITY, TVSMOTOR, SIYSIL x2, TVSHLTD) are kept
in the CSV for transparency -- NSE's corporate-action feed files them under the same
action_type as demergers -- but they are a "Scheme of Arrangement" issuing Non-Convertible
Redeemable Preference Shares, not a business separation, and the Kite bars around each show
no meaningful open-vs-prior-close discontinuity (gap_pct_kite column, all under 2%). They
are marked verified=False with a review_reason rather than silently included or dropped.
"""
from __future__ import annotations

import csv
import functools
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

HERE = Path(__file__).resolve().parent
DEFAULT_DATA_PATH = HERE / "data" / "demergers.csv"

CSV_COLUMNS = (
    "symbol", "ex_date", "date_type", "record_date", "category", "resulting_entity",
    "resulting_symbol", "source", "source_reference", "retrieved_at", "verified",
    "gap_pct_kite", "review_reason",
)

CATEGORIES = ("DEMERGER", "NCRPS_BONUS_SCHEME")


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _parse_optional_date(s: str) -> date | None:
    s = (s or "").strip()
    return _parse_date(s) if s else None


def _parse_bool(s: str) -> bool:
    return str(s).strip().lower() == "true"


def _parse_optional_float(s: str) -> float | None:
    s = (s or "").strip()
    return float(s) if s else None


@dataclass(frozen=True)
class DemergerEvent:
    symbol: str
    ex_date: date
    date_type: str  # always "EX_DATE" in this dataset -- see module docstring
    record_date: date | None
    category: str  # one of CATEGORIES
    resulting_entity: str  # "" if not identified from a read source
    resulting_symbol: str  # "" if not identified from a read source
    source: str
    source_reference: str
    retrieved_at: str  # ISO8601 UTC
    verified: bool
    gap_pct_kite: float | None  # open-vs-prior-close %, computed from Kite bars; None if no bars
    review_reason: str  # "" when verified and category == DEMERGER

    def is_confirmed_demerger(self) -> bool:
        return self.verified and self.category == "DEMERGER"


def _row_to_event(row: dict) -> DemergerEvent:
    return DemergerEvent(
        symbol=row["symbol"],
        ex_date=_parse_date(row["ex_date"]),
        date_type=row["date_type"],
        record_date=_parse_optional_date(row["record_date"]),
        category=row["category"],
        resulting_entity=row.get("resulting_entity", "") or "",
        resulting_symbol=row.get("resulting_symbol", "") or "",
        source=row["source"],
        source_reference=row["source_reference"],
        retrieved_at=row["retrieved_at"],
        verified=_parse_bool(row["verified"]),
        gap_pct_kite=_parse_optional_float(row.get("gap_pct_kite", "")),
        review_reason=row.get("review_reason", "") or "",
    )


def event_to_row(event: DemergerEvent) -> dict:
    """Inverse of _row_to_event -- used by the build script to write the CSV."""
    return {
        "symbol": event.symbol,
        "ex_date": event.ex_date.isoformat(),
        "date_type": event.date_type,
        "record_date": event.record_date.isoformat() if event.record_date else "",
        "category": event.category,
        "resulting_entity": event.resulting_entity,
        "resulting_symbol": event.resulting_symbol,
        "source": event.source,
        "source_reference": event.source_reference,
        "retrieved_at": event.retrieved_at,
        "verified": "true" if event.verified else "false",
        "gap_pct_kite": "" if event.gap_pct_kite is None else f"{event.gap_pct_kite:.4f}",
        "review_reason": event.review_reason,
    }


def load_events(path: str | Path | None = None) -> tuple[DemergerEvent, ...]:
    """Every row in demergers.csv, typed. Raises FileNotFoundError if the CSV has not
    been generated yet (see build_demerger_events.py)."""
    p = Path(path) if path is not None else DEFAULT_DATA_PATH
    with open(p, newline="") as f:
        reader = csv.DictReader(f)
        return tuple(_row_to_event(row) for row in reader)


@functools.lru_cache(maxsize=1)
def _cached_default_events() -> tuple[DemergerEvent, ...]:
    return load_events()


def events_for_symbol(
    symbol: str,
    events: Iterable[DemergerEvent] | None = None,
    *,
    only_confirmed_demergers: bool = True,
) -> tuple[DemergerEvent, ...]:
    """Every event for `symbol`, sorted ascending by ex_date. Defaults to the cached
    on-disk demergers.csv when `events` is not supplied. `only_confirmed_demergers=True`
    (the default, and what regime.py always uses) keeps only category=="DEMERGER" and
    verified==True rows -- an unverified candidate or an NCRPS bonus-scheme row never
    causes a regime break on its own."""
    pool = _cached_default_events() if events is None else tuple(events)
    matches = [e for e in pool if e.symbol == symbol]
    if only_confirmed_demergers:
        matches = [e for e in matches if e.is_confirmed_demerger()]
    return tuple(sorted(matches, key=lambda e: e.ex_date))
