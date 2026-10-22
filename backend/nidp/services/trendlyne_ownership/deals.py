"""Ingest per-stock bulk/block deal history from Trendlyne into nidp.trendlyne_deals.

One API call per stock (the server allows no batching for this tool), so the run is budget-capped
and resumable: it skips symbols already fetched today unless --refresh is given.

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


async def _symbols(limit: Optional[int], only_scored: bool) -> list[str]:
    """Symbols to fetch, most relevant first.

    Defaults to those the Smart Money component actually scores: the deal feature exists to be
    ablated against that component, so fetching beyond it spends a shared budget on stocks the
    study cannot use.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        if only_scored:
            rows = await conn.fetch(
                """
                SELECT DISTINCT s.symbol
                  FROM nidp.smart_money_scores_daily s
                 WHERE s.as_of_date = (SELECT max(as_of_date) FROM nidp.smart_money_scores_daily)
                 ORDER BY 1
                """)
        else:
            rows = await conn.fetch(
                """SELECT DISTINCT symbol FROM nidp.index_constituents
                    WHERE as_of_date = (SELECT max(as_of_date) FROM nidp.index_constituents)
                    ORDER BY 1""")
        syms = [r["symbol"] for r in rows]
        # Resume: skip anything already pulled today unless the caller forces a refresh.
        done = {r["symbol"] for r in await conn.fetch(
            "SELECT DISTINCT symbol FROM nidp.trendlyne_deals WHERE retrieved_at::date = current_date")}
    out = [s for s in syms if s not in done]
    logger.info("trendlyne_deals: %d candidate symbol(s), %d already fetched today, %d to go",
                len(syms), len(done), len(out))
    return out[:limit] if limit else out


async def run(*, max_calls: int = DEFAULT_MAX_CALLS, limit: Optional[int] = None,
              only_scored: bool = True, refresh: bool = False) -> dict:
    bind_context(service=SERVICE_NAME)
    budget = CallBudget(max_calls)
    syms = await _symbols(limit, only_scored)
    if refresh:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT symbol FROM nidp.smart_money_scores_daily WHERE as_of_date="
                "(SELECT max(as_of_date) FROM nidp.smart_money_scores_daily) ORDER BY 1")
        syms = [r["symbol"] for r in rows][:limit] if limit else [r["symbol"] for r in rows]

    summary = {"symbols_attempted": 0, "symbols_with_deals": 0, "rows_written": 0,
               "errors": 0, "budget_limit": max_calls}
    if not syms:
        logger.info("trendlyne_deals: nothing to fetch")
        return summary

    pool = await get_pool()
    async with JobRun(ingester=SERVICE_NAME, target_date=date.today()) as job:
        bind_context(run_id=str(job.run_id))
        async with TrendlyneClient(budget) as tl:
            for i, sym in enumerate(syms, 1):
                if budget.remaining == 0:
                    logger.warning("trendlyne_deals: budget spent after %d symbol(s); "
                                   "re-run to continue (progress is resumable)", i - 1)
                    break
                try:
                    payload = await tl.call_tool(
                        "get_ownership_deals_insider_sast",
                        {"stock_code": sym, "type": "bulblockdeal"})
                except TrendlyneError as e:
                    summary["errors"] += 1
                    logger.info("trendlyne_deals[%s]: %s", sym, str(e)[:150])
                    continue
                summary["symbols_attempted"] += 1
                deals = parse_deals(payload, sym)
                if not deals:
                    continue
                args = [(d["symbol"], d["deal_date"], d["client_name"], d.get("deal_type"),
                         d.get("action"), d["quantity"], d["price"],
                         d.get("traded_percent"), d.get("exchange"), job.run_id)
                        for d in deals]
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        await conn.executemany(_UPSERT, args, timeout=120)
                summary["symbols_with_deals"] += 1
                summary["rows_written"] += len(args)
                if i % 25 == 0:
                    logger.info("trendlyne_deals: %d/%d symbols, %d rows, budget %d left",
                                i, len(syms), summary["rows_written"], budget.remaining)

        summary["calls_used"] = budget.used
        job.rows_fetched = summary["rows_written"]
        job.rows_inserted = summary["rows_written"]
        job.metadata.update(summary)
        await job.finalize("OK" if summary["rows_written"] else "FAILED",
                           error_message=None if summary["rows_written"] else "no deal rows")
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
                    help="re-fetch symbols already pulled today")
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
