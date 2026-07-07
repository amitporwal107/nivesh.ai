"""Strategy DSL — JSON spec for multi-asset (STOCK | MF) strategies.

The DSL is a versioned JSON document. Phase-1 grammar (v1) covers
stock technicals; Phase-2 extends with `fundamental.*`, `shareholding.*`,
`mf.*`, `institutional.*`, `sector.*` namespaces.

────────────────────────────────────────────────────────────────────
Document shape (v1):

    {
      "version":      "1",
      "asset_class":  "STOCK" | "MF",
      "name":         str,
      "description":  str (optional),
      "universe":     {"type": "index"|"custom"|"category", "ref": str},
      "entry":        {"all_of": [Predicate, …], "any_of": [Predicate, …]?},
      "exit":         {"stoploss_pct": num, "target_rr": num,
                       "max_hold_days": int, "trailing_atr_mult": num?},
      "ranking":      {"by": str, "limit": int, "order": "asc"|"desc"?},
      "rebalance":    "daily" | "weekly" | "monthly"
    }

Predicate (one of):

    {"feature":      "<name>", "op": "<", "value": num}
    {"feature":      "<name>", "op": ">", "compare_to": "<other_feature>"}
    {"fundamental":  "<name>", "op": "<", "value": num}                  # Phase 2
    {"shareholding": "<name>", "op": ">", "value": num}                  # Phase 2
    {"institutional":"<name>", "op": ">", "value": num}                  # Phase 2
    {"mf":           "<name>", "op": ">=", "value": num}                 # Phase 2
    {"sector":       "in",     "value": ["BANKING","IT", …]}
    {"sector":       "not_in", "value": [...]}

`feature.<name>` resolves against nidp.stock_features_daily columns.
`fundamental/shareholding/institutional/mf/sector` Phase-2 namespaces
resolve against their respective NIDP tables. The compiler validates
that every namespace.name is a known column before emitting SQL.

────────────────────────────────────────────────────────────────────
Why JSON + JSON-Schema validation?

  • LLM target — Anthropic Copilot (Phase 4) can be prompted to emit
    JSON directly; YAML or a custom DSL would need round-trip parsing.
  • Stable serialisation — strategies persisted to Postgres JSONB stay
    valid across DSL versions if we add migration shims at parse time.
  • Lossless round-trip — UI editor reads JSON, mutates fields, writes
    JSON. No grammar to keep in sync between two layers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ── Vocabularies ────────────────────────────────────────────────────
DSL_VERSION = "1"

ASSET_CLASSES = {"STOCK", "MF"}

UNIVERSE_TYPES = {"index", "custom", "category"}

# Phase 1: only `feature` namespace fully wired. Other namespaces accepted
# at validation time so Phase 2 specs round-trip cleanly, but the compiler
# rejects them until the corresponding snapshot tables land.
NAMESPACES = {"feature", "fundamental", "shareholding", "institutional", "mf", "sector"}

OPS_NUMERIC = {"<", "<=", ">", ">=", "=", "!="}
OPS_SET = {"in", "not_in"}

# Subset of nidp.stock_features_daily columns exposed via DSL.
# Anything not in this list is rejected at compile time with a clear error.
#
# The `feature.*` namespace resolves against nidp.stock_features_daily. That
# feature store denormalises the fundamentals/ownership columns the copilot
# stock-screener already filters on (see _PRIMITIVE_COLS in
# nidp/services/daas_api/routers/stock_scores.py — the exact same table), so
# exposing them here lets a screen become a runnable strategy without the
# Phase-2 `fundamental.*`/`shareholding.*` namespaces (which stay unwired and
# still reject at compile time — kept for a future dedicated-table impl).
STOCK_FEATURE_COLS = {
    # ── Technical (Phase 1) ──
    "close",
    "sma20", "sma50", "sma100", "sma200", "sma50_slope",
    "dist_200dma_pct", "dist_52w_high_pct", "dist_52w_low_pct",
    "rsi14", "macd", "macd_signal", "macd_hist",
    "return_5d_pct", "return_20d_pct", "return_60d_pct",
    "atr14", "atr_pct", "bb_width", "bb_pos",
    "avg_volume_20", "vol_z20", "deliv_pct_avg_20", "deliv_trend10",
    "swing_high_20", "swing_low_20", "pivot_breakout_flag",
    "accumulation_score",
    # ── Fundamentals / ownership / risk (already on stock_features_daily) ──
    # Valuation
    "pe_ttm", "pb", "ev_ebitda", "pe_vs_sector_pct", "dividend_yield_pct",
    # Profitability / quality
    "roe_pct", "roce_pct", "profit_margin_pct", "interest_coverage",
    "earnings_consistency_score",
    # Growth
    "revenue_growth_3y_cagr_pct", "eps_growth_3y_cagr_pct",
    "revenue_growth_yoy_pct", "pat_growth_yoy_pct", "eps_growth_yoy_pct",
    "profit_margin_trend_pct",
    # Financial health
    "debt_to_equity", "debt_trend_pct", "liquidity_score",
    # Size
    "market_cap_cr",
    # Price / technical (1Y)
    "return_252d_pct", "volatility_1y_pct", "beta_1y", "max_drawdown_1y_pct",
    "momentum_score",
    # Ownership / smart money
    "promoter_pct", "promoter_pledged_pct", "fii_pct", "dii_pct",
    "fii_pct_change_qoq", "promoter_pct_change_qoq",
}

REBALANCE_VALUES = {"daily", "weekly", "monthly"}

RANKING_FIELDS = {
    # Phase 1 — backed by stock_features_daily columns
    "composite_score", "score", "rsi14", "vol_z20",
    "return_20d_pct", "accumulation_score", "atr_pct",
    # Fundamentals/technical rank fields (columns on stock_features_daily)
    "momentum_score", "roe_pct", "roce_pct", "return_252d_pct",
    "market_cap_cr", "eps_growth_3y_cagr_pct", "revenue_growth_3y_cagr_pct",
}


# ── Error type ──────────────────────────────────────────────────────
@dataclass
class DSLError:
    path: str          # JSON-pointer-ish path to the offending node
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


# ── Validation entry point ──────────────────────────────────────────
def validate_strategy(spec: Any) -> List[DSLError]:
    """Validate a strategy DSL document. Returns list of errors (empty = valid).

    Pure function — no I/O. Caller decides whether to raise or render.
    """
    errs: List[DSLError] = []

    if not isinstance(spec, dict):
        return [DSLError("$", "strategy must be a JSON object")]

    # version
    v = spec.get("version")
    if v != DSL_VERSION:
        errs.append(DSLError("$.version",
                             f"unsupported DSL version {v!r} (expected {DSL_VERSION!r})"))

    # asset_class
    asset = spec.get("asset_class")
    if asset not in ASSET_CLASSES:
        errs.append(DSLError("$.asset_class",
                             f"must be one of {sorted(ASSET_CLASSES)}"))

    # name
    name = spec.get("name")
    if not isinstance(name, str) or not name.strip():
        errs.append(DSLError("$.name", "must be a non-empty string"))
    elif len(name) > 100:
        errs.append(DSLError("$.name", "must be ≤ 100 chars"))

    # universe
    uni = spec.get("universe")
    errs.extend(_validate_universe(uni, asset))

    # entry
    entry = spec.get("entry")
    errs.extend(_validate_entry(entry, asset))

    # exit (optional for MF rebalance strategies, required for STOCK)
    exit_ = spec.get("exit")
    if asset == "STOCK":
        errs.extend(_validate_exit(exit_, required=True))
    elif exit_ is not None:
        errs.extend(_validate_exit(exit_, required=False))

    # ranking
    ranking = spec.get("ranking")
    errs.extend(_validate_ranking(ranking))

    # rebalance
    reb = spec.get("rebalance")
    if reb not in REBALANCE_VALUES:
        errs.append(DSLError("$.rebalance",
                             f"must be one of {sorted(REBALANCE_VALUES)}"))

    return errs


# ── Sub-validators ──────────────────────────────────────────────────
def _validate_universe(uni: Any, asset_class: Optional[str]) -> List[DSLError]:
    errs: List[DSLError] = []
    if not isinstance(uni, dict):
        return [DSLError("$.universe", "must be an object {type, ref}")]
    t = uni.get("type")
    if t not in UNIVERSE_TYPES:
        errs.append(DSLError("$.universe.type",
                             f"must be one of {sorted(UNIVERSE_TYPES)}"))
    ref = uni.get("ref")
    if not isinstance(ref, str) or not ref.strip():
        errs.append(DSLError("$.universe.ref", "must be a non-empty string"))
    # Cross-checks: MF must use 'category' or 'custom'; STOCK uses 'index' or 'custom'
    if asset_class == "MF" and t == "index":
        errs.append(DSLError("$.universe.type",
                             "MF strategies cannot use index universes (use 'category' or 'custom')"))
    if asset_class == "STOCK" and t == "category":
        errs.append(DSLError("$.universe.type",
                             "STOCK strategies cannot use category universes (use 'index' or 'custom')"))
    return errs


def _validate_entry(entry: Any, asset_class: Optional[str]) -> List[DSLError]:
    errs: List[DSLError] = []
    if not isinstance(entry, dict):
        return [DSLError("$.entry", "must be an object with all_of / any_of")]

    has_all = "all_of" in entry
    has_any = "any_of" in entry
    if not (has_all or has_any):
        errs.append(DSLError("$.entry",
                             "must contain at least one of all_of, any_of"))
        return errs

    for key in ("all_of", "any_of"):
        if key not in entry:
            continue
        preds = entry[key]
        if not isinstance(preds, list):
            errs.append(DSLError(f"$.entry.{key}", "must be an array of predicates"))
            continue
        if len(preds) == 0:
            errs.append(DSLError(f"$.entry.{key}", "must be non-empty"))
            continue
        for i, p in enumerate(preds):
            errs.extend(_validate_predicate(p, asset_class, f"$.entry.{key}[{i}]"))
    return errs


def _validate_predicate(p: Any, asset_class: Optional[str], path: str) -> List[DSLError]:
    errs: List[DSLError] = []
    if not isinstance(p, dict):
        return [DSLError(path, "predicate must be an object")]

    # Detect namespace — exactly one of NAMESPACES must be present as a key
    ns_keys = [k for k in NAMESPACES if k in p]
    if len(ns_keys) == 0:
        return [DSLError(path,
                         f"predicate must have one of {sorted(NAMESPACES)} as key")]
    if len(ns_keys) > 1:
        return [DSLError(path,
                         f"predicate must have exactly one namespace key (got {ns_keys})")]
    ns = ns_keys[0]
    field_name = p[ns]

    # Field-name shape
    if not isinstance(field_name, str) or not field_name.strip():
        errs.append(DSLError(f"{path}.{ns}", "must be a non-empty string"))
        return errs

    # `op` is required for everything except sector set ops
    op = p.get("op")
    if ns == "sector":
        if op not in OPS_SET:
            errs.append(DSLError(f"{path}.op",
                                 f"sector predicate op must be one of {sorted(OPS_SET)}"))
        val = p.get("value")
        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
            errs.append(DSLError(f"{path}.value", "sector value must be array of strings"))
    else:
        if op not in OPS_NUMERIC:
            errs.append(DSLError(f"{path}.op",
                                 f"op must be one of {sorted(OPS_NUMERIC)}"))
        # exactly one of value / compare_to
        has_v = "value" in p
        has_cmp = "compare_to" in p
        if has_v == has_cmp:
            errs.append(DSLError(path, "predicate must have exactly one of `value` or `compare_to`"))
        if has_v and not isinstance(p["value"], (int, float)):
            errs.append(DSLError(f"{path}.value", "value must be numeric"))
        if has_cmp and not isinstance(p["compare_to"], str):
            errs.append(DSLError(f"{path}.compare_to", "compare_to must be a string field name"))

    # Phase-1 strict resolution: feature.* must be a known column.
    # Other namespaces validated leniently (Phase-2 will tighten).
    if ns == "feature" and field_name not in STOCK_FEATURE_COLS:
        errs.append(DSLError(f"{path}.feature",
                             f"unknown feature {field_name!r}; known: {sorted(STOCK_FEATURE_COLS)}"))

    # MF strategies cannot reference stock-only namespaces in Phase 1
    if asset_class == "MF" and ns in {"feature", "fundamental", "shareholding", "institutional", "sector"}:
        errs.append(DSLError(path,
                             f"namespace {ns!r} not available for MF strategies; use 'mf'"))
    if asset_class == "STOCK" and ns == "mf":
        errs.append(DSLError(path,
                             "namespace 'mf' only available for MF strategies"))

    return errs


def _validate_exit(exit_: Any, required: bool) -> List[DSLError]:
    errs: List[DSLError] = []
    if exit_ is None:
        if required:
            errs.append(DSLError("$.exit", "required for STOCK strategies"))
        return errs
    if not isinstance(exit_, dict):
        return [DSLError("$.exit", "must be an object")]

    sl = exit_.get("stoploss_pct")
    if sl is not None and not (isinstance(sl, (int, float)) and 0 < sl < 100):
        errs.append(DSLError("$.exit.stoploss_pct", "must be in (0, 100)"))

    rr = exit_.get("target_rr")
    if rr is not None and not (isinstance(rr, (int, float)) and rr > 0):
        errs.append(DSLError("$.exit.target_rr", "must be > 0"))

    mhd = exit_.get("max_hold_days")
    if mhd is not None and not (isinstance(mhd, int) and mhd > 0):
        errs.append(DSLError("$.exit.max_hold_days", "must be a positive int"))

    tatr = exit_.get("trailing_atr_mult")
    if tatr is not None and not (isinstance(tatr, (int, float)) and tatr > 0):
        errs.append(DSLError("$.exit.trailing_atr_mult", "must be > 0"))

    if sl is None and rr is None and mhd is None:
        errs.append(DSLError("$.exit",
                             "at least one of stoploss_pct / target_rr / max_hold_days required"))
    return errs


def _validate_ranking(ranking: Any) -> List[DSLError]:
    errs: List[DSLError] = []
    if ranking is None:
        return [DSLError("$.ranking", "required (object with `by` and `limit`)")]
    if not isinstance(ranking, dict):
        return [DSLError("$.ranking", "must be an object")]
    by = ranking.get("by")
    if by not in RANKING_FIELDS:
        errs.append(DSLError("$.ranking.by", f"must be one of {sorted(RANKING_FIELDS)}"))
    limit = ranking.get("limit")
    if not isinstance(limit, int) or not (1 <= limit <= 100):
        errs.append(DSLError("$.ranking.limit", "must be an int in [1, 100]"))
    order = ranking.get("order", "desc")
    if order not in {"asc", "desc"}:
        errs.append(DSLError("$.ranking.order", "must be 'asc' or 'desc'"))
    return errs


# ── Convenience helpers ─────────────────────────────────────────────
def is_valid(spec: Any) -> bool:
    """Boolean shortcut for callers that just want a yes/no."""
    return len(validate_strategy(spec)) == 0


def errors_as_strings(errs: Sequence[DSLError]) -> List[str]:
    return [str(e) for e in errs]
