"""B1 walk-forward protocol: monthly folds, growing window capped at 18 months, K2 label-horizon purge."""
from datetime import date

import numpy as np
import pandas as pd
import pytest


def _sessions():
    return [d.date() for d in pd.bdate_range("2024-06-03", "2026-09-11")]


def test_twelve_monthly_folds_over_the_locked_window():
    from nidp.services.tpd_model.walkforward import month_folds

    folds = month_folds(_sessions(), first=date(2025, 9, 1), last=date(2026, 8, 31), cap_months=18)
    assert [f.month for f in folds] == [f"{y}-{m:02d}" for y, m in
                                        [(2025, 9), (2025, 10), (2025, 11), (2025, 12)] + [(2026, m) for m in range(1, 9)]]
    for f in folds:
        assert f.first_scored.strftime("%Y-%m") == f.month and f.last_scored.strftime("%Y-%m") == f.month
        assert pd.Timestamp(f.train_start) >= pd.Timestamp(f.first_scored) - pd.DateOffset(months=18)


def test_window_grows_until_the_cap():
    from nidp.services.tpd_model.walkforward import month_folds

    folds = month_folds(_sessions(), first=date(2025, 9, 1), last=date(2026, 8, 31), cap_months=18)
    assert folds[0].train_start == date(2024, 6, 3)   # data start, less than 18 months back
    assert folds[-1].train_start == date(2025, 2, 3)  # first session on/after 2026-08-03 minus 18 months


def _rows():
    s = [pd.Timestamp(d) for d in pd.bdate_range("2025-07-01", "2025-09-30")]
    rows = []
    for i, t in enumerate(s[:-6]):
        rows.append({"symbol": "A", "as_of_date": t, "target_session": s[i + 1], "horizon_end_1d": s[i + 1],
                     "horizon_end_5d": s[i + 5], "y_p_up10_1d": float(i % 7 == 0), "y_p_up10_5d": float(i % 5 == 0)})
    return pd.DataFrame(rows)


def test_training_rows_end_before_the_scored_month_k2():
    """A 5D row whose five-session horizon reaches into the scored month would teach the model about
    sessions it is about to be scored on."""
    from nidp.services.tpd_model.walkforward import Fold, training_rows

    r = _rows()
    fold = Fold("2025-09", date(2025, 7, 1), date(2025, 9, 1), date(2025, 9, 30))
    tr1 = training_rows(r, fold, "p_up10_1d")
    tr5 = training_rows(r, fold, "p_up10_5d")
    assert (tr1["horizon_end_1d"] < pd.Timestamp("2025-09-01")).all()
    assert (tr5["horizon_end_5d"] < pd.Timestamp("2025-09-01")).all()
    assert len(tr5) < len(tr1)  # the purge actually removed rows


def test_unlabelled_rows_are_dropped_never_counted_as_no_event():
    from nidp.services.tpd_model.walkforward import Fold, training_rows

    r = _rows()
    r.loc[3, "y_p_up10_1d"] = np.nan
    fold = Fold("2025-09", date(2025, 7, 1), date(2025, 9, 1), date(2025, 9, 30))
    tr = training_rows(r, fold, "p_up10_1d")
    assert tr["y_p_up10_1d"].notna().all() and r.loc[3, "as_of_date"] not in set(tr["as_of_date"])


def test_scored_rows_are_the_fold_month_by_target_session():
    from nidp.services.tpd_model.walkforward import Fold, scored_rows

    r = _rows()
    fold = Fold("2025-09", date(2025, 7, 1), date(2025, 9, 1), date(2025, 9, 30))
    sc = scored_rows(r, fold)
    assert sc["target_session"].dt.strftime("%Y-%m").eq("2025-09").all() and len(sc) > 0


def test_model_fit_is_deterministic():
    from nidp.services.tpd_model.walkforward import fit_gbm

    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(600, 5)), columns=list("abcde"))
    y = (X["a"] + rng.normal(size=600) > 1.5).astype(int)
    p1 = fit_gbm(X, y).predict_proba(X)[:, 1]
    p2 = fit_gbm(X, y).predict_proba(X)[:, 1]
    assert (p1.view(np.uint64) == p2.view(np.uint64)).all()


@pytest.mark.parametrize("head,own", [("p_up10_1d", "n_high_up_252"), ("p_down10_1d", "n_low_down_252"),
                                      ("p_up10_5d", "n_high_up_252"), ("p_down10_5d", "n_low_down_252")])
def test_own_history_comparator_uses_the_heads_direction(head, own):
    from nidp.services.tpd_model.design import OWN_HISTORY_COUNT

    assert OWN_HISTORY_COUNT[head] == own
