"""Unit tests for Rules Config + Prompts Manager + safe DSL evaluator."""
import asyncio
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.rules_dsl import safe_eval, validate_expression, SafeEvalError  # noqa: E402
from services import rules_config  # noqa: E402


# ── Safe DSL ─────────────────────────────────────────────────────────────

def test_dsl_basic_comparison():
    assert safe_eval("a > 5", {"a": 10}) is True
    assert safe_eval("a > 5", {"a": 1}) is False


def test_dsl_boolean_combinations():
    ctx = {"a": 10, "b": 2}
    assert safe_eval("a > 5 and b < 3", ctx) is True
    assert safe_eval("a < 5 or b < 3", ctx) is True
    assert safe_eval("not (a < 5)", ctx) is True


def test_dsl_arithmetic():
    assert safe_eval("a + b * 2", {"a": 1, "b": 3}) == 7
    assert safe_eval("(a + b) / 2", {"a": 3, "b": 5}) == 4.0


def test_dsl_safe_builtins():
    ctx = {"x": 10, "y": 20}
    assert safe_eval("max(x, y) > 15", ctx) is True
    assert safe_eval("abs(-5) == 5", {}) is True


def test_dsl_rejects_undefined_name():
    with pytest.raises(SafeEvalError):
        safe_eval("undefined_var > 0", {})


def test_dsl_rejects_eval_injection():
    # Cannot call arbitrary functions
    with pytest.raises(SafeEvalError):
        safe_eval("__import__('os').system('ls')", {})
    with pytest.raises(SafeEvalError):
        safe_eval("open('/etc/passwd').read()", {})


def test_dsl_rejects_attribute_on_non_dict():
    class Foo:
        bar = 1
    with pytest.raises(SafeEvalError):
        safe_eval("foo.bar", {"foo": Foo()})


def test_dsl_rejects_lambdas_and_defs():
    with pytest.raises(SafeEvalError):
        safe_eval("(lambda x: x)(5)", {})


def test_dsl_chained_comparisons():
    assert safe_eval("0 < a < 10", {"a": 5}) is True
    assert safe_eval("0 < a < 10", {"a": 15}) is False


def test_dsl_validate_returns_names_used():
    v = validate_expression("portfolio_score < 60 and max_amc_pct > 20")
    assert v["ok"] is True
    assert set(v["names_used"]) == {"portfolio_score", "max_amc_pct"}


def test_dsl_validate_rejects_syntax_error():
    v = validate_expression("portfolio_score <<< 60")
    assert v["ok"] is False
    assert "Syntax" in v["error"]


def test_dsl_expression_size_limit():
    with pytest.raises(SafeEvalError):
        safe_eval("a" * 501 + " > 0", {})


# ── Rules Config shape ───────────────────────────────────────────────────

def test_rules_config_defaults_all_rules_present():
    rules = rules_config.DEFAULTS["rules"]
    expected = {
        "rule_1_regular_to_direct", "rule_2_amc_concentration",
        "rule_2b_category_concentration", "rule_3_underperformer_replacement",
        "rule_4_different_fund_overlap", "rule_5_debt_allocation",
        "rule_6_cost_leak_switch", "rule_7_do_nothing",
    }
    assert set(rules.keys()) == expected
    for rid, cfg in rules.items():
        assert "enabled" in cfg
        assert "label" in cfg
        assert "description" in cfg
        assert "params" in cfg


def test_rules_config_default_threshold_values():
    r = rules_config.DEFAULTS["rules"]
    assert r["rule_2_amc_concentration"]["params"]["threshold_pct"] == 15.0
    assert r["rule_2b_category_concentration"]["params"]["threshold_pct"] == 35.0
    assert r["rule_4_different_fund_overlap"]["params"]["overlap_threshold_pct"] == 60.0
    assert r["rule_6_cost_leak_switch"]["params"]["total_leak_threshold_rs"] == 10000.0


def test_rules_config_merge_defaults_preserves_unknown_keys():
    merged = rules_config._merge_defaults({
        "rules": {
            "rule_2b_category_concentration": {"enabled": False, "params": {"threshold_pct": 25.0}},
            "unknown_rule": {"enabled": True},  # should be ignored
        },
        "custom_rules": [{"id": "r1", "name": "x"}],
    })
    assert merged["rules"]["rule_2b_category_concentration"]["enabled"] is False
    assert merged["rules"]["rule_2b_category_concentration"]["params"]["threshold_pct"] == 25.0
    assert "unknown_rule" not in merged["rules"]
    assert len(merged["custom_rules"]) == 1
    # Rule 2 defaults preserved
    assert merged["rules"]["rule_2_amc_concentration"]["params"]["threshold_pct"] == 15.0


# ── Prompts Manager registry ─────────────────────────────────────────────

def test_prompts_registry_has_all_expected_prompts():
    from services import prompts_manager
    prompts_manager._ensure_bootstrap()
    expected = {
        "financial_advisor_system", "insight_analysis_system", "cas_parser_system",
        "insights_system_prompt", "category_rating_system", "mf_rating_system",
        "allocation_analysis_system",
    }
    assert expected.issubset(set(prompts_manager._REGISTRY.keys()))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
