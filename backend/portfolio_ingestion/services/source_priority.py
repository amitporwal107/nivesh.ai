"""Source-priority rules for snapshot activation.

PRD §2.1 and §6 define the canonical priority order:

    1. OTP eCAS                 (highest)
    2. Gmail eCAS
    3. Uploaded eCAS
    4. Gmail CAMS / KFin
    5. Uploaded CAMS / KFin     (lowest)

The activation engine collapses this into a small set of rules:

  • eCAS always supersedes MF-only (CAMS / KFin)
  • Within the same tier, later ``statement_to`` wins
  • Same ``statement_to`` → higher ``priority`` int wins  (OTP > Gmail > Upload)

This module is pure functions and pure data; no I/O, no DB.
"""
from __future__ import annotations

import dataclasses
from enum import Enum


class SourceType(str, Enum):
    ECAS_CDSL = "ECAS_CDSL"
    ECAS_NSDL = "ECAS_NSDL"
    MF_CAMS = "MF_CAMS"
    MF_KFIN = "MF_KFIN"

    @property
    def is_ecas(self) -> bool:
        return self in (SourceType.ECAS_CDSL, SourceType.ECAS_NSDL)


class Method(str, Enum):
    UPLOAD = "upload"
    INBOX = "inbox"           # Gmail
    GENERATOR = "generator"   # KFintech mailback
    CDSL_FETCH = "cdsl_fetch" # OTP


# Method → priority (higher = more authoritative). Numbers are deliberately
# non-contiguous so we can slot new methods in without renumbering everywhere.
METHOD_PRIORITY: dict[Method, int] = {
    Method.CDSL_FETCH: 90,
    Method.INBOX: 70,
    Method.GENERATOR: 50,
    Method.UPLOAD: 30,
}


def method_priority(method: Method | str) -> int:
    """Return the priority for a method; unknown methods get 0 so they
    never beat a known method on a tie-break."""
    if isinstance(method, str):
        try:
            method = Method(method)
        except ValueError:
            return 0
    return METHOD_PRIORITY.get(method, 0)


@dataclasses.dataclass(frozen=True)
class SnapshotKey:
    """The minimal set of fields the priority logic needs to compare two
    snapshots. Avoids dragging the full row class into pure-function code."""
    source_type: SourceType
    statement_to: str           # ISO date 'YYYY-MM-DD' — comparison-safe lexically
    method_priority: int        # already resolved via :func:`method_priority`


def incoming_wins(incoming: SnapshotKey, current: SnapshotKey | None) -> bool:
    """Should ``incoming`` replace ``current`` as the active snapshot?

    The rule order is:

    1. No current active → incoming wins trivially.
    2. eCAS vs MF-only:
        - incoming eCAS, current MF → incoming wins.
        - incoming MF, current eCAS → incoming loses (never demote eCAS).
    3. Both same tier → later ``statement_to`` wins.
    4. Same tier + same ``statement_to`` → higher ``method_priority`` wins.
    5. Everything equal → incoming loses (status-quo bias; avoids needless churn).
    """
    if current is None:
        return True

    incoming_is_ecas = incoming.source_type.is_ecas
    current_is_ecas = current.source_type.is_ecas

    if incoming_is_ecas and not current_is_ecas:
        return True
    if (not incoming_is_ecas) and current_is_ecas:
        return False

    # Same tier — compare statement_to (lexical compare works for ISO dates)
    if incoming.statement_to > current.statement_to:
        return True
    if incoming.statement_to < current.statement_to:
        return False

    # Same tier + same statement_to — break ties by method priority
    return incoming.method_priority > current.method_priority
