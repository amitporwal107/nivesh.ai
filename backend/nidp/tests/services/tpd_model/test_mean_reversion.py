"""Short-term mean reversion E1–E5 (user instruction 2026-09-17; rules fixed in
docs/ai_research/tpd3/mean_reversion/PREREGISTRATION.md before this code). Synthetic series with known shapes."""
import json

import numpy as np
import pandas as pd
import pytest


def _bars(closes, opens=None, highs=None, lows=None, vols=None, start="2025-01-01", symbol="X"):
    c = np.asarray(closes, dtype=float)
    o = np.asarray(opens if opens is not None else np.r_[c[0], c[:-1]], dtype=float)
    h = np.asarray(highs if highs is not None else np.maximum(o, c) * 1.005, dtype=float)
    l = np.asarray(lows if lows is not None else np.minimum(o, c) * 0.995, dtype=float)
    v = np.asarray(vols if vols is not None else [1_000_000] * len(c), dtype=float)
    return pd.DataFrame({"symbol": symbol, "as_of_date": pd.bdate_range(start, periods=len(c)), "open": o, "high": h, "low": l, "close": c, "volume": v})


def _uptrend_then_dip(dip=(0.98, 0.975, 0.985)):
    up = [100 * 1.01 ** i for i in range(40)]                  # steep enough that a 5–6% dip stays above SMA20
    closes = up + [up[-1] * f for f in np.cumprod(dip)]
    return closes


def test_indicators_rsi2_sma_returns_and_liquidity_use_only_data_through_t():
    from nidp.services.tpd_model.mean_reversion import indicators

    closes = _uptrend_then_dip()
    x = indicators(_bars(closes))
    last = x.iloc[-1]
    assert last["sma20"] == pytest.approx(np.mean(closes[-20:]))
    assert last["r3"] == pytest.approx(closes[-1] / closes[-4] - 1) and last["r5"] == pytest.approx(closes[-1] / closes[-6] - 1)
    d = pd.Series(closes).diff()
    g = d.clip(lower=0).ewm(alpha=0.5, adjust=False).mean(); lo = (-d.clip(upper=0)).ewm(alpha=0.5, adjust=False).mean()
    assert last["rsi2"] == pytest.approx((100 - 100 / (1 + g / lo)).iloc[-1])
    assert last["adv20"] == pytest.approx((x["close"] * x["volume"]).iloc[-21:-1].mean())
    assert last["rvol"] == pytest.approx(1.0)
    up_only = indicators(_bars([100 + i for i in range(10)]))
    assert up_only["rsi2"].iloc[-1] == 100.0                                            # no losses → 100


def test_e1_fires_on_a_three_day_dip_above_sma20_with_a_close_off_the_low_and_quiet_volume():
    from nidp.services.tpd_model.mean_reversion import indicators, signals

    closes = _uptrend_then_dip()
    b = _bars(closes)
    b.loc[b.index[-1], ["high", "low"]] = [closes[-1] * 1.004, closes[-1] * 0.99]       # CLV ≈ 0.71
    x = signals(indicators(b).assign(rs20_sector=0.01))
    last = x.iloc[-1]
    assert last["r3"] <= -0.04 and last["close"] > last["sma20"] and bool(last["mr_e1"]) is True
    loud = b.copy(); loud.loc[loud.index[-1], "volume"] = 2_000_000                        # RVOL 2 → selling pressure
    assert bool(signals(indicators(loud).assign(rs20_sector=0.01)).iloc[-1]["mr_e1"]) is False
    at_low = b.copy(); at_low.loc[at_low.index[-1], "low"] = closes[-1] * 0.9995            # close at the day's low
    assert bool(signals(indicators(at_low).assign(rs20_sector=0.01)).iloc[-1]["mr_e1"]) is False
    shallow = _bars(_uptrend_then_dip(dip=(0.99, 0.99, 0.995)))                              # −2.5% only
    assert bool(signals(indicators(shallow).assign(rs20_sector=0.01)).iloc[-1]["mr_e1"]) is False


def test_e2_needs_a_five_session_decline_of_five_percent():
    from nidp.services.tpd_model.mean_reversion import indicators, signals

    closes = _uptrend_then_dip(dip=(0.995, 0.99, 0.985, 0.99, 0.985))                        # −5.4% over five
    b = _bars(closes); b.loc[b.index[-1], ["high", "low"]] = [closes[-1] * 1.004, closes[-1] * 0.99]
    x = signals(indicators(b).assign(rs20_sector=0.0)).iloc[-1]
    assert x["r5"] <= -0.05 and x["r3"] > -0.04 and bool(x["mr_e2"]) is True and bool(x["mr_e1"]) is False


def test_e3_rsi2_turns_up_from_ten_or_below_after_the_decline():
    from nidp.services.tpd_model.mean_reversion import indicators, signals

    closes = _uptrend_then_dip(dip=(0.97, 0.965, 1.005))                                      # two hard down days, then an up close
    x = signals(indicators(_bars(closes)).assign(rs20_sector=0.0)).iloc[-1]
    assert x["r3"] <= -0.04 and x["rsi2_prev"] <= 10 and x["rsi2"] > x["rsi2_prev"] and bool(x["mr_e3"]) is True
    still_down = signals(indicators(_bars(_uptrend_then_dip(dip=(0.97, 0.965, 0.995)))).assign(rs20_sector=0.0)).iloc[-1]
    assert bool(still_down["mr_e3"]) is False


def test_e4_needs_positive_relative_strength_against_the_sector_and_e5_a_reversal_candle():
    from nidp.services.tpd_model.mean_reversion import indicators, signals

    closes = _uptrend_then_dip()
    b = _bars(closes)
    i = b.index[-1]
    b.loc[i, "open"] = closes[-1] * 0.985; b.loc[i, "low"] = min(b.loc[b.index[-2], "low"], closes[-1] * 0.98) * 0.999
    b.loc[i, "high"] = closes[-1] * 1.002                                                    # lower low, green body, strong close
    ind = indicators(b)
    assert bool(signals(ind.assign(rs20_sector=0.02)).iloc[-1]["mr_e4"]) is True
    assert bool(signals(ind.assign(rs20_sector=-0.02)).iloc[-1]["mr_e4"]) is False
    assert bool(signals(ind.assign(rs20_sector=np.nan)).iloc[-1]["mr_e4"]) is False           # no sector → cannot fire
    assert bool(signals(ind.assign(rs20_sector=0.0)).iloc[-1]["mr_e5"]) is True


def test_below_sma20_is_a_downtrend_not_a_dip():
    from nidp.services.tpd_model.mean_reversion import indicators, signals

    down = [100 * 0.995 ** i for i in range(40)]
    closes = down + [down[-1] * f for f in np.cumprod((0.98, 0.975, 0.985))]
    x = signals(indicators(_bars(closes)).assign(rs20_sector=0.1)).iloc[-1]
    assert not any(bool(x[f"mr_e{k}"]) for k in range(1, 6))


def test_cooldown_blocks_five_sessions_per_symbol_and_variant():
    from nidp.services.tpd_model.mean_reversion import apply_cooldown

    df = pd.DataFrame({"symbol": ["X"] * 8 + ["Y"] * 2, "sess_i": [10, 11, 15, 16, 17, 30, 31, 36, 11, 12],
                       "flag": [True, True, True, True, True, True, True, True, True, True]})
    kept = apply_cooldown(df, "flag")
    assert df.loc[kept, "sess_i"].tolist() == [10, 16, 30, 36, 11]                          # 11,15 blocked by 10; 17 by 16; 31 by 30; Y 12 by 11


def test_trade_statistics_profit_factor_drawdown_and_halves():
    from nidp.services.tpd_model.mean_reversion import summarize

    t = pd.DataFrame({"as_of_date": pd.to_datetime(["2025-01-02", "2025-01-02", "2025-01-03", "2025-01-06"]),
                      "symbol": ["A", "B", "A", "C"], "net1": [0.01, -0.02, 0.0, 0.01], "net3": [0.02, -0.01, 0.01, 0.0],
                      "net5": [0.03, -0.01, -0.04, 0.02], "mfe5": [0.05, 0.01, 0.0, 0.03], "mae5": [-0.01, -0.03, -0.05, 0.0]})
    s = summarize(t)
    assert s["trades"] == 4 and s["mean_net"] == pytest.approx(0.0) and s["median_net"] == pytest.approx(0.005)
    assert s["win_rate"] == pytest.approx(0.5) and s["profit_factor"] == pytest.approx(0.05 / 0.05)
    assert s["return_volatility"] == pytest.approx(np.std([0.03, -0.01, -0.04, 0.02], ddof=1))
    # per-date mean net: 0.01, −0.04, 0.02 → cumulative 0.01, −0.03, −0.01 from 0 → peak 0.01, trough −0.03
    assert s["max_drawdown"] == pytest.approx(-0.04)
    assert s["net_by_horizon"] == pytest.approx({"1": 0.0, "3": 0.005, "5": 0.0})


def test_bootstrap_by_date_level_and_seed_are_deterministic():
    from nidp.services.tpd_model.mean_reversion import boot_ci

    rng = np.random.default_rng(0)
    t = pd.DataFrame({"as_of_date": pd.to_datetime("2025-01-01") + pd.to_timedelta(rng.integers(0, 60, 400), "D"), "net5": rng.normal(0.01, 0.02, 400)})
    a, b = boot_ci(t, "net5", 0.95), boot_ci(t, "net5", 0.95)
    wide = boot_ci(t, "net5", 1 - 0.05 / 5)
    assert a == b and a[0] < t["net5"].mean() < a[1] and wide[0] < a[0] and wide[1] > a[1]


def test_matched_baseline_uses_same_day_sector_band_and_volatility_with_a_fallback():
    from nidp.services.tpd_model.mean_reversion import matched_edges

    d = pd.Timestamp("2025-03-03")
    trades = pd.DataFrame({"as_of_date": [d, d, d], "symbol": ["S1", "S2", "S3"], "sector": ["IT", "IT", "Metals"], "band": [1, 1, 2], "atr_q": [3, 3, 1], "net5": [0.02, 0.00, 0.01]})
    pool = pd.DataFrame({"as_of_date": [d] * 7, "sector": ["IT", "IT", "IT", "Pharma", "Pharma", "Pharma", "IT"], "band": [1, 1, 1, 2, 2, 2, 2],
                         "atr_q": [3, 3, 3, 1, 1, 1, 5], "net5": [0.01, 0.0, -0.01, 0.003, 0.006, 0.009, 0.5]})
    e = matched_edges(trades, pool)
    assert e["edge"].tolist() == pytest.approx([0.02, 0.0, 0.004])                          # S3: no Metals cell → date x band x ATR q
    assert e["cell"].tolist() == ["sector", "sector", "fallback"]
    lonely = trades.assign(band=[3, 3, 3])
    assert matched_edges(lonely, pool).empty                                                  # < 3 rows in every cell → left out


def test_dependence_checks():
    from nidp.services.tpd_model.mean_reversion import dependence

    dates = pd.to_datetime("2025-01-01") + pd.to_timedelta(np.arange(40), "D")
    t = pd.DataFrame({"as_of_date": dates, "symbol": [f"S{i % 20}" for i in range(40)], "sector": ["IT"] * 20 + ["Metals"] * 20, "net5": [0.01] * 40})
    ok = dependence(t)
    assert ok["max_symbol_share"] == pytest.approx(0.05) and ok["mean_without_top_sector"] > 0 and ok["mean_without_top5_dates"] > 0
    spike = t.copy(); spike["net5"] = [-0.001] * 35 + [0.2] * 5
    assert dependence(spike)["mean_without_top5_dates"] < 0


def test_verdict_requires_every_criterion():
    from nidp.services.tpd_model.mean_reversion import verdict

    good = {"trades": 250, "mean_net": 0.004, "ci": [0.001, 0.007], "b1_mean": 0.001, "edge_b2": 0.002, "half1_mean": 0.003, "half2_mean": 0.005,
            "b3_edge": 0.002, "b3_ci": [0.0005, 0.004], "max_symbol_share": 0.03, "mean_without_top_sector": 0.003,
            "mean_without_top5_dates": 0.002, "mean_net_extra_slippage": 0.002}
    assert verdict(good)["passed"] is True
    for k, bad in [("trades", 199), ("ci", [-0.001, 0.007]), ("b1_mean", 0.005), ("edge_b2", -0.0001), ("half2_mean", -0.001), ("b3_ci", [-0.001, 0.004]),
                   ("max_symbol_share", 0.11), ("mean_without_top5_dates", -0.0001), ("mean_net_extra_slippage", -0.0001)]:
        v = verdict({**good, k: bad})
        assert v["passed"] is False and v["checks"], k


def test_holdout_guard_runs_once(tmp_path):
    from nidp.services.tpd_model.mean_reversion import HoldoutAlreadyRun, claim_holdout

    lock = tmp_path / "holdout_lock.json"
    claim_holdout(lock, script_sha256="ab" * 32, variants=["mr_e1"])
    rec = json.loads(lock.read_text())
    assert rec["variants"] == ["mr_e1"] and rec["script_sha256"] == "ab" * 32 and rec["claimed_at"]
    with pytest.raises(HoldoutAlreadyRun):
        claim_holdout(lock, script_sha256="ab" * 32, variants=["mr_e1"])
