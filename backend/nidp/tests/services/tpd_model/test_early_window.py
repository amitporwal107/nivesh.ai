"""Early-read lock (Jun-Aug 2025) and the frame-level evaluation it shares with the forward verdict."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

LOCK = Path(__file__).resolve().parents[3] / "services" / "tpd_model" / "thresholds_lock_v2_early_window.json"


def test_early_lock_is_pre_registered_and_informational():
    lock = json.loads(LOCK.read_text())
    assert lock["role"] == "early_read_only" and lock["locked_at"] == "2026-09-15"
    assert lock["window"] == {"first_target_session": "2025-06-02", "last_target_session": "2025-08-29", "min_graded_sessions": 60}
    assert lock["retrain"]["folds"] == ["2025-06", "2025-07", "2025-08"]
    assert lock["p_up10_1d_vs_fixed_baseline"]["non_inferior"] == {"p5_margin_pp": 0.5, "auc_margin": 0.003}
    assert lock["p_down10_1d_ship"]["months_beating_best_comparator_auc"]["min"] == 2
    assert lock["regimes"]["required"] is False and "cannot be resolved" in lock["power_caveat"]


def _frames(n_sessions, signal, seed=0, first="2025-06-02"):
    rng = np.random.default_rng(seed)
    sessions = pd.bdate_range(first, periods=n_sessions)
    rows, bases = [], []
    for D in sessions:
        x = rng.normal(size=120)
        syms = [f"S{i:03d}" for i in range(120)]
        up = (x + rng.normal(size=120) * 1.2 > 2.6).astype(float)
        down = (-x + rng.normal(size=120) * 1.2 > 2.9).astype(float)
        p_up = 1 / (1 + np.exp(-(signal * x - 5)))
        for head, p, y, base in (("p_up10_1d", p_up, up, 0.02), ("p_down10_1d", 1 / (1 + np.exp(-(signal * -x - 5.5))), down, 0.01)):
            rows.append(pd.DataFrame({"symbol": syms, "head": head, "target_session": D, "as_of_date": D - pd.offsets.BDay(1),
                                      "y": y, "p_tpd3": p, "p_atr_only": rng.random(120) * 0.05,
                                      "p_own_history_only": rng.random(120) * 0.03, "p_base_rate": base}))
        # A clearly weaker baseline: on ~63 sessions a near-equal one flips non-inferiority by noise (the lock's caveat).
        bases.append(pd.DataFrame({"symbol": syms, "target_session": D, "p_baseline": rng.random(120) * 0.05}))
    return pd.concat(rows, ignore_index=True), pd.concat(bases, ignore_index=True)


def test_evaluate_frames_early_read_reports_without_serving():
    from nidp.services.tpd_model.evaluate_forward import evaluate_frames

    graded, base = _frames(63, signal=2.0)
    v = evaluate_frames(graded, base, lock_path=LOCK)
    assert v["status"] == "EARLY_READ" and v["graded_sessions"] == 63 and len(v["lock_sha256"]) == 64
    assert set(v["heads"]) == {"p_up10_1d", "p_down10_1d"}
    up, dn = v["heads"]["p_up10_1d"], v["heads"]["p_down10_1d"]
    assert up["b3"]["non_inferior"] is True and up["b3"]["bootstrap"]["block"] == "week"
    assert dn["ship"]["pass"] is True
    assert all(h["served"] is False for h in v["heads"].values())
    assert v["g_valid"] is False and v["exposure_blocked"] is True


def test_evaluate_frames_early_read_needs_the_whole_window():
    from nidp.services.tpd_model.evaluate_forward import evaluate_frames

    graded, base = _frames(40, signal=2.0)
    v = evaluate_frames(graded, base, lock_path=LOCK)
    assert v["status"] == "NOT_EVALUATED" and v["heads"] == {}


def test_forward_verdict_still_uses_evaluate_frames(tmp_path):
    """The snapshot-based verdict and the early read share one evaluation path."""
    from nidp.services.tpd_model import evaluate_forward as ef

    assert ef.evaluate_forward.__code__.co_names.__contains__("evaluate_frames")
