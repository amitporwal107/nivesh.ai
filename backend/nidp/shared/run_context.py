"""Run context shared by ingesters: is this run a backfill?

Gate 1's staleness check (G1-UNIV-004) must skip only for a deliberate backfill. Before this module the ingester
inferred "backfill" from the date's age (older than one day), so the check was skipped exactly when it could fail.

A run is a backfill when either:
  * it executes inside `backfill_context()` (nidp.backfill wraps every ingester call it makes, so feed_reconciler and
    dlq_redrive, which heal through nidp.backfill, are covered), or
  * the environment says so: NIDP_BACKFILL=1, for a manual `run_service.sh <feed> --date D` catch-up.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_BACKFILL: ContextVar[bool] = ContextVar("nidp_backfill", default=False)


def is_backfill_run() -> bool:
    """True inside backfill_context() or when NIDP_BACKFILL=1 is set."""
    if _BACKFILL.get():
        return True
    return os.environ.get("NIDP_BACKFILL", "").strip() in ("1", "true", "TRUE", "yes")


@contextmanager
def backfill_context() -> Iterator[None]:
    """Mark every ingester run inside the block as a backfill; the flag is reset afterwards, also on error."""
    token = _BACKFILL.set(True)
    try:
        yield
    finally:
        _BACKFILL.reset(token)
