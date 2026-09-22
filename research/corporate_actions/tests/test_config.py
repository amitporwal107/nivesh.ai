"""config_hash() is deterministic and changes when the config changes -- mirrors
research/charting/tests' coverage of research.charting.config.config_hash."""
from research.corporate_actions.config import CONFIG, CONFIG_HASH, config_hash


def test_config_hash_is_deterministic():
    assert config_hash(CONFIG) == config_hash(CONFIG)
    assert config_hash(CONFIG) == CONFIG_HASH


def test_config_hash_changes_when_a_value_changes():
    changed = dict(CONFIG)
    changed["regime_break_sessions_before"] = 4
    assert config_hash(changed) != CONFIG_HASH


def test_regime_break_window_is_symmetric_5_sessions_each_side():
    assert CONFIG["regime_break_sessions_before"] == 5
    assert CONFIG["regime_break_sessions_after"] == 5
