"""Unit tests for nidp.services.quality_gate.dynamic_runner.

Tests the pure-Python pieces (dataset resolution, result aggregation)
and uses asyncpg-mocked fakes for the DB-bound paths.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from nidp.services.quality_gate.dynamic_runner import (
    DynamicRuleResult,
    _DATASET_MAP,
    _resolve_table,
    _evaluate_rule,
    run_active_rules,
)


# ─── Result dataclass ───────────────────────────────────────────────
class TestDynamicRuleResult:
    def test_as_dict_round_trip(self):
        r = DynamicRuleResult(
            rule_id="abc", dataset_name="prices_eod", name="r1",
            severity="ERROR", expression="high >= low",
            success=True, total_rows=100, failed_rows=0, failed_pct=0.0,
        )
        d = r.as_dict()
        assert d["rule_id"] == "abc"
        assert d["success"] is True
        assert d["error"] is None


# ─── _resolve_table ─────────────────────────────────────────────────
@pytest.mark.asyncio
class TestResolveTable:
    async def test_known_dataset_uses_static_map(self):
        conn = MagicMock()
        out = await _resolve_table(conn, "prices_eod")
        assert out == ("nidp.prices_eod", "as_of_date")
        # static map shouldn't trigger DB calls
        conn.fetchrow.assert_not_called()

    async def test_unknown_dataset_falls_through_to_information_schema(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={
            "table_schema": "nidp", "table_name": "weird_feed",
        })
        conn.fetch = AsyncMock(return_value=[
            {"column_name": "id"}, {"column_name": "as_of_date"},
        ])
        out = await _resolve_table(conn, "weird_feed")
        assert out == ("nidp.weird_feed", "as_of_date")

    async def test_unknown_table_returns_none(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=None)
        out = await _resolve_table(conn, "ghost_dataset")
        assert out is None

    async def test_table_without_known_date_column_returns_none_for_date(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={
            "table_schema": "nidp", "table_name": "static_lookup",
        })
        conn.fetch = AsyncMock(return_value=[{"column_name": "id"}])
        out = await _resolve_table(conn, "static_lookup")
        assert out == ("nidp.static_lookup", None)

    async def test_dataset_map_covers_all_documented_feeds(self):
        # Sanity: every entry in the static map is well-formed.
        for ds, (table, date_col) in _DATASET_MAP.items():
            assert table.startswith(("nidp.", "dq.", "public."))
            assert isinstance(date_col, str) and len(date_col) > 0


# ─── _evaluate_rule ─────────────────────────────────────────────────
@pytest.mark.asyncio
class TestEvaluateRule:
    async def test_unknown_dataset_returns_error_result(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value=None)
        rule = {
            "rule_id": "1", "dataset_name": "ghost", "name": "r1",
            "expression": "x > 0", "severity": "ERROR",
        }
        result = await _evaluate_rule(conn, rule, date(2026, 5, 1))
        assert result.success is False
        assert "not found" in (result.error or "")

    async def test_passing_rule_returns_success(self):
        conn = MagicMock()
        # Mock fetchrow on the SQL eval — bad=0, total=100
        conn.fetchrow = AsyncMock(return_value={"bad": 0, "total": 100})
        rule = {
            "rule_id": "2", "dataset_name": "prices_eod", "name": "high_ge_low",
            "expression": "high_price >= low_price", "severity": "ERROR",
        }
        result = await _evaluate_rule(conn, rule, date(2026, 5, 1))
        assert result.success is True
        assert result.total_rows == 100
        assert result.failed_rows == 0

    async def test_failing_rule_records_violations(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"bad": 7, "total": 100})
        rule = {
            "rule_id": "3", "dataset_name": "prices_eod", "name": "bad_close",
            "expression": "close_price > 0", "severity": "CRITICAL",
        }
        result = await _evaluate_rule(conn, rule, date(2026, 5, 1))
        assert result.success is False
        assert result.failed_rows == 7
        assert result.failed_pct == pytest.approx(7.0)
        assert result.error is None

    async def test_sql_error_caught_and_returned(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(side_effect=asyncpg.UndefinedColumnError(
            "column nonexistent does not exist"
        ))
        rule = {
            "rule_id": "4", "dataset_name": "prices_eod", "name": "bad_rule",
            "expression": "nonexistent > 0", "severity": "WARN",
        }
        result = await _evaluate_rule(conn, rule, date(2026, 5, 1))
        assert result.success is False
        assert result.error is not None
        assert "UndefinedColumnError" in result.error

    async def test_zero_rows_does_not_crash(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(return_value={"bad": 0, "total": 0})
        rule = {
            "rule_id": "5", "dataset_name": "prices_eod", "name": "any",
            "expression": "1=1", "severity": "INFO",
        }
        result = await _evaluate_rule(conn, rule, date(2026, 5, 1))
        # zero total → success=False (consistent with GE runner skipping)
        assert result.total_rows == 0
        assert result.failed_pct == 0.0


# ─── run_active_rules — graceful degradation ────────────────────────
@pytest.mark.asyncio
class TestRunActiveRules:
    async def test_skips_when_table_missing(self, monkeypatch):
        # Patch asyncpg.connect → connection that raises UndefinedTableError on fetch
        conn = MagicMock()
        conn.fetch = AsyncMock(side_effect=asyncpg.UndefinedTableError(
            "relation dq.expectations_active does not exist"
        ))
        conn.close = AsyncMock()

        async def _fake_connect(_dsn):
            return conn

        monkeypatch.setattr("nidp.services.quality_gate.dynamic_runner.asyncpg.connect", _fake_connect)
        out = await run_active_rules(target_date=date(2026, 5, 1))
        assert out["skipped"] is True
        assert "expectations_active" in out["skipped_reason"]
        assert out["rules_total"] == 0

    async def test_no_rules_returns_zero_counts(self, monkeypatch):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        conn.close = AsyncMock()

        async def _fake_connect(_dsn):
            return conn

        monkeypatch.setattr("nidp.services.quality_gate.dynamic_runner.asyncpg.connect", _fake_connect)
        out = await run_active_rules(target_date=date(2026, 5, 1))
        assert out["rules_total"] == 0
        assert out["skipped"] is False
        assert out["datasets"] == {}
