"""A1 point-in-time universe: membership for D uses only bars strictly before D."""
import pandas as pd

from nidp.tests.services.tpd_model.conftest import make_panel, weekday_sessions


def _args(sessions):
    """min_turnover=0 on purpose: these tests pin point-in-time semantics and ranking, not the
    liquidity rule. Leaving the real Rs 1 cr floor on would filter most of make_panel's synthetic
    symbols and make a PIT failure look like a liquidity pass."""
    return {"max_symbols": 10, "lookback": 126, "min_bars": 100, "min_turnover": 0.0}


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
    assert pit_universe(p, D, max_symbols=10, lookback=126, min_bars=100, min_turnover=0.0) == ["OLD"]


def test_minimum_bar_requirement(sessions):
    from nidp.services.tpd_model.universe import pit_universe

    p = make_panel(["OLD", "NEW"], sessions)
    p = p[~((p["symbol"] == "NEW") & (p["as_of_date"] < pd.Timestamp(sessions[150])))]  # NEW lists late
    members = pit_universe(p, sessions[200], max_symbols=10, lookback=126, min_bars=100, min_turnover=0.0)
    assert members == ["OLD"]


def test_ranked_by_median_turnover_with_symbol_tie_break():
    from nidp.services.tpd_model.universe import pit_universe

    s = weekday_sessions("2025-01-01", 130)
    p = make_panel(["BBB", "AAA", "CCC"], s)
    p["turnover"] = 1.0
    assert pit_universe(p, s[-1], max_symbols=2, lookback=126, min_bars=100, min_turnover=0.0) == ["AAA", "BBB"]


def test_max_symbols_is_a_ceiling_not_the_rule(panel, sessions):
    """It still truncates when asked — but it is OFF by default now, so the universe is sized by
    the filters. The old `n=1000` default WAS the eligibility rule: it put the real floor at
    whatever rank 1000 happened to be (Rs 4.67 cr on 2026-09-30, 4.7x the documented Rs 1 cr)."""
    from nidp.services.tpd_model.universe import pit_universe

    capped = pit_universe(panel, sessions[200], max_symbols=25, lookback=126, min_bars=100, min_turnover=0.0)
    uncapped = pit_universe(panel, sessions[200], lookback=126, min_bars=100, min_turnover=0.0)
    assert len(capped) == 25
    assert len(uncapped) > 25, "default must not truncate"
    assert uncapped[:25] == capped, "the cap takes a prefix of the same ordering"


# ── the liquidity rule the docs always claimed ────────────────────────────────────

def test_symbols_below_the_turnover_floor_are_excluded(sessions):
    from nidp.services.tpd_model.universe import pit_universe

    p = make_panel(["RICH", "POOR"], sessions)
    p.loc[p["symbol"] == "RICH", "turnover"] = 5.0e7     # Rs 5 cr
    p.loc[p["symbol"] == "POOR", "turnover"] = 5.0e6     # Rs 0.5 cr
    assert pit_universe(p, sessions[200], min_bars=100) == ["RICH"]


def test_the_floor_is_the_documented_one_crore(sessions):
    """rules_v1 eligibility.min_traded_value is Rs 1 crore. The universe must use that number."""
    from nidp.services.tpd_model.universe import MIN_MEDIAN_TURNOVER, pit_universe

    assert MIN_MEDIAN_TURNOVER == 1.0e7
    p = make_panel(["JUST_OVER", "JUST_UNDER"], sessions)
    p.loc[p["symbol"] == "JUST_OVER", "turnover"] = 1.01e7
    p.loc[p["symbol"] == "JUST_UNDER", "turnover"] = 0.99e7
    assert pit_universe(p, sessions[200], min_bars=100) == ["JUST_OVER"]


def test_the_floor_is_a_MEDIAN_so_one_spike_does_not_qualify(sessions):
    """A single frenzied session must not buy a year of membership."""
    from nidp.services.tpd_model.universe import pit_universe

    p = make_panel(["SPIKY"], sessions)
    p["turnover"] = 1.0e6                                 # Rs 0.1 cr every day
    p.loc[p["as_of_date"] == pd.Timestamp(sessions[199]), "turnover"] = 1.0e11
    assert pit_universe(p, sessions[200], min_bars=100) == []


def test_min_bars_defaults_to_the_scorer_warmup(sessions):
    """A universe gate stricter than forward.WARMUP_BARS silently drops symbols the model could
    score; looser admits symbols whose features (ret60, sma50_slope) are undefined."""
    from nidp.services.tpd_model.forward import WARMUP_BARS
    from nidp.services.tpd_model.universe import MIN_BARS

    assert MIN_BARS == WARMUP_BARS == 60


# ── training and scoring must see the SAME universe ───────────────────────────────

def test_pit_universe_and_universe_by_session_agree(panel, sessions):
    """universe_by_session feeds training, pit_universe feeds live scoring. If they diverge, every
    forward number is measured against a membership the model was never trained on."""
    from nidp.services.tpd_model.backtest import universe_by_session
    from nidp.services.tpd_model.universe import pit_universe

    for i in (150, 200, 250):
        D = sessions[i]
        assert universe_by_session(panel, [D], min_turnover=0.0)[D] == \
            pit_universe(panel, D, min_turnover=0.0), f"diverged at {D}"


def test_both_apply_the_turnover_floor_identically(sessions):
    from nidp.services.tpd_model.backtest import universe_by_session
    from nidp.services.tpd_model.universe import pit_universe

    p = make_panel(["RICH", "POOR"], sessions)
    p.loc[p["symbol"] == "RICH", "turnover"] = 5.0e7
    p.loc[p["symbol"] == "POOR", "turnover"] = 5.0e6
    D = sessions[200]
    assert universe_by_session(p, [D])[D] == pit_universe(p, D) == ["RICH"]
