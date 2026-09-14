"""W3 evaluation against the lock: B2 cells, B4/B5/B6 verdicts, B3 never silently passes without a baseline."""
import numpy as np
import pandas as pd
import pytest

MONTHS = [f"2025-{m:02d}" for m in (9, 10, 11, 12)] + [f"2026-{m:02d}" for m in range(1, 9)]


def _preds(signal=2.0, seed=0, heads=("p_up10_1d", "p_down10_1d", "p_up10_5d", "p_down10_5d")):
    rng = np.random.default_rng(seed)
    rows = []
    for head in heads:
        for m in MONTHS:
            for day in range(1, 21):
                ts = pd.Timestamp(f"{m}-01") + pd.offsets.BDay(day - 1)
                x = rng.normal(size=120)
                y = (x + rng.normal(size=120) * 1.2 > 2.6).astype(float)
                rows.append(pd.DataFrame({
                    "head": head, "month": m, "symbol": [f"S{i:03d}" for i in range(120)], "target_session": ts,
                    "as_of_date": ts - pd.offsets.BDay(1), "y": y,
                    "p_tpd3": 1 / (1 + np.exp(-(signal * x - 5))), "p_base_rate": y.mean() * 0 + 0.02,
                    "p_atr_only": 1 / (1 + np.exp(-(0.3 * x + rng.normal(size=120) - 4))),
                    "p_own_history_only": rng.random(120) * 0.05,
                }))
    return pd.concat(rows, ignore_index=True)


def test_cells_cover_every_head_period_model_metric():
    from nidp.services.tpd_model.evaluate import metric_cells
    from nidp.services.tpd_model.report import missing_cells

    cells = metric_cells(_preds())
    assert set(cells["period"]) == {"overall", *MONTHS}
    assert set(cells["model"]) == {"tpd3", "base_rate", "atr_only", "own_history_only"}
    assert {"n", "events", "base_rate", "auc", "pr_auc", "p5", "p10", "p20", "recall20", "sessions_top5_hit",
            "brier", "log_loss", "log_loss_base_rate"} <= set(cells["metric"])
    assert missing_cells(cells).empty  # constant base-rate AUC carries a reason
    assert cells.loc[(cells["model"] == "base_rate") & (cells["metric"] == "auc"), "reason"].notna().all()


def test_strong_model_passes_b4_and_calibration_is_judged(tmp_path):
    from nidp.services.tpd_model.evaluate import evaluate

    v = evaluate(_preds(signal=2.0), regimes=None, baseline=None)
    assert v["lock_sha256"] and len(v["lock_sha256"]) == 64
    for head in ("p_down10_1d", "p_up10_5d", "p_down10_5d"):
        assert v["heads"][head]["b4"]["pass"] is True, v["heads"][head]["b4"]
    assert set(v["heads"]["p_up10_1d"]["b5"]["checks"]) == {"mean_pred_rel_err", "top_decile_rel_err",
                                                           "deciles_inside_wilson", "logloss_below_base_rate",
                                                           "brier_skill_positive"}


def test_useless_model_fails_b4():
    from nidp.services.tpd_model.evaluate import evaluate

    v = evaluate(_preds(signal=0.0), regimes=None, baseline=None)
    assert v["heads"]["p_up10_5d"]["b4"]["pass"] is False


def test_b3_is_not_evaluated_without_a_baseline():
    from nidp.services.tpd_model.evaluate import evaluate

    v = evaluate(_preds(), regimes=None, baseline=None)
    b3 = v["heads"]["p_up10_1d"]["b3"]
    assert b3["status"] == "NOT_EVALUATED" and "baseline" in b3["reason"]
    assert v["g_valid"] is False  # nothing ships on an unevaluated baseline head


def test_failing_head_policy_and_exposure_block():
    from nidp.services.tpd_model.evaluate import evaluate

    v = evaluate(_preds(signal=0.0), regimes=None, baseline=None)
    assert v["heads"]["p_up10_5d"]["served"] is False
    assert v["exposure_blocked"] is True


def test_regime_cells_use_the_lock_minimum():
    from nidp.services.tpd_model.evaluate import regime_verdict

    p = _preds(heads=("p_up10_5d",))
    sessions = sorted(p["as_of_date"].unique())
    regimes = pd.DataFrame({"as_of_date": sessions,
                            "regime": ["HIGH_UP" if i % 2 else "LOW_DOWN" for i in range(len(sessions))]})
    r = regime_verdict(p[p["head"] == "p_up10_5d"], regimes)
    assert set(r["cells"]) <= {"HIGH_UP", "HIGH_DOWN", "LOW_UP", "LOW_DOWN"}
    assert all(c["status"] in {"PASS", "FAIL", "INSUFFICIENT"} for c in r["cells"].values())
    assert r["cells"]["HIGH_UP"]["events"] >= 50 and r["cells"]["HIGH_UP"]["status"] != "INSUFFICIENT"
