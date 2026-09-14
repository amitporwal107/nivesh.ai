"""The synthetic fixtures must themselves be sound, or every xfail/pass below them means nothing."""
import pandas as pd

from nidp.tests.services.tpd_model.conftest import make_panel, weekday_sessions


def test_panel_is_one_bar_per_symbol_session(panel, symbols, sessions):
    assert len(panel) == len(symbols) * len(sessions)
    assert not panel.duplicated(["symbol", "as_of_date"]).any()


def test_bars_are_internally_consistent(panel):
    assert (panel["high"] >= panel[["open", "close"]].max(axis=1) - 1e-9).all()
    assert (panel["low"] <= panel[["open", "close"]].min(axis=1) + 1e-9).all()
    assert (panel["turnover"] > 0).all()


def test_prev_close_chains_to_prior_close(panel):
    p = panel.sort_values(["symbol", "as_of_date"])
    chained = p.groupby("symbol")["close"].shift(1)
    mask = chained.notna()
    assert (p.loc[mask, "prev_close"] == chained[mask]).all()


def test_builder_is_deterministic():
    s = weekday_sessions("2025-01-01", 30)
    pd.testing.assert_frame_equal(make_panel(["A", "B"], s), make_panel(["A", "B"], s))


def test_weekday_sessions_skip_holidays_and_weekends():
    from datetime import date
    s = weekday_sessions("2026-09-10", 3, frozenset({date(2026, 9, 14)}))
    assert s == [date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 15)]
