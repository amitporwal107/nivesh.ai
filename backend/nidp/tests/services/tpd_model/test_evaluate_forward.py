"""v2 forward verdict (thresholds_lock_v2_forward.json), written before any real snapshot has been graded:
refuses tampered snapshots, ignores rehearsals, NOT_EVALUATED under 60 graded sessions, judges both heads on the
locked bars, p_up10_1d against the frozen baseline on identical rows with a week-block bootstrap."""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from nidp.tests.services.tpd_model.conftest import IST

FIRST = pd.Timestamp("2026-09-16")


def _sessions(n):
    return [d for d in pd.bdate_range(FIRST, periods=n)]


def _write_snapshot(root, D, rng, signal=2.0, rehearsal=False, n_symbols=150):
    from nidp.services.tpd_model.forward import freeze

    x = rng.normal(size=n_symbols)
    up = (x + rng.normal(size=n_symbols) * 1.2 > 2.6).astype(float)
    down = (-x + rng.normal(size=n_symbols) * 1.2 > 2.9).astype(float)
    syms = [f"S{i:03d}" for i in range(n_symbols)]
    p_up = 1 / (1 + np.exp(-(signal * x - 5)))
    p_dn = 1 / (1 + np.exp(-(signal * -x - 5.5)))
    preds = pd.concat([
        pd.DataFrame({"symbol": syms, "head": "p_up10_1d", "p_tpd3": p_up, "p_atr_only": rng.random(n_symbols) * 0.05,
                      "p_own_history_only": rng.random(n_symbols) * 0.03, "p_base_rate": 0.02}),
        pd.DataFrame({"symbol": syms, "head": "p_down10_1d", "p_tpd3": p_dn, "p_atr_only": rng.random(n_symbols) * 0.02,
                      "p_own_history_only": rng.random(n_symbols) * 0.01, "p_base_rate": 0.01}),
    ], ignore_index=True)
    T = D - pd.offsets.BDay(1)
    meta = {"data_as_of": str(T.date()), "target_session": str(D.date()), "fold_month": D.strftime("%Y-%m"),
            "lock_sha256": "c" * 64, "git_sha": "a" * 40}
    base = pd.DataFrame({"symbol": syms, "p_baseline": p_up * (0.9 + 0.2 * rng.random(n_symbols))})
    snap = freeze(root, preds, meta, now=datetime.combine(T.date(), datetime.min.time(), tzinfo=IST) + timedelta(hours=22),
                  rehearsal=rehearsal, extra_files={"baseline_predictions.csv": base.to_csv(index=False).encode()})
    graded = preds.copy()
    graded["y"] = np.nan
    graded.loc[graded["head"] == "p_up10_1d", "y"] = up
    graded.loc[graded["head"] == "p_down10_1d", "y"] = down
    graded["excluded_reason"] = None
    graded.to_csv(snap / "graded.csv", index=False)
    return snap


def _root(tmp_path, n_graded, signal=2.0, rehearsals=0, seed=0):
    rng = np.random.default_rng(seed)
    root = tmp_path / "snapshots"
    for D in _sessions(n_graded):
        _write_snapshot(root, D, rng, signal)
    reh = tmp_path / "rehearsal"
    for D in _sessions(rehearsals):
        _write_snapshot(reh, D, rng, signal, rehearsal=True)
    return root, reh


def test_under_sixty_graded_sessions_is_not_evaluated(tmp_path):
    from nidp.services.tpd_model.evaluate_forward import evaluate_forward

    root, _ = _root(tmp_path, 40)
    v = evaluate_forward(root)
    assert v["status"] == "NOT_EVALUATED" and v["graded_sessions"] == 40 and v["g_valid"] is False


def test_rehearsal_snapshots_are_not_counted(tmp_path):
    from nidp.services.tpd_model.evaluate_forward import evaluate_forward

    root, reh = _root(tmp_path, 3, rehearsals=5)
    v = evaluate_forward(reh)
    assert v["graded_sessions"] == 0 and v["rehearsal_sessions_ignored"] == 5


def test_tampered_snapshot_is_refused(tmp_path):
    from nidp.services.tpd_model.evaluate_forward import evaluate_forward
    from nidp.services.tpd_model.forward import TamperError

    root, _ = _root(tmp_path, 3)
    f = root / "2026-09-17" / "tpd3_predictions.csv"
    f.write_text(f.read_text().replace("p_up10_1d", "p_up10_1d "))
    with pytest.raises(TamperError):
        evaluate_forward(root)


def test_strong_forward_run_passes_both_heads(tmp_path):
    from nidp.services.tpd_model.evaluate_forward import evaluate_forward

    root, _ = _root(tmp_path, 62, signal=2.0)
    v = evaluate_forward(root)
    assert v["status"] == "EVALUATED" and len(v["lock_sha256"]) == 64
    up, dn = v["heads"]["p_up10_1d"], v["heads"]["p_down10_1d"]
    assert up["b3"]["rows_compared"] > 0 and up["b3"]["bootstrap"]["block"] == "week"
    assert up["b3"]["non_inferior"] is True
    assert dn["ship"]["pass"] is True, dn["ship"]
    assert dn["ship"]["checks"]["months_beating_best_comparator"] is True
    assert set(up["calibration"]["checks"]) == {"mean_pred_rel_err", "top_decile_rel_err", "deciles_inside_wilson",
                                                "logloss_below_base_rate", "brier_skill_positive"}
    assert {"n", "events", "base_rate", "auc", "pr_auc", "p5", "p10", "p20"} <= set(up["summary"])
    assert v["missing_sessions"] == [] and "regimes" in v and v["regimes"]["required"] is False


def test_useless_run_fails_ship_and_blocks_exposure(tmp_path):
    from nidp.services.tpd_model.evaluate_forward import evaluate_forward

    root, _ = _root(tmp_path, 62, signal=0.0)
    v = evaluate_forward(root)
    assert v["heads"]["p_down10_1d"]["ship"]["pass"] is False
    assert v["heads"]["p_down10_1d"]["served"] is False
    assert v["exposure_blocked"] is True and v["g_valid"] is False


def test_missing_sessions_in_the_window_are_listed(tmp_path):
    from nidp.services.tpd_model.evaluate_forward import evaluate_forward

    root, _ = _root(tmp_path, 5)
    import shutil
    shutil.rmtree(root / "2026-09-18")
    v = evaluate_forward(root, expected_sessions=[d.date() for d in _sessions(5)])
    assert v["missing_sessions"] == ["2026-09-18"]


def test_qualifying_months_need_fifteen_graded_sessions(tmp_path):
    from nidp.services.tpd_model.evaluate_forward import months_beating

    frame = pd.DataFrame({
        "target_session": pd.to_datetime(["2026-09-16"] * 20 + ["2026-10-01"] * 20 + ["2026-11-02"] * 5),
        "y": ([1.0] + [0.0] * 19) * 2 + [1.0] + [0.0] * 4,
        "p_tpd3": [0.9] + [0.1] * 19 + [0.9] + [0.1] * 19 + [0.9] + [0.1] * 4,
        "p_atr_only": [0.1] * 45, "p_own_history_only": [0.1] * 45,
    })
    frame["target_session"] = frame["target_session"] + pd.to_timedelta(np.tile(np.arange(20), 3)[:45] % 20, unit="D")
    m = months_beating(frame, min_sessions=15)
    assert m["qualifying_months"] == 2 and m["beating"] == 2 and m["skipped_months"] == ["2026-11"]
