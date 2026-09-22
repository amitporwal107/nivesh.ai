"""Real data, real files: the stored demergers.csv (and its raw-source snapshots) match
the sha256 recorded for them in manifest.json -- catches a stale hash after a rewrite, the
same check research/index_history/tests/test_manifest_sha256.py makes for its own data.
Also validates demergers.csv's basic shape/contract so a future regeneration can't
silently corrupt it.
"""
from datetime import date

import pandas as pd
import pytest

from research.corporate_actions.events import (
    CATEGORIES, CSV_COLUMNS, DEFAULT_DATA_PATH as DEMERGERS_CSV, HERE, load_events,
)
from research.corporate_actions.manifest import load_manifest, sha256_file

MANIFEST_PATH = HERE / "data" / "manifest.json"


def test_demergers_csv_sha256_matches_manifest():
    manifest = load_manifest(MANIFEST_PATH)
    recorded = manifest["files"]["demergers.csv"]["sha256"]
    actual = sha256_file(DEMERGERS_CSV)
    assert actual == recorded


def test_raw_source_snapshots_sha256_match_manifest():
    manifest = load_manifest(MANIFEST_PATH)
    for name in ("raw/nse_ca_demerger_rows.json", "raw/tpd_ca_history_demerger_rows.csv"):
        recorded = manifest["files"][name]["sha256"]
        actual = sha256_file(HERE / "data" / name)
        assert actual == recorded, name


def test_gap_review_candidates_csv_sha256_matches_manifest():
    manifest = load_manifest(MANIFEST_PATH)
    recorded = manifest["files"]["gap_review_candidates.csv"]["sha256"]
    actual = sha256_file(HERE / "data" / "gap_review_candidates.csv")
    assert actual == recorded


def test_manifest_records_both_sources_with_a_reference():
    manifest = load_manifest(MANIFEST_PATH)
    assert "nse_corporate_actions_api" in manifest["sources"]
    assert "in_repo_tpd_ca_history" in manifest["sources"]
    for entry in manifest["sources"].values():
        assert entry.get("reference") or entry.get("name")


def test_demergers_csv_has_exactly_the_declared_columns():
    df = pd.read_csv(DEMERGERS_CSV, dtype=str)
    assert list(df.columns) == list(CSV_COLUMNS)


def test_demergers_csv_has_no_duplicate_symbol_ex_date_category_rows():
    df = pd.read_csv(DEMERGERS_CSV, dtype=str)
    key = list(zip(df["symbol"], df["ex_date"], df["category"]))
    assert len(key) == len(set(key))


def test_every_row_category_is_a_declared_category():
    df = pd.read_csv(DEMERGERS_CSV, dtype=str)
    assert set(df["category"].unique()) <= set(CATEGORIES)


def test_every_ex_date_is_within_the_task_window_2021_01_01_to_today():
    events = load_events()
    window_start = date(2021, 1, 1)
    for e in events:
        assert window_start <= e.ex_date <= date.today(), e


def test_ncrps_rows_are_never_verified_true():
    events = load_events()
    for e in events:
        if e.category == "NCRPS_BONUS_SCHEME":
            assert e.verified is False
            assert e.review_reason  # must explain why


def test_every_verified_row_has_a_source_and_retrieved_at():
    events = load_events()
    for e in events:
        if e.verified:
            assert e.source
            assert e.source_reference
            assert e.retrieved_at


def test_siemens_and_abfrl_are_present_confirmed_and_match_documented_gap_ratios():
    """Cross-check against the independently-documented findings this session
    reproduced (.claude/workspace/charting-pattern-engine/data-availability.md):
    SIEMENS ratio 0.6526 (-34.74% gap), ABFRL ratio 0.4815 (-51.85% gap)."""
    events = {e.symbol: e for e in load_events() if e.category == "DEMERGER"}

    siemens = events["SIEMENS"]
    assert siemens.ex_date == date(2025, 4, 7)
    assert siemens.verified is True
    assert siemens.gap_pct_kite == pytest.approx(-34.74, abs=0.02)

    abfrl = events["ABFRL"]
    assert abfrl.ex_date == date(2025, 5, 22)
    assert abfrl.verified is True
    assert abfrl.gap_pct_kite == pytest.approx(-51.85, abs=0.02)
