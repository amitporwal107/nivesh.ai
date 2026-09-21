from research.charting.config import CONFIG, config_hash, relative_volume_band


def test_config_hash_is_stable_and_order_independent():
    shuffled = dict(reversed(list(CONFIG.items())))
    assert config_hash(CONFIG) == config_hash(shuffled)
    assert len(config_hash()) == 64


def test_config_hash_changes_when_a_value_changes():
    changed = dict(CONFIG, breakout_buffer_atr=0.30)
    assert config_hash(changed) != config_hash(CONFIG)


def test_failure_buffer_equals_breakout_buffer():
    # §30.1: equal on purpose, so a bar cannot be both a valid breakout and a valid failure.
    assert CONFIG["failure_buffer_atr"] == CONFIG["breakout_buffer_atr"]


def test_relative_volume_bands_are_half_open_at_every_edge():
    assert relative_volume_band(0.7999) == "WEAK"
    assert relative_volume_band(0.80) == "NORMAL"
    assert relative_volume_band(1.1999) == "NORMAL"
    assert relative_volume_band(1.20) == "SUPPORTING"
    assert relative_volume_band(1.4999) == "SUPPORTING"
    assert relative_volume_band(1.50) == "STRONG"


def test_early_score_weights_sum_to_one_and_match_prd_34_5():
    w = CONFIG["early_score_weights"]
    assert abs(sum(w.values()) - 1.0) < 1e-12
    assert w == {"structural_quality": 0.25, "volatility_compression": 0.20, "distance_to_trigger": 0.15,
                 "volume_behaviour": 0.15, "momentum_relative_strength": 0.15, "market_sector_context": 0.10}
    assert CONFIG["early_maturity_checkpoints"] == [0.2, 0.4, 0.6, 0.8]


def test_early_module_tunables_come_from_config_and_change_the_hash():
    """Review 2026-09-22: ~20 early-formation tunables lived as module constants, so changing one would not have
    changed config_hash. They now live in CONFIG["early_params"]; this pins that the modules read them from there."""
    from research.charting.early import indicators as ind, scoring as sc
    ep = CONFIG["early_params"]
    assert (sc._SHORT_RANGE_PERIOD, sc._LONG_RANGE_PERIOD, sc._VOLUME_BASELINE_BARS) == (
        ep["short_range_period"], ep["long_range_period"], ep["volume_baseline_bars"])
    assert (sc._MOMENTUM_K, sc._MOMENTUM_RSI_PERIOD, sc._MOMENTUM_MACD_FAST, sc._MOMENTUM_MACD_SLOW,
            sc._MOMENTUM_MACD_SIGNAL) == (ep["momentum_k"], ep["momentum_rsi_period"], ep["momentum_macd_fast"],
                                           ep["momentum_macd_slow"], ep["momentum_macd_signal"])
    assert (sc._READINESS_TREND_BARS, sc._READINESS_SLOPE_SCALE) == (ep["readiness_trend_bars"], ep["readiness_slope_scale"])
    assert (sc._MARKET_CONTEXT_LOOKBACK_BARS, sc._MARKET_CONTEXT_RETURN_SCALE) == (
        ep["market_context_lookback_bars"], ep["market_context_return_scale"])
    assert sc._STRUCTURAL_SUBWEIGHTS == ep["structural_subweights"]
    assert sc._DISTANCE_SCALE_ATR == ep["distance_scale_atr"]
    assert [sc._BLEND_PRIMARY, sc._BLEND_SECONDARY] == ep["component_blend"]
    assert [sc._FAILURE_PROXIMITY_WEIGHT, sc._FAILURE_EXPANSION_WEIGHT] == ep["failure_risk_blend"]
    assert (ind.BB_PERIOD, ind.BB_PCTILE_LOOKBACK, ind.VOLUME_TREND_BARS, ind._VOLUME_SLOPE_SCALE,
            ind.FAILED_BREAKOUT_BUFFER_ATR, ind.FAILED_BREAKOUT_SATURATION) == (
        ep["bb_period"], ep["bb_pctile_lookback"], ep["volume_trend_bars"], ep["volume_slope_scale"],
        ep["failed_breakout_buffer_atr"], ep["failed_breakout_saturation"])
    assert abs(sum(ep["structural_subweights"].values()) - 1.0) < 1e-12
    changed = dict(CONFIG, early_params=dict(ep, distance_scale_atr=4.0))
    assert config_hash(changed) != config_hash(CONFIG)
