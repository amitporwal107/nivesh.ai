"""Chronological replay engine — CHART-S32 ("replay engine"), package C of the charting /
pattern-detection / historical-validation project (docs/charting.md; plan:
.claude/workspace/charting-pattern-engine/plan.md).

Purpose: walk a bar series forward bar-by-bar, calling the pattern-detection entry point
`research.charting.patterns.detect_as_of` at every point in time `t` using ONLY
`bars[0..t]`, and record every pattern lifecycle-status transition as an append-only event
(PRD §23.2 pattern event record, `research.charting.lifecycle`). The whole point of this
module is to let a downstream reader PROVE the pattern engine has no look-ahead bias — see
`research/charting/tests/test_replay.py` probe B4 — so every design choice here favours a
provably-correct walk over a convenient one.

Entry point confirmed against the real module (2026-09-21): `patterns.detect_as_of(bars, t,
cfg=CONFIG, *, symbol="UNKNOWN", incomplete_bar=None) -> list[PatternSnapshot]` already
matches the point-in-time contract this replay needs exactly (its own docstring: "`bars` is
sliced to `view = bars.iloc[:t+1]` FIRST ... every function in this module only ever reads
`view`"). No adapter was necessary. `replay()` below still re-slices `bars` to `bars.iloc[:t+1]`
itself before every call, as a second, independent PIT boundary: even if `detect_as_of`'s own
slicing ever regressed, this module's walk loop would still never hand it a row dated after
`t` -- see the loop in `replay()`.

Determinism (requirement 4): the primary output (`ReplayResult.to_dict()` / `results.json`)
contains no wall-clock timestamp, no random id and no unordered-set/dict content -- every
field is derived solely from the input bars + config. `write_run()`'s `manifest.json` is the
only place wall-clock time (`generated_at`) and a run id appear, exactly mirroring
`research.charting.export.build_snapshot`'s `run_id`/`generated_at` split (config/content vs.
run metadata) and `research/sim_diag/make_page_snapshot.py`'s `sha256_file` manifest
convention (a JSON manifest listing each output artifact's relative path and its SHA-256 hex
digest) -- no existing "run manifest" module was found elsewhere in the repo (grepped for
`sim_diag`/`manifest`), so this module follows that same, already-established convention
rather than inventing a new one.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Make `research.charting` importable whether this module is run as part of the package or
# executed as a bare script -- mirrors research/charting/export.py and
# research/charting/tests/conftest.py.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd

from research.charting import patterns
from research.charting.config import CONFIG, ENGINE_VERSION, PROFILE_NAME, config_hash
from research.charting.research_window import assert_no_sealed_rows, research_bars

SCHEMA_VERSION = 1


def _iso_date(d) -> str:
    return pd.Timestamp(d).date().isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Append-only lifecycle-transition event (PRD §23.2, lifecycle.PatternEvent's field set,
#    extended with the replay's own prior/new status pair) ──────────────────────────────────


@dataclass(frozen=True)
class TransitionEvent:
    """One append-only record of a pattern instance's `status` changing between two
    consecutive replay steps. Field set follows `lifecycle.PatternEvent` (`event_index`/
    `event_date` in place of a bare timestamp, `config_hash` for frozen-config identity),
    plus `pattern_id`/`pattern_type`/`symbol` and the `prior_status -> new_status` pair this
    task requires. `prior_status` is `None` exactly once per pattern_id: the step at which
    that pattern is first observed (there is no earlier status to report).

    `event_type`/`rule_id`/`observed_values` are carried through verbatim from whichever of
    `patterns.py`'s own `events` entries is dated exactly at `event_date` (the entry that
    *caused* this transition), when one exists. Some transitions have no such entry (a
    pattern's first appearance, or ageing out into `EXPIRED` purely from bar-index arithmetic)
    -- for those, `event_type` is a value synthesized by this module (`PATTERN_FIRST_OBSERVED`
    / `STATUS_CHANGED`), `rule_id` is `None`, and `observed_values` is `{}`. Nothing is ever
    guessed: a `None`/`{}` here always means patterns.py recorded no rule for this exact bar.
    """

    event_index: int
    event_date: str
    pattern_id: str
    pattern_type: str
    symbol: str
    prior_status: Optional[str]
    new_status: str
    event_type: str
    rule_id: Optional[str]
    observed_values: dict
    config_hash: str

    def to_dict(self) -> dict:
        return {
            "event_index": self.event_index,
            "event_date": self.event_date,
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type,
            "symbol": self.symbol,
            "prior_status": self.prior_status,
            "new_status": self.new_status,
            "event_type": self.event_type,
            "rule_id": self.rule_id,
            "observed_values": self.observed_values,
            "config_hash": self.config_hash,
        }


@dataclass(frozen=True)
class ReplayResult:
    """The full, deterministic output of one `replay()` call: the append-only transition
    log from `start_index` through `end_index` inclusive, plus the state of every pattern
    instance known as of `end_index`. This is the object probe B4 diffs -- see
    `test_replay.py::test_probe_b4_*`.
    """

    schema_version: int
    engine_version: str
    profile: str
    symbol: str
    config_hash: str
    start_index: int
    end_index: int
    start_date: str
    end_date: str
    transitions: tuple
    final_state: dict

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "engine_version": self.engine_version,
            "profile": self.profile,
            "symbol": self.symbol,
            "config_hash": self.config_hash,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "transitions": [t.to_dict() for t in self.transitions],
            "final_state": self.final_state,
        }


def _driving_event(events: list, date_t: str) -> tuple:
    """Whichever of a snapshot's own `events` entries is dated exactly `date_t` -- the entry
    that caused *this* transition, if patterns.py recorded one. At most one is ever expected
    (patterns.py adds at most one event per pattern instance per bar); the last is taken
    defensively if that ever changes. Returns (event_type, rule_id, observed_values)."""
    dated = [e for e in events if e.get("date") == date_t]
    if not dated:
        return None, None, {}
    last = dated[-1]
    return last.get("event_type"), last.get("rule_id"), last.get("observed_values", {})


def replay(
    bars: pd.DataFrame,
    *,
    cfg: dict = CONFIG,
    symbol: str = "UNKNOWN",
    start_index: int = 0,
    end_index: Optional[int] = None,
    incomplete_bar: Optional[dict] = None,
    snapshot_sink: Optional[dict] = None,
) -> ReplayResult:
    """Chronological, point-in-time-safe replay over `bars[start_index..end_index]`.

    At every step `t` in that range, `bars` is first sliced down to `bars.iloc[:t+1]` by THIS
    function -- before `patterns.detect_as_of` gets a chance to slice it again itself -- so
    rows dated after `t` are never even in scope of the call, regardless of how many rows
    `bars` actually has beyond `end_index` (poisoned or not). This is what makes probe B4
    meaningful: the walk's own loop bound, not merely a downstream filter, is the PIT boundary.

    `incomplete_bar` (see `patterns.detect_as_of`'s own contract) is only meaningful for a
    still-open final bar, so it is only ever passed through on the LAST step of the walk
    (`t == end_index`); every earlier step gets `incomplete_bar=None`.

    Every pattern instance's `status` is compared against its own last-recorded status; a
    change (including the pattern's first appearance, `prior_status=None`) is appended to the
    event log. A pattern_id that disappears from `detect_as_of`'s output at some `t` (e.g. it
    aged out of `patterns.py`'s own lookback window -- a documented scope choice there, not a
    PIT concern) is left at its last-known status in `final_state`; no "removed" event is
    invented, since disappearance-by-windowing is not a §11 lifecycle transition.

    Sealed-window guard (review 2026-09-22, defect #1): `replay()` is a RESEARCH evaluation
    path (as opposed to `patterns.detect_as_of` called standalone for live display/detection,
    which this guard deliberately never touches -- see `research.charting.export`), so the
    date span of every bar the walk can read -- bars[0..end_index], i.e. the lookback that
    `detect_as_of` sees as well as the requested window -- is checked against the project-wide
    sealed 2023-01-01..2024-07-31 out-of-sample block BEFORE the walk runs at all;
    `research_window.SealedWindowError` is raised if it overlaps at all. A post-sealed replay
    must therefore be handed bars that start after 2024-07-31 (its own fresh history): a sealed
    bar used only as lookback would still shape every level and swing the replay reports.

    `snapshot_sink` (PERF-DETECT, 2026-09-22, optional -- default `None` changes nothing about
    this function's return value or behaviour): when given a dict, this walk also records
    `snapshot_sink[t] = snaps` -- the RAW `patterns.detect_as_of` output at every step `t` --
    purely as a side channel. `events.extraction.extract_events` used to call
    `patterns.detect_as_of` a SECOND time, at the exact same `(bars.iloc[:t+1], t, cfg, symbol)`
    this walk already computed internally, just to recover the full `PatternSnapshot` for a
    transition it already knows about; passing a dict here lets it look that snapshot up instead
    (see extraction.py's own note). Nothing about `transitions`/`final_state`/the returned
    `ReplayResult` depends on whether this was passed.
    """
    n = len(bars)
    if n == 0:
        raise ValueError("replay() requires at least one bar")
    end = n - 1 if end_index is None else end_index
    if not (0 <= start_index <= end < n):
        raise ValueError(f"invalid replay range start_index={start_index} end_index={end} for {n} bars")

    research_bars(bars.iloc[: end + 1])  # lookback + window: every bar detect_as_of can read

    cfg_hash = config_hash(cfg)
    last_status: dict = {}
    last_type: dict = {}
    first_seen: dict = {}
    transitions: list = []

    for t in range(start_index, end + 1):
        sub = bars.iloc[: t + 1].reset_index(drop=True)  # PIT boundary #1: the walk's own loop bound
        date_t = _iso_date(bars["date"].iloc[t])
        ib = incomplete_bar if (incomplete_bar is not None and t == end) else None
        snaps = patterns.detect_as_of(sub, t, cfg=cfg, symbol=symbol, incomplete_bar=ib)
        if snapshot_sink is not None:
            snapshot_sink[t] = snaps

        for snap in sorted(snaps, key=lambda s: s.pattern_id):
            prior = last_status.get(snap.pattern_id)
            if prior == snap.status:
                continue
            event_type, rule_id, observed = _driving_event(snap.events, date_t)
            if event_type is None:
                event_type = "PATTERN_FIRST_OBSERVED" if prior is None else "STATUS_CHANGED"
            transitions.append(
                TransitionEvent(
                    event_index=t,
                    event_date=date_t,
                    pattern_id=snap.pattern_id,
                    pattern_type=snap.pattern_type,
                    symbol=symbol,
                    prior_status=prior,
                    new_status=snap.status,
                    event_type=event_type,
                    rule_id=rule_id,
                    observed_values=observed,
                    config_hash=cfg_hash,
                )
            )
            last_status[snap.pattern_id] = snap.status
            last_type[snap.pattern_id] = snap.pattern_type
            if snap.pattern_id not in first_seen:
                first_seen[snap.pattern_id] = (t, date_t)

    final_state = {
        pid: {
            "pattern_type": last_type[pid],
            "status": status,
            "first_seen_index": first_seen[pid][0],
            "first_seen_date": first_seen[pid][1],
        }
        for pid, status in sorted(last_status.items())
    }

    return ReplayResult(
        schema_version=SCHEMA_VERSION,
        engine_version=ENGINE_VERSION,
        profile=PROFILE_NAME,
        symbol=symbol,
        config_hash=cfg_hash,
        start_index=start_index,
        end_index=end,
        start_date=_iso_date(bars["date"].iloc[start_index]),
        end_date=_iso_date(bars["date"].iloc[end]),
        transitions=tuple(transitions),
        final_state=final_state,
    )


# ── Run manifest (requirement 3) — mirrors export.py's manifest split (content vs. run
#    metadata) and sim_diag/make_page_snapshot.py's sha256_file convention ─────────────────


def _dump(obj: dict) -> bytes:
    """Canonical, deterministic JSON bytes: sorted keys (list order, i.e. the event log's
    chronological order, is untouched by sort_keys), fixed separators, trailing newline."""
    return (json.dumps(obj, sort_keys=True, indent=2) + "\n").encode("utf-8")


def write_run(
    bars: pd.DataFrame,
    out_dir,
    *,
    cfg: dict = CONFIG,
    symbol: str = "UNKNOWN",
    start_index: int = 0,
    end_index: Optional[int] = None,
    incomplete_bar: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Run `replay()` and write its artifacts to `out_dir`, plus a `manifest.json` recording
    each artifact's relative path and SHA-256 hex digest (requirement 3). Returns the
    manifest dict actually written.

    Artifacts (requirement 2/4):
      - `results.json`      the full `ReplayResult.to_dict()` -- the primary, deterministic
                             output; byte-identical across repeated runs over the same input
                             (requirement 4 -- see test_replay.py's determinism test).
      - `events.json`       the append-only transition-event log alone (requirement 2's
                             explicit deliverable), same content as `results.json.transitions`.
      - `final_state.json`  the final per-pattern-instance state snapshot alone.

    `now` (defaults to the real wall clock) affects ONLY `manifest.json`'s `run_id` /
    `generated_at` fields -- pure run metadata, never part of the hashed artifact content, per
    requirement 4's "run manifest can note actual wall-clock run time as metadata."

    Sealed-window guard (review 2026-09-22, defect #1): `replay()` above already refuses a
    requested window that overlaps the sealed block, but this function additionally asserts
    (`research_window.assert_no_sealed_rows`) that no transition it is about to write ever
    landed on a sealed date -- a second, independent, defense-in-depth check on the actual
    OUTPUT artifacts, so a poisoned sealed row can never reach disk even if the first guard
    were ever bypassed.
    """
    result = replay(
        bars, cfg=cfg, symbol=symbol, start_index=start_index, end_index=end_index, incomplete_bar=incomplete_bar
    )
    assert_no_sealed_rows(t.event_date for t in result.transitions)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result_dict = result.to_dict()
    artifacts = {
        "results.json": result_dict,
        "events.json": {"transitions": result_dict["transitions"]},
        "final_state.json": {"final_state": result_dict["final_state"]},
    }

    written = []
    for name, payload in sorted(artifacts.items()):
        content = _dump(payload)
        (out_dir / name).write_bytes(content)
        written.append({"path": name, "sha256": _sha256_bytes(content)})

    now = now or datetime.now(timezone.utc)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": f"replay_{symbol}_{now.strftime('%Y%m%dT%H%M%SZ')}",
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "engine_version": ENGINE_VERSION,
        "profile": PROFILE_NAME,
        "config_hash": result.config_hash,
        "symbol": symbol,
        "replay_range": {
            "start_index": result.start_index,
            "end_index": result.end_index,
            "start_date": result.start_date,
            "end_date": result.end_date,
        },
        "artifacts": written,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return manifest
