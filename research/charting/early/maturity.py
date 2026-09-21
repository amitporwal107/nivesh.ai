"""§34.7.1 "Formation maturity without look-ahead" (approved by owner 2026-09-21).

"Percent of formation" needs the pattern's final length, which is only known after the
pattern ends. Computing a maturity checkpoint from it would leak the future into every
score recorded there. Two definitions are used, and this module keeps them syntactically
incapable of being merged: `live_maturity` has no parameter that could carry a future bar,
and `offline_checkpoint_index` returns only an integer bar index (`t_ck`) — never a score,
never a fraction derived from `t_end` — for the caller to hand to the scoring layer.

1. Live definition (engine, UI stage badge, any real-time use):
   `maturity = min(bars_since_first_detection / minimum_pattern_length, 1.0)`.
   It never references the unknown end of the pattern — `live_maturity()` below simply has
   no `t_end`/`bars`/"final length" parameter to leak one through even by mistake. This is
   the "trivial-pass" structural guarantee test-plan.md Part C asks be recorded: the live
   definition is unaffected by poisoning `t_end` *by construction*, not by a runtime check.

2. Offline retrospective definition (§34.7 validation study only): for a pattern that has
   already completed, the checkpoint bar is
       t_ck = t_start + round(f * (t_end - t_start))   for f in {0.2, 0.4, 0.6, 0.8}
   `t_end` may choose **which bar** becomes the example; it must never influence **the
   value recorded there**. `offline_checkpoint_index` computes `t_ck` from `t_start`/`t_end`
   as plain integer bar positions and returns it as the ONLY output that depends on
   `t_end` — callers must then score the checkpoint via
   `research.charting.early.scoring.compute_early_scores(bars, t_ck, ...)` (or
   `records.build_record_as_of` / `records.checkpoint_record`), which truncates to
   `bars[:t_ck+1]` before computing anything. `t_end` itself is never passed further.

Required test (test-plan.md Part C, `tests/test_early_lookahead.py` here): mutate every bar
after `t_ck`, including `t_end` itself, and recompute — the stored score must not change.
No `final_length` / `bars_to_breakout` field derived from `t_end` may appear in a checkpoint
score payload (see `scoring.EarlyScores` / `records.EarlyFormationRecord`: neither has one).

The offline study samples only patterns that completed, so it is conditioned on survival.
It must always be reported next to the live-definition study, which includes patterns that
later failed or expired (§34.7.1 last paragraph) — this package does not implement the
study itself (that is a later, separate deliverable), only the leak-free primitive it needs.
"""
from __future__ import annotations

from dataclasses import dataclass

from research.charting.config import CONFIG


@dataclass(frozen=True)
class LiveMaturity:
    bars_since_first_detection: int
    minimum_pattern_length: int
    maturity: float


def live_maturity(bars_since_first_detection: int, cfg: dict = CONFIG) -> LiveMaturity:
    """§34.7.1 definition 1. `maturity = min(bars_since_first_detection / minimum_pattern_length, 1.0)`.

    Deliberately takes no `bars`, no `t_end`, no "final length" — there is nothing in this
    function's signature capable of reading a future bar, which is the point.
    """
    if bars_since_first_detection < 0:
        raise ValueError(f"bars_since_first_detection must be >= 0, got {bars_since_first_detection}")
    min_len = cfg["minimum_pattern_length"]
    maturity = min(bars_since_first_detection / min_len, 1.0) if min_len > 0 else 0.0
    return LiveMaturity(
        bars_since_first_detection=bars_since_first_detection,
        minimum_pattern_length=min_len,
        maturity=float(maturity),
    )


@dataclass(frozen=True)
class OfflineCheckpoint:
    """The ONLY artifact of the offline definition that is allowed to know about `t_end`.
    Everything past this point in the pipeline sees `t_ck` alone — an ordinary bar index,
    indistinguishable from one produced by any live detection run."""

    fraction: float
    t_start: int
    t_end: int
    t_ck: int


def offline_checkpoint_index(t_start: int, t_end: int, fraction: float) -> OfflineCheckpoint:
    """§34.7.1 definition 2: `t_ck = t_start + round(f * (t_end - t_start))`.

    Uses Python's built-in `round()` (round-half-to-even). This is a bar INDEX, not a
    scored value, so the tie-breaking convention has no PIT implication either way.
    """
    if t_end < t_start:
        raise ValueError(f"t_end ({t_end}) must be >= t_start ({t_start})")
    if not (0.0 <= fraction <= 1.0):
        raise ValueError(f"fraction must be in [0, 1], got {fraction}")
    t_ck = t_start + round(fraction * (t_end - t_start))
    return OfflineCheckpoint(fraction=fraction, t_start=t_start, t_end=t_end, t_ck=t_ck)


def checkpoints_for(t_start: int, t_end: int, cfg: dict = CONFIG) -> list[OfflineCheckpoint]:
    """§34.9 AC5: the four maturity checkpoints (20/40/60/80%) are each evaluated. Reads the
    fractions from `CONFIG["early_maturity_checkpoints"]` (frozen elsewhere) rather than
    hard-coding them again here."""
    return [offline_checkpoint_index(t_start, t_end, f) for f in cfg["early_maturity_checkpoints"]]
