"""A8 source integrity: NSE EQ only, ETFs out, thin sessions detected point-in-time (K5)."""
from datetime import date

import pandas as pd

from nidp.tests.services.tpd_model.conftest import NOT_IMPLEMENTED, make_panel, weekday_sessions

pytestmark = NOT_IMPLEMENTED


def test_bse_row_on_nse_date_is_ignored(panel):
    from nidp.services.tpd_model.panel_source import select_nse_eq

    nse = panel[panel["symbol"] == "SYM001"].iloc[[10]]
    bse = nse.assign(source="BSE_BHAVCOPY", close=nse["close"] * 1.07)
    out = select_nse_eq(pd.concat([panel, bse], ignore_index=True), etf_symbols=set())
    row = out[(out["symbol"] == "SYM001") & (out["as_of_date"] == nse["as_of_date"].iloc[0])]
    assert len(row) == 1
    assert row["close"].iloc[0] == nse["close"].iloc[0]


def test_bse_only_bar_is_a_missing_bar_not_a_substitute(panel):
    from nidp.services.tpd_model.panel_source import select_nse_eq

    d = panel["as_of_date"].iloc[-1]
    rows = panel[~((panel["symbol"] == "SYM002") & (panel["as_of_date"] == d))]
    bse_only = panel[(panel["symbol"] == "SYM002") & (panel["as_of_date"] == d)].assign(source="BSE_BHAVCOPY")
    out = select_nse_eq(pd.concat([rows, bse_only], ignore_index=True), etf_symbols=set())
    assert out[(out["symbol"] == "SYM002") & (out["as_of_date"] == d)].empty


def test_etfs_and_non_eq_series_are_excluded(panel):
    from nidp.services.tpd_model.panel_source import select_nse_eq

    be = panel[panel["symbol"] == "SYM003"].assign(series="BE")
    out = select_nse_eq(pd.concat([panel, be], ignore_index=True), etf_symbols={"SYM004"})
    assert "SYM004" not in set(out["symbol"])
    assert set(out["series"]) == {"EQ"}


def test_thin_session_is_detected_and_listed():
    from nidp.services.tpd_model.panel_source import thin_sessions

    s = weekday_sessions("2025-01-01", 60)
    p = make_panel([f"S{i:02d}" for i in range(50)], s)
    thin_day = pd.Timestamp(s[40])
    p = p[~((p["as_of_date"] == thin_day) & (p["symbol"] >= "S20"))]  # 20 of 50 rows = 40% < 80%
    assert thin_sessions(p, lookback=126, frac=0.8) == [s[40]]


def test_thin_rule_uses_only_prior_sessions_k5():
    """Later, larger sessions must not make earlier normal sessions look thin.

    10 rows/session for s[0..9], then 110 rows from s[10]. A whole-panel median (110, used by the
    research code) would flag all of s[0..9]; the point-in-time trailing median flags nothing.
    """
    from nidp.services.tpd_model.panel_source import thin_sessions

    s = weekday_sessions("2025-01-01", 40)
    base = make_panel([f"S{i:02d}" for i in range(10)], s)
    extra = make_panel([f"X{i:03d}" for i in range(100)], s[10:])
    assert thin_sessions(pd.concat([base, extra], ignore_index=True), lookback=126, frac=0.8) == []


def test_first_sessions_without_history_are_not_flagged():
    from nidp.services.tpd_model.panel_source import thin_sessions

    s = weekday_sessions("2025-01-01", 5)
    assert thin_sessions(make_panel(["A", "B"], s)) == []


def test_weekend_special_sessions_are_kept_as_sessions():
    """K6 (user-accepted): 2025-02-01 / 2026-02-01 budget sessions count as normal sessions."""
    from nidp.services.tpd_model.panel_source import select_nse_eq

    s = weekday_sessions("2025-01-27", 5) + [date(2025, 2, 1)]
    out = select_nse_eq(make_panel(["A"], sorted(s)), etf_symbols=set())
    assert pd.Timestamp("2025-02-01") in set(out["as_of_date"])
