"""Signal & alert contract -- Phase 1 of the live-signals PRD (§36), and the ONLY phase that may be
written before study plan v2 reports (docs/charting.md §38.19 Amendment E, position 1).

§36 Phase 1 asks for six things to be defined and frozen: signal states, state transitions, the
signal schema, the alert schema, versioning, and timestamp semantics. All six live here, in one
module, so there is a single place to read them and a single hash to compare -- the same shape as
`research/charting/indicator_catalogue.py`, which is already this repo's pattern for a frozen,
versioned, exported contract.

This module computes nothing and reads nothing. It is declarations plus pure validators, so it can
be imported by the research pipeline (which will produce signals) and by the backend (which will
serve them) without either pulling in the other's dependencies.

WHAT THIS MODULE DELIBERATELY DOES NOT CONTAIN
----------------------------------------------
- No 0-100 headline score. Amendment E position 2 removed it: the seven component bars stay, the
  single number goes, and any composite is a research object -- pre-registered in a later study
  version, tested, then shown. `SIGNAL_FIELDS` therefore carries `score_components` and no `score`.
- No entry / stop / target values. Amendment E position 3 keeps them owner-allowlist-only until the
  SEBI RA/IA question (NI-1a) is answered. The schema reserves the fields so the shape is frozen,
  and `OWNER_ONLY_FIELDS` names them so a serving layer can strip them without guessing.
- No detection, no state derivation. `research/charting/states.py` already derives a research state
  from a §11 lifecycle status; this module validates transitions between states, which is a
  different job.

GAP CLOSED 2026-09-23
--------------------
This module used to declare eight states while `states.py` produced six and None for the rest,
because owner decision #110 (`docs/ai_research/CHARTING_NI3_PREDICATES_V1.md` §1.2) had been made
but never wired:

    INVALIDATED or EXPIRED before any BREAKOUT_CANDIDATE -> NOT_TRIGGERED
    DATA_BLOCKED or UNRESOLVED                           -> INCONCLUSIVE

It is now wired. `states.RESEARCH_STATES` carries all eight and the two sets are equal, which
`tests/test_signal_contract.py` asserts. One nuance survives: the "before any BREAKOUT_CANDIDATE"
precondition is not visible to a pure mapping over a terminal status, so `derive_research_state`
takes `ever_price_confirmed` and leaves the row unmapped when the caller cannot supply it --
"we do not know" never becomes NOT_TRIGGERED.
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from research.charting import pattern_registry

CONTRACT_VERSION = "1.0.0"

# ── 1. Signal states ────────────────────────────────────────────────────────────────────────────
# The research names are canonical (Amendment E position 4). The first six are exactly
# `states.RESEARCH_STATES`; the last two come from owner decision #110.
FORMING = "FORMING"
EARLY_SIGNAL = "EARLY_SIGNAL"
BREAKOUT_CANDIDATE = "BREAKOUT_CANDIDATE"
CONFIRMED_BREAKOUT = "CONFIRMED_BREAKOUT"
FAILED_BREAKOUT = "FAILED_BREAKOUT"
COMPLETED = "COMPLETED"
NOT_TRIGGERED = "NOT_TRIGGERED"
INCONCLUSIVE = "INCONCLUSIVE"

SIGNAL_STATES: tuple[str, ...] = (
    FORMING, EARLY_SIGNAL, BREAKOUT_CANDIDATE, CONFIRMED_BREAKOUT,
    FAILED_BREAKOUT, COMPLETED, NOT_TRIGGERED, INCONCLUSIVE,
)

#: A signal in a terminal state never transitions again; a new structure starts a new signal row.
TERMINAL_STATES: frozenset[str] = frozenset({FAILED_BREAKOUT, COMPLETED, NOT_TRIGGERED, INCONCLUSIVE})

#: The PRD's own state names -> the canonical research names (Amendment E position 4, frozen).
#: PRD "INVALIDATED" is deliberately absent: it is not one state. Invalidation BEFORE any breakout is
#: NOT_TRIGGERED and a confirmed breakout that later failed is FAILED_BREAKOUT (#110). They are two
#: distinct states and Amendment E says they must not be merged, so mapping one PRD word onto them
#: would merge them. `prd_state()` raises on it with that explanation rather than picking one.
PRD_STATE_ALIASES: dict[str, str] = {
    "WATCH": FORMING,
    "READY": EARLY_SIGNAL,
    "TRIGGERED": BREAKOUT_CANDIDATE,
    "CONFIRMED": CONFIRMED_BREAKOUT,
    "NOT_TRIGGERED": NOT_TRIGGERED,
    "INCONCLUSIVE": INCONCLUSIVE,
}

#: RETEST and CONTINUATION are events recorded on the signal row, never states (Amendment E
#: position 4). Keeping them out of SIGNAL_STATES is what stops a retest overwriting the lifecycle.
ROW_EVENTS: tuple[str, ...] = ("RETEST_HELD", "RETEST_FAILED", "CONTINUATION")


# ── 2. State transitions ────────────────────────────────────────────────────────────────────────
#: Legal successors per state. A structure may be abandoned (NOT_TRIGGERED) or become unassessable
#: (INCONCLUSIVE) from any non-terminal state, so both appear widely; the forward path is strictly
#: ordered, and nothing returns to an earlier state -- a pattern that re-forms is a new signal row
#: (§22 "records are never modified in place").
TRANSITIONS: dict[str, frozenset[str]] = {
    FORMING: frozenset({EARLY_SIGNAL, NOT_TRIGGERED, INCONCLUSIVE}),
    EARLY_SIGNAL: frozenset({BREAKOUT_CANDIDATE, NOT_TRIGGERED, INCONCLUSIVE}),
    BREAKOUT_CANDIDATE: frozenset({CONFIRMED_BREAKOUT, FAILED_BREAKOUT, NOT_TRIGGERED, INCONCLUSIVE}),
    CONFIRMED_BREAKOUT: frozenset({FAILED_BREAKOUT, COMPLETED, INCONCLUSIVE}),
    FAILED_BREAKOUT: frozenset(),
    COMPLETED: frozenset(),
    NOT_TRIGGERED: frozenset(),
    INCONCLUSIVE: frozenset(),
}


class InvalidTransition(ValueError):
    """A state change the contract does not allow."""


def prd_state(name: str) -> str:
    """Map a PRD state word to its canonical research state. Raises on an unknown word, and on
    "INVALIDATED" specifically -- see PRD_STATE_ALIASES for why that one cannot be a single state."""
    key = (name or "").strip().upper()
    if key == "INVALIDATED":
        raise ValueError(
            "PRD 'INVALIDATED' maps to two distinct research states and must not be merged: "
            f"{NOT_TRIGGERED} when the structure was invalidated before any breakout, "
            f"{FAILED_BREAKOUT} when a confirmed breakout later failed (#110)."
        )
    if key not in PRD_STATE_ALIASES:
        raise ValueError(f"unknown PRD state {name!r}; known: {sorted(PRD_STATE_ALIASES)}")
    return PRD_STATE_ALIASES[key]


def is_terminal(state: str) -> bool:
    _require_state(state)
    return state in TERMINAL_STATES


def can_transition(frm: str, to: str) -> bool:
    _require_state(frm)
    _require_state(to)
    return to in TRANSITIONS[frm]


def validate_transition(frm: str, to: str) -> None:
    """Raise InvalidTransition unless `frm -> to` is allowed. Same-state is not a transition and is
    rejected: a row that did not change state must not write a new lifecycle entry, or the audit
    trail fills with duplicates that look like real events."""
    if not can_transition(frm, to):
        if frm == to:
            raise InvalidTransition(f"{frm} -> {to}: a state does not transition to itself")
        if frm in TERMINAL_STATES:
            raise InvalidTransition(f"{frm} is terminal; start a new signal row instead of leaving it")
        raise InvalidTransition(f"{frm} -> {to} is not a legal transition; legal: {sorted(TRANSITIONS[frm])}")


def _require_state(state: str) -> None:
    if state not in TRANSITIONS:
        raise ValueError(f"unknown signal state {state!r}; known: {list(SIGNAL_STATES)}")


# ── 3. Timestamp semantics ──────────────────────────────────────────────────────────────────────
#: Three distinct times, kept separate because collapsing any two of them is how look-ahead leaks in.
#: §22-§24 (versioning, fingerprint, no look-ahead) and NI-3 §1.1 depend on this separation.
TIMESTAMP_FIELDS: dict[str, str] = {
    "bar_time": "Open time of the bar that caused the state change, in IST, on the signal's own timeframe.",
    "known_at": "The earliest moment the detector could have known it -- the CLOSE of that bar, never its open. "
                "A signal is never attributable to a bar that had not finished.",
    "published_at": "When this row was written. Used for latency measurement only; it must never feed detection, "
                    "or a slow pipeline would change the signal.",
}

#: Ordering the three must satisfy. Checked by `validate_timestamps`.
TIMESTAMP_RULE = "bar_time < known_at <= published_at"


def validate_timestamps(bar_time, known_at, published_at) -> None:
    """Enforce TIMESTAMP_RULE. Comparable values only (datetimes, or anything with a total order);
    this module does not parse strings, so a caller cannot get a false pass from mixed formats."""
    if bar_time is None or known_at is None or published_at is None:
        raise ValueError("bar_time, known_at and published_at are all required")
    if not bar_time < known_at:
        raise ValueError(f"bar_time must precede known_at ({TIMESTAMP_RULE}); a bar is known at its close, not its open")
    if not known_at <= published_at:
        raise ValueError(f"known_at must not follow published_at ({TIMESTAMP_RULE}); that would publish before knowing")


# ── 4. Signal schema ────────────────────────────────────────────────────────────────────────────
#: field -> one-line meaning. Frozen; adding a field bumps CONTRACT_VERSION and changes the hash.
SIGNAL_FIELDS: dict[str, str] = {
    "signal_id": "Stable id for this signal row. Records are never modified in place (§22).",
    "symbol": "NSE trading symbol.",
    "timeframe": "One of TIMEFRAMES. Every signal and every alert displays it (§17).",
    "pattern_id": "The detector record this signal was adapted from.",
    "pattern_type": "A family in `pattern_registry.FAMILIES`. Only an ENABLED family may produce an alert "
                    "(the registry is the single source of truth; the PRD §7 list of 14 is superseded).",
    "direction": "BULLISH or BEARISH.",
    "state": "One of SIGNAL_STATES.",
    "state_basis": "The §11 lifecycle status the state was derived from, kept for audit.",
    "bar_time": TIMESTAMP_FIELDS["bar_time"],
    "known_at": TIMESTAMP_FIELDS["known_at"],
    "published_at": TIMESTAMP_FIELDS["published_at"],
    "level": "The live breakout/breakdown level this signal is measured against.",
    "volume_ratio": "Breakout-bar volume / 20-session average. Always stored, pass or fail (#109/#110).",
    "score_components": "The seven §12 component values. Components only -- there is no headline number.",
    "events": "Row events from ROW_EVENTS, each with its own bar_time.",
    "contract_version": "CONTRACT_VERSION this row was written under.",
    "config_hash": "The detector config hash, so a row is reproducible.",
    # Reserved now so the shape is frozen; stripped by the serving layer until NI-1a is answered.
    "entry": "Reference entry from the frozen definitions. OWNER-ONLY until SEBI RA/IA (NI-1a).",
    "stop": "NI-3 Layer-1 structural stop widened to >= 0.75 x ATR(14). OWNER-ONLY until NI-1a.",
    "targets": "The v2 target set (+2/+3/+5/+10% and 1/1.5/2/3 R). OWNER-ONLY until NI-1a.",
}

#: Fields a serving layer must strip for anyone not on the owner allowlist (Amendment E position 3).
OWNER_ONLY_FIELDS: frozenset[str] = frozenset({"entry", "stop", "targets"})

#: §17. Detection on weekly/monthly stays out; these are the monitoring timeframes.
TIMEFRAMES: tuple[str, ...] = ("15minute", "60minute", "day")


# ── 5. Alert schema ─────────────────────────────────────────────────────────────────────────────
#: §14 alert types, each tied to the state change that raises it. PATTERN/READY/BREAKOUT/CONFIRMATION
#: /FAILURE map to transitions; RETEST is raised by a row event, not a state change.
ALERT_TYPES: dict[str, str] = {
    "PATTERN": f"a new structure reached {FORMING}",
    "READY": f"-> {EARLY_SIGNAL} (within the 1% readiness band, NI-3 S9)",
    "BREAKOUT": f"-> {BREAKOUT_CANDIDATE} (close beyond the level by the breakout threshold)",
    "CONFIRMATION": f"-> {CONFIRMED_BREAKOUT} (breakout-bar volume >= 1.5x)",
    "FAILURE": f"-> {FAILED_BREAKOUT}",
    "RETEST": "a RETEST_HELD or RETEST_FAILED row event",
}

ALERT_FIELDS: dict[str, str] = {
    "alert_id": "Stable id for this alert.",
    "signal_id": "The signal row it belongs to.",
    "alert_type": "One of ALERT_TYPES.",
    "symbol": "NSE trading symbol.",
    "timeframe": "Repeated on the alert because §17 requires every alert to display it.",
    "state": "The signal state at the moment the alert was raised.",
    "bar_time": TIMESTAMP_FIELDS["bar_time"],
    "known_at": TIMESTAMP_FIELDS["known_at"],
    "published_at": TIMESTAMP_FIELDS["published_at"],
    "dedupe_key": "See dedupe_key(). Identical keys are the same alert.",
    "contract_version": "CONTRACT_VERSION this alert was written under.",
}

#: §16. The tuple that makes two alerts the same alert.
DEDUPE_FIELDS: tuple[str, ...] = ("symbol", "timeframe", "pattern_type", "state", "bar_time")


def dedupe_key(symbol: str, timeframe: str, pattern_type: str, state: str, bar_time) -> str:
    """§16 deduplication key: symbol + timeframe + pattern + state + bar. Two alerts with the same
    key are the same alert and the later one is suppressed. `bar_time` -- not wall-clock -- is what
    makes a re-run of the same bar produce the same key instead of a duplicate.

    Minting an alert identity is the narrowest point every alert must pass through, so the registry
    invariant is enforced here: a family with no validated detector raises rather than quietly
    getting a key. Research code that needs a key for a disabled family should not be using the
    ALERT dedupe key."""
    pattern_registry.assert_alertable(pattern_type)
    _require_state(state)
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"unknown timeframe {timeframe!r}; known: {list(TIMEFRAMES)}")
    return "|".join([symbol, timeframe, pattern_type, state, getattr(bar_time, "isoformat", lambda: str(bar_time))()])


# ── 6. Versioning ───────────────────────────────────────────────────────────────────────────────
def serialisable() -> dict:
    """The whole contract as plain data, for export into a snapshot manifest and for the hash."""
    return {
        "version": CONTRACT_VERSION,
        "states": list(SIGNAL_STATES),
        "terminal_states": sorted(TERMINAL_STATES),
        "prd_state_aliases": dict(PRD_STATE_ALIASES),
        "row_events": list(ROW_EVENTS),
        "transitions": {k: sorted(v) for k, v in TRANSITIONS.items()},
        "timestamp_fields": dict(TIMESTAMP_FIELDS),
        "timestamp_rule": TIMESTAMP_RULE,
        "signal_fields": dict(SIGNAL_FIELDS),
        "owner_only_fields": sorted(OWNER_ONLY_FIELDS),
        "timeframes": list(TIMEFRAMES),
        "alert_types": dict(ALERT_TYPES),
        "alert_fields": dict(ALERT_FIELDS),
        "dedupe_fields": list(DEDUPE_FIELDS),
        # The registry this contract was frozen against: an alert's legality depends on both.
        "pattern_registry_version": pattern_registry.REGISTRY_VERSION,
        "pattern_registry_hash": pattern_registry.registry_hash(),
        "alertable_families": [f.pattern_type for f in pattern_registry.enabled_families()],
    }


def contract_hash() -> str:
    """Stable sha256 of the contract. Changes whenever any declaration above changes, so a stored
    signal row can be checked against the contract it was written under."""
    return hashlib.sha256(json.dumps(serialisable(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
