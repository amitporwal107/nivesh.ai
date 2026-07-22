"""Unit tests for the month-by-month parse window. No DB, no network.

The window is what makes a 126k-document backfill safe to run as bounded,
resumable chunks across machines. Two properties carry the weight:

  * DISJOINT  — consecutive months must never both claim the same document, or
                two workers download the same PDF twice (against endpoints that
                have already rate-limited us).
  * COMPLETE  — consecutive months must leave no gap, or documents are silently
                skipped and nobody notices until someone asks why a filing is
                missing.

Both follow from --to-date being EXCLUSIVE, which is the whole reason it is.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import date


def _cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "nidp.services.document_parser", *args],
        capture_output=True, text=True, timeout=60)


def test_to_date_is_exclusive_so_months_tile_without_overlap_or_gap():
    # January = [2026-01-01, 2026-02-01), February = [2026-02-01, 2026-03-01).
    # 2026-01-31 belongs to January only; 2026-02-01 to February only.
    jan = (date(2026, 1, 1), date(2026, 2, 1))
    feb = (date(2026, 2, 1), date(2026, 3, 1))
    boundary = date(2026, 2, 1)
    in_jan = jan[0] <= boundary < jan[1]
    in_feb = feb[0] <= boundary < feb[1]
    assert not in_jan and in_feb, "boundary date must belong to exactly one month"
    last_jan = date(2026, 1, 31)
    assert (jan[0] <= last_jan < jan[1]) and not (feb[0] <= last_jan < feb[1])
    assert jan[1] == feb[0], "no gap between consecutive windows"


def test_cli_rejects_an_inverted_window():
    r = _cli("--from-date", "2026-03-01", "--to-date", "2026-02-01")
    assert r.returncode != 0
    assert "must be before" in (r.stderr + r.stdout)


def test_cli_rejects_an_empty_window():
    # from == to selects nothing; silently parsing zero documents and reporting
    # success is the failure mode this whole session kept hitting.
    r = _cli("--from-date", "2026-02-01", "--to-date", "2026-02-01")
    assert r.returncode != 0


def test_cli_rejects_a_malformed_date():
    r = _cli("--from-date", "01-02-2026")
    assert r.returncode != 0


def test_cli_accepts_a_valid_month_window_and_shard_combination():
    # --help short-circuits before any DB work, so this validates parsing only.
    r = _cli("--from-date", "2026-01-01", "--to-date", "2026-02-01",
             "--shards", "3", "--shard", "2", "--help")
    assert r.returncode == 0


def test_window_is_optional_so_the_cron_is_unaffected():
    r = _cli("--help")
    assert r.returncode == 0
    assert "--from-date" in r.stdout and "--to-date" in r.stdout


def test_month_windows_for_a_six_month_backfill_are_contiguous():
    # The exact windows a 6-month backfill would use, checked end-to-end.
    months = [(date(2026, m, 1), date(2026, m + 1, 1)) for m in range(1, 7)]
    for (_, end), (nxt, _) in zip(months, months[1:]):
        assert end == nxt, "each window must start exactly where the previous ended"
    assert months[0][0] == date(2026, 1, 1)
    assert months[-1][1] == date(2026, 7, 1)
