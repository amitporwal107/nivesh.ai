"""fundamentals_source / fundamentals_as_of on nidp.stock_features_daily (migration 162).

The two columns say where a row's roe_pct, roce_pct, debt_to_equity, pb and market_cap_cr
came from (a source named in nidp.stock_fundamental_values, or ``nidp_computed`` for the
engine's own calculation) and the day those figures are as of. For a row sourced from
outside, market cap and P/B use that day's close, not the row's own.

Code reaches the staging data platform on every push to dev; migrations are applied in a
separate step. Until 162 is applied the columns do not exist, and a query naming them fails.
``source_columns`` therefore gives the real columns once they exist and typed NULLs before,
so the routes answer either way and start returning the fields the moment the migration lands.
"""
from __future__ import annotations

_present = False     # only ever flips to True: a column, once added, stays

_CHECK_SQL = """
    SELECT COUNT(*) = 2
      FROM information_schema.columns
     WHERE table_schema = 'nidp' AND table_name = 'stock_features_daily'
       AND column_name IN ('fundamentals_source', 'fundamentals_as_of')
"""


async def source_columns(conn, alias: str = "") -> str:
    """Select-list SQL for the two columns, for a query over nidp.stock_features_daily
    (pass the table's alias, if the query uses one)."""
    global _present
    if not _present:
        _present = bool(await conn.fetchval(_CHECK_SQL))
    if not _present:
        return "NULL::text AS fundamentals_source, NULL::date AS fundamentals_as_of"
    prefix = f"{alias}." if alias else ""
    return f"{prefix}fundamentals_source, {prefix}fundamentals_as_of"
