"""Tests for the market-data re-architecture (R2): the Python DSL evaluator
and the provider's pure helpers. The HTTP/SQL backends need live services, so
here we pin the parts that decide correctness without a DB:

  • evaluator predicate truth-table + ranking (must mirror compiler_stock),
  • point-in-time membership selection from sampled snapshots,
  • monthly membership sampling,
  • provider selection by STRATEGY_MARKET_DATA.
"""
from __future__ import annotations

import os
from datetime import date

from services.strategy_engine import evaluator as ev
from services.strategy_engine.compiler_stock import _PIT_INDEX_NAME
from services.strategy_engine import market_data as md


SPEC = {
    "version": "1", "asset_class": "STOCK", "name": "eval-test",
    "universe": {"type": "index", "ref": "NIFTY500"},
    "entry": {"all_of": [
        {"feature": "rsi14", "op": ">", "value": 55},
        {"feature": "close", "op": ">", "compare_to": "sma50"},
    ]},
    "exit": {"stoploss_pct": 5, "target_rr": 2, "max_hold_days": 30},
    "ranking": {"by": "score", "limit": 5, "order": "desc"},
    "rebalance": "daily",
}

ROWS = [
    {"symbol": "A", "rsi14": 60, "close": 100, "sma50": 90,  "accumulation_score": 0.8},
    {"symbol": "B", "rsi14": 50, "close": 80,  "sma50": 85,  "accumulation_score": 0.9},  # rsi fails
    {"symbol": "C", "rsi14": 70, "close": 120, "sma50": 100, "accumulation_score": None},  # matches, null score
    {"symbol": "D", "rsi14": None, "close": 50, "sma50": 40, "accumulation_score": 0.5},   # null operand → excluded
]


def test_screen_rows_filters_ranks_and_caps():
    out = ev.screen_rows(SPEC, ROWS)
    # B fails rsi, D has a NULL operand (SQL semantics → excluded). A and C match,
    # ranked desc by accumulation_score with NULLs last → A then C.
    assert [r["symbol"] for r in out] == ["A", "C"]


def test_ranking_field_matches_compiler_proxy():
    # score/composite_score must resolve to accumulation_score (compiler_stock parity).
    assert ev.ranking_field("score") == "accumulation_score"
    assert ev.ranking_field("composite_score") == "accumulation_score"
    assert ev.ranking_field("rsi14") == "rsi14"


def test_pivot_breakout_flag_boolean_semantics():
    p_eq1 = {"feature": "pivot_breakout_flag", "op": "=", "value": 1}
    assert ev._match_predicate(p_eq1, {"pivot_breakout_flag": 1}) is True
    assert ev._match_predicate(p_eq1, {"pivot_breakout_flag": 0}) is False
    assert ev._match_predicate(p_eq1, {"pivot_breakout_flag": None}) is False


def test_null_operand_never_matches():
    p = {"feature": "rsi14", "op": ">", "value": 55}
    assert ev._match_predicate(p, {"rsi14": None}) is False
    assert ev._match_predicate(p, {"rsi14": 60}) is True


def test_asc_order_and_limit():
    spec = {**SPEC, "ranking": {"by": "rsi14", "limit": 1, "order": "asc"}}
    out = ev.screen_rows(spec, ROWS)
    # matches are A(rsi60) and C(rsi70); asc by rsi14, limit 1 → A
    assert [r["symbol"] for r in out] == ["A"]


def test_membership_sample_dates_monthly():
    pts = md.DaasMarketDataProvider._membership_sample_dates(date(2024, 1, 15), date(2024, 4, 10))
    # endpoints + month-starts strictly between
    assert pts[0] == date(2024, 1, 15) and pts[-1] == date(2024, 4, 10)
    assert date(2024, 2, 1) in pts and date(2024, 3, 1) in pts and date(2024, 4, 1) in pts
    # single-day window collapses to one point
    assert md.DaasMarketDataProvider._membership_sample_dates(date(2024, 1, 1), date(2024, 1, 1)) == [date(2024, 1, 1)]


def test_point_in_time_membership_selection():
    p = md.DaasMarketDataProvider()
    p._snapshots = [
        (date(2024, 1, 1), {"A", "B"}),
        (date(2024, 4, 1), {"B", "C"}),
    ]
    assert p._membership(date(2024, 2, 1)) == {"A", "B"}     # latest <= date
    assert p._membership(date(2024, 5, 1)) == {"B", "C"}
    assert p._membership(date(2023, 1, 1)) == {"A", "B"}     # before all → earliest


def test_index_name_mapping_is_distinct():
    # The legacy bug collapsed breadths; the PIT map must be 1:1.
    assert _PIT_INDEX_NAME["NIFTY500"] == "Nifty 500"
    assert len(set(_PIT_INDEX_NAME.values())) == len(_PIT_INDEX_NAME)


def test_get_provider_respects_env_override():
    prev = os.environ.get("STRATEGY_MARKET_DATA")
    try:
        os.environ["STRATEGY_MARKET_DATA"] = "sql"
        assert isinstance(md.get_provider(None), md.SqlMarketDataProvider)
        os.environ["STRATEGY_MARKET_DATA"] = "daas"
        assert isinstance(md.get_provider(None), md.DaasMarketDataProvider)
    finally:
        if prev is None:
            os.environ.pop("STRATEGY_MARKET_DATA", None)
        else:
            os.environ["STRATEGY_MARKET_DATA"] = prev
