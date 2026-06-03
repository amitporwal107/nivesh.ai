"""Gate 6 — API Output Gate middleware.

Adds data-quality context to every authenticated /v1/* response:

  * Response header  X-DQ-Status: GREEN | AMBER | RED
  * Response header  X-DQ-As-Of-Date: YYYY-MM-DD
  * Response header  X-DQ-Snapshot-Id: <uuid>

The full DQ envelope (degraded feeds, staleness, gate verdicts) is
available at GET /v1/dq/status  (see routers/dq_status.py).

Performance contract: the middleware reads a single row from
dq.snapshot_status (indexed on target_date DESC) in < 5ms.  Cache TTL
is 5 minutes — the table is updated at most once per trading day.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, timedelta
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)

# ── In-process cache ─────────────────────────────────────────────────────────

_CACHE_TTL_SECS = 300      # 5 minutes

class _DQCache:
    def __init__(self) -> None:
        self._status:   Optional[str] = None
        self._date:     Optional[str] = None
        self._snap_id:  Optional[str] = None
        self._fetched_at: float = 0.0
        self._lock      = asyncio.Lock()

    def _expired(self) -> bool:
        return (time.monotonic() - self._fetched_at) > _CACHE_TTL_SECS

    async def get(self) -> tuple[str, str, str]:
        """Returns (dq_status, as_of_date_str, snapshot_id_str)."""
        if not self._expired() and self._status is not None:
            return self._status, self._date, self._snap_id

        async with self._lock:
            # Double-check inside lock
            if not self._expired() and self._status is not None:
                return self._status, self._date, self._snap_id
            try:
                pool = await get_pool()
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        """
                        SELECT status, target_date, id::text AS snap_id
                        FROM dq.snapshot_status
                        ORDER BY target_date DESC
                        LIMIT 1
                        """
                    )
                if row:
                    raw = row["status"]   # PASS | BLOCKED | PARTIAL | PENDING
                    self._status   = _map_dq_status(raw)
                    self._date     = str(row["target_date"])
                    self._snap_id  = str(row["snap_id"])
                else:
                    # No Gate 3 run yet — serve GREEN with null snapshot
                    self._status  = "GREEN"
                    self._date    = str(date.today())
                    self._snap_id = ""
                self._fetched_at = time.monotonic()
            except Exception as exc:                                # noqa: BLE001
                logger.debug("dq_middleware: cache refresh failed: %s", exc)
                # Fail-open: don't break the API on a DQ cache miss
                self._status  = self._status or "GREEN"
                self._date    = self._date    or str(date.today())
                self._snap_id = self._snap_id or ""
                self._fetched_at = time.monotonic()

        return self._status, self._date, self._snap_id


_cache = _DQCache()


def _map_dq_status(gate3_status: str) -> str:
    """Map Gate 3 snapshot_status.status → DQ envelope status."""
    return {
        "PASS":    "GREEN",
        "PARTIAL": "AMBER",
        "PENDING": "AMBER",
        "BLOCKED": "RED",
    }.get(gate3_status, "AMBER")


# ── Middleware ────────────────────────────────────────────────────────────────

class DQStatusMiddleware(BaseHTTPMiddleware):
    """Injects X-DQ-Status / X-DQ-As-Of-Date headers on every /v1/* response.

    Failures in the DQ lookup must NEVER affect API availability.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Only decorate authenticated /v1/* paths
        if not request.url.path.startswith("/v1/"):
            return response

        try:
            dq_status, as_of_date, snap_id = await _cache.get()
            response.headers["X-DQ-Status"]      = dq_status
            response.headers["X-DQ-As-Of-Date"]  = as_of_date
            if snap_id:
                response.headers["X-DQ-Snapshot-Id"] = snap_id
        except Exception as exc:                                    # noqa: BLE001
            logger.debug("dq_middleware: header injection failed: %s", exc)

        return response
