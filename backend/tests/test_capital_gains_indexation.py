"""Indexation (Cost Inflation Index) tests for capital_gains_engine.

FY 2025-26 law (Finance (No.2) Act 2024): indexation survives ONLY as the
property option — immovable property acquired before 23-Jul-2024 and sold
long-term may be taxed at the LOWER of 12.5% (unindexed) or 20% (indexed).
These are pure-function tests — no DB.

Run from /app/backend:
    python3 -m pytest tests/test_capital_gains_indexation.py -v
"""
from datetime import date

import services.capital_gains_engine as cg


def _property(buy_price, sell_price, buy_date, sell_date):
    return cg.Transaction(
        asset_category=cg.AssetCategory.PROPERTY, quantity=1,
        buy_price=buy_price, sell_price=sell_price,
        buy_date=buy_date, sell_date=sell_date, name="Test Flat",
    )


def test_cii_table_known_values():
    # Base year and a few notified anchors.
    assert cg.cost_inflation_index(date(2001, 6, 1)) == 100
    assert cg.cost_inflation_index(date(2010, 6, 1)) == 167   # FY 2010-11
    assert cg.cost_inflation_index(date(2024, 6, 1)) == 363   # FY 2024-25
    assert cg.cost_inflation_index(date(2025, 6, 1)) == 376   # FY 2025-26


def test_cii_fy_boundary():
    # Jan/Feb/Mar fall in the PREVIOUS financial year.
    assert cg.cost_inflation_index(date(2024, 3, 31)) == 348  # FY 2023-24
    assert cg.cost_inflation_index(date(2024, 4, 1)) == 363   # FY 2024-25


def test_cii_clamps_beyond_published_range():
    # A sale in an FY not yet notified falls back to the latest published CII.
    assert cg.cost_inflation_index(date(2030, 6, 1)) == 376


def test_indexed_cost_formula():
    # 20,00,000 × CII(2024-25)/CII(2010-11) = 2000000 × 363/167.
    idx = cg.indexed_cost(2_000_000, date(2010, 6, 1), date(2024, 6, 1))
    assert round(idx) == round(2_000_000 * 363 / 167) == 4_347_305


def test_indexed_option_wins_for_long_held_property():
    """Long holding + modest nominal gain → 20% indexed beats 12.5% unindexed."""
    txn = _property(2_000_000, 5_000_000, date(2010, 6, 1), date(2024, 6, 1))
    gr = cg.compute_single_gain(txn)
    assert gr.tax_category == "property_ltcg_indexed"
    assert gr.indexation_applied is True
    assert round(gr.indexed_cost_basis) == 4_347_305
    assert round(gr.indexed_gain) == 652_695          # 5,000,000 − 4,347,305

    res = cg.compute_capital_gains([txn], slab_rate=0.30)
    # 20% of indexed gain, and NOT taxed in the 12.5% other bucket.
    assert abs(res.property_ltcg_indexed_tax - 652_695 * 0.20) < 1
    assert res.ltcg_other_tax == 0.0


def test_unindexed_option_wins_for_high_gain_property():
    """Large nominal gain vs little inflation → 12.5% unindexed is cheaper."""
    txn = _property(1_000_000, 3_000_000, date(2023, 5, 1), date(2025, 6, 1))
    gr = cg.compute_single_gain(txn)
    assert gr.tax_category == "property_ltcg"
    assert gr.indexation_applied is False
    # Indexed figures still recorded for transparency.
    assert gr.indexed_cost_basis is not None

    res = cg.compute_capital_gains([txn], slab_rate=0.30)
    assert abs(res.ltcg_other_tax - 2_000_000 * 0.125) < 1   # 12.5% of 20L
    assert res.property_ltcg_indexed_tax == 0.0


def test_property_after_cutoff_gets_no_indexation_option():
    """Property acquired on/after 23-Jul-2024 → flat 12.5%, no option."""
    txn = _property(1_000_000, 3_000_000, date(2024, 8, 1), date(2026, 9, 1))
    gr = cg.compute_single_gain(txn)
    assert gr.tax_category == "property_ltcg"
    assert gr.indexation_applied is False
    assert gr.indexed_cost_basis is None


def test_indexed_property_offset_by_ltcl_then_taxed_at_20pct():
    """A long-term capital loss should offset the 20% indexed pool first."""
    # Indexed-option property gain (~6.5L taxable indexed) ...
    prop = _property(2_000_000, 5_000_000, date(2010, 6, 1), date(2024, 6, 1))
    # ... plus an equity LTCL of ₹2,00,000 (sell below cost, held > 1y).
    equity_loss = cg.Transaction(
        asset_category=cg.AssetCategory.EQUITY_MF, quantity=100,
        buy_price=1000, sell_price=800,
        buy_date=date(2022, 1, 1), sell_date=date(2024, 6, 1), name="Equity Loss",
    )
    res = cg.compute_capital_gains([prop, equity_loss], slab_rate=0.30)
    # Indexed gain 652,695 − 20,000 LTCL = 632,695 taxed at 20%.
    assert abs(res.net_property_ltcg_indexed - (652_695 - 20_000)) < 2
    assert abs(res.property_ltcg_indexed_tax - (652_695 - 20_000) * 0.20) < 2
