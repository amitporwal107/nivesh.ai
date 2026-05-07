"""Unit tests for the Strategy Builder engine.

Pure-Python; no DB. Covers:
  • DSL validator: accepts the 5 builtin templates, rejects malformed specs
  • Compiler: emits parameterised SQL, never interpolates user values
  • Compiler: rejects Phase-2 namespaces with a clear error
  • to_asyncpg: numbered-placeholder translation is stable
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from services.strategy_engine import dsl
from services.strategy_engine.compiler_stock import (
    CompileError, compile_stock_query, to_asyncpg,
)


TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "services" / "strategy_engine" / "templates"


# ── DSL validator ───────────────────────────────────────────────────
def _load_template(name: str) -> dict:
    with (TEMPLATES_DIR / name).open() as f:
        return json.load(f)


def test_all_builtin_templates_validate_clean():
    """Every shipped template must round-trip the validator with zero errors."""
    files = list(TEMPLATES_DIR.glob("*.json"))
    assert files, "no templates found — directory layout regressed"
    for p in files:
        spec = json.loads(p.read_text())
        errs = dsl.validate_strategy(spec)
        assert errs == [], f"{p.name} failed validation: {[str(e) for e in errs]}"


def test_validator_rejects_non_object():
    assert dsl.validate_strategy([]) != []
    assert dsl.validate_strategy("not an object") != []
    assert dsl.validate_strategy(None) != []


def test_validator_rejects_unknown_dsl_version():
    spec = _load_template("momentum_breakout.json")
    spec["version"] = "99"
    errs = dsl.validate_strategy(spec)
    assert any("version" in str(e) for e in errs)


def test_validator_rejects_bad_asset_class():
    spec = _load_template("momentum_breakout.json")
    spec["asset_class"] = "OPTIONS"
    errs = dsl.validate_strategy(spec)
    assert any("asset_class" in str(e) for e in errs)


def test_validator_rejects_unknown_feature():
    spec = _load_template("momentum_breakout.json")
    spec["entry"]["all_of"][0] = {"feature": "made_up_metric", "op": ">", "value": 0.5}
    errs = dsl.validate_strategy(spec)
    assert any("made_up_metric" in str(e) for e in errs)


def test_validator_rejects_predicate_with_both_value_and_compare_to():
    spec = _load_template("momentum_breakout.json")
    spec["entry"]["all_of"] = [
        {"feature": "rsi14", "op": ">", "value": 50, "compare_to": "sma50"}
    ]
    errs = dsl.validate_strategy(spec)
    assert any("value" in str(e) or "compare_to" in str(e) for e in errs)


def test_validator_rejects_empty_entry_block():
    spec = _load_template("momentum_breakout.json")
    spec["entry"] = {}
    errs = dsl.validate_strategy(spec)
    assert errs


def test_validator_rejects_stoploss_out_of_range():
    spec = _load_template("momentum_breakout.json")
    spec["exit"]["stoploss_pct"] = 200
    errs = dsl.validate_strategy(spec)
    assert any("stoploss" in str(e) for e in errs)


def test_validator_requires_ranking():
    spec = _load_template("momentum_breakout.json")
    del spec["ranking"]
    errs = dsl.validate_strategy(spec)
    assert any("ranking" in str(e) for e in errs)


def test_mf_strategy_cannot_use_feature_namespace():
    """MF strategies must use the `mf` namespace, not stock features."""
    spec = {
        "version": "1",
        "asset_class": "MF",
        "name": "Bad MF strategy",
        "universe": {"type": "category", "ref": "EQUITY_LARGECAP"},
        "entry": {"all_of": [{"feature": "rsi14", "op": ">", "value": 50}]},
        "ranking": {"by": "score", "limit": 10},
        "rebalance": "monthly",
    }
    errs = dsl.validate_strategy(spec)
    assert any("namespace" in str(e) or "mf" in str(e).lower() for e in errs)


def test_stock_strategy_requires_exit_block():
    """Stock strategies must define exit rules; MF can omit them."""
    spec = _load_template("momentum_breakout.json")
    del spec["exit"]
    errs = dsl.validate_strategy(spec)
    assert any("exit" in str(e) for e in errs)


# ── Compiler ────────────────────────────────────────────────────────
def test_compile_emits_parameterised_sql():
    spec = _load_template("momentum_breakout.json")
    sql, params = compile_stock_query(spec)
    # No raw user-supplied numerics should appear as literals — every
    # numeric value goes through the params dict.
    assert "WHERE" in sql
    assert ":p0" in sql or "$" in sql   # named or positional placeholders
    assert isinstance(params, dict)
    assert all(isinstance(v, (int, float, str, bool)) for v in params.values())
    # Reasonable arity — momentum_breakout has 6 entry predicates:
    # pivot_breakout_flag → IS TRUE (no param), 2× compare_to (no params),
    # 3× numeric. Expect ≥ 3 numeric params.
    numeric_param_count = sum(1 for v in params.values() if isinstance(v, (int, float, bool)))
    assert numeric_param_count >= 3, f"got {numeric_param_count} params: {params}"


def test_compile_universe_index_resolves():
    """The universe predicate must reference a real index/membership flag.

    Phase-1 environment uses stock_master.is_nifty_100 as the proxy
    universe — when full NIDP `index_constituents` lands we'll
    re-target. Either form is acceptable here.
    """
    spec = _load_template("momentum_breakout.json")
    sql, _ = compile_stock_query(spec)
    sql_lc = sql.lower()
    assert any(s in sql_lc for s in ("in_nifty100", "in_nifty500",
                                      "is_nifty_100", "nifty 500"))


def test_compile_ranking_limit_baked_in():
    spec = _load_template("momentum_breakout.json")
    sql, _ = compile_stock_query(spec)
    assert "LIMIT 10" in sql
    assert "ORDER BY" in sql


def test_compile_rejects_phase2_namespace():
    """Phase-2 namespaces (fundamental.*) parse cleanly but must not compile."""
    spec = _load_template("momentum_breakout.json")
    # Make it pass DSL validation: fundamental ns is allowed, only the
    # compiler rejects in Phase 1.
    spec["entry"]["all_of"].append({
        "fundamental": "pe_ttm", "op": "<", "value": 25,
    })
    with pytest.raises(CompileError, match="namespace 'fundamental'"):
        compile_stock_query(spec)


def test_compile_rejects_bad_compare_to():
    spec = _load_template("momentum_breakout.json")
    spec["entry"]["all_of"][0] = {
        "feature": "rsi14", "op": ">", "compare_to": "made_up_metric",
    }
    # validate_strategy lets this through (compare_to validated at compile)
    with pytest.raises(CompileError):
        compile_stock_query(spec)


def test_pivot_breakout_flag_translates_to_boolean_predicate():
    spec = _load_template("momentum_breakout.json")
    sql, _ = compile_stock_query(spec)
    # We use IS TRUE / IS FALSE for boolean flags — verify the translation
    # produced an "IS TRUE" rather than `= 1`
    assert "IS TRUE" in sql or "IS FALSE" in sql


# ── to_asyncpg translator ───────────────────────────────────────────
def test_to_asyncpg_replaces_named_placeholders_with_positional():
    spec = _load_template("momentum_breakout.json")
    sql, params = compile_stock_query(spec)
    pg_sql, args = to_asyncpg(sql, params)
    # No :name left from the param dict
    for k in params:
        assert f":{k}" not in pg_sql, f"{k} not translated"
    # $N count matches arg count
    pg_placeholders = sorted(set(re.findall(r"\$(\d+)", pg_sql)), key=int)
    assert len(pg_placeholders) == len(args)


def test_to_asyncpg_is_deterministic():
    """Same spec produces byte-identical SQL across runs (compiler is pure)."""
    spec = _load_template("accumulation.json")
    a_sql, a_params = compile_stock_query(spec)
    b_sql, b_params = compile_stock_query(spec)
    assert a_sql == b_sql
    assert a_params == b_params


# ── Custom universe path ────────────────────────────────────────────
def test_compile_custom_universe_uses_user_universes_table():
    spec = _load_template("momentum_breakout.json")
    spec["universe"] = {"type": "custom", "ref": "00000000-0000-0000-0000-000000000001"}
    sql, params = compile_stock_query(spec)
    assert "user_universes" in sql.lower()
    # The UUID becomes a parameter, not a literal
    assert "00000000-0000-0000-0000-000000000001" not in sql
    assert "00000000-0000-0000-0000-000000000001" in params.values()
