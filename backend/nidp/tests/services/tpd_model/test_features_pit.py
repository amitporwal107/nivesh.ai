"""A3 future perturbation (feature level), B8 unproven-feature denylist, C6 logged vectors + TECH-3 delivery lag.

Bitwise rule (test-plan §1c): float64 compared via uint64 views with identical NaN masks — no tolerance.
Retrain-and-rescore perturbation belongs to the walk-forward tests (W3).
"""
import re

import numpy as np
import pandas as pd
import pytest

from nidp.tests.services.tpd_model.conftest import IST, NOT_IMPLEMENTED, ist

pytestmark = NOT_IMPLEMENTED

DENYLIST = re.compile(r"fund|(^|_)pat(_|$)|eps|revenue|profit|roe|debt|sector|industry|news|categor|"
                      r"shareholding|pledge|promoter", re.I)


def _bitwise_equal(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    a, b = a.sort_index(), b.sort_index()
    if list(a.columns) != list(b.columns) or list(a.index) != list(b.index):
        return False
    x, y = a.to_numpy(np.float64), b.to_numpy(np.float64)
    return bool((np.isnan(x) == np.isnan(y)).all() and (x.view(np.uint64) == y.view(np.uint64)).all())


def _events(sessions, T):
    D = sessions[sessions.index(T) + 1]
    return pd.DataFrame([
        {"symbol": "SYM001", "event_date": pd.Timestamp(D), "intimated_at": ist(T, 11, 0)},
    ])


@pytest.mark.parametrize("idx", [150, 205, 299])  # early, mid, last session of the panel
def test_future_perturbation_is_bit_identical(panel, sessions, idx):
    from nidp.services.tpd_model.features import compute_features

    T = sessions[idx]
    events = _events(sessions, T) if idx < 299 else None
    base = compute_features(panel, T, events=events)

    future = panel.copy()
    later = future["as_of_date"] > pd.Timestamp(T)
    future.loc[later, ["open", "high", "low", "close", "prev_close"]] *= 3.0
    future.loc[later, "volume"] *= 50
    future = future.drop(future[later & (future["symbol"] == "SYM005")].index)
    perturbed_events = events
    if events is not None:
        leak = pd.DataFrame([{"symbol": "SYM002", "event_date": events["event_date"].iloc[0],
                              "intimated_at": ist(T, 15, 30, 1)}])
        perturbed_events = pd.concat([events, leak], ignore_index=True)

    assert _bitwise_equal(base, compute_features(future, T, events=perturbed_events))


def test_changing_a_bar_on_T_does_change_features(panel, sessions):
    """Guards against a vacuous A3 pass (e.g. features that ignore the panel)."""
    from nidp.services.tpd_model.features import compute_features

    T = sessions[205]
    base = compute_features(panel, T)
    moved = panel.copy()
    moved.loc[moved["as_of_date"] == pd.Timestamp(T), "close"] *= 1.2
    assert not _bitwise_equal(base, compute_features(moved, T))


def test_feature_list_contains_no_unproven_fundamental_or_news_features_b8():
    from nidp.services.tpd_model.features import FEATURE_LIST

    assert [f for f in FEATURE_LIST if DENYLIST.search(f)] == []


def test_every_feature_is_logged_with_a_data_date_not_after_T_c6(panel, sessions):
    from nidp.services.tpd_model.features import FEATURE_LIST, feature_vector

    T = sessions[205]
    vec = feature_vector(panel, T, "SYM001", events=_events(sessions, T))
    assert set(vec) == set(FEATURE_LIST)
    for name, cell in vec.items():
        assert {"value", "data_date"} <= set(cell), name
        assert cell["data_date"] <= T, name


def test_delivery_features_lag_one_session_tech3(panel, sessions):
    from nidp.services.tpd_model.features import DELIVERY_FEATURES, feature_vector

    assert DELIVERY_FEATURES, "delivery features must be declared so the lag is enforceable"
    T = sessions[205]
    vec = feature_vector(panel, T, "SYM001")
    assert all(vec[f]["data_date"] < T for f in DELIVERY_FEATURES)


def test_delivery_on_T_does_not_affect_features_tech3(panel, sessions):
    from nidp.services.tpd_model.features import compute_features

    T = sessions[205]
    base = compute_features(panel, T)
    changed = panel.copy()
    changed.loc[changed["as_of_date"] == pd.Timestamp(T), "deliverable_pct"] = 99.0
    assert _bitwise_equal(base, compute_features(changed, T))


def test_event_features_carry_source_ts_at_or_before_cutoff(panel, sessions):
    from nidp.services.tpd_model.features import EVENT_FEATURES, feature_vector

    T = sessions[205]
    vec = feature_vector(panel, T, "SYM001", events=_events(sessions, T))
    for f in EVENT_FEATURES:
        ts = vec[f].get("source_ts")
        if vec[f]["value"]:
            assert ts is not None and ts <= ist(T, 15, 30), f
        assert ts is None or ts.utcoffset() == IST.utcoffset(ts)


def test_feature_computation_is_deterministic(panel, sessions):
    from nidp.services.tpd_model.features import compute_features

    T = sessions[205]
    assert _bitwise_equal(compute_features(panel, T), compute_features(panel.sample(frac=1, random_state=3), T))


def test_symbol_without_bar_on_T_gets_no_features(panel, sessions):
    from nidp.services.tpd_model.features import compute_features

    T = sessions[205]
    missing = panel.drop(panel[(panel["symbol"] == "SYM007") & (panel["as_of_date"] == pd.Timestamp(T))].index)
    assert "SYM007" not in compute_features(missing, T).index
