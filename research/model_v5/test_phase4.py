"""Tests for the Phase 4 A/B runner on synthetic data only (PREREGISTRATION_P4_AB.md §11 deliverable 3).
run: /app/research/tpd3_forward/venv/bin/python -m pytest -q test_phase4.py
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset as DS  # noqa: E402
import features_p4 as FP  # noqa: E402
import phase4 as P4  # noqa: E402
import walkforward as WF  # noqa: E402

CAL = pd.bdate_range("2021-09-01", "2022-12-30")
SYMS = [f"S{j:02d}" for j in range(24)]


def synth(seed=5, informative_b=True):
    rng = np.random.default_rng(seed)
    days = [d for i, d in enumerate(CAL) if d <= pd.Timestamp("2022-12-22") and i + 5 < len(CAL)]
    ds = pd.DataFrame([(d, s) for d in days for s in SYMS], columns=["date", "symbol"])
    n = len(ds)
    for f in DS.FEATURES:
        ds[f] = rng.normal(size=n)
    hidden = rng.normal(size=n)
    for f in FP.GROUP_A:
        ds[f] = ds.date.map(dict(zip(days, rng.normal(size=len(days)))))
    for f in FP.GROUP_B:
        ds[f] = rng.normal(size=n)
    if informative_b:
        ds["rs_sec20"] = hidden
    sig = 0.5 * ds.ret5 + (1.2 * hidden if informative_b else 0) + rng.normal(size=n)
    ds["industry"] = ds.symbol.map({s: f"IND{i % 4}" for i, s in enumerate(SYMS)})
    ds["eligible"] = True
    ds["entry_status"] = "OK"
    ds["tbs_5_2"] = np.where(sig > 1.0, "TARGET", np.where(sig < -0.3, "STOP", "EXPIRED"))
    ds["dir_5_5d"] = np.where(sig > 0.7, "UP", np.where(sig < -0.7, "DOWN", "NONE"))
    for lab, thr in (("hit_high_10_5d", 1.5), ("hit_low_10_5d", 9.0), ("net_pos_5_2", 0.9)):
        ds[lab] = (sig > thr).astype(float)
    ret = np.where(ds.tbs_5_2 == "TARGET", 0.045, np.where(ds.tbs_5_2 == "STOP", -0.025, 0.003))
    for c, adj in (("net_ret_5_2", 0.0), ("net_ret_5_2_opt", 0.001), ("net_ret_5_2_cons", -0.002)):
        ds[c] = ret + adj
    pos = CAL.get_indexer(ds.date)
    ds["entry_date"], ds["tbs_5_2_exit_date"], ds["label_end_date"] = CAL[pos + 1], CAL[pos + 3], CAL[pos + 5]
    ds["entry_px"] = 100.0
    ds["tbs_5_2_exit_px"] = np.where(ds.tbs_5_2 == "TARGET", 105.0, np.where(ds.tbs_5_2 == "STOP", 98.0, 100.3))
    ds["gap_s1"], ds["slip_pct"], ds["mkt_above200"] = 0.0, 0.1, 1.0
    return WF.prepare(ds)


def synth_bars():
    rows = [(s, d, 100.0, 106.0, 97.0, 100.0, 1e5) for s in SYMS for d in CAL]
    return pd.DataFrame(rows, columns=["symbol", "date", "open", "high", "low", "close", "volume"])


def test_arm_feature_sets_are_the_frozen_ones():
    assert [len(v) for v in P4.ARMS.values()] == [44, 60, 58]
    assert all(len(set(v)) == len(v) for v in P4.ARMS.values())
    assert P4.ARMS["A"][:44] == P4.ARMS["B0"] == list(DS.FEATURES) and P4.ARMS["B"][44:] == list(FP.GROUP_B)


def test_bootstrap_identical_and_better_scores():
    rng = np.random.default_rng(0)
    dates = np.repeat(np.arange(60), 50)
    y = rng.integers(0, 2, len(dates))
    base = rng.random(len(dates))
    same = P4.boot_auc_diff(y, base, base, dates, "roc_auc", reps=200)
    assert same["point"] == 0 and same["lo95"] == 0 and same["p_le_0"] == 1.0
    better = P4.boot_auc_diff(y, y + 0.5 * base, base, dates, "pr_auc", reps=200)
    assert better["lo95"] > 0 and better["p_le_0"] == 0.0


def _holm(a_up=False, a_tbs=False, b_up=False, b_tbs=False):
    return {("A", "up_given_move"): {"reject_null": a_up}, ("A", "tbs_5_2"): {"reject_null": a_tbs},
            ("B", "up_given_move"): {"reject_null": b_up}, ("B", "tbs_5_2"): {"reject_null": b_tbs}}


def test_keep_drop_rule():
    trade = {"B0": {"pooled": -0.006, "folds": [-0.01, -0.005, -0.006, -0.004]},
             "A": {"pooled": -0.005, "folds": [-0.009, -0.004, -0.007, -0.003]},     # 3 of 4 folds not worse
             "B": {"pooled": -0.005, "folds": [-0.011, -0.006, -0.005, -0.003]}}     # 2 of 4
    pr = {"B0": [0.24, 0.24, 0.24, 0.24], "A": [0.25, 0.25, 0.25, 0.235], "B": [0.25, 0.25, 0.25, 0.225]}
    d = P4.decide(_holm(a_up=True, b_tbs=True), trade, pr)
    assert d["A"]["verdict"] == "KEPT" and d["A"]["K2_folds_not_worse"] == 3
    assert d["B"]["verdict"] == "DROPPED" and not d["B"]["K2"] and not d["B"]["K3"]
    assert P4.decide(_holm(), trade, pr)["A"]["verdict"] == "DROPPED"                      # K1 fails
    worse = dict(trade, A={"pooled": -0.007, "folds": [-0.009, -0.004, -0.007, -0.003]})
    assert P4.decide(_holm(a_up=True), worse, pr)["A"]["verdict"] == "DROPPED"             # pooled worse


def test_reproduction_gate(tmp_path):
    ds = synth()
    s = pd.Series(np.random.default_rng(1).random(200), index=ds.index[:200])
    ref = ds.loc[s.index, ["date", "symbol"]].assign(**{"M8|tbs_5_2": s.to_numpy()})
    ref.to_csv(tmp_path / "oof.csv.gz", index=False)
    assert P4.check_reproduction(ds, s, str(tmp_path / "oof.csv.gz")) <= 1e-15          # CSV round-trip: last bit only
    (ref.assign(**{"M8|tbs_5_2": s.to_numpy() + 1e-9})).to_csv(tmp_path / "bad.csv.gz", index=False)
    with pytest.raises(RuntimeError, match="does not reproduce"):
        P4.check_reproduction(ds, s, str(tmp_path / "bad.csv.gz"))
    ref.iloc[:-1].to_csv(tmp_path / "short.csv.gz", index=False)
    with pytest.raises(RuntimeError, match="different rows"):
        P4.check_reproduction(ds, s, str(tmp_path / "short.csv.gz"))


def test_join_refuses_missing_feature_rows():
    ds = synth()
    base = ds.drop(columns=list(FP.GROUP_A) + list(FP.GROUP_B))
    feats = ds[["symbol", "date", *FP.GROUP_A, *FP.GROUP_B]]
    assert list(P4.join_features(base, feats).columns[-30:]) == [*FP.GROUP_A, *FP.GROUP_B]
    with pytest.raises(RuntimeError, match="no Phase 4 feature row"):
        P4.join_features(base, feats.iloc[1:])


def test_audit_flags_a_fill_outside_the_bar():
    ds = synth()
    p = WF.top_k_picks(ds, pd.Series(np.arange(len(ds), dtype=float), index=ds.index), ds.date >= "2022-01-01", 1)
    assert P4.audit_trades(ds, p, synth_bars(), {})["status"] == "CLEAN"
    bad = ds.copy()
    worst = bad.loc[p.index].net_ret_5_2.idxmin()
    bad.loc[worst, "tbs_5_2_exit_px"] = 90.0
    a = P4.audit_trades(bad, p, synth_bars(), {})
    assert a["status"] == "INVALID" and "B exit outside the bar" in a["failures"][0]["issues"]


@pytest.fixture(scope="module")
def run_small():
    ds = synth()
    cal = CAL
    S = {}
    for arm, cols in P4.ARMS.items():
        for label in ("tbs_5_2", "up_given_move", "dir_5_5d"):
            S[(arm, label, "hgb")] = P4.fold_scores(ds, cal, cols, label)
        S[(arm, "tbs_5_2", "logit")] = P4.fold_scores(ds, cal, cols, "tbs_5_2", kind="logit")
    return ds, S, P4.evaluate(ds, cal, S, synth_bars(), {}, auc_reps=100, trade_reps=200)


def test_end_to_end_small_run(run_small):
    ds, S, res = run_small
    assert set(res["decision"]) == {"A", "B"} and all(v["verdict"] in ("KEPT", "DROPPED") for v in res["decision"].values())
    assert all(a["status"] == "CLEAN" for a in res["audit"].values())
    assert all(p.groupby("date").size().max() <= 5 for p in res["_picks"].values())
    for (arm, label, kind), s in S.items():
        assert s.index.isin(ds.index[ds.date >= "2022-01-01"]).all() and s.notna().all()
    assert set(res["k1_holm"]) == {"A|tbs_5_2", "A|up_given_move", "B|tbs_5_2", "B|up_given_move"}


def test_an_informative_group_improves_and_an_uninformative_one_does_not(run_small):
    _, _, res = run_small
    p = res["prediction"]["hgb"]["tbs_5_2"]
    assert p["B"]["pooled_pr_auc"] > p["B0"]["pooled_pr_auc"] + 0.05                     # rs_sec20 carries the hidden signal
    assert res["k1_holm"]["B|tbs_5_2"]["reject_null"]
    assert not res["k1_holm"]["A|tbs_5_2"]["reject_null"]                                   # group A is noise here


def test_fold_scores_ignore_validation_labels():
    ds = synth(informative_b=False)
    a = P4.fold_scores(ds, CAL, P4.ARMS["B"], "tbs_5_2")
    ds2 = ds.copy()
    ds2.loc[ds2.date >= "2022-01-01", "tbs_5_2"] = "STOP"
    ds2.loc[ds2.date >= "2022-01-01", "tbs_5_2"] = np.where(np.arange((ds2.date >= "2022-01-01").sum()) % 3 == 0, "TARGET", "STOP")
    b = P4.fold_scores(ds2, CAL, P4.ARMS["B"], "tbs_5_2")
    q1_end = pd.Timestamp("2022-03-31")
    pd.testing.assert_series_equal(a[ds.loc[a.index, "date"] <= q1_end], b[ds2.loc[b.index, "date"] <= q1_end])


def test_each_arm_is_ranked_by_its_own_score(run_small):
    ds, S, res = run_small
    for arm, p in res["_picks"].items():
        s = S[(arm, "tbs_5_2", "hgb")]
        day = p.date.iloc[0]
        top = s[ds.loc[s.index, "date"] == day].nlargest(5).index
        assert set(p[p.date == day].index) == set(top)


# ---------- groups C and D (PREREGISTRATION_P4_CD.md): the same procedure with its own group set ----------

import features_p4cd as FC  # noqa: E402


def test_cd_arms_are_the_frozen_ones():
    arms = P4.arms_for("cd")
    assert list(arms) == ["B0", "C", "D"] and [len(v) for v in arms.values()] == [44, 55, 51]
    assert arms["C"][44:] == list(FC.GROUP_C) and arms["D"][44:] == list(FC.GROUP_D)
    assert P4.arms_for("ab") == P4.ARMS and tuple(P4.EXPERIMENTS["ab"]["groups"]) == P4.GROUPS


def test_cd_keep_drop_uses_its_own_groups():
    holm = {("C", "up_given_move"): {"reject_null": False}, ("C", "tbs_5_2"): {"reject_null": False},
            ("D", "up_given_move"): {"reject_null": False}, ("D", "tbs_5_2"): {"reject_null": True}}
    trade = {"B0": {"pooled": -0.006, "folds": [-0.01, -0.005, -0.006, -0.004]},
             "C": {"pooled": -0.005, "folds": [-0.009, -0.004, -0.005, -0.003]},
             "D": {"pooled": -0.005, "folds": [-0.009, -0.004, -0.005, -0.003]}}
    pr = {"B0": [0.24] * 4, "C": [0.25] * 4, "D": [0.25] * 4}
    d = P4.decide(holm, trade, pr, groups=("C", "D"))
    assert set(d) == {"C", "D"} and d["C"]["verdict"] == "DROPPED" and d["D"]["verdict"] == "KEPT"


def test_cd_end_to_end_small_run():
    ds = synth(seed=8, informative_b=False)
    rng = np.random.default_rng(80008)          # not synth's seed: that would copy the baseline columns exactly
    hidden = rng.normal(size=len(ds))
    for f in (*FC.GROUP_C, *FC.GROUP_D):
        ds[f] = rng.normal(size=len(ds))
    ds["td_hist_target"] = hidden
    sig = 0.5 * ds.ret5 + 1.2 * hidden + rng.normal(size=len(ds))
    ds["tbs_5_2"] = np.where(sig > 1.0, "TARGET", np.where(sig < -0.3, "STOP", "EXPIRED"))
    ds["dir_5_5d"] = np.where(sig > 0.7, "UP", np.where(sig < -0.7, "DOWN", "NONE"))
    arms = P4.arms_for("cd")
    S = {}
    for arm, cols in arms.items():
        for label in ("tbs_5_2", "up_given_move", "dir_5_5d"):
            S[(arm, label, "hgb")] = P4.fold_scores(ds, CAL, cols, label)
    res = P4.evaluate(ds, CAL, S, synth_bars(), {}, auc_reps=100, trade_reps=200, arms=arms, groups=("C", "D"))
    assert set(res["decision"]) == {"C", "D"} and set(res["_picks"]) == {"B0", "C", "D"}
    assert set(res["k1_holm"]) == {"C|tbs_5_2", "C|up_given_move", "D|tbs_5_2", "D|up_given_move"}
    assert res["k1_holm"]["D|tbs_5_2"]["reject_null"] and not res["k1_holm"]["C|tbs_5_2"]["reject_null"]
