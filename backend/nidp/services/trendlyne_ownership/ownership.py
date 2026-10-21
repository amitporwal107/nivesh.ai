"""Universe-wide aggregate institutional ownership from Trendlyne -> nidp.trendlyne_ownership.

Fills the hole that made the "stocks with rising institutional ownership" tile unbuildable:
nidp.stock_features_daily.fii_pct_change_qoq was populated for 5.9% of the scored universe. This
feed carries FII, institutional and mutual-fund levels plus their changes for essentially every
listed stock, at 10 stocks per call.

What it is NOT: there is no scheme- or AMC-level breakdown here (verified against the live API),
so it complements the scheme-level breadth layer and cannot replace it. And it carries no
market-wide FII/DII CASH FLOW — every fii* parameter is a per-stock HOLDING percentage, so the
"FII net flow (Rs Cr)" tiles cannot be served from this feed.

Values are keyed by the feed's FIELD NAME, never by position: the server returns blocks in
arbitrary order, and names vary in spacing ("MF holding Chg 3M%" vs "... 3M %"), so names are
normalised before lookup and anything unrecognised is logged rather than silently dropped.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
from datetime import date
from typing import Optional

from nidp.shared.logging_setup import bind_context, setup_logging
from nidp.shared.storage.job_log import JobRun
from nidp.shared.storage.pg import close_pool, get_pool

from .client import MAX_STOCKS_PER_PARAM_CALL, CallBudget, TrendlyneClient, TrendlyneError

logger = logging.getLogger(__name__)

SERVICE_NAME = "trendlyne_ownership"
DEFAULT_MAX_CALLS = 150

PARAMETERS = [
    "mfhold", "mfhold1m", "mfhold2m", "mfhold3m", "mfhold4m",
    "mfptc1m", "mfptc2m", "mfptc3m", "mfpct1q", "mfpct4q", "mfpct8q",
    "fiihold", "fiipct1q", "instihold", "instipct1q", "prompct",
]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


# Normalised field name -> column. Built from the feed's own labels, which do not match the
# parameter tokens (mfpct4q is labelled "MF holding change 1Y %", not "4Qtr").
_FIELD_TO_COL = {_norm(k): v for k, v in {
    "MF holding current Qtr %":             "mf_hold_pct",
    "MF holding total shares Prev. month":  "mf_shares_m1",
    "MF holding total shares 2M ago":       "mf_shares_m2",
    "MF holding total shares 3M ago":       "mf_shares_m3",
    "MF holding total shares 4M ago":       "mf_shares_m4",
    "MF holding Chg 1M %":                  "mf_chg_1m_pct",
    "MF holding Chg 2M %":                  "mf_chg_2m_pct",
    "MF holding Chg 3M%":                   "mf_chg_3m_pct",
    "MF holding change QoQ %":              "mf_chg_qoq_pct",
    "MF holding change 1Y %":               "mf_chg_1y_pct",
    "MF holding change 2Y %":               "mf_chg_2y_pct",
    "FII holding current Qtr %":            "fii_hold_pct",
    "FII holding change QoQ %":             "fii_chg_qoq_pct",
    "Institutional holding current Qtr %":  "insti_hold_pct",
    "Institutional holding change QoQ %":   "insti_chg_qoq_pct",
    "Promoter holding latest %":            "promoter_pct",
}.items()}

_HEADER_RE = re.compile(r"^(\d+)\|([^|]*)\|([^|]*)\|([^|]*)\|(\d{4}-\d{2}-\d{2})\s*$")


def parse_values(payload: str) -> tuple[dict[str, dict], set[str]]:
    """(symbol -> {column: value, as_of_date, stock_id}, unmapped_field_names)."""
    import json as _json
    body = payload
    if body.lstrip().startswith("{"):
        try:
            body = _json.loads(body).get("data", "")
        except _json.JSONDecodeError:
            pass

    out: dict[str, dict] = {}
    unmapped: set[str] = set()

    for line in body.splitlines():
        m = _HEADER_RE.match(line.strip())
        if m:
            stock_id, _name, nse, _bse, d = m.groups()
            if nse:
                out[nse] = {"symbol": nse, "stock_id": int(stock_id),
                            "as_of_date": date.fromisoformat(d)}

    for block in body.split("---"):
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue
        field, values = None, []
        for l in lines:
            if _HEADER_RE.match(l):
                continue
            if ":" in l and field is not None:
                values.append(l)
            elif field is None:
                field = l
        if field is None:
            continue
        col = _FIELD_TO_COL.get(_norm(field))
        if col is None:
            unmapped.add(field)
            continue
        for v in values:
            sym, _, raw = v.partition(":")
            sym, raw = sym.strip(), raw.strip()
            if sym not in out or raw in ("", "None", "null", "-"):
                continue
            try:
                out[sym][col] = float(raw)
            except ValueError:
                continue
    return out, unmapped


_COLS = ["mf_hold_pct", "mf_shares_m1", "mf_shares_m2", "mf_shares_m3", "mf_shares_m4",
         "mf_chg_1m_pct", "mf_chg_2m_pct", "mf_chg_3m_pct", "mf_chg_qoq_pct",
         "mf_chg_1y_pct", "mf_chg_2y_pct", "fii_hold_pct", "fii_chg_qoq_pct",
         "insti_hold_pct", "insti_chg_qoq_pct", "promoter_pct"]

_UPSERT = f"""
INSERT INTO nidp.trendlyne_ownership
    (symbol, as_of_date, stock_id, {', '.join(_COLS)}, source_run_id)
VALUES ($1, $2, $3, {', '.join(f'${i}' for i in range(4, 4 + len(_COLS)))}, ${4 + len(_COLS)})
ON CONFLICT (symbol, as_of_date) DO UPDATE SET
    stock_id = EXCLUDED.stock_id,
    {', '.join(f'{c} = coalesce(EXCLUDED.{c}, nidp.trendlyne_ownership.{c})' for c in _COLS)},
    retrieved_at = now(),
    source_run_id = EXCLUDED.source_run_id
"""


async def _symbols(limit: Optional[int]) -> list[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT DISTINCT symbol FROM nidp.stock_features_daily
                WHERE as_of_date=(SELECT max(as_of_date) FROM nidp.stock_features_daily)
                  AND symbol NOT LIKE '\\_\\_%' ORDER BY 1""")
        done = {r["symbol"] for r in await conn.fetch(
            "SELECT symbol FROM nidp.trendlyne_ownership WHERE retrieved_at::date = current_date")}
    syms = [r["symbol"] for r in rows if r["symbol"] not in done]
    logger.info("%s: %d symbol(s) to fetch (%d already done today)",
                SERVICE_NAME, len(syms), len(done))
    return syms[:limit] if limit else syms


async def run(*, max_calls: int = DEFAULT_MAX_CALLS, limit: Optional[int] = None) -> dict:
    bind_context(service=SERVICE_NAME)
    budget = CallBudget(max_calls)
    syms = await _symbols(limit)
    summary = {"symbols_written": 0, "batches": 0, "errors": 0, "unmapped_fields": []}
    if not syms:
        return summary

    pool = await get_pool()
    unmapped_all: set[str] = set()
    async with JobRun(ingester=SERVICE_NAME, target_date=date.today()) as job:
        bind_context(run_id=str(job.run_id))
        async with TrendlyneClient(budget) as tl:
            for i in range(0, len(syms), MAX_STOCKS_PER_PARAM_CALL):
                if budget.remaining == 0:
                    logger.warning("%s: budget spent; re-run to continue (resumable)", SERVICE_NAME)
                    break
                batch = syms[i:i + MAX_STOCKS_PER_PARAM_CALL]
                try:
                    payload = await tl.call_tool("get_stock_parameter_values",
                                                 {"stock_codes": batch, "parameters": PARAMETERS})
                except TrendlyneError as e:
                    summary["errors"] += 1
                    logger.info("%s: batch failed: %s", SERVICE_NAME, str(e)[:140])
                    continue
                summary["batches"] += 1
                parsed, unmapped = parse_values(payload)
                unmapped_all |= unmapped
                if not parsed:
                    continue
                args = [tuple([r["symbol"], r["as_of_date"], r.get("stock_id")]
                              + [r.get(c) for c in _COLS] + [job.run_id])
                        for r in parsed.values()]
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        await conn.executemany(_UPSERT, args, timeout=120)
                summary["symbols_written"] += len(args)
                if summary["batches"] % 20 == 0:
                    logger.info("%s: %d symbols, budget %d left",
                                SERVICE_NAME, summary["symbols_written"], budget.remaining)

        if unmapped_all:
            # Field labels drifting is how a silent column of nulls starts.
            logger.warning("%s: %d unrecognised field label(s): %s",
                           SERVICE_NAME, len(unmapped_all), sorted(unmapped_all)[:6])
        summary["unmapped_fields"] = sorted(unmapped_all)[:10]
        summary["calls_used"] = budget.used
        job.rows_fetched = summary["symbols_written"]
        job.rows_inserted = summary["symbols_written"]
        job.metadata.update(summary)
        await job.finalize("OK" if summary["symbols_written"] else "FAILED",
                           error_message=None if summary["symbols_written"] else "no rows")
    logger.info("%s done: %s", SERVICE_NAME, summary)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest aggregate institutional ownership from Trendlyne")
    ap.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    setup_logging(service=SERVICE_NAME)

    async def _go() -> None:
        try:
            await run(max_calls=args.max_calls, limit=args.limit)
        finally:
            await close_pool()

    asyncio.run(_go())


if __name__ == "__main__":
    main()
