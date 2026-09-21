"""Tests for research.charting.instruments — CHART-S07 instrument identity resolution.

IMPORTANT — what these tests do and do not prove
--------------------------------------------------
This project has no real historical instrument master (see instruments.py's module
docstring for what was checked: universe.py's sealed ETF list, sector_master.csv, and
a repo-wide grep for "erstwhile" that found only mutual-fund scheme-name handling,
never equity symbol/ISIN renames). So:

- Every "real symbol" used below (e.g. "RELIANCE", "INFY") is real only in the sense
  that it is a plausible NSE trading symbol — these tests make NO claim about that
  company's actual historical identity. They exist to prove the NO-MASTER-DATA
  fallback path and its honesty flag, nothing more.
- Every rename record used below is clearly synthetic (`SYNTHETIC_OLD_SYM` /
  `SYNTHETIC_NEW_SYM`, `source="synthetic"`) — a made-up example, not sourced from
  any real corporate action. It exists to prove the resolver's DATE-BOUNDARY LOGIC
  (which identity applies before/after a rename, from either alias), not to assert
  that this specific rename ever happened.
"""
from __future__ import annotations

from datetime import date

import pytest

from research.charting import instruments
from research.charting.instruments import (
    IdentityBasis,
    InstrumentMaster,
    RenameRecord,
    load_rename_records_csv,
    resolve_symbol_at,
)

# A clearly-synthetic rename fixture — see module docstring above. Not a real company.
SYNTHETIC_OLD_SYM = "ZZZSYNTHOLD"
SYNTHETIC_NEW_SYM = "ZZZSYNTHNEW"
SYNTHETIC_RENAME_DATE = date(2022, 6, 1)
SYNTHETIC_RENAME = RenameRecord(
    old_symbol=SYNTHETIC_OLD_SYM,
    new_symbol=SYNTHETIC_NEW_SYM,
    effective_date=SYNTHETIC_RENAME_DATE,
    source="synthetic",
    note="SYNTHETIC FIXTURE for test_instruments.py — not a real company or rename.",
)


# ---------------------------------------------------------------------------
# 1. No master data present at all -> stable-identity fallback, honesty flag set
# ---------------------------------------------------------------------------

def test_empty_master_is_the_documented_no_data_state():
    master = InstrumentMaster.empty()
    assert master.records == ()
    assert master.coverage_start is None
    assert master.coverage_end is None
    summary = master.provenance_summary()
    assert summary["record_count"] == 0
    assert summary["has_real_master_data"] is False


def test_real_symbol_real_date_no_rename_data_present_flags_unverified():
    # "RELIANCE" is a real, plausible NSE symbol; this test asserts nothing about its
    # real history — only that with no master data, resolution honestly falls back
    # to "assume stable" and is flagged, not silently presented as verified fact.
    result = InstrumentMaster.empty().resolve_symbol_at("RELIANCE", date(2023, 3, 15))
    assert result.resolved_symbol == "RELIANCE"
    assert result.query_symbol == "RELIANCE"
    assert result.as_of == date(2023, 3, 15)
    assert result.basis is IdentityBasis.ASSUMED_STABLE_NO_MASTER_DATA
    assert result.governing_record is None
    assert result.is_unverified is True


def test_module_level_convenience_defaults_to_empty_master():
    result = resolve_symbol_at("INFY", date(2020, 1, 1))
    assert result.resolved_symbol == "INFY"
    assert result.basis is IdentityBasis.ASSUMED_STABLE_NO_MASTER_DATA
    assert result.is_unverified is True


def test_unrelated_symbol_not_confused_by_other_records_in_the_master():
    # A master that DOES have rename data, but not for the symbol being queried,
    # must still fall back honestly for that unrelated symbol.
    master = InstrumentMaster(records=[SYNTHETIC_RENAME])
    result = master.resolve_symbol_at("SOMEOTHERSTOCK", date(2023, 1, 1))
    assert result.resolved_symbol == "SOMEOTHERSTOCK"
    assert result.basis is IdentityBasis.ASSUMED_STABLE_NO_MASTER_DATA


# ---------------------------------------------------------------------------
# 2. Synthetic rename mapping changes the resolved identity across the boundary
# ---------------------------------------------------------------------------

def test_synthetic_rename_before_boundary_resolves_to_old_symbol_queried_by_old():
    master = InstrumentMaster(records=[SYNTHETIC_RENAME])
    result = master.resolve_symbol_at(SYNTHETIC_OLD_SYM, date(2022, 1, 1))
    assert result.resolved_symbol == SYNTHETIC_OLD_SYM
    assert result.basis is IdentityBasis.SYNTHETIC_RENAME_MAPPING
    assert result.governing_record == SYNTHETIC_RENAME
    assert result.is_unverified is True  # synthetic, never treat as real


def test_synthetic_rename_on_and_after_boundary_resolves_to_new_symbol_queried_by_old():
    master = InstrumentMaster(records=[SYNTHETIC_RENAME])
    on_boundary = master.resolve_symbol_at(SYNTHETIC_OLD_SYM, SYNTHETIC_RENAME_DATE)
    after = master.resolve_symbol_at(SYNTHETIC_OLD_SYM, date(2023, 1, 1))
    assert on_boundary.resolved_symbol == SYNTHETIC_NEW_SYM
    assert after.resolved_symbol == SYNTHETIC_NEW_SYM
    assert on_boundary.basis is IdentityBasis.SYNTHETIC_RENAME_MAPPING


def test_synthetic_rename_queried_by_new_symbol_still_resolves_pre_rename_history():
    # The whole point of tracking identity: querying via the CURRENT/new symbol for a
    # date before the rename must still surface the OLD identity, not silently keep
    # today's symbol.
    master = InstrumentMaster(records=[SYNTHETIC_RENAME])
    before = master.resolve_symbol_at(SYNTHETIC_NEW_SYM, date(2021, 1, 1))
    after = master.resolve_symbol_at(SYNTHETIC_NEW_SYM, date(2023, 1, 1))
    assert before.resolved_symbol == SYNTHETIC_OLD_SYM
    assert after.resolved_symbol == SYNTHETIC_NEW_SYM


def test_synthetic_rename_chain_of_two_renames():
    # A -> B on 2020-01-01, then B -> C on 2022-01-01. Three windows, one lineage.
    r1 = RenameRecord("SCHAINA", "SCHAINB", date(2020, 1, 1), source="synthetic")
    r2 = RenameRecord("SCHAINB", "SCHAINC", date(2022, 1, 1), source="synthetic")
    master = InstrumentMaster(records=[r1, r2])

    assert master.resolve_symbol_at("SCHAINA", date(2019, 1, 1)).resolved_symbol == "SCHAINA"
    assert master.resolve_symbol_at("SCHAINA", date(2021, 1, 1)).resolved_symbol == "SCHAINB"
    assert master.resolve_symbol_at("SCHAINA", date(2023, 1, 1)).resolved_symbol == "SCHAINC"
    # Querying by the middle alias must reach both ends of the chain too.
    assert master.resolve_symbol_at("SCHAINB", date(2019, 1, 1)).resolved_symbol == "SCHAINA"
    assert master.resolve_symbol_at("SCHAINB", date(2023, 1, 1)).resolved_symbol == "SCHAINC"


def test_sourced_rename_is_not_flagged_unverified():
    # A record whose source names real provenance (anything not "synthetic"/"test")
    # is reported as SOURCED, not synthetic/unverified — this is the state a real
    # instrument master would put callers in, reserved for future use since nothing
    # in this repo populates it today.
    real_looking = RenameRecord(
        "OLDNAME", "NEWNAME", date(2021, 1, 1), source="nse_symbol_change_20210101.csv",
    )
    master = InstrumentMaster(records=[real_looking])
    result = master.resolve_symbol_at("OLDNAME", date(2022, 1, 1))
    assert result.basis is IdentityBasis.SOURCED_RENAME_MAPPING
    assert result.is_unverified is False


# ---------------------------------------------------------------------------
# 3. Date completely out of any known range
# ---------------------------------------------------------------------------

def test_date_before_declared_coverage_window_is_flagged_out_of_range():
    master = InstrumentMaster(
        records=[SYNTHETIC_RENAME], coverage_start=date(2020, 1, 1), coverage_end=date(2024, 12, 31),
    )
    result = master.resolve_symbol_at(SYNTHETIC_OLD_SYM, date(1990, 1, 1))
    assert result.basis is IdentityBasis.OUT_OF_KNOWN_RANGE
    assert result.resolved_symbol == SYNTHETIC_OLD_SYM  # returned as-is, not asserted as fact
    assert result.is_unverified is True


def test_date_after_declared_coverage_window_is_flagged_out_of_range():
    master = InstrumentMaster(
        records=[SYNTHETIC_RENAME], coverage_start=date(2020, 1, 1), coverage_end=date(2024, 12, 31),
    )
    result = master.resolve_symbol_at(SYNTHETIC_NEW_SYM, date(2099, 1, 1))
    assert result.basis is IdentityBasis.OUT_OF_KNOWN_RANGE


def test_date_within_coverage_window_is_not_out_of_range():
    master = InstrumentMaster(
        records=[SYNTHETIC_RENAME], coverage_start=date(2020, 1, 1), coverage_end=date(2024, 12, 31),
    )
    result = master.resolve_symbol_at(SYNTHETIC_OLD_SYM, date(2021, 1, 1))
    assert result.basis is not IdentityBasis.OUT_OF_KNOWN_RANGE


def test_no_declared_coverage_window_never_flags_out_of_range():
    # InstrumentMaster.empty() (and any master built without coverage_start/_end)
    # makes no claim about any date range at all, so it must never emit
    # OUT_OF_KNOWN_RANGE — only ASSUMED_STABLE_NO_MASTER_DATA.
    result = InstrumentMaster.empty().resolve_symbol_at("ANY", date(1900, 1, 1))
    assert result.basis is IdentityBasis.ASSUMED_STABLE_NO_MASTER_DATA
    result2 = InstrumentMaster.empty().resolve_symbol_at("ANY", date(2200, 1, 1))
    assert result2.basis is IdentityBasis.ASSUMED_STABLE_NO_MASTER_DATA


def test_invalid_coverage_window_raises():
    with pytest.raises(ValueError):
        InstrumentMaster(coverage_start=date(2024, 1, 1), coverage_end=date(2020, 1, 1))


# ---------------------------------------------------------------------------
# provenance_summary — CHART-S05-adjacent
# ---------------------------------------------------------------------------

def test_provenance_summary_flags_synthetic_only_master_as_not_real():
    master = InstrumentMaster(records=[SYNTHETIC_RENAME], coverage_start=date(2020, 1, 1), coverage_end=date(2024, 1, 1))
    summary = master.provenance_summary()
    assert summary["record_count"] == 1
    assert summary["sources"] == ["synthetic"]
    assert summary["has_real_master_data"] is False
    assert summary["coverage_start"] == date(2020, 1, 1)
    assert summary["coverage_end"] == date(2024, 1, 1)


def test_provenance_summary_flags_real_looking_source_as_real():
    real_looking = RenameRecord("OLDNAME", "NEWNAME", date(2021, 1, 1), source="nse_symbol_change_feed")
    master = InstrumentMaster(records=[real_looking])
    assert master.provenance_summary()["has_real_master_data"] is True


# ---------------------------------------------------------------------------
# load_rename_records_csv — documented extension point, synthetic fixture only
# ---------------------------------------------------------------------------

def test_load_rename_records_csv_round_trips_a_synthetic_fixture(tmp_path):
    p = tmp_path / "synthetic_rename_master.csv"
    p.write_text(
        "old_symbol,new_symbol,effective_date,source,note\n"
        f"{SYNTHETIC_OLD_SYM},{SYNTHETIC_NEW_SYM},{SYNTHETIC_RENAME_DATE.isoformat()},synthetic,"
        "SYNTHETIC fixture row for a CSV-loader test\n"
    )
    records = load_rename_records_csv(p)
    assert records == [RenameRecord(
        old_symbol=SYNTHETIC_OLD_SYM,
        new_symbol=SYNTHETIC_NEW_SYM,
        effective_date=SYNTHETIC_RENAME_DATE,
        source="synthetic",
        note="SYNTHETIC fixture row for a CSV-loader test",
    )]

    # And it plugs straight into InstrumentMaster with no other code changing.
    master = InstrumentMaster(records=records)
    result = master.resolve_symbol_at(SYNTHETIC_OLD_SYM, date(2023, 1, 1))
    assert result.resolved_symbol == SYNTHETIC_NEW_SYM
    assert result.basis is IdentityBasis.SYNTHETIC_RENAME_MAPPING


def test_load_rename_records_csv_missing_column_raises(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("old_symbol,new_symbol,effective_date\nA,B,2020-01-01\n")
    with pytest.raises(ValueError):
        load_rename_records_csv(p)


def test_load_rename_records_csv_note_column_optional(tmp_path):
    p = tmp_path / "no_note.csv"
    p.write_text(f"old_symbol,new_symbol,effective_date,source\nA,B,2020-01-01,synthetic\n")
    records = load_rename_records_csv(p)
    assert records == [RenameRecord("A", "B", date(2020, 1, 1), source="synthetic", note="")]


# ---------------------------------------------------------------------------
# Module docstring / naming sanity — keeps the "no real master data" claim honest
# ---------------------------------------------------------------------------

def test_module_does_not_ship_with_any_seeded_real_rename_record():
    # Guards against a future edit silently adding a "real" seeded record: the empty
    # default must stay empty, since this module documents that none was found.
    assert instruments.InstrumentMaster.empty().records == ()
