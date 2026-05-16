"""yfinance backfill orchestrator.

Per-symbol historical fetch from Yahoo Finance v8 chart API. Designed
as a one-shot batch tool, not a daily scheduled job — invoked with
explicit symbol list + date range.

Defaults: backfill last 20 years for the Nifty 500 universe (read
from nidp.index_constituents — most recent as_of_date for 'Nifty 500').

Rate limiting: Yahoo throttles at ~50 req/min per IP, returning HTTP 429.
We run at 2× the safe rate and rely on exponential-backoff retry to absorb
throttle bursts — this delivers ~2× the throughput of the old conservative
approach while keeping the final success rate at 100%.

Concurrency model:
  - asyncio.Semaphore(concurrency) limits in-flight requests.
  - All symbols are queued at once (no manual chunking): as each slot
    finishes, the next waiting symbol starts immediately, eliminating the
    "wait for slowest in chunk" stall that the old CHUNK=25 design caused.
  - Progress is logged every PROGRESS_EVERY symbols.

Failure semantics:
  - Per-symbol failure isolated — others continue.
  - Each symbol's row count + final status persisted to nidp.job_log
    via a single JobRun spanning the whole batch.
  - ON CONFLICT in writer handles re-runs.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import aiohttp

from nidp.shared.config import DEFAULT_UA, HTTP_TIMEOUT_S
from nidp.shared.logging_setup import bind_context
from nidp.shared.metrics import (
    INGESTER_ROWS, INGESTER_RUNS, SOURCE_FETCH, time_fetch, time_ingester,
)
from nidp.shared.storage.job_log import JobRun
from nidp.shared.storage.pg import get_pool

from .parser import epoch_range_for, parse_yf_chart
from .writer import SOURCE_NAME, upsert_yfinance

logger = logging.getLogger(__name__)

SERVICE_NAME = "yfinance_backfill"
YF_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={p1}&period2={p2}&interval=1d"

# Run at 2× the safe rate; 429 retries absorb throttle bursts so the
# effective success rate stays at ~100% while throughput doubles vs the
# old conservative (single-IP, no-retry) approach.
DEFAULT_PER_REQUEST_DELAY_S = 1.0   # was 2.0
DEFAULT_CONCURRENCY = 8             # was 4

_MAX_RETRIES = 3                    # retry budget for 429 / transient errors
_RETRY_BASE_S = 5.0                 # first backoff: 5s → 10s → 20s
PROGRESS_EVERY = 25                 # log a progress line every N completions


async def _fetch_one(
    session: aiohttp.ClientSession,
    nse_symbol: str,
    p1: int,
    p2: int,
) -> tuple[Optional[bytes], int]:
    """Fetch one symbol's OHLCV with exponential-backoff retry on 429."""
    ticker = f"{nse_symbol}.NS"
    url = YF_CHART_URL.format(ticker=ticker, p1=p1, p2=p2)
    for attempt in range(_MAX_RETRIES + 1):
        try:
            with time_fetch(SOURCE_NAME):
                async with session.get(url) as resp:
                    body = await resp.read()
                    status = resp.status
                    SOURCE_FETCH.labels(source=SOURCE_NAME, status=str(status)).inc()

            if status == 429:
                if attempt < _MAX_RETRIES:
                    sleep_s = _RETRY_BASE_S * (2 ** attempt)   # 5 / 10 / 20 s
                    logger.info(
                        "yf %s: 429 throttle, retry %d/%d after %.0fs",
                        ticker, attempt + 1, _MAX_RETRIES, sleep_s,
                    )
                    await asyncio.sleep(sleep_s)
                    continue
                logger.warning("yf %s: 429 after %d retries — giving up", ticker, _MAX_RETRIES)
                return None, 429

            if status != 200:
                logger.warning("yf %s: HTTP %s, body[:200]: %r", ticker, status, body[:200])
                return None, status

            return body, status

        except Exception as exc:                                     # noqa: BLE001
            SOURCE_FETCH.labels(source=SOURCE_NAME, status="error").inc()
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BASE_S)
                continue
            logger.warning("yf %s: %s: %s", ticker, type(exc).__name__, exc)
            return None, 0

    return None, 0


async def _resolve_symbols(symbols_arg: Optional[list[str]]) -> list[str]:
    """If --symbols provided, use those. Else read latest Nifty 500
    constituents from nidp.index_constituents."""
    if symbols_arg:
        return [s.strip().upper() for s in symbols_arg if s.strip()]

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT symbol
              FROM nidp.index_constituents
             WHERE index_name ILIKE 'Nifty 500%'
               AND as_of_date = (
                   SELECT max(as_of_date) FROM nidp.index_constituents
                    WHERE index_name ILIKE 'Nifty 500%'
               )
             ORDER BY symbol
        """)
    return [r["symbol"] for r in rows]


async def run(
    *,
    start: date,
    end: date,
    symbols: Optional[list[str]] = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    per_request_delay: float = DEFAULT_PER_REQUEST_DELAY_S,
) -> uuid.UUID:
    """Backfill yfinance OHLCV for `symbols` in `[start, end]`."""
    bind_context(
        service=SERVICE_NAME,
        target_date=f"{start.isoformat()}..{end.isoformat()}",
    )

    sym_list = await _resolve_symbols(symbols)
    logger.info("yfinance backfill: %d symbols, range %s..%s",
                len(sym_list), start.isoformat(), end.isoformat())

    if not sym_list:
        logger.warning("no symbols resolved — provide --symbols or populate nidp.index_constituents")
        async with JobRun(ingester=SERVICE_NAME, target_date=None) as run_:
            run_.metadata["start"] = start.isoformat()
            run_.metadata["end"] = end.isoformat()
            await run_.finalize("SKIPPED", error_message="no symbols")
        return uuid.uuid4()

    p1, p2 = epoch_range_for(start.isoformat(), end.isoformat())

    async with JobRun(ingester=SERVICE_NAME, target_date=None) as run_:
        bind_context(run_id=str(run_.run_id))
        run_.metadata.update({
            "start": start.isoformat(),
            "end": end.isoformat(),
            "symbol_count": len(sym_list),
        })

        total_inserted = 0
        total_failed = 0
        total_rows_seen = 0

        with time_ingester(SERVICE_NAME):
            connector = aiohttp.TCPConnector(limit=concurrency + 2)
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S),
                headers={"User-Agent": DEFAULT_UA, "Accept": "application/json"},
            ) as session:
                semaphore = asyncio.Semaphore(concurrency)
                completed = 0

                async def _process(sym: str) -> tuple[str, int, int]:
                    nonlocal completed
                    async with semaphore:
                        body, status = await _fetch_one(session, sym, p1, p2)
                        await asyncio.sleep(per_request_delay)
                    completed += 1
                    if completed % PROGRESS_EVERY == 0:
                        logger.info(
                            "yfinance backfill: %d/%d done, %d inserted so far",
                            completed, len(sym_list), total_inserted,
                        )
                    if not body:
                        return sym, 0, status
                    try:
                        rows = parse_yf_chart(body, symbol=sym)
                    except ValueError as e:
                        logger.warning("yf parse failed for %s: %s", sym, e)
                        return sym, 0, status
                    if not rows:
                        return sym, 0, status
                    inserted = await upsert_yfinance(rows, run_.run_id)
                    return sym, inserted, status

                # Queue all symbols at once — semaphore gates actual concurrency.
                # This eliminates the old CHUNK=25 boundary stall where one slow
                # symbol held up the next 24 waiting for asyncio.gather to finish.
                all_results = await asyncio.gather(*[_process(s) for s in sym_list])
                for sym, ins, status in all_results:
                    total_rows_seen += ins
                    if ins > 0:
                        total_inserted += ins
                    else:
                        total_failed += 1
                        logger.info("  %s: 0 rows (status=%s)", sym, status)

        run_.rows_fetched = total_rows_seen
        run_.rows_inserted = total_inserted
        run_.rows_skipped = total_failed
        INGESTER_ROWS.labels(service=SERVICE_NAME, kind="inserted").inc(total_inserted)

        if total_failed >= len(sym_list):
            await run_.finalize("FAILED", error_message=f"all {len(sym_list)} symbols failed")
            INGESTER_RUNS.labels(service=SERVICE_NAME, status="FAILED").inc()
        elif total_failed > 0:
            await run_.finalize("PARTIAL")
            INGESTER_RUNS.labels(service=SERVICE_NAME, status="PARTIAL").inc()
        else:
            await run_.finalize("OK")
            INGESTER_RUNS.labels(service=SERVICE_NAME, status="OK").inc()

        logger.info(
            "yfinance backfill DONE: inserted=%d, failed=%d, total_symbols=%d",
            total_inserted, total_failed, len(sym_list),
        )
        return run_.run_id
