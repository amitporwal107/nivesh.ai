"""Single source of truth for the project-wide sealed out-of-sample research window
(2023-01-01..2024-07-31, inclusive) — see `.claude/workspace/charting-pattern-engine/spec.md`
/ `test-plan.md` and `docs/ai_research/TPD_PROJECT_STATUS_2026-09-19.md:255` ("Jan 2023 - Jul
2024 can be used once"). This exact window is reused across multiple studies outside this
package too (MEMORY: TPD sealed tests, model v5 phases) — it is a fixed, project-wide
calendar rule, deliberately NOT derived from wherever any particular data file happens to
end/start (a future data refresh must not silently move this boundary).

Review 2026-09-22 (`.claude/workspace/charting-pattern-engine/review-prd-pattern-intelligence.md`,
defect #1) found this window enforced in exactly one place (`research.charting.context`, for
market/sector DATA AVAILABILITY) and nowhere else: `bars.py`, `replay.py`, `movement.py`,
`patterns.py`, `export.py` and `universe.py` had zero references to it, so a historical-
validation run over the real Kite bars (which run to 2026-09-18) could silently include
2023-01..2024-07 in a research result.

Two different kinds of consumer need this window for two different purposes, and this module
keeps both honest without letting either one weaken the other:

  1. `research.charting.context` (market/sector context lookups) already enforces it for DATA
     AVAILABILITY: a market/sector value for a sealed-window date is reported
     STATUS_UNAVAILABLE/REASON_SEALED_GAP, regardless of what the underlying source files
     contain. `context.py` imports `SEALED_GAP_START`/`SEALED_GAP_END` from here — its own
     names are kept as aliases so nothing downstream breaks — rather than defining them a
     second time: a project-wide constant lives in exactly one place.

  2. Every RESEARCH EVALUATION path (replay, movement/direction measurement, and any future
     study code) must REFUSE outright to evaluate a window that overlaps the sealed block.
     `research_bars()` / `assert_no_sealed_rows()` below are the guard for this — a research
     path calls one of them BEFORE (or immediately after) deciding what window it is about to
     evaluate, and the call raises `SealedWindowError` rather than silently narrowing or
     dropping rows: a research path that got this far already decided what window it means to
     evaluate, so silently trimming it would just hide the mistake instead of surfacing it.

Display/detection at the latest bar (charts, the live pattern-detector engine, the snapshot
exporter) legitimately uses the full history including the sealed block, and is deliberately
NOT restricted by this module — see `research.charting.export`, which never imports this
module at all.
"""
from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

SEALED_GAP_START = pd.Timestamp("2023-01-01")
SEALED_GAP_END = pd.Timestamp("2024-07-31")


class SealedWindowError(ValueError):
    """Raised when a research-evaluation path is asked to evaluate a window, or is handed an
    artifact whose own dates, that overlaps the sealed out-of-sample block. Never caught and
    silently worked around inside this package -- a research path that hits this must stop."""


def is_sealed_gap(date: Any) -> bool:
    """True if `date` falls inside the sealed window (inclusive of both ends)."""
    ts = pd.Timestamp(date).normalize()
    return SEALED_GAP_START <= ts <= SEALED_GAP_END


def overlaps_sealed_gap(start: Any, end: Any) -> bool:
    """True if the inclusive calendar-date range [start, end] overlaps the sealed window at
    all -- a PARTIAL overlap counts (a study window that starts in 2022 and runs into
    2023-02 is refused outright, never silently truncated to the safe part). `start`/`end`
    may be given in either order."""
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    if start_ts > end_ts:
        start_ts, end_ts = end_ts, start_ts
    return start_ts <= SEALED_GAP_END and end_ts >= SEALED_GAP_START


def research_bars(
    bars: pd.DataFrame, *, window: tuple[Any, Any] | None = None, date_column: str = "date"
) -> pd.DataFrame:
    """The guarded, research-evaluation entry point onto a bars frame: returns `bars`
    unchanged when the requested evaluation window does not overlap the sealed block, and
    RAISES `SealedWindowError` when it does. Never silently truncates/filters `bars` --
    a caller that wants to know "is this evaluation allowed at all" gets a definite yes (the
    same frame back) or a definite no (an exception), never a quietly narrowed frame.

    `window`: an explicit `(start, end)` calendar-date pair naming the evaluation window --
    e.g. the (start_date, end_date) a replay run is about to walk -- checked BEFORE the walk
    itself draws on `bars` at all. When omitted, the window defaults to `bars[date_column]`'s
    own (min, max) span, i.e. "does this bars frame, taken whole as the thing about to be
    evaluated, touch the sealed block at all".
    """
    if window is not None:
        start, end = window
    elif bars.empty:
        return bars
    else:
        col = bars[date_column]
        start, end = col.min(), col.max()

    if overlaps_sealed_gap(start, end):
        raise SealedWindowError(
            f"research evaluation window [{pd.Timestamp(start).date()}, {pd.Timestamp(end).date()}] "
            f"overlaps the sealed out-of-sample block [{SEALED_GAP_START.date()}, {SEALED_GAP_END.date()}] "
            "-- no research evaluation may touch this window (charts/display may; see module docstring)."
        )
    return bars


def assert_no_sealed_rows(dates: Iterable[Any]) -> None:
    """Assertion helper for an already-built research ARTIFACT (e.g. a replay's own
    transition-event dates, or a movement report's confirmed-event entry dates): raises
    `SealedWindowError` naming the first offending date if ANY date in `dates` falls inside
    the sealed window.

    A final, independent belt-and-braces check on the OUTPUT of a research computation --
    not a substitute for `research_bars()` / checking the intended window up front (that is
    what actually stops the evaluation from running at all); this is the second, defense-in-
    depth line that catches a poisoned sealed row even if the first one were ever bypassed.
    """
    for d in dates:
        if is_sealed_gap(d):
            raise SealedWindowError(
                f"sealed out-of-sample date {pd.Timestamp(d).date()} reached a research output "
                f"-- sealed window is [{SEALED_GAP_START.date()}, {SEALED_GAP_END.date()}]"
            )
