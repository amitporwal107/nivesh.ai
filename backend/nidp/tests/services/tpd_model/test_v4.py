"""v4 = v3 + the results print read at the freeze-time cutoff + 5% heads (user 2026-09-15: "please do... I need a
confidence level of 50%"). Tests written before the implementation."""
from datetime import date, time

import numpy as np
import pandas as pd
import pytest

from nidp.tests.services.tpd_model.conftest import IST, ist, make_panel, weekday_sessions


# ── labels at 5% ───────────────────────────────────────────────────────────────────────────────────────────────
def test_labels_take_a_threshold_and_stay_exact_in_paise():
    from nidp.services.tpd_model.labels import build_labels, touch_1d

    assert touch_1d(100.00, 105.00, 99.0, pct=5) == (True, False) and touch_1d(100.00, 105.00, 99.0) == (False, False)
    s = weekday_sessions("2026-01-01", 8)
    p = make_panel(["AAA"], s)
    p.loc[p["as_of_date"] == pd.Timestamp(s[1]), ["high", "low"]] = [0.0, 0.0]
    c = float(p.loc[p["as_of_date"] == pd.Timestamp(s[0]), "close"].iloc[0])
    p.loc[p["as_of_date"] == pd.Timestamp(s[1]), "high"] = round(c * 1.05, 2)     # +5.00% high on the target day
    p.loc[p["as_of_date"] == pd.Timestamp(s[1]), "low"] = round(c * 0.97, 2)
    none = pd.DataFrame(columns=["symbol", "ex_date"])
    l5 = build_labels(p, none, pct=5).set_index("as_of_date"); l10 = build_labels(p, none).set_index("as_of_date")
    assert l5.loc[pd.Timestamp(s[0]), "up_1d"] is True and l10.loc[pd.Timestamp(s[0]), "up_1d"] is False
    assert l5.loc[pd.Timestamp(s[0]), "down_1d"] is False
    assert build_labels(p, none, pct=10).equals(build_labels(p, none))               # default unchanged


def test_assemble_rows_can_carry_the_5pct_labels():
    from nidp.services.tpd_model.backtest import assemble_rows
    from nidp.services.tpd_model.features import compute_features
    from nidp.services.tpd_model.labels import build_labels

    s = weekday_sessions("2025-01-01", 70)
    p = make_panel(["AAA", "BBB"], s)
    none = pd.DataFrame(columns=["symbol", "ex_date"])
    T = s[65]
    f = compute_features(p, T).reset_index().assign(as_of_date=pd.Timestamp(T))
    rows = assemble_rows(f, build_labels(p, none), {s[66]: ["AAA", "BBB"]}, s, labels5=build_labels(p, none, pct=5))
    assert {"y_p_up5_1d", "y_p_down5_1d", "y_p_up10_1d"} <= set(rows.columns)
    assert (rows["y_p_up5_1d"].fillna(0) >= rows["y_p_up10_1d"].fillna(0)).all()      # a 10% touch is also a 5% touch


# ── the freeze-time cutoff ───────────────────────────────────────────────────────────────────────────────────────
def test_cutoff_takes_a_time_of_day_and_defaults_to_1530():
    from nidp.services.tpd_model.event_gate import cutoff_ist

    assert cutoff_ist(date(2026, 9, 15)).time() == time(15, 30)
    c = cutoff_ist(date(2026, 9, 15), at=time(20, 30))
    assert c.time() == time(20, 30) and c.tzinfo is not None and c.utcoffset().total_seconds() == 5.5 * 3600


# ── the results print block ───────────────────────────────────────────────────────────────────────────────────
def _fin(symbol, broadcast, pat_by_quarter, rev_by_quarter=None):
    """Quarterly rows ending 2026-06-30 back n quarters; only the latest carries `broadcast`, older ones 30 days
    after their period end (already known)."""
    n = len(pat_by_quarter)
    ends = [pd.Timestamp("2026-06-30") - pd.DateOffset(months=3 * k) + pd.offsets.QuarterEnd(0) for k in range(n)][::-1]
    rev = rev_by_quarter or [1000.0] * n
    rows = []
    for k, e in enumerate(ends):
        b = broadcast if k == n - 1 else ist((e + pd.Timedelta(days=30)).date(), 18, 0)
        rows.append({"symbol": symbol, "period_end": e, "period_type": "quarterly", "consolidated": True, "revenue_from_ops_cr": float(rev[k]),
                     "pat_cr": float(pat_by_quarter[k]), "eps_basic": pat_by_quarter[k] / 10, "ebitda_cr": 0.2 * rev[k], "broadcast_at": b,
                     "total_equity_cr": 2000.0, "long_term_debt_cr": 300.0, "short_term_debt_cr": 100.0, "finance_costs_cr": 8.0,
                     "pbt_cr": 1.3 * pat_by_quarter[k], "current_assets_cr": 900.0, "current_liabilities_cr": 600.0,
                     "equity_share_capital_cr": 100.0, "face_value": 10.0})
    return pd.DataFrame(rows)


def test_results_print_reads_a_filing_made_after_the_close_on_T():
    from nidp.services.tpd_model.results_print import RESULTS_PRINT_FEATURES, results_print

    T = date(2026, 7, 30)
    fin = _fin("ACME", ist(T, 18, 5), pat_by_quarter=[100, 100, 100, 100, 110, 120, 130, 180], rev_by_quarter=[1000] * 7 + [1300])
    f = results_print(fin, ["ACME", "NONE"], T)
    assert list(f.columns) == list(RESULTS_PRINT_FEATURES) and set(RESULTS_PRINT_FEATURES) >= {"filed_today", "filed_pat_yoy", "filed_rev_yoy", "filed_pat_qoq", "filed_loss", "filed_turnaround", "hours_since_filing"}
    r = f.loc["ACME"]
    assert r["filed_today"] == 1.0 and r["filed_pat_yoy"] == pytest.approx(0.80) and r["filed_rev_yoy"] == pytest.approx(0.30)
    assert r["filed_pat_qoq"] == pytest.approx(180 / 130 - 1) and r["filed_loss"] == 0.0 and r["filed_turnaround"] == 0.0
    assert r["hours_since_filing"] == pytest.approx((20.5 - 18 - 5 / 60), abs=0.02)   # measured to the 20:30 cutoff
    assert f.loc["NONE", "filed_today"] == 0.0 and np.isnan(f.loc["NONE", "filed_pat_yoy"])


def test_results_print_window_is_after_the_open_on_T_up_to_the_freeze_cutoff():
    from nidp.services.tpd_model.results_print import results_print

    T = date(2026, 7, 30)
    pat = [100, 100, 100, 100, 110, 120, 130, 180]
    assert results_print(_fin("ACME", ist(T, 20, 30), pat), ["ACME"], T).loc["ACME", "filed_today"] == 1.0    # at the cutoff: in
    assert results_print(_fin("ACME", ist(T, 20, 30, 1), pat), ["ACME"], T).loc["ACME", "filed_today"] == 0.0  # a second later: not yet
    assert results_print(_fin("ACME", ist(T, 8, 59), pat), ["ACME"], T).loc["ACME", "filed_today"] == 0.0     # pre-open: T itself reacted
    assert results_print(_fin("ACME", ist(T, 13, 0), pat), ["ACME"], T).loc["ACME", "filed_today"] == 1.0     # mid-session: partly still to come
    unstamped = _fin("ACME", pd.NaT, pat)
    assert results_print(unstamped, ["ACME"], T).loc["ACME", "filed_today"] == 0.0                            # no timestamp: unknown, never proxied
    before = results_print(_fin("ACME", ist(date(2026, 7, 29), 18, 0), pat), ["ACME"], T).loc["ACME"]
    assert before["filed_today"] == 0.0 and np.isnan(before["filed_pat_yoy"])                                # yesterday's filing already reacted


def test_results_print_flags_losses_and_turnarounds():
    from nidp.services.tpd_model.results_print import results_print

    T = date(2026, 7, 30)
    loss = results_print(_fin("ACME", ist(T, 18, 0), [100, 100, 100, 100, 90, 80, 20, -40]), ["ACME"], T).loc["ACME"]
    assert loss["filed_loss"] == 1.0 and np.isnan(loss["filed_pat_yoy"]) and loss["filed_turnaround"] == 0.0
    turn = results_print(_fin("ACME", ist(T, 18, 0), [100, 100, 100, -30, -20, -10, 5, 40]), ["ACME"], T).loc["ACME"]
    assert turn["filed_turnaround"] == 1.0 and turn["filed_loss"] == 0.0 and np.isnan(turn["filed_pat_yoy"])  # year-ago quarter was a loss


# ── v4 columns and heads ───────────────────────────────────────────────────────────────────────────────────────
def test_v4_columns_and_heads():
    from nidp.services.tpd_model.design import HEADS_V4, MODEL_COLUMNS_V3, MODEL_COLUMNS_V4, OWN_HISTORY_COUNT
    from nidp.services.tpd_model.results_print import RESULTS_PRINT_FEATURES

    assert list(MODEL_COLUMNS_V4) == list(MODEL_COLUMNS_V3) + list(RESULTS_PRINT_FEATURES)
    assert HEADS_V4 == ("p_up10_1d", "p_down10_1d", "p_up5_1d", "p_down5_1d")
    assert OWN_HISTORY_COUNT["p_up5_1d"] == "n_high_up_252" and OWN_HISTORY_COUNT["p_down5_1d"] == "n_low_down_252"


def test_features_v4_is_v3_plus_the_print_block(panel, sessions, symbols):
    from nidp.services.tpd_model.features_v3 import compute_features_v3
    from nidp.services.tpd_model.features_v4 import FEATURE_LIST_V4, compute_features_v4
    from nidp.services.tpd_model.results_print import RESULTS_PRINT_FEATURES

    T = sessions[205]
    fin = _fin(symbols[0], ist(T, 18, 0), [100, 100, 100, 100, 110, 120, 130, 180])
    fin["period_end"] = fin["period_end"] - pd.DateOffset(years=1) + pd.offsets.QuarterEnd(0)      # 2025 quarters for a 2025 T
    fin["broadcast_at"] = [ist((e + pd.Timedelta(days=30)).date(), 18, 0) for e in fin["period_end"][:-1]] + [ist(T, 18, 0)]
    v4 = compute_features_v4(panel, T, financials=fin)
    v3 = compute_features_v3(panel, T, financials=fin)
    assert list(v4.columns) == list(FEATURE_LIST_V4) and list(FEATURE_LIST_V4) == list(v3.columns) + list(RESULTS_PRINT_FEATURES)
    assert v4[v3.columns].equals(v3)                                                                # v3 part untouched
    assert v4.loc[symbols[0], "filed_today"] == 1.0 and v4.loc[symbols[1], "filed_today"] == 0.0
