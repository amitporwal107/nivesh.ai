"""costs_bridge.py: qty/position-value/participation-ratio derivation, and the full
event+horizon cost block (4 PRD sensitivity scenarios + liquidity-bucket model +
unverified_rates_used), bridged to `research/costs/*` (never edited by this package)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from research.charting.events import costs_bridge, schema


# ── qty / position value / participation ratio ───────────────────────────────────────────


def test_qty_for_notional_floors_and_never_goes_below_one_share():
    assert costs_bridge.qty_for_notional(Decimal("111"), Decimal("100000")) == 900  # floor(900.9)
    assert costs_bridge.qty_for_notional(Decimal("250000"), Decimal("100000")) == 1  # price > notional -> 1 share
    assert costs_bridge.qty_for_notional(Decimal("0"), Decimal("100000")) == 0  # non-positive price -> 0


def test_position_value_inr_is_qty_times_entry_price():
    assert costs_bridge.position_value_inr(Decimal("111"), 900) == pytest.approx(99900.0)


def test_participation_ratio_none_when_adv_unavailable_infinite_when_adv_zero():
    assert costs_bridge.participation_ratio_for(99900.0, None) is None
    assert costs_bridge.participation_ratio_for(99900.0, 0.0) == float("inf")
    assert costs_bridge.participation_ratio_for(99900.0, 999_000.0) == pytest.approx(99900.0 / 999_000.0)


# ── compute_cost_block ────────────────────────────────────────────────────────────────────


def _cfg(**overrides) -> costs_bridge.CostConfig:
    base = dict(notional_inr=Decimal("100000"))
    base.update(overrides)
    return costs_bridge.CostConfig(**base)


def test_qty_zero_is_reported_unavailable_never_a_fabricated_trade():
    block = costs_bridge.compute_cost_block(
        entry_date=dt.date(2025, 1, 1), entry_price=100.0, exit_date=dt.date(2025, 1, 10), exit_price=110.0,
        qty=0, adv_inr=None, cfg=_cfg(),
    )
    assert block == {"available": False, "reason": "non_positive_qty"}


def test_cost_block_shape_and_internal_consistency():
    block = costs_bridge.compute_cost_block(
        entry_date=dt.date(2025, 1, 1), entry_price=1000.0, exit_date=dt.date(2025, 1, 10), exit_price=1100.0,
        qty=100, adv_inr=None, cfg=_cfg(),
    )
    assert block["available"] is True
    assert set(block["scenarios"].keys()) == {"optimistic", "base", "conservative", "stress"}
    assert block["liquidity_bucket"] == {"available": False, "reason": "adv_unavailable"}
    assert isinstance(block["unverified_rates_used"], list)
    assert block["cost_rule_version"] == "nse-equity-statutory-v1@1"
    assert block["tax_rule_version"] == "tax-equity-v1@1"

    for name, rec in block["scenarios"].items():
        assert rec["qty"] == 100
        assert rec["gross"] == pytest.approx((1100.0 - 1000.0) * 100)
        total_components = rec["brokerage"] + rec["stt"] + rec["exchange_txn"] + rec["sebi"] + rec["stamp"] + rec["gst"] + rec["dp"]
        assert rec["total_cost"] == pytest.approx(total_components, abs=0.02)
        expected_net = rec["gross"] - rec["entry_slippage"] - rec["exit_slippage"] - rec["total_cost"]
        assert rec["net_before_tax"] == pytest.approx(expected_net, abs=0.02)
        # net_after_tax = net_before_tax - total_tax (Series A vs Series B kept separate, never merged)
        assert rec["net_after_tax"] == pytest.approx(rec["net_before_tax"] - rec["total_tax"], abs=0.02)


def test_higher_sensitivity_slippage_strictly_reduces_net_before_tax_on_a_winning_trade():
    block = costs_bridge.compute_cost_block(
        entry_date=dt.date(2025, 1, 1), entry_price=1000.0, exit_date=dt.date(2025, 1, 10), exit_price=1100.0,
        qty=100, adv_inr=None, cfg=_cfg(),
    )
    nets = [block["scenarios"][name]["net_before_tax"] for name in ("optimistic", "base", "conservative", "stress")]
    assert nets == sorted(nets, reverse=True)  # strictly decreasing as slippage assumption worsens
    assert nets[0] > nets[-1]


def test_default_zerodha_delivery_brokerage_is_zero():
    block = costs_bridge.compute_cost_block(
        entry_date=dt.date(2025, 1, 1), entry_price=1000.0, exit_date=dt.date(2025, 1, 10), exit_price=1100.0,
        qty=100, adv_inr=None, cfg=_cfg(),
    )
    assert block["scenarios"]["base"]["brokerage"] == pytest.approx(0.0)


def test_liquidity_bucket_model_present_when_adv_supplied():
    block = costs_bridge.compute_cost_block(
        entry_date=dt.date(2025, 1, 1), entry_price=1000.0, exit_date=dt.date(2025, 1, 10), exit_price=1100.0,
        qty=100, adv_inr=5_000_000.0, cfg=_cfg(),
    )
    lb = block["liquidity_bucket"]
    assert lb["available"] is True
    assert lb["slippage_model_version"].startswith("liquidity_bucket_v1")
    # lowest ADV bucket (< 25 crore) -> 0.20% per side, worse than the "base" 0.15% scenario
    assert lb["net_before_tax"] < block["scenarios"]["base"]["net_before_tax"]


def test_dp_charge_only_applied_when_dp_applies_true():
    with_dp = costs_bridge.compute_cost_block(
        entry_date=dt.date(2025, 1, 1), entry_price=1000.0, exit_date=dt.date(2025, 1, 10), exit_price=1100.0,
        qty=100, adv_inr=None, cfg=_cfg(dp_applies=True, dp_broker="zerodha"),
    )
    without_dp = costs_bridge.compute_cost_block(
        entry_date=dt.date(2025, 1, 1), entry_price=1000.0, exit_date=dt.date(2025, 1, 10), exit_price=1100.0,
        qty=100, adv_inr=None, cfg=_cfg(dp_applies=False, dp_broker=None),
    )
    assert with_dp["scenarios"]["base"]["dp"] > 0.0
    assert without_dp["scenarios"]["base"]["dp"] == pytest.approx(0.0)


def test_compute_tax_false_leaves_tax_fields_none():
    block = costs_bridge.compute_cost_block(
        entry_date=dt.date(2025, 1, 1), entry_price=1000.0, exit_date=dt.date(2025, 1, 10), exit_price=1100.0,
        qty=100, adv_inr=None, cfg=_cfg(compute_tax=False),
    )
    rec = block["scenarios"]["base"]
    assert rec["taxable_gain"] is None
    assert rec["total_tax"] is None
    assert rec["net_after_tax"] is None
    assert block["tax_rule_version"] is None


def test_a_rate_straddling_round_trip_uses_each_legs_own_date_dp_charge_changed_2024_10_01():
    # DP charge: Rs 15.93/scrip pre-2024-10-01 (secondary source, unverified), Rs 15.34 from
    # 2024-10-01 (verified). A sell leg dated just before vs just after must resolve differently.
    before = costs_bridge.compute_cost_block(
        entry_date=dt.date(2024, 9, 1), entry_price=1000.0, exit_date=dt.date(2024, 9, 25), exit_price=1010.0,
        qty=10, adv_inr=None, cfg=_cfg(),
    )
    after = costs_bridge.compute_cost_block(
        entry_date=dt.date(2024, 10, 5), entry_price=1000.0, exit_date=dt.date(2024, 10, 20), exit_price=1010.0,
        qty=10, adv_inr=None, cfg=_cfg(),
    )
    assert before["scenarios"]["base"]["dp"] == pytest.approx(15.93)
    assert after["scenarios"]["base"]["dp"] == pytest.approx(15.34)
    assert "https://www.chittorgarh.com/broker/zerodha/demat-account/18/" in before["unverified_rates_used"]
    assert after["unverified_rates_used"] == []


def test_cost_blocks_state_they_are_long_round_trips_and_flag_bearish_short_costs_as_not_modelled():
    """A BEARISH row's directional return is short-side; its costs are a long round trip, so the
    row must say so rather than let the long net figure pass for the short outcome."""
    from research.charting.events.extraction import build_outcome_cost_block
    from research.charting.tests import synth

    bars = synth.bars_from_closes([100.0 + (i % 5) * 0.5 + i * 0.1 for i in range(60)], start_date="2021-03-01")
    bull = build_outcome_cost_block(bars, 30, "BULLISH")["costs"]
    bear = build_outcome_cost_block(bars, 30, "BEARISH")["costs"]
    assert bull["trade_side"] == bear["trade_side"] == "LONG"
    assert bull["short_side_costs"] is None
    assert bear["short_side_costs"] == "NOT_MODELLED"
