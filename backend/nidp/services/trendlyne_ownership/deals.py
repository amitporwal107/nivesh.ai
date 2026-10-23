"""Ingest per-stock bulk/block deal history from Trendlyne into nidp.trendlyne_deals.

One API call per stock (the server allows no batching for this tool), so the run is budget-capped
and always stops part-way. Resumption is therefore the core of this job, not a nicety.

HOW RESUMPTION WORKS, AND WHY IT IS NOT ALPHABETICAL
Candidates are ordered LEAST-RECENTLY-ATTEMPTED FIRST from nidp.trendlyne_deal_fetch_log, which
records every symbol this job has ASKED about — including symbols that legitimately returned no
deals. Coverage then self-levels across runs: whatever a budget break leaves unreached is exactly
what the next run starts with.

The previous ordering was `ORDER BY 1` with the progress marker inferred from the fact table
(`nidp.trendlyne_deals WHERE retrieved_at::date = current_date`), and it truncated the feed to
0-9/A-G. Two faults combined (measured 2026-10-22, see migration 181): the marker was day-scoped,
so each new day restarted the alphabetical walk at 'A' and re-paid for the same prefix; and it
only recorded symbols that PRODUCED ROWS, so a symbol with no deals was re-queried on every run
forever. 341 calls reached candidate 338 of 984 and the study consuming this feed could see 27.8%
of its eligible universe — "never asked", not "no institutional interest". Do not reintroduce a
deterministic alphabetical order here, and do not infer progress from the fact table.

The vendor returns a text block whose `tableData` rows are JSON arrays in the order declared by
`tableHeaders`. The order is read FROM the headers rather than assumed, because a positional
assumption is exactly what broke the parameter feed before (blocks arrive in arbitrary order).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import uuid
from datetime import date
from typing import Any, Iterable, Optional

from nidp.shared.logging_setup import bind_context, setup_logging
from nidp.shared.storage.job_log import JobRun
from nidp.shared.storage.pg import close_pool, get_pool

from .client import CallBudget, TrendlyneClient, TrendlyneError

logger = logging.getLogger(__name__)

SERVICE_NAME = "trendlyne_deals"
DEFAULT_MAX_CALLS = 250          # conservative: the daily allowance is shared with other jobs

_UPSERT = """
INSERT INTO nidp.trendlyne_deals
    (symbol, deal_date, client_name, deal_type, action, quantity, price,
     traded_percent, exchange, source_run_id)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
ON CONFLICT (symbol, deal_date, client_name, action, quantity, price, exchange) DO UPDATE SET
    deal_type      = EXCLUDED.deal_type,
    traded_percent = coalesce(EXCLUDED.traded_percent, nidp.trendlyne_deals.traded_percent),
    retrieved_at   = now(),
    source_run_id  = EXCLUDED.source_run_id
"""

# Every symbol we ASKED about, whatever came back. 'EMPTY' is a real answer and must be recorded,
# or the symbol is re-queried out of the shared budget on every subsequent run.
_ATTEMPT_UPSERT = """
INSERT INTO nidp.trendlyne_deal_fetch_log
    (symbol, last_attempt_at, last_status, last_success_at, attempts, deal_rows, last_run_id)
VALUES ($1, now(), $2, CASE WHEN $2 = 'ERROR' THEN NULL ELSE now() END, 1, $3, $4)
ON CONFLICT (symbol) DO UPDATE SET
    last_attempt_at = now(),
    last_status     = EXCLUDED.last_status,
    last_success_at = coalesce(EXCLUDED.last_success_at,
                               nidp.trendlyne_deal_fetch_log.last_success_at),
    attempts        = nidp.trendlyne_deal_fetch_log.attempts + 1,
    deal_rows       = coalesce(EXCLUDED.deal_rows, nidp.trendlyne_deal_fetch_log.deal_rows),
    last_run_id     = EXCLUDED.last_run_id
"""

# The candidate universes. Kept as fragments because the ordering and coverage queries below must
# both be computed over exactly the same set.
_CAND_SCORED = """
    SELECT DISTINCT symbol FROM nidp.smart_money_scores_daily
     WHERE as_of_date = (SELECT max(as_of_date) FROM nidp.smart_money_scores_daily)
"""
_CAND_INDEX = """
    SELECT DISTINCT symbol FROM nidp.index_constituents
     WHERE as_of_date = (SELECT max(as_of_date) FROM nidp.index_constituents)
"""

# Least-recently-attempted first; never attempted at all comes before everything.
#
# The tie-break is md5(symbol), NOT symbol: among symbols that have never been attempted every
# ordering is equally valid for coverage, but an alphabetical one makes any partial ingest an
# alphabetically biased SAMPLE, which is the defect this file exists to prevent. md5 is stable, so
# a resumed run continues the same order rather than reshuffling.
#
# $1 = refresh: when false, a symbol already attempted today (IST, the allowance's day, matching
# trendlyne_fundamentals' budget accounting) is held back so a second run of the day spends the
# budget on new ground instead of refreshing.
_SYMBOLS_SQL = """
WITH cand AS (
{candidates}
)
SELECT c.symbol
  FROM cand c
  LEFT JOIN nidp.trendlyne_deal_fetch_log f ON f.symbol = c.symbol
 WHERE $1
    OR f.last_attempt_at IS NULL
    OR (f.last_attempt_at AT TIME ZONE 'Asia/Kolkata')::date
         < (now() AT TIME ZONE 'Asia/Kolkata')::date
 ORDER BY f.last_attempt_at ASC NULLS FIRST, md5(c.symbol)
"""

# What the feed has ever been asked about, so a partial run can state its own coverage.
_COVERAGE_SQL = """
WITH cand AS (
{candidates}
)
SELECT count(*)                           AS candidates,
       count(f.symbol)                    AS attempted_ever,
       count(*) - count(f.symbol)         AS never_attempted,
       round(100.0 * count(f.symbol) / greatest(count(*), 1), 1) AS attempted_pct
  FROM cand c LEFT JOIN nidp.trendlyne_deal_fetch_log f ON f.symbol = c.symbol
"""


def _header_order(payload: str) -> list[str]:
    """Field order declared by tableHeaders, e.g. ['client_name','get_deal_type_display',...]."""
    block = payload.split("tableHeaders:", 1)
    if len(block) < 2:
        return []
    order: list[str] = []
    for line in block[1].splitlines():
        line = line.strip()
        # The text after "tableHeaders:" begins with a newline, so the first split element is
        # empty. Breaking on any blank line therefore ate the whole block; only a blank AFTER
        # the columns have started means the end of it.
        if not line:
            if order:
                break
            continue
        if line.startswith("extraHeaders") or line.endswith(":"):
            break
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 3 and parts[2] != "unique_name":
            order.append(parts[2])
    return order


# unique_name in the feed -> our column
_FIELD_MAP = {
    "client_name":            "client_name",
    "get_deal_type_display":  "deal_type",
    "get_action_display":     "action",
    "date":                   "deal_date",
    "price":                  "price",
    "quantity":               "quantity",
    "traded_percent":         "traded_percent",
    "exchange":               "exchange",
}


def parse_deals(payload: str, symbol: str) -> list[dict]:
    order = [_FIELD_MAP.get(h) for h in _header_order(payload)]
    if not order or "client_name" not in order:
        logger.warning("trendlyne_deals[%s]: tableHeaders missing or unrecognised — skipping "
                       "rather than guessing column positions", symbol)
        return []
    seg = payload.split("tableData:", 1)
    if len(seg) < 2:
        return []
    body = seg[1].split("tableHeaders:", 1)[0]

    rows: list[dict] = []
    for m in re.finditer(r"\[(?:[^\[\]]|\\.)*\]", body):
        try:
            vals = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if len(vals) != len(order):
            continue
        rec: dict[str, Any] = {"symbol": symbol}
        for col, v in zip(order, vals):
            if col:
                rec[col] = v
        if not rec.get("deal_date") or not rec.get("client_name"):
            continue
        try:
            rec["deal_date"] = date.fromisoformat(str(rec["deal_date"])[:10])
        except ValueError:
            continue
        # quantity and price are part of the key, so a row without them is unusable.
        if rec.get("quantity") in (None, "") or rec.get("price") in (None, ""):
            continue
        rows.append(rec)
    return rows


def _candidate_sql(only_scored: bool) -> str:
    """The candidate universe.

    Defaults to those the Smart Money component actually scores: the deal feature exists to be
    ablated against that component, so fetching beyond it spends a shared budget on stocks the
    study cannot use.
    """
    return _CAND_SCORED if only_scored else _CAND_INDEX


async def _coverage(only_scored: bool) -> dict:
    """How much of the candidate universe the feed has ever been ASKED about."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            _COVERAGE_SQL.format(candidates=_candidate_sql(only_scored)))
    return {k: (float(v) if k == "attempted_pct" else int(v)) for k, v in dict(row).items()}


async def _symbols(limit: Optional[int], only_scored: bool, refresh: bool) -> list[str]:
    """Symbols to fetch, least-recently-attempted first. See this module's docstring."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            _SYMBOLS_SQL.format(candidates=_candidate_sql(only_scored)), refresh)
    out = [r["symbol"] for r in rows]
    cov = await _coverage(only_scored)
    logger.info("trendlyne_deals: %d candidate(s), %d ever attempted (%.1f%%), %d never attempted; "
                "%d due this run%s",
                cov["candidates"], cov["attempted_ever"], cov["attempted_pct"],
                cov["never_attempted"], len(out), " (refresh)" if refresh else "")
    return out[:limit] if limit else out


async def _note_attempt(pool, symbol: str, status: str, deal_rows: Optional[int],
                        run_id: uuid.UUID) -> None:
    """Record that `symbol` was asked about. This is the durable progress marker."""
    async with pool.acquire() as conn:
        await conn.execute(_ATTEMPT_UPSERT, symbol, status, deal_rows, run_id)


async def run(*, max_calls: int = DEFAULT_MAX_CALLS, limit: Optional[int] = None,
              only_scored: bool = True, refresh: bool = False) -> dict:
    bind_context(service=SERVICE_NAME)
    budget = CallBudget(max_calls)
    # One ordering authority: _symbols() honours `refresh` itself. An override here is how the
    # alphabetical order used to creep back in.
    syms = await _symbols(limit, only_scored, refresh)

    summary = {"symbols_attempted": 0, "symbols_with_deals": 0, "rows_written": 0,
               "errors": 0, "budget_limit": max_calls}
    if not syms:
        logger.info("trendlyne_deals: nothing to fetch")
        summary.update(await _coverage(only_scored))
        return summary

    pool = await get_pool()
    async with JobRun(ingester=SERVICE_NAME, target_date=date.today()) as job:
        bind_context(run_id=str(job.run_id))
        async with TrendlyneClient(budget) as tl:
            for i, sym in enumerate(syms, 1):
                if budget.remaining == 0:
                    # Nothing is recorded for the symbols not reached, so the next run sees them
                    # as never attempted and starts exactly here.
                    logger.warning("trendlyne_deals: budget spent after %d of %d symbol(s); "
                                   "re-run to continue from %s (progress is durable)",
                                   i - 1, len(syms), sym)
                    break
                spent_before = budget.used
                try:
                    payload = await tl.call_tool(
                        "get_ownership_deals_insider_sast",
                        {"stock_code": sym, "type": "bulblockdeal"})
                except TrendlyneError as e:
                    summary["errors"] += 1
                    logger.info("trendlyne_deals[%s]: %s", sym, str(e)[:150])
                    # Only a symbol that actually cost a call has been attempted; a refusal raised
                    # by the budget itself must not mark it done.
                    if budget.used > spent_before:
                        await _note_attempt(pool, sym, "ERROR", None, job.run_id)
                    continue
                summary["symbols_attempted"] += 1
                deals = parse_deals(payload, sym)
                if not deals:
                    # A real answer: this stock has no disclosed deals. Recorded, or the shared
                    # budget pays for the same question again on every future run.
                    await _note_attempt(pool, sym, "EMPTY", 0, job.run_id)
                    continue
                args = [(d["symbol"], d["deal_date"], d["client_name"], d.get("deal_type"),
                         d.get("action"), d["quantity"], d["price"],
                         d.get("traded_percent"), d.get("exchange"), job.run_id)
                        for d in deals]
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        await conn.executemany(_UPSERT, args, timeout=120)
                await _note_attempt(pool, sym, "OK", len(args), job.run_id)
                summary["symbols_with_deals"] += 1
                summary["rows_written"] += len(args)
                if i % 25 == 0:
                    logger.info("trendlyne_deals: %d/%d symbols, %d rows, budget %d left",
                                i, len(syms), summary["rows_written"], budget.remaining)

        summary["calls_used"] = budget.used
        # Coverage AFTER the run, so a partial run reports how far the feed has got overall rather
        # than only what this invocation happened to write.
        summary.update(await _coverage(only_scored))
        job.rows_fetched = summary["rows_written"]
        job.rows_inserted = summary["rows_written"]
        job.metadata.update(summary)
        # Status is about whether the FEED answered, not whether these particular stocks had
        # deals. Once coverage reaches genuinely deal-free names a zero-row run is normal, and
        # calling it FAILED climbs source_registry.consecutive_failures and freezes v_feed_status.
        attempted = summary["symbols_attempted"]
        await job.finalize("OK" if attempted else "FAILED",
                           error_message=None if attempted
                           else f"no symbol fetched ({summary['errors']} error(s))")
    logger.info("trendlyne_deals done: %s", summary)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest bulk/block deal history from Trendlyne")
    ap.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS,
                    help=f"shared daily allowance to consume (default {DEFAULT_MAX_CALLS})")
    ap.add_argument("--limit", type=int, default=None, help="cap the symbol count (pilot runs)")
    ap.add_argument("--all-symbols", dest="only_scored", action="store_false", default=True,
                    help="fetch the whole index universe instead of only scored symbols")
    ap.add_argument("--refresh", action="store_true",
                    help="also re-attempt symbols already attempted today (still "
                         "least-recently-attempted first)")
    args = ap.parse_args()
    setup_logging(service=SERVICE_NAME)

    async def _go() -> None:
        try:
            await run(max_calls=args.max_calls, limit=args.limit,
                      only_scored=args.only_scored, refresh=args.refresh)
        finally:
            await close_pool()

    asyncio.run(_go())


if __name__ == "__main__":
    main()
