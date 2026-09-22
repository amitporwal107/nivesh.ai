"""Unit tests for the five PRD slippage models plus the fixed_amount primitive."""
from decimal import Decimal

from research.costs import slippage


def test_fixed_pct():
    assert slippage.fixed_pct(Decimal("1000"), Decimal("0.15")) == Decimal("1.5")


def test_fixed_bps():
    assert slippage.fixed_bps(Decimal("1000"), Decimal("15")) == Decimal("1.5")


def test_liquidity_bucket_pct_uses_the_zerodha_style_bucket_table():
    buckets = (
        (Decimal("1000000000"), Decimal("0.05")),
        (Decimal("250000000"), Decimal("0.10")),
        (Decimal("0"), Decimal("0.20")),
    )
    assert slippage.liquidity_bucket_pct(Decimal("2000000000"), buckets) == Decimal("0.05")
    assert slippage.liquidity_bucket_pct(Decimal("300000000"), buckets) == Decimal("0.10")
    assert slippage.liquidity_bucket_pct(Decimal("1000"), buckets) == Decimal("0.20")
    assert slippage.liquidity_bucket_pct(None, buckets) == Decimal("0.20")  # unknown ADV -> worst bucket


def test_volume_dependent_sums_base_liquidity_and_volatility_penalties():
    amount = slippage.volume_dependent(Decimal("1000"), base_pct=Decimal("0.10"),
                                        liquidity_penalty_pct=Decimal("0.05"), volatility_penalty_pct=Decimal("0.03"))
    assert amount == Decimal("1000") * Decimal("0.18") / 100


def test_atr_based_is_n_times_atr():
    assert slippage.atr_based(atr=Decimal("12.5"), n_atr=Decimal("0.5")) == Decimal("6.25")


def test_atr_based_pct_matches_atr_based_expressed_as_percentage_of_price():
    pct = slippage.atr_based_pct(atr=Decimal("12.5"), price=Decimal("1000"), n_atr=Decimal("0.5"))
    assert pct == Decimal("0.625")


def test_atr_based_pct_zero_price_does_not_divide_by_zero():
    assert slippage.atr_based_pct(atr=Decimal("12.5"), price=Decimal("0"), n_atr=Decimal("0.5")) == Decimal(0)


def test_fixed_amount_is_passthrough():
    assert slippage.fixed_amount(Decimal("3")) == Decimal("3")


def test_apply_slippage_direction_convention():
    assert slippage.apply_slippage(Decimal("100"), "BUY", Decimal("1")) == Decimal("101")
    assert slippage.apply_slippage(Decimal("100"), "SELL", Decimal("1")) == Decimal("99")


def test_apply_slippage_rejects_negative_magnitude():
    import pytest
    with pytest.raises(ValueError):
        slippage.apply_slippage(Decimal("100"), "BUY", Decimal("-1"))
