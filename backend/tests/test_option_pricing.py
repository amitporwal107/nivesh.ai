"""services/option_pricing.py — Black-76 price, implied volatility and Greeks for a European option on a forward.

Pure functions, no network and no database. Every expected figure below is worked by hand here from the
formulas in the module's docstring; the normal-distribution values are checked against the standard library's
own `statistics.NormalDist`, which shares no code with the module.

    d1 = [ln(F/K) + σ²T/2] / (σ√T)        d2 = d1 − σ√T        DF = e^(−rT)
    call = DF·[F·N(d1) − K·N(d2)]         put = DF·[K·N(−d2) − F·N(−d1)]

Case A — at the money on the forward, no discounting: F = K = 100, σ = 20%, T = 1 year, r = 0
    σ√T = 0.20            d1 = (0 + 0.04/2)/0.20 = 0.10          d2 = −0.10
    N(0.10) = 0.5398278   N(−0.10) = 0.4601722                   φ(0.10) = 0.3969525
    call = 100×(0.5398278 − 0.4601722) = 100×0.0796556 = 7.9656  put = the same (F = K)
    delta  call = N(d1) = 0.5398278                              put = −N(−d1) = −0.4601722
    gamma  = φ(d1)/(F·σ√T) = 0.3969525/(100×0.20) = 0.01984763
    vega   = F·φ(d1)·√T = 39.69525 per 1.00 of volatility → 0.3969525 per volatility point
    theta  = −F·φ(d1)·σ/(2√T) = −100×0.3969525×0.20/2 = −3.969525 a year → −0.01087541 a day (÷365)

Case B — the textbook example for Black's model (Hull, "Options, Futures, and Other Derivatives": a four-month
European put on a futures price of 20 struck at 20, r = 9%, σ = 25%; the book's answer is 1.12)
    σ√T = 0.25×√(1/3) = 0.1443376     d1 = 0.0721688     d2 = −0.0721688
    N(d1) = 0.5287662                 N(−d1) = 0.4712338  DF = e^(−0.03) = 0.9704455
    put = 0.9704455×20×(0.5287662 − 0.4712338) = 0.9704455×1.150648 = 1.116641            → 1.12

Case C — in the money, with discounting: F = 105, K = 100, σ = 30%, T = 0.5 year, r = 5%
    ln(105/100) = 0.0487902    σ√T = 0.30×0.7071068 = 0.2121320    σ²T/2 = 0.0225
    d1 = (0.0487902 + 0.0225)/0.2121320 = 0.3360651               d2 = 0.3360651 − 0.2121320 = 0.1239330
    N(d1) = 0.6315891          N(d2) = 0.5493158                   φ(d1) = 0.3770383     DF = e^(−0.025) = 0.9753099
    call = 0.9753099×(105×0.6315891 − 100×0.5493158) = 0.9753099×11.385276 = 11.104167
    put  = 0.9753099×(100×0.4506842 − 105×0.3684109) = 0.9753099×6.385271  = 6.227618
    parity: call − put = 4.876550 = DF×(F − K) = 0.9753099×5
    delta  call = DF·N(d1) = 0.6159951                             put = −DF·N(−d1) = −0.3593148
    gamma  = DF·φ(d1)/(F·σ√T) = 0.9753099×0.3770383/(105×0.2121320) = 0.01650945
    vega   = DF·F·φ(d1)·√T/100 = 0.9753099×105×0.3770383×0.7071068/100 = 0.2730250 per volatility point
    decay  = DF·F·φ(d1)·σ/(2√T) = 0.9753099×105×0.3770383×0.30/1.4142136 = 8.190751 a year
    theta  call = (r·call − decay)/365 = (0.5552084 − 8.190751)/365 = −0.02091929 a day
           put  = (r·put  − decay)/365 = (0.3113809 − 8.190751)/365 = −0.02158731 a day
"""
from __future__ import annotations

import math
from datetime import date
from statistics import NormalDist

import pytest

from services import option_pricing as op

STD = NormalDist()
CALL, PUT = "CE", "PE"


# ── the normal distribution ──────────────────────────────────────────────────

def test_normal_cdf_matches_the_printed_table_and_the_standard_library():
    # the usual table values
    for x, expected in ((0.0, 0.5), (1.0, 0.8413447), (1.96, 0.9750021), (-1.645, 0.0499849), (0.1, 0.5398278)):
        assert op.norm_cdf(x) == pytest.approx(expected, abs=5e-8), x
    for i in range(-800, 801):
        x = i / 100
        assert op.norm_cdf(x) == pytest.approx(STD.cdf(x), abs=1e-12), x
        assert op.norm_pdf(x) == pytest.approx(STD.pdf(x), abs=1e-12), x
    # symmetric, and the tails stay inside [0, 1]
    assert op.norm_cdf(-2.5) + op.norm_cdf(2.5) == pytest.approx(1.0, abs=1e-15)
    assert 0.0 <= op.norm_cdf(-40.0) < 1e-300 and op.norm_cdf(40.0) == 1.0


# ── hand-worked prices and Greeks ────────────────────────────────────────────

def test_case_a_at_the_money_on_the_forward_without_discounting():
    F, K, T, vol, r = 100.0, 100.0, 1.0, 0.20, 0.0
    # 7-figure table values of N carry the product to four decimals
    assert op.price(CALL, F, K, T, vol, r) == pytest.approx(7.9656, abs=5e-5)
    assert op.price(PUT, F, K, T, vol, r) == pytest.approx(7.9656, abs=5e-5)
    assert op.delta(CALL, F, K, T, vol, r) == pytest.approx(0.5398278, abs=5e-8)
    assert op.delta(PUT, F, K, T, vol, r) == pytest.approx(-0.4601722, abs=5e-8)
    assert op.gamma(F, K, T, vol, r) == pytest.approx(0.01984763, abs=5e-9)
    assert op.vega_per_point(F, K, T, vol, r) == pytest.approx(0.3969525, abs=5e-8)
    assert op.theta_per_day(CALL, F, K, T, vol, r) == pytest.approx(-0.01087541, abs=5e-9)
    assert op.theta_per_day(PUT, F, K, T, vol, r) == pytest.approx(-0.01087541, abs=5e-9)


def test_case_b_the_textbook_put_on_a_future_is_1_12():
    put = op.price(PUT, 20.0, 20.0, 4 / 12, 0.25, 0.09)
    assert put == pytest.approx(1.116641, abs=5e-7)
    assert round(put, 2) == 1.12
    # F = K, so the call costs the same
    assert op.price(CALL, 20.0, 20.0, 4 / 12, 0.25, 0.09) == pytest.approx(put, abs=1e-12)


def test_case_c_in_the_money_with_discounting():
    F, K, T, vol, r = 105.0, 100.0, 0.5, 0.30, 0.05
    call, put = op.price(CALL, F, K, T, vol, r), op.price(PUT, F, K, T, vol, r)
    assert call == pytest.approx(11.104167, abs=5e-7)
    assert put == pytest.approx(6.227618, abs=5e-7)
    assert call - put == pytest.approx(math.exp(-0.025) * 5.0, abs=1e-12)
    assert op.delta(CALL, F, K, T, vol, r) == pytest.approx(0.6159951, abs=5e-8)
    assert op.delta(PUT, F, K, T, vol, r) == pytest.approx(-0.3593148, abs=5e-8)
    assert op.gamma(F, K, T, vol, r) == pytest.approx(0.01650945, abs=5e-9)
    assert op.vega_per_point(F, K, T, vol, r) == pytest.approx(0.2730250, abs=5e-8)
    assert op.theta_per_day(CALL, F, K, T, vol, r) == pytest.approx(-0.02091929, abs=5e-9)
    assert op.theta_per_day(PUT, F, K, T, vol, r) == pytest.approx(-0.02158731, abs=5e-9)


def test_greeks_bundle_is_the_five_single_functions():
    F, K, T, vol, r = 105.0, 100.0, 0.5, 0.30, 0.05
    for kind in (CALL, PUT):
        g = op.greeks(kind, F, K, T, vol, r)
        assert g == op.Greeks(
            delta=op.delta(kind, F, K, T, vol, r), gamma=op.gamma(F, K, T, vol, r),
            theta=op.theta_per_day(kind, F, K, T, vol, r), vega=op.vega_per_point(F, K, T, vol, r))


def test_the_default_rate_is_the_named_constant():
    assert op.price(CALL, 105.0, 100.0, 0.5, 0.30) == op.price(CALL, 105.0, 100.0, 0.5, 0.30, op.RISK_FREE_RATE)
    assert op.implied_vol(CALL, 11.0, 105.0, 100.0, 0.5) == op.implied_vol(CALL, 11.0, 105.0, 100.0, 0.5, op.RISK_FREE_RATE)


# ── Greeks against finite differences of the price ───────────────────────────

GRID = [
    # forward, strike, years, volatility, rate
    (100.0, 100.0, 1.0, 0.20, 0.0),
    (105.0, 100.0, 0.5, 0.30, 0.05),
    (22834.8, 22700.0, 14 / 365, 0.14, 0.0575),
    (22834.8, 24000.0, 14 / 365, 0.14, 0.0575),
    (1174.3, 1100.0, 41 / 365, 0.28, 0.0575),
    (50.0, 80.0, 2.0, 0.60, 0.07),
]


@pytest.mark.parametrize("F,K,T,vol,r", GRID)
@pytest.mark.parametrize("kind", [CALL, PUT])
def test_greeks_are_the_slopes_of_the_price(kind, F, K, T, vol, r):
    p = lambda f=F, t=T, v=vol: op.price(kind, f, K, t, v, r)  # noqa: E731
    h = F * 1e-4
    # a difference quotient carries its own error of order h², so the slopes are matched to four figures
    assert op.delta(kind, F, K, T, vol, r) == pytest.approx((p(f=F + h) - p(f=F - h)) / (2 * h), rel=1e-4, abs=1e-9)
    assert op.gamma(F, K, T, vol, r) == pytest.approx((p(f=F + h) - 2 * p() + p(f=F - h)) / h ** 2, rel=1e-3, abs=1e-9)
    # one volatility point = 0.01; the slope is taken over ±0.0001 and scaled to a point
    assert op.vega_per_point(F, K, T, vol, r) == pytest.approx((p(v=vol + 1e-4) - p(v=vol - 1e-4)) / 2e-4 / 100, rel=1e-4, abs=1e-9)
    # one calendar day = 1/365 of a year; a day later there is less time left, forward and volatility unchanged
    dt = 1e-5
    assert op.theta_per_day(kind, F, K, T, vol, r) == pytest.approx((p(t=T - dt) - p(t=T + dt)) / (2 * dt) / 365, rel=1e-4, abs=1e-9)


# ── price → implied volatility → price ───────────────────────────────────────

MONEYNESS = [0.80, 0.90, 0.95, 0.98, 1.00, 1.02, 1.05, 1.10, 1.25]   # strike ÷ forward
TENORS = [1, 6, 14, 41, 77, 168, 350, 730]                            # calendar days
VOLS = [0.05, 0.10, 0.14, 0.25, 0.45, 0.80, 1.50]


def test_round_trip_across_moneyness_tenor_and_volatility():
    F, r = 22834.8, op.RISK_FREE_RATE
    checked = skipped = 0
    for kind in (CALL, PUT):
        for m in MONEYNESS:
            for days in TENORS:
                for vol in VOLS:
                    K, T = F * m, days / 365
                    px = op.price(kind, F, K, T, vol, r)
                    time_value = px - op.intrinsic(kind, F, K, T, r)
                    iv = op.implied_vol(kind, px, F, K, T, r)
                    if time_value < 1e-9 * F:
                        # nothing but intrinsic value is left in the price: there is no volatility to read back
                        assert iv is None or op.price(kind, F, K, T, iv, r) == pytest.approx(px, abs=1e-6), (kind, m, days, vol)
                        skipped += 1
                        continue
                    assert iv is not None, (kind, m, days, vol)
                    assert op.price(kind, F, K, T, iv, r) == pytest.approx(px, abs=1e-6), (kind, m, days, vol)
                    # where the price still moves with volatility, the volatility itself comes back
                    if op.vega_per_point(F, K, T, vol, r) > 1e-4:
                        assert iv == pytest.approx(vol, abs=1e-6), (kind, m, days, vol)
                    checked += 1
    assert checked > 700 and skipped < 300, (checked, skipped)


def test_put_call_parity_and_one_volatility_for_both_sides():
    """C − P = DF·(F − K) at every strike, so a call and a put priced off one forward imply one volatility."""
    for F, K, T, vol, r in GRID:
        call, put = op.price(CALL, F, K, T, vol, r), op.price(PUT, F, K, T, vol, r)
        assert call - put == pytest.approx(math.exp(-r * T) * (F - K), rel=1e-12, abs=1e-9)
        iv_call, iv_put = op.implied_vol(CALL, call, F, K, T, r), op.implied_vol(PUT, put, F, K, T, r)
        assert iv_call == pytest.approx(vol, abs=1e-6) and iv_put == pytest.approx(vol, abs=1e-6)
        assert iv_call == pytest.approx(iv_put, abs=1e-6)


def test_a_wrong_forward_splits_the_two_sides_apart():
    """Why the forward matters: prices struck off F = 100 read on a forward of 99 give the call a higher
    volatility than the put. (The mean of the two stays near the true 20%.)"""
    F, K, T, vol, r = 100.0, 100.0, 30 / 365, 0.20, 0.0
    call, put = op.price(CALL, F, K, T, vol, r), op.price(PUT, F, K, T, vol, r)
    low_call, low_put = op.implied_vol(CALL, call, 99.0, K, T, r), op.implied_vol(PUT, put, 99.0, K, T, r)
    assert low_call > vol + 0.03 and low_put < vol - 0.03
    assert (low_call + low_put) / 2 == pytest.approx(vol, abs=0.005)


# ── monotonicity and bounds ──────────────────────────────────────────────────

def test_price_rises_with_volatility_and_implied_volatility_rises_with_price():
    F, K, T, r = 100.0, 105.0, 0.25, 0.05
    for kind in (CALL, PUT):
        prices = [op.price(kind, F, K, T, v / 100, r) for v in range(1, 301)]
        assert all(b > a for a, b in zip(prices, prices[1:])), kind
        low = op.intrinsic(kind, F, K, T, r)
        ivs = [op.implied_vol(kind, low + step * 0.5, F, K, T, r) for step in range(1, 40)]
        assert all(v is not None for v in ivs)
        assert all(b > a for a, b in zip(ivs, ivs[1:])), kind


def test_calls_fall_and_puts_rise_with_the_strike():
    F, T, vol, r = 100.0, 0.25, 0.20, 0.05
    strikes = [float(k) for k in range(60, 141, 5)]
    calls = [op.price(CALL, F, k, T, vol, r) for k in strikes]
    puts = [op.price(PUT, F, k, T, vol, r) for k in strikes]
    assert all(b < a for a, b in zip(calls, calls[1:]))
    assert all(b > a for a, b in zip(puts, puts[1:]))


@pytest.mark.parametrize("F,K,T,vol,r", GRID)
def test_greek_signs_and_the_links_between_the_two_sides(F, K, T, vol, r):
    df = math.exp(-r * T)
    dc, dp = op.delta(CALL, F, K, T, vol, r), op.delta(PUT, F, K, T, vol, r)
    assert 0.0 < dc < df and -df < dp < 0.0
    assert dc - dp == pytest.approx(df, abs=1e-12)          # from put-call parity
    assert op.gamma(F, K, T, vol, r) > 0 and op.vega_per_point(F, K, T, vol, r) > 0
    # an option is never worth less than its discounted intrinsic value, nor more than its bound
    for kind, cap in ((CALL, df * F), (PUT, df * K)):
        assert op.intrinsic(kind, F, K, T, r) <= op.price(kind, F, K, T, vol, r) < cap


def test_price_with_no_time_or_no_volatility_is_the_intrinsic_value():
    assert op.price(CALL, 110.0, 100.0, 0.0, 0.2, 0.05) == 10.0
    assert op.price(PUT, 110.0, 100.0, 0.0, 0.2, 0.05) == 0.0
    assert op.price(PUT, 90.0, 100.0, 0.5, 0.0, 0.05) == pytest.approx(10.0 * math.exp(-0.025), abs=1e-12)
    assert op.intrinsic(CALL, 110.0, 100.0, 0.5, 0.05) == pytest.approx(10.0 * math.exp(-0.025), abs=1e-12)
    assert op.intrinsic(PUT, 110.0, 100.0, 0.5, 0.05) == 0.0


# ── the None cases: never a made-up number ───────────────────────────────────

def test_implied_volatility_is_none_below_or_at_intrinsic_value():
    F, K, T, r = 110.0, 100.0, 0.5, 0.05
    low = op.intrinsic(CALL, F, K, T, r)                     # 10 × e^(−0.025) = 9.7531
    assert low == pytest.approx(9.753099, abs=5e-7)
    assert op.implied_vol(CALL, low - 0.5, F, K, T, r) is None   # below intrinsic: no volatility prices it
    assert op.implied_vol(CALL, low, F, K, T, r) is None         # exactly intrinsic: no time value to read
    assert op.implied_vol(CALL, low + 0.5, F, K, T, r) is not None
    assert op.implied_vol(PUT, 9.0, 90.0, 100.0, 0.5, r) is None  # put intrinsic is 10 × e^(−0.025) = 9.7531


def test_implied_volatility_is_none_for_a_zero_or_negative_price():
    for px in (0.0, -1.0):
        assert op.implied_vol(CALL, px, 100.0, 120.0, 0.25, 0.05) is None
        assert op.implied_vol(PUT, px, 100.0, 80.0, 0.25, 0.05) is None


def test_implied_volatility_is_none_when_the_option_expires_today_or_has_expired():
    assert op.implied_vol(CALL, 5.0, 100.0, 100.0, 0.0, 0.05) is None
    assert op.implied_vol(PUT, 5.0, 100.0, 100.0, -1 / 365, 0.05) is None
    assert op.greeks(CALL, 100.0, 100.0, 0.0, 0.2, 0.05) is None
    assert op.delta(CALL, 100.0, 100.0, 0.0, 0.2, 0.05) is None


def test_implied_volatility_is_none_at_or_above_the_price_bound_and_outside_the_volatility_bounds():
    F, K, T, r = 100.0, 100.0, 0.25, 0.05
    df = math.exp(-r * T)
    assert op.implied_vol(CALL, df * F, F, K, T, r) is None          # a call is worth less than DF·F
    assert op.implied_vol(PUT, df * K + 1.0, F, K, T, r) is None     # a put is worth less than DF·K
    # a price that needs more than MAX_VOL (500%) is not answered with the bound
    above = op.price(CALL, F, K, T, op.MAX_VOL + 0.5, r)
    assert above < df * F and op.implied_vol(CALL, above, F, K, T, r) is None
    inside = op.price(CALL, F, K, T, op.MAX_VOL - 0.5, r)
    assert op.implied_vol(CALL, inside, F, K, T, r) == pytest.approx(op.MAX_VOL - 0.5, abs=1e-6)
    # nor is a time value too small for MIN_VOL (0.01%)
    assert op.implied_vol(CALL, op.price(CALL, F, K, T, op.MIN_VOL / 2, r), F, K, T, r) is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -5.0, 0.0])
def test_bad_inputs_give_none_not_a_number(bad):
    assert op.implied_vol(CALL, 5.0, bad, 100.0, 0.25, 0.05) is None
    assert op.implied_vol(CALL, 5.0, 100.0, bad, 0.25, 0.05) is None
    assert op.greeks(CALL, bad, 100.0, 0.25, 0.2, 0.05) is None
    assert op.greeks(CALL, 100.0, bad, 0.25, 0.2, 0.05) is None
    assert op.greeks(CALL, 100.0, 100.0, 0.25, bad, 0.05) is None
    assert op.gamma(100.0, 100.0, 0.25, bad, 0.05) is None
    assert op.vega_per_point(100.0, 100.0, 0.25, bad, 0.05) is None
    assert op.theta_per_day(PUT, 100.0, 100.0, 0.25, bad, 0.05) is None
    assert op.implied_vol(CALL, bad, 100.0, 100.0, 0.25, 0.05) is None   # as the price


def test_an_unknown_option_type_is_an_error_not_a_guess():
    with pytest.raises(ValueError):
        op.price("XX", 100.0, 100.0, 0.25, 0.2, 0.05)
    with pytest.raises(ValueError):
        op.implied_vol("FUT", 5.0, 100.0, 100.0, 0.25, 0.05)


# ── time to expiry and the forward ───────────────────────────────────────────

def test_time_to_expiry_is_calendar_days_over_365_from_the_datas_day():
    assert op.days_between(date(2026, 10, 13), date(2026, 10, 27)) == 14
    assert op.year_fraction(14) == 14 / 365
    assert op.year_fraction(365) == 1.0
    assert op.year_fraction(0) == 0.0          # expires at this day's close: no time left
    assert op.days_between(date(2026, 10, 13), date(2026, 10, 12)) == -1


def test_forward_is_the_same_expiry_future_when_there_is_one():
    # a future expiring with the options is the market's own forward: nothing is carried
    assert op.choose_forward(108.75, 108.0, 14 / 365, 0.0575) == (108.75, "future")
    assert op.choose_forward(108.75, None, 14 / 365, 0.0575) == (108.75, "future")


def test_forward_is_the_spot_carried_at_the_rate_when_no_future_expires_with_the_options():
    # 100 × e^(0.0575 × 73/365) = 100 × e^0.0115 = 101.15664
    fwd, basis = op.choose_forward(None, 100.0, 73 / 365, 0.0575)
    assert basis == "carried spot"
    assert fwd == pytest.approx(101.15664, abs=5e-6)
    assert op.choose_forward(0.0, 100.0, 73 / 365, 0.0575) == (fwd, "carried spot")   # a zero settle is a missing price
    assert op.choose_forward(None, 100.0, 73 / 365)[0] == pytest.approx(100.0 * math.exp(op.RISK_FREE_RATE * 0.2), rel=1e-12)


def test_no_forward_without_a_future_and_a_spot():
    assert op.choose_forward(None, None, 14 / 365, 0.0575) is None
    assert op.choose_forward(None, 0.0, 14 / 365, 0.0575) is None
    assert op.choose_forward(float("nan"), float("inf"), 14 / 365, 0.0575) is None
    assert op.choose_forward(None, None, 14 / 365, 0.0575, pairs=[]) is None


# ── the forward implied by put-call parity ───────────────────────────────────

def test_parity_forward_by_hand():
    # F = K + (C − P)·e^(rT): 100 + (5.00 − 3.00) × e^(0.0575 × 73/365) = 100 + 2 × 1.0115664 = 102.02313
    assert op.parity_forward([(100.0, 5.0, 3.0)], 73 / 365, 0.0575) == pytest.approx(102.02313, abs=5e-6)
    # a put dearer than the call puts the forward below the strike: 100 + (3 − 5) × 1.0115664 = 97.97687
    assert op.parity_forward([(100.0, 3.0, 5.0)], 73 / 365, 0.0575) == pytest.approx(97.97687, abs=5e-6)


def test_parity_forward_is_read_where_the_call_and_the_put_are_closest():
    pairs = [(90.0, 12.4, 1.1), (100.0, 5.0, 3.0), (110.0, 1.2, 9.6)]      # |C − P| = 11.3, 2.0, 8.4
    assert op.parity_forward(pairs, 73 / 365, 0.0575) == pytest.approx(102.02313, abs=5e-6)
    assert op.parity_forward(reversed(pairs), 73 / 365, 0.0575) == pytest.approx(102.02313, abs=5e-6)
    # equally close at two strikes → the lower strike: 100 + (5 − 3) × e^0 = 102, not 105 + (3 − 5) = 103
    assert op.parity_forward([(105.0, 3.0, 5.0), (100.0, 5.0, 3.0)], 73 / 365, 0.0) == 102.0


def test_parity_forward_is_none_without_a_usable_pair_or_time():
    assert op.parity_forward([], 73 / 365) is None
    assert op.parity_forward(None, 73 / 365) is None
    assert op.parity_forward([(100.0, 5.0, 0.0), (110.0, None, 4.0), (0.0, 5.0, 3.0), (120.0, float("nan"), 3.0)], 73 / 365) is None
    assert op.parity_forward([(100.0, 5.0, 3.0)], 0.0) is None            # expires today
    assert op.parity_forward([(100.0, 5.0, 3.0)], -1 / 365) is None


@pytest.mark.parametrize("true_forward,days,vol", [(22805.0, 6, 0.13), (25230.0, 43, 0.125), (1174.3, 14, 0.24), (101.37, 350, 0.45)])
def test_parity_forward_recovers_the_forward_a_chain_was_priced_from_and_both_sides_then_agree(true_forward, days, vol):
    """A synthetic chain priced off one forward with a smile. Parity hands that forward back exactly, whatever
    the smile; and on it every call and put at one strike imply the same volatility."""
    r, t = op.RISK_FREE_RATE, days / 365
    smile = {m: vol + 0.8 * (m - 1.0) ** 2 - 0.15 * (m - 1.0) for m in (0.94, 0.97, 0.99, 1.00, 1.01, 1.03, 1.06)}
    chain = [(true_forward * m, op.price(CALL, true_forward, true_forward * m, t, v, r), op.price(PUT, true_forward, true_forward * m, t, v, r), v)
             for m, v in smile.items()]
    implied = op.parity_forward([(k, c, p) for k, c, p, _ in chain], t, r)
    assert implied == pytest.approx(true_forward, rel=1e-12)
    for k, c, p, v in chain:
        iv_call, iv_put = op.implied_vol(CALL, c, implied, k, t, r), op.implied_vol(PUT, p, implied, k, t, r)
        assert iv_call == pytest.approx(v, abs=1e-6) and iv_put == pytest.approx(v, abs=1e-6), k
    # a carried spot 0.3% below that forward does not: the at-the-money call reads high and the put low
    k, c, p, v = chain[3]
    low = true_forward * 0.997
    assert op.implied_vol(CALL, c, low, k, t, r) > v > op.implied_vol(PUT, p, low, k, t, r)


def test_the_forward_is_chosen_future_first_then_parity_then_the_carried_spot():
    t, r = 73 / 365, 0.0575
    pairs = [(100.0, 5.0, 3.0)]                                            # implies 102.02313
    # 1. a future expiring with the options wins, whatever the options imply
    assert op.choose_forward(108.75, 100.0, t, r, pairs=pairs) == (108.75, "future")
    # 2. no such future: the options' own forward
    fwd, basis = op.choose_forward(None, 100.0, t, r, pairs=pairs)
    assert basis == "put-call parity" and fwd == pytest.approx(102.02313, abs=5e-6)
    assert op.choose_forward(None, None, t, r, pairs=pairs)[1] == "put-call parity"   # it needs no spot
    # 3. no future and no usable pair: the spot carried at the rate, 100 × e^0.0115 = 101.15664
    for none in (None, [], [(100.0, 5.0, 0.0)]):
        fwd, basis = op.choose_forward(None, 100.0, t, r, pairs=none)
        assert basis == "carried spot" and fwd == pytest.approx(101.15664, abs=5e-6)


def test_the_rate_constant_is_the_one_the_exchanges_own_settlement_prices_imply():
    """RISK_FREE_RATE = 5.75%. Where the number comes from: the exchange gives a deep in-the-money call that
    did not trade a theoretical settlement price of  S − K·e^(−rT). Two such NIFTY contracts in the staging
    F&O bhavcopy of 13 Oct 2026 (spot 22,721.95, strike 20,050; public end-of-day data):

        19 Oct expiry, T = 6/365    settle 2,690.89   → K·e^(−rT) = 20,031.06   → r = ln(20050/20031.06)×365/6  = 5.75%
        27 Oct expiry, T = 14/365   settle 2,716.12   → K·e^(−rT) = 20,005.83   → r = ln(20050/20005.83)×365/14 = 5.75%
    """
    assert op.RISK_FREE_RATE == 0.0575
    spot, strike = 22721.95, 20050.0
    for days, settle in ((6, 2690.89), (14, 2716.12)):
        implied = -math.log((spot - settle) / strike) / (days / 365)
        assert implied == pytest.approx(op.RISK_FREE_RATE, abs=5e-5), days
