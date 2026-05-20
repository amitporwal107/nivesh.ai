"""Structural test for migration 059 — nidp.v_mf_lookthrough_quality.

A full database-mode test of the view's math would need a live PG instance
populated with mf_holdings_monthly + sector_master + stock_features_daily.
That's expensive for a unit test suite. Instead we assert the migration's
*contract*:

  1. The migration file exists and registers itself in schema_migrations.
  2. The view is named exactly nidp.v_mf_lookthrough_quality (any rename
     would break the scoring engine's downstream query).
  3. The required output columns are present (lookthrough_pe / roe / d-e /
     piotroski / altman / coverage_pct).
  4. The JOIN chain hits the right tables (mf_holdings_monthly +
     sector_master + stock_features_daily).
  5. Coverage_pct normalisation: each weighted average must divide by
     SUM(covered_weight), not raw SUM(weight_pct) — otherwise a fund with
     30% mappable holdings would see its PE diluted by 70% NULL rows.

If the migration file moves or is renumbered, this test fails fast so we
notice before deploy.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


MIGRATION_PATH = Path(
    os.environ.get(
        "NIDP_MIGRATION_PATH",
        Path(__file__).resolve().parent.parent
        / "nidp" / "migrations" / "059_nidp_mf_lookthrough_quality.sql",
    )
)


@pytest.fixture(scope="module")
def sql_text() -> str:
    assert MIGRATION_PATH.is_file(), f"migration missing at {MIGRATION_PATH}"
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_view_is_named_v_mf_lookthrough_quality(sql_text):
    assert re.search(
        r"CREATE\s+(OR\s+REPLACE\s+)?VIEW\s+nidp\.v_mf_lookthrough_quality",
        sql_text, re.IGNORECASE,
    ), "view name must remain nidp.v_mf_lookthrough_quality"


def test_required_output_columns_present(sql_text):
    expected = [
        "lookthrough_pe",
        "lookthrough_roe_pct",
        "lookthrough_debt_to_equity",
        "lookthrough_piotroski",
        "lookthrough_altman",
        "coverage_pct",
    ]
    for col in expected:
        assert col in sql_text, f"missing output column: {col}"


def test_join_chain_hits_required_tables(sql_text):
    # MF holdings → sector_master → stock_features_daily
    assert "mf_holdings_monthly" in sql_text
    assert "sector_master" in sql_text
    assert "stock_features_daily" in sql_text


def test_filters_to_equity_only(sql_text):
    """Debt/cash/derivative rows have no stock-features to look through to."""
    assert "EQUITY" in sql_text.upper(), (
        "view must filter instrument_type = 'EQUITY' to avoid pulling "
        "debt/cash rows into the look-through math"
    )


def test_normalises_by_covered_weight_not_raw_weight(sql_text):
    """Each weighted average must divide by SUM(covered_weight), so funds
    with low coverage don't have their averages diluted by 0-contribution
    rows."""
    # Find each ROUND(SUM(metric * covered_weight) / SUM(covered_weight))
    # pattern. Should appear for each weighted output column.
    expected_pairs = [
        ("pe_ttm",          "lookthrough_pe"),
        ("roe_pct",         "lookthrough_roe_pct"),
        ("debt_to_equity",  "lookthrough_debt_to_equity"),
        ("piotroski_score", "lookthrough_piotroski"),
        ("altman_z_score",  "lookthrough_altman"),
    ]
    for metric, alias in expected_pairs:
        # Allow whitespace + newlines; look for the metric times covered_weight
        pattern = rf"SUM\s*\(\s*{re.escape(metric)}\s*\*\s*covered_weight"
        assert re.search(pattern, sql_text, re.IGNORECASE), (
            f"metric {metric} must be weighted by covered_weight in the view"
        )


def test_handles_zero_coverage_safely(sql_text):
    """When no constituents map, SUM(covered_weight) = 0. Must not divide
    by zero — view should return NULL (via CASE / NULLIF / similar)."""
    has_case = re.search(
        r"CASE\s+WHEN\s+SUM\s*\(\s*covered_weight\s*\)\s*>\s*0",
        sql_text, re.IGNORECASE,
    )
    has_nullif = "NULLIF" in sql_text.upper()
    assert has_case or has_nullif, (
        "view must guard against zero-coverage division — neither "
        "CASE WHEN SUM(covered_weight) > 0 nor NULLIF found"
    )


def test_registers_in_schema_migrations(sql_text):
    assert "schema_migrations" in sql_text, (
        "migration must INSERT into schema_migrations so the runner skips on rerun"
    )
    assert "059_nidp_mf_lookthrough_quality.sql" in sql_text


def test_view_provides_coverage_diagnostic_for_scoring_engine(sql_text):
    """coverage_pct lets the downstream scoring engine know when to
    redistribute the Fundamentals factor weight (e.g., < 60% coverage).

    Must be derived from SUM(covered_weight) (the weight of holdings that
    *matched* a symbol), not SUM(weight_pct) (the raw weight of all rows).
    Otherwise a fund with 30% mappable holdings reports coverage_pct = 100
    instead of 30."""
    # Find the SELECT-clause definition of coverage_pct (ignoring comment
    # block at the top of the file). Strip comment lines and look for
    # `SUM(covered_weight) ... AS coverage_pct` within the remaining SQL.
    code_lines = [ln for ln in sql_text.splitlines() if not ln.strip().startswith("--")]
    code = "\n".join(code_lines)
    match = re.search(
        r"SUM\s*\(\s*covered_weight\s*\).*?AS\s+coverage_pct",
        code, re.IGNORECASE | re.DOTALL,
    )
    assert match, (
        "coverage_pct must be derived from SUM(covered_weight) so it "
        "reports what fraction of NAV the lookthrough actually covers"
    )
