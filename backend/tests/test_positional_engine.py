"""Unit tests for the positional engine's pure-Python core.

Covers:
  - SMA, EMA, RSI (Wilder), MACD, ATR, slope, returns
  - Scoring + stage classification edge cases
  - Trade planner (entry/SL/target/RR)
  - Chartink CSV parsing
  - Bhavcopy CSV parsing

These tests are import-light and do not touch the database.
"""
from __future__ import annotations

import math
from datetime import date

import pytest

from services.positional_engine import (
    chartink_api,
    chartink_loader,
    bhavcopy_ingester,
    feature_calculator as fc,
    portfolio_filter,
    scan_config,
    scorer,
    trade_planner,
)
from services.positional_engine.pipeline import score_symbol


# ── Helpers ──────────────────────────────────────────────────────────────
def _bars_from_closes(closes, *, start_high_low_spread=0.5, vol=100_000):
    """Build bar dicts from a list of closes — for tests that only need
    one of {close, ohlc} but we still need the bar shape."""
    bars = []
    base = date(2026, 1, 1)
    prev = closes[0]
    for i, c in enumerate(closes):
        h = max(c, prev) + start_high_low_spread
        l = min(c, prev) - start_high_low_spread
        bars.append({
            "bar_date": base, "open": prev, "high": h, "low": l, "close": c,
            "volume": vol, "delivery_pct": 50.0,
        })
        prev = c
    return bars


# ── SMA / EMA ────────────────────────────────────────────────────────────
def test_sma_basic():
    assert fc.sma([1, 2, 3, 4, 5], 5) == 3
    assert fc.sma([1, 2, 3], 5) is None
    assert fc.sma([], 1) is None


def test_ema_seed_matches_sma():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert fc.ema(vals, 5) == pytest.approx(3.0)


def test_ema_responsive_to_recent_jump():
    base = [10.0] * 19
    spike = base + [20.0]
    e = fc.ema(spike, 10)
    assert e is not None and 10 < e < 20


# ── RSI ──────────────────────────────────────────────────────────────────
def test_rsi_all_up_is_100():
    closes = [i * 1.0 for i in range(1, 50)]
    assert fc.rsi(closes, 14) == pytest.approx(100.0, abs=1e-6)


def test_rsi_all_down_is_0():
    closes = [50 - i * 1.0 for i in range(40)]
    val = fc.rsi(closes, 14)
    assert val is not None and val < 5


def test_rsi_neutral_near_50():
    closes = []
    for i in range(40):
        closes.append(100 + (i % 2) * 0.5)
    val = fc.rsi(closes, 14)
    assert val is not None and 30 < val < 70


# ── MACD ─────────────────────────────────────────────────────────────────
def test_macd_returns_components():
    closes = [100 + math.sin(i / 5) * 5 for i in range(60)]
    m = fc.macd(closes)
    assert m is not None
    assert "macd" in m and "signal" in m and "hist" in m
    assert m["hist"] == pytest.approx(m["macd"] - m["signal"])


def test_macd_too_short():
    assert fc.macd([1, 2, 3]) is None


# ── ATR ──────────────────────────────────────────────────────────────────
def test_atr_basic():
    bars = _bars_from_closes([100 + i * 0.1 for i in range(20)])
    a = fc.atr(bars, 14)
    assert a is not None and a > 0


# ── Slope ────────────────────────────────────────────────────────────────
def test_slope_pct_uptrend():
    closes = [100 + i for i in range(20)]
    s = fc.slope_pct(closes, 20)
    assert s is not None and s > 0


def test_slope_pct_downtrend():
    closes = [100 - i for i in range(20)]
    s = fc.slope_pct(closes, 20)
    assert s is not None and s < 0


# ── Returns / highs ──────────────────────────────────────────────────────
def test_return_pct():
    assert fc.return_pct([100, 110], 1) == pytest.approx(10.0)
    assert fc.return_pct([100, 100, 100], 1) == 0.0
    assert fc.return_pct([100], 1) is None


def test_highest_lowest():
    vals = [3, 1, 4, 1, 5, 9, 2, 6]
    assert fc.highest(vals, 5) == 9
    assert fc.lowest(vals, 5) == 1


# ── Top-level feature pack ───────────────────────────────────────────────
def test_compute_features_uptrend_pack():
    closes = [100 + i * 0.5 for i in range(220)]
    bars = _bars_from_closes(closes)
    f = fc.compute_features(bars)
    assert f["close"] == closes[-1]
    assert f["sma_50"] is not None
    assert f["sma_200"] is not None
    assert f["close"] > f["sma_50"] > f["sma_200"]
    assert f["rsi_14"] is not None and f["rsi_14"] > 50


def test_compute_features_returns_dict_for_short_series():
    bars = _bars_from_closes([100, 101, 102])
    f = fc.compute_features(bars)
    assert f["close"] == 102
    assert f["sma_50"] is None


# ── Scorer ───────────────────────────────────────────────────────────────
def test_score_uptrend_high():
    closes = [100 + i * 0.5 for i in range(220)]
    bars = _bars_from_closes(closes)
    f = fc.compute_features(bars)
    s = scorer.score(f, rs_vs_nifty_pct=2.5, scan_hits=("trend_up",))
    assert s["sub_scores"]["trend"] >= 0.6
    assert 0.0 <= s["final_score"] <= 1.0


def test_score_downtrend_weak():
    closes = [200 - i * 0.5 for i in range(220)]
    bars = _bars_from_closes(closes)
    f = fc.compute_features(bars)
    s = scorer.score(f)
    assert s["sub_scores"]["trend"] <= 0.4
    assert s["stage"] in ("WEAK", "ACCUMULATION", "EXTENDED")


def test_stage_extended_when_overbought():
    closes = [100 * (1.02 ** i) for i in range(220)]   # parabolic
    bars = _bars_from_closes(closes)
    f = fc.compute_features(bars)
    s = scorer.score(f)
    assert s["stage"] == "EXTENDED"


def test_score_missing_inputs_neutral():
    s = scorer.score({})
    assert 0.4 <= s["final_score"] <= 0.6


# ── Trade planner ────────────────────────────────────────────────────────
def test_plan_breakout_has_positive_rr():
    closes = [100 + i * 0.4 for i in range(220)]
    bars = _bars_from_closes(closes)
    f = fc.compute_features(bars)
    plan = trade_planner.plan("BREAKOUT", f)
    assert plan is not None
    assert plan["target"] > plan["entry"] > plan["stoploss"]
    assert plan["risk_reward"] >= 1.5


def test_plan_returns_none_for_weak():
    closes = [200 - i * 0.5 for i in range(220)]
    bars = _bars_from_closes(closes)
    f = fc.compute_features(bars)
    assert trade_planner.plan("WEAK", f) is None
    assert trade_planner.plan("EXTENDED", f) is None


# ── Pipeline (pure-function path) ────────────────────────────────────────
def test_score_symbol_short_history_returns_none():
    bars = _bars_from_closes([100, 101, 102])
    assert score_symbol("ABC", bars) is None


def test_score_symbol_uptrend_actionable_or_extended():
    closes = [100 + i * 0.5 for i in range(220)]
    bars = _bars_from_closes(closes)
    out = score_symbol("INFY", bars, scan_hits=["atlas.trend_up"])
    assert out is not None
    assert out["nse_symbol"] == "INFY"
    # Either it's actionable with a plan, or stage is EXTENDED/WEAK without one
    if out["actionable"]:
        assert out["trade_plan"] is not None
        assert out["scores"]["stage"] in ("ACCUMULATION", "EARLY_BREAKOUT", "BREAKOUT")
    else:
        assert out["scores"]["stage"] in ("EXTENDED", "WEAK")


# ── Chartink CSV parser ──────────────────────────────────────────────────
def test_chartink_parse_basic():
    csv = "Stock Name,Symbol,Price,% Chg\nInfosys,INFY,1500,1.2\nTCS,TCS.NS,3500,0.5\n"
    rows = chartink_loader.parse_csv(csv)
    syms = sorted(r["symbol"] for r in rows)
    assert syms == ["INFY", "TCS"]


def test_chartink_parse_skips_blank_rows():
    csv = "Symbol,Price\nINFY,1500\n,\nRELIANCE,2500\n"
    rows = chartink_loader.parse_csv(csv)
    assert {r["symbol"] for r in rows} == {"INFY", "RELIANCE"}


# ── Bhavcopy parser ──────────────────────────────────────────────────────
def test_bhavcopy_parse_filters_to_eq_be():
    blob = (
        " SYMBOL , SERIES , DATE1 , PREV_CLOSE , OPEN_PRICE , HIGH_PRICE , LOW_PRICE ,"
        " LAST_PRICE , CLOSE_PRICE , AVG_PRICE , TTL_TRD_QNTY , TURNOVER_LACS ,"
        " NO_OF_TRADES , DELIV_QTY , DELIV_PER \n"
        " INFY , EQ , 02-MAY-2026 , 1490 , 1495 , 1510 , 1488 , 1500 , 1505 , 1500 ,"
        " 5000000 , 7500 , 25000 , 3500000 , 70.00 \n"
        " ABCSME , SM , 02-MAY-2026 , 100 , 100 , 105 , 99 , 102 , 102 , 101 ,"
        " 100000 , 100 , 200 , 50000 , 50.00 \n"
    )
    bars = bhavcopy_ingester.parse_bhavcopy_csv(blob, date(2026, 5, 2))
    assert len(bars) == 1
    b = bars[0]
    assert b["nse_symbol"] == "INFY"
    assert b["close"] == 1505.0
    assert b["delivery_pct"] == 70.0
    assert b["source"] == "bhavcopy"


# ── Portfolio filter ─────────────────────────────────────────────────────
def test_portfolio_filter_warns_on_overlap():
    signals = [{"nse_symbol": "INFY", "final_score": 0.8}]
    holdings = [{"nse_symbol": "INFY", "sector": "IT", "value": 100000}]
    out = portfolio_filter.annotate(signals, holdings,
                                     symbol_to_sector={"INFY": "IT"})
    assert len(out) == 1
    assert "portfolio_warning" in out[0]


def test_portfolio_filter_no_warning_when_unrelated():
    signals = [{"nse_symbol": "TCS", "final_score": 0.8}]
    holdings = [{"nse_symbol": "RELIANCE", "sector": "Energy", "value": 100000}]
    out = portfolio_filter.annotate(signals, holdings,
                                     symbol_to_sector={"TCS": "IT"})
    assert "portfolio_warning" not in out[0]


# ── Chartink API parser ──────────────────────────────────────────────────
def test_chartink_api_parse_basic():
    payload = {
        "data": [
            {"sr": 1, "name": "Infosys", "nsecode": "INFY", "bsecode": "500209",
             "per_chg": 1.2, "close": 1500.5, "volume": 5000000},
            {"sr": 2, "name": "TCS", "nsecode": "TCS",
             "per_chg": 0.5, "close": 3500, "volume": 1200000},
        ],
        "aborted": False,
    }
    rows = chartink_api.parse_response(payload)
    assert [r["symbol"] for r in rows] == ["INFY", "TCS"]
    assert rows[0]["extra"]["close"] == 1500.5
    assert rows[0]["extra"]["per_chg"] == 1.2


def test_chartink_api_parse_handles_empty_and_garbage():
    assert chartink_api.parse_response({}) == []
    assert chartink_api.parse_response({"data": None}) == []
    assert chartink_api.parse_response({"data": [{}, {"nsecode": ""}, {"nsecode": "-"}]}) == []
    assert chartink_api.parse_response("not a dict") == []


def test_chartink_api_parse_falls_back_to_name():
    """If `nsecode` is missing, parser uses `name` (some clauses return that)."""
    payload = {"data": [{"name": "RELIANCE"}]}
    rows = chartink_api.parse_response(payload)
    assert rows == [{"symbol": "RELIANCE", "extra": {
        "name": "RELIANCE", "close": None, "per_chg": None,
        "volume": None, "bsecode": None,
    }}]


# ── Scan config validator ────────────────────────────────────────────────
def test_scan_config_validate_dedupes_and_drops_blank():
    raw = [
        {"name": "atlas.trend", "clause": "( {cash} ... )"},
        {"name": "atlas.trend", "clause": "duplicate name — should be dropped"},
        {"name": "", "clause": "no name"},
        {"name": "atlas.delivery", "clause": ""},  # no clause
        {"name": "atlas.breakout", "clause": "x", "enabled": False},
    ]
    cleaned = scan_config.validate(raw)
    assert [s["name"] for s in cleaned] == ["atlas.trend", "atlas.breakout"]
    assert cleaned[1]["enabled"] is False


def test_portfolio_filter_drop_mode():
    """User holds INFY (10% — over per-stock cap) and a diversified rest of
    portfolio. Drop mode should drop INFY but keep TCS (different sector,
    no overlap)."""
    signals = [
        {"nse_symbol": "INFY", "final_score": 0.8},
        {"nse_symbol": "TCS", "final_score": 0.7},
    ]
    holdings = [
        {"nse_symbol": "INFY",     "sector": "IT",       "value": 100_000},
        {"nse_symbol": "RELIANCE", "sector": "Energy",   "value": 400_000},
        {"nse_symbol": "HDFCBANK", "sector": "Banking",  "value": 500_000},
    ]
    out = portfolio_filter.filter_actionable(
        signals, holdings,
        drop_if_overexposed=True,
        symbol_to_sector={"INFY": "IT", "TCS": "IT"},
    )
    assert {s["nse_symbol"] for s in out} == {"TCS"}
