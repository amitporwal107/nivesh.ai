"""Quick Hedge inputs (services/quick_hedge/inputs.py, costs.py): holding classification, beta coverage, fit to Nifty, expiry choice,
traded puts, charges. Expected values are worked by hand; return series are seeded random walks, not market data."""
import random
from datetime import date, timedelta

import pytest

from services import desk_cost_card as card
from services.quick_hedge import costs, inputs


# ── classification, hedgeable value, beta ──────────────────────────────────────────────────────────────────────
def _h(atype, ticker, qty, price, **kw):
    return {"asset_type": atype, "ticker": ticker, "quantity": qty, "current_price": price, "name": kw.pop("name", ticker), **kw}


def test_an_isin_ticker_is_not_a_symbol_but_nse_symbol_is():
    assert inputs.stock_symbol({"ticker": "INE666D01022", "nse_symbol": "aartiind"}) == "AARTIIND"
    assert inputs.stock_symbol({"ticker": "INE666D01022"}) is None
    assert inputs.stock_symbol({"ticker": "tcs"}) == "TCS"


def test_the_split_beta_and_every_excluded_rupee_accounted_for():
    holdings = [
        _h("equity", "INE1", 1000, 1000.0, nse_symbol="AAA"),            # 10,00,000 beta 1.2
        _h("equity", "INE2", 500, 1000.0, nse_symbol="BBB"),             #  5,00,000 beta 0.8
        _h("mutual_fund", "INF1", 500, 1000.0),                          #  5,00,000 equity fund beta 1.0
        _h("mutual_fund", "INF2", 200, 1000.0),                          #  2,00,000 hybrid
        _h("mutual_fund", "INF3", 100, 1000.0),                          #  1,00,000 debt
        _h("gold", "GOLD", 300, 1000.0),                                 #  3,00,000 gold
        _h("mutual_fund", "INF9", 50, 1000.0),                           #    50,000 no primitives -> unclassified
        _h("equity", "INE123A01012", 10, 1000.0),                        #    10,000 ISIN only -> unclassified
    ]
    stock = {"AAA": {"beta_1y": 1.2}, "BBB": {"beta_1y": 0.8}}
    mf = {"INF1": {"category": "Equity Scheme", "beta_1y": 1.0}, "INF2": {"category": "Hybrid Scheme", "beta_1y": 0.6},
          "INF3": {"category": "Income/Debt Oriented Schemes", "beta_1y": 0.1}}
    p = inputs.build_portfolio(holdings, stock, mf)
    assert p["portfolio_value_rs"] == pytest.approx(2_660_000.0)
    assert p["hedgeable_value_rs"] == pytest.approx(2_000_000.0)
    assert p["excluded_rs"] == pytest.approx({"hybrid": 200_000.0, "debt": 100_000.0, "gold": 300_000.0, "overseas": 0.0, "other": 0.0, "unclassified": 60_000.0})
    assert p["hedgeable_value_rs"] + sum(p["excluded_rs"].values()) == pytest.approx(p["portfolio_value_rs"])
    assert p["beta"] == pytest.approx((1.2 * 1_000_000 + 0.8 * 500_000 + 1.0 * 500_000) / 2_000_000)      # 1.05
    assert p["beta_coverage"] == pytest.approx(1.0) and p["reasons"] == []


def test_beta_is_withheld_when_too_little_of_the_value_has_one():
    holdings = [_h("equity", "INE1", 1000, 1000.0, nse_symbol="AAA"), _h("equity", "INE2", 1000, 1000.0, nse_symbol="BBB")]
    p = inputs.build_portfolio(holdings, {"AAA": {"beta_1y": 1.0}}, {})          # half the value has a beta (0.5 < 0.8)
    assert p["beta"] is None and p["beta_coverage"] == pytest.approx(0.5)
    assert p["reasons"][0]["code"] == "beta_coverage_low"


def test_an_empty_portfolio_says_so():
    p = inputs.build_portfolio([], {}, {})
    assert p["hedgeable_value_rs"] == 0 and p["reasons"][0]["code"] == "missing_portfolio"


@pytest.mark.parametrize("cat,sub,atype,bucket", [
    ("Equity Scheme", "Large Cap", "mutual_fund", "equity"), ("Equity Schemes", None, "mutual_fund", "equity"),
    ("Hybrid Scheme", "Balanced", "mutual_fund", "hybrid"), ("Income/Debt Oriented Schemes", "Liquid", "mutual_fund", "debt"),
    ("Other Scheme", "Index Funds", "mutual_fund", "other"), ("Exchange Traded Funds (ETFs)", "Nifty 50 Index ETF", "etf", "equity"),
    ("Exchange Traded Funds (ETFs)", "Gold ETF", "etf", "gold"), ("Exchange Traded Funds (ETFs)", "Some other ETF", "etf", "unclassified"),
    ("Overseas Fund of Funds", "Fund of Funds investing overseas", "etf", "overseas"),
    ("Fund of Funds Scheme (Domestic)", "Fund of Funds Scheme (Domestic)", "etf", "unclassified"),   # no name to go on: unknown, not guessed
    ("Other Scheme", "Other  ETFs", "etf", "unclassified"),
])
def test_fund_buckets(cat, sub, atype, bucket):
    assert inputs.fund_bucket({"category": cat, "sub_category": sub}, atype) == bucket


def test_overseas_and_liquid_funds_are_named_not_left_unclassified():
    ov = {"category": "Fund of Funds Scheme (Domestic)", "sub_category": "Fund of Funds Scheme (Domestic)", "scheme_name": "Mirae Asset NYSE FANG+ ETF Fund of Fund"}
    assert inputs.fund_bucket(ov, "etf") == "overseas"                            # the name says what the category does not
    liq = {"category": "Other Scheme", "sub_category": "Other  ETFs", "scheme_name": "Nippon India ETF Nifty 1D Rate Liquid BeES"}
    assert inputs.fund_bucket(liq, "etf") == "debt"


def test_the_same_instrument_in_several_rows_is_one_position_with_the_summed_value():
    holdings = [_h("equity", "INE1", 100, 1000.0, nse_symbol="AAA"), _h("equity", "INE1", 50, 1000.0, nse_symbol="AAA"),
                _h("mutual_fund", "INF1", 10, 1000.0), _h("mutual_fund", "INF1", 5, 1000.0)]
    p = inputs.build_portfolio(holdings, {"AAA": {"beta_1y": 1.0}}, {"INF1": {"category": "Equity Scheme", "beta_1y": 1.0}})
    assert sorted((x["kind"], x["value_rs"]) for x in p["holdings"]) == [("fund", 15_000.0), ("stock", 150_000.0)]
    assert p["hedgeable_value_rs"] == pytest.approx(165_000.0)


# ── fit to Nifty ───────────────────────────────────────────────────────────────────────────────────────────────
def _dates(n):
    return [(date(2025, 1, 1) + timedelta(days=i)).isoformat() for i in range(n)]


def _walk(returns, p0):
    out = [p0]
    for r in returns:
        out.append(out[-1] * (1 + r))
    return out


RM = [random.Random(7).gauss(0, 0.01) for _ in range(1)]            # placeholder replaced below
_rng = random.Random(7)
RM = [_rng.gauss(0, 0.01) for _ in range(300)]
_rng2 = random.Random(99)
RI = [_rng2.gauss(0, 0.01) for _ in range(300)]
DATES = _dates(301)
NIFTY = list(zip(DATES, _walk(RM, 20_000.0)))


def _series(returns, p0=100.0):
    return list(zip(DATES, _walk(returns, p0)))


def test_a_portfolio_that_is_nifty_fits_perfectly():
    f = inputs.fit_to_nifty({"a": _series(RM)}, {"a": 100.0}, NIFTY)
    assert f["r2"] == pytest.approx(1.0, abs=1e-9) and f["regression_beta"] == pytest.approx(1.0, abs=1e-9)
    assert f["observations"] == 252 and f["coverage"] == pytest.approx(1.0) and f["reason"] is None


def test_a_leveraged_copy_has_beta_one_and_a_half_and_still_r2_one():
    f = inputs.fit_to_nifty({"a": _series([1.5 * r for r in RM])}, {"a": 1.0}, NIFTY)
    assert f["regression_beta"] == pytest.approx(1.5, abs=1e-9) and f["r2"] == pytest.approx(1.0, abs=1e-9)


def test_an_unrelated_series_has_a_poor_fit():
    f = inputs.fit_to_nifty({"a": _series(RI)}, {"a": 1.0}, NIFTY)
    assert f["r2"] < 0.05


def test_a_blend_sits_in_between_by_weight():
    f = inputs.fit_to_nifty({"m": _series(RM), "i": _series(RI)}, {"m": 600.0, "i": 400.0}, NIFTY)
    assert 0.6 < f["r2"] < 0.8                    # about 0.36 / (0.36 + 0.16) = 0.69 before sampling noise


def test_a_holding_without_enough_history_is_left_out_and_lowers_coverage():
    short = list(zip(DATES[-100:], _walk(RM[-99:], 100.0)))
    f = inputs.fit_to_nifty({"m": _series(RM), "s": short}, {"m": 600.0, "s": 400.0}, NIFTY, total_weight=1000.0)
    assert f["series_used"] == 1 and f["coverage"] == pytest.approx(0.6)
    assert f["r2"] is None and f["reason"]["code"] == "fit_coverage_low"


def test_coverage_counts_holdings_that_were_never_fetched():
    f = inputs.fit_to_nifty({"m": _series(RM)}, {"m": 600.0}, NIFTY, total_weight=1000.0)
    assert f["r2"] is None and f["coverage"] == pytest.approx(0.6)


def test_short_nifty_history_is_reported_not_guessed():
    f = inputs.fit_to_nifty({"m": _series(RM)}, {"m": 1.0}, NIFTY[:100])
    assert f["r2"] is None and f["reason"]["code"] == "fit_history_short"


# ── expiry choice, traded puts ─────────────────────────────────────────────────────────────────────────────────
EXPS = [{"expiry": f"e{d}", "days_to_expiry": d} for d in (1, 3, 10, 17, 24, 31, 59, 87, 150)]


@pytest.mark.parametrize("tenor,days", [("1w", 10), ("2w", 17), ("1m", 31), ("3m", 87)])
def test_expiry_nearest_the_tenor(tenor, days):
    assert inputs.choose_expiry(EXPS, tenor)["days_to_expiry"] == days


def test_no_expiry_in_range_or_unknown_tenor():
    assert inputs.choose_expiry([{"expiry": "x", "days_to_expiry": 1}, {"expiry": "y", "days_to_expiry": 150}], "1m") is None
    assert inputs.choose_expiry(EXPS, "5y") is None


def test_only_puts_that_traded_with_open_interest_are_priced():
    strikes = [{"strike": 22_000.0, "put": {"close": 90.0, "oi": 10_000}},
               {"strike": 21_900.0, "put": {"close": None, "oi": 90_000}},        # did not trade: the close is yesterday's
               {"strike": 21_800.0, "put": {"close": 70.0, "oi": 499}},           # too thin
               {"strike": 21_700.0, "put": None}]
    assert inputs.traded_puts(strikes) == {22_000.0: 90.0}


# ── charges come from the desk cost card ───────────────────────────────────────────────────────────────────────
LEGS = [{"side": "buy", "type": "put", "strike": 21_850.0, "qty": 65, "premium": 120.0}]


def test_entry_charges_are_the_cards_buy_side_on_the_premium():
    assert costs.make_charges()(LEGS, None) == pytest.approx(card.order_side("options", "BUY", 7_800.0)["total"])


def test_expiry_charges_otm_is_the_exit_side_flat_fee_and_itm_adds_exercise_stt():
    ch = costs.make_charges()
    otm = ch(LEGS, 22_500.0)
    assert otm == pytest.approx(card.order_side("options", "SELL", 0.0)["total"]) and otm > 0
    itm = ch(LEGS, 21_000.0)                                                      # intrinsic 850 x 65
    assert itm == pytest.approx(card.order_side("options", "SELL", 850.0 * 65)["total"]) and itm > otm


def test_a_short_leg_is_bought_back_at_intrinsic():
    legs = LEGS + [{"side": "sell", "type": "put", "strike": 19_550.0, "qty": 65, "premium": 30.0}]
    entry = costs.make_charges()(legs, None)
    assert entry == pytest.approx(card.order_side("options", "BUY", 7_800.0)["total"] + card.order_side("options", "SELL", 1_950.0)["total"])
    at18k = costs.make_charges()(legs, 18_000.0)
    assert at18k == pytest.approx(card.order_side("options", "SELL", 3_850.0 * 65)["total"] + card.order_side("options", "BUY", 1_550.0 * 65)["total"])
