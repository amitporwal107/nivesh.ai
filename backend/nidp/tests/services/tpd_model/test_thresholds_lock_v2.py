"""v2 forward-test lock: committed before the first forward session, two 1-day heads, v1 bars adapted to 60 sessions."""
import json
from pathlib import Path

LOCK = Path(__file__).resolve().parents[3] / "services" / "tpd_model" / "thresholds_lock_v2_forward.json"


def _lock():
    return json.loads(LOCK.read_text())


def test_forward_window_and_heads():
    lock = _lock()
    assert lock["version"] == 2.1
    assert lock["heads"] == ["p_up10_1d", "p_down10_1d"]
    assert lock["forward_window"] == {"first_target_session": "2026-09-16", "interim_read_graded_sessions": 60,
                                      "verdict_min_graded_sessions": 250, "evaluate_by": "2027-09-30"}
    assert "before any real session was graded" in lock["amended"]
    assert lock["scoring"]["filings_cutoff"] == "15:30 IST on T"


def test_only_the_market_feature_change():
    assert _lock()["model_changes_vs_v1"] == [
        "mkt_ret1 and breadth computed over the target session's point-in-time universe members instead of every EQ stock"]


def test_bars_keep_v1_numbers_with_window_adaptations():
    lock = _lock()
    b3 = lock["p_up10_1d_vs_fixed_baseline"]
    assert b3["non_inferior"] == {"p5_margin_pp": 0.5, "auc_margin": 0.003}
    assert b3["better"]["bootstrap"]["block"] == "week"
    down = lock["p_down10_1d_ship"]
    assert (down["auc_min"], down["pr_auc_vs_best_comparator_min"], down["p5_vs_base_rate_min"]) == (0.70, 1.25, 3.0)
    assert down["months_beating_best_comparator_auc"] == {"min": 2, "of_qualifying_months": 3, "qualifying_month_min_graded_sessions": 15}
    assert lock["calibration_both_heads"]["top_decile_rel_err_max"] == 0.15
    assert lock["regimes"]["required"] is False
    assert lock["failing_head"] == {"policy": "hide_keep_logging", "block_exposure_if_fails": "p_up10_1d"}
