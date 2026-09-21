"""Pattern lifecycle state machine, independent component statuses, and the pattern
event record — PRD §11 (lifecycle), §13.9 (breakout/retest states), §17.3 (failure
classifications), §23.2 (pattern event record), and spec gap G-2 (`RESEARCH_ELIGIBLE`
definition, `.claude/workspace/charting-pattern-engine/spec.md:396`).

§11 requires the engine to "store separate booleans or statuses" for geometry,
price, volume, volatility, market, sector and data quality, and states plainly that
"a single opaque confidence score is insufficient." `PatternComponents` below is
that: seven independent fields, nothing derives one from another, and nothing here
ever collapses them into a composite score.

Spec gap G-2: §11 draws PRICE_CONFIRMED -> VOLUME_CONFIRMED -> CONTEXT_VALIDATED ->
RESEARCH_ELIGIBLE as a strict linear chain, but PRD §30's own recommended config sets
`require_volume_confirmation` / `require_market_alignment` / `require_sector_alignment`
all to `False` — so under the PRD's own defaults nothing could ever traverse that
chain. The resolution recorded in spec.md (frozen for the pre-registration) is: the
seven components are orthogonal, the §11 chain is the MAXIMUM state reached (not a
mandatory sequential gate), and `RESEARCH_ELIGIBLE` is defined directly by
`research_eligible()` below. `ALLOWED_TRANSITIONS` encodes this: PRICE_CONFIRMED may
jump straight to RESEARCH_ELIGIBLE when nothing downstream is required, matching the
predicate exactly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd

from research.charting.config import CONFIG, config_hash


# ── §11 lifecycle states ─────────────────────────────────────────────────────


class LifecycleState(str, Enum):
    # Primary chain (§11) — the maximum state reached; see spec G-2 in the module
    # docstring for why this is not a mandatory sequential gate.
    CANDIDATE = "CANDIDATE"
    FORMING = "FORMING"
    GEOMETRY_VALID = "GEOMETRY_VALID"
    BREAKOUT_ATTEMPT = "BREAKOUT_ATTEMPT"
    PRICE_CONFIRMED = "PRICE_CONFIRMED"
    VOLUME_CONFIRMED = "VOLUME_CONFIRMED"
    CONTEXT_VALIDATED = "CONTEXT_VALIDATED"
    RESEARCH_ELIGIBLE = "RESEARCH_ELIGIBLE"
    # Alternative / terminal states (§11)
    FAILED = "FAILED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    DATA_BLOCKED = "DATA_BLOCKED"
    UNRESOLVED = "UNRESOLVED"


# ── §13.9 breakout/retest states ─────────────────────────────────────────────


class RetestState(str, Enum):
    BREAKOUT_CONFIRMED = "BREAKOUT_CONFIRMED"
    RETEST_PENDING = "RETEST_PENDING"
    RETEST_SUCCESSFUL = "RETEST_SUCCESSFUL"
    RETEST_FAILED = "RETEST_FAILED"
    BREAKOUT_FAILED = "BREAKOUT_FAILED"


# ── §17.3 failure classifications ────────────────────────────────────────────


class FailureReason(str, Enum):
    FALSE_BREAKOUT = "FALSE_BREAKOUT"
    FAILED_RETEST = "FAILED_RETEST"
    LOW_VOLUME_FAILURE = "LOW_VOLUME_FAILURE"
    GAP_FAILURE = "GAP_FAILURE"
    MARKET_REVERSAL = "MARKET_REVERSAL"
    SECTOR_REVERSAL = "SECTOR_REVERSAL"
    DATA_FAILURE = "DATA_FAILURE"
    UNRESOLVED = "UNRESOLVED"


# ── §9.2 data status ──────────────────────────────────────────────────────────


class DataQualityStatus(str, Enum):
    VALID = "VALID"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    INVALID = "INVALID"
    PIT_UNVERIFIED = "PIT_UNVERIFIED"
    BLOCKED = "BLOCKED"


# ── Seven independent component statuses (§11) ───────────────────────────────


class ComponentStatus(str, Enum):
    """Status of one independently-tracked confirmation component. Deliberately NOT
    a score: PENDING/CONFIRMED/FAILED is the entire vocabulary, and a component's
    value never depends on any other component's value."""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


@dataclass
class PatternComponents:
    """§11's seven independently-tracked statuses for one pattern instance. No field
    is derived from another, and there is no aggregate/composite field anywhere on
    this class — PRD §11: "A single opaque confidence score is insufficient."

    `data_quality` defaults to PIT_UNVERIFIED (not VALID): a freshly-created
    candidate has not yet had its data validated, and PIT_UNVERIFIED is the "not
    proven yet" state per §9.2 / §32 — never assume validity by default.
    """

    geometry: ComponentStatus = ComponentStatus.PENDING
    price: ComponentStatus = ComponentStatus.PENDING
    volume: ComponentStatus = ComponentStatus.PENDING
    volatility: ComponentStatus = ComponentStatus.PENDING
    market: ComponentStatus = ComponentStatus.PENDING
    sector: ComponentStatus = ComponentStatus.PENDING
    data_quality: DataQualityStatus = DataQualityStatus.PIT_UNVERIFIED


# ── §23.2 pattern event record ───────────────────────────────────────────────


class RuleResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class PatternEvent:
    """A single rule evaluation, PRD §23.2 adapted for the offline research engine:
    `event_index`/`event_date` (this package's pivot_index/pivot_date convention,
    for point-in-time-safe replay) in place of a bare `event_timestamp`, and
    `config_hash` (frozen config identity, §21) in place of `data_version`.
    Immutable: an event is a fact about what a rule observed, once, at one bar.
    """

    event_type: str
    event_index: int
    event_date: pd.Timestamp
    rule_id: str
    rule_result: RuleResult
    observed_values: dict[str, Any]
    config_hash: str = field(default_factory=config_hash)


# ── Spec G-2: RESEARCH_ELIGIBLE predicate ────────────────────────────────────

# require_* config flag -> the PatternComponents field it gates. Only flags actually
# named `require_*` in config.py participate (require_close_confirmation maps to the
# `price` component that PRD §12.3 close-confirmation already governs).
REQUIRE_FLAG_TO_COMPONENT: dict[str, str] = {
    "require_close_confirmation": "price",
    "require_volume_confirmation": "volume",
    "require_market_alignment": "market",
    "require_sector_alignment": "sector",
}

_BLOCKING_DATA_QUALITY = frozenset(
    {DataQualityStatus.INVALID, DataQualityStatus.BLOCKED, DataQualityStatus.PIT_UNVERIFIED}
)


def research_eligible(components: PatternComponents, cfg: dict = CONFIG) -> bool:
    """Spec gap G-2's `RESEARCH_ELIGIBLE` predicate — the study's sample definition.

    True iff:
      - geometry AND price are CONFIRMED (always required, regardless of config), AND
      - data_quality is not in {INVALID, BLOCKED, PIT_UNVERIFIED}, AND
      - every `require_*` flag that is True in `cfg` has its mapped component CONFIRMED.

    Configurable via `cfg` so a study can freeze a variant config in the
    pre-registration (spec.md: "Build it as a configurable predicate; freeze the
    choice in the pre-registration before the run"). Defaults to the shared CONFIG.
    """
    if components.geometry != ComponentStatus.CONFIRMED:
        return False
    if components.price != ComponentStatus.CONFIRMED:
        return False
    if components.data_quality in _BLOCKING_DATA_QUALITY:
        return False
    for flag_key, component_name in REQUIRE_FLAG_TO_COMPONENT.items():
        if cfg.get(flag_key, False):
            if getattr(components, component_name) != ComponentStatus.CONFIRMED:
                return False
    return True


# ── Lifecycle transitions (deterministic) ────────────────────────────────────

_LIVE_STATES: tuple[LifecycleState, ...] = (
    LifecycleState.CANDIDATE,
    LifecycleState.FORMING,
    LifecycleState.GEOMETRY_VALID,
    LifecycleState.BREAKOUT_ATTEMPT,
    LifecycleState.PRICE_CONFIRMED,
    LifecycleState.VOLUME_CONFIRMED,
    LifecycleState.CONTEXT_VALIDATED,
)

# Absorbing: once reached, no further transition (RESEARCH_ELIGIBLE is the chain's
# success terminal; the rest are §11's alternative/terminal states). A pattern
# instance is an immutable-per-bar research artifact (plan.md: "no SQL migration --
# immutable run artifacts"), so there is no "un-blocking" edge out of DATA_BLOCKED
# etc. either — a later candidate would be a new pattern instance, not a resumption.
_TERMINAL_STATES: tuple[LifecycleState, ...] = (
    LifecycleState.FAILED,
    LifecycleState.INVALIDATED,
    LifecycleState.EXPIRED,
    LifecycleState.DATA_BLOCKED,
    LifecycleState.UNRESOLVED,
    LifecycleState.RESEARCH_ELIGIBLE,
)

# Primary §11 chain edges, plus the G-2 "skip" edges: PRICE_CONFIRMED may go straight
# to RESEARCH_ELIGIBLE (nothing downstream required) or to CONTEXT_VALIDATED (volume
# not required, market/sector are), and VOLUME_CONFIRMED may skip CONTEXT_VALIDATED
# (market/sector not required). These mirror research_eligible() exactly: they are
# reachable precisely when the corresponding require_* flags are false.
_PRIMARY_CHAIN_EDGES: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.CANDIDATE: frozenset({LifecycleState.FORMING}),
    LifecycleState.FORMING: frozenset({LifecycleState.GEOMETRY_VALID}),
    LifecycleState.GEOMETRY_VALID: frozenset({LifecycleState.BREAKOUT_ATTEMPT}),
    LifecycleState.BREAKOUT_ATTEMPT: frozenset({LifecycleState.PRICE_CONFIRMED}),
    LifecycleState.PRICE_CONFIRMED: frozenset(
        {
            LifecycleState.VOLUME_CONFIRMED,
            LifecycleState.CONTEXT_VALIDATED,
            LifecycleState.RESEARCH_ELIGIBLE,
        }
    ),
    LifecycleState.VOLUME_CONFIRMED: frozenset(
        {LifecycleState.CONTEXT_VALIDATED, LifecycleState.RESEARCH_ELIGIBLE}
    ),
    LifecycleState.CONTEXT_VALIDATED: frozenset({LifecycleState.RESEARCH_ELIGIBLE}),
}

ALLOWED_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    state: _PRIMARY_CHAIN_EDGES.get(state, frozenset()) | frozenset(_TERMINAL_STATES)
    for state in _LIVE_STATES
}
for _s in _TERMINAL_STATES:
    ALLOWED_TRANSITIONS[_s] = frozenset()


def transition(current: LifecycleState, target: LifecycleState) -> LifecycleState:
    """Validate a `current -> target` lifecycle move against `ALLOWED_TRANSITIONS`.

    Pure and deterministic: the same `(current, target)` pair always yields the same
    result (either `target`, or a raised `ValueError`) — no clock, no randomness, no
    hidden state. Self-transitions and any edge out of a terminal state are illegal.
    """
    current = LifecycleState(current)
    target = LifecycleState(target)
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise ValueError(f"illegal lifecycle transition: {current.value} -> {target.value}")
    return target


# §13.9: "Retest confirmation must be optional because requiring a retest can miss
# breakouts that continue without one" (§12.5) -> BREAKOUT_CONFIRMED may go straight
# to BREAKOUT_FAILED without ever visiting RETEST_PENDING.
RETEST_ALLOWED_TRANSITIONS: dict[RetestState, frozenset[RetestState]] = {
    RetestState.BREAKOUT_CONFIRMED: frozenset(
        {RetestState.RETEST_PENDING, RetestState.BREAKOUT_FAILED}
    ),
    RetestState.RETEST_PENDING: frozenset({RetestState.RETEST_SUCCESSFUL, RetestState.RETEST_FAILED}),
    RetestState.RETEST_SUCCESSFUL: frozenset(),
    RetestState.RETEST_FAILED: frozenset(),
    RetestState.BREAKOUT_FAILED: frozenset(),
}


def retest_transition(current: RetestState, target: RetestState) -> RetestState:
    """Same contract as `transition()`, for the §13.9 retest sub-state machine."""
    current = RetestState(current)
    target = RetestState(target)
    allowed = RETEST_ALLOWED_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise ValueError(f"illegal retest transition: {current.value} -> {target.value}")
    return target
