"""Replay-engine tests — CHART-S32 ("replay engine"), package C.

Covers: chronological bar-by-bar walk + append-only lifecycle-transition event log
(requirements 1-2), run-manifest SHA-256 hashing of every output artifact (requirement 3),
determinism of the primary output across repeated runs (requirement 4), the look-ahead
guard (probe B4, requirement 5) and its mandatory negative control (requirement 6).

Poisoning helpers below are deliberately the same shape as
`test_patterns_lookahead.py`'s (`_poison_alternating_extremes` / `_poison_fabricated_clean_breakout`)
so the replay-layer probe exercises the same adversarial scenarios already proven meaningful
one layer down, rather than inventing a weaker one.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd
import pytest

from research.charting import replay, research_window
from research.charting.tests import synth


def _shift_outside_sealed_window(bars: pd.DataFrame) -> pd.DataFrame:
    """Shift every date back by 3 years. `synth.py`'s fixtures are anchored at
    `_START_DATE` (2024-01-02), which — like every other package's synthetic fixtures —
    falls inside the project-wide sealed 2023-01-01..2024-07-31 out-of-sample block
    (see test_early_scoring.py's own note on this). `replay.replay()`/`write_run()` now
    refuse (fix 1, research_window.SealedWindowError) to evaluate any window overlapping
    that block, so every fixture actually fed to them in this file is shifted to land
    safely in 2021 first. Only the calendar dates move; every OHLCV value and the walk's
    bar-by-bar mechanics this file tests are untouched."""
    shifted = bars.copy()
    shifted["date"] = shifted["date"] - pd.DateOffset(years=3)
    return shifted


def _lookahead_fixture() -> pd.DataFrame:
    """RECT-1 extended through a full breakout + retest + failure cycle (fixture #4) — the
    same fixture test_patterns_lookahead.py's sweep uses, so the replay's walk exercises
    formation, confirmation, retest and failure states, not just the quiet pre-breakout
    window. Dates shifted outside the sealed window — see _shift_outside_sealed_window."""
    return _shift_outside_sealed_window(synth.fixture_04_false_retest(synth.rect1()))


def _poison_alternating_extremes(bars: pd.DataFrame, t: int) -> pd.DataFrame:
    """Every row after `t` becomes a deterministic adversarial extreme (alternating
    huge/tiny OHLC + volume) — rows [0, t] are left byte-identical. Mirrors
    test_lookahead.py's `_poison_after` / test_patterns_lookahead.py's helper of the same name."""
    poisoned = bars.copy()
    for i in range(t + 1, len(bars)):
        if (i - t) % 2 == 1:
            poisoned.loc[i, ["open", "high", "low", "close"]] = [9999.0, 9999.5, 9998.5, 9999.0]
            poisoned.loc[i, "volume"] = 9_999_999.0
        else:
            poisoned.loc[i, ["open", "high", "low", "close"]] = [0.02, 0.03, 0.01, 0.02]
            poisoned.loc[i, "volume"] = 1.0
    return poisoned


def _poison_fabricated_clean_breakout(bars: pd.DataFrame, t: int) -> pd.DataFrame:
    """Every row after `t` becomes a smooth, decisive rally on huge volume — exactly the
    shape a genuine breakout confirmation would have, so a detector that peeked at it would
    plausibly (and wrongly) confirm a breakout dated at or before `t`."""
    poisoned = bars.copy()
    last_close = float(bars["close"].iloc[t])
    for j, i in enumerate(range(t + 1, len(bars))):
        c = last_close + 50.0 + j
        poisoned.loc[i, ["open", "high", "low", "close"]] = [c - 1.0, c + 1.0, c - 2.0, c]
        poisoned.loc[i, "volume"] = 2_000_000.0
    return poisoned


_POISON_FNS = (_poison_alternating_extremes, _poison_fabricated_clean_breakout)


# ── Requirements 1-2: chronological walk + append-only event log ────────────────────────


def test_replay_walks_rect1_breakout_retest_failure_and_records_transitions():
    bars = _lookahead_fixture()
    result = replay.replay(bars, symbol="SYN1")

    assert len(result.transitions) > 0
    rect_transitions = [t for t in result.transitions if t.pattern_type == "RECTANGLE"]
    assert rect_transitions, "expected at least one RECTANGLE pattern instance"

    statuses_seen = {t.new_status for t in rect_transitions}
    assert "PRICE_CONFIRMED" in statuses_seen
    assert "FAILED" in statuses_seen  # fixture #4 is a false-retest -> hard failure

    # The very first transition recorded for each pattern_id has prior_status None (there is
    # no earlier status to report -- this is the pattern's first observation, not a "change").
    first_by_pattern = {}
    for t in result.transitions:
        first_by_pattern.setdefault(t.pattern_id, t)
    for t in first_by_pattern.values():
        assert t.prior_status is None


def test_event_log_is_append_only_and_chronological():
    bars = _lookahead_fixture()
    result = replay.replay(bars, symbol="SYN1")

    indices = [t.event_index for t in result.transitions]
    assert indices == sorted(indices)  # walk order == chronological order, never reordered

    by_pattern: dict = {}
    for t in result.transitions:
        by_pattern.setdefault(t.pattern_id, []).append(t)
    for pid, seq in by_pattern.items():
        assert seq[0].prior_status is None, pid
        for a, b in zip(seq, seq[1:]):
            assert b.prior_status == a.new_status, pid  # each link's prior == the previous new
            assert b.event_index >= a.event_index, pid


def test_final_state_matches_last_recorded_transition_per_pattern():
    bars = _lookahead_fixture()
    result = replay.replay(bars, symbol="SYN1")

    last_by_pattern: dict = {}
    for t in result.transitions:
        last_by_pattern[t.pattern_id] = t

    assert set(result.final_state) == set(last_by_pattern)
    for pid, t in last_by_pattern.items():
        assert result.final_state[pid]["status"] == t.new_status
        assert result.final_state[pid]["pattern_type"] == t.pattern_type


def test_transition_events_carry_the_driving_detector_rule_when_one_exists():
    bars = _lookahead_fixture()
    result = replay.replay(bars, symbol="SYN1")

    price_confirmed = [t for t in result.transitions if t.new_status == "PRICE_CONFIRMED"]
    assert price_confirmed
    known_rule_ids = {
        "CLOSE_ABOVE_BREAKOUT", "CLOSE_BELOW_BREAKDOWN",
        "CLOSE_ABOVE_RESISTANCE", "CLOSE_BELOW_SUPPORT",
        "CLOSE_ABOVE_PRIOR_HIGH", "CLOSE_BELOW_PRIOR_LOW",
    }
    for t in price_confirmed:
        assert t.rule_id in known_rule_ids
        assert t.observed_values  # non-empty: patterns.py recorded a rule for this exact bar
        assert t.event_type == "PRICE_CONFIRMED"


def test_incomplete_bar_only_applies_at_final_step_quiet_bar_does_not_change_state():
    """Mirrors test_patterns_lookahead.py's quiet-incomplete-bar probe, one layer up: passing
    a non-crossing running candle must never change any recorded transition."""
    base = _shift_outside_sealed_window(synth.rect1())
    without = replay.replay(base, symbol="SYN1").to_dict()

    running_date = pd.bdate_range(start=base["date"].iloc[-1] + pd.tseries.offsets.BDay(1), periods=1)[0]
    quiet_incomplete_bar = {
        "date": running_date, "open": 105.0, "high": 105.5, "low": 104.5, "close": 105.0,
        "volume": 50_000.0, "is_complete": False,
    }
    with_quiet = replay.replay(base, symbol="SYN1", incomplete_bar=quiet_incomplete_bar).to_dict()
    assert without == with_quiet


# ── Requirement 3: run manifest with SHA-256 of every output artifact ───────────────────


def test_write_run_manifest_hashes_match_actual_file_contents(tmp_path):
    bars = _lookahead_fixture()
    manifest = replay.write_run(bars, tmp_path, symbol="SYN1")

    assert manifest["artifacts"], "manifest recorded no artifacts"
    written_names = {e["path"] for e in manifest["artifacts"]}
    assert written_names == {"results.json", "events.json", "final_state.json"}

    for entry in manifest["artifacts"]:
        path = tmp_path / entry["path"]
        assert path.exists(), entry["path"]
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == entry["sha256"], entry["path"]


# ── Requirement 4: determinism — byte-identical primary output across repeated runs ─────


def test_replay_is_deterministic_across_repeated_runs_same_input(tmp_path):
    bars = _lookahead_fixture()
    out_a, out_b = tmp_path / "run_a", tmp_path / "run_b"

    manifest_a = replay.write_run(bars, out_a, symbol="SYN1")
    manifest_b = replay.write_run(bars, out_b, symbol="SYN1")

    for name in ("results.json", "events.json", "final_state.json"):
        content_a = (out_a / name).read_bytes()
        content_b = (out_b / name).read_bytes()
        assert content_a == content_b, f"{name} is not byte-identical across two runs"

    hashes_a = {e["path"]: e["sha256"] for e in manifest_a["artifacts"]}
    hashes_b = {e["path"]: e["sha256"] for e in manifest_b["artifacts"]}
    assert hashes_a == hashes_b


def test_manifest_run_metadata_is_the_only_thing_wall_clock_affects(tmp_path):
    bars = _lookahead_fixture()
    now_a = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now_b = datetime(2027, 6, 15, tzinfo=timezone.utc)
    out_a, out_b = tmp_path / "run_a", tmp_path / "run_b"

    manifest_a = replay.write_run(bars, out_a, symbol="SYN1", now=now_a)
    manifest_b = replay.write_run(bars, out_b, symbol="SYN1", now=now_b)

    assert manifest_a["generated_at"] != manifest_b["generated_at"]
    assert manifest_a["run_id"] != manifest_b["run_id"]
    # every hashed artifact is nonetheless identical -- wall clock never leaks into content
    assert manifest_a["artifacts"] == manifest_b["artifacts"]
    for name in ("results.json", "events.json", "final_state.json"):
        assert (out_a / name).read_bytes() == (out_b / name).read_bytes()


# ── Requirement 5: probe B4 — look-ahead guard ───────────────────────────────────────────


def test_probe_b4_state_at_t_unaffected_by_poisoning_every_bar_after_t():
    base = _lookahead_fixture()
    n = len(base)
    checked = 0
    for t in range(10, n - 1):  # leave >=1 bar after t to poison
        for poison_fn in _POISON_FNS:
            poisoned = poison_fn(base, t)
            # Sanity: rows [0, t] are byte-identical between the two runs.
            pd.testing.assert_frame_equal(
                poisoned.iloc[: t + 1].reset_index(drop=True), base.iloc[: t + 1].reset_index(drop=True)
            )
            state_a = replay.replay(base, symbol="SYN1", end_index=t).to_dict()
            state_b = replay.replay(poisoned, symbol="SYN1", end_index=t).to_dict()
            assert state_a == state_b, f"leak detected at t={t} via {poison_fn.__name__}"
            checked += 1
    assert checked >= 10  # meaningful sweep breadth, not a single lucky t


def test_probe_b4_state_at_t_unaffected_by_poisoning_during_formation_only():
    """Same probe restricted to the pre-breakout formation window (t < formation_end), where
    pivot/ATR/clustering computations are most exposed to a look-ahead bug."""
    base = _shift_outside_sealed_window(synth.rect1())
    n = len(base)
    checked = 0
    for t in range(6, n - 1):
        poisoned = _poison_alternating_extremes(base, t)
        state_a = replay.replay(base, symbol="SYN1", end_index=t).to_dict()
        state_b = replay.replay(poisoned, symbol="SYN1", end_index=t).to_dict()
        assert state_a == state_b, f"leak detected at t={t} (formation-only sweep)"
        checked += 1
    assert checked >= 10


def test_probe_b4_on_disk_manifest_artifacts_unaffected_by_future_poisoning(tmp_path):
    """Same guarantee, exercised through write_run()'s on-disk artifacts (not just the
    in-memory ReplayResult), at one representative t."""
    base = _lookahead_fixture()
    t = 15
    poisoned = _poison_fabricated_clean_breakout(base, t)

    out_a, out_b = tmp_path / "clean", tmp_path / "poisoned"
    replay.write_run(base, out_a, symbol="SYN1", end_index=t)
    replay.write_run(poisoned, out_b, symbol="SYN1", end_index=t)

    for name in ("results.json", "events.json", "final_state.json"):
        assert (out_a / name).read_bytes() == (out_b / name).read_bytes(), name


# ── Requirement 6: mandatory negative control for probe B4 ──────────────────────────────


def _leaky_replay_state_at_t(bars: pd.DataFrame, t: int) -> dict:
    """NEGATIVE CONTROL ONLY — deliberately PIT-broken, NOT real replay.py logic, and must
    NEVER be imported outside this test file.

    Demonstrates the exact leaky pattern the task asks this control to catch: it derives its
    one status-driving threshold from `bars["high"].max()` over the WHOLE frame (future rows
    included — the same mistake test_patterns_lookahead.py's `_peeking_resistance_level`
    negative control demonstrates one layer down), then walks EVERY bar `0..len(bars)-1`
    (never bounded by `t`) tagging each with PRICE_CONFIRMED once its close first exceeds
    that threshold. Only at the very end does it filter the resulting event log down to
    `event_index <= t` — filtering "up to time t" at the final serialization step instead of
    during the walk, exactly as described in the task. Because the THRESHOLD itself (not
    merely which events survive the filter) is computed from the whole frame, bars dated at
    or before `t` can have their status change purely because of what happens after `t` —
    proving this probe methodology (poison the future, diff the state at `t`) really can
    catch a look-ahead bug, not just always pass.
    """
    resistance = float(bars["high"].max())  # THE LEAK: whole-frame aggregate, future included
    threshold = resistance - 5.0
    events = []
    status = "GEOMETRY_VALID"
    for i in range(len(bars)):  # THE LEAK: walks past `t`, never bounded by it
        close = float(bars["close"].iloc[i])
        new_status = "PRICE_CONFIRMED" if close > threshold else "GEOMETRY_VALID"
        if new_status != status:
            events.append({"event_index": i, "prior_status": status, "new_status": new_status})
            status = new_status
    kept = [e for e in events if e["event_index"] <= t]  # filtered only NOW -- serialization time
    status_at_t = kept[-1]["new_status"] if kept else "GEOMETRY_VALID"
    return {"events": kept, "status_at_t": status_at_t}


def test_negative_control_leaky_replay_variant_is_caught_by_the_same_probe():
    base = _lookahead_fixture()
    t = 15  # well within RECT-1's own formation window, well before any breakout bar
    poisoned = _poison_alternating_extremes(base, t)

    # Sanity: rows [0, t] are byte-identical, exactly as every other probe in this file checks.
    pd.testing.assert_frame_equal(
        poisoned.iloc[: t + 1].reset_index(drop=True), base.iloc[: t + 1].reset_index(drop=True)
    )

    leak_a = _leaky_replay_state_at_t(base, t)
    leak_b = _leaky_replay_state_at_t(poisoned, t)
    assert leak_a != leak_b, (
        "negative control failed to detect the leak -- a probe that stays green against a "
        "broken detector proves nothing (task requirement 6)"
    )

    # And the real, correct replay() shows no such difference for the same (base, poisoned, t).
    state_a = replay.replay(base, symbol="SYN1", end_index=t).to_dict()
    state_b = replay.replay(poisoned, symbol="SYN1", end_index=t).to_dict()
    assert state_a == state_b


# ── Fix 1: sealed-window guard on the research path (review 2026-09-22, defect #1) ──────


def test_replay_over_a_window_touching_2023_03_raises():
    # Starts well before the sealed block and runs into 2023-03 -- a partial overlap, which
    # must be refused exactly like a window fully inside the block.
    bars = synth.bars_from_closes([100.0 + i * 0.1 for i in range(80)], start_date="2022-11-01")
    assert bars["date"].max() > research_window.SEALED_GAP_START  # sanity: fixture really overlaps
    with pytest.raises(research_window.SealedWindowError):
        replay.replay(bars, symbol="SYN1")


def test_replay_over_2021_2022_passes():
    bars = synth.bars_from_closes([100.0 + i * 0.1 for i in range(80)], start_date="2021-06-01")
    assert bars["date"].max() < research_window.SEALED_GAP_START  # sanity: fixture is entirely safe
    result = replay.replay(bars, symbol="SYN1")
    assert result.end_index == len(bars) - 1  # ran normally, nothing refused


def test_write_run_over_a_sealed_window_raises_before_writing_anything(tmp_path):
    bars = synth.bars_from_closes([100.0 + i * 0.1 for i in range(80)], start_date="2023-02-01")
    with pytest.raises(research_window.SealedWindowError):
        replay.write_run(bars, tmp_path, symbol="SYN1")
    assert list(tmp_path.iterdir()) == []  # refused before any artifact touched disk


def test_write_run_artifact_assertion_catches_a_poisoned_sealed_transition(tmp_path, monkeypatch):
    """Defense in depth: even if replay()'s own window guard were somehow bypassed,
    write_run() independently asserts no sealed date reaches the artifacts it writes (fix 1's
    'assertion helper for artifacts', assert_no_sealed_rows). Proven here by monkeypatching
    replay() to return a result carrying one poisoned (sealed-window) transition date;
    write_run must raise before writing anything to tmp_path."""
    bars = _shift_outside_sealed_window(synth.rect1())
    real_result = replay.replay(bars, symbol="SYN1")
    assert real_result.transitions, "fixture sanity: need at least one transition to poison"

    poisoned_transition = replace(real_result.transitions[0], event_date="2023-06-15")
    poisoned_result = replace(real_result, transitions=(poisoned_transition, *real_result.transitions[1:]))
    monkeypatch.setattr(replay, "replay", lambda *a, **k: poisoned_result)

    with pytest.raises(research_window.SealedWindowError):
        replay.write_run(bars, tmp_path, symbol="SYN1")
    assert list(tmp_path.iterdir()) == []  # nothing written -- refused before any artifact touched disk
