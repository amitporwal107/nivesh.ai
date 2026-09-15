"""v2 forward test mechanics (thresholds_lock_v2_forward.json): frozen snapshots before the open, tamper refusal,
grading only once the target session's bars exist, stale-data refusal, monthly training with the purge."""
import json
from datetime import date, datetime, time

import numpy as np
import pandas as pd
import pytest

from nidp.tests.services.tpd_model.conftest import IST, make_panel, weekday_sessions

T, D = date(2026, 9, 15), date(2026, 9, 16)


def _preds():
    return pd.DataFrame({"symbol": ["AAA", "BBB"], "head": ["p_up10_1d", "p_up10_1d"], "p_tpd3": [0.12, 0.03],
                         "p_atr_only": [0.02, 0.01], "p_own_history_only": [0.01, 0.01], "p_base_rate": [0.01, 0.01]})


def _meta():
    return {"data_as_of": str(T), "target_session": str(D), "fold_month": "2026-09", "lock_sha256": "c" * 64,
            "git_sha": "a" * 40}


def test_freeze_writes_predictions_and_a_matching_manifest(tmp_path):
    import hashlib
    from nidp.services.tpd_model.forward import freeze

    snap = freeze(tmp_path, _preds(), _meta(), now=datetime(2026, 9, 15, 22, 30, tzinfo=IST))
    manifest = json.loads((snap / "manifest.json").read_text())
    body = (snap / "tpd3_predictions.csv").read_bytes()
    assert manifest["sha256"] == hashlib.sha256(body).hexdigest()
    assert manifest["target_session"] == str(D) and manifest["rows"] == 2 and manifest["rehearsal"] is False
    assert {"lock_sha256", "git_sha", "fold_month", "data_as_of", "generated_at"} <= set(manifest)


def test_freeze_never_overwrites(tmp_path):
    from nidp.services.tpd_model.forward import freeze

    now = datetime(2026, 9, 15, 22, 30, tzinfo=IST)
    freeze(tmp_path, _preds(), _meta(), now=now)
    with pytest.raises(FileExistsError):
        freeze(tmp_path, _preds(), _meta(), now=now)


def test_freeze_refuses_once_the_target_session_has_opened(tmp_path):
    from nidp.services.tpd_model.forward import LateSnapshotError, freeze

    with pytest.raises(LateSnapshotError):
        freeze(tmp_path, _preds(), _meta(), now=datetime(2026, 9, 16, 9, 15, tzinfo=IST))
    assert not (tmp_path / str(D)).exists()


def test_rehearsal_snapshots_are_marked_and_ignore_the_deadline(tmp_path):
    from nidp.services.tpd_model.forward import freeze

    snap = freeze(tmp_path, _preds(), _meta(), now=datetime(2026, 9, 20, 12, 0, tzinfo=IST), rehearsal=True)
    assert json.loads((snap / "manifest.json").read_text())["rehearsal"] is True


def test_verify_refuses_an_edited_snapshot(tmp_path):
    from nidp.services.tpd_model.forward import TamperError, freeze, verify

    snap = freeze(tmp_path, _preds(), _meta(), now=datetime(2026, 9, 15, 22, 30, tzinfo=IST))
    verify(snap)
    (snap / "tpd3_predictions.csv").write_text((snap / "tpd3_predictions.csv").read_text().replace("0.12", "0.50"))
    with pytest.raises(TamperError):
        verify(snap)


def _panel_with_target(include_target: bool):
    s = weekday_sessions("2026-06-01", 76)                     # ends 2026-09-14 -> add T and D by hand
    p = make_panel(["AAA", "BBB"], s)
    extra = []
    for sym, (c, h, l) in {"AAA": (100.0, 100.0, 100.0), "BBB": (50.0, 50.0, 50.0)}.items():
        extra.append({"symbol": sym, "as_of_date": pd.Timestamp(T), "series": "EQ", "source": "NSE_BHAVCOPY", "open": c,
                      "high": h, "low": l, "close": c, "prev_close": c, "volume": 1000, "turnover": 1e5, "deliverable_pct": 50.0})
    if include_target:
        extra.append({**extra[0], "as_of_date": pd.Timestamp(D), "high": 110.0, "low": 99.0, "close": 105.0})
        extra.append({**extra[1], "as_of_date": pd.Timestamp(D), "high": 51.0, "low": 44.0, "close": 45.0})
    return pd.concat([p, pd.DataFrame(extra)], ignore_index=True)


def test_grade_labels_only_after_the_target_session_exists(tmp_path):
    from nidp.services.tpd_model.forward import freeze, grade

    preds = pd.concat([_preds(), _preds().assign(head="p_down10_1d")], ignore_index=True)
    snap = freeze(tmp_path, preds, _meta(), now=datetime(2026, 9, 15, 22, 30, tzinfo=IST))
    no_actions = pd.DataFrame(columns=["symbol", "ex_date"])
    assert grade(snap, _panel_with_target(False), no_actions) is None
    graded = grade(snap, _panel_with_target(True), no_actions).set_index(["head", "symbol"])
    assert graded.loc[("p_up10_1d", "AAA"), "y"] == 1.0      # 110.00 is exactly +10% on 100.00
    assert graded.loc[("p_up10_1d", "BBB"), "y"] == 0.0
    assert graded.loc[("p_down10_1d", "BBB"), "y"] == 1.0    # 44.00 <= 45.00 (-12%)
    assert (snap / "graded.csv").exists()


def test_grade_refuses_a_tampered_snapshot(tmp_path):
    from nidp.services.tpd_model.forward import TamperError, freeze, grade

    snap = freeze(tmp_path, _preds(), _meta(), now=datetime(2026, 9, 15, 22, 30, tzinfo=IST))
    (snap / "manifest.json").write_text((snap / "manifest.json").read_text().replace('"rows": 2', '"rows": 3'))
    with pytest.raises(TamperError):
        grade(snap, _panel_with_target(True), pd.DataFrame(columns=["symbol", "ex_date"]))


def test_stale_or_thin_data_is_refused():
    from nidp.services.tpd_model.forward import StaleDataError, check_fresh

    s = weekday_sessions("2026-01-01", 180)
    p = make_panel([f"S{i:02d}" for i in range(20)], s)
    check_fresh(p, expected_T=s[-1])
    with pytest.raises(StaleDataError, match="latest session"):
        check_fresh(p[p["as_of_date"] < pd.Timestamp(s[-1])], expected_T=s[-1])
    thin = p[~((p["as_of_date"] == pd.Timestamp(s[-1])) & (p["symbol"] >= "S05"))]
    with pytest.raises(StaleDataError, match="rows"):
        check_fresh(thin, expected_T=s[-1])


def test_month_fold_purges_labels_that_reach_into_the_month():
    from nidp.services.tpd_model.forward import month_fold

    known = [d.date() for d in pd.bdate_range("2024-06-03", "2026-09-15")]
    fold = month_fold(known, month_first_session=date(2026, 9, 1))
    assert fold.month == "2026-09" and fold.first_scored == date(2026, 9, 1)
    assert fold.train_start == date(2025, 3, 3)                # first session on/after 2026-09-01 minus 18 months


def test_freeze_includes_extra_files_in_the_manifest_and_verify_checks_them(tmp_path):
    """The fixed baseline's forward predictions are frozen in the same snapshot (lock v2: same sessions)."""
    import hashlib
    from nidp.services.tpd_model.forward import TamperError, freeze, verify

    extra = {"baseline_predictions.csv": b"symbol,p_baseline\nAAA,0.11\nBBB,0.02\n"}
    snap = freeze(tmp_path, _preds(), _meta(), now=datetime(2026, 9, 15, 22, 30, tzinfo=IST), extra_files=extra)
    manifest = verify(snap)
    assert manifest["files"]["baseline_predictions.csv"] == hashlib.sha256(extra["baseline_predictions.csv"]).hexdigest()
    (snap / "baseline_predictions.csv").write_bytes(b"symbol,p_baseline\nAAA,0.99\nBBB,0.02\n")
    with pytest.raises(TamperError):
        verify(snap)


# ── v3 alongside v2 (user scope change 2026-09-15; lock v3 early: "v3 runs alongside v2 in the forward test") ──

def _preds_v3():
    return _preds().assign(p_tpd3=[0.20, 0.01])


def test_freeze_can_carry_v3_predictions_as_a_hashed_extra_file(tmp_path):
    from nidp.services.tpd_model.forward import V3_FILE, freeze, verify

    snap = freeze(tmp_path, _preds(), _meta(), now=datetime(2026, 9, 15, 22, 30, tzinfo=IST),
                  extra_files={V3_FILE: _preds_v3().to_csv(index=False).encode()})
    assert V3_FILE == "tpd3_v3_predictions.csv" and V3_FILE in verify(snap)["files"]


def test_grade_also_grades_the_v3_file_with_the_same_labels(tmp_path):
    from nidp.services.tpd_model.forward import V3_FILE, freeze, grade

    preds = pd.concat([_preds(), _preds().assign(head="p_down10_1d")], ignore_index=True)
    v3 = preds.assign(p_tpd3=preds["p_tpd3"] * 2)
    snap = freeze(tmp_path, preds, _meta(), now=datetime(2026, 9, 15, 22, 30, tzinfo=IST),
                  extra_files={V3_FILE: v3.to_csv(index=False).encode()})
    no_actions = pd.DataFrame(columns=["symbol", "ex_date"])
    grade(snap, _panel_with_target(True), no_actions)
    g2 = pd.read_csv(snap / "graded.csv").set_index(["head", "symbol"])
    g3 = pd.read_csv(snap / "graded_v3.csv").set_index(["head", "symbol"])
    assert g3["y"].equals(g2["y"]) and g3.loc[("p_up10_1d", "AAA"), "y"] == 1.0
    assert g3.loc[("p_up10_1d", "AAA"), "p_tpd3"] == pytest.approx(0.24)


def test_grade_without_a_v3_file_writes_no_v3_grades(tmp_path):
    from nidp.services.tpd_model.forward import freeze, grade

    snap = freeze(tmp_path, _preds(), _meta(), now=datetime(2026, 9, 15, 22, 30, tzinfo=IST))
    grade(snap, _panel_with_target(True), pd.DataFrame(columns=["symbol", "ex_date"]))
    assert (snap / "graded.csv").exists() and not (snap / "graded_v3.csv").exists()


def test_v3_bundle_trains_on_v3_columns(panel, sessions):
    """train_bundle(columns=MODEL_COLUMNS_V3) fits on the wider input set; the v2 default is unchanged."""
    from nidp.services.tpd_model.design import MODEL_COLUMNS, MODEL_COLUMNS_V3
    from nidp.services.tpd_model.forward import Fold, train_bundle

    rng = np.random.default_rng(2)
    s = [pd.Timestamp(d) for d in sessions[:120]]
    rows = []
    for i, T in enumerate(s[:-6]):
        for k in range(30):
            x = rng.normal()
            rows.append({"symbol": f"S{k:02d}", "as_of_date": T, "target_session": s[i + 1], "horizon_end_1d": s[i + 1],
                         "horizon_end_5d": s[i + 5], "nbars": 200.0, "atr_pct": 2 + abs(x), "bb_width": 0.1,
                         "dist_52w_low": 10.0, "turn_med20": 1e7, "close_raw": 100.0, "n_high_up_252": 1.0, "n_low_down_252": 1.0,
                         **{c: float(rng.normal()) for c in MODEL_COLUMNS_V3 if not c.startswith(("log_", "lr_"))},
                         "y_p_up10_1d": float(x > 1.6), "y_p_down10_1d": float(x < -1.6)})
    frame = pd.DataFrame(rows)
    fold = Fold("m", s[0].date(), s[100].date(), s[-1].date())
    b2 = train_bundle(frame, fold)
    b3 = train_bundle(frame, fold, columns=MODEL_COLUMNS_V3)
    assert b2["models"]["p_up10_1d"]["gbm"].n_features_in_ == len(MODEL_COLUMNS)
    assert b3["models"]["p_up10_1d"]["gbm"].n_features_in_ == len(MODEL_COLUMNS_V3)
    assert b3["columns"] == list(MODEL_COLUMNS_V3)
