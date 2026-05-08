"""MFAPI.in historical NAV backfill ingester.

For each scheme_code in mf_scheme_master (or a CLI-supplied list), fetch
GET https://api.mfapi.in/mf/{scheme_code} and upsert NAV history.

MFAPI returns:
    {
      "meta": {"fund_house": "...", "scheme_type": "...", "scheme_code": 119551, ...},
      "data": [{"date": "07-05-2026", "nav": "520.45"}, ...],
      "status": "SUCCESS"
    }

Strategy:
    - Concurrent fetches with a semaphore (default 8) — MFAPI is
      reasonably tolerant but not infinite.
    - One JobRun spans the whole backfill; per-scheme failures are
      isolated and surfaced as a count.
    - --from / --to date filters to bound how much history we write.
    - --scheme-codes CSV optionally narrows to a list.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime
from typing import Optional

import aiohttp

from nidp.shared.config import (
    DEFAULT_UA, HTTP_TIMEOUT_S, MFAPI_SCHEME_URL,
)
from nidp.shared.logging_setup import bind_context
from nidp.shared.metrics import (
    INGESTER_ROWS, INGESTER_RUNS, SOURCE_FETCH, time_fetch, time_ingester,
)
from nidp.shared.storage.job_log import JobRun
from nidp.shared.storage.pg import get_pool

from .writer import SOURCE_NAME, upsert_history

logger = logging.getLogger(__name__)

SERVICE_NAME = "amfi_nav_history"

DEFAULT_CONCURRENCY = 8


def _parse_mfapi_date(s: str):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


async def _fetch_scheme(
    session: aiohttp.ClientSession, scheme_code: str,
) -> tuple[Optional[list[dict]], int]:
    url = MFAPI_SCHEME_URL.replace("{SCHEME_CODE}", scheme_code)
    try:
        with time_fetch(SOURCE_NAME):
            async with session.get(url) as resp:
                SOURCE_FETCH.labels(source=SOURCE_NAME, status=str(resp.status)).inc()
                if resp.status != 200:
                    return None, resp.status
                payload = await resp.json(content_type=None)
        if not isinstance(payload, dict) or payload.get("status") != "SUCCESS":
            return None, 0
        return payload.get("data") or [], 200
    except Exception as e:                                              # noqa: BLE001
        SOURCE_FETCH.labels(source=SOURCE_NAME, status="error").inc()
        logger.warning("MFAPI %s: %s: %s", scheme_code, type(e).__name__, e)
        return None, 0


async def _resolve_scheme_codes(
    explicit: Optional[list[str]],
) -> list[str]:
    if explicit:
        return [c for c in explicit if c.strip()]
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT scheme_code FROM nidp.mf_scheme_master "
            "WHERE status = 'active' ORDER BY scheme_code"
        )
    return [r["scheme_code"] for r in rows]


async def run(
    target_date: Optional[date] = None,
    *,
    scheme_codes: Optional[list[str]] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> uuid.UUID:
    """Backfill historical NAVs from MFAPI.in.

    target_date is bookkeeping-only. The actual range is bounded by
    from_date / to_date (None = unbounded on that side).
    """
    bind_context(service=SERVICE_NAME)
    as_of = target_date or date.today()

    codes = await _resolve_scheme_codes(scheme_codes)
    if not codes:
        raise RuntimeError("No scheme codes to backfill — populate mf_scheme_master "
                           "(run amfi_nav once) or pass --scheme-codes.")

    async with JobRun(ingester=SERVICE_NAME, target_date=as_of) as run:
        bind_context(run_id=str(run.run_id))
        run.source_url = MFAPI_SCHEME_URL
        sem = asyncio.Semaphore(concurrency)
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)
        headers = {"User-Agent": DEFAULT_UA, "Accept": "application/json"}

        total_inserted = 0
        total_failed = 0
        total_fetched = 0

        with time_ingester(SERVICE_NAME):
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:

                async def _one(code: str) -> None:
                    nonlocal total_inserted, total_failed, total_fetched
                    async with sem:
                        data, _ = await _fetch_scheme(session, code)
                    if data is None:
                        total_failed += 1
                        return
                    rows: list[dict] = []
                    for entry in data:
                        nav_date = _parse_mfapi_date(str(entry.get("date", "")))
                        nav_str = entry.get("nav")
                        if not nav_date or nav_str in (None, ""):
                            continue
                        try:
                            nav = float(nav_str)
                        except (TypeError, ValueError):
                            continue
                        if from_date and nav_date < from_date:
                            continue
                        if to_date and nav_date > to_date:
                            continue
                        rows.append({
                            "scheme_code": code,
                            "nav_date":    nav_date,
                            "nav":         nav,
                        })
                    if not rows:
                        return
                    total_fetched += len(rows)
                    inserted = await upsert_history(rows, run.run_id)
                    total_inserted += inserted

                await asyncio.gather(*[_one(c) for c in codes])

            run.rows_fetched = total_fetched
            run.rows_inserted = total_inserted
            run.rows_skipped = total_failed
            INGESTER_ROWS.labels(service=SERVICE_NAME, kind="fetched").inc(total_fetched)
            INGESTER_ROWS.labels(service=SERVICE_NAME, kind="inserted").inc(total_inserted)
            INGESTER_ROWS.labels(service=SERVICE_NAME, kind="skipped").inc(total_failed)

            partial = total_failed > 0 and total_inserted > 0
            failed = total_failed > 0 and total_inserted == 0
            if failed:
                final = "FAILED"
            elif partial:
                final = "PARTIAL"
            else:
                final = "OK"
            await run.finalize(final, error_message=(
                f"{total_failed}/{len(codes)} scheme fetches failed" if total_failed else None
            ))
            INGESTER_RUNS.labels(service=SERVICE_NAME, status=final).inc()
            return run.run_id
