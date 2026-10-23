"""Naming live F&O contracts for the desk's Top-5 screen.

The resolver is pure, so the part that would silently produce a WRONG premium — naming the contract —
is fully testable without a Kite token and outside market hours. The live read itself is not covered
here and is marked UNVERIFIED in the report: staging stores no platform token
(`platform_token.stored: false`) and the market is closed.
"""
from __future__ import annotations

from datetime import date

from services.kite_live_feed import fno_quotes as fq

# Rows shaped like Kite's own NFO dump: a weekly and a monthly NIFTY option whose symbols follow
# DIFFERENT patterns, which is exactly why a symbol must be read from the dump and never assembled.
NFO = [
    {"tradingsymbol": "NIFTY2510722800PE", "name": "NIFTY", "expiry": date(2026, 10, 27),
     "strike": 22800.0, "instrument_type": "PE", "lot_size": 65},
    {"tradingsymbol": "NIFTY2510722800CE", "name": "NIFTY", "expiry": date(2026, 10, 27),
     "strike": 22800.0, "instrument_type": "CE", "lot_size": 65},
    {"tradingsymbol": "NIFTY26NOV22500PE", "name": "NIFTY", "expiry": date(2026, 11, 24),
     "strike": 22500.0, "instrument_type": "PE", "lot_size": 65},
    {"tradingsymbol": "NIFTY26OCTFUT", "name": "NIFTY", "expiry": date(2026, 10, 27),
     "strike": 0.0, "instrument_type": "FUT", "lot_size": 65},
    {"tradingsymbol": "RELIANCE26OCT2550PE", "name": "RELIANCE", "expiry": date(2026, 10, 27),
     "strike": 2550.0, "instrument_type": "PE", "lot_size": 275},
]
INDEX = fq.index_instruments(NFO)


def leg(**over):
    base = {"kind": "option", "underlying": "NIFTY", "expiry": "2026-10-27",
            "strike": 22800, "option_type": "put"}
    base.update(over)
    return base


def test_an_option_leg_resolves_to_the_exchange_s_own_symbol():
    keys, unresolved = fq.resolve([leg()], INDEX)
    assert keys == {0: "NFO:NIFTY2510722800PE"}
    assert unresolved == []


def test_a_weekly_and_a_monthly_of_the_same_underlying_do_not_collide():
    keys, _ = fq.resolve([leg(), leg(expiry="2026-11-24", strike=22500)], INDEX)
    assert keys[0] == "NFO:NIFTY2510722800PE"
    assert keys[1] == "NFO:NIFTY26NOV22500PE"


def test_call_and_put_at_the_same_strike_are_different_contracts():
    keys, _ = fq.resolve([leg(option_type="call"), leg(option_type="put")], INDEX)
    assert keys[0].endswith("CE") and keys[1].endswith("PE")


def test_a_future_leg_resolves_without_a_strike():
    keys, unresolved = fq.resolve([{"kind": "future", "underlying": "NIFTY", "expiry": "2026-10-27"}], INDEX)
    assert keys == {0: "NFO:NIFTY26OCTFUT"} and unresolved == []


def test_a_stock_option_resolves_too():
    keys, _ = fq.resolve([leg(underlying="RELIANCE", strike=2550)], INDEX)
    assert keys == {0: "NFO:RELIANCE26OCT2550PE"}


def test_an_unlisted_contract_is_named_as_unresolved_not_guessed():
    keys, unresolved = fq.resolve([leg(strike=99999)], INDEX)
    assert keys == {}
    assert len(unresolved) == 1 and "no listed contract" in unresolved[0]["reason"]


def test_a_cash_leg_is_not_an_fno_contract():
    keys, unresolved = fq.resolve([{"kind": "cash", "underlying": "RELIANCE"}], INDEX)
    assert keys == {} and unresolved[0]["index"] == 0


def test_a_missing_field_never_produces_a_key():
    for bad in (leg(expiry=None), leg(strike=None), leg(option_type=None), leg(underlying="")):
        keys, unresolved = fq.resolve([bad], INDEX)
        assert keys == {}, bad
        assert unresolved, bad


def test_resolution_is_case_and_date_format_tolerant():
    keys, _ = fq.resolve([leg(underlying="nifty", expiry="2026-10-27T00:00:00")], INDEX)
    assert keys == {0: "NFO:NIFTY2510722800PE"}


# ── the answer ──────────────────────────────────────────────────────────────

def test_prices_are_read_per_leg_and_a_missing_one_is_absent_not_zero():
    keys = {0: "NFO:A", 1: "NFO:B"}
    answer = {"NFO:A": {"last_price": 136.65, "ohlc": {"close": 225.3}, "oi": 7778745, "volume": 1322963},
              "NFO:B": {}}
    out = fq.prices_from(answer, keys)
    assert out[0]["last_price"] == 136.65
    assert out[0]["previous_close"] == 225.3
    assert out[0]["oi"] == 7778745
    assert 1 not in out, "a leg without a price must be absent, never defaulted to zero"


def test_a_quote_answer_that_is_empty_yields_nothing():
    assert fq.prices_from({}, {0: "NFO:A"}) == {}
    assert fq.prices_from(None, {0: "NFO:A"}) == {}


def test_the_leg_cap_is_small_enough_for_one_rest_call():
    # Five ideas x four legs, with headroom. The point is that this never becomes a chain subscription.
    assert 8 <= fq.MAX_LEGS <= 60
