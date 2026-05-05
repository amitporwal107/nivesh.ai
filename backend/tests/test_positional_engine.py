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
    accumulation_detector,
    backtest,
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


# ── Accumulation detector ────────────────────────────────────────────────
def test_vol_divergence_fires_on_volume_z_with_flat_price():
    """Volume Z = 1.5, price slope ~0 → vol_divergence should fire."""
    feats = {"volume_z_20": 1.5, "slope_20_pct": 0.05}
    fired, strength = accumulation_detector.detect_vol_divergence(feats)
    assert fired is True
    assert strength > 0.3


def test_vol_divergence_skips_when_price_already_running():
    """Volume Z high but slope > 0.1 means price is already moving — not pre-breakout."""
    feats = {"volume_z_20": 2.5, "slope_20_pct": 0.5}
    fired, _ = accumulation_detector.detect_vol_divergence(feats)
    assert fired is False


def test_vol_divergence_skips_when_volume_normal():
    feats = {"volume_z_20": 0.3, "slope_20_pct": 0.05}
    fired, _ = accumulation_detector.detect_vol_divergence(feats)
    assert fired is False


def test_delivery_spike_fires_on_rising_delivery():
    feats = {"delivery_trend_pct": 25.0, "slope_20_pct": 0.1}
    fired, strength = accumulation_detector.detect_delivery_spike(feats)
    assert fired is True
    assert strength >= 0.4


def test_delivery_spike_skips_when_already_running():
    feats = {"delivery_trend_pct": 25.0, "slope_20_pct": 0.5}
    fired, _ = accumulation_detector.detect_delivery_spike(feats)
    assert fired is False


def test_bb_squeeze_fires_when_compressed():
    feats = {"bb_width_20": 0.05, "atr_pct": 1.5}
    fired, strength = accumulation_detector.detect_bb_squeeze(feats)
    assert fired is True
    assert strength >= 0.4


def test_bb_squeeze_skips_when_loose():
    feats = {"bb_width_20": 0.15, "atr_pct": 3.0}
    fired, _ = accumulation_detector.detect_bb_squeeze(feats)
    assert fired is False


def test_sector_lag_fires_when_stock_lags_strong_bench():
    """Bench up 10%, stock up only 2%, stock above SMA50 — catch-up setup."""
    feats = {"return_20d_pct": 2.0, "close": 100, "sma_50": 95}
    fired, strength = accumulation_detector.detect_sector_lag(feats, bench_ret_20d=10.0)
    assert fired is True
    assert strength >= 0.4


def test_sector_lag_skips_when_bench_weak():
    """No catch-up case if the bench itself is flat."""
    feats = {"return_20d_pct": 1.0, "close": 100, "sma_50": 95}
    fired, _ = accumulation_detector.detect_sector_lag(feats, bench_ret_20d=0.5)
    assert fired is False


def test_sector_lag_skips_when_stock_below_sma50():
    """Stock weak → not 'lagging', it's broken."""
    feats = {"return_20d_pct": 1.0, "close": 90, "sma_50": 100}
    fired, _ = accumulation_detector.detect_sector_lag(feats, bench_ret_20d=10.0)
    assert fired is False


def test_detect_all_composite_zero_when_no_signals():
    out = accumulation_detector.detect_all({})
    assert out["accumulation_score"] == 0.0
    assert out["signals"] == []
    assert out["is_early_opportunity"] is False


def test_detect_all_combines_multiple_signals():
    """Volume divergence + BB squeeze should both fire and combine."""
    feats = {
        "volume_z_20": 2.0, "slope_20_pct": 0.05,
        "bb_width_20": 0.06, "atr_pct": 1.8,
        "delivery_trend_pct": 5.0,        # below threshold — won't fire
    }
    out = accumulation_detector.detect_all(feats)
    assert "vol_divergence" in out["signals"]
    assert "bb_squeeze" in out["signals"]
    assert out["accumulation_score"] > 0


def test_detect_all_count_multiplier_rewards_more_signals():
    """A pick with 3 fired signals should outscore a pick with 1
    fired signal of the same per-signal strength."""
    weak3 = {
        "volume_z_20": 1.5, "slope_20_pct": 0.05,
        "bb_width_20": 0.06, "atr_pct": 1.8,
        "delivery_trend_pct": 25.0,
    }
    strong1 = {
        "volume_z_20": 5.0, "slope_20_pct": 0.05,   # very strong vol_div
    }
    out_weak3 = accumulation_detector.detect_all(weak3)
    out_strong1 = accumulation_detector.detect_all(strong1)
    assert len(out_weak3["signals"]) >= 3
    assert len(out_strong1["signals"]) == 1
    # The 3-signal-confirmation should win even though each signal is weaker
    assert out_weak3["accumulation_score"] > out_strong1["accumulation_score"]


# ── Backtest forward-outcome computation ─────────────────────────────────
def test_forward_outcome_computes_max_return():
    bars_after = [
        {"high": 100, "low": 98},
        {"high": 105, "low": 99},     # max 5% up here
        {"high": 103, "low": 96},
    ]
    # v2: 3-tuple (max_ret, max_dd, broke_high)
    max_ret, max_dd, broke = backtest._forward_outcome(bars_after, 100, 3)
    assert max_ret == 5.0
    assert max_dd == -4.0
    assert broke is None     # no resistance arg → broke_high not computed


def test_forward_outcome_with_resistance_flags_break():
    """With a resistance arg, returns whether high crossed it."""
    bars_after = [
        {"high": 100, "low": 98},
        {"high": 105, "low": 99},
    ]
    _, _, broke = backtest._forward_outcome(bars_after, 100, 2, resistance=103)
    assert broke is True
    _, _, no_broke = backtest._forward_outcome(bars_after, 100, 2, resistance=110)
    assert no_broke is False


def test_forward_outcome_returns_none_when_short():
    """If we don't have enough forward bars, label is None."""
    max_ret, max_dd, broke = backtest._forward_outcome([{"high": 100, "low": 100}], 100, 5)
    assert max_ret is None and max_dd is None and broke is None


def test_label_one_skips_when_too_little_history():
    """label_one needs ≥60 bars before scan_date."""
    bars = _bars_from_closes([100] * 30)
    out = backtest.label_one(bars, bars[-1]["bar_date"])
    assert out is None


# ── Conviction framework ─────────────────────────────────────────────────
from services.positional_engine import conviction


def test_conviction_high_when_clean_setup_just_triggered():
    """Strong pillars, no penalties, LTP just above entry → HIGH_CONVICTION."""
    feats = {
        "close": 100.0, "sma_50": 95.0, "sma_200": 90.0,
        "slope_20_pct": 0.3, "rsi_14": 60,
        "volume_z_20": 1.5, "delivery_trend_pct": 12,
        "atr_pct": 1.5, "bb_width_20": 0.07,
        "breakout_proximity_pct": 0.5,
        "return_5d_pct": 3.0,
    }
    plan = {"entry": 100.0, "stoploss": 95.0, "target": 115.0, "risk_reward": 3.0}
    out = conviction.classify_verdict(features=feats, trade_plan=plan,
                                        live_ltp=101.0, scan_count=2)
    assert out["verdict"] == "HIGH_CONVICTION"
    assert out["final_score"] >= 65


def test_conviction_capped_when_extended_8_to_15_pct():
    """Same clean setup but LTP 12% past entry → SETUP_FORMING (hard cap)."""
    feats = {
        "close": 100.0, "sma_50": 95.0, "sma_200": 90.0,
        "slope_20_pct": 0.3, "rsi_14": 60,
        "volume_z_20": 1.5, "delivery_trend_pct": 12,
        "atr_pct": 1.5, "bb_width_20": 0.07,
        "breakout_proximity_pct": 0.5,
    }
    plan = {"entry": 100.0, "stoploss": 95.0, "target": 115.0, "risk_reward": 3.0}
    out = conviction.classify_verdict(features=feats, trade_plan=plan,
                                        live_ltp=112.0, scan_count=2)
    # Hard-capped — even with great pillars, can't be HIGH_CONVICTION
    assert out["verdict"] == "SETUP_FORMING"
    # Penalty fired
    assert any(p["name"].startswith("extended") for p in out["penalties"])


def test_conviction_capped_when_extended_above_15_pct():
    """LTP 20% past entry → AVOID_LATE no matter the setup."""
    feats = {"close": 100, "sma_50": 95, "sma_200": 90, "rsi_14": 60,
             "atr_pct": 1.5, "breakout_proximity_pct": 0.5}
    plan = {"entry": 100.0, "stoploss": 95.0, "target": 115.0, "risk_reward": 3.0}
    out = conviction.classify_verdict(features=feats, trade_plan=plan,
                                        live_ltp=120.0, scan_count=3)
    assert out["verdict"] == "AVOID_LATE"


def test_conviction_avoid_when_pillars_weak():
    """Weak pillars + no LTP overlay still produces AVOID_LATE."""
    feats = {"close": 100, "sma_50": 110, "sma_200": 120,    # below DMAs
             "rsi_14": 35, "atr_pct": 5.0}
    plan = {"entry": 100.0, "stoploss": 99.0, "target": 102.0, "risk_reward": 1.5}
    out = conviction.classify_verdict(features=feats, trade_plan=plan)
    assert out["verdict"] == "AVOID_LATE"


def test_conviction_overbought_rsi_penalised():
    feats = {"close": 100, "sma_50": 95, "sma_200": 90, "rsi_14": 78,
             "atr_pct": 2.0, "breakout_proximity_pct": 0.5}
    plan = {"entry": 100.0, "stoploss": 95.0, "target": 110.0, "risk_reward": 2.0}
    out = conviction.classify_verdict(features=feats, trade_plan=plan, live_ltp=100.5)
    assert any(p["name"] == "overbought_rsi" for p in out["penalties"])


def test_conviction_scan_bonus_lifts_borderline():
    """A borderline pick should benefit from multi-scan confirmation."""
    feats = {"close": 100, "sma_50": 99, "sma_200": 98, "rsi_14": 55,
             "atr_pct": 2.5, "breakout_proximity_pct": -1.0,
             "volume_z_20": 0.5, "delivery_trend_pct": 5}
    plan = {"entry": 100.0, "stoploss": 96.0, "target": 108.0, "risk_reward": 2.0}
    no_scans = conviction.classify_verdict(features=feats, trade_plan=plan,
                                              live_ltp=100, scan_count=0)
    many_scans = conviction.classify_verdict(features=feats, trade_plan=plan,
                                                live_ltp=100, scan_count=4)
    assert many_scans["final_score"] > no_scans["final_score"]
