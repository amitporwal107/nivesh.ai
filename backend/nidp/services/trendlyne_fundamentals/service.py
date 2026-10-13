"""Fundamentals and sectors from the Trendlyne MCP server.

Three steps, each safe to re-run:

  fetch    Stage raw parameter values (10 stocks x 10 parameters per call) into
           nidp.trendlyne_param_values. Largest companies first; stops when the
           daily call budget is spent and carries on from there next run.
  sectors  Fill sector_master.sector / industry for rows that have none
           (one search per company).
  build    Turn the staged values into dated rows in nidp.nse_financials_quarterly.

Why staging and building are separate: Trendlyne labels values relative to now
("Net Profit Qtr", "Net Profit 3Qtr Ago") and gives no quarter date. `build`
works the date out per company — from a quarter we already hold from a dated
source when there is one, otherwise from when the company filed its results —
and writes nothing for a company it cannot date.

Rows from other sources are never overwritten: `build` only inserts quarters
that are missing and updates rows it wrote itself (source = 'trendlyne_mcp').

Usage:
    python -m nidp.services.trendlyne_fundamentals fetch --pass p1 --max-calls 300
    python -m nidp.services.trendlyne_fundamentals sectors --max-calls 200
    python -m nidp.services.trendlyne_fundamentals build [--dry-run]
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from nidp.shared.storage.pg import get_pool

from . import parse
from .client import MAX_STOCKS, BudgetExhausted, TrendlyneClient, TrendlyneError, mcp_url

logger = logging.getLogger(__name__)


def _dec(value: Optional[float]) -> Optional[Decimal]:
    """A float as the exact decimal the provider printed (747.16, not 747.15999...)."""
    return None if value is None else Decimal(str(round(value, 4)))

SOURCE = "trendlyne_mcp"
SECTOR_NOT_FOUND = "trendlyne_mcp_not_found"
DEFAULT_DAILY_BUDGET = 700          # the account's cap is about 1,000 a day and is shared
REFERENCE_STOCK = "RELIANCE"        # used once per parameter to learn its display label
DELAY_S = 1.0

# Largest companies first, by the latest day's traded value.
_UNIVERSE_SQL = """
    SELECT u.symbol
      FROM nidp.v_screener_backfill_universe u
      LEFT JOIN (SELECT symbol, MAX(turnover) AS turnover FROM nidp.prices_eod
                  WHERE as_of_date = (SELECT MAX(as_of_date) FROM nidp.prices_eod) GROUP BY symbol) p USING (symbol)
     ORDER BY p.turnover DESC NULLS LAST, u.symbol
"""


def daily_budget() -> int:
    return int(os.environ.get("TRENDLYNE_DAILY_CALL_BUDGET", DEFAULT_DAILY_BUDGET))


async def _client(pool, max_calls: Optional[int]) -> tuple[TrendlyneClient, list]:
    """A client whose budget is what is left of today's allowance (IST day)."""
    async with pool.acquire() as conn:
        used = await conn.fetchval(
            "SELECT COUNT(*) FROM nidp.trendlyne_call_log "
            "WHERE (called_at AT TIME ZONE 'Asia/Kolkata')::date = (NOW() AT TIME ZONE 'Asia/Kolkata')::date")
    left = max(0, daily_budget() - used)
    if max_calls is not None:
        left = min(left, max_calls)
    ledger: list = []
    logger.info("trendlyne: %d calls used today, %d available to this run", used, left)
    return TrendlyneClient(mcp_url(), budget_left=left, on_call=lambda *row: ledger.append(row)), ledger


async def _flush_ledger(pool, ledger: list) -> None:
    if not ledger:
        return
    rows, ledger[:] = list(ledger), []
    async with pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO nidp.trendlyne_call_log (tool, ok, detail) VALUES ($1, $2, $3)", rows)


# ── fetch ────────────────────────────────────────────────────────────────────

async def _learn_labels(pool, client: TrendlyneClient, ledger: list, parameters: List[str]) -> Dict[str, str]:
    """{label: parameter} for `parameters`. A label not yet known is learned with
    one single-parameter call, so a block can always be tied to its token."""
    async with pool.acquire() as conn:
        known = {r["parameter"]: r["label"] for r in await conn.fetch(
            "SELECT parameter, label FROM nidp.trendlyne_param_labels WHERE parameter = ANY($1::text[])", parameters)}
    for parameter in parameters:
        if parameter in known:
            continue
        try:
            text = client.call("get_stock_parameter_values",
                               {"stock_codes": [REFERENCE_STOCK], "parameters": [parameter]})
        finally:
            await _flush_ledger(pool, ledger)
        _, blocks = parse.parse_parameter_values(text)
        if len(blocks) != 1:
            raise TrendlyneError(f"parameter {parameter!r} answered {len(blocks)} blocks, expected 1")
        label = next(iter(blocks))
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO nidp.trendlyne_param_labels (parameter, label) VALUES ($1, $2)", parameter, label)
        known[parameter] = label
        logger.info("trendlyne: learned %s = %r", parameter, label)
        await asyncio.sleep(DELAY_S)
    return {label: parameter for parameter, label in known.items()}


async def fetch(pass_name: str, max_calls: Optional[int] = None, symbols: Optional[List[str]] = None,
                refresh_days: int = 30) -> dict:
    parameters = parse.PASSES[pass_name]
    pool = await get_pool()
    client, ledger = await _client(pool, max_calls)
    run_id = uuid.uuid4()
    stats = {"pass": pass_name, "calls": 0, "symbols_staged": 0, "symbols_unknown_to_provider": 0, "stopped": None}
    try:
        label_to_parameter = await _learn_labels(pool, client, ledger, parameters)
        async with pool.acquire() as conn:
            universe = [s.upper() for s in symbols] if symbols else [r["symbol"] for r in await conn.fetch(_UNIVERSE_SQL)]
            done = {r["symbol"] for r in await conn.fetch(
                "SELECT symbol FROM nidp.trendlyne_param_values "
                "WHERE parameter = ANY($1::text[]) AND fetched_at > NOW() - make_interval(days => $2) "
                "GROUP BY symbol HAVING COUNT(*) = $3", parameters, refresh_days, len(parameters))}
        todo = [s for s in universe if s not in done]
        logger.info("trendlyne fetch %s: %d of %d symbols to stage", pass_name, len(todo), len(universe))

        for i in range(0, len(todo), MAX_STOCKS):
            batch = todo[i:i + MAX_STOCKS]
            try:
                text = client.call("get_stock_parameter_values", {"stock_codes": batch, "parameters": parameters})
            finally:
                await _flush_ledger(pool, ledger)
            stats["calls"] += 1
            stocks, blocks = parse.parse_parameter_values(text)
            unknown = set(blocks) - set(label_to_parameter)
            if unknown or len(blocks) != len(parameters):
                # A label we cannot tie to a token means a value could land in the wrong column.
                raise TrendlyneError(f"unexpected blocks for {pass_name}: unknown={sorted(unknown)} got={len(blocks)}")
            rows = []
            for symbol in batch:
                as_of = stocks.get(symbol)
                if as_of is None:
                    stats["symbols_unknown_to_provider"] += 1
                for label, values in blocks.items():
                    # A company the provider does not know is staged as NULLs so it is not asked for again.
                    rows.append((symbol, label_to_parameter[label], _dec(values.get(symbol)) if as_of else None,
                                 as_of or date.today(), run_id))
            async with pool.acquire() as conn:
                await conn.executemany(
                    """
                    INSERT INTO nidp.trendlyne_param_values (symbol, parameter, value, as_of_date, source_run_id)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (symbol, parameter) DO UPDATE SET
                        value = EXCLUDED.value, as_of_date = EXCLUDED.as_of_date,
                        fetched_at = NOW(), source_run_id = EXCLUDED.source_run_id
                    """, rows)
            stats["symbols_staged"] += len(batch)
            await asyncio.sleep(DELAY_S)
    except BudgetExhausted as exc:
        stats["stopped"] = str(exc)
    finally:
        await _flush_ledger(pool, ledger)
        client.close()
    logger.info("trendlyne fetch: done — %s", stats)
    return stats


# ── sectors ──────────────────────────────────────────────────────────────────

async def sectors(max_calls: Optional[int] = None, symbols: Optional[List[str]] = None) -> dict:
    pool = await get_pool()
    client, ledger = await _client(pool, max_calls)
    stats = {"calls": 0, "written": 0, "not_found": 0, "stopped": None}
    try:
        async with pool.acquire() as conn:
            names = {r["symbol"]: r["company_name"] or "" for r in await conn.fetch(
                "SELECT symbol, company_name FROM nidp.sector_master")}
            if symbols:
                todo = [s.upper() for s in symbols]
            else:
                order = [r["symbol"] for r in await conn.fetch(_UNIVERSE_SQL)]
                missing = {r["symbol"] for r in await conn.fetch(
                    "SELECT symbol FROM nidp.sector_master WHERE sector IS NULL "
                    "AND sector_source IS DISTINCT FROM $1", SECTOR_NOT_FOUND)}
                todo = [s for s in order if s in missing]
        logger.info("trendlyne sectors: %d symbols without a sector", len(todo))
        for symbol in todo:
            # The company name finds far more than the bare symbol does, so it goes first;
            # the symbol is the second try. Either way only an exact NSE-code match is used.
            match = None
            for query in dict.fromkeys(q for q in (parse.company_search_name(names.get(symbol, "")), symbol) if q):
                try:
                    text = client.call("search_entities", {"query": query, "entity_type": "stock", "limit": 5})
                finally:
                    await _flush_ledger(pool, ledger)
                stats["calls"] += 1
                match = next((e for e in parse.parse_entities(text)
                              if e["nse_code"].upper() == symbol and e["sector"] not in ("", "None")), None)
                await asyncio.sleep(DELAY_S)
                if match:
                    break
            async with pool.acquire() as conn:
                if match:
                    status = await conn.execute(
                        "UPDATE nidp.sector_master SET sector = $2, industry = $3, sector_source = $4, "
                        "sector_resolved_at = NOW() WHERE symbol = $1 AND sector IS NULL",
                        symbol, match["sector"], match["industry"] or None, SOURCE)
                    stats["written"] += int(status.split()[-1])
                else:
                    # Marked so the next run does not spend another call on it.
                    await conn.execute(
                        "UPDATE nidp.sector_master SET sector_source = $2, sector_resolved_at = NOW() "
                        "WHERE symbol = $1 AND sector IS NULL", symbol, SECTOR_NOT_FOUND)
                    stats["not_found"] += 1
    except BudgetExhausted as exc:
        stats["stopped"] = str(exc)
    finally:
        await _flush_ledger(pool, ledger)
        client.close()
    logger.info("trendlyne sectors: done — %s", stats)
    return stats


# ── build ────────────────────────────────────────────────────────────────────

_RESULTS_FILINGS_SQL = """
    SELECT ticker_symbol AS symbol, filed_at::date AS filed_on
      FROM nidp.corporate_announcements
     WHERE source = 'NSE_ANN' AND filed_at >= $1
       AND (subject ILIKE '%financial result%'
            OR (subject ILIKE '%outcome of board meeting%' AND description ILIKE '%financial result%'))
"""

_COLUMNS = ["revenue_from_ops_cr", "ebitda_cr", "pat_cr", "eps_basic", "finance_costs_cr", "depreciation_cr",
            "tax_expense_cr", "total_equity_cr", "long_term_debt_cr", "cash_and_equiv_cr"]

_UPSERT_SQL = f"""
    INSERT INTO nidp.nse_financials_quarterly
        (symbol, period_end, period_type, consolidated, {", ".join(_COLUMNS)}, source, source_run_id, raw_data)
    VALUES ($1, $2, 'quarterly', $3, {", ".join(f"${i}" for i in range(4, 4 + len(_COLUMNS)))}, '{SOURCE}', $14, $15)
    ON CONFLICT (symbol, period_end, consolidated, period_type) DO UPDATE SET
        {", ".join(f"{c} = COALESCE(EXCLUDED.{c}, nidp.nse_financials_quarterly.{c})" for c in _COLUMNS)},
        source_run_id = EXCLUDED.source_run_id, raw_data = EXCLUDED.raw_data, ingested_at = NOW()
    WHERE nidp.nse_financials_quarterly.source = '{SOURCE}'
"""


async def build(dry_run: bool = False, symbols: Optional[List[str]] = None) -> dict:
    pool = await get_pool()
    run_id = uuid.uuid4()
    async with pool.acquire() as conn:
        staged: Dict[str, Dict[str, Optional[float]]] = {}
        as_of: Dict[str, date] = {}
        for r in await conn.fetch("SELECT symbol, parameter, value, as_of_date FROM nidp.trendlyne_param_values"):
            staged.setdefault(r["symbol"], {})[r["parameter"]] = float(r["value"]) if r["value"] is not None else None
            as_of[r["symbol"]] = max(as_of.get(r["symbol"], r["as_of_date"]), r["as_of_date"])
        # The newest dated quarter held from any other source, per company.
        anchors = {r["symbol"]: r for r in await conn.fetch(
            f"""SELECT DISTINCT ON (symbol) symbol, period_end, revenue_from_ops_cr, consolidated
                  FROM nidp.nse_financials_quarterly
                 WHERE period_type = 'quarterly' AND source <> '{SOURCE}' AND revenue_from_ops_cr > 0
                 ORDER BY symbol, period_end DESC""")}
        filings: Dict[str, List[date]] = {}
        if as_of:
            since = parse.shift_quarters(parse.quarter_end_on_or_before(min(as_of.values())), -1)
            for r in await conn.fetch(_RESULTS_FILINGS_SQL, since):
                filings.setdefault(r["symbol"], []).append(r["filed_on"])

    stats = {"symbols_staged": len(staged), "no_values": 0, "dated_by_anchor": 0, "dated_by_filings": 0,
             "undated": 0, "anchor_mismatch": 0, "methods_agree": 0, "methods_disagree": 0, "rows_written": 0, "dry_run": dry_run}
    to_write = []
    for symbol in sorted(staged):
        if symbols and symbol not in symbols:
            continue
        values = staged[symbol]
        revenue = {o: values.get(parse.series_token("sr", o)) for o in range(8)}
        if all(v is None for v in revenue.values()) and values.get("npq") is None:
            stats["no_values"] += 1
            continue
        anchor = anchors.get(symbol)
        by_anchor = parse.latest_quarter_from_anchor(
            revenue, anchor["period_end"], float(anchor["revenue_from_ops_cr"]), as_of[symbol]) if anchor else None
        by_filings = parse.latest_quarter_from_filings(as_of[symbol], filings.get(symbol, []))
        if by_anchor and by_filings:
            stats["methods_agree" if by_anchor == by_filings else "methods_disagree"] += 1
        if anchor and not by_anchor:
            # We hold a dated quarter for this company and none of the provider's quarters
            # has its revenue: the two are on different bases (standalone vs consolidated)
            # or the match is ambiguous. Writing the provider's series next to that row
            # would mix bases inside one company's history, so nothing is written.
            stats["anchor_mismatch"] += 1
            continue
        latest_end, method = (by_anchor, "anchor") if by_anchor else (by_filings, "results_filing")
        if latest_end is None:
            stats["undated"] += 1
            continue
        stats["dated_by_anchor" if method == "anchor" else "dated_by_filings"] += 1
        # Trendlyne does not say whether a figure is consolidated. Where an anchor matched,
        # the figures are on the anchor's basis; otherwise the provider's default is assumed.
        consolidated = bool(anchor["consolidated"]) if by_anchor else True
        raw = json.dumps({"provider": SOURCE, "as_of_date": as_of[symbol].isoformat(), "dated_by": method,
                          "consolidated_basis": "matched anchor" if by_anchor else "assumed (provider default)"})
        for row in parse.build_quarter_rows(values, latest_end):
            to_write.append((symbol, row["period_end"], consolidated,
                             *[_dec(row.get(c)) for c in _COLUMNS], run_id, raw))

    if to_write and not dry_run:
        async with pool.acquire() as conn:
            before = await conn.fetchval(
                f"SELECT COUNT(*) FROM nidp.nse_financials_quarterly WHERE source = '{SOURCE}'")
            await conn.executemany(_UPSERT_SQL, to_write)
            after = await conn.fetchval(
                f"SELECT COUNT(*) FROM nidp.nse_financials_quarterly WHERE source = '{SOURCE}'")
        stats["rows_written"] = after - before
        stats["rows_from_this_source_now"] = after
    stats["rows_candidate"] = len(to_write)
    logger.info("trendlyne build: done — %s", stats)
    return stats
