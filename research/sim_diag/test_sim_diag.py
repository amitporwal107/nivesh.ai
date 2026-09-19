"""Reconciliation classes, RC-1 rules, the raw-bar re-check, data-quality flags, the candidate check and Mode A paths —
synthetic cases with hand-worked answers (PRD §6, §8, §9, §14, §15)."""
from __future__ import annotations

import datetime as dt
import os
import sys
from decimal import Decimal as D

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit as AU  # noqa: E402
import candidates as CD  # noqa: E402
import dq as DQ  # noqa: E402
import inputs as IN  # noqa: E402
import reconcile as RC  # noqa: E402


def trade(**kw):
    t = {"status": "CLOSED", "symbol": "X", "decision_date": dt.date(2022, 10, 3), "exit_reason": "STOP_HIT",
         "exit_detail": "STOP", "exit_date": dt.date(2022, 10, 5), "exit_level": D("98.00"), "net_ret": -0.0255,
         "net_ret_exact": -0.0255, "fill_quantity": 499, "qty_exact": 499, "flags": "", "intended_entry": D("100"),
         "initial_stop": D("98"), "initial_target": D("105"), "next_session_open": D("100"), "signal_close": D("99.5"),
         "net_inr": D("-1275"), "gross_inr": D("-1000"), "initial_risk_inr": D("1048"), "fill_status": "FILLED",
         "high_after_exit_pct": 0.01, "stop_distance_atr": 0.6, "path_max_high_pct": 0.012, "path_min_low_pct": -0.03,
         "close_last_pct": -0.01, "entry_date": dt.date(2022, 10, 4)}
    t.update(kw)
    return t


def lab(**kw):
    r = {"tbs_5_2": "STOP", "tbs_5_2_exit_date": pd.Timestamp("2022-10-05"), "tbs_5_2_exit_px": 98.0, "net_ret_5_2": -0.0255}
    r.update(kw)
    return pd.Series(r)


# ---------------- reconciliation ----------------
def test_reconcile_agreement_and_each_field():
    assert RC.compare(trade(), lab())["ok"]
    r = RC.compare(trade(exit_reason="TARGET_HIT"), lab())
    assert not r["ok_outcome"] and r["classes"] == "UNEXPLAINED"
    r = RC.compare(trade(exit_date=dt.date(2022, 10, 6)), lab())
    assert not r["ok_date"] and r["classes"] == "UNEXPLAINED"
    assert RC.compare(trade(exit_level=D("98.01")), lab())["ok"]                         # within ₹0.01
    r = RC.compare(trade(exit_level=D("98.02")), lab())
    assert not r["ok_level"] and r["classes"] == "UNEXPLAINED"


def test_reconcile_gap_through_is_a_labels_stop():
    r = RC.compare(trade(exit_reason="GAP_THROUGH_STOP", exit_level=D("96")), lab(tbs_5_2_exit_px=96.0))
    assert r["ok"]


def test_reconcile_net_differences_are_explained_only_by_the_exact_path():
    r = RC.compare(trade(net_ret=-0.02551, net_ret_exact=-0.0255000004), lab())
    assert not r["ok_net"] and r["classes"] == "NET_PAISA_ROUNDING"
    r = RC.compare(trade(net_ret=-0.02551, net_ret_exact=-0.0255000004, qty_exact=498), lab())
    assert r["classes"] == "NET_QTY_BOUNDARY"
    r = RC.compare(trade(net_ret=-0.02551, net_ret_exact=-0.02551), lab())
    assert r["classes"] == "UNEXPLAINED"


def test_reconcile_locked_lower_full_day_vs_lock_test_false_positive():
    r = RC.compare(trade(exit_date=dt.date(2022, 10, 6), flags="LOCKED_LOWER_FULLDAY_S2"), lab())
    assert r["classes"] == "LOCKED_LOWER_FULL_DAY"
    r2 = RC.compare(trade(exit_date=dt.date(2022, 10, 6), flags="LOCKED_LOWER_FULLDAY_S2;LOCKED_LOWER_PARTIAL_S3"), lab())
    assert r2["classes"] == "LOCKED_LOWER_HEURISTIC"
    assert RC.compare(trade(exit_date=dt.date(2022, 10, 6), flags="NO_BAR_S3"), lab())["classes"] == "UNEXPLAINED"
    s = RC.summarise(pd.DataFrame([RC.compare(trade(), lab()), r, r2]))
    assert s["agree_all_fields"] == 1 and s["mismatch_classes"] == {"LOCKED_LOWER_FULL_DAY": 1, "LOCKED_LOWER_HEURISTIC": 1}
    assert s["simulator_defects"] == 1 and s["unexplained"] == 0
    assert s["defect_side"] == {"LOCKED_LOWER_FULL_DAY": "labels.py", "LOCKED_LOWER_HEURISTIC": "simulator"}


def test_reconcile_lists_entry_disagreements():
    r = RC.compare({"status": "UNRESOLVED", "symbol": "X", "decision_date": dt.date(2022, 10, 3),
                    "exit_reason": "MANUAL_REVIEW_REQUIRED", "flags": ""}, lab(entry_status="OK"))
    assert not r["ok"] and r["classes"] == "UNEXPLAINED" and "UNRESOLVED" in r["detail"]
    r = RC.compare(trade(), lab(entry_status="LOCKED_UPPER_OPEN"))
    assert not r["ok"] and r["classes"] == "UNEXPLAINED"


# ---------------- RC-1 ----------------
def test_rc1_order_and_rules():
    assert AU.rc1(trade(), False, False, False) == ["STOP_FAILURE", "DIRECTION_FAILURE"]
    assert AU.rc1(trade(), False, True, False)[0] == "DATA_FAILURE"
    assert AU.rc1(trade(), False, False, True)[0] == "SIMULATION_FAILURE"
    assert AU.rc1(trade(), True, False, False)[0] == "DATA_FAILURE"
    assert AU.rc1(trade(net_inr=D("-1600")), False, False, False)[0] == "RISK_FAILURE"      # 1600 > 1.5 x 1048
    assert AU.rc1(trade(net_inr=D("-1572")), False, False, False)[0] == "STOP_FAILURE"      # 1572 = 1.5 x 1048: not over
    assert AU.rc1(trade(fill_status="PARTIAL"), False, False, False)[0] == "LIQUIDITY_FAILURE"
    assert AU.rc1(trade(next_session_open=D("101.6")), False, False, False)[0] == "ENTRY_FAILURE"   # > 99.5 x 1.02
    assert AU.rc1(trade(next_session_open=D("101.49")), False, False, False)[0] == "STOP_FAILURE"
    assert AU.rc1(trade(high_after_exit_pct=0.05, path_max_high_pct=0.05), False, False, False)[0] == "VOLATILITY_TRAP"
    assert AU.rc1(trade(stop_distance_atr=1.0), False, False, False) == ["DIRECTION_FAILURE"]
    assert AU.rc1(trade(stop_distance_atr=1.0, close_last_pct=0.001), False, False, False) == []
    # the stop bar itself reached the target (ambiguous bar): not "reached later", so not a volatility trap
    assert "VOLATILITY_TRAP" not in AU.rc1(trade(path_max_high_pct=0.06, high_after_exit_pct=0.01), False, False, False)


def test_rc1_expired_trades():
    exp = dict(exit_reason="TIME_EXIT", exit_detail="TIME")
    assert AU.rc1(trade(**exp, path_max_high_pct=0.03), False, False, False) == ["TARGET_FAILURE"]
    assert AU.rc1(trade(**exp, path_max_high_pct=0.019, path_min_low_pct=-0.019), False, False, False) == ["SIGNAL_FAILURE"]
    assert AU.rc1(trade(**exp, path_max_high_pct=0.022, path_min_low_pct=-0.01), False, False, False) == []
    assert AU.rc1(trade(**exp, path_max_high_pct=0.01, path_min_low_pct=-0.01, gross_inr=D("50"), net_inr=D("-60")),
                  False, False, False) == ["SIGNAL_FAILURE", "COST_FAILURE"]
    assert AU.rc1(trade(**exp, path_max_high_pct=0.01, path_min_low_pct=-0.01, gross_inr=D("0"), net_inr=D("-60")),
                  False, False, False) == ["SIGNAL_FAILURE"]                    # gross exactly 0 is not a cost failure


# ---------------- raw-bar re-check ----------------
def raw(rows):
    return pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"]).assign(date=lambda d: pd.to_datetime(d.date))


def test_raw_bar_check_passes_a_correct_trade_and_catches_errors():
    r = raw([("2022-10-04", 100, 101, 99, 100), ("2022-10-05", 99, 100, 97, 98)])
    assert AU.raw_bar_check(trade(), r) == ("PASS", "")
    assert AU.raw_bar_check(trade(intended_entry=D("100.5")), r)[0] == "FAIL"
    early = raw([("2022-10-04", 100, 101, 97.9, 100), ("2022-10-05", 99, 100, 97, 98)])
    assert "earlier" in AU.raw_bar_check(trade(), early)[1]
    outside = raw([("2022-10-04", 100, 101, 99, 100), ("2022-10-05", 99, 100, 98.5, 99)])
    assert AU.raw_bar_check(trade(), outside)[1] == "exit level outside the raw bar"
    dup = pd.concat([r, r.iloc[[1]]])
    assert AU.raw_bar_check(trade(), dup)[1] == "duplicate raw bars inside the trade"
    gap = raw([("2022-10-04", 100, 101, 99, 100), ("2022-10-05", 96, 97, 95, 96)])
    assert AU.raw_bar_check(trade(exit_detail="GAP_THROUGH", exit_level=D("96")), gap) == ("PASS", "")
    assert AU.raw_bar_check(trade(exit_detail="GAP_THROUGH", exit_level=D("95.5")), gap)[0] == "FAIL"


# ---------------- data quality ----------------
def bars_frame(rows):
    d = pd.DataFrame(rows, columns=["symbol", "date", "open", "high", "low", "close", "volume", "prev_close", "vol_med20"])
    return d.assign(date=pd.to_datetime(d.date))


def test_bar_flags():
    b = bars_frame([
        ("OK", "2022-10-03", 100, 102, 99, 101, 1000, 100, 1000),
        ("BADHL", "2022-10-03", 100, 99, 98, 101, 1000, 100, 1000),         # high below the close
        ("CA", "2022-10-03", 60, 61, 59, 60, 1000, 100, 1000),              # -40%: corporate-action move and gap
        ("SPIKE", "2022-10-03", 100, 102, 99, 101, 10001, 100, 1000),       # volume > 10x median
        ("THIN", "2022-10-03", 100, 102, 99, 101, 49, 100, 1000),           # < 5% of median
        ("MID", "2022-10-03", 100, 102, 99, 101, 100, 100, 1000),           # 10% of median: not low
        ("BADCLOSE", "2022-10-03", 100, 101, 99, 102, 1000, 100, 1000),     # close above the high
        ("UPLOCK", "2022-10-03", 110, 110, 108, 109, 1000, 100, 1000),      # open = high at +10%
        ("DNCLOSE", "2022-10-24", 97, 98, 95, 95, 1000, 100, 1000),         # close = low at -5%, Muhurat
    ])
    f = DQ.bar_flags(b).set_index("symbol")
    assert f.ohlc_invalid.tolist() == [False, True, False, False, False, False, True, False, False]
    assert not f.vol_low["MID"]
    assert f.ca_move["CA"] and f.gap20["CA"] and not f.ca_move["OK"]
    assert f.ca_volume["SPIKE"] and not f.ca_volume["OK"] and f.vol_low["THIN"] and not f.vol_low["OK"]
    assert f.locked_open_up["UPLOCK"] and not f.locked_open_up["OK"]
    assert f.locked_close_down["DNCLOSE"] and f.special_session["DNCLOSE"] == "DIWALI_MUHURAT"
    assert not f.any_flag["OK"] and f.any_flag["DNCLOSE"]


def test_raw_checks_count_exact_and_conflicting_duplicates_and_instruments():
    r = pd.DataFrame({"symbol": ["A", "A", "B", "B", "C", "C"], "instrument_token": [1, 1, 2, 2, 3, 4],
                      "date": pd.to_datetime(["2022-10-03"] * 2 + ["2022-10-03"] * 2 + ["2022-10-03", "2022-10-05"]),
                      "open": [1, 1, 1, 2, 1, 1], "high": 1, "low": 1, "close": 1, "volume": 1})
    cal = pd.DatetimeIndex(["2022-10-03", "2022-10-04"])
    c = DQ.raw_checks(r, cal)
    assert c["duplicate_keys"] == 2 and c["conflicting_duplicate_keys"] == 1 and c["duplicate_rows"] == 4
    assert c["off_calendar_bars"] == 1 and c["symbols_with_several_instruments"] == ["C"]


def test_missing_table_separates_missing_from_not_yet_listed():
    b = pd.DataFrame({"symbol": ["A", "A", "B"], "date": pd.to_datetime(["2022-10-03", "2022-10-05", "2022-10-05"])})
    uni = pd.DataFrame({"symbol": ["A", "B", "C"]})
    m = DQ.missing_table(b, uni, pd.to_datetime(["2022-10-03", "2022-10-04"]))
    got = {(d.date().isoformat(), s): k for d, s, k in m.itertuples(index=False)}
    assert got == {("2022-10-03", "B"): "NOT_YET_LISTED", ("2022-10-03", "C"): "NO_DATA",
                   ("2022-10-04", "A"): "MISSING", ("2022-10-04", "B"): "NOT_YET_LISTED", ("2022-10-04", "C"): "NO_DATA"}


# ---------------- candidates and inputs ----------------
def test_verify_picks_raises_on_any_difference():
    ranked = pd.DataFrame({"date": pd.to_datetime(["2022-10-03"] * 6), "symbol": list("ABCDEF"),
                           "score": [.9, .8, .7, .6, .5, .4], "tie": [.1] * 6, "rank": [1, 2, 3, 4, 5, 6]})
    assert CD.verify_picks(ranked, ranked.iloc[:5])["identical"]
    bad = ranked.iloc[:5].copy()
    bad.loc[4, "score"] = 0.51
    with pytest.raises(IN.InputError):
        CD.verify_picks(ranked, bad)


def test_ineligible_reasons():
    assert CD.ineligible_reason(59, 6e7, 100) == "HISTORY_LT_60"
    assert CD.ineligible_reason(60, 4.9e7, 49) == "VALUE20_LT_5CR;CLOSE_LT_50"
    assert CD.ineligible_reason(np.nan, 6e7, 100) == "HISTORY_LT_60"


def test_prediction_id_is_deterministic_and_sensitive_to_every_field():
    base = ("c", "M8", "tbs_5_2", "2022-10-03", "X", 0.25)
    ids = {IN.prediction_id(*base)}
    assert IN.prediction_id(*base) in ids
    for i, alt in enumerate(("d", "M4", "dir_5_5d", "2022-10-04", "Y", 0.2500001)):
        v = list(base)
        v[i] = alt
        ids.add(IN.prediction_id(*v))
    assert len(ids) == 7


# ---------------- Mode A ----------------
def test_forward_paths_by_hand():
    cal = pd.DatetimeIndex(pd.to_datetime(["2022-10-03", "2022-10-04", "2022-10-06", "2022-10-07"]))
    b = pd.DataFrame({"symbol": "X", "date": cal, "open": [9, 100, 101, 99], "high": [9, 103, 104, 100],
                      "low": [9, 97, 100, 95], "close": [9, 102, 103, 96]})
    p = AU.forward_paths(b, cal, pd.DataFrame({"symbol": ["X"], "date": [cal[0]]}), k=3)
    assert p.r1.iat[0] == pytest.approx(0.02) and p.r3.iat[0] == pytest.approx(-0.04) and p.r_last.iat[0] == pytest.approx(-0.04)
    assert p.mfe.iat[0] == pytest.approx(0.04) and p.mae.iat[0] == pytest.approx(-0.05) and p.s1_low.iat[0] == pytest.approx(-0.03)
    q = AU.forward_paths(b, cal, pd.DataFrame({"symbol": ["X"], "date": [cal[1]]}), k=3)
    assert q.isna().all(axis=1).iat[0]                                          # the window runs past the calendar


def test_exposure_and_losing_streak():
    t = pd.DataFrame({"symbol": ["A", "A", "B"], "entry_date": pd.to_datetime(["2022-10-04", "2022-10-06", "2022-10-06"]),
                      "exit_date": pd.to_datetime(["2022-10-06", "2022-10-07", "2022-10-06"]), "buy_value": [100.0, 200.0, 50.0]})
    cal = pd.DatetimeIndex(pd.to_datetime(["2022-10-04", "2022-10-06", "2022-10-07"]))
    e = AU.exposure(t, cal, {"A": "Banks", "B": "Banks"}).set_index("date")
    assert e.open_trades.tolist() == [1, 3, 1] and e.capital_in_use_inr.tolist() == [100.0, 350.0, 200.0]
    assert e.same_symbol_overlaps.tolist() == [0, 1, 0] and e.max_same_industry.tolist() == [1, 3, 1]
    assert AU.longest_losing_streak(pd.Series([1, -1, 0, -2, 3, -1])) == 3


class _Store:
    def __init__(self, rows):
        self.rows = rows

    def sessions_after(self, d, n):
        return [pd.Timestamp("2022-10-04")]

    def row(self, s, d):
        return self.rows.get(s)


def test_session_report_fail_flag_and_pass():
    D = pd.Timestamp("2022-10-03")
    b = bars_frame([("A", "2022-10-03", 100, 102, 99, 101, 1000, 100, 1000), ("B", "2022-10-03", 100, 102, 99, 101, 1000, 100, 1000)])
    uni = pd.DataFrame({"symbol": ["A", "B"], "isin": ["INE1", "INE2"]})
    ds_day = pd.DataFrame({"symbol": ["A", "B"], "eligible": [True, False], "hist_n": [100, 10], "value20": [1e9, 1e9], "close": [101, 101]})
    picks = pd.DataFrame({"symbol": ["A"], "entry_status": ["OK"]})
    empty = pd.DataFrame(columns=["symbol", "date", "kind"])
    tb = pd.DataFrame({"symbol": ["A"], "date": [D]})
    args = dict(missing=empty, raw_dups=pd.DataFrame(columns=["symbol", "date"]), uni=uni, ds_day=ds_day, trade_bars=tb,
                picks_day=picks, cutoff={"violations": 0}, instrument_conflicts=[], store=_Store({"A": object()}))
    r = DQ.session_report(D, DQ.bar_flags(b), **args)
    assert r["status"] == "PASS" and r["exclusions"]["not_eligible"] == {"HISTORY_LT_60": 1} and r["trade_bars_checked"] == 1
    bad = bars_frame([("A", "2022-10-03", 100, 99, 98, 101, 1000, 100, 1000), ("B", "2022-10-03", 100, 102, 99, 101, 1000, 100, 1000)])
    assert DQ.session_report(D, DQ.bar_flags(bad), **args)["status"] == "FAIL"
    spike = bars_frame([("A", "2022-10-03", 100, 102, 99, 101, 20000, 100, 1000), ("B", "2022-10-03", 100, 102, 99, 101, 1000, 100, 1000)])
    r = DQ.session_report(D, DQ.bar_flags(spike), **args)
    assert r["status"] == "PASS_WITH_FLAGS" and r["flags_trade_bars"] == {"ca_volume": ["A@2022-10-03"]}
    assert DQ.session_report(D, DQ.bar_flags(b), **(args | {"uni": uni.assign(isin=[None, "INE2"])}))["status"] == "FAIL"
    assert DQ.session_report(D, DQ.bar_flags(b), **(args | {"cutoff": {"violations": 3}}))["status"] == "FAIL"


def test_reconcile_labels_own_lock_heuristic_is_attributed_to_labels_not_left_unexplained():
    """D7, 2026-09-20: the simulator now buys a bar that opened at the upper circuit and then traded. labels.py is
    frozen with the H#32 dataset and keeps the old test, so it skips the same pick. That is labels.py's heuristic,
    not an unexplained difference - but only when the bar really did trade."""
    t = trade()
    lab_locked = lab(); lab_locked["entry_status"] = "LOCKED_UPPER_OPEN"
    class B:                                   # the s1 bar: opened at the band, then traded away from it
        high, low = RC.np.float64(110), RC.np.float64(104)
    r = RC.compare(t, lab_locked, B())
    assert r["classes"] == "LOCKED_UPPER_LABELS_HEURISTIC" and not r["ok"]
    assert RC.DEFECT_SIDE[r["classes"]] == "labels.py"
    assert "buyable" in r["detail"]

    class FullDay:                             # locked all day: labels.py was right to skip it
        high, low = RC.np.float64(110), RC.np.float64(110)
    assert RC.compare(t, lab_locked, FullDay())["classes"] == "UNEXPLAINED"
    assert RC.compare(t, lab_locked, None)["classes"] == "UNEXPLAINED"          # no bar: never guessed
    assert "LOCKED_UPPER_LABELS_HEURISTIC" not in RC.SIMULATION_FAILURE_CLASSES  # not a simulator defect
