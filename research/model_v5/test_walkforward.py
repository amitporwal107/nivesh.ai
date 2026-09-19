"""Tests for the development walk-forward helpers on synthetic data only (PREREGISTRATION_P2_P3.md §10 deliverable 2).
run: /app/research/tpd3_forward/venv/bin/python -m pytest -q test_walkforward.py
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset as DS  # noqa: E402
import walkforward as WF  # noqa: E402

CAL = pd.bdate_range("2022-01-03", periods=80)


def synth(n_sym=30, days=CAL[:70], seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for d in days:
        for j in range(n_sym):
            rows.append({"date": d, "symbol": f"S{j:02d}", "industry": f"IND{j % 4}"})
    ds = pd.DataFrame(rows)
    n = len(ds)
    for f in WF.FEATURES:
        ds[f] = rng.normal(size=n)
    ds.loc[rng.random(n) < 0.05, "ret20"] = np.nan
    sig = ds.ret5 + rng.normal(scale=1.0, size=n)
    ds["eligible"] = rng.random(n) > 0.1
    ds["entry_status"] = np.where(rng.random(n) < 0.03, "LOCKED_UPPER_OPEN", "OK")
    ok = ds.entry_status == "OK"
    for lab, thr in (("hit_high_5_1d", 1.5), ("hit_high_5_3d", 1.0), ("hit_high_5_5d", 0.5), ("hit_high_10_5d", 1.5),
                     ("hit_close_5_5d", 1.0), ("hit_close_10_5d", 1.8), ("hit_low_10_5d", 1.6), ("net_pos_5_2", 0.6)):
        ds[lab] = np.where(ok, (sig > thr).astype(float), np.nan)
    ds["hit_low_10_5d"] = np.where(ok, (sig < -1.6).astype(float), np.nan)
    ds["tbs_5_2"] = np.where(ok, np.where(sig > 1.0, "TARGET", np.where(sig < -0.5, "STOP", "EXPIRED")), None)
    ds["tbs_10_4"] = np.where(ok, np.where(sig > 1.6, "TARGET", np.where(sig < -1.0, "STOP", "EXPIRED")), None)
    ds["dir_5_5d"] = np.where(ok, np.where(sig > 0.8, "UP", np.where(sig < -0.8, "DOWN", np.where(rng.random(n) < 0.02, "AMBIGUOUS", "NONE"))), None)
    ret = np.where(ds.tbs_5_2 == "TARGET", 0.045, np.where(ds.tbs_5_2 == "STOP", -0.025, 0.001))
    for c, adj in (("net_ret_5_2", 0.0), ("net_ret_5_2_opt", 0.001), ("net_ret_5_2_cons", -0.002)):
        ds[c] = np.where(ok & ds.eligible, ret + adj, np.nan)
    pos = CAL.get_indexer(ds.date)
    ds["entry_date"] = CAL[pos + 1]
    ds["tbs_5_2_exit_date"] = CAL[pos + 3]
    ds["label_end_date"] = CAL[pos + 5]
    ds["gap_s1"] = rng.normal(scale=0.01, size=n)
    ds["slip_pct"] = 0.1
    ds["mkt_above200"] = 1.0
    return ds


def dev_block_ok(ds):
    """Synthetic dates are in 2022; shift nothing, the dev block allows them."""
    return WF.prepare(ds)


def test_prepare_refuses_rows_outside_the_dev_block():
    ds = synth()
    bad = ds.copy()
    bad.loc[0, "label_end_date"] = pd.Timestamp("2023-01-02")
    with pytest.raises(DS.SealedDataError):
        WF.prepare(bad)
    bad = ds.copy()
    bad.loc[0, "date"] = pd.Timestamp("2022-12-23")
    with pytest.raises(DS.SealedDataError):
        WF.prepare(bad)


def test_fold_embargo_keeps_training_labels_before_the_fold():
    ds = WF.prepare(synth())
    train, valid = WF.fold_masks(ds, CAL, str(CAL[50].date()), str(CAL[60].date()))
    assert ds.loc[train, "date"].max() == CAL[44]
    assert ds.loc[train, "label_end_date"].max() < CAL[50]
    assert ds.loc[valid, "date"].min() == CAL[50] and ds.loc[valid, "date"].max() == CAL[60]
    assert not (train & valid).any()


def test_target_mapping():
    ds = WF.prepare(synth())
    y, ok = WF.target(ds, "tbs_5_2")
    assert set(ds.loc[ok & (y == 1), "tbs_5_2"]) == {"TARGET"}
    assert set(ds.loc[ok & (y == 0), "tbs_5_2"]) == {"STOP", "EXPIRED"}
    assert not ok[~ds.tradable].any()
    y, ok = WF.target(ds, "dir_5_5d")
    assert "AMBIGUOUS" not in set(ds.loc[ok, "dir_5_5d"]) and set(ds.loc[ok & (y == 0), "dir_5_5d"]) == {"DOWN", "NONE"}
    y, ok = WF.target(ds, "up_given_move")
    assert set(ds.loc[ok, "dir_5_5d"]) == {"UP", "DOWN"}
    y, ok = WF.target(ds, "big_move_10_5d")
    assert ((y[ok] == 1) == ((ds.hit_high_10_5d == 1) | (ds.hit_low_10_5d == 1))[ok]).all()


def test_top_k_among_eligible_counts_missed_entries_and_ranks_nan_last():
    raw = synth()
    d0 = raw.date == CAL[10]
    elig_day = raw.index[d0 & raw.eligible]
    target_locked = elig_day[5]
    raw.loc[target_locked, "entry_status"] = "LOCKED_UPPER_OPEN"     # unknown at selection: still pickable
    ds = WF.prepare(raw)
    d0 = ds.date == CAL[10]
    elig_day = ds.index[d0 & ds.eligible]
    target_locked = ds.index[d0 & ds.eligible & (ds.entry_status == "LOCKED_UPPER_OPEN")][0]
    score = pd.Series(0.0, index=ds.index)
    ineligible = ds.index[d0 & ~ds.eligible]
    score[ineligible] = 10.0                                   # never picked: not eligible
    others = [i for i in elig_day if i != target_locked]
    score[others[:4]] = 5.0
    score[target_locked] = 6.0
    elig_day = pd.Index(others[:4] + [target_locked] + others[4:])
    score[elig_day[6]] = np.nan
    picks = WF.top_k_picks(ds, score, d0, WF.SEED)
    assert len(picks) == 5 and set(picks.index) >= set(elig_day[:4]) | {target_locked}
    assert not set(picks.index) & set(ineligible) and elig_day[6] not in picks.index
    assert picks.groupby("date").size().max() <= WF.TOP_K
    again = WF.top_k_picks(ds, score, d0, WF.SEED)
    assert list(picks.index) == list(again.index)
    m = WF.trading_metrics(ds, picks, CAL)
    assert m["picks"] == 5 and m["missed_no_entry"] >= 1 and m["trades"] + m["missed_no_entry"] == 5


def test_trading_metrics_on_known_trades():
    ds = WF.prepare(synth())
    rows = ds.date.isin(CAL[20:30])
    score = pd.Series(np.where(ds.tbs_5_2 == "TARGET", 1.0, 0.0), index=ds.index)
    picks = WF.top_k_picks(ds, score, rows, WF.SEED)
    m = WF.trading_metrics(ds, picks, CAL)
    t = ds.loc[picks.index[picks.tradable]]
    assert m["mean_net"] == pytest.approx(t.net_ret_5_2.mean())
    assert m["target_rate"] == pytest.approx((t.tbs_5_2 == "TARGET").mean())
    assert 0 < m["exposure"] <= 1 and m["max_drawdown"] >= 0
    w, lo = t.net_ret_5_2[t.net_ret_5_2 > 0].sum(), -t.net_ret_5_2[t.net_ret_5_2 < 0].sum()
    assert m["profit_factor"] == (pytest.approx(w / lo) if lo > 0 else m["profit_factor"])


def test_cluster_bootstrap_point_and_identity():
    ds = WF.prepare(synth())
    rows = ds.date.isin(CAL[20:40])
    p = WF.top_k_picks(ds, pd.Series(np.random.default_rng(3).random(len(ds)), index=ds.index), rows, WF.SEED)
    b = WF.cluster_bootstrap(ds, p, reps=500)
    t = ds.loc[p.index[p.tradable]]
    assert b["point"] == pytest.approx(t.net_ret_5_2.mean()) and b["lo95"] <= b["point"] <= b["hi95"]
    same = WF.cluster_bootstrap(ds, p, p, reps=500)
    assert same["point"] == 0 and same["lo95"] == 0 and same["hi95"] == 0


def test_holm_step_down():
    h = WF.holm({"a": 0.001, "b": 0.012, "c": 0.02})
    assert h["a"]["reject_null"] and h["b"]["reject_null"] and h["c"]["reject_null"]
    h = WF.holm({"a": 0.001, "b": 0.03, "c": 0.004})           # thresholds 0.0083, 0.0125, 0.025
    assert h["a"]["reject_null"] and h["c"]["reject_null"] and not h["b"]["reject_null"]
    h = WF.holm({"a": 0.0101, "b": 0.013, "c": 0.02})          # the first fails, so the step-down stops
    assert not any(v["reject_null"] for v in h.values())


def test_prediction_metrics_handles_nan_rule_scores():
    y = np.array([0, 1, 0, 1, 0, 0, 1, 0, 0, 0], float)
    s = np.array([0.1, 0.9, np.nan, 0.8, 0.2, 0.1, 0.7, 0.3, 0.2, np.nan])
    m = WF.prediction_metrics(y, s, probabilistic=False)
    assert m["roc_auc"] == 1.0 and m["precision_top10"] == 1.0 and "brier" not in m


def test_model_scores_smoke_all_models_and_no_leak_of_validation_rows():
    ds = WF.prepare(synth())
    train, valid = WF.fold_masks(ds, CAL, str(CAL[55].date()), str(CAL[69].date()))
    S, fitted = WF.model_scores(ds, CAL, train, valid, np.random.default_rng(WF.SEED), labels=("tbs_5_2", "dir_5_5d"))
    for m in ("M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9"):
        for lab in ("tbs_5_2", "dir_5_5d"):
            s = S[(m, lab)]
            assert list(s.index) == list(ds.index[valid])
            if m in WF.PROBABILISTIC:
                assert s.between(0, 1).all()
    # the signal is learnable: M8 on tbs ranks better than random on the validation rows
    y, ok = WF.target(ds, "tbs_5_2")
    use = ds.index[valid & ok]
    auc = WF.prediction_metrics(y[use].to_numpy(), S[("M8", "tbs_5_2")][use].to_numpy(), True)["roc_auc"]
    assert auc > 0.6
    # validation labels must not influence the fit: scrambling them leaves the scores unchanged
    ds2 = ds.copy()
    ds2.loc[valid, "tbs_5_2"] = np.where(ds2.loc[valid, "tbs_5_2"].notna(), "STOP", None)
    ds2.loc[valid, ["hit_high_10_5d", "hit_low_10_5d"]] = 0.0
    ds2.loc[valid, "dir_5_5d"] = np.where(ds2.loc[valid, "dir_5_5d"].notna(), "DOWN", None)
    S2, _ = WF.model_scores(ds2, CAL, train, valid, np.random.default_rng(WF.SEED), labels=("tbs_5_2",))
    for m in ("M4", "M5", "M6", "M7", "M8", "M9"):
        pd.testing.assert_series_equal(S[(m, "tbs_5_2")], S2[(m, "tbs_5_2")])


def test_purged_oof_predicts_every_usable_row_only():
    ds = WF.prepare(synth())
    rows = ds.date <= CAL[60]
    oof = WF.purged_oof(ds, CAL, rows, "big_move_10_5d")
    _, ok = WF.target(ds, "big_move_10_5d")
    assert oof[rows & ok].notna().all() and oof[~(rows & ok)].isna().all()


def test_a_feature_missing_in_every_training_row_is_dropped_and_logged():
    ds = WF.prepare(synth())
    train, valid = WF.fold_masks(ds, CAL, str(CAL[55].date()), str(CAL[69].date()))
    ds.loc[train, "vol_ratio_250"] = np.nan                     # not yet observable in the training window
    ds.loc[train & (ds.symbol == "S00"), "dist_sma200"] = np.nan  # partly missing: kept
    WF.FIT_LOG.clear()
    S, fitted = WF.model_scores(ds, CAL, train, valid, np.random.default_rng(WF.SEED), labels=("tbs_5_2",))
    assert WF.FIT_LOG and all(cols == ["vol_ratio_250"] for _, cols in WF.FIT_LOG)
    m8 = fitted["M8__tbs_5_2"]
    assert "vol_ratio_250" not in m8.feature_names_in_ and "dist_sma200" in m8.feature_names_in_
    assert S[("M8", "tbs_5_2")].between(0, 1).all() and S[("M7", "tbs_5_2")].between(0, 1).all()
    WF.FIT_LOG.clear()
