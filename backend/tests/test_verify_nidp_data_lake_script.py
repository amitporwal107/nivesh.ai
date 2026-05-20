"""Smoke test for scripts/verify_nidp_data_lake.py.

We can't run the script end-to-end without a NIDP Postgres, but we *can*
assert that the module imports cleanly, exposes the expected entrypoint,
and that the SQL strings inside it reference the right tables/columns.
If anyone refactors the underlying schema, these assertions catch a stale
verification script before it ships.
"""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts" / "verify_nidp_data_lake.py"
)


@pytest.fixture(scope="module")
def module():
    assert SCRIPT_PATH.is_file(), f"script missing at {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("verify_script", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def script_source() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_main_is_async(module):
    """Entry-point must be async — wrapped by asyncio.run() in __main__."""
    assert inspect.iscoroutinefunction(module.main)


def test_thresholds_present(module):
    """Operators may tighten thresholds over time — ensure the dict exists
    with the documented keys so a typo in a key name doesn't silently
    skip a check."""
    expected_keys = {
        "mf_analytics_rows",
        "mf_analytics_ret1y_ratio",
        "stock_features_piotroski",
        "stock_features_vol1y",
        "lookthrough_schemes",
        "lookthrough_avg_coverage",
    }
    assert set(module.CRITICAL_THRESHOLDS.keys()) == expected_keys


def test_checks_reference_required_tables(script_source):
    """If anyone renames these tables, the verification script will
    silently pass while the engines remain broken. Fail loud."""
    required = [
        "nidp.schema_migrations",
        "nidp.v_mf_lookthrough_quality",
        "analytics.fund_category_rank",
        "nidp.stock_features_daily",
        "nidp.job_log",
    ]
    for table in required:
        assert table in script_source, f"verification script missing reference to {table}"


def test_checks_reference_required_columns(script_source):
    """The whole point of the verification is that these columns become
    non-NULL. If any column name drifts, the check still passes (NULL
    counted as 'has column = 0') without surfacing the drift."""
    required = [
        "piotroski_score",
        "volatility_1y_pct",
        "return_1y",
        "coverage_pct",
    ]
    for col in required:
        assert col in script_source, f"missing column reference: {col}"


def test_checks_engine_names_match_cron(script_source):
    """Engine names in checks must match the names used in nidp.cron
    (which is what job_log.ingester records)."""
    for engine in (
        "mf_analytics_engine",
        "technical_indicator_engine",
        "fundamental_engine",
    ):
        assert engine in script_source, f"missing engine reference: {engine}"


def test_fund_category_rank_uses_rank_date_not_as_of_date(script_source):
    """Regression guard for a real bug — analytics.fund_category_rank uses
    `rank_date` (per migration 047 / mf_analytics_engine UPSERT_SQL), not
    `as_of_date`. The earlier verify-script revision queried with the
    wrong column name, which made section 3 silently report 'query failed'
    even when the data was fine.

    Strategy: strip comments first (so the schema-note comment doesn't
    trigger a false positive), then concatenate adjacent string literals
    into single SQL statements, then verify every statement that mentions
    analytics.fund_category_rank pairs it with rank_date and never with
    as_of_date."""
    import re
    import tokenize
    import io

    # Walk the token stream to find runs of adjacent string literals
    # (Python's implicit string concatenation). Each run = one SQL
    # statement as seen at runtime. Comments are tokens too but we
    # ignore them — they never make it into runtime SQL.
    sql_statements: list[str] = []
    current_run: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(script_source).readline):
        if tok.type == tokenize.STRING:
            # Reject docstrings (triple-quoted) — only single-line "..."
            # forms participate in our SQL concatenation pattern.
            raw = tok.string
            if raw.startswith(('"""', "'''")):
                if current_run:
                    sql_statements.append("".join(current_run))
                    current_run = []
                continue
            # Strip the surrounding quote chars
            unquoted = raw[1:-1] if len(raw) >= 2 else raw
            current_run.append(unquoted)
        elif tok.type in (tokenize.NEWLINE, tokenize.NL, tokenize.COMMENT):
            # whitespace / comments don't break adjacency in source —
            # the Python tokenizer treats them as no-ops between strings.
            continue
        else:
            if current_run:
                sql_statements.append("".join(current_run))
                current_run = []
    if current_run:
        sql_statements.append("".join(current_run))

    fcr_statements = [s for s in sql_statements if "analytics.fund_category_rank" in s]
    assert fcr_statements, "no SQL statement references analytics.fund_category_rank"
    for stmt in fcr_statements:
        assert "rank_date" in stmt, (
            f"SQL referencing analytics.fund_category_rank must use "
            f"`rank_date` (the actual date column). Statement: {stmt!r}"
        )
        assert "as_of_date" not in stmt, (
            f"SQL referencing analytics.fund_category_rank must NOT use "
            f"`as_of_date` — that's a stock_features_daily column. "
            f"Use `rank_date` instead. Statement: {stmt!r}"
        )


def test_no_writes_in_sql(script_source):
    """The script must remain read-only. No INSERT/UPDATE/DELETE/CREATE/
    DROP/ALTER/TRUNCATE allowed."""
    forbidden = ("INSERT INTO", "UPDATE ", "DELETE ", "DROP ", "TRUNCATE ",
                 "CREATE TABLE", "CREATE VIEW", "ALTER TABLE", "ALTER VIEW")
    for verb in forbidden:
        # Allow `CREATE OR REPLACE` references in comments/docstrings but
        # not actual statements. Restrict to uppercase form — SQL strings
        # in the file are written uppercase.
        assert verb not in script_source, (
            f"verify_nidp_data_lake.py must remain read-only — found {verb!r}"
        )
