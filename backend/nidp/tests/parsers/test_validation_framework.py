"""Unit tests for the validation framework.

These exercise the framework in isolation — Rule construction, classification,
registry behaviour. Rules that need a live DB are integration-tested
elsewhere.
"""
from __future__ import annotations

import pytest

from nidp.shared.validation import register, get_rules
from nidp.shared.validation.registry import reset
from nidp.shared.validation.rules import (
    CountAtLeastRule, CustomSQLRule, FailureClass, NoNullsRule, RangeRule,
    Severity,
)
from nidp.shared.validation.runner import _classify_status, _json_dumps
from nidp.shared.validation.rules import Finding


def setup_function():
    reset()


def test_register_appends_to_registry():
    register("test_ingester", [
        CountAtLeastRule(name="t.row_min", sql="SELECT 1", min_count=1),
    ])
    register("test_ingester", [
        RangeRule(name="t.range", table="x", column="y", lo=0, hi=1),
    ])
    rules = get_rules("test_ingester")
    assert len(rules) == 2
    assert rules[0].name == "t.row_min"
    assert rules[1].name == "t.range"


def test_get_rules_unknown_ingester_returns_empty():
    assert get_rules("does_not_exist") == []


def test_classify_status_passed():
    assert _classify_status([]) == "PASSED"


def test_classify_status_failed_when_block():
    f = Finding(
        rule_name="x", severity=Severity.CRITICAL,
        failure_class=FailureClass.BLOCK, message="bad",
    )
    assert _classify_status([f]) == "FAILED"


def test_classify_status_partial_when_error_no_block():
    f = Finding(
        rule_name="x", severity=Severity.ERROR,
        failure_class=FailureClass.FIX, message="meh",
    )
    assert _classify_status([f]) == "PARTIAL"


def test_classify_status_passed_when_only_info_warn():
    f = Finding(
        rule_name="x", severity=Severity.WARN,
        failure_class=FailureClass.INFO, message="fyi",
    )
    assert _classify_status([f]) == "PASSED"


def test_json_dumps_handles_dates():
    from datetime import date as _d
    s = _json_dumps([{"as_of_date": _d(2026, 5, 4)}])
    assert "2026-05-04" in s


def test_per_service_validators_are_registered():
    """Each service's import-side-effect should register at least one
    rule. This guards against forgetting `from . import validators`
    in a new service's __init__.py."""
    # `setup_function` clears the registry; force-reload each
    # validators module so its `register(...)` side-effect re-fires.
    import importlib
    import sys
    for svc in (
        "bhavcopy", "delivery", "fii_dii", "corporate_actions",
        "bulk_deals", "block_deals", "rbi_yields", "index_close",
    ):
        modname = f"nidp.services.{svc}.validators"
        mod = sys.modules.get(modname) or importlib.import_module(modname)
        importlib.reload(mod)
        rules = get_rules(svc)
        assert len(rules) > 0, f"no validators registered for {svc!r}"


def test_block_finding_marks_summary_has_block():
    """Smoke test the dataclass invariants the runner relies on."""
    from nidp.shared.validation.runner import ValidationSummary
    import uuid as _u
    findings = [Finding(
        rule_name="x", severity=Severity.CRITICAL,
        failure_class=FailureClass.BLOCK, message="bad",
    )]
    summary = ValidationSummary(
        validation_id=_u.uuid4(),
        status="FAILED",
        rules_run=3,
        rules_failed=1,
        findings_count=1,
        has_block=True,
        findings=findings,
    )
    assert summary.has_block is True
    assert summary.status == "FAILED"
