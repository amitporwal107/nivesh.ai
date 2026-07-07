"""Unit tests for the screener → strategy bridge.

Pure-Python; no DB. Covers:
  • DSL now accepts fundamental columns under the `feature.*` namespace
  • Compiler parameterises fundamental predicates + the new `sector` predicate
  • `fundamental.*` namespace is STILL rejected (Phase-2 unchanged — backward compat)
  • screen_bridge.build_definition_from_screen maps widget filters → valid DSL
  • drift guard: every mapped column is in the DSL whitelist
"""
from __future__ import annotations

import pytest

from services.strategy_engine import dsl
from services.strategy_engine.compiler_stock import (
    CompileError, compile_stock_query,
)
from services.strategy_engine.screen_bridge import (
    SCREENER_KEY_TO_FEATURE, build_definition_from_screen, ScreenBridgeError,
)


def _base_stock_spec(entry_preds):
    return {
        "version": "1",
        "asset_class": "STOCK",
        "name": "test",
        "universe": {"type": "index", "ref": "NIFTY500"},
        "entry": {"all_of": entry_preds},
        "exit": {"stoploss_pct": 8, "target_rr": 2, "max_hold_days": 90},
        "ranking": {"by": "momentum_score", "limit": 20, "order": "desc"},
        "rebalance": "weekly",
    }


# ── TC-1: DSL accepts fundamental columns as feature.* ──────────────
def test_dsl_accepts_fundamental_feature_cols():
    spec = _base_stock_spec([
        {"feature": "pe_ttm", "op": "<", "value": 15},
        {"feature": "roe_pct", "op": ">", "value": 18},
        {"feature": "debt_to_equity", "op": "<", "value": 0.5},
        {"feature": "promoter_pledged_pct", "op": "<", "value": 1},
    ])
    assert dsl.validate_strategy(spec) == []


def test_dsl_ranking_accepts_new_fields():
    spec = _base_stock_spec([{"feature": "roe_pct", "op": ">", "value": 18}])
    spec["ranking"]["by"] = "roe_pct"
    assert dsl.validate_strategy(spec) == []


# ── TC-2: compiler parameterises a fundamental predicate ────────────
def test_compile_fundamental_feature_predicate_parameterised():
    spec = _base_stock_spec([{"feature": "pe_ttm", "op": "<=", "value": 15}])
    sql, params = compile_stock_query(spec)
    assert "f.pe_ttm <=" in sql
    # value goes through a param, never inlined as a literal
    assert "15" not in sql.replace("LIMIT 20", "")   # 15 must not appear as a literal
    assert 15.0 in params.values() or 15 in params.values()


# ── TC-3: fundamental.* namespace STILL rejected (backward compat) ──
def test_fundamental_namespace_still_rejected():
    spec = _base_stock_spec([{"fundamental": "pe_ttm", "op": "<", "value": 15}])
    with pytest.raises(CompileError, match="namespace 'fundamental'"):
        compile_stock_query(spec)


# ── TC-4: sector predicate compiles + parameterises ─────────────────
def test_sector_predicate_compiles():
    spec = _base_stock_spec([
        {"feature": "roe_pct", "op": ">", "value": 15},
        {"sector": "sector", "op": "in", "value": ["Banking", "IT"]},
    ])
    assert dsl.validate_strategy(spec) == []
    sql, params = compile_stock_query(spec)
    assert "f.sector IN (" in sql
    assert "Banking" not in sql and "Banking" in params.values()
    assert "IT" in params.values()


def test_sector_not_in_compiles_negated():
    spec = _base_stock_spec([
        {"feature": "roe_pct", "op": ">", "value": 15},
        {"sector": "sector", "op": "not_in", "value": ["Utilities"]},
    ])
    sql, _ = compile_stock_query(spec)
    assert "NOT f.sector IN (" in sql


# ── TC-5: build_definition_from_screen → valid DSL ──────────────────
def test_build_from_screen_produces_valid_dsl():
    definition, dropped = build_definition_from_screen(
        name="Quality compounders",
        filters={"pe_max": 15, "roe_min": 18, "de_max": 0.5},
        sector=["Banking"],
    )
    assert dropped == []
    assert dsl.validate_strategy(definition) == []
    preds = definition["entry"]["all_of"]
    # 3 feature predicates + 1 sector predicate
    feat = [p for p in preds if "feature" in p]
    sect = [p for p in preds if "sector" in p]
    assert len(feat) == 3 and len(sect) == 1
    # _min → >=, _max → <=
    by_col = {p["feature"]: p for p in feat}
    assert by_col["pe_ttm"]["op"] == "<=" and by_col["roe_pct"]["op"] == ">="
    # defaults attached
    assert definition["exit"]["stoploss_pct"] == 8.0
    assert definition["ranking"]["by"] == "momentum_score"
    assert definition["rebalance"] == "weekly"
    # and it compiles end-to-end
    sql, _ = compile_stock_query(definition)
    assert "f.pe_ttm <=" in sql and "f.sector IN (" in sql


# ── TC-6: edge — unknown keys dropped, empty raises ─────────────────
def test_build_from_screen_drops_unknown_keys():
    definition, dropped = build_definition_from_screen(
        name="mixed",
        filters={"roe_min": 18, "made_up_min": 5, "pe": 10, "de_max": "notnum"},
    )
    # made_up_min (unknown primitive), pe (no _min/_max suffix), de_max (non-numeric)
    assert set(dropped) == {"made_up_min", "pe", "de_max"}
    assert len(definition["entry"]["all_of"]) == 1


def test_build_from_screen_empty_raises():
    with pytest.raises(ScreenBridgeError):
        build_definition_from_screen(name="empty", filters={})
    with pytest.raises(ScreenBridgeError):
        build_definition_from_screen(name="all-dropped", filters={"nonsense_min": 1})


def test_build_from_screen_sector_only():
    definition, dropped = build_definition_from_screen(
        name="banks", filters={}, sector=["Banking"],
    )
    assert dropped == []
    assert dsl.validate_strategy(definition) == []
    assert any("sector" in p for p in definition["entry"]["all_of"])


# ── TC-7: drift guard — every mapped column is whitelisted ──────────
def test_screener_map_columns_all_whitelisted():
    missing = {k: c for k, c in SCREENER_KEY_TO_FEATURE.items()
               if c not in dsl.STOCK_FEATURE_COLS}
    assert not missing, f"mapped columns missing from STOCK_FEATURE_COLS: {missing}"
