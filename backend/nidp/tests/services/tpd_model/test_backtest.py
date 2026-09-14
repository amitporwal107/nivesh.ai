"""W3 runner pieces: fast universe equals the tested pit_universe, corporate actions via price_adjuster,
suspected unrecorded actions, row assembly, and a small end-to-end walk-forward that refuses without the lock."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from nidp.tests.services.tpd_model.conftest import make_panel, weekday_sessions


def test_universe_by_session_equals_pit_universe_with_gaps():
    from nidp.services.tpd_model.backtest import universe_by_session
    from nidp.services.tpd_model.universe import pit_universe

    s = weekday_sessions("2025-01-01", 170)
    p = make_panel([f"S{i:02d}" for i in range(40)], s)
    rng = np.random.default_rng(5)
    p = p.drop(p.sample(frac=0.08, random_state=1).index)          # scattered missing bars
    p = p[~((p["symbol"] == "S03") & (p["as_of_date"] < pd.Timestamp(s[80])))]  # late listing
    p.loc[p["symbol"] == "S07", "turnover"] = p.loc[p["symbol"] == "S01", "turnover"].median()  # ties
    fast = universe_by_session(p, s[120:], n=15, lookback=126, min_bars=100)
    for D in s[120:]:
        assert fast[D] == pit_universe(p, D, n=15, lookback=126, min_bars=100), D


def _ca_rows():
    return pd.DataFrame([
        {"symbol": "SPL", "action_type": "SPLIT", "ex_date": "2025-03-03", "face_value_pre": 10, "face_value_post": 2, "ratio": None},
        {"symbol": "BON", "action_type": "BONUS", "ex_date": "2025-03-04", "face_value_pre": None, "face_value_post": None, "ratio": "1:1"},
        {"symbol": "RGT", "action_type": "RIGHTS", "ex_date": "2025-03-05", "face_value_pre": None, "face_value_post": None, "ratio": "1:5"},
        {"symbol": "DIV", "action_type": "DIVIDEND", "ex_date": "2025-03-06", "face_value_pre": None, "face_value_post": None, "ratio": None},
        {"symbol": "DEM", "action_type": "DEMERGER", "ex_date": "2025-03-07", "face_value_pre": None, "face_value_post": None, "ratio": None},
    ])


def test_corporate_actions_use_price_adjuster_factors_and_exclude_price_events():
    from nidp.services.tpd_model.backtest import corporate_actions_from_archive

    factors, exclusions = corporate_actions_from_archive(_ca_rows())
    f = factors.set_index("symbol")["factor"].to_dict()
    assert f == {"SPL": pytest.approx(0.2), "BON": pytest.approx(0.5)}
    assert set(exclusions["symbol"]) == {"SPL", "BON", "RGT", "DEM"}   # dividends move price only by the payout
    assert pd.api.types.is_datetime64_any_dtype(exclusions["ex_date"])


def test_suspected_unrecorded_actions_are_flagged_from_impossible_opens():
    """A 60% gap cannot happen inside NSE circuit rules; it is an unrecorded split/bonus."""
    from nidp.services.tpd_model.backtest import suspected_actions

    s = weekday_sessions("2025-01-01", 10)
    p = make_panel(["OK", "HIDDEN", "KNOWN"], s)
    for sym in ("HIDDEN", "KNOWN"):
        m = (p["symbol"] == sym) & (p["as_of_date"] >= pd.Timestamp(s[5]))
        p.loc[m, ["open", "high", "low", "close"]] /= 3
    known = pd.DataFrame({"symbol": ["KNOWN"], "ex_date": [pd.Timestamp(s[5])]})
    sus = suspected_actions(p, known)
    assert list(zip(sus["symbol"], sus["ex_date"])) == [("HIDDEN", pd.Timestamp(s[5]))]


def test_assembled_rows_carry_universe_horizons_and_warmup():
    from nidp.services.tpd_model.backtest import assemble_rows
    from nidp.services.tpd_model.labels import build_labels

    s = weekday_sessions("2025-01-01", 80)
    p = make_panel(["A", "B"], s)
    feats = pd.DataFrame({"as_of_date": pd.to_datetime([s[70], s[70], s[10]]), "symbol": ["A", "B", "A"],
                          "nbars": [71.0, 71.0, 11.0]})
    labels = build_labels(p, pd.DataFrame(columns=["symbol", "ex_date", "factor"]))
    universe = {s[71]: ["A"], s[11]: ["A", "B"]}
    rows = assemble_rows(feats, labels, universe, s, warmup=60)
    assert list(zip(rows["symbol"], rows["as_of_date"])) == [("A", pd.Timestamp(s[70]))]  # B not member; s[10] warm-up
    r = rows.iloc[0]
    assert r["target_session"] == pd.Timestamp(s[71]) and r["horizon_end_1d"] == pd.Timestamp(s[71])
    assert r["horizon_end_5d"] == pd.Timestamp(s[75])
    assert {"y_p_up10_1d", "y_p_down10_1d", "y_p_up10_5d", "y_p_down10_5d"} <= set(rows.columns)


def test_walkforward_refuses_without_lock(tmp_path):
    from nidp.services.tpd_model.backtest import run_walkforward
    from nidp.services.tpd_model.report import LockMissingError

    with pytest.raises(LockMissingError):
        run_walkforward(pd.DataFrame(), sessions=[], lock_path=tmp_path / "nope.json")


def test_small_walkforward_scores_only_out_of_sample_months():
    from nidp.services.tpd_model.backtest import run_walkforward
    from nidp.services.tpd_model.design import MODEL_COLUMNS

    rng = np.random.default_rng(9)
    s = [d.date() for d in pd.bdate_range("2025-06-02", "2025-10-31")]
    rows = []
    for i, T in enumerate(s[:-6]):
        for k in range(40):
            x = rng.normal()
            rows.append({"symbol": f"S{k:02d}", "as_of_date": pd.Timestamp(T), "target_session": pd.Timestamp(s[i + 1]),
                         "horizon_end_1d": pd.Timestamp(s[i + 1]), "horizon_end_5d": pd.Timestamp(s[i + 5]),
                         "nbars": 200.0, "atr_pct": 2 + abs(x), "bb_width": 0.1, "dist_52w_low": 10.0, "turn_med20": 1e7,
                         "close_raw": 100.0, "n_high_up_252": float(k % 4), "n_low_down_252": float(k % 3),
                         **{c: float(rng.normal()) for c in MODEL_COLUMNS if not c.startswith(("log_", "lr_"))},
                         "y_p_up10_1d": float(x > 1.6), "y_p_down10_1d": float(x < -1.6),
                         "y_p_up10_5d": float(x > 1.2), "y_p_down10_5d": float(x < -1.2)})
    frame = pd.DataFrame(rows)
    preds = run_walkforward(frame, sessions=s, first=date(2025, 9, 1), last=date(2025, 10, 31))
    assert set(preds["month"]) == {"2025-09", "2025-10"}
    assert (preds["target_session"] >= pd.Timestamp("2025-09-01")).all()
    assert {"p_tpd3", "p_base_rate", "p_atr_only", "p_own_history_only"} <= set(preds.columns)
    assert set(preds["head"]) == {"p_up10_1d", "p_down10_1d", "p_up10_5d", "p_down10_5d"}
    sep = preds[(preds["head"] == "p_up10_1d") & (preds["month"] == "2025-09")]
    assert (sep["train_end_max_horizon"] < pd.Timestamp("2025-09-01")).all()
