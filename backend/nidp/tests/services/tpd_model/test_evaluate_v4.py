"""v4 early-read evaluation: the pre-registered lock and the high-confidence (>=50%) bin rule."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

LOCK = Path(__file__).resolve().parents[3] / "services" / "tpd_model" / "thresholds_lock_v4_early_window.json"


def test_v4_lock_is_pre_registered_with_the_50pct_rule():
    lock = json.loads(LOCK.read_text())
    assert lock["role"] == "early_read_only" and lock["heads"] == ["p_up10_1d", "p_down10_1d", "p_up5_1d", "p_down5_1d"]
    hc = lock["bars"]["high_confidence_50"]
    assert hc["threshold"] == 0.50 and hc["min_rows_to_judge"] == 30 and "no_peek_disclosure" in lock


def _rows(n, p, hit_rate, seed=1):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"p_tpd3": np.full(n, p), "y": (rng.random(n) < hit_rate).astype(float),
                         "target_session": pd.date_range("2025-01-01", periods=n, freq="D"), "symbol": [f"S{i}" for i in range(n)]})


def test_high_confidence_bin_insufficient_below_min_rows():
    from nidp.services.tpd_model.evaluate_v4 import high_confidence_verdict

    bar = json.loads(LOCK.read_text())["bars"]["high_confidence_50"]
    v = high_confidence_verdict(pd.concat([_rows(29, 0.6, 0.6), _rows(500, 0.05, 0.05, 2)]), bar)
    assert v["rows"] == 29 and v["status"] == "INSUFFICIENT" and v["pass"] is False


def test_high_confidence_bin_calibrated_and_useful():
    from nidp.services.tpd_model.evaluate_v4 import high_confidence_verdict

    bar = json.loads(LOCK.read_text())["bars"]["high_confidence_50"]
    good = pd.concat([_rows(200, 0.55, 0.55), _rows(500, 0.05, 0.05, 2)])
    v = high_confidence_verdict(good, bar)
    assert v["status"] == "JUDGED" and v["calibrated"] and v["useful"] and v["pass"]
    assert v["wilson95"][0] <= v["mean_p"] <= v["wilson95"][1] and v["months_with_rows"] >= 1


def test_high_confidence_bin_overconfident_fails():
    from nidp.services.tpd_model.evaluate_v4 import high_confidence_verdict

    bar = json.loads(LOCK.read_text())["bars"]["high_confidence_50"]
    v = high_confidence_verdict(_rows(300, 0.60, 0.20), bar)
    assert v["status"] == "JUDGED" and not v["calibrated"] and not v["useful"] and not v["pass"]


def test_evaluate_v4_frames_reports_every_head():
    from nidp.services.tpd_model.evaluate_v4 import evaluate_v4_frames

    lock = json.loads(LOCK.read_text())
    parts = []
    rng = np.random.default_rng(5)
    for head, base in (("p_up10_1d", 0.02), ("p_down10_1d", 0.01), ("p_up5_1d", 0.08), ("p_down5_1d", 0.05)):
        n = 6000
        x = rng.normal(size=n); p = 1 / (1 + np.exp(-(np.log(base / (1 - base)) + 1.2 * x)))
        y = (rng.random(n) < p).astype(float)
        parts.append(pd.DataFrame({"head": head, "symbol": [f"S{i%400}" for i in range(n)], "target_session": pd.Timestamp("2025-01-02") + pd.to_timedelta(np.arange(n) // 400, unit="D"),
                                   "month": "2025-01", "y": y, "p_tpd3": p, "p_base_rate": base, "p_atr_only": 1 / (1 + np.exp(-(np.log(base / (1 - base)) + 0.3 * x))), "p_own_history_only": base}))
    out = evaluate_v4_frames(pd.concat(parts, ignore_index=True), lock)
    assert set(out["heads"]) == set(lock["heads"]) and out["status"] == "EARLY_READ" and out["served"] is False
    for h in lock["heads"]:
        e = out["heads"][h]
        assert {"auc", "p5", "base_rate", "best_comparator_auc", "calibration", "high_confidence_50", "ranking_pass"} <= set(e)
