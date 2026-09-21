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
