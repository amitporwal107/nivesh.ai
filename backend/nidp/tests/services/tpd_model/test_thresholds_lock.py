"""NI-4 no-peek gate: the pass bars are a committed file, locked before any walk-forward result exists."""
import json
from pathlib import Path

LOCK = Path(__file__).resolve().parents[3] / "services" / "tpd_model" / "thresholds_lock.json"
HEADS = {"p_up10_1d", "p_down10_1d", "p_up10_5d", "p_down10_5d"}


def _lock():
    return json.loads(LOCK.read_text())


def test_lock_names_all_four_heads_and_a_twelve_month_window():
    lock = _lock()
    assert set(lock["heads"]) == HEADS
    assert lock["oos_window"] == {"first": "2025-09-01", "last": "2026-08-31", "months": 12}


def test_baseline_head_has_non_inferiority_and_better_rules():
    b3 = _lock()["b3_p_up10_1d_vs_fixed_baseline"]
    assert b3["non_inferior"] == {"p5_margin_pp": 0.5, "auc_margin": 0.003}
    assert b3["better"] == {"delta_auc_min": 0.005, "delta_p5_pp_min": 1.0,
                            "bootstrap": {"block": "month", "resamples": 2000, "ci": 0.95, "delta_p5_lower_gt": 0.0}}


def test_other_heads_ship_bar():
    b4 = _lock()["b4_other_heads_ship"]
    assert b4 == {"heads": ["p_down10_1d", "p_up10_5d", "p_down10_5d"], "auc_min": 0.70,
                  "pr_auc_vs_best_comparator_min": 1.25, "p5_vs_base_rate_min": 3.0,
                  "months_beating_best_comparator_auc_min": 9}


def test_calibration_regimes_rollback_and_failing_head_are_locked():
    lock = _lock()
    assert lock["b5_calibration"]["top_decile_rel_err_max"] == 0.15
    assert lock["b6_regimes"]["definition"] == "volatility_x_trend"
    assert lock["b6_regimes"]["cell_min_events"] == 50
    assert lock["live_rollback"]["min_wrote_sessions_per_month"] == 15
    assert lock["failing_head"]["policy"] == "hide_keep_logging"
    assert lock["failing_head"]["block_exposure_if_fails"] == "p_up10_1d"
