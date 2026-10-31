"""Quick Hedge core (services/quick_hedge/calc.py): sizing, rounding, strike choice, payoffs, scenario table.

Every expected number below is worked by hand from the decisions in docs/RISK_AND_HEDGE_GAP_AND_PLAN_20261031.md §4a:
round DOWN to whole lots; strikes from the user's tolerable loss; v1 = long put and put spread; hedge ratio never above
100% of beta-adjusted exposure; a premium is never guessed. The chain below is SYNTHETIC test data, not market data.
"""
import math

import pytest

from services.quick_hedge import calc

SPOT = 23_000.0
LOT = 65
LOT_NOTIONAL = SPOT * LOT                      # 14,95,000


def _puts():
    """Strikes 19,000..23,000 step 50, premium falling smoothly with distance (a farther put is never dearer than a nearer
    one): 120 at 21,850 (23 steps out) and 30 at 19,550 (69 steps out), so 240 at the money."""
    puts = {float(k): round(120 * 4 ** (-((SPOT - k) / 50 - 23) / 46), 2) for k in range(19_000, 23_001, 50)}
    puts[21_850.0], puts[19_550.0] = 120.0, 30.0
    return puts


def _charges(legs, s_t):
    """Stub cost model: 100 rupees at entry, none at expiry."""
    return 100.0 if s_t is None else 0.0


def _run(**kw):
    base = dict(portfolio_value=2_000_000.0, hedgeable_value=2_000_000.0, beta=1.0, spot=SPOT, lot=LOT,
                expiry="2026-12-01", puts=_puts(), tolerance_rs=100_000.0, expected_fall_pct=15.0, r2=0.83,
                charges=_charges)
    base.update(kw)
    return calc.build(**base)


def _mode(res, name):
    return next(m for m in res["modes"] if m["mode"] == name)


# ── rounding and the hedge-ratio cap ────────────────────────────────────────────────────────────────────────────
def test_round_down_and_show_the_residual():
    s = calc.lots_for(2_000_000.0, SPOT, LOT)
    assert s["required_lots"] == pytest.approx(2_000_000 / LOT_NOTIONAL)            # 1.3378
    assert s["executed_lots"] == 1
    assert s["protected_pct"] == pytest.approx(LOT_NOTIONAL / 2_000_000 * 100)      # 74.75
    assert s["residual_pct"] == pytest.approx(100 - 74.75)


def test_smaller_than_one_lot_is_not_hedgeable_and_offers_no_order():
    res = _run(portfolio_value=1_000_000.0, hedgeable_value=1_000_000.0)            # 0.669 lots
    assert res["status"] == "not_hedgeable"
    assert res["modes"] == []
    assert res["reasons"][0]["code"] == "smaller_than_one_lot"
    assert "over-hedge" in res["reasons"][0]["message"]


def test_beta_scales_the_exposure_and_the_cap_is_never_exceeded():
    res = _run(portfolio_value=1_000_000.0, hedgeable_value=1_000_000.0, beta=1.5)  # E = 15,00,000 -> 1.0033 lots
    assert res["exposure"]["beta_adjusted_exposure_rs"] == pytest.approx(1_500_000.0)
    assert res["exposure"]["executed_lots"] == 1
    for value in range(500_000, 20_000_000, 137_000):
        for beta in (0.4, 0.8, 1.0, 1.3, 1.9):
            s = calc.lots_for(value * beta, SPOT, LOT)
            assert s["executed_lots"] * LOT_NOTIONAL <= value * beta + 1e-6          # never more than 100%
            assert 0.0 <= s["protected_pct"] <= 100.0


# ── strike from tolerable loss ─────────────────────────────────────────────────────────────────────────────────
def test_balanced_strike_puts_the_deductible_at_the_tolerance():
    m = _mode(_run(), "balanced")                      # 1,00,000 on 20,00,000 = 5% -> target 21,850 (listed)
    assert m["structure"] == "long_put"
    assert m["legs"][0]["strike"] == 21_850.0
    assert m["deductible_rs"] == pytest.approx(100_000.0)


def test_the_deductible_never_exceeds_the_tolerance():
    m = _mode(_run(tolerance_rs=110_000.0), "balanced")   # 5.5% -> target 21,735 -> lowest listed >= is 21,750
    assert m["legs"][0]["strike"] == 21_750.0
    assert m["deductible_rs"] <= 110_000.0
    assert m["deductible_rs"] == pytest.approx(2_000_000 * (SPOT - 21_750) / SPOT)


def test_maximum_protection_starts_at_half_the_tolerance():
    m = _mode(_run(), "maximum")                       # 2.5% -> target 22,425 -> 22,450
    assert m["legs"][0]["strike"] == 22_450.0
    assert m["deductible_rs"] < _mode(_run(), "balanced")["deductible_rs"]


def test_a_strike_with_no_premium_is_never_used_and_the_next_listed_one_is():
    puts = _puts()
    del puts[21_850.0]
    m = _mode(_run(puts=puts), "balanced")
    assert m["legs"][0]["strike"] == 21_900.0           # the next listed strike with a real premium, so deductible <= tolerance
    assert m["deductible_rs"] <= 100_000.0


def test_no_listed_strike_within_the_tolerance_means_no_idea_not_a_wider_one():
    puts = {k: v for k, v in _puts().items() if k < 20_000}     # nothing between target and spot
    res = _run(puts=puts)
    assert all(not m["available"] for m in res["modes"])
    assert res["modes"][0]["reason"]["code"] == "no_strike_within_tolerance"


def test_tolerance_at_or_above_exposure_needs_no_hedge():
    res = _run(tolerance_rs=2_500_000.0)
    assert res["status"] == "no_hedge_needed"
    assert res["modes"] == []


# ── put spread (lowest cost) ───────────────────────────────────────────────────────────────────────────────────
def test_lowest_cost_is_a_put_spread_ending_at_the_expected_fall():
    m = _mode(_run(), "lowest_cost")                   # long 21,850, short at highest listed <= 23,000 x 0.85 = 19,550
    assert m["structure"] == "put_spread"
    assert [(l["side"], l["strike"]) for l in m["legs"]] == [("buy", 21_850.0), ("sell", 19_550.0)]
    assert m["cost"]["premium_rs"] == pytest.approx((120.0 - 30.0) * LOT)           # 5,850
    assert m["break_even_level"] == pytest.approx(21_850.0 - 90.0)                  # 21,760
    assert m["max_protection_rs"] == pytest.approx((21_850.0 - 19_550.0) * LOT)     # 1,49,500


def test_put_spread_is_unavailable_when_the_expected_fall_is_inside_the_tolerance():
    m = _mode(_run(expected_fall_pct=4.0), "lowest_cost")       # 4% < the 5% deductible
    assert m["available"] is False
    assert m["reason"]["code"] == "expected_fall_within_tolerance"


# ── payoffs and the scenario table ─────────────────────────────────────────────────────────────────────────────
def _row(mode, move):
    return next(r for r in mode["scenario_rows"] if r["move_pct"] == move)


def test_long_put_scenario_rows_tie_out_by_hand():
    m = _mode(_run(), "balanced")
    assert m["cost"]["premium_rs"] == pytest.approx(7_800.0)
    assert m["cost"]["charges_rs"] == pytest.approx(100.0)
    assert m["cost"]["total_rs"] == pytest.approx(7_900.0)
    down10 = _row(m, -10)                                   # Nifty 20,700: payoff 65 x (21,850 - 20,700) = 74,750
    assert down10["without_hedge_rs"] == pytest.approx(-200_000.0)
    assert down10["hedge_pnl_rs"] == pytest.approx(74_750.0 - 7_800.0 - 100.0)
    assert down10["with_hedge_rs"] == pytest.approx(-200_000.0 + 66_850.0)
    flat = _row(m, 0)
    assert flat["hedge_pnl_rs"] == pytest.approx(-7_900.0) and flat["with_hedge_rs"] == pytest.approx(-7_900.0)
    up10 = _row(m, 10)
    assert up10["with_hedge_rs"] == pytest.approx(200_000.0 - 7_900.0)


def test_put_spread_payoff_is_capped():
    m = _mode(_run(), "lowest_cost")
    down20 = _row(m, -20)                                   # Nifty 18,400: capped at 65 x 2,300 = 1,49,500
    assert down20["hedge_pnl_rs"] == pytest.approx(149_500.0 - 5_850.0 - 100.0)
    assert _row(m, -15)["hedge_pnl_rs"] == pytest.approx(65 * (21_850 - 19_550) - 5_850.0 - 100.0)


def test_every_row_adds_up_and_the_expected_fall_row_is_marked():
    res = _run(expected_fall_pct=12.0)
    for m in res["modes"]:
        if not m["available"]:
            continue
        for r in m["scenario_rows"]:
            assert r["with_hedge_rs"] == pytest.approx(r["without_hedge_rs"] + r["hedge_pnl_rs"])
            assert r["nifty_level"] == pytest.approx(SPOT * (1 + r["move_pct"] / 100.0))
        assert [r["move_pct"] for r in m["scenario_rows"]] == sorted((r["move_pct"] for r in m["scenario_rows"]), reverse=True)
        assert [r["move_pct"] for r in m["scenario_rows"] if r["is_expected_fall"]] == [-12]


# ── hedge confidence, placing and data gaps ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("r2,level", [(0.83, "high"), (0.70, "high"), (0.55, "medium"), (0.40, "medium"), (0.18, "poor"), (None, "unknown")])
def test_hedge_confidence_bands(r2, level):
    assert calc.confidence(r2)["level"] == level


def test_a_poor_or_unknown_hedge_confidence_blocks_placing_but_not_viewing():
    for r2 in (0.18, None):
        res = _run(r2=r2)
        assert res["status"] == "ok"
        assert res["modes"] and all(m["place_allowed"] is False for m in res["modes"] if m["available"])
    assert all(m["place_allowed"] for m in _run(r2=0.83)["modes"] if m["available"])


@pytest.mark.parametrize("missing", ["beta", "spot", "lot"])
def test_missing_inputs_say_incomplete_and_invent_nothing(missing):
    res = _run(**{missing: None})
    assert res["status"] == "incomplete"
    assert res["modes"] == []
    assert res["reasons"][0]["code"] == f"missing_{missing}"


def test_no_premiums_at_all_is_incomplete():
    res = _run(puts={})
    assert res["status"] == "incomplete" and res["reasons"][0]["code"] == "missing_premiums"


def test_cost_as_a_share_of_the_portfolio_and_the_disclosures():
    res = _run()
    m = _mode(res, "balanced")
    assert m["cost"]["pct_of_portfolio"] == pytest.approx(7_900.0 / 2_000_000 * 100)
    text = " ".join(res["disclosures"])
    assert "not guaranteed future performance" in text and "does not eliminate" in text


def test_no_figure_is_nan_or_infinite():
    res = _run()
    def walk(x):
        if isinstance(x, float):
            assert math.isfinite(x)
        elif isinstance(x, dict):
            [walk(v) for v in x.values()]
        elif isinstance(x, (list, tuple)):
            [walk(v) for v in x]
    walk(res)
