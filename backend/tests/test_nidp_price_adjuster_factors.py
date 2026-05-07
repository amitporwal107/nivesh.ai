"""Pure-Python tests for price_adjuster.factors.

The math here is the *whole correctness story* for adjusted prices.
Backtests, technical indicators, and 52-week-high lookups all
silently lie if these factors drift. Treat the assertions as a spec.
"""
from __future__ import annotations

from datetime import date

from nidp.services.price_adjuster.factors import (
    CorpActionEvent,
    bonus_factor,
    build_events,
    cumulative_factors_for_dates,
    dividend_factor,
    split_factor,
)


# ── split_factor ────────────────────────────────────────────────────
def test_split_factor_10_to_2():
    """Classic Reliance-style 10 → 2 split: factor 0.2."""
    assert split_factor(10.0, 2.0) == 0.2


def test_split_factor_5_to_1():
    assert split_factor(5.0, 1.0) == 0.2


def test_split_factor_1_to_2_reverse_split():
    """Reverse split 1 → 2 is mathematically supported (factor = 2)."""
    assert split_factor(1.0, 2.0) == 2.0


def test_split_factor_invalid_inputs():
    assert split_factor(None, 2.0) is None
    assert split_factor(10.0, None) is None
    assert split_factor(0, 2.0) is None
    assert split_factor(10.0, -2.0) is None
    assert split_factor(10.0, 10.0) is None     # no actual split


# ── bonus_factor ────────────────────────────────────────────────────
def test_bonus_factor_one_for_one():
    """1:1 bonus → factor 0.5 (each share's price halves)."""
    assert bonus_factor("1:1") == 0.5


def test_bonus_factor_one_for_five():
    """1:5 bonus → factor 5/6 ≈ 0.833."""
    assert abs(bonus_factor("1:5") - (5 / 6)) < 1e-9


def test_bonus_factor_two_for_one():
    """2:1 bonus → factor 1/3 ≈ 0.333."""
    assert abs(bonus_factor("2:1") - (1 / 3)) < 1e-9


def test_bonus_factor_with_slash_separator():
    """Some CA filings use '1/1' instead of '1:1'."""
    assert bonus_factor("1/1") == 0.5


def test_bonus_factor_invalid_inputs():
    assert bonus_factor(None) is None
    assert bonus_factor("") is None
    assert bonus_factor("not a ratio") is None
    assert bonus_factor("0:1") is None        # no new shares
    assert bonus_factor("1:0") is None        # no held shares (would div-by-0)


# ── dividend_factor ─────────────────────────────────────────────────
def test_dividend_factor_basic():
    """₹5 dividend on ₹100 close → factor 0.95."""
    assert dividend_factor(5.0, 100.0) == 0.95


def test_dividend_factor_invalid_inputs():
    assert dividend_factor(None, 100.0) is None
    assert dividend_factor(5.0, None) is None
    assert dividend_factor(0, 100.0) is None
    assert dividend_factor(-5, 100.0) is None
    assert dividend_factor(5.0, 0) is None
    # Dividend > prev close → almost certainly a data error
    assert dividend_factor(150.0, 100.0) is None


# ── build_events ────────────────────────────────────────────────────
def test_build_events_skips_uncomputable_rows():
    raw = [
        # Computable
        {"symbol": "X", "ex_date": date(2026, 3, 1),
         "action_type": "SPLIT", "face_value_pre": 10, "face_value_post": 2},
        # SPLIT missing face values
        {"symbol": "X", "ex_date": date(2026, 4, 1),
         "action_type": "SPLIT", "face_value_pre": None, "face_value_post": None},
        # BONUS computable
        {"symbol": "X", "ex_date": date(2026, 5, 1),
         "action_type": "BONUS", "ratio": "1:1"},
        # Unknown action type
        {"symbol": "X", "ex_date": date(2026, 6, 1),
         "action_type": "BUYBACK"},
    ]
    events = build_events(raw, lambda s, d: None)
    assert len(events) == 2
    assert events[0].action_type == "SPLIT"
    assert events[1].action_type == "BONUS"


def test_build_events_dividend_uses_prev_close_lookup():
    raw = [
        {"symbol": "X", "ex_date": date(2026, 3, 1),
         "action_type": "DIVIDEND", "dividend_amount": 5.0},
    ]
    # Lookup returns prev close
    events = build_events(raw, lambda s, d: 100.0)
    assert len(events) == 1
    e = events[0]
    assert e.pret_factor == 1.0      # PRET unaffected by dividends
    assert e.tret_factor == 0.95     # TRET captures the cash payout


def test_build_events_dividend_skipped_when_no_prev_close():
    raw = [
        {"symbol": "X", "ex_date": date(2026, 3, 1),
         "action_type": "DIVIDEND", "dividend_amount": 5.0},
    ]
    events = build_events(raw, lambda s, d: None)
    assert events == []


# ── cumulative_factors_for_dates ────────────────────────────────────
def test_cumulative_no_events_returns_unity():
    target_dates = [date(2026, 1, 1), date(2026, 6, 1)]
    out = cumulative_factors_for_dates([], target_dates)
    assert out == [(1.0, 1.0, None, None), (1.0, 1.0, None, None)]


def test_cumulative_single_split_applies_to_prior_dates_only():
    """Split on 2026-03-15 (factor 0.2). Prices BEFORE that get
    factor 0.2; prices ON or AFTER get factor 1.0."""
    events = [CorpActionEvent("X", date(2026, 3, 15), "SPLIT", 0.2, 0.2)]
    target_dates = [
        date(2026, 1, 1),    # before — full factor
        date(2026, 3, 14),   # day before ex-date — full factor
        date(2026, 3, 15),   # ex-date itself — already adjusted by NSE
        date(2026, 3, 16),   # after
        date(2026, 6, 1),    # later
    ]
    out = cumulative_factors_for_dates(events, target_dates)
    pret_factors = [t[0] for t in out]
    assert pret_factors == [0.2, 0.2, 1.0, 1.0, 1.0]
    # last_event_ex_date populated for prior dates only
    assert out[0][2] == date(2026, 3, 15)
    assert out[1][2] == date(2026, 3, 15)
    assert out[2][2] is None


def test_cumulative_multiple_events_compose():
    """Two events: SPLIT 5:1 (factor 0.2) on 2026-03-15, BONUS 1:1
    (factor 0.5) on 2026-06-15. A price BEFORE both should get
    0.2 × 0.5 = 0.1. A price BETWEEN should get 0.5. After both: 1.0."""
    events = [
        CorpActionEvent("X", date(2026, 3, 15), "SPLIT", 0.2, 0.2),
        CorpActionEvent("X", date(2026, 6, 15), "BONUS", 0.5, 0.5),
    ]
    target_dates = [
        date(2026, 1, 1),    # before both
        date(2026, 4, 1),    # between
        date(2026, 7, 1),    # after both
    ]
    out = cumulative_factors_for_dates(events, target_dates)
    pret = [t[0] for t in out]
    assert abs(pret[0] - 0.1) < 1e-9
    assert abs(pret[1] - 0.5) < 1e-9
    assert pret[2] == 1.0


def test_cumulative_dividend_does_not_touch_pret():
    """A pure dividend event leaves pret_factor unchanged but
    tret_factor reflects the payout."""
    events = [
        CorpActionEvent("X", date(2026, 3, 15), "DIVIDEND", 1.0, 0.95),
    ]
    target_dates = [date(2026, 1, 1), date(2026, 4, 1)]
    out = cumulative_factors_for_dates(events, target_dates)
    assert out[0][0] == 1.0     # pret unaffected
    assert out[0][1] == 0.95    # tret captures cash dividend
    assert out[1] == (1.0, 1.0, None, None)


def test_cumulative_unsorted_events_handled():
    """Events arriving in any order get sorted internally."""
    events = [
        CorpActionEvent("X", date(2026, 6, 15), "BONUS", 0.5, 0.5),
        CorpActionEvent("X", date(2026, 3, 15), "SPLIT", 0.2, 0.2),
    ]
    out = cumulative_factors_for_dates(events, [date(2026, 1, 1)])
    assert abs(out[0][0] - 0.1) < 1e-9


def test_cumulative_last_event_type_for_diagnostics():
    """The most-recent event AFTER the date should be reported as
    last_event_*."""
    events = [
        CorpActionEvent("X", date(2026, 3, 15), "SPLIT", 0.2, 0.2),
        CorpActionEvent("X", date(2026, 6, 15), "BONUS", 0.5, 0.5),
    ]
    out = cumulative_factors_for_dates(events, [date(2026, 1, 1), date(2026, 4, 1)])
    # For 2026-01-01: NEXT event is the SPLIT on 2026-03-15
    assert out[0][2] == date(2026, 3, 15)
    assert out[0][3] == "SPLIT"
    # For 2026-04-01: NEXT event is the BONUS on 2026-06-15
    assert out[1][2] == date(2026, 6, 15)
    assert out[1][3] == "BONUS"
