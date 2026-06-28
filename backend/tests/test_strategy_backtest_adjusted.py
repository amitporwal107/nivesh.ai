"""Tests for the Tier-2 / R1 backtest correctness fix.

The backtest runner needs a live DB to execute, but the two defects R1
fixed live in *pure* code we can pin without a DB:

  1. the compiled query now projects the corp-action-adjusted close and
     joins nidp.prices_eod_adjusted (so entries trade on adj_close), and
  2. index universes can resolve to point-in-time index_constituents
     membership instead of the legacy present-day stock_master flag, and
  3. the exit-bar query reads the adjusted series, not raw stock_ohlcv.

A regression in any of these would silently reintroduce split/bonus return
corruption or survivorship bias, so they are worth pinning at the unit level.
"""
from __future__ import annotations

from services.strategy_engine.compiler_stock import compile_stock_query, to_asyncpg
from services.strategy_engine import backtest as bt


def _spec(ref: str = "NIFTY500"):
    return {
        "version": "1",
        "asset_class": "STOCK",
        "name": "adjusted-backtest-test",
        "universe": {"type": "index", "ref": ref},
        "entry": {"all_of": [
            {"feature": "rsi14", "op": ">", "value": 55},  # one bound param
        ]},
        "exit": {"stoploss_pct": 5, "target_rr": 2, "max_hold_days": 30},
        "ranking": {"by": "score", "limit": 20, "order": "desc"},
        "rebalance": "daily",
    }


def test_compiler_projects_adjusted_close_and_factor():
    sql, _ = compile_stock_query(_spec())
    assert "nidp.prices_eod_adjusted" in sql
    assert "pea.adj_close" in sql
    assert "adj_factor" in sql


def test_default_membership_is_legacy_flag():
    # Default (point_in_time_universe=False) keeps the present-day behaviour
    # so envs without index_constituents never silently return zero rows.
    sql, _ = compile_stock_query(_spec("NIFTY100"))
    assert "sm.is_nifty_100 IS TRUE" in sql
    assert "nidp.index_constituents" not in sql


def test_point_in_time_membership_uses_constituents():
    sql, _ = compile_stock_query(_spec("NIFTY500"), point_in_time_universe=True)
    assert "nidp.index_constituents" in sql
    assert "'Nifty 500'" in sql
    assert "MAX(ic2.as_of_date)" in sql       # point-in-time snapshot pick
    assert "ic2.as_of_date <= f.as_of_date" in sql
    assert "is_nifty_100" not in sql


def test_point_in_time_distinguishes_nifty_breadths():
    # The legacy bug collapsed 100/200/500 to the same ~226 set. Point-in-time
    # must map each ref to its own index_constituents name.
    for ref, name in [("NIFTY50", "Nifty 50"), ("NIFTY100", "Nifty 100"),
                      ("NIFTY200", "Nifty 200"), ("NIFTY500", "Nifty 500")]:
        sql, _ = compile_stock_query(_spec(ref), point_in_time_universe=True)
        assert f"'{name}'" in sql


def test_exit_bars_sql_reads_adjusted_series_not_raw_ohlcv():
    assert "nidp.prices_eod_adjusted" in bt._EXIT_BARS_SQL
    assert "adj_close" in bt._EXIT_BARS_SQL and "adj_high" in bt._EXIT_BARS_SQL
    assert "stock_ohlcv" not in bt._EXIT_BARS_SQL


def test_adjusted_join_adds_no_bound_params():
    # The adjusted-price join and point-in-time clause are all static SQL —
    # they must not shift the positional-param numbering the runner relies on.
    sql, params = compile_stock_query(_spec())
    _, base_args = to_asyncpg(sql, params)
    assert base_args == [55]
    sql_pit, params_pit = compile_stock_query(_spec(), point_in_time_universe=True)
    _, base_args_pit = to_asyncpg(sql_pit, params_pit)
    assert base_args_pit == [55]
