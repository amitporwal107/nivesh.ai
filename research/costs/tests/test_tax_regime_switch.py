"""Tax regime switch at 23-Jul-2024 (Budget 2024 / Finance (No. 2) Act 2024): STCG (Section 111A)
15% -> 20%, LTCG (Section 112A) 10% -> 12.5% with the annual exemption Rs 1,00,000 -> Rs 1,25,000.
"""
import datetime as dt
from decimal import Decimal

from research.costs.tax import classify_term, compute_tax
from research.costs.rule_loader import load_rule_file

SWITCH_DATE = dt.date(2024, 7, 23)


def test_stcg_rate_before_and_on_switch_date():
    before = compute_tax(Decimal("10000"), term="SHORT", on_date=SWITCH_DATE - dt.timedelta(days=1))
    on_switch = compute_tax(Decimal("10000"), term="SHORT", on_date=SWITCH_DATE)
    after = compute_tax(Decimal("10000"), term="SHORT", on_date=SWITCH_DATE + dt.timedelta(days=1))
    assert before.rate_pct == Decimal("15.0")
    assert on_switch.rate_pct == Decimal("20.0")   # effective_from is inclusive
    assert after.rate_pct == Decimal("20.0")


def test_ltcg_rate_and_exemption_before_and_after_switch():
    gain = Decimal("200000")
    unused = Decimal("999999")  # a full unused annual allowance: capped at each year's threshold
    before = compute_tax(gain, term="LONG", on_date=SWITCH_DATE - dt.timedelta(days=1),
                         ltcg_exemption_available_inr=unused)
    after = compute_tax(gain, term="LONG", on_date=SWITCH_DATE, ltcg_exemption_available_inr=unused)
    assert before.rate_pct == Decimal("10.0")
    assert after.rate_pct == Decimal("12.5")
    # exemption changed 1,00,000 -> 1,25,000: taxable base differs even before the rate is applied
    assert before.tax_before_cess == ((gain - Decimal("100000")) * Decimal("10.0") / 100).quantize(Decimal("0.01"))
    assert after.tax_before_cess == ((gain - Decimal("125000")) * Decimal("12.5") / 100).quantize(Decimal("0.01"))


def test_holding_period_classification_unaffected_by_the_tax_switch():
    rs = load_rule_file("tax-equity-v1")
    long_term = classify_term(dt.date(2023, 1, 1), dt.date(2024, 6, 1), rule_set=rs)
    short_term = classify_term(dt.date(2024, 1, 1), dt.date(2024, 6, 1), rule_set=rs)
    assert long_term == "LONG"
    assert short_term == "SHORT"


def test_cess_and_surcharge_cap_apply_on_both_sides_of_the_switch():
    result = compute_tax(Decimal("100000000"), term="SHORT", on_date=SWITCH_DATE,
                          total_income_inr=Decimal("600000000"))  # well above every surcharge slab
    assert result.surcharge_pct == Decimal("15.0")  # capped, not 37%
    assert result.cess_pct == Decimal("4.0")
    expected_tax = (Decimal("100000000") * Decimal("20.0") / 100).quantize(Decimal("0.01"))
    expected_surcharge = (expected_tax * Decimal("15.0") / 100).quantize(Decimal("0.01"))
    expected_cess = ((expected_tax + expected_surcharge) * Decimal("4.0") / 100).quantize(Decimal("0.01"))
    assert result.tax_before_cess == expected_tax
    assert result.surcharge == expected_surcharge
    assert result.cess == expected_cess
    assert result.total_tax == expected_tax + expected_surcharge + expected_cess


def test_loss_or_zero_gain_produces_zero_tax():
    result = compute_tax(Decimal("-5000"), term="SHORT", on_date=SWITCH_DATE)
    assert result.total_tax == Decimal(0)
    assert "no tax" in result.notes[0]


def test_ltcg_exemption_is_not_granted_per_trade_by_default():
    """The 112A allowance is annual and shared across trades: without the caller passing its unused
    amount, no exemption is applied."""
    gain = Decimal("200000")
    result = compute_tax(gain, term="LONG", on_date=SWITCH_DATE)
    assert result.tax_before_cess == (gain * Decimal("12.5") / 100).quantize(Decimal("0.01"))
    partial = compute_tax(gain, term="LONG", on_date=SWITCH_DATE, ltcg_exemption_available_inr=Decimal("25000"))
    assert partial.tax_before_cess == ((gain - Decimal("25000")) * Decimal("12.5") / 100).quantize(Decimal("0.01"))


def test_surcharge_is_the_income_slab_capped_at_15pct_not_a_flat_15pct():
    tax_on = lambda income, on=SWITCH_DATE: compute_tax(Decimal("100000"), term="SHORT", on_date=on,
                                                         total_income_inr=Decimal(income)).surcharge_pct
    assert tax_on("1000000") == Decimal(0)         # Rs 10 lakh: no surcharge
    assert tax_on("7500000") == Decimal("10.0")    # Rs 75 lakh
    assert tax_on("15000000") == Decimal("15.0")   # Rs 1.5 crore
    assert tax_on("30000000") == Decimal("15.0")   # Rs 3 crore: slab 25%, capped
    # the cap on 111A/112A gains predates the Finance Act 2022 (FY2019-20), so 2021 trades are capped too
    assert tax_on("60000000", on=dt.date(2021, 6, 1)) == Decimal("15.0")


def test_holding_period_is_calendar_exact_more_than_12_months():
    rs = load_rule_file("tax-equity-v1")
    buy = dt.date(2023, 3, 1)
    assert classify_term(buy, dt.date(2024, 3, 1), rule_set=rs) == "SHORT"  # exactly 12 months (366 days)
    assert classify_term(buy, dt.date(2024, 3, 2), rule_set=rs) == "LONG"
    assert classify_term(dt.date(2024, 2, 29), dt.date(2025, 3, 1), rule_set=rs) == "SHORT"
    assert classify_term(dt.date(2024, 2, 29), dt.date(2025, 3, 2), rule_set=rs) == "LONG"


def test_loss_ledger_sets_off_a_same_year_loss():
    from research.costs.tax import LossLedger
    ledger = LossLedger()
    ledger.record_loss(2026, "SHORT", Decimal("3000"))
    assert ledger.offset(2026, "SHORT", Decimal("5000")) == (Decimal("2000"), Decimal("3000"))
    ledger.record_loss(2016, "SHORT", Decimal("1000"))  # 10 years back: beyond the 8-year carry-forward
    ledger.record_loss(2027, "SHORT", Decimal("1000"))  # a later year's loss cannot reach back
    assert ledger.offset(2026, "SHORT", Decimal("500")) == (Decimal("500"), Decimal(0))
