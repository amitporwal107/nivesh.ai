"""extraction.py: one row per confirmed pattern instance, task item 1-5's full row shape,
across all three pattern families (RECTANGLE, SUPPORT_RESISTANCE, HH_HL)."""
from __future__ import annotations

import pandas as pd
import pytest

from research.charting.config import CONFIG, ENGINE_VERSION, config_hash
from research.charting.events import extraction
from research.charting.tests._events_helpers import (
    confirmed_hh_hl_with_runway,
    confirmed_rectangle_with_runway,
    confirmed_support_resistance_with_runway,
)

_EXPECTED_TOP_KEYS = {
    "event_id", "symbol", "pattern_id", "pattern_type", "direction", "signal_date",
    "confirmation_bar_index", "level_broken", "level_broken_field", "atr_at_t",
    "relative_volume_at_t", "config_hash", "engine_version", "profile", "dataset_version",
    "versioning", "entry", "outcomes", "outcomes_alt_close_entry", "liquidity", "costs",
    "stop", "targets", "tradability", "action", "unavailable_reason",
}


def test_rectangle_event_row_shape_and_signal_fields():
    bars = confirmed_rectangle_with_runway()
    rows = extraction.extract_events(bars, "SYN1")
    assert len(rows) == 1
    row = rows[0]
    assert set(row.keys()) == _EXPECTED_TOP_KEYS
    assert row["symbol"] == "SYN1"
    assert row["pattern_type"] == "RECTANGLE"
    assert row["direction"] == "BULLISH"
    assert row["level_broken_field"] == "breakout_level"
    assert row["level_broken"] == pytest.approx(row["level_broken"])  # a real float, not None
    assert row["level_broken"] is not None
    t = row["confirmation_bar_index"]
    assert row["signal_date"] == bars["date"].iloc[t].date().isoformat()
    assert row["config_hash"] == config_hash(CONFIG)
    assert row["engine_version"] == ENGINE_VERSION
    assert row["dataset_version"] == 2
    assert row["unavailable_reason"] is None
    assert row["tradability"] == "LONG_ACTIONABLE"
    assert row["action"] == "CONSIDER_LONG"


def test_support_resistance_event_uses_breakout_level_key():
    bars = confirmed_support_resistance_with_runway()
    rows = extraction.extract_events(bars, "SYN2")
    sr_rows = [r for r in rows if r["pattern_type"] == "SUPPORT_RESISTANCE"]
    assert len(sr_rows) == 1
    assert sr_rows[0]["direction"] == "BULLISH"
    assert sr_rows[0]["level_broken_field"] == "breakout_level"
    assert sr_rows[0]["level_broken"] == pytest.approx(sr_rows[0]["level_broken"])


def test_hh_hl_event_uses_prior_high_key():
    bars = confirmed_hh_hl_with_runway()
    rows = extraction.extract_events(bars, "ZZ")
    hh_rows = [r for r in rows if r["pattern_type"] == "HH_HL"]
    assert len(hh_rows) >= 1
    for r in hh_rows:
        assert r["direction"] == "BULLISH"
        assert r["level_broken_field"] == "prior_high"


def test_entry_convention_primary_is_open_t_plus_1_alt_is_close_t():
    bars = confirmed_rectangle_with_runway()
    row = extraction.extract_events(bars, "SYN1")[0]
    t = row["confirmation_bar_index"]
    primary = row["entry"]["primary"]
    alt = row["entry"]["alternative_close_t"]
    assert primary["method"] == "open_t_plus_1"
    assert primary["index"] == t + 1
    assert primary["price"] == pytest.approx(bars["open"].iloc[t + 1])
    assert alt["method"] == "close_t"
    assert alt["index"] == t
    assert alt["price"] == pytest.approx(bars["close"].iloc[t])


def test_outcomes_present_for_every_horizon_with_enough_runway():
    bars = confirmed_rectangle_with_runway(tail_len=30)
    row = extraction.extract_events(bars, "SYN1")[0]
    fwd = row["outcomes"]["forward_returns"]
    assert set(fwd.keys()) == {1, 3, 5, 10, 20}
    for h, block in fwd.items():
        assert block["available"] is True
        assert "close_return" in block and "mfe" in block and "mae" in block
        assert "highest_price" in block and "lowest_price" in block
    directional = row["outcomes"]["forward_returns_directional"]
    for h in fwd:
        assert directional[h]["close_return_directional"] == pytest.approx(fwd[h]["close_return"])  # BULLISH: unchanged
    assert set(row["outcomes"]["bars_to_target"].keys()) == {"plus_2pct", "plus_5pct", "plus_10pct", "plus_15pct"}
    # hit_high_N/hit_close_N were removed from `outcomes` 2026-09-22 (§37 Amendment C) --
    # superseded by `row["stop"]`/`row["targets"]`, see test_events_stops.py.
    assert "hit_high_5" not in row["outcomes"] and "hit_close_5" not in row["outcomes"]


def test_alt_close_entry_outcomes_use_a_different_entry_price_than_primary():
    bars = confirmed_rectangle_with_runway()
    row = extraction.extract_events(bars, "SYN1")[0]
    primary_1 = row["outcomes"]["forward_returns"][1]
    alt_1 = row["outcomes_alt_close_entry"]["forward_returns"][1]
    # Different entry BAR by construction (t vs t+1) -- this synthetic fixture happens to have
    # no gap between bar t's close and bar t+1's open, so the two entry PRICES can legitimately
    # coincide; what must always differ is the entry index/method and (generally) the exit bar
    # each horizon resolves against, since the two entries start counting sessions from
    # different bars.
    assert row["entry"]["primary"]["index"] != row["entry"]["alternative_close_t"]["index"]
    assert row["entry"]["primary"]["method"] != row["entry"]["alternative_close_t"]["method"]
    assert primary_1["exit_index"] != alt_1["exit_index"]


def test_costs_by_horizon_present_and_net_before_tax_reported_gross_and_net():
    bars = confirmed_rectangle_with_runway()
    row = extraction.extract_events(bars, "SYN1")[0]
    by_h = row["costs"]["by_horizon"]
    assert set(by_h.keys()) == {1, 3, 5, 10, 20}
    for h, block in by_h.items():
        assert block["available"] is True
        base = block["scenarios"]["base"]
        assert "gross" in base and "net_before_tax" in base and "total_cost" in base
        assert base["net_before_tax"] != base["gross"]  # costs actually deducted


def test_liquidity_block_reports_adv_qty_position_value_participation():
    bars = confirmed_rectangle_with_runway()
    row = extraction.extract_events(bars, "SYN1")[0]
    liq = row["liquidity"]
    assert liq["adv_inr_at_t"] is not None
    assert liq["qty"] > 0
    assert liq["position_value_inr"] == pytest.approx(liq["qty"] * row["entry"]["primary"]["price"])
    assert liq["participation_ratio"] is not None


def test_versioning_block_has_every_prd_field():
    bars = confirmed_rectangle_with_runway()
    row = extraction.extract_events(bars, "SYN1")[0]
    v = row["versioning"]
    assert set(v.keys()) == {
        "signal_timestamp", "data_cutoff_timestamp", "config_hash", "engine_version",
        "cost_rule_version", "tax_rule_version", "slippage_model_version", "dataset_version",
    }
    assert v["signal_timestamp"] == row["signal_date"]
    assert v["data_cutoff_timestamp"] == row["signal_date"]
    assert v["cost_rule_version"] == "nse-equity-statutory-v1@1"
    assert v["tax_rule_version"] == "tax-equity-v1@1"


def test_event_never_dropped_when_no_bar_after_confirmation():
    """A confirmation on the LAST bar of the frame supplied has no t+1 open to enter at -- the
    row must still be emitted (never silently dropped), with outcomes/costs explicitly
    unavailable."""
    full = confirmed_rectangle_with_runway(tail_len=0)
    # Truncate to exactly the confirmation bar itself (no bar after it at all).
    from research.charting import replay

    result = replay.replay(full, symbol="SYN1")
    confirmed = [t for t in result.transitions if t.new_status == "PRICE_CONFIRMED"]
    assert confirmed
    t_idx = confirmed[0].event_index
    truncated = full.iloc[: t_idx + 1].reset_index(drop=True)
    rows = extraction.extract_events(truncated, "SYN1")
    assert len(rows) == 1
    row = rows[0]
    assert row["entry"]["primary"] is None
    assert row["unavailable_reason"] == "no_bar_after_confirmation"
    assert row["outcomes"] is None
    assert row["costs"] is None
    # The alternative close-t entry is still recorded (it never needs a t+1 bar) even though
    # the primary/outcomes/costs are unavailable.
    assert row["entry"]["alternative_close_t"]["price"] == pytest.approx(truncated["close"].iloc[-1])


def test_extract_events_multi_visits_symbols_in_sorted_order():
    from research.charting.events import extraction as ext

    bars_a = confirmed_rectangle_with_runway()
    rows_direct = ext.extract_events(bars_a, "AAA") + ext.extract_events(bars_a, "ZZZ")
    rows_multi = ext.extract_events_multi({"ZZZ": bars_a, "AAA": bars_a})
    assert [r["symbol"] for r in rows_multi] == [r["symbol"] for r in rows_direct]
