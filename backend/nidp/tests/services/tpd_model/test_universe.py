"""A1 point-in-time universe: membership for D uses only bars strictly before D."""
import pandas as pd

from nidp.tests.services.tpd_model.conftest import make_panel, weekday_sessions


def _args(sessions):
    return {"n": 10, "lookback": 126, "min_bars": 100}


def test_bars_on_or_after_D_do_not_change_membership(panel, sessions):
    from nidp.services.tpd_model.universe import pit_universe

    D = pd.Timestamp(sessions[200])
    before = pit_universe(panel, sessions[200], **_args(sessions))
    future = panel.copy()
    future.loc[future["as_of_date"] >= D, "turnover"] *= 1000.0  # huge future turnover for everyone
    future.loc[(future["as_of_date"] >= D) & (future["symbol"] == "SYM039"), "turnover"] *= 1e6
    assert pit_universe(future, sessions[200], **_args(sessions)) == before


def test_bars_before_D_can_change_membership(panel, sessions):
    from nidp.services.tpd_model.universe import pit_universe

    before = pit_universe(panel, sessions[200], **_args(sessions))
    assert "SYM039" not in before  # lowest turnover by construction
    boosted = panel.copy()
    window = (boosted["as_of_date"] < pd.Timestamp(sessions[200])) & (boosted["symbol"] == "SYM039")
    boosted.loc[window, "turnover"] *= 1e6
    assert "SYM039" in pit_universe(boosted, sessions[200], **_args(sessions))


def test_bar_on_D_does_not_count_toward_min_bars(sessions):
    """A single leaked bar barely moves a 126-bar median, so the ranking tests above cannot see a
    window that includes D. The min-bars edge can: 99 bars before D plus one on D must stay out."""
    from nidp.services.tpd_model.universe import pit_universe

    D = sessions[200]
    p = make_panel(["EDGE", "OLD"], sessions)
    edge_keep = (p["symbol"] == "EDGE") & (p["as_of_date"] >= pd.Timestamp(sessions[101]))
    p = p[(p["symbol"] == "OLD") | edge_keep]  # EDGE: s[101]..s[199] = 99 bars before D, plus D and later
    assert pit_universe(p, D, n=10, lookback=126, min_bars=100) == ["OLD"]


def test_minimum_bar_requirement(sessions):
    from nidp.services.tpd_model.universe import pit_universe

    p = make_panel(["OLD", "NEW"], sessions)
    p = p[~((p["symbol"] == "NEW") & (p["as_of_date"] < pd.Timestamp(sessions[150])))]  # NEW lists late
    members = pit_universe(p, sessions[200], n=10, lookback=126, min_bars=100)
    assert members == ["OLD"]


def test_ranked_by_median_turnover_with_symbol_tie_break():
    from nidp.services.tpd_model.universe import pit_universe

    s = weekday_sessions("2025-01-01", 130)
    p = make_panel(["BBB", "AAA", "CCC"], s)
    p["turnover"] = 1.0
    assert pit_universe(p, s[-1], n=2, lookback=126, min_bars=100) == ["AAA", "BBB"]


def test_size_cap(panel, sessions):
    from nidp.services.tpd_model.universe import pit_universe

    assert len(pit_universe(panel, sessions[200], n=25, lookback=126, min_bars=100)) == 25
