"""W3 report: no evaluation without the committed lock, verdicts follow the lock, regimes are point-in-time,
forward returns follow the locked entry rule (K4)."""
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nidp.tests.services.tpd_model.conftest import make_panel, weekday_sessions

LOCK = Path(__file__).resolve().parents[3] / "services" / "tpd_model" / "thresholds_lock.json"


def test_report_refuses_without_the_lock(tmp_path):
    from nidp.services.tpd_model.report import LockMissingError, load_lock

    with pytest.raises(LockMissingError):
        load_lock(tmp_path / "missing.json")


def test_lock_sha_is_the_file_sha256():
    from nidp.services.tpd_model.report import load_lock

    lock, sha = load_lock(LOCK)
    assert sha == hashlib.sha256(LOCK.read_bytes()).hexdigest() and lock["version"] == 1


def _head_metrics(**over):
    m = {"auc": 0.75, "pr_auc": 0.05, "p5": 0.06, "base_rate": 0.01, "months_auc_beats_best_comparator": 10,
         "comparators": {"atr_only": {"pr_auc": 0.03, "auc": 0.7}, "own_history_only": {"pr_auc": 0.02, "auc": 0.65}}}
    m.update(over)
    return m


def test_b4_verdict_follows_the_lock():
    from nidp.services.tpd_model.report import b4_verdict, load_lock

    lock, _ = load_lock(LOCK)
    assert b4_verdict(_head_metrics(), lock)["pass"] is True
    assert b4_verdict(_head_metrics(auc=0.69), lock)["pass"] is False                 # AUC floor 0.70
    assert b4_verdict(_head_metrics(pr_auc=0.037), lock)["pass"] is False             # < 1.25 x 0.03
    assert b4_verdict(_head_metrics(p5=0.029), lock)["pass"] is False                 # < 3 x base rate
    assert b4_verdict(_head_metrics(months_auc_beats_best_comparator=8), lock)["pass"] is False
    assert b4_verdict(_head_metrics(pr_auc=0.0375), lock)["pass"] is True             # exactly 1.25 x


def test_b3_verdict_non_inferiority_and_better():
    from nidp.services.tpd_model.report import b3_verdict, load_lock

    lock, _ = load_lock(LOCK)
    base = {"auc": 0.800, "p5": 0.148}
    assert b3_verdict({"auc": 0.798, "p5": 0.144}, base, {"ci_lo": -0.01}, lock) == {"non_inferior": True, "better": False}
    assert b3_verdict({"auc": 0.796, "p5": 0.144}, base, {"ci_lo": -0.01}, lock)["non_inferior"] is False
    assert b3_verdict({"auc": 0.806, "p5": 0.159}, base, {"ci_lo": 0.002}, lock) == {"non_inferior": True, "better": True}
    assert b3_verdict({"auc": 0.806, "p5": 0.159}, base, {"ci_lo": -0.001}, lock)["better"] is False


def test_regime_labels_are_point_in_time():
    from nidp.services.tpd_model.report import regime_labels

    s = weekday_sessions("2025-01-01", 200)
    p = make_panel([f"S{i:02d}" for i in range(30)], s)
    members = {d: [f"S{i:02d}" for i in range(30)] for d in s}
    base = regime_labels(p, members, s[60:120])
    fut = p.copy()
    fut.loc[fut["as_of_date"] > pd.Timestamp(s[119]), ["high", "low", "close"]] *= 5
    assert base.equals(regime_labels(fut, members, s[60:120]))
    assert set(base["regime"]) <= {"HIGH_UP", "HIGH_DOWN", "LOW_UP", "LOW_DOWN"}


def test_forward_excess_return_follows_k4():
    """Entry at the target session's open, exit at the close H sessions after T, 0.30% round trip,
    excess over the equal-weight mean of the same measure across the supplied symbols."""
    from nidp.services.tpd_model.report import forward_returns

    s = [pd.Timestamp(d) for d in weekday_sessions("2026-03-02", 8)]
    rows = []
    for sym, opens, closes in (("PICK", [100, 110, 111, 112, 113, 114, 115, 116], [100, 110, 111, 112, 113, 114, 115, 116]),
                               ("OTHR", [100, 100, 100, 100, 100, 100, 100, 100], [100, 101, 102, 103, 104, 105, 106, 107])):
        for d, o, c in zip(s, opens, closes):
            rows.append({"symbol": sym, "as_of_date": d, "open": float(o), "close": float(c)})
    panel = pd.DataFrame(rows)
    fr = forward_returns(panel, T=s[0].date(), symbols=["PICK", "OTHR"], horizons=(1, 5), cost=0.003)
    assert fr.loc["PICK", "ret_1"] == pytest.approx(110 / 110 - 1 - 0.003)
    assert fr.loc["PICK", "ret_5"] == pytest.approx(114 / 110 - 1 - 0.003)
    assert fr.loc["OTHR", "ret_5"] == pytest.approx(105 / 100 - 1 - 0.003)
    assert fr.loc["PICK", "excess_5"] == pytest.approx(fr.loc["PICK", "ret_5"] - fr["ret_5"].mean())


def test_b2_matrix_flags_missing_cells_without_reason():
    from nidp.services.tpd_model.report import missing_cells

    cells = pd.DataFrame([
        {"head": "p_up10_1d", "period": "overall", "model": "tpd3", "metric": "auc", "value": 0.8, "reason": None},
        {"head": "p_up10_1d", "period": "overall", "model": "base_rate", "metric": "auc", "value": np.nan,
         "reason": "constant prediction has no AUC"},
        {"head": "p_up10_1d", "period": "2025-09", "model": "tpd3", "metric": "p5", "value": np.nan, "reason": None},
    ])
    bad = missing_cells(cells)
    assert len(bad) == 1 and bad.iloc[0]["period"] == "2025-09"
