"""nse_financials_backfill — batch historical quarterly financials ingester.

For every symbol in the Nifty 500 (or a supplied list):
  1. Fetch NSE XBRL comparator (Standalone + Consolidated) → up to 8 quarters
  2. If quarters < MIN_QUARTERS_TARGET, fall back to Screener.in → up to 20 quarters
  3. Upsert all rows to nidp.nse_financials_quarterly

Rate limiting:
  - NSE: ~30 req/min (needs session cookie rotation)
  - Screener.in: ~20 req/min  (polite; no account required for basic data)

Design:
  - Per-symbol failure is isolated — others continue.
  - Idempotent — ON CONFLICT in writer does coalesce-update.
  - Progress logged per-symbol with quarter count.
  - Single JobRun spans the whole batch.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date
from typing import Any, Dict, List, Optional

import aiohttp

from nidp.shared.config import DEFAULT_UA, HTTP_TIMEOUT_S
from nidp.shared.logging_setup import bind_context
from nidp.shared.metrics import INGESTER_ROWS, INGESTER_RUNS, time_ingester
from nidp.shared.storage.job_log import JobRun
from nidp.shared.storage.pg import get_pool

from nidp.services.nse_financials.writer import upsert_financials

from .parser import parse_nse_xbrl_multi_quarter, parse_screener_quarters

logger = logging.getLogger(__name__)

SERVICE_NAME = "nse_financials_backfill"

# Screener delivers 20 quarters; NSE XBRL ~ 4-8.
# If NSE returns fewer than this, fall back to Screener.
MIN_QUARTERS_TARGET = 8

DEFAULT_CONCURRENCY = 8          # was 5 — NSE tolerates 8 with proper cookies
PER_REQUEST_DELAY_S = 1.5        # was 2.5 — 1.5s keeps us within ~30 NSE req/min

_MAX_RETRIES = 3                 # retry budget for 403/429/connection errors
_RETRY_BASE_S = 4.0              # first backoff 4s → 8s → 16s
_SESSION_REFRESH_EVERY = 40      # re-hit NSE homepage every N symbols to refresh cookies

NSE_XBRL_URL = (
    "https://www.nseindia.com/api/results-comparator"
    "?params={symbol}&period=Quarterly&type={type}"
)
SCREENER_URL = "https://www.screener.in/company/{symbol}/consolidated/"


_HEADERS_NSE = {
    "User-Agent": DEFAULT_UA,
    "Accept":     "application/json, text/javascript, */*; q=0.01",
    "Referer":    "https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
    "X-Requested-With": "XMLHttpRequest",
}

_HEADERS_SCREENER = {
    "User-Agent": DEFAULT_UA,
    "Accept":     "text/html,application/xhtml+xml",
    "Referer":    "https://www.screener.in/",
}

_NSE_HOME = "https://www.nseindia.com"


async def _get_nse_session(session: aiohttp.ClientSession) -> None:
    """Hit the NSE homepage to set required cookies before XBRL calls."""
    try:
        async with session.get(_NSE_HOME, headers=_HEADERS_NSE, timeout=aiohttp.ClientTimeout(total=10)) as r:
            pass  # cookies set on session
    except Exception:
        pass


async def _fetch_xbrl(
    session: aiohttp.ClientSession,
    symbol: str,
    stmt_type: str,  # "Standalone" | "Consolidated"
) -> Optional[str]:
    """Fetch NSE XBRL comparator with retry on 403/429/transient errors."""
    url = NSE_XBRL_URL.format(symbol=symbol, type=stmt_type)
    for attempt in range(_MAX_RETRIES + 1):
        try:
            async with session.get(url, headers=_HEADERS_NSE,
                                   timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)) as r:
                if r.status in (403, 429):
                    if attempt < _MAX_RETRIES:
                        sleep_s = _RETRY_BASE_S * (2 ** attempt)
                        logger.debug("NSE XBRL %s/%s: HTTP %d, retry %d after %.0fs",
                                     symbol, stmt_type, r.status, attempt + 1, sleep_s)
                        await asyncio.sleep(sleep_s)
                        continue
                    logger.debug("NSE XBRL %s/%s: HTTP %d after %d retries",
                                 symbol, stmt_type, r.status, _MAX_RETRIES)
                    return None
                if r.status != 200:
                    logger.debug("NSE XBRL %s/%s: HTTP %d", symbol, stmt_type, r.status)
                    return None
                return await r.text()
        except Exception as exc:                                      # noqa: BLE001
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BASE_S)
                continue
            logger.debug("NSE XBRL %s/%s: %s", symbol, stmt_type, exc)
            return None
    return None


async def _fetch_screener(
    session: aiohttp.ClientSession,
    symbol: str,
) -> Optional[str]:
    """Fetch Screener.in quarterly table with retry on transient errors."""
    url = SCREENER_URL.format(symbol=symbol)
    for attempt in range(_MAX_RETRIES + 1):
        try:
            async with session.get(url, headers=_HEADERS_SCREENER,
                                   timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)) as r:
                if r.status == 404:
                    url2 = url.replace("/consolidated/", "/")
                    async with session.get(url2, headers=_HEADERS_SCREENER,
                                           timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)) as r2:
                        return await r2.text() if r2.status == 200 else None
                if r.status in (429, 503):
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(_RETRY_BASE_S * (2 ** attempt))
                        continue
                    return None
                return await r.text() if r.status == 200 else None
        except Exception as exc:                                      # noqa: BLE001
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BASE_S)
                continue
            logger.debug("Screener %s: %s", symbol, exc)
            return None
    return None


async def _resolve_symbols(symbols_arg: Optional[List[str]]) -> List[str]:
    """Latest Nifty 500 from index_constituents, or supplied list."""
    if symbols_arg:
        return [s.strip().upper() for s in symbols_arg if s.strip()]
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT symbol
              FROM nidp.index_constituents
             WHERE index_name ILIKE 'Nifty 500%'
               AND as_of_date = (
                   SELECT MAX(as_of_date) FROM nidp.index_constituents
                    WHERE index_name ILIKE 'Nifty 500%'
               )
             ORDER BY symbol
        """)
    return [r["symbol"] for r in rows]


async def _process_symbol(
    session: aiohttp.ClientSession,
    symbol: str,
    semaphore: asyncio.Semaphore,
    delay: float,
) -> Dict[str, Any]:
    """Fetch + parse + upsert all quarters for one symbol."""
    async with semaphore:
        result: Dict[str, Any] = {
            "symbol": symbol, "nse_quarters": 0,
            "screener_quarters": 0, "total_upserted": 0, "error": None,
        }
        try:
            all_quarters: List[Dict] = []

            # ── NSE XBRL: Consolidated first, then Standalone ──────────
            for stmt_type, consolidated in [("Consolidated", True), ("Standalone", False)]:
                raw = await _fetch_xbrl(session, symbol, stmt_type)
                await asyncio.sleep(delay)
                if not raw:
                    continue
                quarters = parse_nse_xbrl_multi_quarter(symbol, raw, consolidated)
                all_quarters.extend(quarters)
                logger.debug("%s/%s: %d quarters from NSE XBRL", symbol, stmt_type, len(quarters))

            result["nse_quarters"] = len(all_quarters)

            # ── Screener.in fallback for deeper history ────────────────
            nse_quarter_count = len({q["period_end"] for q in all_quarters if q.get("period_end")})
            if nse_quarter_count < MIN_QUARTERS_TARGET:
                html = await _fetch_screener(session, symbol)
                await asyncio.sleep(delay)
                if html:
                    # Try consolidated first, then standalone
                    sc_rows = parse_screener_quarters(symbol, html)
                    for row in sc_rows:
                        row["consolidated"] = True  # Screener /consolidated/ URL
                    if not sc_rows:
                        sc_rows = parse_screener_quarters(symbol, html)
                    result["screener_quarters"] = len(sc_rows)
                    # Only add Screener rows for periods not covered by NSE XBRL
                    nse_periods = {q["period_end"] for q in all_quarters if q.get("period_end")}
                    sc_new = [q for q in sc_rows if q.get("period_end") not in nse_periods]
                    all_quarters.extend(sc_new)
                    logger.debug("%s: %d new quarters from Screener.in", symbol, len(sc_new))

            # ── Upsert all quarters ────────────────────────────────────
            upserted = 0
            for q in all_quarters:
                if not q.get("period_end"):
                    continue
                try:
                    fid = await upsert_financials(
                        symbol=symbol,
                        data=q,
                        source="nse_xbrl_backfill" if q.get("consolidated") is not None else "screener_in",
                    )
                    if fid:
                        upserted += 1
                except Exception as exc:
                    logger.warning("upsert failed for %s period=%s: %s", symbol, q.get("period_end"), exc)

            result["total_upserted"] = upserted
            logger.info(
                "  %s: nse=%d screener=%d upserted=%d",
                symbol, result["nse_quarters"], result["screener_quarters"], upserted,
            )

        except Exception as exc:
            result["error"] = str(exc)
            logger.warning("_process_symbol %s failed: %s", symbol, exc)

        return result


async def run(
    *,
    symbols: Optional[List[str]] = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    per_request_delay: float = PER_REQUEST_DELAY_S,
    only_missing: bool = False,  # skip symbols that already have MIN_QUARTERS_TARGET rows
) -> uuid.UUID:
    """Backfill quarterly financials for `symbols` (default: Nifty 500)."""
    bind_context(service=SERVICE_NAME)

    sym_list = await _resolve_symbols(symbols)
    if not sym_list:
        logger.warning("nse_financials_backfill: no symbols resolved")
        return uuid.uuid4()

    # Optionally filter to symbols with fewer than MIN_QUARTERS_TARGET rows
    if only_missing:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT symbol, COUNT(DISTINCT period_end) AS q_count
                  FROM nidp.nse_financials_quarterly
                 WHERE symbol = ANY($1::text[])
                 GROUP BY symbol
                """,
                sym_list,
            )
        has_enough = {r["symbol"] for r in rows if r["q_count"] >= MIN_QUARTERS_TARGET}
        before = len(sym_list)
        sym_list = [s for s in sym_list if s not in has_enough]
        logger.info(
            "nse_financials_backfill: only_missing=True — skipping %d / %d symbols",
            before - len(sym_list), before,
        )

    if not sym_list:
        logger.info("nse_financials_backfill: all symbols already have >= %d quarters", MIN_QUARTERS_TARGET)
        return uuid.uuid4()

    logger.info("nse_financials_backfill: %d symbols to process", len(sym_list))

    async with JobRun(ingester=SERVICE_NAME, target_date=None) as run_:
        bind_context(run_id=str(run_.run_id))
        run_.metadata["symbol_count"] = len(sym_list)
        run_.metadata["concurrency"] = concurrency

        total_upserted = 0
        total_failed = 0

        with time_ingester(SERVICE_NAME):
            connector = aiohttp.TCPConnector(limit=concurrency + 2, ssl=False)
            async with aiohttp.ClientSession(connector=connector) as session:
                # Warm NSE session cookie before the first request
                await _get_nse_session(session)

                semaphore = asyncio.Semaphore(concurrency)
                completed = 0

                async def _process_with_refresh(sym: str) -> Any:
                    """Wrapper that periodically re-warms the NSE session cookie."""
                    nonlocal completed
                    result = await _process_symbol(session, sym, semaphore, per_request_delay)
                    completed += 1
                    # Refresh NSE cookie every _SESSION_REFRESH_EVERY symbols to
                    # prevent 403s caused by cookie expiry mid-run.
                    if completed % _SESSION_REFRESH_EVERY == 0:
                        logger.info(
                            "nse_financials_backfill: refreshing NSE session cookie "
                            "at symbol %d/%d", completed, len(sym_list),
                        )
                        await _get_nse_session(session)
                    if completed % 20 == 0:
                        logger.info(
                            "nse_financials_backfill: %d/%d done, %d rows upserted",
                            completed, len(sym_list), total_upserted,
                        )
                    return result

                # Queue all symbols at once — semaphore controls actual concurrency.
                all_results = await asyncio.gather(
                    *[_process_with_refresh(sym) for sym in sym_list],
                    return_exceptions=True,
                )
                for res in all_results:
                    if isinstance(res, Exception):
                        total_failed += 1
                    elif isinstance(res, dict) and res.get("error"):
                        total_failed += 1
                    elif isinstance(res, dict):
                        total_upserted += res.get("total_upserted", 0)

        run_.rows_inserted = total_upserted
        run_.rows_skipped  = total_failed
        INGESTER_ROWS.labels(service=SERVICE_NAME, kind="inserted").inc(total_upserted)

        status = "FAILED" if total_failed >= len(sym_list) else ("PARTIAL" if total_failed else "OK")
        INGESTER_RUNS.labels(service=SERVICE_NAME, status=status).inc()
        await run_.finalize(status)

        logger.info(
            "nse_financials_backfill DONE: upserted=%d, failed=%d, total=%d",
            total_upserted, total_failed, len(sym_list),
        )
        return run_.run_id
