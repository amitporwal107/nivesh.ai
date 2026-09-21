"""Versioned instrument identity resolution — CHART-S07, with a CHART-S05-adjacent
provenance summary.

WHAT THIS MODULE IS FOR (and what it is NOT)
---------------------------------------------
`research.charting.universe` answers "does this symbol belong in the v1 research
universe RIGHT NOW" — ETF exclusion via the sealed list, a min-bars gate, and an
optional coverage gate, all evaluated against today's (symbol, bars_frame) pairs. It
does not track, and was never meant to track, a DIFFERENT question this module exists
for: "was the instrument currently trading as symbol X always known as X, or did its
symbol/identity change at some point in its history (rename, re-listing under a new
symbol, an ISIN change)?" That is symbol IDENTITY over time, not universe MEMBERSHIP
at a point in time. Read universe.py's own module docstring first if this boundary is
unclear — the two modules are complementary and neither should grow to do the other's
job (e.g. this module never decides ETF/min-bars/coverage inclusion, and universe.py
never resolves what an instrument used to be called).

THE HONEST STARTING POINT: NO REAL INSTRUMENT MASTER EXISTS LOCALLY
----------------------------------------------------------------------
This project does not have access to a real historical instrument master — a dataset
of ISIN/symbol changes, renames, or delistings over time, sourced from an
NSE/BSE/Kite instrument-master feed. Checked before writing this module:

- `research/charting/universe.py`'s sealed ETF list
  (`/app/research/sealed/etf_symbols_kite_20260919.csv`) is a point-in-time symbol
  list (one snapshot), not a change history — it cannot tell you what a symbol was
  called last year.
- `/app/research/screener_nr6/sector_master.csv` has only
  `symbol,company_name,sector,industry` columns — no ISIN, no effective dates, no
  prior-symbol column — and is itself 62% blank on `sector` per another agent's
  finding (data-availability note), so it is not a usable identity-history source
  even setting that aside.
- A repo-wide `grep -rn "erstwhile" backend/ research/` turns up real handling of
  entity renames, but only for MUTUAL FUND SCHEME NAMES: AMFI/NSDL scheme-name
  strings like "ICICI Prudential Large Cap Fund (erstwhile Bluechip Fund)" are
  parsed and canonicalized in `backend/services/masterdata.py`,
  `backend/services/action_plan_manager.py`, and resolved in
  `backend/tests/test_mf_holdings_resolver.py` / `backend/tests/test_action_rules.py`.
  That is free-text fund-name canonicalization against AMFI's own descriptor
  convention — a different domain (mutual funds, not equities), built on a different
  data source (a name string, not a structured ISIN/symbol table) — and it supplies
  zero equity symbol-rename data. No equity/stock symbol-rename or ISIN-change
  handling of any kind exists anywhere else in this repo today.

Given that, this module's honest job is NOT to pretend it can resolve real renames.
It is to:

1. Provide the resolution INTERFACE callers should use — "what identity was this
   instrument known by on date X" — with a safe default (assume identity is stable:
   today's symbol is used at every historical date) that is explicitly, machine-
   checkably FLAGGED as an unverified best-effort assumption rather than asserted as
   fact. See `IdentityBasis` and `ResolvedIdentity.is_unverified`.
2. Provide the plug-in point (`RenameRecord`, `InstrumentMaster`,
   `load_rename_records_csv`) so a REAL instrument master can be dropped in later —
   as a CSV of (old_symbol, new_symbol, effective_date, source, note) rows, or built
   from any other loader that produces `RenameRecord`s — without any caller of
   `resolve_symbol_at` changing a single line. The only thing that changes is the
   `basis` on the returned result, which flips from an unverified assumption to a
   sourced mapping once real records are supplied.
3. Never fabricate rename history. No real rename record is seeded into this module
   (none was found in the repo to seed with — see above), and the one rename example
   used in this module's own tests is explicitly synthetic: a made-up symbol pair,
   clearly labelled as such in both the fixture and the test names, never presented
   as a real company's history.

This mirrors the PRD's own point-in-time vocabulary (docs/charting.md §32.9: a
feature is only PIT-eligible when, among other things, "the instrument mapping is
valid for the historical date" — exactly the question this module exists to answer
honestly rather than assume away) and its provider-provenance vocabulary (§32.6:
`source_identifier`, `point_in_time_validated`) — `RenameRecord.source` and
`InstrumentMaster.provenance_summary()` reuse that shape (CHART-S05-adjacent) so a
real loader has an obvious place to attach real provenance without inventing new
field names.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Sequence

# Sources recognised as NOT a real, attributable instrument-master provenance. Any
# other `source` string is treated as real for the purpose of `IdentityBasis`
# selection — see `InstrumentMaster.resolve_symbol_at`.
_UNSOURCED_LABELS = frozenset({"synthetic", "test"})

RENAME_CSV_COLUMNS = ("old_symbol", "new_symbol", "effective_date", "source", "note")


class IdentityBasis(str, Enum):
    """How a resolved identity was determined — the honesty label every caller must
    check before trusting `ResolvedIdentity.resolved_symbol` for anything point-in-
    time-sensitive."""

    ASSUMED_STABLE_NO_MASTER_DATA = "ASSUMED_STABLE_NO_MASTER_DATA"
    """No rename record touches this symbol at all (the common case today, since no
    real master is wired in for ANY symbol). We ASSUME — we do not verify — that the
    instrument's identity has been stable across its whole queried history."""

    SYNTHETIC_RENAME_MAPPING = "SYNTHETIC_RENAME_MAPPING"
    """A rename record matched, but its `source` is a test/synthetic label (see
    `_UNSOURCED_LABELS`). Exercises the resolver's logic only — never a real
    historical fact. This is what this module's own tests use."""

    SOURCED_RENAME_MAPPING = "SOURCED_RENAME_MAPPING"
    """A rename record matched and its `source` names a real, attributable
    instrument-master provenance. Nothing in this repo populates this today —
    reserved for when a real instrument master is plugged in."""

    OUT_OF_KNOWN_RANGE = "OUT_OF_KNOWN_RANGE"
    """`as_of` falls outside the `InstrumentMaster`'s own declared coverage window
    (`coverage_start`/`coverage_end`), so even the "assume stable" fallback cannot be
    offered with any confidence: this master does not claim to know anything, not
    even absence of a rename, about dates outside that window."""


# Every basis except SOURCED_RENAME_MAPPING rests on an assumption, a synthetic/test
# fixture, or an explicit "we don't know" — i.e. everything this module can produce
# today, since no real master is wired in anywhere in this repo.
UNVERIFIED_BASES = frozenset({
    IdentityBasis.ASSUMED_STABLE_NO_MASTER_DATA,
    IdentityBasis.SYNTHETIC_RENAME_MAPPING,
    IdentityBasis.OUT_OF_KNOWN_RANGE,
})


@dataclass(frozen=True)
class RenameRecord:
    """One instrument-identity change: `old_symbol` became `new_symbol` effective on
    `effective_date` (inclusive — `effective_date` itself already uses `new_symbol`).

    This is the extension point for a REAL instrument master: load real rows into a
    list of these (see `load_rename_records_csv` for the matching CSV shape) and pass
    them to `InstrumentMaster(records=...)`. No other code needs to change.
    """

    old_symbol: str
    new_symbol: str
    effective_date: date
    source: str  # e.g. "synthetic" (test-only) or a real provenance id/name
    note: str = ""


@dataclass(frozen=True)
class ResolvedIdentity:
    """The result of resolving an instrument's symbol identity at a specific date."""

    query_symbol: str
    as_of: date
    resolved_symbol: str
    basis: IdentityBasis
    governing_record: RenameRecord | None = None
    """The `RenameRecord` this resolution is based on, or `None` when no record
    touches `query_symbol` at all. Set even when `as_of` predates the record's own
    `effective_date` (i.e. the instrument has not been renamed yet as of `as_of`,
    but we know a rename happens later in its recorded lineage)."""

    @property
    def is_unverified(self) -> bool:
        """True whenever this result rests on an assumption, a synthetic/test
        fixture, or an explicit "date out of range" — i.e. everything except a real,
        sourced instrument-master mapping. Callers doing anything point-in-time-
        sensitive (PRD §32.9) should check this before trusting `resolved_symbol`."""
        return self.basis in UNVERIFIED_BASES


class InstrumentMaster:
    """A (possibly empty) collection of instrument-identity rename records, plus an
    optional declared coverage window.

    `InstrumentMaster.empty()` is the honest default in effect everywhere in this
    repo today: zero records, no declared coverage window, so every resolution falls
    back to "assume stable identity" and is labelled
    `ASSUMED_STABLE_NO_MASTER_DATA` — never silently treated as verified fact.
    """

    def __init__(
        self,
        records: Sequence[RenameRecord] = (),
        *,
        coverage_start: date | None = None,
        coverage_end: date | None = None,
    ) -> None:
        if coverage_start is not None and coverage_end is not None and coverage_start > coverage_end:
            raise ValueError(f"coverage_start {coverage_start} is after coverage_end {coverage_end}")
        self.records: tuple[RenameRecord, ...] = tuple(records)
        self.coverage_start = coverage_start
        self.coverage_end = coverage_end

    @classmethod
    def empty(cls) -> "InstrumentMaster":
        """No real historical instrument master is wired in anywhere in this repo.
        This is that honest state made explicit: zero rename records, no coverage
        claim over any date range."""
        return cls()

    def _in_coverage(self, as_of: date) -> bool:
        if self.coverage_start is not None and as_of < self.coverage_start:
            return False
        if self.coverage_end is not None and as_of > self.coverage_end:
            return False
        return True

    def _lineage_for(self, symbol: str) -> list[RenameRecord]:
        """Every rename record touching `symbol`, directly or transitively through a
        chain of renames (old->new->newer...). Implemented as a simple closure over
        `self.records`; real-world rename chains are expected to be short (a handful
        of renames per instrument over decades), so this is not optimised for scale.
        """
        touched = {symbol}
        relevant: list[RenameRecord] = []
        changed = True
        while changed:
            changed = False
            for r in self.records:
                if r in relevant:
                    continue
                if r.old_symbol in touched or r.new_symbol in touched:
                    relevant.append(r)
                    if r.old_symbol not in touched:
                        touched.add(r.old_symbol)
                        changed = True
                    if r.new_symbol not in touched:
                        touched.add(r.new_symbol)
                        changed = True
        return relevant

    def resolve_symbol_at(self, symbol: str, as_of: date) -> ResolvedIdentity:
        """What symbol identifies this instrument on `as_of`?

        `symbol` may be given as EITHER the current/latest symbol or any historical
        alias that appears in a rename record this master knows about — both resolve
        to whichever identity this master believes was effective on `as_of`.

        With no matching record (the default, everywhere, today) this degrades to
        the honest "assume stable identity" fallback: `resolved_symbol == symbol`,
        flagged `ASSUMED_STABLE_NO_MASTER_DATA`.
        """
        if not self._in_coverage(as_of):
            return ResolvedIdentity(
                query_symbol=symbol,
                as_of=as_of,
                resolved_symbol=symbol,
                basis=IdentityBasis.OUT_OF_KNOWN_RANGE,
            )

        lineage = self._lineage_for(symbol)
        if not lineage:
            return ResolvedIdentity(
                query_symbol=symbol,
                as_of=as_of,
                resolved_symbol=symbol,
                basis=IdentityBasis.ASSUMED_STABLE_NO_MASTER_DATA,
            )

        # Walk the lineage chronologically: before the earliest effective_date the
        # identity is that record's old_symbol; from an effective_date onward
        # (inclusive) it is that record's new_symbol, until a later record in the
        # chain supersedes it again.
        ordered = sorted(lineage, key=lambda r: r.effective_date)
        resolved = ordered[0].old_symbol
        governing = ordered[0]
        for r in ordered:
            if as_of >= r.effective_date:
                resolved = r.new_symbol
                governing = r
            else:
                break

        basis = (
            IdentityBasis.SYNTHETIC_RENAME_MAPPING
            if governing.source in _UNSOURCED_LABELS
            else IdentityBasis.SOURCED_RENAME_MAPPING
        )
        return ResolvedIdentity(
            query_symbol=symbol,
            as_of=as_of,
            resolved_symbol=resolved,
            basis=basis,
            governing_record=governing,
        )

    def provenance_summary(self) -> dict:
        """A small, honest self-description of what backs this master — every
        consumer should be able to ask "where did this identity information come
        from" (PRD §32.6-style provenance) rather than trust it blindly.
        """
        sources = sorted({r.source for r in self.records})
        has_real_master_data = any(s not in _UNSOURCED_LABELS for s in sources)
        return {
            "record_count": len(self.records),
            "sources": sources,
            "coverage_start": self.coverage_start,
            "coverage_end": self.coverage_end,
            "has_real_master_data": has_real_master_data,
        }


def resolve_symbol_at(symbol: str, as_of: date, master: InstrumentMaster | None = None) -> ResolvedIdentity:
    """Module-level convenience: resolve `symbol` at `as_of` against `master`, or —
    when no master is supplied — the honest empty default (`InstrumentMaster.empty()`)
    that every caller in this repo gets today unless it explicitly wires in a real
    instrument master."""
    return (master if master is not None else InstrumentMaster.empty()).resolve_symbol_at(symbol, as_of)


def load_rename_records_csv(path: str | Path) -> list[RenameRecord]:
    """Load rename records from a header-full CSV with columns `RENAME_CSV_COLUMNS`
    (`effective_date` as `YYYY-MM-DD`).

    This is the documented plug-in point for a REAL instrument master: point this at
    a real NSE/BSE/Kite-derived symbol-rename history file and pass the result into
    `InstrumentMaster(records=..., coverage_start=..., coverage_end=...)` — nothing
    else in this module, or in any of its callers, needs to change.

    No such real file exists in this repo today (see module docstring). This loader
    is exercised in tests only, against a synthetic fixture CSV.
    """
    p = Path(path)
    records: list[RenameRecord] = []
    with open(p, newline="") as f:
        reader = csv.DictReader(f)
        missing = set(RENAME_CSV_COLUMNS) - {"note"} - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{p}: missing required column(s) {sorted(missing)}")
        for row in reader:
            records.append(RenameRecord(
                old_symbol=row["old_symbol"].strip(),
                new_symbol=row["new_symbol"].strip(),
                effective_date=datetime.strptime(row["effective_date"].strip(), "%Y-%m-%d").date(),
                source=row["source"].strip(),
                note=(row.get("note") or "").strip(),
            ))
    return records
