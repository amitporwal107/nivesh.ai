"""Entry setups A–E (user specification 2026-09-17; rules fixed in
.claude/workspace/ten-percent-days-3/evidence/entry_setups/PREREGISTRATION.md). Synthetic single-stock series with a
known shape per setup; every indicator uses data through T only."""
import numpy as np
import pandas as pd
import pytest


def _series(closes, vols=None, start="2025-01-01", spread=0.01, opens=None, highs=None, lows=None):
    d = pd.bdate_range(start, periods=len(closes))
    c = np.array(closes, dtype=float)
    o = np.array(opens if opens is not None else np.r_[c[0], c[:-1]], dtype=float)
    h = np.array(highs if highs is not None else np.maximum(o, c) * (1 + spread), dtype=float)
    l = np.array(lows if lows is not None else np.minimum(o, c) * (1 - spread), dtype=float)
    v = np.array(vols if vols is not None else [100_000] * len(c), dtype=float)
    return pd.DataFrame({"symbol": "X", "as_of_date": d, "open": o, "high": h, "low": l, "close": c, "prev_close": np.r_[c[0], c[:-1]],
                         "volume": v, "deliverable_pct": 40.0})


def test_indicators_use_only_prior_sessions_for_highs_and_volume_averages():
    from nidp.services.tpd_model.entry_setups import indicators

    df = _series(list(range(100, 160)), vols=[100_000] * 59 + [900_000])
    ind = indicators(df)
    last = ind.iloc[-1]
    assert last["hh20"] == pytest.approx(df["high"].iloc[-21:-1].max())               # T-20..T-1, not including T
    assert last["vol_avg20"] == pytest.approx(100_000) and last["rvol"] == pytest.approx(9.0)
    assert last["clv"] == pytest.approx((last["close"] - last["low"]) / (last["high"] - last["low"]))
    assert last["ema20"] == pytest.approx(df["close"].ewm(span=20, adjust=False).mean().iloc[-1])
    assert last["ret20"] == pytest.approx(df["close"].iloc[-1] / df["close"].iloc[-21] - 1)


def _breakout_frame():
    closes = [100 + 0.2 * np.sin(i) for i in range(59)] + [104.0]                      # a tight base, then a close above it
    highs = [c * 1.005 for c in closes[:-1]] + [104.3]
    lows = [c * 0.995 for c in closes[:-1]] + [100.8]
    return _series(closes, vols=[100_000] * 59 + [200_000], highs=highs, lows=lows)


def test_setup_a_breakout_fires_on_close_above_hh20_with_volume_and_strong_close():
    from nidp.services.tpd_model.entry_setups import evaluate_setups, indicators

    ind = indicators(_breakout_frame())
    ind["rs20_nifty"] = 0.02; ind["rs20_sector"] = 0.01
    row = evaluate_setups(ind).iloc[-1]
    assert bool(row["setup_a"]) is True and bool(row["no_chase"]) is False
    weak = _breakout_frame(); weak.loc[weak.index[-1], "close"] = 101.2               # long upper wick, weak close (CLV < 0.70)
    ind2 = indicators(weak); ind2["rs20_nifty"] = 0.02; ind2["rs20_sector"] = 0.01
    assert bool(evaluate_setups(ind2).iloc[-1]["setup_a"]) is False
    ind3 = indicators(_breakout_frame()); ind3["rs20_nifty"] = -0.01; ind3["rs20_sector"] = 0.01
    assert bool(evaluate_setups(ind3).iloc[-1]["setup_a"]) is False                   # relative strength must be positive


def test_setup_d_volatility_expansion_needs_compression_contraction_then_breakout():
    from nidp.services.tpd_model.entry_setups import evaluate_setups, indicators

    wide = [100 + 6 * np.sin(i / 2) for i in range(46)]                                 # volatile phase covers T-30..T-11 and ATR(T-21)
    tight = [100 + 0.3 * np.sin(i) for i in range(14)]                                  # compression covers ATR(T-1) and T-10..T-1
    closes = wide + tight + [102.5]
    vols = [300_000] * 46 + [100_000] * 14 + [400_000]
    highs = [c * 1.03 for c in wide] + [c * 1.004 for c in tight] + [102.7]
    lows = [c * 0.97 for c in wide] + [c * 0.996 for c in tight] + [100.2]
    ind = indicators(_series(closes, vols=vols, highs=highs, lows=lows))
    ind["rs20_nifty"] = 0.0; ind["rs20_sector"] = 0.0
    row = evaluate_setups(ind).iloc[-1]
    assert bool(row["setup_d"]) is True
    assert row["range10"] <= 0.10 and row["atr_prev"] < 0.75 * row["atr_prev21"]


def test_setup_b_pullback_reversal_in_an_uptrend():
    from nidp.services.tpd_model.entry_setups import evaluate_setups, indicators

    up = [100 * 1.006 ** i for i in range(55)]
    pull = [up[-1] * 0.99, up[-1] * 0.98, up[-1] * 0.972, up[-1] * 0.968]              # down days on light volume
    rev = [up[-1] * 0.985]
    closes = up + pull + rev
    vols = [100_000] * 55 + [60_000] * 4 + [150_000]
    opens = list(np.r_[closes[0], closes[:-1]]); opens[-1] = pull[-1] * 0.999
    df = _series(closes, vols=vols, opens=opens)
    ind = indicators(df); ind["rs20_nifty"] = 0.0; ind["rs20_sector"] = 0.0
    row = evaluate_setups(ind).iloc[-1]
    assert row["ema20"] > row["ema50"] and bool(row["setup_b"]) is True


def test_setup_c_needs_a_material_positive_print_and_price_confirmation():
    from nidp.services.tpd_model.entry_setups import evaluate_setups, indicators

    closes = [100.0] * 59 + [104.0]
    df = _series(closes, vols=[100_000] * 59 + [250_000], highs=[100.5] * 59 + [104.2], lows=[99.5] * 59 + [101.0])
    ind = indicators(df); ind["rs20_nifty"] = 0.0; ind["rs20_sector"] = 0.0
    ind["event_positive_today"] = False
    assert bool(evaluate_setups(ind).iloc[-1]["setup_c"]) is False
    ind.loc[ind.index[-1], "event_positive_today"] = True
    assert bool(evaluate_setups(ind).iloc[-1]["setup_c"]) is True


def test_no_chase_marks_band_closes_and_locked_bars():
    from nidp.services.tpd_model.entry_setups import evaluate_setups, indicators

    closes = [100.0] * 59 + [110.0]
    df = _series(closes, vols=[100_000] * 59 + [500_000], highs=[100.5] * 59 + [110.0], lows=[99.5] * 59 + [104.0])
    ind = indicators(df); ind["rs20_nifty"] = 0.05; ind["rs20_sector"] = 0.05
    row = evaluate_setups(ind).iloc[-1]
    assert bool(row["no_chase"]) is True and bool(row["setup_a"]) is False


def test_trade_plan_stops_risk_reward_and_filters():
    from nidp.services.tpd_model.entry_setups import trade_plan

    p5 = trade_plan(entry=100.0, structure_stop=98.5, atr=2.0, target_pct=0.05, atr_mult=1.5)
    assert p5["stop"] == pytest.approx(98.5) and p5["stop_pct"] == pytest.approx(0.015) and p5["rr"] == pytest.approx(0.05 / 0.015) and p5["ok"]
    wide = trade_plan(entry=100.0, structure_stop=90.0, atr=2.0, target_pct=0.05, atr_mult=1.5)
    assert wide["stop"] == pytest.approx(97.0) and wide["rr"] == pytest.approx(0.05 / 0.03) and wide["ok"] is False       # R/R < 2
    tight = trade_plan(entry=100.0, structure_stop=99.8, atr=2.0, target_pct=0.05, atr_mult=1.5)
    assert tight["ok"] is False                                                        # stop closer than 0.5 x ATR
    assert trade_plan(entry=100.0, structure_stop=101.0, atr=2.0, target_pct=0.05, atr_mult=1.5)["ok"] is False


def test_bracket_simulation_is_conservative_on_same_day_ties_and_gaps():
    from nidp.services.tpd_model.entry_setups import simulate_bracket

    fwd = pd.DataFrame({"open": [100.5, 101, 102], "high": [101, 105.5, 103], "low": [99.5, 100.5, 101], "close": [100.8, 104, 102.5]})
    r = simulate_bracket(entry=100.0, stop=98.0, target=105.0, fwd=fwd, cost=0.0025)
    assert r["exit"] == 105.0 and r["exit_day"] == 2 and r["outcome"] == "target" and r["net"] == pytest.approx(0.05 - 0.0025)
    tie = pd.DataFrame({"open": [100], "high": [106], "low": [97], "close": [101]})
    assert simulate_bracket(100.0, 98.0, 105.0, tie, 0.0)["outcome"] == "stop"             # both inside one bar: stop first
    gap = pd.DataFrame({"open": [100.5, 95.0], "high": [101, 96], "low": [99.5, 94], "close": [100.8, 95.5]})
    g = simulate_bracket(100.0, 98.0, 105.0, gap, 0.0)
    assert g["outcome"] == "stop" and g["exit"] == 95.0                                   # gapped through the stop: exit at the open
    flat = pd.DataFrame({"open": [100] * 5, "high": [101] * 5, "low": [99] * 5, "close": [100, 100, 100, 100, 100.4]})
    assert simulate_bracket(100.0, 98.0, 105.0, flat, 0.0)["outcome"] == "time" and simulate_bracket(100.0, 98.0, 105.0, flat, 0.0)["exit"] == 100.4


def test_eqs_is_bounded_and_weighted_as_specified():
    from nidp.services.tpd_model.entry_setups import EQS_WEIGHTS, entry_quality

    assert sum(EQS_WEIGHTS.values()) == 100
    best = {"clv": 1.0, "close": 110.0, "hh20": 100.0, "atr_pct": 0.02, "rvol": 3.0, "updown_ok": True, "ema20": 2, "ema50": 1, "rs20_nifty": 0.1,
            "atr_prev": 1.0, "atr_prev21": 2.0, "range10": 0.05, "event_positive_today": True, "event_recent": False, "nifty_above_ema50": True,
            "nifty_ret5": 0.01, "adv20": 1e9}
    q = entry_quality(best)
    assert q["eqs"] == pytest.approx(100.0) and set(q["components"]) == set(EQS_WEIGHTS)
    worst = {**best, "clv": 0.0, "close": 90.0, "rvol": 0.0, "updown_ok": False, "ema20": 1, "ema50": 2, "rs20_nifty": -0.1, "atr_prev": 3.0,
             "range10": 0.3, "event_positive_today": False, "nifty_above_ema50": False, "nifty_ret5": -0.02, "adv20": 0.0}
    assert entry_quality(worst)["eqs"] == pytest.approx(0.0)


def test_evaluate_setups_is_row_wise_on_a_multi_symbol_frame():
    from nidp.services.tpd_model.entry_setups import evaluate_setups, indicators

    one = indicators(_breakout_frame())
    other = indicators(_breakout_frame().assign(symbol="Y", volume=5_000_000.0))       # a much busier stock stacked above
    both = pd.concat([other, one], ignore_index=True)
    both["rs20_nifty"] = 0.02; both["rs20_sector"] = 0.01
    alone = one.assign(rs20_nifty=0.02, rs20_sector=0.01)
    cols = ["setup_a", "setup_b", "setup_c", "setup_d", "setup_e", "no_chase"]
    pd.testing.assert_frame_equal(evaluate_setups(both).iloc[len(other):][cols].reset_index(drop=True), evaluate_setups(alone)[cols])
    assert bool(evaluate_setups(both)["setup_a_raw"].iloc[-1]) is True
