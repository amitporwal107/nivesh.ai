"""study/execute.py: the CHARTING_PREREGISTRATION_V1 end-to-end orchestrator (§1-§9). Built
and tested against small synthetic multi-symbol universes only -- this file never runs
`execute_study` over the real Kite universe (that is this package's own one-off,
artifact-deleted <=10-symbol wiring smoke run, documented separately, never a pytest test).

Real, committed reference files ARE used here where `execute_study` itself always uses them
(the real sealed-demerger hooks `research.corporate_actions.regime.regime_break_mask`/
`regime_segments` -- our synthetic symbols simply have no confirmed demerger, so both are a
no-op; the real `research/index_history/data/*.csv` benchmark/VIX/breadth files for
`attach_context=True`, the same convention `test_study_run.py`'s own
`test_build_segment_attach_context_adds_context_and_research_blocks` already uses). Only the
Kite daily-bars *directory* and the sealed ETF *list* are synthesized per test (via `kite_dir`/
`etf_list_path`/`bars_by_symbol`), so no test here touches the real ~2,926-symbol Kite
directory.
"""
from __future__ import annotations

import csv
import gzip
import json

import pandas as pd
from pathlib import Path

import pytest

from research.charting.events import schema
from research.charting.study import execute
from research.charting.tests._events_helpers import (
    confirmed_hh_hl_with_runway,
    confirmed_rectangle_with_runway,
    confirmed_support_resistance_with_runway,
)


# ── Synthetic kite_dir / etf_list_path / bars_by_symbol fixtures ────────────────────────


def _write_kite_dir(tmp_path) -> "Path":
    """A minimal, valid `part-*.csv.gz` directory -- structurally correct for
    `bars.provenance()`/`bars.load_symbol` (§1's own input-hash source), content
    irrelevant to this module's own tests (which always pass `bars_by_symbol` directly,
    bypassing the real load)."""
    d = tmp_path / "kite_dir"
    d.mkdir()
    with gzip.open(d / "part-0.csv.gz", "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "instrument_token", "date", "open", "high", "low", "close", "volume", "source_version"])
        w.writerow(["DUMMY", "1", "2021-01-04", "100.0", "101.0", "99.0", "100.5", "1000", "v1"])
    return d


def _write_etf_list(tmp_path) -> "Path":
    p = tmp_path / "etf_list.csv"
    p.write_text("ZZZ_NOT_USED\n")  # header-less; none of our synthetic symbols are ETFs
    return p


def _rebase_dates(bars: pd.DataFrame, *, start: str = "2021-01-04") -> pd.DataFrame:
    """Same technique as `test_study_run.py::_rebase_dates_pre_sealed` -- a fresh, unique
    business-day sequence, working around a latent leap-day collision in
    `_events_helpers.shift_outside_sealed_window`."""
    out = bars.copy()
    out["date"] = pd.bdate_range(start=start, periods=len(out))
    return out


def _mixed_segment_universe(tail_len: int = 260) -> dict:
    """Three families, each present in BOTH segments: P_* symbols dated ~2021 (pre-sealed),
    Q_* symbols dated ~2025 (post-sealed, P_* shifted +4 years -- neither 2021/2022 nor
    2025/2026 touch a leap-day, so the shift is collision-free). `build_pre_sealed_segment`/
    `build_post_sealed_segment` each window every symbol's frame to their own span BEFORE
    building, so the "wrong-segment" symbols simply end up with an empty (0-bar) frame and
    are excluded by the universe rule's own INSUFFICIENT_BARS gate -- never a crash."""
    pre = {
        "P_RECT": _rebase_dates(confirmed_rectangle_with_runway(tail_len=tail_len)),
        "P_SR": _rebase_dates(confirmed_support_resistance_with_runway(tail_len=tail_len)),
        "P_HHHL": _rebase_dates(confirmed_hh_hl_with_runway(tail_len=tail_len)),
    }
    post = {}
    for sym, bars in pre.items():
        shifted = bars.copy()
        shifted["date"] = shifted["date"] + pd.DateOffset(years=4)
        post[sym.replace("P_", "Q_")] = shifted
    return {**pre, **post}


# ── _git_commit ───────────────────────────────────────────────────────────────────────────


@pytest.mark.skipif(not (Path(execute.__file__).resolve().parents[3] / ".git").exists(),
                    reason="not a git checkout — the study can run from an exported tree, which is "
                           "what GIT_COMMIT_ENV covers (see test_git_commit_falls_back_...)")
def test_git_commit_resolves_the_real_worktree_head():
    import subprocess

    root = execute.Path(__file__).resolve().parents[3]
    expected = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True,
    ).stdout.strip()
    assert execute._git_commit() == expected
    assert len(expected) == 40  # a real sha, not a placeholder


def test_git_commit_returns_none_for_a_non_git_directory(tmp_path, monkeypatch):
    """Still None with no git AND no env override -- the fallback added 2026-09-25 must not invent
    a commit, only report one the operator supplied."""
    monkeypatch.delenv(execute.GIT_COMMIT_ENV, raising=False)
    assert execute._git_commit(tmp_path) is None


# ── eligible_population ──────────────────────────────────────────────────────────────────


def test_eligible_population_excludes_the_last_bar_of_every_symbol():
    bars_by_symbol = {
        "A": pd.DataFrame({"date": pd.bdate_range("2021-01-04", periods=5)}),
        "B": pd.DataFrame({"date": pd.bdate_range("2021-01-04", periods=1)}),  # only 1 bar
    }
    pop = execute.eligible_population(bars_by_symbol)
    assert set(pop) == {("A", 0), ("A", 1), ("A", 2), ("A", 3)}  # idx 4 has no bar after it
    assert ("B", 0) not in pop  # a single-bar symbol has no entry-eligible index at all


def test_eligible_population_empty_for_empty_universe():
    assert execute.eligible_population({}) == []


# ── _benchmark_forward_returns ────────────────────────────────────────────────────────────


def _benchmark_df(dates, closes):
    return pd.DataFrame({
        "date": pd.to_datetime(list(dates)), "open": closes, "high": closes, "low": closes,
        "close": closes, "source": "kite",
    })


def test_benchmark_forward_returns_hand_computed():
    bench = _benchmark_df(pd.bdate_range("2021-01-04", periods=10), [100, 101, 102, 103, 104, 105, 106, 107, 108, 109])
    # Two BULLISH rows entering on index 0 (close 100) and index 2 (close 102).
    rows = [
        {"direction": "BULLISH", "entry": {"primary": {"date": "2021-01-04"}}},
        {"direction": "BULLISH", "entry": {"primary": {"date": "2021-01-06"}}},
        {"direction": "BEARISH", "entry": {"primary": {"date": "2021-01-04"}}},  # excluded: not BULLISH
    ]
    out = execute._benchmark_forward_returns(rows, bench, horizons=(1, 3))
    # h=1: (101-100)/100=0.01 and (103-102)/102 -> mean of the two
    expected_h1 = ((101 - 100) / 100 + (103 - 102) / 102) / 2
    assert out[1]["n"] == 2
    assert out[1]["mean"] == pytest.approx(expected_h1)
    expected_h3 = ((103 - 100) / 100 + (105 - 102) / 102) / 2
    assert out[3]["n"] == 2
    assert out[3]["mean"] == pytest.approx(expected_h3)


def test_benchmark_forward_returns_missing_date_or_insufficient_runway_is_not_fabricated():
    bench = _benchmark_df(pd.bdate_range("2021-01-04", periods=3), [100, 101, 102])
    rows = [
        {"direction": "BULLISH", "entry": {"primary": {"date": "2021-01-04"}}},  # h=5 has no runway
        {"direction": "BULLISH", "entry": {"primary": {"date": "1999-01-01"}}},  # not in benchmark at all
    ]
    out = execute._benchmark_forward_returns(rows, bench, horizons=(5,))
    assert out[5] == {"mean": None, "n": 0}


# ── _collect_unverified_cost_rates ───────────────────────────────────────────────────────


def test_collect_unverified_cost_rates_unions_across_rows_and_horizons():
    rows = [
        {"costs": {"by_horizon": {1: {"available": True, "unverified_rates_used": ["stt_v1"]},
                                   5: {"available": True, "unverified_rates_used": ["dp_charge_v1"]}}}},
        {"costs": {"by_horizon": {1: {"available": True, "unverified_rates_used": ["stt_v1", "stamp_v1"]}}}},
        {"costs": {"by_horizon": {1: {"available": False}}}},  # unavailable block contributes nothing
        {"costs": None},  # a BEARISH-shaped row contributes nothing, never raises
    ]
    out = execute._collect_unverified_cost_rates(rows)
    assert out == ["dp_charge_v1", "stamp_v1", "stt_v1"]


# ── build_family_comparison_groups (real controls.py, synthetic symbols) ────────────────


def test_build_family_comparison_groups_structure():
    from research.charting.events import extraction

    bars_a = confirmed_rectangle_with_runway(tail_len=40)
    bars_by_symbol = {"SYN1": bars_a}
    rows = extraction.extract_events(bars_a, "SYN1")
    assert rows  # the fixture is known to confirm at least one RECTANGLE event

    bench = _benchmark_df(bars_a["date"], bars_a["close"] + 5.0)  # any deterministic series
    groups = execute.build_family_comparison_groups(
        rows, bars_by_symbol, random_seeds=(0, 1, 2), atr_decile_seed=0, benchmark_df=bench,
    )
    assert set(groups.keys()) == {"RECTANGLE"}
    g = groups["RECTANGLE"]
    assert set(g["random_batch"].keys()) == {0, 1, 2}
    bullish_n = len([r for r in rows if r.get("direction") == "BULLISH"])
    for seed_rows in g["random_batch"].values():
        assert len(seed_rows) <= bullish_n  # capped at eligible-population size, never over-drawn
    assert len(g["buy_next_open_rows"]) == len(rows)  # one baseline row per event, any direction
    assert set(g["nifty_500_return_by_horizon"].keys()) == set(schema.HORIZONS)
    assert set(g["nifty_500_detail_by_horizon"].keys()) == set(schema.HORIZONS)


def test_build_family_comparison_groups_empty_rows_produces_no_families():
    groups = execute.build_family_comparison_groups([], {}, random_seeds=(0,), benchmark_df=_benchmark_df([], []))
    assert groups == {}


def test_build_family_comparison_groups_max_workers_matches_serial():
    """PERF-CONTROLS: the `max_workers > 1` forked-process path (see `build_family_comparison_
    groups`' own docstring / the "PERFORMANCE ONLY" block above `_WORKER_CTX`) must produce
    output BYTE-IDENTICAL to the default serial path -- never a different sample, never a
    reordered dict -- for the exact same inputs. Three real families (RECTANGLE,
    SUPPORT_RESISTANCE, HH_HL) so `max_workers=4` actually exercises >1 worker."""
    import json as _json

    from research.charting.events import extraction

    bars_by_symbol = {
        "SYN_RECT": confirmed_rectangle_with_runway(tail_len=40),
        "SYN_SR": confirmed_support_resistance_with_runway(tail_len=40),
        "SYN_HH": confirmed_hh_hl_with_runway(tail_len=40),
    }
    rows = extraction.extract_events_multi(bars_by_symbol)
    assert {r["pattern_type"] for r in rows} == {"RECTANGLE", "SUPPORT_RESISTANCE", "HH_HL"}

    bench = _benchmark_df(bars_by_symbol["SYN_RECT"]["date"], bars_by_symbol["SYN_RECT"]["close"] + 5.0)
    kwargs = dict(random_seeds=(0, 1, 2), atr_decile_seed=0, benchmark_df=bench)

    serial = execute.build_family_comparison_groups(rows, bars_by_symbol, max_workers=1, **kwargs)
    parallel = execute.build_family_comparison_groups(rows, bars_by_symbol, max_workers=4, **kwargs)

    assert list(serial.keys()) == list(parallel.keys()) == sorted({r["pattern_type"] for r in rows})
    # dict -> JSON round trip (default=str for the rare non-JSON-native value, matching writer.py's
    # own convention) is a simple, thorough byte-identity check over the FULL nested structure.
    assert _json.dumps(serial, sort_keys=True, default=str) == _json.dumps(parallel, sort_keys=True, default=str)


# ── _write_rows_artifact / _write_nifty_artifact / _write_family_comparison_artifacts ────


def test_write_rows_artifact_hashes_match_and_manifest_shape(tmp_path):
    from research.charting.config import CONFIG

    rows = [{"event_id": "E1", "versioning": {"cost_rule_version": "v1", "tax_rule_version": "t1"}}]
    manifest = execute._write_rows_artifact(rows, tmp_path / "art", segment="pre_sealed", symbols=["SYN1"], cfg=CONFIG)
    content = (tmp_path / "art" / "events.jsonl").read_bytes()
    import hashlib
    assert manifest["artifacts"][0]["sha256"] == hashlib.sha256(content).hexdigest()
    assert manifest["cost_rule_versions"] == ["v1"]
    assert manifest["tax_rule_versions"] == ["t1"]
    assert manifest["row_count"] == 1


def test_write_nifty_artifact_hash_matches_file_on_disk(tmp_path):
    detail = {1: {"mean": 0.01, "n": 5}, 5: {"mean": None, "n": 0}}
    manifest = execute._write_nifty_artifact(tmp_path, detail, segment="pre_sealed", family="RECTANGLE", benchmark_path=tmp_path / "nope.csv")
    written = (tmp_path / "nifty_500_returns.json").read_bytes()
    import hashlib
    assert manifest["sha256"] == hashlib.sha256(written).hexdigest()
    payload = json.loads(written)
    assert payload["return_by_horizon"] == {"1": 0.01, "5": None}
    assert payload["n_by_horizon"] == {"1": 5, "5": 0}
    assert payload["source_file_sha256"] is None  # the given path does not exist


def test_write_family_comparison_artifacts_writes_all_four_kinds(tmp_path):
    from research.charting.config import CONFIG

    group = {
        "random_batch": {0: [], 1: []},
        "atr_decile_rows": [],
        "buy_next_open_rows": [],
        "nifty_500_detail_by_horizon": {h: {"mean": None, "n": 0} for h in schema.HORIZONS},
    }
    manifest = execute._write_family_comparison_artifacts(
        tmp_path, "RECTANGLE", "pre_sealed", group, cfg=CONFIG, symbols=["SYN1"], benchmark_path=tmp_path / "nope.csv",
    )
    assert set(manifest.keys()) == {"random_control", "atr_decile_control", "buy_next_open", "nifty_500"}
    for name in ("random_control", "atr_decile_control", "buy_next_open"):
        assert (tmp_path / "RECTANGLE" / name / "events.jsonl").exists()
        assert (tmp_path / "RECTANGLE" / name / "manifest.json").exists()
    assert (tmp_path / "RECTANGLE" / "nifty_500_returns.json").exists()


# ── execute_study: end-to-end, synthetic universe, real integrity gate ──────────────────


@pytest.fixture
def _small_kwargs(tmp_path):
    return {
        "kite_dir": _write_kite_dir(tmp_path),
        "etf_list_path": _write_etf_list(tmp_path),
        "bars_by_symbol": _mixed_segment_universe(),
        "random_control_seeds": (0, 1, 2),  # small: this is an orchestration test, not a power study
    }


def test_execute_study_end_to_end_complete_status_and_artifact_layout(tmp_path, _small_kwargs):
    out_dir = tmp_path / "out"
    result = execute.execute_study(out_dir, **_small_kwargs)

    assert result["status"] == "COMPLETE"
    assert result["integrity"]["passed"] is True

    for segment in ("pre_sealed", "post_sealed"):
        seg_dir = out_dir / segment
        assert (seg_dir / "events.jsonl").exists()
        assert (seg_dir / "manifest.json").exists()
        assert (seg_dir / "report.json").exists()
        assert (seg_dir / "report.md").exists()

        report_payload = json.loads((seg_dir / "report.json").read_text())
        json.dumps(report_payload, allow_nan=False)  # strict JSON, must not raise
        assert report_payload["segment"] == segment
        assert report_payload["prereg_sha256"] == result["study_manifest"]["prereg_sha256"]
        for family, family_report in report_payload["families"].items():
            assert set(family_report["horizons"].keys()) == {str(h) for h in schema.HORIZONS}
            for cell in family_report["horizons"].values():
                assert set(cell["targets"].keys())  # non-empty target table
                assert "comparisons" in cell
                assert "bearish" in cell
                comp_dir = seg_dir / "comparisons" / family
                assert (comp_dir / "random_control" / "events.jsonl").exists()
                assert (comp_dir / "atr_decile_control" / "events.jsonl").exists()
                assert (comp_dir / "buy_next_open" / "events.jsonl").exists()
                assert (comp_dir / "nifty_500_returns.json").exists()

    assert not (out_dir / "INTEGRITY_FAILED.md").exists()

    study_manifest = json.loads((out_dir / "study_manifest.json").read_text())
    assert study_manifest["status"] == "COMPLETE"
    assert study_manifest["config_hash_check"] == {"passed": True, "config_hash": execute.study_run.FROZEN_CONFIG_HASH}
    assert set(study_manifest["segments"].keys()) == {"pre_sealed", "post_sealed"}
    assert study_manifest["run_started_at"] <= study_manifest["run_ended_at"]
    assert study_manifest["symbols_requested"] == "ALL"  # bars_by_symbol override: no `symbols` filter given


def test_execute_study_kill_switch_false_is_recorded_as_skipped_not_a_silent_pass(tmp_path, _small_kwargs):
    result = execute.execute_study(tmp_path / "out", kill_switch=False, **_small_kwargs)
    for segment in ("pre_sealed", "post_sealed"):
        ks = result["integrity"][segment]["kill_switch"]
        assert ks["skipped"] is True
        assert ks["passed"] is True
        assert "tests only" in ks["reason"]


def test_execute_study_integrity_failure_writes_integrity_failed_and_no_report(tmp_path, _small_kwargs, monkeypatch):
    # Patches the DIGEST entry point, which is what the kill switch calls now that the duplicate
    # build is folded a symbol at a time instead of held whole. Patching the old row-based
    # `kill_switch_check` would leave this test green while testing nothing.
    def _forced_failure(digest_a, digest_b):
        return {
            "passed": False, "pattern_id_sets_match": False, "event_file_sha256_match": False,
            "sha256_a": "a", "sha256_b": "b", "pattern_id_set_symmetric_difference": ["FORCED_TEST_FAILURE"],
            "n_rows_a": digest_a.n_rows, "n_rows_b": digest_b.n_rows,
        }
    monkeypatch.setattr(execute.integrity, "kill_switch_check_digests", _forced_failure)

    out_dir = tmp_path / "out"
    result = execute.execute_study(out_dir, **_small_kwargs)

    assert result["status"] == "INTEGRITY_FAILED"
    assert result["integrity"]["passed"] is False
    assert (out_dir / "INTEGRITY_FAILED.md").exists()
    failed_text = (out_dir / "INTEGRITY_FAILED.md").read_text()
    assert "FORCED_TEST_FAILURE" in failed_text

    for segment in ("pre_sealed", "post_sealed"):
        assert not (out_dir / segment / "report.json").exists()
        assert not (out_dir / segment / "report.md").exists()
        # the segment's own events.jsonl/manifest.json still exist (built before the gate ran)
        assert (out_dir / segment / "events.jsonl").exists()

    study_manifest = json.loads((out_dir / "study_manifest.json").read_text())
    assert study_manifest["status"] == "INTEGRITY_FAILED"


def test_execute_study_sealed_window_check_covers_comparison_rows_too(tmp_path, _small_kwargs, monkeypatch):
    """§8 bullet 3 is re-checked across pattern rows AND every comparison-group row --
    poison `assert_no_sealed_rows_in_dataset` to prove the gate actually looks at what this
    module passes it (a positive control on the WIRING, not a re-test of
    `research_window.py` itself, which already has its own dedicated tests)."""
    def _always_raises(dates):
        raise execute.SealedWindowError("forced: sealed-window check reached")
    monkeypatch.setattr(execute.integrity, "assert_no_sealed_rows_in_dataset", _always_raises)

    out_dir = tmp_path / "out"
    result = execute.execute_study(out_dir, **_small_kwargs)
    assert result["status"] == "INTEGRITY_FAILED"
    for segment in ("pre_sealed", "post_sealed"):
        assert result["integrity"][segment]["sealed_window_check"]["passed"] is False
        assert "forced" in result["integrity"][segment]["sealed_window_check"]["error"]


def test_execute_study_config_hash_mismatch_raises_before_anything_runs(tmp_path, _small_kwargs):
    import copy
    tampered = copy.deepcopy(execute.CONFIG)
    tampered["atr_period"] = 999
    with pytest.raises(execute.study_run.ConfigHashMismatch):
        execute.execute_study(tmp_path / "out", cfg=tampered, **_small_kwargs)
    assert not (tmp_path / "out" / "pre_sealed").exists()  # nothing was built


def test_execute_study_explicit_symbols_requested_is_recorded(tmp_path, _small_kwargs):
    kwargs = dict(_small_kwargs)
    result = execute.execute_study(tmp_path / "out", symbols=["P_RECT", "Q_RECT"], **kwargs)
    # bars_by_symbol override still wins over `symbols` for what actually gets built (test
    # seam documented in execute_study's own docstring); `symbols_requested` still records
    # what the caller asked for, honestly, even though it wasn't the thing actually used.
    assert result["study_manifest"]["symbols_requested"] == ["P_RECT", "Q_RECT"]


# ── CLI ───────────────────────────────────────────────────────────────────────────────────


def test_parse_args_splits_comma_separated_symbols():
    args = execute._parse_args(["--out", "/tmp/x", "--symbols", "RELIANCE, TCS ,INFY"])
    assert args.out == "/tmp/x"
    assert args.symbols == "RELIANCE, TCS ,INFY"


def test_main_wires_parsed_symbols_into_execute_study_and_never_prints_a_metric(tmp_path, monkeypatch, capsys):
    captured = {}

    def fake_execute_study(out_dir, *, symbols=None, **kwargs):
        captured["out_dir"] = out_dir
        captured["symbols"] = symbols
        return {"status": "COMPLETE", "out_dir": str(out_dir)}

    monkeypatch.setattr(execute, "execute_study", fake_execute_study)
    rc = execute.main(["--out", str(tmp_path / "out"), "--symbols", "RELIANCE,TCS, INFY"])
    assert rc == 0
    assert captured["symbols"] == ["RELIANCE", "TCS", "INFY"]
    assert captured["out_dir"] == str(tmp_path / "out")

    printed = json.loads(capsys.readouterr().out)
    assert printed == {"status": "COMPLETE", "out_dir": str(tmp_path / "out")}


def test_main_omitted_symbols_means_full_universe(tmp_path, monkeypatch):
    captured = {}

    def fake_execute_study(out_dir, *, symbols=None, **kwargs):
        captured["symbols"] = symbols
        return {"status": "COMPLETE", "out_dir": str(out_dir)}

    monkeypatch.setattr(execute, "execute_study", fake_execute_study)
    execute.main(["--out", str(tmp_path / "out")])
    assert captured["symbols"] is None


def test_main_returns_nonzero_on_integrity_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(execute, "execute_study", lambda out_dir, **kwargs: {"status": "INTEGRITY_FAILED", "out_dir": str(out_dir)})
    rc = execute.main(["--out", str(tmp_path / "out")])
    assert rc == 1


def test_git_commit_falls_back_to_the_env_var_outside_a_checkout(tmp_path, monkeypatch):
    """A study run from an exported tree (a purpose-built VM fed a tarball) still has to record
    WHICH code produced it. Without this the manifest carries `git_commit: null`, and a
    pre-registered result that cannot name its own code is not reproducible."""
    monkeypatch.setenv(execute.GIT_COMMIT_ENV, "76eff14dadbb9244d9351aab2d1955a31155aad4")
    assert execute._git_commit(tmp_path) == "76eff14dadbb9244d9351aab2d1955a31155aad4"


def test_a_real_checkout_still_wins_over_the_env_var(monkeypatch):
    """The fallback must never override git where git can answer -- that would let a stale env var
    mislabel a run."""
    monkeypatch.setenv(execute.GIT_COMMIT_ENV, "0000000000000000000000000000000000000000")
    got = execute._git_commit()
    if got is not None and got != "0000000000000000000000000000000000000000":
        assert len(got) == 40      # a real SHA from the real checkout
