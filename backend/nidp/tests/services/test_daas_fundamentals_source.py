"""The query API returns where ROE, ROCE, debt-to-equity, P/B and market cap came from, and
as of when (stock_features_daily.fundamentals_source / fundamentals_as_of, migration 162) —
and keeps answering while that migration has not been applied yet."""
import asyncio
from datetime import date

import pytest

from nidp.services.daas_api import metric_registry as reg
from nidp.services.daas_api.routers import _fundamentals_source, features, stock_scores, stock_screen

REAL = ("fundamentals_source", "fundamentals_as_of")
PLACEHOLDER = "NULL::text AS fundamentals_source, NULL::date AS fundamentals_as_of"


class _Conn:
    """Records every statement; answers the column check with `migrated`."""

    def __init__(self, migrated: bool):
        self.migrated, self.sql, self.checks = migrated, [], 0

    async def fetchval(self, sql, *args, **kw):
        if "information_schema.columns" in sql:
            self.checks += 1
            return self.migrated
        return date(2026, 10, 12)

    async def fetch(self, sql, *args, **kw):
        self.sql.append(sql)
        return []

    async def fetchrow(self, sql, *args, **kw):
        self.sql.append(sql)
        return {"symbol": "TCS", "fundamentals_source": "trendlyne_mcp", "fundamentals_as_of": date(2026, 10, 12)}

    def acquire(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def conn(monkeypatch, request):
    migrated = getattr(request, "param", True)
    c = _Conn(migrated)

    async def _pool():
        return c
    monkeypatch.setattr(_fundamentals_source, "_present", False)
    for module in (features, stock_scores):
        monkeypatch.setattr(module, "get_pool", _pool)
    return c


def _call_every_route():
    page = {"limit": 50, "offset": 0}
    asyncio.run(stock_scores.stock_screener(
        sector=None, market_cap=None, min_roe=None, max_de=None, min_eps_cagr_3y=None, min_rev_cagr_3y=None,
        max_rsi=None, min_rsi=None, max_pe_vs_sector=None, min_pat_growth_yoy=None, min_rev_growth_yoy=None,
        min_eps_growth_yoy=None, universe=None, sort_by="roe_pct", sort_desc=True, as_of_date=None, page=page))
    asyncio.run(stock_scores.top_stocks(metric="roe_pct", sector=None, market_cap=None, limit=10, as_of_date=None))
    asyncio.run(stock_scores.stock_primitives(symbol="TCS", as_of_date=None))
    asyncio.run(stock_scores.stock_v3_primitives_bulk(body={"symbols": ["TCS"]}))
    asyncio.run(features.stock_features(symbol="TCS", start=None, end=None, page=page))
    asyncio.run(features.features_bulk(body={"symbols": ["TCS"]}))


def test_every_screener_score_and_feature_route_selects_the_source_and_its_date(conn):
    _call_every_route()
    assert len(conn.sql) == 6
    for sql in conn.sql:
        assert all(column in sql for column in REAL) and "NULL::text" not in sql, sql
    assert "f.fundamentals_source, f.fundamentals_as_of" in conn.sql[0]         # aliased where the query is
    assert conn.checks == 1                                                    # looked up once, then remembered


@pytest.mark.parametrize("conn", [False], indirect=True)
def test_before_the_migration_the_routes_still_answer_with_empty_fields(conn):
    """A push to dev deploys this code without running migrations. Naming a column that is
    not there yet would fail the screener; typed NULLs keep the response shape instead."""
    _call_every_route()
    assert len(conn.sql) == 6
    for sql in conn.sql:
        assert PLACEHOLDER in sql and "f.fundamentals_source" not in sql, sql
    assert conn.checks == 6                                                    # keeps looking until it is there
    conn.migrated = True
    asyncio.run(stock_scores.stock_primitives(symbol="TCS", as_of_date=None))
    assert "f.fundamentals_source, f.fundamentals_as_of" in conn.sql[-1]       # picked up without a restart


def test_the_score_route_passes_the_two_fields_through(conn):
    out = asyncio.run(stock_scores.stock_primitives(symbol="TCS", as_of_date=None))
    assert out["data"]["fundamentals_source"] == "trendlyne_mcp"
    assert out["data"]["fundamentals_as_of"] == "2026-10-12"


def test_the_feature_column_lists_are_otherwise_unchanged():
    assert "fundamentals" not in features._FEATURE_COLS and "fundamentals" not in stock_scores._PRIMITIVE_COLS
    assert "market_cap_cr" in features._FEATURE_COLS and "f.market_cap_cr" in stock_scores._PRIMITIVE_COLS


def test_a_screen_cell_from_an_outside_source_says_so_and_does_not_claim_our_formula():
    row = {"symbol": "TCS", "roe_pct": 45.88, "fundamentals_source": "trendlyne_mcp",
           "fundamentals_as_of": date(2026, 10, 12)}
    cell = stock_screen._cell(reg.BY_KEY["roe_pct"], 45.88, date(2026, 10, 13), row)
    assert cell["value"] == 45.88 and cell["as_of"] == "2026-10-13"
    assert cell["source"] == "trendlyne_mcp" and cell["source_as_of"] == "2026-10-12"
    assert cell["source_dataset"] == "nidp.stock_fundamental_values"
    assert "formula" not in cell            # the registry's formula describes our own calculation, not the provider's


def test_a_screen_cell_from_our_own_calculation_keeps_its_formula_and_names_its_source():
    row = {"symbol": "TCS", "roe_pct": 44.0, "fundamentals_source": "nidp_computed",
           "fundamentals_as_of": date(2026, 10, 13)}
    cell = stock_screen._cell(reg.BY_KEY["roe_pct"], 44.0, date(2026, 10, 13), row)
    assert cell["formula"] == reg.BY_KEY["roe_pct"].formula
    assert cell["source_dataset"] == reg.BY_KEY["roe_pct"].source_dataset
    assert cell["source"] == "nidp_computed" and cell["source_as_of"] == "2026-10-13"


def test_other_cells_and_rows_without_a_source_are_unchanged():
    row = {"symbol": "TCS", "pe_ttm": 14.9, "roe_pct": None, "fundamentals_source": "trendlyne_mcp",
           "fundamentals_as_of": date(2026, 10, 12)}
    pe = stock_screen._cell(reg.BY_KEY["pe_ttm"], 14.9, date(2026, 10, 13), row)
    assert "source" not in pe and pe["formula"] == reg.BY_KEY["pe_ttm"].formula
    empty = stock_screen._cell(reg.BY_KEY["roe_pct"], None, date(2026, 10, 13), row)
    assert empty["value"] is None and "null_reason" in empty and "source" not in empty
    legacy = stock_screen._cell(reg.BY_KEY["roe_pct"], 12.0, date(2026, 10, 13))      # callers that pass no row
    assert legacy["formula"] == reg.BY_KEY["roe_pct"].formula and "source" not in legacy
    unlabelled = stock_screen._cell(reg.BY_KEY["roe_pct"], 12.0, date(2026, 10, 13), {"fundamentals_source": None})
    assert unlabelled["formula"] == reg.BY_KEY["roe_pct"].formula and "source" not in unlabelled
