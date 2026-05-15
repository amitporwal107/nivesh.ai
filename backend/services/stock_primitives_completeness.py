"""NIDP Stock Primitives — completeness checker.

Verifies the data lake state for `nidp.v_v3_stock_primitives` (the view
exposed by migration 055). Reports:
  - row count, distinct symbols, date range
  - per-column NULL %
  - universe coverage vs the live Nivesh holding universe (passed in)
  - which fields required by services/stock_scoring.py are entirely missing

Run via the existing SSH bridge — no DaaS API change needed.
"""
from __future__ import annotations

from typing import Any

from services.nidp_vm_query import run_pg_query


# Columns that stock_scoring.py reads via primitives.get(). Order
# matches the call order in stock_scoring.py for readability.
SCORING_PRIMITIVES = [
    "roe_pct",
    "debt_to_equity",
    "eps_growth_3y_cagr_pct",
    "earnings_consistency_score",
    "promoter_holding_pct",
    "cap_bucket",
    "revenue_growth_3y_cagr_pct",
    "profit_margin_trend_pct",
    "debt_trend_pct",
    "volatility_1y_pct",
    "dividend_yield_pct",
    "earnings_surprise_pct",   # known hard gap per migration 055 comment
    "pe_overvaluation_pct",
    "earnings_decline_flag",
    "debt_spike_flag",
    "liquidity_score",
    "momentum_score",
]


async def _table_exists() -> dict[str, bool]:
    script = (
        "async def main():\n"
        "    conn = await asyncpg.connect(DSN)\n"
        "    try:\n"
        "        view = await conn.fetchval(\n"
        "            \"SELECT EXISTS (SELECT 1 FROM information_schema.views \"\n"
        "            \"WHERE table_schema='nidp' AND table_name='v_v3_stock_primitives')\")\n"
        "        base = await conn.fetchval(\n"
        "            \"SELECT EXISTS (SELECT 1 FROM information_schema.tables \"\n"
        "            \"WHERE table_schema='nidp' AND table_name='stock_features_daily')\")\n"
        "        print(json.dumps({'view': bool(view), 'base': bool(base)}))\n"
        "    finally:\n"
        "        await conn.close()\n"
        "asyncio.run(main())\n"
    )
    return await run_pg_query(script)


async def _basic_counts() -> dict[str, Any]:
    script = (
        "async def main():\n"
        "    conn = await asyncpg.connect(DSN)\n"
        "    try:\n"
        "        row = await conn.fetchrow(\n"
        "            'SELECT COUNT(*) AS rows, COUNT(DISTINCT symbol) AS symbols, '\n"
        "            'MIN(as_of_date) AS min_d, MAX(as_of_date) AS max_d '\n"
        "            'FROM nidp.v_v3_stock_primitives')\n"
        "        print(json.dumps({\n"
        "            'rows': int(row['rows'] or 0),\n"
        "            'distinct_symbols': int(row['symbols'] or 0),\n"
        "            'min_date': str(row['min_d']) if row['min_d'] else None,\n"
        "            'max_date': str(row['max_d']) if row['max_d'] else None,\n"
        "        }))\n"
        "    finally:\n"
        "        await conn.close()\n"
        "asyncio.run(main())\n"
    )
    return await run_pg_query(script)


async def _null_percentages(columns: list[str]) -> dict[str, float]:
    # Build SQL that counts NULLs per column in a single pass for cheap perf
    quoted = ", ".join([f"SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END) AS null_{c}"
                        for c in columns])
    script = (
        f"async def main():\n"
        f"    conn = await asyncpg.connect(DSN)\n"
        f"    try:\n"
        f"        row = await conn.fetchrow(\n"
        f"            \"SELECT COUNT(*) AS n, {quoted} FROM nidp.v_v3_stock_primitives \"\n"
        f"            \"WHERE as_of_date = (SELECT MAX(as_of_date) FROM nidp.v_v3_stock_primitives)\")\n"
        f"        n = max(1, int(row['n'] or 0))\n"
        f"        out = {{}}\n"
        f"        for c in {columns!r}:\n"
        f"            null_n = int(row[f'null_' + c] or 0)\n"
        f"            out[c] = round(100.0 * null_n / n, 1)\n"
        f"        print(json.dumps({{'latest_date_row_count': n, 'null_pct': out}}))\n"
        f"    finally:\n"
        f"        await conn.close()\n"
        f"asyncio.run(main())\n"
    )
    return await run_pg_query(script)


async def _universe_overlap(nivesh_symbols: list[str]) -> dict[str, Any]:
    if not nivesh_symbols:
        return {"nivesh_universe_size": 0, "covered_count": 0, "coverage_pct": 0, "missing_sample": []}
    # Send as array literal
    syms_array = "ARRAY[" + ",".join(f"'{s.replace(chr(39), chr(39)+chr(39))}'" for s in nivesh_symbols) + "]"
    script = (
        f"async def main():\n"
        f"    conn = await asyncpg.connect(DSN)\n"
        f"    try:\n"
        f"        rows = await conn.fetch(\n"
        f"            \"WITH univ AS (SELECT UNNEST({syms_array}) AS s) \"\n"
        f"            \"SELECT u.s AS symbol, EXISTS(SELECT 1 FROM nidp.v_v3_stock_primitives p \"\n"
        f"            \"WHERE p.symbol = u.s) AS present FROM univ u\")\n"
        f"        present = [r['symbol'] for r in rows if r['present']]\n"
        f"        missing = [r['symbol'] for r in rows if not r['present']]\n"
        f"        out = {{\n"
        f"            'nivesh_universe_size': len(rows),\n"
        f"            'covered_count': len(present),\n"
        f"            'coverage_pct': round(100.0 * len(present) / max(1, len(rows)), 1),\n"
        f"            'missing_sample': missing[:30],\n"
        f"        }}\n"
        f"        print(json.dumps(out))\n"
        f"    finally:\n"
        f"        await conn.close()\n"
        f"asyncio.run(main())\n"
    )
    return await run_pg_query(script)


async def run_completeness_check(
    nivesh_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Single-shot completeness report. Returns a JSON envelope safe to
    publish to /app/test_reports/ or to surface in the admin UI."""
    exists = await _table_exists()
    if not exists.get("base"):
        return {
            "ok": False,
            "error": "Base table nidp.stock_features_daily does not exist on the VM.",
            "exists": exists,
        }
    if not exists.get("view"):
        return {
            "ok": False,
            "error": "View nidp.v_v3_stock_primitives does not exist — migration 055 has not been applied.",
            "exists": exists,
        }

    basic = await _basic_counts()
    nulls = await _null_percentages(SCORING_PRIMITIVES)
    coverage = await _universe_overlap(nivesh_symbols or [])

    # Diagnose problem fields
    hard_gaps = [c for c, p in nulls["null_pct"].items() if p >= 99.0]
    soft_gaps = [c for c, p in nulls["null_pct"].items() if 50.0 <= p < 99.0]
    healthy = [c for c, p in nulls["null_pct"].items() if p < 50.0]

    return {
        "ok": True,
        "exists": exists,
        "basic": basic,
        "scoring_primitives_total": len(SCORING_PRIMITIVES),
        "scoring_primitives_healthy": healthy,
        "scoring_primitives_soft_gaps": soft_gaps,
        "scoring_primitives_hard_gaps": hard_gaps,
        "null_pct_latest_snapshot": nulls,
        "nivesh_universe_coverage": coverage,
    }


__all__ = ["run_completeness_check", "SCORING_PRIMITIVES"]
