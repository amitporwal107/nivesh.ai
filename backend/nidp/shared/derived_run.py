"""Helper to wrap derived (non-BaseIngester) pipelines with JobRun.

Derived pipelines (announcement_classifier, quality_gate, intelligence,
event_calendar, d1_prep, price_adjuster, event_day_poller, …) consume
already-ingested facts rather than fetching from external sources, so
they don't fit the BaseIngester loop. But the NIDP UI relies on
nidp.job_log for its run-history view, so derived runs MUST log there
too — otherwise the UI shows them as "never ran" even when they
succeed.

This helper wraps any async callable in a JobRun context, marking the
run OK on success and FAILED on exception (and re-raising so the CLI
exit code is preserved).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Awaitable, Callable, Optional

from nidp.shared.storage.job_log import JobRun

logger = logging.getLogger(__name__)


async def run_with_job_log(
    ingester: str,
    coro_fn: Callable[..., Awaitable[Any]],
    *args: Any,
    target_date: Optional[date] = None,
    source_url: Optional[str] = None,
    rows_inserted_attr: Optional[str] = None,
    **kwargs: Any,
) -> Any:
    """Execute ``coro_fn(*args, **kwargs)`` inside a JobRun context.

    On success → status=OK (with rows_inserted populated when extractable).
    On exception → status=FAILED (re-raised; callers see the original error).

    The pg pool is **not** closed here — the calling ``__main__`` is
    responsible for that, since JobRun's terminal write needs a live
    connection on both happy and exception paths.
    """
    async with JobRun(
        ingester=ingester,
        target_date=target_date,
        source_url=source_url,
    ) as run:
        result = await coro_fn(*args, **kwargs)
        inserted = _extract_rows_inserted(result, rows_inserted_attr)
        if inserted is not None:
            run.rows_inserted = inserted
        await run.finalize("OK")
        return result


def _extract_rows_inserted(result: Any, attr: Optional[str]) -> Optional[int]:
    """Best-effort extraction of a row count from common return shapes."""
    if result is None:
        return None
    if attr and hasattr(result, attr):
        v = getattr(result, attr)
        if isinstance(v, int):
            return v
    if isinstance(result, dict):
        for k in ("rows_inserted", "rows_written", "inserted",
                  "processed", "count"):
            v = result.get(k)
            if isinstance(v, int):
                return v
    if isinstance(result, int):
        return result
    return None
