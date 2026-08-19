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

# Per-request ceiling. Generous next to the fetcher's own 30s timeout x4
# retries, but finite — the point is that no single socket can wedge a sweep
# over 2,000 symbols.
_SYMBOL_TIMEOUT_S = 180


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


# nidp.shareholding_pattern stores percentages as NUMERIC(8,4), so anything at or
# above 10^4 cannot be written at all — asyncpg raises NumericValueOutOfRangeError
# and, because the writer uses executemany, ONE bad filing aborts the whole batch and
# ends the sweep. Observed 2026-08-19: the run died at 22.3% coverage on exactly this.
#
# A holding percentage above 10,000 is not a number this table can hold or that any
# reading of it could be true — the same corruption family as the public_pct = 9904
# already sitting in the table. Such a row is dropped and counted, never silently
# clamped: clamping would invent a plausible value for a filing whose real one is
# unknown.
_PCT_LIMIT = 10_000
_PCT_FIELDS = (
    "promoter_pct", "promoter_pledged_pct", "promoter_pledged_to_total_pct",
    "fii_pct", "dii_pct", "mf_pct", "insurance_pct", "bank_fi_pct",
    "govt_holding_pct", "public_pct", "individual_pct", "nri_pct",
    "bodies_corporate_pct",
)


def storable(row: Dict[str, Any]) -> bool:
    """False when a percentage field exceeds what the column can store."""
    for f in _PCT_FIELDS:
        v = row.get(f)
        if v is None:
            continue
        try:
            if abs(float(v)) >= _PCT_LIMIT:
                return False
        except (TypeError, ValueError):
            return False
    return True


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
    out_of_range = write_failed = 0
    skipped_complete = len(symbols) - len(todo)

    for i, sym in enumerate(todo, 1):
        want = quarters - len(held.get(sym, []))
        try:
            # Hard ceiling per symbol. The shared fetcher has its own per-request
            # timeout, but a run over ~2,000 symbols only needs ONE socket to hang
            # past it to wedge the whole sweep — observed 2026-08-19, live processes
            # with no write for 5+ minutes. A symbol that overruns is skipped and
            # picked up by the next run, which is safe because the backfill is
            # incremental.
            body, status = await asyncio.wait_for(fetch_bytes(
                symbol_url(sym), referer=REFERER,
                extra_headers={"Accept": "application/json"}),
                timeout=_SYMBOL_TIMEOUT_S)
            if status != 200 or not body:
                failed += 1
                continue
            manifests = parse_filing_list(body)
        except asyncio.TimeoutError:
            logger.warning("backfill: %s timed out after %ss — skipping",
                           sym, _SYMBOL_TIMEOUT_S)
            failed += 1
            continue
        except Exception:                                            # noqa: BLE001
            logger.exception("backfill: list fetch failed for %s", sym)
            failed += 1
            continue

        rows: List[Dict[str, Any]] = []
        wanted = missing_quarters(manifests, held.get(sym, []), want)
        offered += len(wanted)
        for m in wanted:
            try:
                doc, st = await asyncio.wait_for(
                    fetch_bytes(m["xbrl_url"], referer=REFERER),
                    timeout=_SYMBOL_TIMEOUT_S)
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
        keep = [r for r in rows if storable(r)]
        if len(keep) != len(rows):
            out_of_range += len(rows) - len(keep)
            logger.warning("backfill: %s dropped %d unstorable row(s) "
                           "(percentage >= %d)", sym, len(rows) - len(keep), _PCT_LIMIT)
        if keep:
            try:
                written += await upsert_shareholding(keep, run_id)
            except Exception:                                        # noqa: BLE001
                # One symbol must not end the sweep. The writer batches, so a
                # failure here loses this symbol's rows, not the run's.
                write_failed += 1
                logger.exception("backfill: write failed for %s", sym)
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
        "rows_out_of_range": out_of_range,
        "symbol_writes_failed": write_failed,
        "symbol_list_failed": failed,
    }
    logger.info("nse_shareholding backfill done: %s", result)
    return result
