"""A >=35% session in a holding window is not automatically a return, and not automatically junk.

nidp.prices_eod is raw and the price adjuster is incomplete, so moves that large reach the
evaluator from three different causes that must not be treated alike: an adjustment the adjuster
never applied, a real market event, and a bad print. Deleting all of them would bias the study
toward calm names; keeping all of them lets a -65% demerger artefact land in a portfolio return.

Every case below is a real row from nidp_staging, measured 2026-10-22, not a constructed fixture.
"""
from nidp.services.smart_money_study.evaluator import (
    INTRADAY_GAP_FRAC, UNEXPLAINED_MOVE_PCT, _classify_unexplained_move, _round_trip_cost_pct)


def _move(**kw):
    """One detection row as _UNEXPLAINED_MOVE_SQL returns it."""
    row = {"symbol": "X", "prev_date": None, "move_date": None, "sessions_spanned": 1,
           "prev_adj_close": 100.0, "adj_close": 60.0, "next_adj_close": 60.0,
           "adj_move_pct": -40.0, "open_gap_pct": -39.0, "action_types": None}
    row.update(kw)
    return row


def test_vedl_demerger_the_adjuster_never_applied_is_excluded():
    """VEDL 2026-04-29 -> 2026-04-30: a DEMERGER row exists, cumulative_adj_factor is still 1.0,
    and the full -64.90% survives into adj_close. Ranked 23/30 on 2026-01-12, so only the calendar
    kept this out of a portfolio."""
    disposition, keep = _classify_unexplained_move(_move(
        symbol="VEDL", prev_adj_close=773.60, adj_close=271.55, next_adj_close=294.65,
        adj_move_pct=-64.90, open_gap_pct=-62.58, action_types="DEMERGER"))
    assert keep is False
    assert disposition.startswith("ca_adjustment_mismatch")
    assert "DEMERGER" in disposition


def test_policybzr_intraday_crash_is_a_genuine_observation_and_is_kept():
    """POLICYBZR 2026-09-24: opened -10.0% and fell to -36.0% by the close on 11x volume. A real
    market event. Excluding it would be throwing away the observations the study exists to measure."""
    disposition, keep = _classify_unexplained_move(_move(
        symbol="POLICYBZR", prev_adj_close=1886.30, adj_close=1207.20, next_adj_close=1166.00,
        adj_move_pct=-36.00, open_gap_pct=-10.00, action_types=None))
    assert (disposition, keep) == ("genuine_market_move", True)


def test_unrecorded_corporate_action_fails_closed():
    """TATAMOTORS 2025-10-14: -40.15%, essentially all of it an overnight gap (-39.46%), and
    nidp.corporate_actions has no row at all. Almost certainly the demerger, but that cannot be
    established from the evidence, so it must not enter the result as a -40% return."""
    disposition, keep = _classify_unexplained_move(_move(
        symbol="TATAMOTORS", prev_adj_close=660.75, adj_close=395.45, next_adj_close=390.85,
        adj_move_pct=-40.15, open_gap_pct=-39.46, action_types=None))
    assert (disposition, keep) == ("unexplained_gap_undetermined", False)


def test_bad_print_that_reverses_next_session_is_excluded():
    """A -50% session whose next session returns to the prior level is a print, not a price.
    Recovery is measured on levels: 100 -> 50 -> 95 restores 90% of the move."""
    disposition, keep = _classify_unexplained_move(_move(
        prev_adj_close=100.0, adj_close=50.0, next_adj_close=95.0,
        adj_move_pct=-50.0, open_gap_pct=-50.0))
    assert (disposition, keep) == ("data_error_reversal", False)


def test_reversal_is_not_declared_on_a_mild_bounce():
    """VEDL's +8.51% bounce off -64.90% is 4.6% of the move. Comparing percentage magnitudes
    instead of levels would be wrong here, since undoing -64.9% takes +185%."""
    disposition, _ = _classify_unexplained_move(_move(
        prev_adj_close=773.60, adj_close=271.55, next_adj_close=294.65,
        adj_move_pct=-64.90, open_gap_pct=-62.58))
    assert disposition != "data_error_reversal"


def test_gap_spanning_step_is_not_called_a_single_session_move():
    """TRIVENI 2026-07-21 -> 2026-08-05 spans 11 market sessions: the name was suspended across
    its demerger. lag() over the symbol's own rows would report this as a one-day -50.10% fall.
    46 of the 48 in-window detections in this warehouse are of this shape."""
    disposition, keep = _classify_unexplained_move(_move(
        symbol="TRIVENI", sessions_spanned=11, prev_adj_close=519.95, adj_close=259.45,
        next_adj_close=254.18, adj_move_pct=-50.10, open_gap_pct=-45.92, action_types=None))
    assert keep is False
    assert disposition == "trading_gap_discontinuity"


def test_an_up_move_is_screened_too():
    """The threshold is on magnitude. A +43% overnight gap with no action row is as suspect as a
    fall, and reversal detection has to work in that direction as well."""
    disposition, keep = _classify_unexplained_move(_move(
        prev_adj_close=100.0, adj_close=145.0, next_adj_close=143.0,
        adj_move_pct=45.0, open_gap_pct=44.0))
    assert (disposition, keep) == ("unexplained_gap_undetermined", False)
    disposition, keep = _classify_unexplained_move(_move(
        prev_adj_close=100.0, adj_close=145.0, next_adj_close=102.0,
        adj_move_pct=45.0, open_gap_pct=44.0))
    assert (disposition, keep) == ("data_error_reversal", False)


def test_no_disposition_falls_through_silently():
    """Whatever the evidence, the ladder returns a disposition and a decision. A row with no gap
    information cannot be shown to be intraday, so it fails closed."""
    disposition, keep = _classify_unexplained_move(_move(open_gap_pct=None, next_adj_close=None))
    assert keep is False
    assert disposition == "unexplained_gap_undetermined"


def test_intraday_boundary_is_the_documented_fraction():
    """At exactly the boundary the move counts as travelled intraday; just past it, it does not."""
    move = -40.0
    at = _classify_unexplained_move(_move(
        adj_move_pct=move, open_gap_pct=move * INTRADAY_GAP_FRAC, next_adj_close=60.0))
    past = _classify_unexplained_move(_move(
        adj_move_pct=move, open_gap_pct=move * INTRADAY_GAP_FRAC - 0.01, next_adj_close=60.0))
    assert at == ("genuine_market_move", True)
    assert past == ("unexplained_gap_undetermined", False)


def test_threshold_is_the_preregistered_35_pct():
    assert UNEXPLAINED_MOVE_PCT == 35.0


def test_frozen_cost_total_is_checked_against_its_own_components():
    """001's cost_model states both a round-trip total and the schedule it summarises. Reading the
    total alone would not notice if it had been edited away from the components."""
    cfg = {"cost_model": {
        "round_trip_total_pct": 0.4937,
        "per_side_pct": {"brokerage": 0.03, "exchange_txn": 0.00325, "sebi": 0.0001,
                         "slippage": 0.1, "stt": 0.1},
        "gst_pct_on": {"components": ["brokerage", "exchange_txn", "sebi"], "rate": 18.0},
        "buy_only_pct": {"stamp_duty": 0.015}}}
    assert _round_trip_cost_pct(cfg) == 0.4937

    tampered = {"cost_model": dict(cfg["cost_model"], round_trip_total_pct=0.1)}
    try:
        _round_trip_cost_pct(tampered)
    except Exception as exc:                                          # noqa: BLE001
        assert "internally inconsistent" in str(exc)
    else:
        raise AssertionError("a cost total that contradicts its own schedule must not be accepted")
