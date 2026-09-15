"""A3 future perturbation (feature level), B8 unproven-feature denylist, C6 logged vectors + TECH-3 delivery lag.

Bitwise rule (test-plan §1c): float64 compared via uint64 views with identical NaN masks — no tolerance.
Retrain-and-rescore perturbation belongs to the walk-forward tests (W3).
"""
import re

import numpy as np
import pandas as pd
import pytest

from nidp.tests.services.tpd_model.conftest import IST, ist


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


def _bonus(sessions, idx):
    return pd.DataFrame({"symbol": ["SYM001"], "ex_date": [pd.Timestamp(sessions[idx])], "factor": [0.5]})


def test_corporate_action_after_T_does_not_change_features(panel, sessions):
    from nidp.services.tpd_model.features import compute_features

    T = sessions[205]
    assert _bitwise_equal(compute_features(panel, T), compute_features(panel, T, actions=_bonus(sessions, 210)))


def test_bonus_before_T_is_adjusted_not_read_as_a_crash(panel, sessions):
    """Halve SYM001's raw prices from ex-date onward (a 1:1 bonus); with the action supplied the returns
    must match the unbonused series, without it ret20 shows the ~-50% artefact."""
    from nidp.services.tpd_model.features import compute_features

    T, ex = sessions[205], sessions[195]
    bonused = panel.copy()
    after = (bonused["symbol"] == "SYM001") & (bonused["as_of_date"] >= pd.Timestamp(ex))
    bonused.loc[after, ["open", "high", "low", "close", "prev_close"]] /= 2
    bonused.loc[after, "volume"] *= 2
    clean = compute_features(panel, T).loc["SYM001"]
    adjusted = compute_features(bonused, T, actions=_bonus(sessions, 195)).loc["SYM001"]
    unadjusted = compute_features(bonused, T).loc["SYM001"]
    assert adjusted["ret20"] == pytest.approx(clean["ret20"], rel=1e-9)
    assert adjusted["rsi14"] == pytest.approx(clean["rsi14"], rel=1e-9)
    assert unadjusted["ret20"] < clean["ret20"] - 30


def test_inputs_on_record_are_the_fixed_d_ux3_set_in_order():
    """Every row shows the same observable inputs in the same order (user decision D-UX3, 2026-09-14)."""
    from nidp.services.tpd_model.features import FEATURE_LIST, INPUTS_ON_RECORD

    assert INPUTS_ON_RECORD == ("res_on_D", "ret1", "vol_z20", "atr_pct", "n_high_up_252")
    assert set(INPUTS_ON_RECORD) <= set(FEATURE_LIST)


def test_event_flags_match_the_gate_for_every_symbol(panel, sessions):
    """compute_features may pre-filter filings for speed, but each flag must equal event_gate.results_flag
    over the full filing set: known by the cutoff, after it, NULL timestamp, and another day's meeting."""
    from nidp.services.tpd_model.event_gate import results_flag
    from nidp.services.tpd_model.features import compute_features

    T, D = sessions[205], sessions[206]
    events = pd.DataFrame({
        "symbol": ["SYM001", "SYM002", "SYM003", "SYM004", "SYM005", "SYM005"],
        "event_date": pd.to_datetime([D, D, D, T, D, sessions[220]]),
        "intimated_at": pd.Series([ist(T, 9, 0), ist(T, 15, 30, 1), pd.NaT, ist(sessions[204], 18, 0),
                                   ist(sessions[200], 10, 0), ist(T, 10, 0)], dtype="datetime64[ns, Asia/Kolkata]"),
    })
    f = compute_features(panel, T, events=events, target_session=D)
    for sym in f.index:
        for col, day in (("res_on_D", D), ("res_on_T", T)):
            flag, _ = results_flag(events, sym, T, day)
            expected = float("nan") if flag is None else float(flag)
            got = f.loc[sym, col]
            assert (np.isnan(got) and np.isnan(expected)) or got == expected, (sym, col, got, expected)
    assert f.loc["SYM001", "res_on_D"] == 1.0 and f.loc["SYM002", "res_on_D"] == 0.0
    assert np.isnan(f.loc["SYM003", "res_on_D"]) and f.loc["SYM004", "res_on_T"] == 1.0


def test_market_features_over_supplied_members_only_v2(panel, sessions):
    """v2 (lock v2): mkt_ret1/breadth over the target session's universe members, not every stock with a bar."""
    from nidp.services.tpd_model.features import compute_features

    T = sessions[205]
    members = {f"SYM{i:03d}" for i in range(10)}
    all_stocks = compute_features(panel, T)
    only = compute_features(panel, T, market_members=members)
    rets = all_stocks.loc[sorted(members), "ret1"]
    assert only["mkt_ret1"].iloc[0] == pytest.approx(rets.mean(), rel=1e-12)
    assert only["breadth"].iloc[0] == pytest.approx(float((rets > 0).mean()), rel=1e-12)
    assert set(only.index) == set(all_stocks.index)          # still scores every stock with a bar on T
    assert not np.isclose(only["mkt_ret1"].iloc[0], all_stocks["mkt_ret1"].iloc[0])
    cols = [c for c in only.columns if c not in ("mkt_ret1", "breadth")]
    assert _bitwise_equal(only[cols], all_stocks[cols])       # nothing else changes
