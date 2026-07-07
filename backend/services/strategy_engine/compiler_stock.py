"""DSL → SQL compiler for STOCK strategies.

Emits a parameterised SELECT against
    nidp.stock_features_daily f
LEFT JOINed to
    nidp.stock_daily_snapshot s     (universe membership: in_nifty50/100/500)

returning the symbol set that matches the entry rules on a given
as_of_date, ranked by the spec's `ranking.by` field, capped at
`ranking.limit`. The same query shape works for backtest sweeps
(parameterise as_of_date) and live runs (one date).

Phase-1 scope: only `feature.*` predicates and `index|custom` universes.
Phase-2 will extend with fundamental.* / shareholding.* / institutional.* /
sector.* once those snapshots land.

Output of compile() is `(sql_text, params_dict)` — both safe to feed
straight into asyncpg / psycopg.

Critical safety property: no string interpolation of user content. All
values flow through positional/named parameters. The only literals we
substitute are *column identifiers*, which are validated against
STOCK_FEATURE_COLS in dsl.py before reaching here — that whitelist is
the security boundary for the otherwise-trusted JSON spec.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .dsl import (
    DSLError, STOCK_FEATURE_COLS, RANKING_FIELDS,
    validate_strategy,
)


# Universe references → SQL clause.
#
# Two membership modes (caller picks via `point_in_time_universe`):
#
#   • LEGACY (default) — present-day membership off `stock_master`
#     (226 large/midcaps with is_nifty_100=TRUE). A pragmatic stand-in
#     when `nidp.index_constituents` isn't populated; carries survivorship
#     bias and does NOT distinguish Nifty 100/200/500.
#
#   • POINT-IN-TIME — membership as of the most recent index_constituents
#     snapshot on/before the bar date. Survivorship-correct and gives a
#     real Nifty 50/100/200/500 distinction. Used by the backtest when the
#     constituents table is populated for the chosen index.
INDEX_REFS = {
    "NIFTY50":  "sm.market_cap_cr IS NOT NULL AND sm.market_cap_cr >= "
                "(SELECT market_cap_cr FROM stock_master WHERE is_nifty_100 "
                "  ORDER BY market_cap_cr DESC NULLS LAST OFFSET 49 LIMIT 1)",
    "NIFTY100": "sm.is_nifty_100 IS TRUE",
    "NIFTY200": "sm.is_nifty_100 IS TRUE",   # legacy fallback: this env covers ~226
    "NIFTY500": "sm.is_nifty_100 IS TRUE",   # legacy fallback: this env covers ~226
}

# Maps a universe ref → the index_name string stored in
# nidp.index_constituents (verbatim from config.INDEX_CONSTITUENT_URLS keys).
# These are TRUSTED constants — never user input — so they are safe to
# inline as SQL literals in the point-in-time clause below.
_PIT_INDEX_NAME = {
    "NIFTY50": "Nifty 50", "NIFTY100": "Nifty 100",
    "NIFTY200": "Nifty 200", "NIFTY500": "Nifty 500",
}


def _pit_index_clause(index_name: str) -> str:
    """Point-in-time membership: symbol is in `index_name` as of the latest
    constituents snapshot on/before the bar date (f.as_of_date)."""
    return (
        "f.symbol IN (SELECT ic.symbol FROM nidp.index_constituents ic "
        f"WHERE ic.index_name = '{index_name}' "
        "AND ic.as_of_date = (SELECT MAX(ic2.as_of_date) "
        "FROM nidp.index_constituents ic2 "
        f"WHERE ic2.index_name = '{index_name}' "
        "AND ic2.as_of_date <= f.as_of_date))"
    )


class CompileError(Exception):
    """Raised when a validated DSL document still can't be compiled
    (e.g. references a Phase-2 namespace we don't yet support)."""


def compile_stock_query(
    spec: Dict[str, Any],
    *,
    as_of_date_param: str = "as_of_date",
    point_in_time_universe: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    """Compile a STOCK strategy DSL into (sql, params).

    The caller binds `as_of_date_param` — defaulting to "as_of_date" — so
    the same compiled SQL can be reused across many dates in a backtest.

    `point_in_time_universe`: when True, index universes resolve to
    survivorship-correct membership from nidp.index_constituents as of the
    bar date; when False (default) they use the legacy present-day
    stock_master flag. The backtest sets this True only when the
    constituents table is populated for the chosen index (see backtest.py).

    Raises CompileError on Phase-2 namespaces or unknown universe refs.
    Validation errors should be caught earlier via validate_strategy();
    we re-validate defensively here so a malformed spec never reaches
    SQL generation.
    """
    errs = validate_strategy(spec)
    if errs:
        raise CompileError("invalid spec: " + "; ".join(str(e) for e in errs))

    if spec["asset_class"] != "STOCK":
        raise CompileError("compile_stock_query only supports STOCK strategies")

    where_parts: List[str] = []
    params: Dict[str, Any] = {}
    next_param_id = [0]

    def add_param(value: Any) -> str:
        idx = next_param_id[0]
        next_param_id[0] += 1
        key = f"p{idx}"
        params[key] = value
        return f":{key}"   # asyncpg-style; route layer translates if needed

    # ── Universe ────────────────────────────────────────────────────
    uni = spec["universe"]
    where_parts.append(_compile_universe(uni, add_param, point_in_time_universe))

    # ── Entry predicates ────────────────────────────────────────────
    entry = spec["entry"]
    if "all_of" in entry:
        for p in entry["all_of"]:
            where_parts.append(_compile_predicate(p, add_param))
    if "any_of" in entry:
        any_clauses = [_compile_predicate(p, add_param) for p in entry["any_of"]]
        where_parts.append("(" + " OR ".join(any_clauses) + ")")

    # ── Ranking ─────────────────────────────────────────────────────
    ranking = spec["ranking"]
    by = ranking["by"]
    order = ranking.get("order", "desc").upper()
    limit = int(ranking["limit"])
    if by not in RANKING_FIELDS:
        raise CompileError(f"ranking.by {by!r} not in allowed fields")
    # `composite_score` and `score` are aliases; map both to a literal
    # placeholder until Phase-2 scoring layer materialises them. For now,
    # rank by the same column as a default-ranked field.
    if by in {"composite_score", "score"}:
        order_col = "f.accumulation_score"   # safest Phase-1 proxy
    else:
        order_col = f"f.{by}"

    # ── Final SQL ───────────────────────────────────────────────────
    # Phase-1: features_daily JOINed to stock_master for sector / index
    # membership. `nidp.stock_daily_snapshot` (the canonical NIDP table)
    # isn't deployed in this env yet; stock_master is the available
    # equivalent for this codebase. When NIDP rolls out we swap the
    # JOIN target without touching the predicate logic.
    where_sql = "\n  AND ".join(where_parts)
    # `pea.adj_close` / `adj_factor` come from the corp-action-adjusted
    # series (split+bonus). The backtest trades on adj_close so a split or
    # bonus mid-trade doesn't fabricate a gain/loss; the LEFT JOIN keeps the
    # row even where the adjusted series is missing (caller falls back to
    # f.close). The live Screen step ignores these columns harmlessly.
    sql = f"""
SELECT f.symbol,
       f.as_of_date,
       f.close,
       pea.adj_close,
       pea.cumulative_adj_factor AS adj_factor,
       f.rsi14,
       f.vol_z20,
       f.atr14,
       f.atr_pct,
       f.sma20, f.sma50, f.sma200,
       f.swing_high_20,
       f.swing_low_20,
       f.accumulation_score,
       f.return_20d_pct,
       sm.sector,
       sm.market_cap_cr
  FROM nidp.stock_features_daily f
  LEFT JOIN stock_master sm
    ON sm.nse_symbol = f.symbol
  LEFT JOIN nidp.prices_eod_adjusted pea
    ON pea.symbol = f.symbol AND pea.as_of_date = f.as_of_date
 WHERE f.as_of_date = :{as_of_date_param}
  AND {where_sql}
 ORDER BY {order_col} {order} NULLS LAST
 LIMIT {limit}
""".strip()

    return sql, params


# ── Internal helpers ────────────────────────────────────────────────
def _compile_universe(uni: Dict[str, Any], add_param,
                      point_in_time: bool = False) -> str:
    t = uni["type"]
    ref = uni["ref"]
    if t == "index":
        key = ref.upper()
        if key not in INDEX_REFS:
            raise CompileError(f"unknown index ref {ref!r}; "
                               f"supported: {sorted(INDEX_REFS)}")
        if point_in_time and key in _PIT_INDEX_NAME:
            return _pit_index_clause(_PIT_INDEX_NAME[key])
        return INDEX_REFS[key]
    if t == "custom":
        # ref is a user_universes.id (UUID string). Compiler expands to a
        # subselect that pulls the symbols[] column; the route layer
        # is responsible for verifying the universe belongs to the caller.
        param = add_param(ref)
        return (f"f.symbol = ANY (SELECT unnest(symbols) FROM user_universes "
                f"WHERE id = {param})")
    raise CompileError(f"universe type {t!r} not supported in Phase 1 "
                       f"(allowed: index, custom)")


def _compile_predicate(p: Dict[str, Any], add_param) -> str:
    """Compile a single predicate.

    Handles `feature.*` (numeric/boolean columns on stock_features_daily) and
    `sector` set membership (against f.sector). The `fundamental.*`/
    `shareholding.*`/`institutional.*`/`mf` namespaces remain Phase-2 and reject
    here — fundamentals are reachable today via `feature.*` because the feature
    store already carries those columns.
    """
    ns = next(k for k in ("feature", "fundamental", "shareholding",
                          "institutional", "mf", "sector") if k in p)

    if ns == "sector":
        # {"sector": "in"|"not_in", "value": ["Banking", "IT", …]}.
        # Sector strings flow through params (never interpolated); f.sector is
        # the NSE-industry column on stock_features_daily.
        op = p["op"]
        vals = p.get("value") or []
        if not isinstance(vals, list) or not vals:
            raise CompileError("sector predicate requires a non-empty value list")
        placeholders = ", ".join(add_param(str(v)) for v in vals)
        neg = "NOT " if op == "not_in" else ""
        return f"{neg}f.sector IN ({placeholders})"

    if ns != "feature":
        raise CompileError(
            f"namespace {ns!r} not yet supported in Phase 1 "
            "(coming in Phase 2 along with the fundamentals/shareholding/NSDL ingesters)"
        )

    field = p["feature"]
    if field not in STOCK_FEATURE_COLS:
        raise CompileError(f"unknown feature {field!r}")

    col = f"f.{field}"
    op = p["op"]

    # Boolean field special-case: pivot_breakout_flag stored as boolean,
    # users compare with `op="="` and `value=1` (or 0). Translate.
    if field == "pivot_breakout_flag":
        if "value" not in p:
            raise CompileError("pivot_breakout_flag requires `value`")
        truthy = bool(int(p["value"]))
        if op not in ("=", "!="):
            raise CompileError("pivot_breakout_flag only supports = and !=")
        eq = "" if op == "=" else "NOT "
        return f"{eq}{col} IS {('TRUE' if truthy else 'FALSE')}"

    if "value" in p:
        param = add_param(p["value"])
        return f"{col} {op} {param}"
    # compare_to — second feature column. Validated against whitelist.
    other = p["compare_to"]
    if other not in STOCK_FEATURE_COLS:
        raise CompileError(f"compare_to {other!r} not in feature whitelist")
    return f"{col} {op} f.{other}"


# ── Sanitiser for asyncpg-style $1, $2 binding ──────────────────────
# Our compiler emits :name placeholders for readability. Some drivers
# (asyncpg) want $1, $2. This helper translates and returns a positional
# args list in stable order.
def to_asyncpg(sql: str, params: Dict[str, Any]) -> Tuple[str, List[Any]]:
    """Convert :name → $N and return positional args list.

    We rely on the compiler emitting params named p0, p1, … in declaration
    order so the positional list trivially matches. Any extra non-pN
    bindings the route adds (e.g. as_of_date) get assigned slots after.
    """
    ordered_keys: List[str] = []
    out_sql = sql
    # The compiler-managed params first, in their numeric order
    for i in range(len(params)):
        key = f"p{i}"
        if key in params and (f":{key}" in out_sql):
            ordered_keys.append(key)
            out_sql = out_sql.replace(f":{key}", f"${len(ordered_keys)}")
    # Then any non-pN names the caller bound (e.g. as_of_date)
    import re
    for m in re.finditer(r":([a-zA-Z_][a-zA-Z0-9_]*)", out_sql):
        name = m.group(1)
        if name not in ordered_keys and name in params:
            ordered_keys.append(name)
            out_sql = out_sql.replace(f":{name}", f"${len(ordered_keys)}")
    return out_sql, [params[k] for k in ordered_keys]
