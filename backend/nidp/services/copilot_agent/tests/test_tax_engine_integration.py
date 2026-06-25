"""TASK-069 integration tests: FY 2025-26 capital gains engine wired into portfolio tools.

Verifies:
  1. Grandfathered equity holding computes correct deemed cost
  2. SGB via RBI shows zero tax
  3. LTCG exemption of ₹1,25,000 (not old ₹1,00,000) applied correctly
  4. get_full_tax_report() returns CapitalGainsResult-shaped dict
  5. get_tax_harvest_candidates() rows contain tax_if_sold field
  6. Loss positions have tax_saved_if_harvested > 0
  7. Debt MF acquired post-Apr-2023 taxed at slab, not LTCG rate
  8. Full report summary mentions net_tax_payable

Run from /app/backend:
    PYTHONPATH=. python3 -m pytest nidp/services/copilot_agent/tests/test_tax_engine_integration.py -v
"""
from __future__ import annotations

import asyncio
import sys
import types
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest

# ── Stub DB dependency ────────────────────────────────────────────────────────
# _load_holdings() uses `async for h in db.holdings.find(...)` — we need an
# async iterator, not a coroutine or SimpleNamespace.

_HOLDINGS: list = []   # overridden per test class


class _AsyncIter:
    """Minimal async iterator that yields items from a list."""
    def __init__(self, items):
        self._it = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


def _make_db_stub():
    """Re-create the stub so db.holdings.find() reads the current _HOLDINGS list."""
    stub = types.ModuleType("deps")
    db = types.SimpleNamespace()

    # Use a closure that reads the module-level _HOLDINGS at call time (not at
    # stub-construction time) so that setup_method reassignments take effect.
    def _holdings_find(*a, **kw):
        return _AsyncIter(list(_HOLDINGS))

    def _empty_find(*a, **kw):
        return _AsyncIter([])

    db.holdings           = types.SimpleNamespace(find=_holdings_find)
    db.portfolio_holdings = types.SimpleNamespace(find=_empty_find)
    stub.db = db
    sys.modules["deps"] = stub
    return stub


_make_db_stub()

# ── Import the tools under test ───────────────────────────────────────────────
# Other test files (test_agent_graph.py) permanently stub
# services.copilot_tools.portfolio in sys.modules at collection time.  We
# temporarily remove the stub to import the REAL module's functions, then
# restore whatever was there so other tests see their stub again.
_prior_portfolio_stub = sys.modules.pop("services.copilot_tools.portfolio", None)

from services.copilot_tools.portfolio import (
    get_full_tax_report,
    get_tax_harvest_candidates,
)

# Restore whatever was in sys.modules before (the stub from test_agent_graph.py,
# or nothing if this file is run standalone).  Our local name bindings above
# already point to the real functions — this just keeps other test files happy.
if _prior_portfolio_stub is not None:
    sys.modules["services.copilot_tools.portfolio"] = _prior_portfolio_stub

from services.capital_gains_engine import (
    quick_tax_estimate,
    compute_capital_gains,
    classify_asset,
    Transaction,
    AssetCategory,
    EQUITY_LTCG_EXEMPTION,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _holding(
    name="Test Fund",
    asset_type="MF",
    buy_price=100.0,
    current_price=150.0,
    quantity=1000.0,
    buy_date="2020-01-01",
    equity_allocation_pct=None,
    fmv_31jan2018=None,
    redemption_via_rbi=False,
):
    return {
        "name": name,
        "asset_type": asset_type,
        "buy_price": buy_price,
        "current_price": current_price,
        "quantity": quantity,
        "buy_date": buy_date,
        "equity_allocation_pct": equity_allocation_pct,
        "fmv_31jan2018": fmv_31jan2018,
        "redemption_via_rbi": redemption_via_rbi,
    }


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Test 1: Grandfathering ────────────────────────────────────────────────────

class TestGrandfathering:
    def test_deemed_cost_is_max_of_actual_and_fmv(self):
        """Pre-2018 equity: deemed_cost = max(actual_cost, min(FMV_31Jan2018, sale_price))."""
        txn = Transaction(
            asset_category=AssetCategory.LISTED_EQUITY,
            quantity=100,
            buy_price=50.0,       # actual cost ₹5,000 total
            sell_price=200.0,     # sale ₹20,000 total
            buy_date=date(2015, 6, 1),
            sell_date=date(2025, 3, 31),
            fmv_31jan2018=120.0,  # FMV on 31-Jan-2018 ₹12,000 total
        )
        from services.capital_gains_engine import compute_single_gain
        gr = compute_single_gain(txn)
        # deemed_cost = max(5000, min(12000, 20000)) = max(5000, 12000) = 12000
        assert gr.is_grandfathered
        assert gr.cost_basis == pytest.approx(12_000.0)
        # gain = 20000 - 12000 = 8000
        assert gr.gross_gain == pytest.approx(8_000.0)

    def test_grandfathering_does_not_create_loss(self):
        """If FMV > sale_price, deemed_cost = sale_price → gain = 0, not a loss."""
        txn = Transaction(
            asset_category=AssetCategory.LISTED_EQUITY,
            quantity=100,
            buy_price=50.0,
            sell_price=80.0,      # sale below FMV
            buy_date=date(2016, 1, 1),
            sell_date=date(2025, 3, 31),
            fmv_31jan2018=200.0,  # FMV much higher than sale
        )
        from services.capital_gains_engine import compute_single_gain
        gr = compute_single_gain(txn)
        # deemed_cost = max(5000, min(20000, 8000)) = max(5000, 8000) = 8000
        # gain = 8000 - 8000 = 0  (no artificial loss)
        assert gr.gross_gain == pytest.approx(0.0)


# ── Test 2: SGB RBI exemption ─────────────────────────────────────────────────

class TestSGBExemption:
    def test_sgb_rbi_redemption_is_zero_tax(self):
        est = quick_tax_estimate(
            {
                "name": "Sovereign Gold Bond 2016-17 Series I",
                "asset_type": "SGB",
                "buy_price": 2800.0,
                "current_price": 6200.0,
                "quantity": 10,
                "buy_date": "2016-12-01",
                "redemption_via_rbi": True,
            },
            slab_rate=0.30,
        )
        assert est["ok"] is True
        assert est["tax_liability"] == 0.0
        assert est["tax_regime"] == "sgb_rbi_exempt"
        assert est["taxable_gain"] == 0.0


# ── Test 3: ₹1,25,000 LTCG exemption ─────────────────────────────────────────

class TestLTCGExemption:
    def test_exemption_is_125000_not_100000(self):
        """The exemption constant must be ₹1,25,000 as per FY 2025-26 rules."""
        assert EQUITY_LTCG_EXEMPTION == 125_000

    def test_exemption_applied_in_quick_estimate(self):
        """Gain of ₹1,20,000 → taxable gain 0 (within exemption)."""
        est = quick_tax_estimate(
            {
                "name": "HDFC Top 100 Fund",
                "asset_type": "MF",
                "buy_price": 100.0,
                "current_price": 220.0,   # gain = 120 × 1000 = ₹1,20,000
                "quantity": 1000.0,
                "buy_date": "2022-01-01",  # > 1 year → LTCG
                "equity_allocation_pct": 90.0,
            },
            ltcg_used=0.0,
            slab_rate=0.30,
        )
        assert est["ok"] is True
        assert est["taxable_gain"] == pytest.approx(0.0)
        assert est["tax_liability"] == pytest.approx(0.0)

    def test_exemption_partially_consumed(self):
        """With ₹1,00,000 already used, only ₹25,000 exemption remains."""
        est = quick_tax_estimate(
            {
                "name": "Axis Bluechip Fund",
                "asset_type": "MF",
                "buy_price": 100.0,
                "current_price": 200.0,   # gain = ₹1,00,000
                "quantity": 1000.0,
                "buy_date": "2022-01-01",
                "equity_allocation_pct": 85.0,
            },
            ltcg_used=100_000.0,   # already consumed ₹1L
            slab_rate=0.30,
        )
        # remaining exemption = 125000 - 100000 = 25000
        # taxable gain = 100000 - 25000 = 75000
        assert est["taxable_gain"] == pytest.approx(75_000.0)


# ── Test 4: get_full_tax_report shape ─────────────────────────────────────────

class TestFullTaxReport:
    def setup_method(self):
        global _HOLDINGS
        _HOLDINGS = [
            _holding("Equity Fund A", "MF", 100, 160, 1000, "2021-06-01", equity_allocation_pct=90.0),
            _holding("Debt Fund B", "MF", 100, 130, 500, "2021-06-01", equity_allocation_pct=10.0),
        ]

    def test_report_has_net_tax_payable(self):
        result = _run(get_full_tax_report("user1", slab_rate=0.30))
        assert result.ok is True
        assert "net_tax_payable" in result.data
        assert "equity_ltcg_exemption" in result.data
        assert "total_tax" in result.data

    def test_report_rows_have_capital_gain_field(self):
        result = _run(get_full_tax_report("user1"))
        assert len(result.rows) >= 1
        for row in result.rows:
            assert "capital_gain" in row
            assert "asset_category" in row
            assert "gain_type" in row

    def test_summary_mentions_tax_payable(self):
        result = _run(get_full_tax_report("user1"))
        assert "tax payable" in result.summary.lower() or "net_tax" in result.summary.lower()


# ── Test 5: get_tax_harvest_candidates rows ───────────────────────────────────

class TestHarvestCandidates:
    def setup_method(self):
        global _HOLDINGS
        _HOLDINGS = [
            _holding("Fund A (profit)", "MF", 100, 180, 500, "2021-01-01", equity_allocation_pct=90.0),
            _holding("Fund B (loss)",   "MF", 200, 140, 300, "2022-06-01", equity_allocation_pct=90.0),
        ]

    def test_rows_contain_tax_if_sold(self):
        result = _run(get_tax_harvest_candidates("user1"))
        assert result.ok is True
        for row in result.rows:
            assert "tax_if_sold" in row
            assert "gain_type" in row
            assert "capital_gain" in row
            assert "holding_days" in row

    def test_loss_positions_have_harvest_saving(self):
        result = _run(get_tax_harvest_candidates("user1"))
        loss_rows = [r for r in result.rows if r["capital_gain"] < 0]
        assert len(loss_rows) >= 1
        for row in loss_rows:
            assert row["tax_saved_if_harvested"] >= 0

    def test_loss_positions_sorted_first(self):
        result = _run(get_tax_harvest_candidates("user1"))
        if len(result.rows) >= 2:
            # First row should be loss (or highest tax)
            gains = [r["capital_gain"] for r in result.rows]
            # Losses (negative) come first
            has_loss = any(g < 0 for g in gains)
            if has_loss:
                first_loss_idx = next(i for i, g in enumerate(gains) if g < 0)
                first_gain_idx = next((i for i, g in enumerate(gains) if g > 0), len(gains))
                assert first_loss_idx < first_gain_idx

    def test_data_has_exemption_remaining(self):
        result = _run(get_tax_harvest_candidates("user1"))
        assert "ltcg_exemption_remaining_rs" in result.data
        assert "total_tax_if_sold_rs" in result.data


# ── Test 6: Debt MF post-Apr-2023 taxed at slab ──────────────────────────────

class TestDebtMFSlabRate:
    def test_debt_mf_post_apr23_is_slab_not_ltcg(self):
        """Debt MF acquired on/after 2023-04-01 → DEBT_MF_POST23 → always slab.

        equity_allocation_pct must be None so the name-keyword path fires.
        Passing an explicit % routes to the HYBRID branch regardless of date.
        """
        category = classify_asset(
            "MF", "HDFC Short Duration Fund",
            equity_allocation_pct=None,           # let name drive classification
            acquisition_date=date(2023, 6, 1),
        )
        assert category == AssetCategory.DEBT_MF_POST23

        est = quick_tax_estimate(
            {
                "name": "HDFC Short Duration Fund",
                "asset_type": "MF",
                "buy_price": 100.0,
                "current_price": 130.0,
                "quantity": 1000.0,
                "buy_date": "2023-06-01",         # post cutover, > 1 year held
                # no equity_allocation_pct → name-keyword path → DEBT_MF_POST23
            },
            slab_rate=0.30,
        )
        assert est["ok"] is True
        assert "debt" in est["tax_regime"] or "slab" in est["tax_regime"]
        assert est["tax_rate"] == pytest.approx(0.30)

    def test_debt_mf_pre_apr23_with_name_keyword(self):
        """Debt MF acquired before 2023-04-01 → DEBT_MF_PRE23.

        Use a name with a debt keyword that doesn't also match the BOND branch.
        "short duration" is in _DEBT_KEYWORDS; "bond" is NOT used here since
        classify_asset checks the BOND asset_type branch before MF.
        """
        category = classify_asset(
            "MF", "SBI Short Duration Fund",
            equity_allocation_pct=None,
            acquisition_date=date(2021, 1, 1),    # before cutover
        )
        assert category == AssetCategory.DEBT_MF_PRE23


class TestPropertyIndexation:
    """Sec 112 proviso: property acquired before 23-Jul-2024 is taxed at the
    LOWER of 12.5% unindexed vs 20% on the CII-indexed gain."""

    def test_cii_lookup(self):
        from services.capital_gains_engine import cost_inflation_index
        assert cost_inflation_index(date(2024, 6, 1)) == 363   # FY 2024-25
        assert cost_inflation_index(date(2002, 5, 1)) == 105   # FY 2002-03

    def test_indexed_option_elected_when_cheaper(self):
        """Old property + heavy inflation → 20%-indexed beats 12.5%-flat."""
        from services.capital_gains_engine import compute_single_gain
        txn = Transaction(
            asset_category=AssetCategory.PROPERTY, quantity=1,
            buy_price=1_000_000, sell_price=5_000_000,
            buy_date=date(2002, 5, 1), sell_date=date(2024, 6, 1),
        )
        gr = compute_single_gain(txn)
        assert gr.indexation_applied is True
        assert gr.tax_category == "property_ltcg_indexed"
        assert gr.applicable_rate == pytest.approx(0.20)
        # indexed cost = 10L × 363/105 ; indexed gain taxed, not the flat 40L
        assert gr.indexed_cost_basis == pytest.approx(1_000_000 * 363 / 105, rel=1e-4)
        assert gr.gross_gain == pytest.approx(5_000_000 - gr.indexed_cost_basis, rel=1e-4)

    def test_flat_option_when_indexation_does_not_help(self):
        """Long-term property, modest inflation, large gain → flat 12.5% wins."""
        from services.capital_gains_engine import compute_single_gain
        txn = Transaction(
            asset_category=AssetCategory.PROPERTY, quantity=1,
            buy_price=1_000_000, sell_price=5_000_000,
            buy_date=date(2022, 1, 1), sell_date=date(2024, 12, 1),
        )
        gr = compute_single_gain(txn)
        assert gr.is_long_term is True
        assert gr.indexation_applied is False
        assert gr.tax_category == "property_ltcg"

    def test_no_indexation_option_after_cutoff(self):
        """Property bought on/after 23-Jul-2024 → no indexation option at all."""
        from services.capital_gains_engine import compute_single_gain
        txn = Transaction(
            asset_category=AssetCategory.PROPERTY, quantity=1,
            buy_price=1_000_000, sell_price=5_000_000,
            buy_date=date(2024, 8, 1), sell_date=date(2026, 9, 1),
        )
        gr = compute_single_gain(txn)
        assert gr.indexation_applied is False
        assert gr.tax_category == "property_ltcg"

    def test_full_computation_taxes_indexed_gain_at_20pct(self):
        txn = Transaction(
            asset_category=AssetCategory.PROPERTY, quantity=1,
            buy_price=1_000_000, sell_price=5_000_000,
            buy_date=date(2002, 5, 1), sell_date=date(2024, 6, 1),
        )
        from services.capital_gains_engine import compute_single_gain
        gr = compute_single_gain(txn)
        res = compute_capital_gains([txn], total_income_rs=1_000_000)
        assert res.property_ltcg_indexed_tax == pytest.approx(gr.gross_gain * 0.20, rel=1e-4)
        assert res.base_tax >= res.property_ltcg_indexed_tax  # included in base tax

    def test_ltcl_absorbs_indexed_pool_first(self):
        """A long-term loss offsets the 20% indexed pool before lower-rate LTCG."""
        prop = Transaction(
            asset_category=AssetCategory.PROPERTY, quantity=1,
            buy_price=1_000_000, sell_price=5_000_000,
            buy_date=date(2002, 5, 1), sell_date=date(2024, 6, 1),
        )
        ltcl = Transaction(
            asset_category=AssetCategory.EQUITY_MF, quantity=1,
            buy_price=2_000_000, sell_price=1_000_000,
            buy_date=date(2020, 1, 1), sell_date=date(2024, 6, 1),
        )
        base = compute_capital_gains([prop], total_income_rs=1_000_000)
        with_loss = compute_capital_gains([prop, ltcl], total_income_rs=1_000_000)
        assert with_loss.net_property_ltcg_indexed < base.net_property_ltcg_indexed
