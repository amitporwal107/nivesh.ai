"""The order state machine (F&O PRD §12.1).

    CREATED → VALIDATED → AUTHORIZED → SUBMITTED → ACKNOWLEDGED → PARTIALLY_FILLED → FILLED
    plus REJECTED, CANCEL_PENDING, CANCELLED, EXPIRED, UNKNOWN, RECONCILIATION_REQUIRED

Two rules carry most of the weight:
- UNKNOWN (a timeout, a lost acknowledgement) leads only to RECONCILIATION_REQUIRED. It never leads back to
  SUBMITTED: resubmitting an order whose fate is unknown is how a position gets doubled (PRD §14.3).
- CANCEL_PENDING can still receive a fill. A cancel request races the exchange; the fill that wins is real.
"""
from __future__ import annotations

from typing import Dict, FrozenSet

CREATED = "CREATED"
VALIDATED = "VALIDATED"
AUTHORIZED = "AUTHORIZED"
SUBMITTED = "SUBMITTED"
ACKNOWLEDGED = "ACKNOWLEDGED"
PARTIALLY_FILLED = "PARTIALLY_FILLED"
FILLED = "FILLED"
REJECTED = "REJECTED"
CANCEL_PENDING = "CANCEL_PENDING"
CANCELLED = "CANCELLED"
EXPIRED = "EXPIRED"
UNKNOWN = "UNKNOWN"
RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"

STATES = (CREATED, VALIDATED, AUTHORIZED, SUBMITTED, ACKNOWLEDGED, PARTIALLY_FILLED, FILLED,
          REJECTED, CANCEL_PENDING, CANCELLED, EXPIRED, UNKNOWN, RECONCILIATION_REQUIRED)

TERMINAL: FrozenSet[str] = frozenset({FILLED, REJECTED, CANCELLED, EXPIRED})

# Where each state may go next. Anything not listed is refused.
TRANSITIONS: Dict[str, FrozenSet[str]] = {
    CREATED: frozenset({VALIDATED, REJECTED}),
    VALIDATED: frozenset({AUTHORIZED, REJECTED}),
    AUTHORIZED: frozenset({SUBMITTED, REJECTED, CANCELLED}),          # cancelled before it was sent
    SUBMITTED: frozenset({ACKNOWLEDGED, PARTIALLY_FILLED, FILLED, REJECTED, CANCEL_PENDING, UNKNOWN}),
    ACKNOWLEDGED: frozenset({PARTIALLY_FILLED, FILLED, REJECTED, CANCEL_PENDING, EXPIRED, UNKNOWN}),
    PARTIALLY_FILLED: frozenset({PARTIALLY_FILLED, FILLED, CANCEL_PENDING, EXPIRED, UNKNOWN}),
    CANCEL_PENDING: frozenset({CANCELLED, PARTIALLY_FILLED, FILLED, UNKNOWN}),
    UNKNOWN: frozenset({RECONCILIATION_REQUIRED}),
    RECONCILIATION_REQUIRED: frozenset({ACKNOWLEDGED, PARTIALLY_FILLED, FILLED, REJECTED, CANCELLED,
                                        EXPIRED}),
    FILLED: frozenset(),
    REJECTED: frozenset(),
    CANCELLED: frozenset(),
    EXPIRED: frozenset(),
}


class IllegalTransition(ValueError):
    """A move the state machine does not allow. Carries both ends so the caller can say which."""

    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"an order cannot move from {current} to {target}")
        self.current, self.target = current, target


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


def check_transition(current: str, target: str) -> None:
    """Raise IllegalTransition unless `current → target` is allowed. Unknown names are refused too."""
    if current not in TRANSITIONS or target not in TRANSITIONS or not can_transition(current, target):
        raise IllegalTransition(current, target)
