"""Nightly refit challenger (user 2026-09-16: 'for every prediction each day please train the model to improve it').
v4 keeps its locked monthly refit; v4d is the same model refit every night on every label known by T's close, frozen
in its own root under its own lock, and compared with v4 on identical sessions by a pre-registered rule."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from nidp.tests.services.tpd_model.conftest import weekday_sessions


def _rows(sessions):
    return pd.DataFrame({"as_of_date": pd.to_datetime(sessions[:-1]), "target_session": pd.to_datetime(sessions[1:]),
                         "horizon_end_1d": pd.to_datetime(sessions[1:]), "y_p_up5_1d": 0})


def test_daily_fold_trains_on_every_label_that_ended_before_the_target_session():
    from nidp.services.tpd_model.forward import month_fold
    from nidp.services.tpd_model.forward_v4 import daily_fold
    from nidp.services.tpd_model.walkforward import training_rows

    s = weekday_sessions("2026-07-01", 55)
    D = date(2026, 9, 16); T = max(x for x in s if x < D); rows = _rows(s + [D])
    daily = training_rows(rows, daily_fold(s, D), "p_up5_1d")
    monthly = training_rows(rows, month_fold(s, date(2026, 9, 1)), "p_up5_1d")
    assert daily["target_session"].max().date() == T                       # the label for T is known at T's close
    assert monthly["target_session"].max().date() == date(2026, 8, 31)       # monthly stops before the month began
    assert len(daily) - len(monthly) == len([x for x in s if date(2026, 9, 1) <= x <= T])
    assert (rows["target_session"] >= pd.Timestamp(D)).any() and (daily["target_session"] < pd.Timestamp(D)).all()
    f = daily_fold(s, D)
    assert f.first_scored == D and f.last_scored == D and f.month == "2026-09-16"


def test_refit_plan_keeps_v4_monthly_by_default_and_gives_v4d_its_own_lock():
    from nidp.services.tpd_model.forward import month_fold
    from nidp.services.tpd_model.forward_v4 import LOCK_V4, LOCK_V4D, daily_fold, refit_plan

    s = weekday_sessions("2026-07-01", 55)
    D = date(2026, 9, 16)
    fold, lock, model = refit_plan("monthly", s, D)
    assert fold == month_fold(s, date(2026, 9, 1)) and lock == LOCK_V4 and model == "v4"
    fold, lock, model = refit_plan("daily", s, D)
    assert fold == daily_fold(s, D) and lock == LOCK_V4D and model == "v4d"
    with pytest.raises(ValueError):
        refit_plan("weekly", s, D)


def test_cli_default_refit_is_monthly():
    import argparse
    from nidp.services.tpd_model import forward_v4

    seen = {}
    orig = forward_v4.cmd_score
    forward_v4.cmd_score = lambda a: seen.update(refit=a.refit) or 0
    try:
        forward_v4.main(["score", "--exports", "x", "--ca-csv", "x", "--root", "x", "--store-v3", "x", "--live-dir", "x"])
        assert seen["refit"] == "monthly"
        forward_v4.main(["score", "--exports", "x", "--ca-csv", "x", "--root", "x", "--store-v3", "x", "--live-dir", "x", "--refit", "daily"])
        assert seen["refit"] == "daily"
    finally:
        forward_v4.cmd_score = orig


def test_v4d_forward_lock_is_pre_registered():
    from nidp.services.tpd_model.forward_v4 import LOCK_V4D
    from nidp.services.tpd_model.report import load_lock

    lock, sha = load_lock(LOCK_V4D)
    assert lock["role"] == "forward" and lock["model"].startswith("v4d") and len(sha) == 64
    c = lock["comparison_with_v4"]
    assert c["primary_head"] == "p_up5_1d" and c["read_at_paired_sessions"] >= 60 and c["bootstrap"]["resamples"] >= 2000
    assert set(c["outcomes"]) == {"PROMOTE", "KEEP_V4", "INCONCLUSIVE"}
    assert lock["serving"].startswith("nothing served")
    # cmd_score reads these keys for every refit: the challenger lock must carry them itself, not by reference
    v4, _ = load_lock(LOCK_V4D.with_name("thresholds_lock_v4_forward.json"))
    for k in ("threshold", "min_rows_to_judge", "calibrated_if", "useful_if"):
        assert lock["high_confidence"][k] == v4["high_confidence"][k], k
    assert lock["forward_window"]["first_target_session"] == "2026-09-17"


def _graded(sessions, n=20, lift=0.0, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for d in sessions:
        p = rng.uniform(0, 0.4, n)
        y = (rng.uniform(0, 1, n) < p).astype(float)
        for i in range(n):
            rows.append({"head": "p_up5_1d", "symbol": f"S{i}", "target_session": d, "p_tpd3": p[i], "y": y[i]})
    return pd.DataFrame(rows)


def test_refit_verdict_is_paired_on_identical_sessions_and_follows_the_locked_rule():
    from nidp.services.tpd_model.evaluate_v4 import refit_verdict

    rule = {"primary_head": "p_up5_1d", "read_at_paired_sessions": 60, "top_k": 10, "non_inferiority_hits_per_session": -0.25,
            "auc_margin": 0.005, "bootstrap": {"resamples": 2000, "seed": 7},
            "outcomes": {"PROMOTE": "", "KEEP_V4": "", "INCONCLUSIVE": ""}}
    s = pd.bdate_range("2026-09-17", periods=80)
    v4 = _graded(s, seed=1)
    same = refit_verdict(v4, v4.copy(), rule)
    assert same["paired_sessions"] == 80 and same["mean_diff_hits_per_session"] == 0 and same["outcome"] == "PROMOTE"   # identical = non-inferior
    # v4d ranks with noise only: clearly worse top-10 lists
    bad = v4.copy(); bad["p_tpd3"] = np.random.default_rng(3).uniform(0, 1, len(bad))
    assert refit_verdict(v4, bad, rule)["outcome"] == "KEEP_V4"
    # too few paired sessions: no read yet
    early = refit_verdict(v4[v4["target_session"] < s[30]], v4[v4["target_session"] < s[30]], rule)
    assert early["outcome"] == "INCONCLUSIVE" and early["reason"].startswith("fewer than 60")
    # a session present in only one model is dropped, never counted
    one_sided = refit_verdict(v4, v4[v4["target_session"] != s[0]], rule)
    assert one_sided["paired_sessions"] == 79
    # the high-band calibration guard: same ranking, but v4d inflates every probability above 0.30 by +0.25
    guarded = {**rule, "high_band_calibration_guard": {"band_min": 0.30, "min_rows": 100, "max_extra_abs_error": 0.03}}
    inflated = v4.copy(); inflated["p_tpd3"] = np.where(inflated["p_tpd3"] >= 0.30, np.minimum(inflated["p_tpd3"] + 0.25, 0.99), inflated["p_tpd3"])
    r = refit_verdict(v4, inflated, guarded)
    assert r["high_band_calibration"]["judged"] and r["outcome"] == "KEEP_V4" and "calibration" in r["reason"]
    assert refit_verdict(v4, v4.copy(), guarded)["outcome"] == "PROMOTE"
