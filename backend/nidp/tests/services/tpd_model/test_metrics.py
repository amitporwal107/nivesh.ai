"""B2 metric definitions (test-plan §2.4 / K1): pooled precision@k, recall@k, calibration, bootstrap."""
import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import average_precision_score, roc_auc_score


def _frame():
    return pd.DataFrame({
        "target_session": pd.to_datetime(["2025-09-01"] * 4 + ["2025-09-02"] * 3),
        "symbol": ["B", "A", "C", "D", "A", "B", "C"],
        "p": [0.9, 0.9, 0.2, 0.1, 0.5, 0.4, 0.3],
        "y": [0, 1, 1, 0, 0, 1, 0],
    })


def test_precision_at_k_is_pooled_with_symbol_tie_break():
    """Day 1 top-1 = A (0.9, tie with B broken by symbol): hit. Day 2 top-1 = A: miss. 1/2."""
    from nidp.services.tpd_model.metrics import precision_at_k

    assert precision_at_k(_frame(), "p", "y", k=1) == pytest.approx(0.5)
    assert precision_at_k(_frame(), "p", "y", k=2) == pytest.approx(0.5)  # day 1: A, B -> 1; day 2: A, B -> 1


def test_precision_at_k_uses_min_k_eligible():
    """k=5 with 4 and 3 eligible rows: hits 2 + 1 over 4 + 3 slots."""
    from nidp.services.tpd_model.metrics import precision_at_k

    assert precision_at_k(_frame(), "p", "y", k=5) == pytest.approx(3 / 7)


def test_recall_and_session_hit_rate():
    from nidp.services.tpd_model.metrics import recall_at_k, sessions_with_hit

    f = _frame()
    assert recall_at_k(f, "p", "y", k=1) == pytest.approx(1 / 3)  # top-1s are A (hit) and A (miss); 3 events
    assert sessions_with_hit(f, "p", "y", k=1) == pytest.approx(0.5)


def test_auc_and_pr_auc_match_sklearn():
    from nidp.services.tpd_model.metrics import pr_auc, roc_auc

    rng = np.random.default_rng(1)
    y = rng.integers(0, 2, 500)
    p = rng.random(500)
    assert roc_auc(y, p) == pytest.approx(roc_auc_score(y, p), abs=1e-12)
    assert pr_auc(y, p) == pytest.approx(average_precision_score(y, p), abs=1e-12)


def test_wilson_interval_known_value():
    from nidp.services.tpd_model.metrics import wilson

    lo, hi = wilson(10, 100)
    assert (round(lo, 4), round(hi, 4)) == (0.0552, 0.1744)


def test_calibration_has_ten_rank_deciles():
    from nidp.services.tpd_model.metrics import calibration_deciles

    rng = np.random.default_rng(2)
    p = rng.random(1000)
    y = (rng.random(1000) < p).astype(int)
    cal = calibration_deciles(y, p)
    assert len(cal) == 10 and cal["n"].sum() == 1000
    assert {"pred_mean", "obs_rate", "wilson_lo", "wilson_hi"} <= set(cal.columns)
    assert cal["pred_mean"].is_monotonic_increasing


def test_month_block_bootstrap_is_seeded_and_brackets_the_point_estimate():
    from nidp.services.tpd_model.metrics import bootstrap_delta_p5

    rng = np.random.default_rng(3)
    rows = []
    for m in range(1, 13):
        for d in range(1, 6):
            for s in range(30):
                y = int(rng.random() < 0.05)
                rows.append({"target_session": pd.Timestamp(2026, m, d), "symbol": f"S{s:02d}", "y": y,
                             "p_new": y * 0.5 + rng.random() * 0.6, "p_old": rng.random()})
    f = pd.DataFrame(rows)
    a = bootstrap_delta_p5(f, "p_new", "p_old", "y", resamples=300, seed=7)
    b = bootstrap_delta_p5(f, "p_new", "p_old", "y", resamples=300, seed=7)
    assert a == b
    assert a["ci_lo"] <= a["delta"] <= a["ci_hi"]
