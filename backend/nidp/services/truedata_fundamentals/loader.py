"""Warehouse side (asyncpg): the reference data the transform needs, the locked read of the rows the offers meet, the
writes, the provenance record, and the exact rollback of a run.

Everything one run writes happens in ONE transaction: the rows it meets are read FOR UPDATE, the plan (plan.py) is made
from what was read, and every write is recorded in nidp.truedata_fundamentals_fills (migration 190) with the columns it
filled and the values it wrote. Nothing in nse_financials_quarterly.raw_data is relied on: other writers replace it.

Rollback of a run (`--rollback RUN_ID`), also one transaction:
  * a row the run INSERTED is deleted while it is still the run's (source 'truedata', source_run_id = run);
  * a column the run FILLED is set back to NULL only while it still holds the value the run wrote (it was NULL before,
    by construction); a value another writer has put there since is left alone and counted;
  * the run's provenance rows are stamped rolled_back_at, so a second rollback does nothing.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from nidp.shared.storage.pg import get_pool

from .plan import CASHFLOW, INSERT_SOURCE, Q_COLUMNS, QUARTERLY, Action, Plan, Row, build_plan, offer_keys
from .transform import BS_COLUMNS, CF_COLUMNS, Offer, OurFinancials

logger = logging.getLogger(__name__)

PROVENANCE = "nidp.truedata_fundamentals_fills"
_ALLOWED = {QUARTERLY: set(Q_COLUMNS), CASHFLOW: set(CF_COLUMNS)}


@dataclass
class References:
    known: Set[str]
    bse_map: Dict[str, str]
    ours: OurFinancials
    shares: Dict[str, float]                       # shares outstanding (share-capital unit anchor)
    caps: Dict[str, float] = field(default_factory=dict)    # market cap, crore (fetch order: largest first)


# ── reads ────────────────────────────────────────────────────────────────────────────────────────────────────────

async def read_references(conn, symbols: Optional[Sequence[str]] = None) -> References:
    """Our universe, the BSE scrip → NSE symbol map, our revenue per period (unit anchor and quarter check) and our
    shares outstanding (market cap / close on the day the market cap is as of; share-capital anchor)."""
    if symbols:
        known = {s.strip().upper() for s in symbols if s.strip()}
    else:
        rows = await conn.fetch(
            "SELECT DISTINCT symbol FROM nidp.nse_financials_quarterly "
            "UNION SELECT symbol FROM nidp.stock_features_daily "
            " WHERE as_of_date = (SELECT max(as_of_date) FROM nidp.stock_features_daily)")
        known = {r["symbol"] for r in rows}
    try:
        bse = await conn.fetch(
            "SELECT DISTINCT ON (scrip_code) scrip_code, nse_symbol FROM nidp.v_bse_scrip_to_nse "
            " WHERE nse_symbol IS NOT NULL ORDER BY scrip_code, as_of_date DESC")
        bse_map = {str(r["scrip_code"]).strip(): r["nse_symbol"] for r in bse}
    except Exception as exc:                                   # the view is optional: NSE symbols still resolve
        logger.warning("truedata_fundamentals: no BSE scrip map (%s)", type(exc).__name__)
        bse_map = {}
    syms = sorted(known)
    rev = await conn.fetch(
        "SELECT symbol, period_end, consolidated, period_type, revenue_from_ops_cr::float8 AS revenue_from_ops_cr, "
        "       total_income_cr::float8 AS total_income_cr "
        "  FROM nidp.nse_financials_quarterly WHERE symbol = ANY($1::text[])", syms)
    caps = await conn.fetch(
        """SELECT f.symbol, f.market_cap_cr::float8 AS mcap,
                  COALESCE((SELECT p.close_price FROM nidp.prices_eod p
                             WHERE p.symbol = f.symbol AND p.as_of_date <= COALESCE(f.fundamentals_as_of, f.as_of_date)
                             ORDER BY p.as_of_date DESC, (p.series = 'EQ') DESC LIMIT 1), f.close)::float8 AS close
             FROM nidp.stock_features_daily f
            WHERE f.as_of_date = (SELECT max(as_of_date) FROM nidp.stock_features_daily)
              AND f.market_cap_cr > 0 AND f.symbol = ANY($1::text[])""", syms)
    shares = {r["symbol"]: r["mcap"] * 1e7 / r["close"] for r in caps if r["close"] and r["close"] > 0}
    return References(known, bse_map, OurFinancials([dict(r) for r in rev]), shares,
                      {r["symbol"]: r["mcap"] for r in caps})


async def read_rows(conn, keys: Sequence[Tuple[str, date, bool]], lock: bool) -> Tuple[List[Row], List[Row]]:
    """Every quarterly-table row and cash-flow row of the offered (symbol, period_end, consolidated) keys."""
    if not keys:
        return [], []
    syms, pes, cons = (list(x) for x in zip(*keys))
    qcols = ", ".join(f"q.{c}" for c in Q_COLUMNS)
    q = await conn.fetch(
        f"""SELECT q.symbol, q.period_end, q.consolidated, q.period_type, q.source, {qcols}
              FROM nidp.nse_financials_quarterly q
              JOIN unnest($1::text[], $2::date[], $3::boolean[]) AS k(symbol, period_end, consolidated)
                ON q.symbol = k.symbol AND q.period_end = k.period_end AND q.consolidated = k.consolidated
             {"FOR UPDATE OF q" if lock else ""}""", syms, pes, cons)
    ccols = ", ".join(f"c.{c}" for c in CF_COLUMNS)
    c = await conn.fetch(
        f"""SELECT c.symbol, c.period_end, c.consolidated, c.source, {ccols}
              FROM nidp.nse_financials_cashflow c
              JOIN unnest($1::text[], $2::date[], $3::boolean[]) AS k(symbol, period_end, consolidated)
                ON c.symbol = k.symbol AND c.period_end = k.period_end AND c.consolidated = k.consolidated
             {"FOR UPDATE OF c" if lock else ""}""", syms, pes, cons)
    q_rows = [Row(QUARTERLY, r["symbol"], r["period_end"], r["consolidated"], r["period_type"], r["source"],
                  {col: r[col] for col in Q_COLUMNS}) for r in q]
    cf_rows = [Row(CASHFLOW, r["symbol"], r["period_end"], r["consolidated"], "annual", r["source"],
                   {col: r[col] for col in CF_COLUMNS}) for r in c]
    return q_rows, cf_rows


# ── writes ───────────────────────────────────────────────────────────────────────────────────────────────────────

_Q_FILL = ("UPDATE nidp.nse_financials_quarterly SET "
           + ", ".join(f"{c} = COALESCE({c}, ${i + 5}::numeric)" for i, c in enumerate(Q_COLUMNS))
           + " WHERE symbol = $1 AND period_end = $2 AND consolidated = $3 AND period_type = $4")
_CF_FILL = ("UPDATE nidp.nse_financials_cashflow SET "
            + ", ".join(f"{c} = COALESCE({c}, ${i + 4}::numeric)" for i, c in enumerate(CF_COLUMNS))
            + " WHERE symbol = $1 AND period_end = $2 AND consolidated = $3")
_Q_INSERT = (
    "INSERT INTO nidp.nse_financials_quarterly (symbol, period_end, period_type, consolidated, "
    + ", ".join(BS_COLUMNS) + ", source, source_run_id, raw_data) "
    "SELECT k.symbol, k.period_end, 'annual', k.consolidated, " + ", ".join(f"k.{c}" for c in BS_COLUMNS)
    + f", '{INSERT_SOURCE}', $1::uuid, k.raw::jsonb "
    "  FROM unnest($2::text[], $3::date[], $4::boolean[], "
    + ", ".join(f"${i + 5}::numeric[]" for i in range(len(BS_COLUMNS)))
    + f", ${len(BS_COLUMNS) + 5}::text[]) AS k(symbol, period_end, consolidated, " + ", ".join(BS_COLUMNS) + ", raw) "
    "ON CONFLICT (symbol, period_end, consolidated, period_type) DO NOTHING "
    "RETURNING symbol, period_end, consolidated")
_CF_INSERT = (
    "INSERT INTO nidp.nse_financials_cashflow (symbol, period_end, consolidated, " + ", ".join(CF_COLUMNS)
    + ", source, source_run_id) "
    "SELECT k.symbol, k.period_end, k.consolidated, " + ", ".join(f"k.{c}" for c in CF_COLUMNS)
    + f", '{INSERT_SOURCE}', $1::uuid "
    "  FROM unnest($2::text[], $3::date[], $4::boolean[], "
    + ", ".join(f"${i + 5}::numeric[]" for i in range(len(CF_COLUMNS)))
    + ") AS k(symbol, period_end, consolidated, " + ", ".join(CF_COLUMNS) + ") "
    "ON CONFLICT ON CONSTRAINT uq_cashflow DO NOTHING "
    "RETURNING symbol, period_end, consolidated")
_PROV_INSERT = (
    f"INSERT INTO {PROVENANCE} (run_id, kind, target_table, symbol, period_end, consolidated, period_type, row_source, "
    "td_filing_id, unit, unit_how, columns_filled, values_written, inserted) "
    "VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::text[], $13::jsonb, $14)")


def _written(values: Dict[str, Decimal]) -> str:
    return json.dumps({c: str(v) for c, v in sorted(values.items())})


async def apply_plan(conn, plan: Plan, run_id: str) -> Dict[str, int]:
    """Execute the plan inside the caller's transaction and record every write. Returns write counts."""
    counts: Counter = Counter()
    applied: List[Action] = []

    q_fills = [a for a in plan.actions if a.table == QUARTERLY and a.op == "fill"]
    if q_fills:
        await conn.executemany(_Q_FILL, [(a.symbol, a.period_end, a.consolidated, a.period_type,
                                          *[a.values.get(c) for c in Q_COLUMNS]) for a in q_fills])
        applied += q_fills
    cf_fills = [a for a in plan.actions if a.table == CASHFLOW and a.op == "fill"]
    if cf_fills:
        await conn.executemany(_CF_FILL, [(a.symbol, a.period_end, a.consolidated,
                                           *[a.values.get(c) for c in CF_COLUMNS]) for a in cf_fills])
        applied += cf_fills

    q_ins = [a for a in plan.actions if a.table == QUARTERLY and a.op == "insert"]
    if q_ins:
        raw = [json.dumps({"truedata_fundamentals": {"run_id": run_id, "td_filing_id": a.offer.filing_id,
                                                     "unit": a.offer.unit}}) for a in q_ins]
        got = await conn.fetch(_Q_INSERT, run_id, [a.symbol for a in q_ins], [a.period_end for a in q_ins],
                               [a.consolidated for a in q_ins],
                               *[[a.values.get(c) for a in q_ins] for c in BS_COLUMNS], raw)
        done = {(r["symbol"], r["period_end"], r["consolidated"]) for r in got}
        counts["quarterly_insert_conflicts"] = len(q_ins) - len(done)
        applied += [a for a in q_ins if (a.symbol, a.period_end, a.consolidated) in done]
    cf_ins = [a for a in plan.actions if a.table == CASHFLOW and a.op == "insert"]
    if cf_ins:
        got = await conn.fetch(_CF_INSERT, run_id, [a.symbol for a in cf_ins], [a.period_end for a in cf_ins],
                               [a.consolidated for a in cf_ins], *[[a.values.get(c) for a in cf_ins] for c in CF_COLUMNS])
        done = {(r["symbol"], r["period_end"], r["consolidated"]) for r in got}
        counts["cashflow_insert_conflicts"] = len(cf_ins) - len(done)
        applied += [a for a in cf_ins if (a.symbol, a.period_end, a.consolidated) in done]

    if applied:
        await conn.executemany(_PROV_INSERT, [
            (run_id, a.kind, a.table, a.symbol, a.period_end, a.consolidated, a.period_type, a.row_source,
             a.offer.filing_id, a.offer.unit, a.offer.unit_how, sorted(a.values), _written(a.values), a.op == "insert")
            for a in applied])
    recorded = await conn.fetchval(f"SELECT count(*) FROM {PROVENANCE} WHERE run_id = $1::uuid", run_id)
    if recorded != len(applied):
        raise RuntimeError(f"provenance rows {recorded} != writes {len(applied)}; the run is rolled back")
    for a in applied:
        counts[f"{a.kind}_{a.op}_rows"] += 1
        counts[f"{a.kind}_columns_written"] += len(a.values)
    counts["rows_written"] = len(applied)
    return dict(sorted(counts.items()))


class Warehouse:
    """The job's database side; the service talks only to this (tests pass a fake)."""

    async def references(self, symbols: Optional[Sequence[str]] = None) -> References:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction(readonly=True):
                return await read_references(conn, symbols)

    async def load(self, offers: Sequence[Offer], run_id: str, dry_run: bool) -> Dict[str, Any]:
        pool = await get_pool()
        keys = offer_keys(offers)
        async with pool.acquire() as conn:
            if dry_run:
                async with conn.transaction(readonly=True):          # Postgres refuses any write
                    q_rows, cf_rows = await read_rows(conn, keys, lock=False)
                plan = build_plan(offers, q_rows, cf_rows)
                return {"dry_run": True, "would_write_rows": len(plan.actions), **plan.summary()}
            async with conn.transaction():
                q_rows, cf_rows = await read_rows(conn, keys, lock=True)
                plan = build_plan(offers, q_rows, cf_rows)
                written = await apply_plan(conn, plan, run_id)
            return {"dry_run": False, "planned_rows": len(plan.actions),
                    **{k: v for k, v in plan.counts.items()}, **written}

    async def rollback(self, run_id: str) -> Dict[str, Any]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await rollback_run(conn, run_id)


# ── rollback ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _key_sql(table: str) -> str:
    if table == QUARTERLY:
        return "symbol = $1 AND period_end = $2 AND consolidated = $3 AND period_type = $4"
    return "symbol = $1 AND period_end = $2 AND consolidated = $3"


def _key_args(table: str, p) -> tuple:
    base = (p["symbol"], p["period_end"], p["consolidated"])
    return base + ((p["period_type"],) if table == QUARTERLY else ())


async def rollback_run(conn, run_id: str) -> Dict[str, Any]:
    str(uuid.UUID(str(run_id)))                                     # refuse anything that is not a run id
    counts: Counter = Counter()
    async with conn.transaction():
        prov = await conn.fetch(
            f"SELECT * FROM {PROVENANCE} WHERE run_id = $1::uuid AND rolled_back_at IS NULL ORDER BY id FOR UPDATE",
            str(run_id))
        for p in prov:
            table = p["target_table"]
            if table not in _ALLOWED:
                raise RuntimeError(f"unknown target table {table!r} in provenance")
            if p["inserted"]:
                n = len(_key_args(table, p))
                status = await conn.execute(
                    f"DELETE FROM nidp.{table} WHERE {_key_sql(table)} "
                    f"AND source = '{INSERT_SOURCE}' AND source_run_id = ${n + 1}::uuid",
                    *_key_args(table, p), str(run_id))
                deleted = int(status.split()[-1])
                counts["inserted_rows_deleted" if deleted else "inserted_rows_no_longer_ours"] += 1
                continue
            cols = [c for c in (p["columns_filled"] or []) if c in _ALLOWED[table]]
            if len(cols) != len(p["columns_filled"] or []):
                raise RuntimeError(f"unexpected column in provenance row {p['id']}")
            written = p["values_written"]
            written = json.loads(written) if isinstance(written, str) else dict(written or {})
            row = await conn.fetchrow(f"SELECT {', '.join(cols)} FROM nidp.{table} WHERE {_key_sql(table)} FOR UPDATE",
                                      *_key_args(table, p))
            if row is None:
                counts["filled_rows_gone"] += 1
                continue
            back = [c for c in cols if row[c] is not None and c in written and row[c] == Decimal(written[c])]
            counts["columns_changed_since_kept"] += len(cols) - len(back)
            if back:
                await conn.execute(f"UPDATE nidp.{table} SET {', '.join(f'{c} = NULL' for c in back)} "
                                   f"WHERE {_key_sql(table)}", *_key_args(table, p))
                counts["columns_reset_to_null"] += len(back)
                counts["rows_reset"] += 1
        await conn.execute(f"UPDATE {PROVENANCE} SET rolled_back_at = now() "
                           "WHERE run_id = $1::uuid AND rolled_back_at IS NULL", str(run_id))
    counts["provenance_rows"] = len(prov)
    return dict(sorted(counts.items()))
