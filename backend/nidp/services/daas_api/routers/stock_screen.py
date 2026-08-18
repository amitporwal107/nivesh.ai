"""Full-universe stock screener (S2) — POST /v1/stocks/screen.

Why a new endpoint rather than extending ``/v1/stocks/screener``: that one is
key-gated public and has internal callers (the copilot widget, ``/screener/top``,
sector aggregates). Changing its semantics under them would be a silent break, so
it is left byte-identical and callers migrate deliberately.

What this fixes, measured on nidp_staging 2026-08-17:

  * **Filters are evaluated in SQL over the whole universe.** The existing path
    runs 12 filters server-side and applies everything else client-side over rows
    fetched with ``sort_by=roe_pct, limit=60`` — so "P/E under 15" silently means
    "P/E under 15 among the top 60 stocks by ROE". That is a wrong answer wearing
    a feature's clothes.
  * **``total`` is returned.** ``envelope()`` accepts it but the legacy handler
    never passes it, so ``pagination.total`` is always null and a caller cannot
    tell "12 matched" from "12 shown of unknown".
  * **Sorts are deterministic.** ``ORDER BY <col> DESC NULLS LAST`` with no
    tiebreaker reorders tied rows between calls, so page 2 can repeat or skip a
    row that page 1 already showed.
  * **Only measured-available metrics are offered**, and a hidden one says why.
  * **Zero results explain themselves** with leave-one-out counts and a threshold
    derived from the real distribution — not a hardcoded step.

Contract: .claude/workspace/stock-screener/contracts/screener-api-contract.md
Executable contract: backend/tests/test_screener_contract.py
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api import metric_registry as reg
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, jsonify
from nidp.services.daas_api.screen_query import (
    FEATURES_TABLE, ScreenQueryError, metric_or_raise, predicate, select_columns, where,
)

router = APIRouter(
    prefix="/stocks",
    tags=["stock-screen"],
    dependencies=[Depends(require_api_key)],
)

_FEATURES = FEATURES_TABLE
_MAX_LIMIT = 500
# Rows a relaxed threshold should aim to admit when suggesting a loosening (B6-A).
_SUGGEST_TARGET_ROWS = 10


class _Bad(HTTPException):
    def __init__(self, msg: str) -> None:
        super().__init__(status_code=400, detail=msg)


def _metric_or_400(key: str) -> reg.Metric:
    try:
        return metric_or_raise(key)
    except ScreenQueryError as e:
        raise _Bad(str(e))


def _where(filters: List[Dict[str, Any]], as_of: Any):
    """Adapt the pure builder's errors onto HTTP 400."""
    try:
        return where(filters, as_of)
    except ScreenQueryError as e:
        raise _Bad(str(e))


async def _coverage(conn, as_of) -> Dict[str, Dict[str, Any]]:
    """Per-metric coverage for the as-of date.

    Reads nidp.metric_coverage_daily when migration 130 has landed; otherwise
    measures inline so the availability gate works from day one. The inline path
    is bounded (one pass over ~2.4k rows) and lets the endpoint ship before the
    migration without ever guessing at availability.
    """
    out: Dict[str, Dict[str, Any]] = {}
    has_table = await conn.fetchval(
        "SELECT to_regclass('nidp.metric_coverage_daily') IS NOT NULL"
    )
    if has_table:
        rows = await conn.fetch(
            "SELECT metric_key, rows_total, rows_non_null, distinct_non_null "
            "FROM nidp.metric_coverage_daily WHERE as_of_date = $1", as_of)
        for r in rows:
            total = r["rows_total"] or 0
            out[r["metric_key"]] = {
                "covered_pct": round(100.0 * (r["rows_non_null"] or 0) / total, 1) if total else 0.0,
                "distinct_non_null": r["distinct_non_null"] or 0,
            }
        if out:
            return out

    parts = []
    for m in reg._METRICS:
        parts.append(
            f'COUNT(f."{m.column}") AS "n_{m.key}", '
            f'COUNT(DISTINCT f."{m.column}") AS "d_{m.key}"'
        )
    row = await conn.fetchrow(
        f'SELECT COUNT(*) AS total, {", ".join(parts)} FROM {_FEATURES} f WHERE f.as_of_date = $1',
        as_of)
    total = row["total"] or 0
    for m in reg._METRICS:
        n = row[f"n_{m.key}"] or 0
        out[m.key] = {
            "covered_pct": round(100.0 * n / total, 1) if total else 0.0,
            "distinct_non_null": row[f"d_{m.key}"] or 0,
        }
    return out


def _cell(m: reg.Metric, value: Any, as_of: Any) -> Dict[str, Any]:
    """One cell WITH its provenance inline (C1/C2). A null value must explain
    itself — a bare em-dash is the silent failure this product exists to avoid."""
    cell: Dict[str, Any] = {"value": jsonify(value), "as_of": jsonify(as_of)}
    if value is None:
        cell["null_reason"] = (
            "Not reported for this company in the latest available filing"
            if m.source_dataset.endswith("financials_quarterly")
            else "No value available for this company today")
        return cell
    cell["formula"] = m.formula
    cell["source_dataset"] = m.source_dataset
    # C2 — a price-derived value must say how many sessions produced it, so a
    # user can tell a 20-session average from a 200-session one at a glance.
    if m.source_dataset == "nidp.prices_eod" and m.key.endswith("_20"):
        cell["bar_count"] = 20
    return cell


async def _filter_impact(conn, filters, as_of) -> List[Dict[str, Any]]:
    """B6-A: for each filter, how many rows return without it, and what relaxed
    threshold would actually admit some — derived from the real distribution of
    the rows passing every OTHER filter, never a hardcoded step.

    Runs ONLY on a zero-result screen (B6-B) so the normal path keeps its latency.
    """
    impacts: List[Dict[str, Any]] = []
    for i, f in enumerate(filters):
        others = [g for j, g in enumerate(filters) if j != i]
        where_sql, params = _where(others, as_of)
        loo = await conn.fetchval(
            f"SELECT COUNT(*) FROM {_FEATURES} f WHERE {where_sql}", *params) or 0

        m = _metric_or_400(f["key"])
        suggested: Optional[float] = None
        would: int = 0
        op = f.get("op")
        if loo > 0 and op in ("gte", "gt", "lte", "lt") and not m.is_text:
            # Aim at the threshold that admits ~_SUGGEST_TARGET_ROWS of the passing
            # set: for a minimum filter that is a LOW percentile, for a maximum a
            # HIGH one.
            frac = min(0.95, max(0.05, _SUGGEST_TARGET_ROWS / loo))
            pct = 1.0 - frac if op in ("gte", "gt") else frac
            # `where_sql` already numbers its own placeholders from $1 (as_of is
            # $1), so the percentile fraction MUST be appended LAST. Passing it
            # first shifts every placeholder and hands the date comparison a
            # float: "operator does not exist: date = double precision".
            pct_params = list(params) + [pct]
            suggested = await conn.fetchval(
                f'SELECT percentile_cont(${len(pct_params)}) '
                f'WITHIN GROUP (ORDER BY f."{m.column}") '
                f"FROM {_FEATURES} f WHERE {where_sql} AND f.\"{m.column}\" IS NOT NULL",
                *pct_params)
            if suggested is not None:
                suggested = round(float(suggested), 2)
                probe = dict(f)
                probe["value"] = suggested
                w2, p2 = _where(others + [probe], as_of)
                would = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {_FEATURES} f WHERE {w2}", *p2) or 0

        impacts.append({
            "key": f["key"], "op": op, "value": f.get("value"),
            "leave_one_out_count": int(loo),
            "suggested_value": suggested,
            "would_return": int(would),
            "most_restrictive": False,
        })

    if impacts:
        top = max(impacts, key=lambda d: d["leave_one_out_count"])
        top["most_restrictive"] = True
    return impacts


@router.post("/screen", summary="Full-universe screener with provenance (S2)")
async def screen(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    filters: List[Dict[str, Any]] = payload.get("filters") or []
    if not isinstance(filters, list):
        raise _Bad("`filters` must be a list")
    page = payload.get("page") or {}
    limit = min(int(page.get("limit", 50)), _MAX_LIMIT)
    offset = max(int(page.get("offset", 0)), 0)
    columns: List[str] = payload.get("columns") or []
    sort = payload.get("sort") or {}

    pool = await get_pool()
    async with pool.acquire() as conn:
        as_of = payload.get("as_of") or await conn.fetchval(
            f"SELECT MAX(as_of_date) FROM {_FEATURES}")
        if as_of is None:
            raise HTTPException(status_code=503, detail="feature store is empty")

        coverage = await _coverage(conn, as_of)
        offered = [m.key for m in reg._METRICS if reg.is_offered(m, coverage.get(m.key))]
        hidden = [
            {"key": m.key,
             "reason": reg.hidden_reason(m, coverage.get(m.key)),
             "measured": coverage.get(m.key, {})}
            for m in reg._METRICS if m.key not in offered
        ]

        # Fail closed: a filter on a metric we cannot honestly serve is refused
        # rather than silently returning a set the user will misread.
        for f in filters:
            if f.get("key") not in offered:
                raise _Bad(
                    f"metric {f.get('key')!r} is not available today: "
                    f"{reg.hidden_reason(_metric_or_400(f.get('key')), coverage.get(f.get('key')))}")

        where_sql, params = _where(filters, as_of)
        universe_size = await conn.fetchval(
            f"SELECT COUNT(*) FROM {_FEATURES} f WHERE f.as_of_date = $1", as_of) or 0
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM {_FEATURES} f WHERE {where_sql}", *params) or 0

        wanted = [k for k in (columns or []) if k in reg.BY_KEY]
        for f in filters:                      # C5 — filtered metrics are always columns
            if f["key"] not in wanted:
                wanted.append(f["key"])
        if not wanted:
            wanted = [k for k in ("roe_pct", "pe_ttm", "market_cap_cr") if k in offered]

        sort_key = sort.get("key") if sort.get("key") in offered else (
            wanted[0] if wanted else "symbol")
        sort_col = reg.BY_KEY[sort_key].column if sort_key in reg.BY_KEY else "symbol"
        direction = "ASC" if str(sort.get("dir", "desc")).lower() == "asc" else "DESC"

        rows = await conn.fetch(
            f"SELECT {select_columns(wanted)} FROM {_FEATURES} f WHERE {where_sql} "
            # `, f.symbol ASC` is load-bearing: without a tiebreaker, tied rows
            # reorder between calls and pagination repeats or drops rows (B1).
            f'ORDER BY f."{sort_col}" {direction} NULLS LAST, f.symbol ASC '
            f"LIMIT {int(limit)} OFFSET {int(offset)}",
            *params)

        out_rows: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            cells = {k: _cell(reg.BY_KEY[k], d.get(reg.BY_KEY[k].column), as_of) for k in wanted}
            matched = [{
                "key": f["key"], "op": f["op"],
                "threshold": f.get("value", f.get("values", [f.get("min"), f.get("max")])),
                "actual": jsonify(d.get(reg.BY_KEY[f["key"]].column)),
            } for f in filters]
            out_rows.append({
                # The feature store carries no company-name column, so `name`
                # is the symbol. Returning the sector here would look like a
                # name and read as wrong data — better an honest duplicate.
                "symbol": d["symbol"], "name": d["symbol"],
                "sector": d.get("sector"),
                "cells": cells, "matched": matched, "events": [], "flags": [],
            })

        impact = await _filter_impact(conn, filters, as_of) if (total == 0 and filters) else None

    notice = None
    if filters:
        k = filters[0]["key"]
        cov = coverage.get(k, {})
        covered = int(round((cov.get("covered_pct") or 0) / 100.0 * universe_size))
        notice = {
            "metric": k, "covered": covered, "universe": universe_size,
            "text": (f"{covered:,} of {universe_size:,} companies have "
                     f"{reg.BY_KEY[k].label}. Results are drawn from those {covered:,}."),
        }

    # Pagination block reuses the shared envelope so this endpoint stays
    # consistent with the rest of the DaaS; `data` carries the screener contract.
    base = envelope(out_rows, limit=limit, offset=offset, total=int(total))
    base["data"] = {
        "as_of_date": jsonify(as_of),
        "registry_version": reg.REGISTRY_VERSION,
        "universe": {"name": payload.get("universe") or "all", "size": int(universe_size)},
        "total": int(total),
        "rows": out_rows,
        "offered_metrics": offered,
        "hidden_metrics": hidden,
        "coverage_notice": notice,
        "filter_impact": impact,
        "event_coverage": None,
    }
    return base


@router.get("/screener/registry", summary="Metric registry + measured availability (PLAT-4)")
async def registry(as_of: Optional[str] = None) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        target = as_of or await conn.fetchval(f"SELECT MAX(as_of_date) FROM {_FEATURES}")
        coverage = await _coverage(conn, target)
    return {
        "data": {
            "registry_version": reg.REGISTRY_VERSION,
            "as_of_date": jsonify(target),
            "metrics": [reg.to_payload(m, coverage.get(m.key)) for m in reg._METRICS],
            "event_categories": reg.EVENT_CATEGORIES,
            "curated_screens": [],
        }
    }
