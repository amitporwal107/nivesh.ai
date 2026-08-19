"""Backfill older shareholding quarters, one symbol at a time.

Why this exists: the daily ingester reads
``/api/corporate-share-holdings-master?index=equities``, which returns only the
CURRENT quarter's filings for the whole universe. So NIDP holds two quarters
(2026-03-31, 2026-06-30) for ~2,300 symbols, and a quarter-on-quarter series needs
more than that — the FLOW LEDGER's S1 asks for four, and with two quarters only
~353 symbols could answer it.

The same endpoint with ``&symbol=<SYM>`` returns that symbol's FULL filing history —
21-22 quarters back to March 2022, verified 2026-08-19 for RELIANCE, INFY and
HDFCBANK. The ``period=`` parameter is ignored, so per-symbol is the only way in.

Cost is one list request plus one XBRL document per missing quarter. At the shared
fetcher's NSE pacing that is roughly 0.35s per document, so backfilling two extra
quarters across the universe is ~30 minutes — a background job, not a request path.
It is deliberately incremental: quarters already stored are never re-fetched, so a
re-run after an interruption resumes rather than restarting.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional, Sequence

from nidp.shared.config import NSE_SHAREHOLDING_LIST_URL, NSE_WWW
from nidp.shared.sources.nse_fetcher import fetch_bytes
from nidp.shared.storage.pg import get_pool

from .parser import parse_filing_list, parse_xbrl_document
from .writer import upsert_shareholding

logger = logging.getLogger(__name__)

REFERER = f"{NSE_WWW}/companies-listing/corporate-filings-shareholding-pattern"


def symbol_url(symbol: str) -> str:
    return f"{NSE_SHAREHOLDING_LIST_URL}&symbol={symbol}"


def missing_quarters(manifests: List[Dict[str, Any]], have: Sequence[Any],
                     want: int) -> List[Dict[str, Any]]:
    """The most recent `want` filings this symbol is missing, newest first.

    Filings already stored are skipped rather than re-fetched — that is what makes a
    re-run after an interruption resume instead of restart, and it is the difference
    between a 30-minute job and a 5-hour one.
    """
    # Compare as ISO strings on BOTH sides. parse_filing_list yields period_end as a
    # str while asyncpg returns datetime.date, so a direct `in` check is always False
    # — that does not raise, it just stops excluding anything, and the backfill
    # quietly re-fetches the quarters it already had instead of deepening history.
    # Observed on staging 2026-08-19: 556 rows written across ~278 symbols, every one
    # of which still held exactly the same two quarters afterwards.
    seen = {str(q) for q in have if q is not None}
    out: List[Dict[str, Any]] = []
    for m in sorted((m for m in manifests if m.get("period_end")),
                    key=lambda m: str(m["period_end"]), reverse=True):
        if str(m["period_end"]) in seen or not m.get("xbrl_url"):
            continue
        out.append(m)
        if len(out) >= want:
            break
    return out


async def _quarters_held(conn, symbols: Sequence[str]) -> Dict[str, List[Any]]:
    rows = await conn.fetch(
        "SELECT symbol, ARRAY_AGG(DISTINCT period_end) AS quarters "
        "  FROM nidp.shareholding_pattern WHERE symbol = ANY($1::text[]) "
        " GROUP BY symbol", list(symbols))
    return {r["symbol"]: list(r["quarters"]) for r in rows}


async def run(*, quarters: int = 4, limit: Optional[int] = None,
              only: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Backfill until every targeted symbol holds `quarters` filings."""
    run_id = uuid.uuid4()
    pool = await get_pool()

    async with pool.acquire() as conn:
        if only:
            symbols = [s.strip().upper() for s in only]
        else:
            symbols = [r["symbol"] for r in await conn.fetch(
                "SELECT DISTINCT symbol FROM nidp.shareholding_pattern ORDER BY symbol")]
        if limit:
            symbols = symbols[:limit]
        held = await _quarters_held(conn, symbols)

    todo = [s for s in symbols if len(held.get(s, [])) < quarters]
    logger.info("nse_shareholding backfill: %d symbol(s) below %d quarters "
                "(of %d considered)", len(todo), quarters, len(symbols))

    written = fetched = failed = 0
    offered = doc_unavailable = doc_unparsed = doc_error = 0
    skipped_complete = len(symbols) - len(todo)

    for i, sym in enumerate(todo, 1):
        want = quarters - len(held.get(sym, []))
        try:
            body, status = await fetch_bytes(
                symbol_url(sym), referer=REFERER,
                extra_headers={"Accept": "application/json"})
            if status != 200 or not body:
                failed += 1
                continue
            manifests = parse_filing_list(body)
        except Exception:                                            # noqa: BLE001
            logger.exception("backfill: list fetch failed for %s", sym)
            failed += 1
            continue

        rows: List[Dict[str, Any]] = []
        wanted = missing_quarters(manifests, held.get(sym, []), want)
        offered += len(wanted)
        for m in wanted:
            try:
                doc, st = await fetch_bytes(m["xbrl_url"], referer=REFERER)
                if st != 200 or not doc:
                    doc_unavailable += 1
                    logger.info("backfill: %s %s XBRL HTTP %s",
                                sym, m.get("period_end"), st)
                    continue
                fetched += 1
                # A 200 that parses to nothing is its own failure mode — NSE's older
                # filings use an earlier XBRL schema — and it must not be invisible,
                # or a backfill that silently deepens nothing reads as a success.
                parsed = parse_xbrl_document(doc, m)
                if not parsed:
                    doc_unparsed += 1
                    logger.info("backfill: %s %s parsed to 0 rows",
                                sym, m.get("period_end"))
                rows.extend(parsed)
            except Exception:                                        # noqa: BLE001
                doc_error += 1
                logger.warning("backfill: XBRL failed %s %s",
                               sym, m.get("period_end"))

        rows = [r for r in rows if r.get("symbol") and r.get("period_end")]
        if rows:
            written += await upsert_shareholding(rows, run_id)
        if i % 100 == 0:
            logger.info("backfill: %d/%d symbols, %d rows written",
                        i, len(todo), written)

    result = {
        "status": "OK", "run_id": str(run_id),
        "symbols_considered": len(symbols),
        "symbols_already_complete": skipped_complete,
        "symbols_attempted": len(todo),
        "quarters_wanted": offered,
        "xbrl_fetched": fetched,
        "xbrl_http_failed": doc_unavailable,
        "xbrl_parsed_empty": doc_unparsed,
        "xbrl_errored": doc_error,
        "rows_written": written,
        "symbol_list_failed": failed,
    }
    logger.info("nse_shareholding backfill done: %s", result)
    return result
