"""study/report.py: CHARTING_PREREGISTRATION_V1 §7 report tables. Helper-level tests use
small, hand-built row fixtures (only the sub-schema each function reads) with hand-computed
expected numbers; `test_build_report_*` integration tests run the real extraction/controls
pipeline over tiny synthetic symbols end to end."""
from __future__ import annotations

import json
import math

import pytest

from research.charting.events import controls, extraction
from research.charting.study import report
from research.charting.tests._events_helpers import confirmed_rectangle_with_runway


# ── hit_rate_table ────────────────────────────────────────────────────────────────────────


def _target_row(event_id, *, first_exit_event, holding_period=None, net_before_tax=None):
    exit_block = None
    if first_exit_event in ("TARGET", "STOP") and holding_period is not None:
        exit_block = {
            "holding_period_sessions": holding_period,
            "gross_return": 0.02,
            "costs": {"scenarios": {"base": {"net_before_tax": net_before_tax}}},
        }
    block = {
        "available": True,
        "target_hit": first_exit_event == "TARGET",
        "stop_hit": first_exit_event == "STOP",
        "both_hit": first_exit_event == "AMBIGUOUS",
        "neither_hit": first_exit_event == "NONE",
        "first_exit_event": first_exit_event,
        "exit": exit_block,
    }
    return {"event_id": event_id, "targets": {"pct_2": {"by_horizon": {5: block}}}}


def test_hit_rate_table_hand_computed():
    rows = (
        [_target_row(f"T{i}", first_exit_event="TARGET", holding_period=3, net_before_tax=0.01) for i in range(10)]
        + [_target_row(f"T{i}", first_exit_event="TARGET", holding_period=4, net_before_tax=-0.005) for i in range(10, 15)]
        + [_target_row(f"S{i}", first_exit_event="STOP", holding_period=2, net_before_tax=-0.02) for i in range(3)]
        + [_target_row("A0", first_exit_event="AMBIGUOUS")]
        + [_target_row("N0", first_exit_event="NONE")]
    )
    out = report.hit_rate_table(rows, "pct_2", 5)
    assert out["n"] == 20
    assert out["insufficient_n"] is True  # n=20 < MIN_N=30 -- still fully reported, never dropped
    assert out["gross_hit_rate"] == pytest.approx(15 / 20)
    assert out["net_hit_rate"] == pytest.approx(10 / 20)  # only the 10 TARGET rows with net > 0
    assert out["target_first_share"] == pytest.approx(15 / 20)
    assert out["stop_first_share"] == pytest.approx(3 / 20)
    assert out["ambiguous_share"] == pytest.approx(1 / 20)
    assert out["neither_share"] == pytest.approx(1 / 20)
    assert out["counts"] == {"target_first": 15, "stop_first": 3, "ambiguous": 1, "neither": 1}
    # 15 holding periods of 3 (x10) and 4 (x5), plus 3 of 2 (stop) -- median of 18 values.
    import statistics
    holding = [3] * 10 + [4] * 5 + [2] * 3
    assert out["median_holding_period"] == pytest.approx(statistics.median(holding))


def test_hit_rate_table_empty_is_insufficient_n_not_a_crash():
    out = report.hit_rate_table([], "pct_2", 5)
    assert out["n"] == 0
    assert out["insufficient_n"] is True
    assert out["gross_hit_rate"] is None
    assert out["median_holding_period"] is None


def test_hit_rate_table_below_30_marked_insufficient_but_still_reported():
    rows = [_target_row(f"T{i}", first_exit_event="TARGET", holding_period=1, net_before_tax=0.01) for i in range(5)]
    out = report.hit_rate_table(rows, "pct_2", 5)
    assert out["n"] == 5
    assert out["insufficient_n"] is True
    assert out["gross_hit_rate"] == 1.0  # still a real number -- never dropped


# ── return_stats ──────────────────────────────────────────────────────────────────────────


def _cost_row(event_id, signal_date, *, gross, net, total_cost, entry_slip=1.0, exit_slip=1.0, horizon=5, scenario="base"):
    return {
        "event_id": event_id, "signal_date": signal_date,
        "costs": {"by_horizon": {horizon: {"available": True, "scenarios": {
            scenario: {"gross": gross, "net_before_tax": net, "total_cost": total_cost,
                       "entry_slippage": entry_slip, "exit_slippage": exit_slip}
        }}}},
    }


def test_return_stats_hand_computed_expectancy_profit_factor_drawdown():
    # Sequential (by signal_date) net returns: +0.02, -0.01, +0.03, -0.02, +0.01
    rows = [
        _cost_row("E1", "2021-01-04", gross=0.025, net=0.02, total_cost=0.005),
        _cost_row("E2", "2021-01-05", gross=-0.005, net=-0.01, total_cost=0.005),
        _cost_row("E3", "2021-01-06", gross=0.035, net=0.03, total_cost=0.005),
        _cost_row("E4", "2021-01-07", gross=-0.015, net=-0.02, total_cost=0.005),
        _cost_row("E5", "2021-01-08", gross=0.015, net=0.01, total_cost=0.005),
    ]
    out = report.return_stats(rows, 5)
    assert out["n"] == 5
    net_vals = [0.02, -0.01, 0.03, -0.02, 0.01]
    assert out["net_return"]["mean"] == pytest.approx(sum(net_vals) / 5)
    assert out["net_return"]["median"] == pytest.approx(0.01)
    assert out["gross_return"]["mean"] == pytest.approx((0.025 - 0.005 + 0.035 - 0.015 + 0.015) / 5)
    assert out["avg_cost"] == pytest.approx(0.005)
    assert out["avg_slippage"] == pytest.approx(2.0)  # 1.0 + 1.0 every row
    assert out["net_expectancy"] == pytest.approx(sum(net_vals) / 5)
    wins = [0.02, 0.03, 0.01]
    losses = [-0.01, -0.02]
    assert out["win_rate"] == pytest.approx(3 / 5)
    assert out["avg_win"] == pytest.approx(sum(wins) / 3)
    assert out["avg_loss"] == pytest.approx(sum(losses) / 2)
    assert out["profit_factor"] == pytest.approx(sum(wins) / (-sum(losses)))
    # Equity curve (cumulative, in signal_date order): 0.02, 0.01, 0.04, 0.02, 0.03
    # Running max:                                     0.02, 0.02, 0.04, 0.04, 0.04
    # Drawdown:                                         0.00,-0.01, 0.00,-0.02,-0.01 -> min -0.02
    assert out["max_drawdown"] == pytest.approx(-0.02)


def test_return_stats_orders_by_signal_date_not_input_order():
    rows = [
        _cost_row("LATER", "2021-02-01", gross=0.0, net=-0.05, total_cost=0.0),
        _cost_row("EARLIER", "2021-01-01", gross=0.0, net=0.05, total_cost=0.0),
    ]
    out = report.return_stats(rows, 5)
    # Equity curve in DATE order: +0.05, 0.00 -- running max 0.05, 0.05 -- drawdown 0, -0.05
    assert out["max_drawdown"] == pytest.approx(-0.05)


def test_return_stats_empty_reports_n_zero_insufficient_never_crashes():
    out = report.return_stats([], 5)
    assert out == report.n_cell(0) | {
        "gross_return": {"median": None, "mean": None}, "net_return": {"median": None, "mean": None},
        "avg_cost": None, "avg_slippage": None, "net_expectancy": None, "profit_factor": None,
        "win_rate": None, "avg_win": None, "avg_loss": None, "max_drawdown": None,
    }


def test_return_stats_all_wins_profit_factor_is_infinite_not_fabricated():
    rows = [_cost_row(f"E{i}", f"2021-01-0{i+1}", gross=0.01, net=0.01, total_cost=0.0) for i in range(3)]
    out = report.return_stats(rows, 5)
    assert out["profit_factor"] == math.inf


# ── mfe_mae_stats ─────────────────────────────────────────────────────────────────────────


def test_mfe_mae_stats_hand_computed():
    rows = [
        {"outcomes": {"forward_returns": {5: {"available": True, "mfe": 0.05, "mae": -0.02}}}},
        {"outcomes": {"forward_returns": {5: {"available": True, "mfe": 0.09, "mae": -0.01}}}},
        {"outcomes": {"forward_returns": {5: {"available": False, "reason": "insufficient_forward_bars"}}}},
    ]
    out = report.mfe_mae_stats(rows, 5)
    assert out["n"] == 2
    assert out["median_mfe"] == pytest.approx((0.05 + 0.09) / 2)
    assert out["median_mae"] == pytest.approx((-0.02 + -0.01) / 2)


# ── cost_sensitivity_table ────────────────────────────────────────────────────────────────


def test_cost_sensitivity_table_has_all_four_scenarios_and_reads_each_independently():
    rows = [{
        "event_id": "E1", "signal_date": "2021-01-04",
        "costs": {"by_horizon": {5: {"available": True, "scenarios": {
            "optimistic": {"gross": 0.02, "net_before_tax": 0.018, "total_cost": 0.002, "entry_slippage": 0.1, "exit_slippage": 0.1},
            "base": {"gross": 0.02, "net_before_tax": 0.015, "total_cost": 0.005, "entry_slippage": 0.2, "exit_slippage": 0.2},
            "conservative": {"gross": 0.02, "net_before_tax": 0.010, "total_cost": 0.010, "entry_slippage": 0.3, "exit_slippage": 0.3},
            "stress": {"gross": 0.02, "net_before_tax": 0.005, "total_cost": 0.015, "entry_slippage": 0.4, "exit_slippage": 0.4},
        }}}},
    }]
    out = report.cost_sensitivity_table(rows, 5)
    assert set(out.keys()) == {"optimistic", "base", "conservative", "stress"}
    assert out["optimistic"]["net_return"]["mean"] == pytest.approx(0.018)
    assert out["stress"]["net_return"]["mean"] == pytest.approx(0.005)
    assert out["optimistic"]["net_expectancy"] > out["stress"]["net_expectancy"]


# ── percentile_rank ───────────────────────────────────────────────────────────────────────


def test_percentile_rank_hand_computed():
    dist = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert report.percentile_rank(5, dist) == pytest.approx(50.0)
    assert report.percentile_rank(10, dist) == pytest.approx(100.0)
    assert report.percentile_rank(0, dist) == pytest.approx(0.0)


def test_percentile_rank_none_for_missing_value_or_empty_distribution():
    assert report.percentile_rank(None, [1, 2, 3]) is None
    assert report.percentile_rank(5, []) is None


# ── comparison_block ──────────────────────────────────────────────────────────────────────


def test_comparison_block_random_batch_percentile():
    pattern_rows = [_cost_row("P1", "2021-01-04", gross=0.03, net=0.03, total_cost=0.0)]
    random_batch = {
        seed: [_cost_row(f"R{seed}", "2021-01-04", gross=v, net=v, total_cost=0.0)]
        for seed, v in enumerate([0.0, 0.01, 0.02, 0.04, 0.05])
    }
    out = report.comparison_block(pattern_rows, 5, random_batch=random_batch)
    assert out["random_200_seed"]["n_seeds_total"] == 5
    # pattern net=0.03 is above 3 of the 5 seed means (0.0,0.01,0.02) and below 2 (0.04,0.05)
    assert out["random_200_seed"]["pattern_percentile_within_seed_distribution"] == pytest.approx(60.0)


def test_comparison_block_atr_decile_percentile():
    pattern_rows = [_cost_row("P1", "2021-01-04", gross=0.03, net=0.03, total_cost=0.0)]
    atr_rows = [_cost_row(f"D{i}", "2021-01-04", gross=v, net=v, total_cost=0.0) for i, v in enumerate([0.0, 0.01, 0.02, 0.04])]
    out = report.comparison_block(pattern_rows, 5, atr_decile_rows=atr_rows)
    assert out["atr_decile_matched"]["n"] == 4
    assert out["atr_decile_matched"]["pattern_percentile_within_distribution"] == pytest.approx(75.0)


def test_comparison_block_nifty_and_buy_next_open_passthrough():
    pattern_rows = [_cost_row("P1", "2021-01-04", gross=0.03, net=0.03, total_cost=0.0)]
    bno_rows = [_cost_row("B1", "2021-01-04", gross=0.01, net=0.01, total_cost=0.0)]
    out = report.comparison_block(pattern_rows, 5, buy_next_open_rows=bno_rows, nifty_500_return=0.008)
    assert out["buy_next_open"]["net_return"]["mean"] == pytest.approx(0.01)
    assert out["nifty_500"]["return"] == pytest.approx(0.008)


# ── segmentation ──────────────────────────────────────────────────────────────────────────


def test_liquidity_bucket_label_matches_frozen_thresholds():
    assert report.liquidity_bucket_label(None) == "UNKNOWN"
    assert report.liquidity_bucket_label(2_000_000_000) == "LIQUIDITY_BUCKET_0"  # >= 100cr
    assert report.liquidity_bucket_label(300_000_000) == "LIQUIDITY_BUCKET_1"  # >= 25cr
    assert report.liquidity_bucket_label(1_000) == "LIQUIDITY_BUCKET_2"  # everything else


def test_atr_bucket_labels_terciles_and_unknown_fallback():
    rows = [{"event_id": f"E{i}", "atr_at_t": v, "entry": {"primary": {"price": 100.0}}} for i, v in enumerate([1, 2, 3, 4, 5, 6])]
    labels = report.atr_bucket_labels(rows)
    assert set(labels.values()) <= {"LOW_VOL", "MID_VOL", "HIGH_VOL"}
    assert labels["E0"] == "LOW_VOL"  # smallest ATR%
    assert labels["E5"] == "HIGH_VOL"  # largest ATR%


def test_atr_bucket_labels_too_few_rows_are_unknown():
    rows = [{"event_id": "E0", "atr_at_t": 1.0, "entry": {"primary": {"price": 100.0}}}]
    labels = report.atr_bucket_labels(rows)
    assert labels["E0"] == "UNKNOWN"


def test_segment_rows_by_context_dimension():
    rows = [
        {"event_id": "E0", "context": {"trend_class_class": "BULL"}},
        {"event_id": "E1", "context": {"trend_class_class": "BEAR"}},
        {"event_id": "E2", "context": None},
    ]
    buckets = report.segment_rows(rows, dimension="stock_trend_class")
    assert set(buckets.keys()) == {"BULL", "BEAR", "NO_CONTEXT"}
    assert len(buckets["NO_CONTEXT"]) == 1


def test_segment_rows_unknown_dimension_raises():
    with pytest.raises(ValueError):
        report.segment_rows([], dimension="not_a_real_dimension")


# ── bearish_directional_report ───────────────────────────────────────────────────────────


def test_bearish_directional_report_only_reads_bearish_rows():
    rows = [
        {"direction": "BULLISH", "outcomes": {"forward_returns_directional": {5: {"available": True, "close_return_directional": 0.5}},
                                               "forward_returns": {5: {"available": True, "mfe": 0.9, "mae": -0.9}}}},
        {"direction": "BEARISH", "outcomes": {"forward_returns_directional": {5: {"available": True, "close_return_directional": 0.03}},
                                               "forward_returns": {5: {"available": True, "mfe": 0.01, "mae": -0.05}}}},
        {"direction": "BEARISH", "outcomes": {"forward_returns_directional": {5: {"available": True, "close_return_directional": -0.01}},
                                               "forward_returns": {5: {"available": True, "mfe": 0.02, "mae": -0.02}}}},
    ]
    out = report.bearish_directional_report(rows, 5)
    assert out["n"] == 2  # the BULLISH row is excluded
    assert out["directional_return"]["mean"] == pytest.approx((0.03 - 0.01) / 2)


# ── move_direction_auc_report (reuses movement.py) ───────────────────────────────────────


def test_move_direction_auc_report_wires_real_movement_module():
    bars = confirmed_rectangle_with_runway(tail_len=40)
    events = extraction.extract_events(bars, "SYN1")
    out = report.move_direction_auc_report(events, {"SYN1": bars}, horizons=(1, 5))
    assert set(out.keys()) == {("RECTANGLE", 1), ("RECTANGLE", 5)}
    for cell in out.values():
        assert "move_auc" in cell and "direction_auc" in cell


# ── to_json_dict / render_markdown ───────────────────────────────────────────────────────


def test_to_json_dict_replaces_nan_and_infinity_with_null():
    payload = {"a": float("nan"), "b": float("inf"), "c": {"d": [float("-inf"), 1.0]}}
    safe = report.to_json_dict(payload)
    assert safe == {"a": None, "b": None, "c": {"d": [None, 1.0]}}
    json.dumps(safe, allow_nan=False)  # must not raise


def test_render_markdown_is_nonempty_and_traceable():
    bars = confirmed_rectangle_with_runway(tail_len=40)
    events = extraction.extract_events(bars, "SYN1")
    r = report.build_report(segment="pre_sealed", pattern_rows=events, bars_by_symbol={"SYN1": bars},
                             exclusion_counts={"data_quality": 0, "demerger_window": 0})
    md = report.render_markdown(r)
    assert "# Chart-pattern validation report" in md
    assert "RECTANGLE" in md
    assert "n=" in md  # counts sit next to rates


# ── build_report: integration ─────────────────────────────────────────────────────────────


def test_build_report_end_to_end_shape_and_json_safety():
    bars_a = confirmed_rectangle_with_runway(tail_len=40)
    events = extraction.extract_events(bars_a, "SYN1")
    bars_by_symbol = {"SYN1": bars_a}

    eligible = [("SYN1", i) for i in range(20, 35)]
    random_batch = controls.random_control_batch(bars_by_symbol, eligible, n=2, seeds=(0, 1, 2))
    atr_rows = controls.atr_decile_control_rows(bars_by_symbol, events, eligible, seed=0)
    bno_rows = controls.buy_next_open_baseline_rows(bars_by_symbol, events)

    comparison_groups = {
        "RECTANGLE": {
            "random_batch": random_batch, "atr_decile_rows": atr_rows, "buy_next_open_rows": bno_rows,
            "nifty_500_return_by_horizon": {1: 0.001, 3: 0.003, 5: 0.005, 10: 0.01, 20: 0.02},
        }
    }

    r = report.build_report(
        segment="pre_sealed", pattern_rows=events, bars_by_symbol=bars_by_symbol,
        exclusion_counts={"data_quality": 2, "demerger_window": 1},
        comparison_groups_by_family=comparison_groups,
        universe_caveats=["ETF list known to exclude some real equities"],
        unverified_cost_rates=[], input_hashes={"kite_day_2021_part0": "deadbeef"},
        prereg_sha256="abc123",
    )

    assert r["segment"] == "pre_sealed"
    assert r["prereg_sha256"] == "abc123"
    assert r["exclusions"]["total_excluded"] == 3
    assert "RECTANGLE" in r["families"]
    fam = r["families"]["RECTANGLE"]
    assert fam["n_bullish"] + fam["n_bearish"] == fam["n_total"]["n"]
    for h in (1, 3, 5, 10, 20):
        cell = fam["horizons"][h]
        assert set(cell["targets"].keys()) == set(report.DEFAULT_TARGET_NAMES)
        assert "comparisons" in cell
        assert cell["comparisons"]["nifty_500"]["return"] == pytest.approx({1: 0.001, 3: 0.003, 5: 0.005, 10: 0.01, 20: 0.02}[h])
        assert set(report.SEGMENTATION_DIMENSIONS) == set(cell["segmentation"].keys())
        assert "bearish" in cell

    safe = report.to_json_dict(r)
    json.dumps(safe, allow_nan=False)  # strict JSON, must not raise

    md = report.render_markdown(r)
    assert isinstance(md, str) and len(md) > 0


def test_build_report_never_drops_a_family_for_being_unfavourable():
    """§1/§7: every family present in the rows gets a cell, whatever the sign."""
    bars_rect = confirmed_rectangle_with_runway(tail_len=40)
    from research.charting.tests._events_helpers import confirmed_hh_hl_with_runway
    bars_hh = confirmed_hh_hl_with_runway(tail_len=40)

    events = extraction.extract_events(bars_rect, "SYN1") + extraction.extract_events(bars_hh, "ZZ")
    bars_by_symbol = {"SYN1": bars_rect, "ZZ": bars_hh}
    r = report.build_report(segment="pre_sealed", pattern_rows=events, bars_by_symbol=bars_by_symbol,
                             exclusion_counts={})
    assert {"RECTANGLE", "HH_HL"} <= set(r["families"].keys())
