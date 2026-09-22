"""37.6 Pattern research states -- docs/charting.md section 37.6 ("Amendment C -- Owner
decision baseline for validation", owner decision 2026-09-22):

    "Research states FORMING -> EARLY_SIGNAL -> BREAKOUT_CANDIDATE -> CONFIRMED_BREAKOUT ->
    FAILED_BREAKOUT / COMPLETED. Resolution: the section 11 lifecycle names are live on
    staging, so these are a derived `research_state` mapped from the section 11 state and
    the section 34 early stage, not a rename. An unconfirmed pattern is never called a
    breakout."

Owner course-correction (2026-09-22, relayed mid-task): "Don't let the research-state
calculation mutate the production pattern result" -- production `patterns.py` /
`research/charting/early/` stay untouched, and this module produces NOTHING by itself; it
is a pure function of already-computed values, called by a separate enrichment layer
(`research/charting/enrich.py`), never by `patterns.py` or `early/` themselves.

This module is a PURE function, `derive_research_state()`, with no bars/dates/I-O at all --
point-in-time correctness is therefore not this module's concern (its two inputs, the
section 11 `status` string and the section 34 `formation_stage` string, are already
point-in-time correct by construction of the modules that produced them; see
`research/charting/patterns.py` and `research/charting/early/records.py`).

-- Mapping table (every source value in both enums is listed; nothing unmapped silently --
an unknown value raises `ValueError`) --

section 11 lifecycle state (`research.charting.lifecycle.LifecycleState`, as stored verbatim
in a CONFIRMED-population `PatternSnapshot.status` string -- `research/charting/patterns.py`)
-> research_state:

    CANDIDATE          -> FORMING              -- not yet geometry-valid
    FORMING            -> FORMING              -- name match; still building structure
    GEOMETRY_VALID     -> EARLY_SIGNAL         -- structure valid, no close beyond the level yet
    BREAKOUT_ATTEMPT   -> EARLY_SIGNAL         -- wick-only breach: the owner's flow makes a
                                                   close beyond the level the entry into
                                                   BREAKOUT_CANDIDATE, so a wick alone stays an
                                                   early signal
    PRICE_CONFIRMED    -> BREAKOUT_CANDIDATE   -- close beyond the level, volume not confirmed
                          CONFIRMED_BREAKOUT   -- ... and the volume component is PASS/CONFIRMED
    CONTEXT_VALIDATED,
    RESEARCH_ELIGIBLE  -> same rule as PRICE_CONFIRMED (the section 11 chain can skip
                                                   VOLUME_CONFIRMED, so volume is read from the
                                                   component, not implied by the state)
    VOLUME_CONFIRMED   -> CONFIRMED_BREAKOUT
    FAILED             -> FAILED_BREAKOUT      -- section 17: a confirmed breakout that failed
    INVALIDATED,
    EXPIRED,
    DATA_BLOCKED,
    UNRESOLVED         -> None (not mapped)    -- these never broke out (invalidated / expired
                                                   before a breakout) or could not be assessed
                                                   (data); calling them FAILED_BREAKOUT would
                                                   say a breakout failed when none happened.
                                                   Left unmapped pending an owner decision on
                                                   two extra states (e.g. NOT_TRIGGERED,
                                                   INCONCLUSIVE); the enrichment record keeps
                                                   the source status as research_state_basis.

    COMPLETED is never produced from the lifecycle: completion (the move played out, e.g. a
    target reached) is an outcome (section 35.1: TARGET_REACHED lives in the outcome record),
    so it comes from the event dataset's exit labels, not from this mapping.

    Source of the flow (owner, 2026-09-22): "close > resistance -> BREAKOUT_CANDIDATE -> volume
    confirmation -> CONFIRMED_BREAKOUT". Review 2026-09-22 corrected the first version, which
    labelled every PRICE_CONFIRMED pattern CONFIRMED_BREAKOUT (on the 50 display symbols: 261
    price-confirmed, of which only 45 have a PASS volume component).

section 34 early formation stage (`research.charting.early.records.FormationStage`, EARLY
population only, `formation_stage` field of an `EarlyFormationRecord`) -> research_state:

    EARLY_FORMATION     -> FORMING              -- section 34.3 Stage 1
    PATTERN_DEVELOPING  -> EARLY_SIGNAL         -- section 34.3 Stage 2
    BREAKOUT_READINESS  -> BREAKOUT_CANDIDATE   -- section 34.3 Stage 3 (pre-trigger; section
                                                    34.2's own reconciliation table maps Stage 4
                                                    "Confirmation" onto section 11
                                                    BREAKOUT_ATTEMPT/PRICE_CONFIRMED onward --
                                                    i.e. the section 11 branch above, not this
                                                    one; `early/records.py` has no Stage-4 value
                                                    of its own to map here)

`direction` (BULLISH | BEARISH | NEUTRAL, matching both `PatternSnapshot.direction` and
`EarlyFormationRecord.direction`'s vocabularies) is validated but does not change which
bucket a pattern maps to -- included in the signature per the task brief, kept for
forward-compatible validation (an unrecognised direction raises, same "nothing unmapped
silently" discipline as the two state enums) rather than silently ignored.
"""
from __future__ import annotations

from research.charting.lifecycle import LifecycleState

# ── The six research_state values (section 37.6) ────────────────────────────────────────

FORMING = "FORMING"
EARLY_SIGNAL = "EARLY_SIGNAL"
BREAKOUT_CANDIDATE = "BREAKOUT_CANDIDATE"
CONFIRMED_BREAKOUT = "CONFIRMED_BREAKOUT"
FAILED_BREAKOUT = "FAILED_BREAKOUT"
COMPLETED = "COMPLETED"

RESEARCH_STATES = (FORMING, EARLY_SIGNAL, BREAKOUT_CANDIDATE, CONFIRMED_BREAKOUT, FAILED_BREAKOUT, COMPLETED)

_DIRECTIONS = ("BULLISH", "BEARISH", "NEUTRAL")

# section 11 status string -> research_state (see module docstring for the full table + reasoning)
_VOLUME_DEPENDENT = object()  # resolved from the volume component in derive_research_state

_LIFECYCLE_STATE_MAP: dict[str, object] = {
    LifecycleState.CANDIDATE.value: FORMING,
    LifecycleState.FORMING.value: FORMING,
    LifecycleState.GEOMETRY_VALID.value: EARLY_SIGNAL,
    LifecycleState.BREAKOUT_ATTEMPT.value: EARLY_SIGNAL,
    LifecycleState.PRICE_CONFIRMED.value: _VOLUME_DEPENDENT,
    LifecycleState.VOLUME_CONFIRMED.value: CONFIRMED_BREAKOUT,
    LifecycleState.CONTEXT_VALIDATED.value: _VOLUME_DEPENDENT,
    LifecycleState.RESEARCH_ELIGIBLE.value: _VOLUME_DEPENDENT,
    LifecycleState.FAILED.value: FAILED_BREAKOUT,
    LifecycleState.INVALIDATED.value: None,
    LifecycleState.EXPIRED.value: None,
    LifecycleState.DATA_BLOCKED.value: None,
    LifecycleState.UNRESOLVED.value: None,
}

# section 34 formation_stage string -> research_state (EARLY population; see module docstring)
_EARLY_STAGE_MAP: dict[str, str] = {
    "EARLY_FORMATION": FORMING,
    "PATTERN_DEVELOPING": EARLY_SIGNAL,
    "BREAKOUT_READINESS": BREAKOUT_CANDIDATE,
}

# Volume component values as stored on a pattern (served snapshots use PASS/FAIL/PENDING;
# lifecycle.ComponentStatus uses CONFIRMED/FAILED/PENDING). None = no component supplied.
_VOLUME_CONFIRMED_VALUES = frozenset({"PASS", "CONFIRMED"})
_VOLUME_VALUES = frozenset({"PASS", "CONFIRMED", "FAIL", "FAILED", "PENDING", None})

# section 37.6: "an unconfirmed pattern is never called a breakout" -- the section 11 states that
# may produce CONFIRMED_BREAKOUT, re-checked below independently of the map.
_CONFIRMED_BREAKOUT_STATES = frozenset({
    LifecycleState.PRICE_CONFIRMED.value, LifecycleState.VOLUME_CONFIRMED.value,
    LifecycleState.CONTEXT_VALIDATED.value, LifecycleState.RESEARCH_ELIGIBLE.value,
})


def derive_research_state(
    lifecycle_state: str | None, early_stage: str | None, direction: str, volume_status: str | None = None,
) -> str | None:
    """Pure mapping (section 11 lifecycle state, section 34 early stage where present,
    direction) -> research_state. Exactly ONE of `lifecycle_state` / `early_stage` must be
    given, never both and never neither -- they identify the two disjoint populations
    (`population: CONFIRMED` vs `population: EARLY`, see `research/charting/early/records.py`'s
    own module docstring) that this codebase's detectors already keep separate; a caller
    passing both, or neither, has a record whose population this function cannot honestly
    determine, so it raises rather than guessing.

    Raises `ValueError` for any value outside the closed sets documented in the module
    docstring's mapping table -- a typo, or a state/stage this module has not been updated
    for after a `lifecycle.py` / `early/records.py` change, is a bug to surface, not to
    silently default.
    """
    if direction not in _DIRECTIONS:
        raise ValueError(f"unknown direction: {direction!r} (expected one of {_DIRECTIONS})")

    if (lifecycle_state is None) == (early_stage is None):
        raise ValueError(
            "exactly one of lifecycle_state (CONFIRMED population, research.charting.patterns) or "
            "early_stage (EARLY population, research.charting.early) must be given, never both or "
            f"neither: lifecycle_state={lifecycle_state!r} early_stage={early_stage!r}"
        )

    if volume_status is not None:
        volume_status = str(volume_status).upper()
    if volume_status not in _VOLUME_VALUES:
        raise ValueError(f"unknown volume component status: {volume_status!r}")

    if lifecycle_state is not None:
        if lifecycle_state not in _LIFECYCLE_STATE_MAP:
            raise ValueError(f"unknown section-11 lifecycle state: {lifecycle_state!r}")
        research_state = _LIFECYCLE_STATE_MAP[lifecycle_state]
        if research_state is _VOLUME_DEPENDENT:
            research_state = CONFIRMED_BREAKOUT if volume_status in _VOLUME_CONFIRMED_VALUES else BREAKOUT_CANDIDATE
    else:
        if early_stage not in _EARLY_STAGE_MAP:
            raise ValueError(f"unknown section-34 early formation stage: {early_stage!r}")
        research_state = _EARLY_STAGE_MAP[early_stage]

    # Independent re-check of section 37.6's rule.
    if research_state == CONFIRMED_BREAKOUT and not (
        lifecycle_state == LifecycleState.VOLUME_CONFIRMED.value
        or (lifecycle_state in _CONFIRMED_BREAKOUT_STATES and volume_status in _VOLUME_CONFIRMED_VALUES)
    ):
        raise AssertionError(
            f"internal mapping error: {lifecycle_state!r} / volume {volume_status!r} produced CONFIRMED_BREAKOUT "
            "without a price-confirmed state and a confirmed volume component -- section 37.6 forbids this"
        )
    if research_state == COMPLETED:
        raise AssertionError("internal mapping error: COMPLETED comes from outcomes, never from the lifecycle")

    return research_state
