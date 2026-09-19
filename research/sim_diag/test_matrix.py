"""Comparison-matrix runner helpers (matrix.py) — synthetic frames with every expected number worked by hand.

What is pinned here, and why:

- **The §4 / §4a / §4b specification table.** Every field of every MATRIX, SECONDARY and POOL spec is compared
  against the pre-registration's own words (PREREGISTRATION_SIM_MATRIX.md, frozen at ffa0a139), not read back out
  of the module, so a parameter edited after the freeze fails the suite instead of quietly changing the run.
- **The §5 metric definitions**, including the two that are easy to swap (`worst_cumulative_net` is the lowest point
  of the cumulative net, `worst_peak_to_trough` is the largest fall from a peak — the fixture makes them differ),
  the portfolio-only drawdown branch, and the deliberately-absent capital figure for run G.
- **§5a's tax annex arithmetic** (both regimes, both with the 4% cess).
- **§4a's random control**: k symbols a session, without replacement, one generator per seed, symbols sorted before
  the draw so row order cannot move it; and a percentile that is A's place *below* the seed distribution.
- The rank bands, the extreme-trade audit, and the signal / trade frames that feed the risk engine.
- **One end-to-end portfolio run** on three synthetic symbols under SIM-MATRIX-F and SIM-MATRIX-D, which proves the
  2% / 5% levels are re-derived from the FILL's raw base (not from the decision close the signal carried) and that
  F's allocation caps refuse a candidate D takes.

No market data, no database, no network: every frame is built in this file.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matrix as MX  # noqa: E402
import tradesim as TS  # noqa: E402
from decimal import Decimal as D  # noqa: E402
from nidp.services.tpd_model.risk import engine as EN  # noqa: E402

CM = TS.CC.load_cost_model("zerodha-equity-v1")


# ============================== §4: the frozen specification table ==============================

SPEC_FIELDS = tuple(f.name for f in dataclasses.fields(TS.Spec))
# §4 "Baseline conventions for every fixed-notional run", transcribed from the pre-registration.
BASELINE = {
    "entry": "NEXT_OPEN", "stop": "FIXED", "target": "FIXED", "stop_pct": D("2"), "target_pct": D("5"),
    "target_r": D("2"), "atr_mult": D("1.5"), "vol_mult": D("1.5"), "structure_buffer_pct": D("0.1"),
    "stop_bounds_pct": (D("1"), D("8")), "confirm_buffer_pct": D("0.1"), "limit_discount_pct": D("0.5"),
    "max_chase_pct": None, "notional": D("50000"), "sessions": 5, "carry_sessions": 25, "costs_on": True,
    "slippage_basis": "DECISION", "policy": "STOP_FIRST", "participation_pct": D("100"), "frozen": True,
}


def fields(s: TS.Spec) -> dict:
    return {f: getattr(s, f) for f in SPEC_FIELDS}


def spec(name: str, **changes) -> dict:
    """The §4 baseline with the one documented change of that row, and nothing else."""
    out = {"name": name, **BASELINE}
    out.update(changes)
    return out


def test_the_matrix_rows_are_the_preregistered_ones_parameter_by_parameter():
    assert set(MX.MATRIX) == {"A", "B", "C", "E", "H"}          # D, F are portfolio runs; G is a selection control
    assert MX.MATRIX["A"] is TS.CONFIG_A                        # A is the reconciled H#32 baseline, not a copy
    assert fields(MX.MATRIX["A"]) == spec("A")
    assert fields(MX.MATRIX["B"]) == spec("B", stop="ATR", target="R_MULTIPLE", atr_mult=D("1.5"), target_r=D("2"))
    assert fields(MX.MATRIX["C"]) == spec("C", entry="OPEN_CONFIRMATION", confirm_buffer_pct=D("0.1"))
    assert fields(MX.MATRIX["E"]) == spec("E", costs_on=False)
    assert fields(MX.MATRIX["H"]) == spec("H", stop="NONE", target="NONE")
    # the baseline conventions, spelled out once more so a changed dataclass default is caught too
    for k, s in MX.MATRIX.items():
        assert s.notional == D("50000"), k                      # 50,000 a trade
        assert s.sessions == 5, k                               # at most 5 sessions
        assert s.slippage_basis == "DECISION", k                # the decision day's value20 bucket
        assert s.policy == "STOP_FIRST", k                      # stop-first on an ambiguous bar
        assert s.participation_pct == D("100"), k               # participation not capped
        assert s.max_chase_pct is None, k                       # "Max chase is not applied in the matrix"
        assert s.frozen is True, k
    assert MX.MATRIX["E"].costs_on is False
    assert all(MX.MATRIX[k].costs_on is True for k in ("A", "B", "C", "H"))


def test_the_secondary_rows_and_the_whole_pool_row():
    assert set(MX.SECONDARY) == {"S1_STRUCTURE", "S2_VOL_ADJ", "S3_LIMIT", "S4_VWAP"}
    # S1: lowest low of the 10 sessions to D less 0.1%, bounded 1-8% below entry; target 2R
    assert fields(MX.SECONDARY["S1_STRUCTURE"]) == spec(
        "S1_STRUCTURE", stop="STRUCTURE", target="R_MULTIPLE", structure_buffer_pct=D("0.1"),
        stop_bounds_pct=(D("1"), D("8")), target_r=D("2"))
    # S2: entry x (1 - 1.5 sigma20), bounded 1-8%; target 2.5R
    assert fields(MX.SECONDARY["S2_VOL_ADJ"]) == spec(
        "S2_VOL_ADJ", stop="VOL_ADJ", target="R_MULTIPLE", vol_mult=D("1.5"),
        stop_bounds_pct=(D("1"), D("8")), target_r=D("2.5"))
    # S3: limit at D close x 0.995
    assert fields(MX.SECONDARY["S3_LIMIT"]) == spec("S3_LIMIT", entry="LIMIT_ENTRY", limit_discount_pct=D("0.5"))
    # S4: s1 (high + low + close) / 3
    assert fields(MX.SECONDARY["S4_VWAP"]) == spec("S4_VWAP", entry="VWAP_PROXY")
    # S5: every eligible candidate under A's rules -> A's parameters exactly, only the name differs
    assert fields(MX.POOL) == spec("S5_POOL")
    assert MX.POOL.name == "S5_POOL"


def test_the_portfolio_control_and_bootstrap_constants():
    assert MX.PORTFOLIO == {"D": "SIM-MATRIX-D", "F": "SIM-MATRIX-F"}      # D = no caps, F = all caps
    assert MX.RISK_LEVELS == (D("0.5"), D("1.0"), D("2.0"))                # §4b sensitivity
    assert MX.F_POSITIONS == (8, 5)                                        # 8 is the baseline
    assert MX.EXITS == {"breakeven_at_r": D("1000000"), "trail_at_r": D("1000000"), "trail_atr_mult": D("2"),
                        "max_sessions": 5, "cost_estimate_pct_for_sizing": D("0.5")}
    assert MX.EXITS["breakeven_at_r"] > D("1000") and MX.EXITS["trail_at_r"] > D("1000")   # both effectively off
    assert (MX.SEED_RANDOM, MX.RANDOM_SEEDS, MX.BOOT_REPS, MX.TOP_K) == (20260920, 200, 2000, 5)
    assert MX.STOPPED == ("STOP_HIT", "GAP_THROUGH_STOP")
    assert MX.PREREG == "PREREGISTRATION_SIM_MATRIX.md @ ffa0a139"


# ============================== simulate_rows / frame / rejections ==============================

DAY0 = dt.date(2022, 10, 3)


def bar(o, h, l, c, v=1_000_000, pc=None):
    return TS.EX.Bar(D(str(o)), D(str(h)), D(str(l)), D(str(c)), v, D(str(pc)) if pc is not None else D(str(o)))


QUIET = bar(100, 101, 99, 100)


def window(symbol, bars, atr_pct=3.0, d_close=100, value20=3e8):
    dates = [DAY0 + dt.timedelta(days=i + 1) for i in range(len(bars))]
    return TS.Window(symbol, DAY0, D(str(d_close)), D("101"), D("99"), value20, atr_pct, dates=dates, bars=bars)


class FakeStore:
    """Stands in for panel.BarStore: records the (symbol, date, atr_pct) it was asked for."""

    def __init__(self, bars_by_symbol):
        self.bars_by_symbol = bars_by_symbol
        self.calls = []

    def window(self, symbol, date, atr_pct):
        self.calls.append((symbol, date, atr_pct))
        return window(symbol, self.bars_by_symbol[symbol], atr_pct=atr_pct)


def test_simulate_rows_uses_each_rows_own_atr_and_tags_the_dataset_row():
    rows = pd.DataFrame({"symbol": ["AAA", "BBB"], "date": [pd.Timestamp("2022-10-03")] * 2}, index=[7, 9])
    ds = pd.DataFrame({"atr_pct": [3.0, 4.5]}, index=[7, 9])
    store = FakeStore({"AAA": [bar(100, 104, 99, 103), bar(103, 106, 102, 105)] + [QUIET] * 3,
                       "BBB": [bar(100, 101, 96, 97)] + [QUIET] * 4})
    out = MX.simulate_rows(TS.CONFIG_A, rows, store, ds, CM)
    assert store.calls == [("AAA", pd.Timestamp("2022-10-03"), 3.0), ("BBB", pd.Timestamp("2022-10-03"), 4.5)]
    assert [t["row"] for t in out] == [7, 9]                    # the dataset index, not 0..n
    assert [t["symbol"] for t in out] == ["AAA", "BBB"]
    assert out[0]["exit_reason"] == "TARGET_HIT" and out[1]["exit_reason"] == "STOP_HIT"


def test_frame_keeps_only_closed_trades_and_takes_the_values_from_the_fills():
    # the hand-worked configuration-A target trade: entry 100.10 (0.10% bucket), 499 shares, exit level 105
    closed = TS.simulate(TS.CONFIG_A, window("AAA", [bar(100, 104, 99, 103), bar(103, 106, 102, 105)] + [QUIET] * 3), CM)
    closed["row"] = 11
    rejected = TS.simulate(TS.CONFIG_A, window("BBB", [None, QUIET]), CM)
    f = MX.frame([closed, rejected])
    assert len(f) == 1 and f.config.iloc[0] == "A" and f.symbol.iloc[0] == "AAA"
    assert f.qty.iloc[0] == 499 and isinstance(f.qty.iloc[0].item(), int)
    assert f.buy_value.iloc[0] == pytest.approx(100.10 * 499)           # fills[0]["value"] = 49,949.90
    assert f.sell_value.iloc[0] == pytest.approx(104.90 * 499)          # fills[1]["value"] = 52,345.10
    assert f.gross_inr.iloc[0] == pytest.approx(2495.0) and f.net_inr.iloc[0] == pytest.approx(2266.24)
    assert f.row.iloc[0] == 11
    assert f.decision_date.iloc[0] == pd.Timestamp("2022-10-03") and f.entry_date.iloc[0] == pd.Timestamp("2022-10-04")
    assert f.intrabar_ambiguous.iloc[0] is np.False_ or f.intrabar_ambiguous.iloc[0] == False  # noqa: E712


def test_rejections_counts_the_entry_reason_then_falls_back():
    no_bar = TS.simulate(TS.CONFIG_A, window("AAA", [None, QUIET]), CM)
    locked = TS.simulate(TS.CONFIG_A, window("BBB", [bar(110, 110, 108, 109, pc=100), QUIET]), CM)
    unresolved = {"status": "UNRESOLVED", "exit_reason": "MANUAL_REVIEW_REQUIRED"}
    closed = TS.simulate(TS.CONFIG_A, window("CCC", [QUIET] * 5), CM)
    assert MX.rejections([no_bar, locked, unresolved, closed, no_bar]) == {
        "NO_BAR_S1": 2, "LOCKED_UPPER": 1, "MANUAL_REVIEW_REQUIRED": 1}
    assert MX.rejections([{"status": "WEIRD"}]) == {"WEIRD": 1}          # last fallback is the status itself


# ============================== §5: metrics ==============================

CAL = pd.date_range("2022-01-03", "2022-01-11", freq="D")
INDUSTRY = {"AAA": "Auto", "BBB": "Auto", "CCC": "Banks", "DDD": "Banks", "EEE": "Pharma",
            "FFF": "Auto", "GGG": "Banks"}


def t_row(symbol, entry, exit_, gross_ret, net_ret, gross_inr, net_inr, exit_reason, sd_atr, amb, flags, mfe, mae,
          slippage=100.0, charges=100.0, buy_value=50000.0):
    return {"symbol": symbol, "entry_date": pd.Timestamp(entry), "exit_date": pd.Timestamp(exit_),
            "gross_ret": gross_ret, "net_ret": net_ret, "gross_inr": gross_inr, "net_inr": net_inr,
            "slippage_inr": slippage, "charges_inr": charges, "buy_value": buy_value, "exit_reason": exit_reason,
            "stop_distance_atr": sd_atr, "intrabar_ambiguous": amb, "flags": flags, "mfe_pct": mfe, "mae_pct": mae}


def five_trades() -> pd.DataFrame:
    """Five trades, deliberately overlapping in time and with one exactly-zero net."""
    return pd.DataFrame([
        t_row("AAA", "2022-01-03", "2022-01-05", 0.01, 0.006, 500.0, 300.0, "TARGET_HIT", 1.0, False, "", 0.05, -0.01),
        t_row("BBB", "2022-01-03", "2022-01-06", -0.02, -0.024, -1000.0, -1200.0, "STOP_HIT", 0.8, True, "", 0.01, -0.03),
        t_row("CCC", "2022-01-04", "2022-01-07", -0.04, -0.044, -2000.0, -2200.0, "GAP_THROUGH_STOP", 1.2, False,
              "LOCKED_LOWER_FULLDAY_S2", 0.00, -0.05),
        t_row("DDD", "2022-01-05", "2022-01-10", 0.00, 0.000, 0.0, 0.0, "TIME_EXIT", 1.4, False, "", 0.02, -0.01),
        t_row("EEE", "2022-01-06", "2022-01-11", 0.03, 0.026, 1500.0, 1300.0, "TARGET_HIT", 1.6, True,
              "NO_BAR_S2;LOCKED_LOWER_PARTIAL_S3", 0.06, 0.00),
    ])


def test_metrics_every_headline_number_by_hand():
    m = MX.metrics("A", five_trades(), {"NO_BAR_S1": 2, "LOCKED_UPPER": 1}, CAL, INDUSTRY)
    assert m["config"] == "A" and m["trades"] == 5
    assert m["no_entry"] == 3 and m["no_entry_reasons"] == {"NO_BAR_S1": 2, "LOCKED_UPPER": 1}
    assert m["win_rate"] == pytest.approx(0.4)                          # 2 of 5 have net > 0; the zero is not a win
    # (0.01 - 0.02 - 0.04 + 0.00 + 0.03) / 5 and (0.006 - 0.024 - 0.044 + 0.000 + 0.026) / 5
    assert m["gross_per_trade"] == pytest.approx(-0.004)
    assert m["net_per_trade"] == pytest.approx(-0.0072)
    assert m["cost_drag"] == pytest.approx(0.0032)                      # gross - net, a positive drag on a loser
    assert m["slippage_per_trade"] == pytest.approx(0.002)              # 100 / 50,000
    assert m["charges_per_trade"] == pytest.approx(0.002)
    assert m["gross_inr"] == pytest.approx(-1000.0) and m["net_inr"] == pytest.approx(-1800.0)
    assert m["slippage_inr"] == pytest.approx(500.0) and m["charges_inr"] == pytest.approx(500.0)
    assert m["expectancy_inr"] == pytest.approx(-360.0)                 # -1800 / 5
    assert m["profit_factor"] == pytest.approx(1600.0 / 3400.0)         # (300 + 1300) / |-1200 - 2200|
    assert m["largest_win_inr"] == pytest.approx(1300.0) and m["largest_loss_inr"] == pytest.approx(-2200.0)
    assert m["longest_losing_streak"] == 3                              # -1200, -2200, 0 (a zero is not a win)
    assert m["exit_mix"] == {"TARGET_HIT": 2, "STOP_HIT": 1, "GAP_THROUGH_STOP": 1, "TIME_EXIT": 1}
    assert m["stop_hit_rate"] == pytest.approx(0.4)                     # STOP_HIT + GAP_THROUGH_STOP
    assert m["target_hit_rate"] == pytest.approx(0.4)
    assert m["median_stop_distance_atr"] == pytest.approx(1.2)
    assert m["ambiguous_bars"] == 2
    assert m["gap_through_stops"] == 1                                  # only the gap, not every stop
    assert m["lock_affected_trades"] == 2                               # FULLDAY and PARTIAL both count
    assert m["median_mfe"] == pytest.approx(0.02) and m["median_mae"] == pytest.approx(-0.01)


def test_worst_cumulative_is_not_the_peak_to_trough_and_capital_comes_from_the_overlap():
    m = MX.metrics("A", five_trades(), {}, CAL, INDUSTRY)
    # net in exit order: +300, -1200, -2200, 0, +1300 -> cumulative 300, -900, -3100, -3100, -1800
    assert m["worst_cumulative_net_inr"] == pytest.approx(-3100.0)      # the lowest point of the curve
    assert m["worst_peak_to_trough_inr"] == pytest.approx(3400.0)       # 300 (the peak) down to -3100
    assert m["worst_cumulative_net_inr"] != m["worst_peak_to_trough_inr"]
    assert "max_drawdown_inr" not in m                                  # never called a drawdown (§5)
    # 4 trades are open together on 2022-01-05 and 2022-01-06, at 50,000 each
    assert m["peak_capital_required_inr"] == pytest.approx(200000.0)
    assert m["max_concurrent_trades"] == 4


def test_metrics_leaves_the_capital_figure_out_when_exposure_is_meaningless():
    m = MX.metrics("G", five_trades(), {}, CAL, INDUSTRY, exposure=False)
    assert m["peak_capital_required_inr"] is None and m["max_concurrent_trades"] is None
    assert m["worst_cumulative_net_inr"] == pytest.approx(-3100.0)      # the sequence numbers still stand
    assert m["net_per_trade"] == pytest.approx(-0.0072)


def test_metrics_portfolio_branch_reports_a_real_drawdown_on_the_equity_curve():
    equity = pd.DataFrame({"date": pd.date_range("2022-01-03", periods=4, freq="D"),
                           "equity": [500000.0, 510000.0, 495000.0, 505000.0], "positions": [1, 2, 3, 1]})
    m = MX.metrics("F", five_trades(), {}, CAL, INDUSTRY, portfolio=True, equity=equity, capital=500000.0)
    assert m["max_drawdown_inr"] == pytest.approx(15000.0)              # peak 510,000 down to 495,000
    assert m["max_drawdown_pct"] == pytest.approx(3.0)                  # 15,000 / 500,000
    assert m["final_equity_inr"] == pytest.approx(505000.0)
    assert m["return_on_capital_pct"] == pytest.approx(1.0)             # 505,000 / 500,000 - 1
    assert m["max_positions_open"] == 3
    assert "worst_cumulative_net_inr" not in m and "peak_capital_required_inr" not in m
    assert m["net_per_trade"] == pytest.approx(-0.0072)                 # the per-trade block is shared


def test_metrics_with_no_losers_and_no_stop_has_no_profit_factor():
    tr = pd.DataFrame([
        t_row("FFF", "2022-01-03", "2022-01-05", 0.01, 0.008, 150.0, 100.0, "TIME_EXIT", np.nan, False, "", 0.02, -0.01,
              slippage=np.nan),
        t_row("GGG", "2022-01-04", "2022-01-06", 0.02, 0.018, 250.0, 200.0, "TIME_EXIT", np.nan, False, "", 0.03, 0.00,
              slippage=np.nan),
    ])
    m = MX.metrics("H", tr, {}, CAL, INDUSTRY)
    assert m["profit_factor"] is None                                   # no negative net to divide by
    assert m["median_stop_distance_atr"] is None                        # run H has no stop
    assert m["slippage_per_trade"] is None                              # costs off / not attributed
    assert m["win_rate"] == pytest.approx(1.0) and m["longest_losing_streak"] == 0
    assert m["worst_peak_to_trough_inr"] == pytest.approx(0.0)          # a curve that only rises never falls


# ============================== §5a: the tax annex ==============================

def test_tax_annex_applies_only_to_a_positive_net_and_carries_the_cess():
    for nil in (0.0, -1.0, -125000.0):
        a = MX.tax_annex(nil)
        assert a["applies"] is False and "stcg_2022_15pct_plus_cess" not in a
    a = MX.tax_annex(10000.0)
    assert a["applies"] is True
    assert a["stcg_2022_15pct_plus_cess"] == pytest.approx(1560.0, abs=1e-9)     # 10,000 x 15% x 1.04
    assert a["stcg_current_20pct_plus_cess"] == pytest.approx(2080.0, abs=1e-9)  # 10,000 x 20% x 1.04
    assert a["stcg_2022_15pct_plus_cess"] != pytest.approx(1500.0)               # the cess is not dropped
    assert a["stcg_current_20pct_plus_cess"] != pytest.approx(2000.0)
    assert MX.tax_annex(1.0)["stcg_2022_15pct_plus_cess"] == pytest.approx(0.156, abs=1e-12)


# ============================== §5: the paired comparison ==============================

def ret_frame(rows) -> pd.DataFrame:
    return pd.DataFrame([{"symbol": s, "decision_date": pd.Timestamp(d), "net_ret": r} for s, d, r in rows])


A_RUN = ret_frame([("AAA", "2022-01-03", 0.00), ("AAA", "2022-01-04", 0.20), ("AAA", "2022-01-06", 0.50),
                   ("BBB", "2022-01-03", -0.02), ("BBB", "2022-01-04", 0.04), ("CCC", "2022-01-05", 0.05)])
X_RUN = ret_frame([("AAA", "2022-01-03", 0.01), ("AAA", "2022-01-04", 0.26),
                   ("BBB", "2022-01-03", 0.00), ("BBB", "2022-01-04", 0.04), ("DDD", "2022-01-05", 0.09)])
# common (symbol, decision_date): AAA/03 +0.01, AAA/04 +0.06, BBB/03 +0.02, BBB/04 0.00 -> mean 0.09 / 4


def test_paired_diff_uses_only_the_trades_both_runs_entered():
    r = MX.paired_diff(A_RUN, X_RUN)
    assert r["n_common"] == 4                     # AAA/06 and CCC/05 are A-only, DDD/05 is X-only
    assert r["mean_diff"] == pytest.approx(0.0225)
    assert r["share_better"] == pytest.approx(0.75)   # the zero difference is not "better"
    assert r["reps"] == MX.BOOT_REPS == 2000
    assert MX.paired_diff(A_RUN, X_RUN, reps=50)["reps"] == 50


def test_paired_diff_is_deterministic_and_its_interval_brackets_the_mean():
    r1, r2 = MX.paired_diff(A_RUN, X_RUN), MX.paired_diff(A_RUN, X_RUN)
    assert r1 == r2                                                     # same seed -> byte-identical result
    lo, hi = r1["ci95"]
    assert lo <= r1["mean_diff"] <= hi
    # two date clusters: resampling them with replacement can only give 0.015 (03,03), 0.0225 (03,04), 0.03 (04,04),
    # and each pair-of-identical-clusters has probability 1/4, so the 2.5th and 97.5th percentiles are the extremes
    assert lo == pytest.approx(0.015) and hi == pytest.approx(0.03)
    assert MX.paired_diff(A_RUN, X_RUN, seed=MX.SEED_RANDOM + 7)["mean_diff"] == pytest.approx(0.0225)


def test_paired_diff_reports_nothing_when_the_runs_share_no_trade():
    other = ret_frame([("ZZZ", "2022-02-01", 0.03)])
    assert MX.paired_diff(A_RUN, other) == {"n_common": 0}


# ============================== §4a: control G ==============================

def pool_rows() -> pd.DataFrame:
    rows = [("2022-01-03", s) for s in ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")]
    rows += [("2022-01-04", s) for s in ("T1", "T2", "T3")]
    return pd.DataFrame(rows, columns=["date", "symbol"]).assign(date=lambda d: pd.to_datetime(d["date"]))


D1, D2 = pd.Timestamp("2022-01-03"), pd.Timestamp("2022-01-04")


def test_random_picks_draws_k_a_session_without_replacement():
    draws = MX.random_picks(pool_rows(), k=5, seeds=50)
    assert len(draws) == 50
    for d in draws:
        assert set(d) == {D1, D2}
        assert len(d[D1]) == 5 and len(set(d[D1])) == 5          # exactly k, no symbol drawn twice
        assert set(d[D1]) <= {"S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"}
        assert len(d[D2]) == 3 and set(d[D2]) == {"T1", "T2", "T3"}   # a pool smaller than k is taken whole
    assert len({tuple(d[D1]) for d in draws}) > 1                # the seeds actually differ from one another


def test_random_picks_is_seeded_per_draw_and_reproducible():
    draws = MX.random_picks(pool_rows(), k=5, seeds=50)
    assert MX.random_picks(pool_rows(), k=5, seeds=50) == draws
    shifted = MX.random_picks(pool_rows(), k=5, seeds=50, base=MX.SEED_RANDOM + 1)
    assert shifted != draws
    assert shifted[0] == draws[1]                                # seed k is default_rng(base + k), §4a
    assert MX.random_picks(pool_rows(), k=5, seeds=2, base=99)[0] != draws[0]


def test_random_picks_does_not_depend_on_the_order_of_the_pool_rows():
    pool = pool_rows()
    shuffled = pool.iloc[::-1].reset_index(drop=True)
    assert list(shuffled.symbol) != list(pool.symbol)             # the rows really are in a different order
    assert MX.random_picks(shuffled, k=5, seeds=20) == MX.random_picks(pool, k=5, seeds=20)


POOL_TRADES = pd.DataFrame([
    {"decision_date": pd.Timestamp("2022-01-03"), "symbol": "AAA", "net_ret": 0.10},
    {"decision_date": pd.Timestamp("2022-01-03"), "symbol": "BBB", "net_ret": -0.02},
    {"decision_date": pd.Timestamp("2022-01-03"), "symbol": "CCC", "net_ret": 0.06},
    {"decision_date": pd.Timestamp("2022-01-04"), "symbol": "AAA", "net_ret": 0.00},
    {"decision_date": pd.Timestamp("2022-01-04"), "symbol": "DDD", "net_ret": 0.20},
])
DRAWS = [
    {D1: ["AAA", "BBB"]},                       # 0.10, -0.02          -> 0.04 over 2
    {D1: ["AAA", "ZZZ"]},                       # ZZZ never traded     -> 0.10 over 1, NOT 0.05 over 2
    {D1: ["BBB", "CCC"], D2: ["DDD"]},          # -0.02, 0.06, 0.20    -> 0.08 over 3
    {D2: ["AAA", "DDD"]},                       # 0.00, 0.20           -> 0.10 over 2
]


def test_random_control_means_come_from_the_pool_run_and_untraded_draws_are_dropped():
    r = MX.random_control(DRAWS, POOL_TRADES, a_net_per_trade=0.10)
    # the metadata is derived from the draws it was handed (these fixtures draw 2 a session), not from the constants
    assert r["seeds"] == 4 and r["seed_base"] == 20260920 and r["picks_per_session"] == 2
    assert MX.random_control(DRAWS, POOL_TRADES, a_net_per_trade=0.10, seed_base=7)["seed_base"] == 7
    assert r["mean_trades_per_seed"] == pytest.approx(2.0)       # 2 + 1 + 3 + 2, so the missing pick is not a zero
    assert r["mean_of_means"] == pytest.approx(0.08)             # (0.04 + 0.10 + 0.08 + 0.10) / 4
    assert r["min"] == pytest.approx(0.04) and r["max"] == pytest.approx(0.10)
    assert r["p50"] == pytest.approx(0.09)                       # linear interpolation over 0.04, 0.08, 0.10, 0.10
    assert r["p05"] == pytest.approx(0.046)
    assert r["p95"] == pytest.approx(0.10)


def test_random_control_percentile_is_a_s_place_below_the_seed_distribution():
    # two of the four seed means (0.04, 0.08) are below 0.10; the two equal to it are not "below"
    assert MX.random_control(DRAWS, POOL_TRADES, 0.10)["a_percentile"] == pytest.approx(50.0)
    assert MX.random_control(DRAWS, POOL_TRADES, 0.04)["a_percentile"] == pytest.approx(0.0)
    assert MX.random_control(DRAWS, POOL_TRADES, 0.11)["a_percentile"] == pytest.approx(100.0)
    assert MX.random_control(DRAWS, POOL_TRADES, 0.09)["a_percentile"] == pytest.approx(50.0)


def test_random_frame_pools_every_drawn_trade_and_drops_the_untraded_ones():
    f = MX.random_frame(DRAWS, POOL_TRADES)
    assert len(f) == 8                                           # 2 + 1 + 3 + 2 matched keys
    assert set(f.config) == {"G"} and sorted(f.seed.unique()) == [0, 1, 2, 3]
    assert "ZZZ" not in set(f.symbol)
    aaa_d1 = f[(f.symbol == "AAA") & (f.decision_date == D1)]
    assert len(aaa_d1) == 2 and sorted(aaa_d1.seed) == [0, 1]    # drawn by two seeds, counted twice
    assert f.net_ret.sum() == pytest.approx(0.10 - 0.02 + 0.10 - 0.02 + 0.06 + 0.20 + 0.00 + 0.20)


# ============================== S5: rank bands ==============================

def band_fixture():
    pool_trades = pd.DataFrame([
        {"row": 0, "net_ret": 0.02, "gross_ret": 0.03, "net_inr": 100.0, "exit_reason": "TARGET_HIT"},
        {"row": 1, "net_ret": 0.04, "gross_ret": 0.05, "net_inr": 200.0, "exit_reason": "TARGET_HIT"},
        {"row": 2, "net_ret": -0.01, "gross_ret": 0.00, "net_inr": -50.0, "exit_reason": "STOP_HIT"},
        {"row": 3, "net_ret": -0.03, "gross_ret": -0.02, "net_inr": -150.0, "exit_reason": "GAP_THROUGH_STOP"},
        {"row": 4, "net_ret": 0.05, "gross_ret": 0.06, "net_inr": 250.0, "exit_reason": "TARGET_HIT"},
        {"row": 5, "net_ret": -0.10, "gross_ret": -0.09, "net_inr": -500.0, "exit_reason": "STOP_HIT"},
    ])
    ranked = pd.DataFrame({"rank": [1.0, 5.0, 6.0, 10.0, 11.0, 21.0]}, index=[0, 1, 2, 3, 4, 5])
    return pool_trades, ranked


def test_rank_bands_are_1_5_6_10_11_20_and_21_plus():
    b = MX.rank_bands(*band_fixture())
    assert set(b) == {"1-5", "6-10", "11-20", "21+"}
    assert b["1-5"]["trades"] == 2                              # ranks 1 and 5 — 5 is the top band, not the second
    assert b["6-10"]["trades"] == 2                             # ranks 6 and 10
    assert b["11-20"]["trades"] == 1                            # rank 11
    assert b["21+"]["trades"] == 1                              # rank 21
    assert b["1-5"]["net_per_trade"] == pytest.approx(0.03) and b["1-5"]["gross_per_trade"] == pytest.approx(0.04)
    assert b["6-10"]["net_per_trade"] == pytest.approx(-0.02) and b["6-10"]["gross_per_trade"] == pytest.approx(-0.01)
    assert b["11-20"]["net_per_trade"] == pytest.approx(0.05)
    assert b["21+"]["net_per_trade"] == pytest.approx(-0.10)
    assert b["1-5"]["win_rate"] == pytest.approx(1.0) and b["6-10"]["win_rate"] == pytest.approx(0.0)
    assert b["1-5"]["stop_hit_rate"] == pytest.approx(0.0)
    assert b["6-10"]["stop_hit_rate"] == pytest.approx(1.0)      # STOP_HIT and GAP_THROUGH_STOP both count
    assert b["21+"]["stop_hit_rate"] == pytest.approx(1.0)


def test_rank_bands_join_the_rank_onto_the_dataset_row():
    pool_trades, ranked = band_fixture()
    moved = ranked.loc[[5, 4, 3, 2, 1, 0]]                       # the same ranks, rows in a different order
    assert MX.rank_bands(pool_trades, moved) == MX.rank_bands(pool_trades, ranked)
    swapped = pd.DataFrame({"rank": [21.0, 21.0, 21.0, 21.0, 21.0, 1.0]}, index=[0, 1, 2, 3, 4, 5])
    assert MX.rank_bands(pool_trades, swapped)["21+"]["trades"] == 5   # the rank, not the row number, bands a trade


# ============================== RC-1 causes per configuration ==============================
#
# matrix.rc1_column is landing after the frozen commit this worktree sits on, so the contract tests below are
# skipped here and will run the moment it appears. The fixtures they depend on are pinned by a test that does run.

rc1_needed = pytest.mark.skipif(not hasattr(MX, "rc1_column"),
                                reason="matrix.rc1_column is not in this revision of matrix.py")


def rc1_trade(symbol, bars, **kw):
    return TS.simulate(TS.CONFIG_A, window(symbol, bars, **kw), CM)


WINNER_BARS = [bar(100, 104, 99, 103), bar(103, 106, 102, 105)] + [QUIET] * 3   # target on s2
LOSER_BARS = [bar(100, 101, 97, 98), QUIET, QUIET, QUIET, bar(100, 101, 99, 99)]  # stop on s1, no recovery
PARTIAL_LOCK_BARS = [QUIET, bar(80, 90, 80, 88, pc=100), bar(99, 100, 98.5, 99.5, pc=88), QUIET, QUIET]
DEC_DAY, S1, S2 = (pd.Timestamp("2022-10-03"), pd.Timestamp("2022-10-04"), pd.Timestamp("2022-10-05"))


def by_symbol(c: pd.DataFrame) -> pd.DataFrame:
    return c.set_index("symbol")


def test_the_rc1_fixtures_are_what_the_cause_expectations_assume():
    """Runs unconditionally: everything the rc1_column expectations below rest on is a fact about these trades."""
    w = rc1_trade("AAA", WINNER_BARS)
    assert w["status"] == "CLOSED" and w["exit_reason"] == "TARGET_HIT"
    assert float(w["net_inr"]) == pytest.approx(2266.24) and float(w["net_inr"]) > 0     # a winner
    assert w["flags"] == "" and w["bars_used"] == [dt.date(2022, 10, 4), dt.date(2022, 10, 5)]
    l = rc1_trade("BBB", LOSER_BARS)
    assert l["exit_reason"] == "STOP_HIT" and float(l["net_inr"]) == pytest.approx(-1223.13)
    assert l["stop_distance_atr"] == pytest.approx(2 / 3)      # (100 - 98) / a 3.00 ATR -> under 1 R, STOP_FAILURE
    assert l["path_max_high_pct"] == pytest.approx(0.01) and l["close_last_pct"] == pytest.approx(-0.01)
    assert l["flags"] == "" and l["bars_used"] == [dt.date(2022, 10, 4)]
    p = rc1_trade("CCC", PARTIAL_LOCK_BARS)
    assert p["exit_reason"] == "TIME_EXIT" and float(p["net_inr"]) == pytest.approx(-226.16)
    assert "LOCKED_LOWER_PARTIAL_S2" in p["flags"]             # the lock heuristic's known false positive
    assert rc1_trade("DDD", [None, QUIET])["status"] == "NO_ENTRY"


@rc1_needed
def test_rc1_column_leaves_a_winner_alone_even_when_its_data_is_suspect():
    w = rc1_trade("AAA", WINNER_BARS)
    clean = by_symbol(MX.rc1_column([w], {}, {}))
    assert clean.loc["AAA", "rc1_primary"] == "WIN" and clean.loc["AAA", "rc1_all"] == ""
    assert clean.loc["AAA", "rc1_primary_excl_unreviewed_flags"] == "WIN"
    assert clean.loc["AAA", "dq_status"] == "PASS" and clean.loc["AAA", "dq_flags"] == ""
    # RC-1 is a loss post-mortem: a profitable trade is never given a cause, however bad its bars look
    flagged = by_symbol(MX.rc1_column([w], {}, {("AAA", S2): ["DUPLICATE_BAR"]}))
    assert flagged.loc["AAA", "rc1_primary"] == "WIN" and flagged.loc["AAA", "rc1_all"] == ""
    assert flagged.loc["AAA", "dq_status"] == "FLAGGED" and flagged.loc["AAA", "dq_flags"] == "DUPLICATE_BAR"
    # a bar that FAILED integrity and a (different) bar that is merely flagged, on the same trade
    failed = by_symbol(MX.rc1_column([w], {("AAA", S2): True}, {("AAA", S1): ["DUPLICATE_BAR"]}))
    assert failed.loc["AAA", "rc1_primary"] == "WIN"
    assert failed.loc["AAA", "dq_status"] == "FAIL"            # an integrity failure outranks an unreviewed flag
    assert failed.loc["AAA", "dq_flags"] == "DUPLICATE_BAR"    # and the flag is still reported alongside it


@rc1_needed
def test_rc1_column_primary_cause_is_the_first_in_the_frozen_order():
    c = by_symbol(MX.rc1_column([rc1_trade("BBB", LOSER_BARS)], {}, {}))
    # RC1_ORDER puts STOP_FAILURE before DIRECTION_FAILURE, so the primary is the stop, not the direction
    assert c.loc["BBB", "rc1_all"] == "STOP_FAILURE;DIRECTION_FAILURE"
    assert c.loc["BBB", "rc1_primary"] == "STOP_FAILURE"
    assert c.loc["BBB", "rc1_primary"] != "DIRECTION_FAILURE"  # not causes[-1]
    assert c.loc["BBB", "rc1_primary_excl_unreviewed_flags"] == "STOP_FAILURE"
    assert c.loc["BBB", "dq_status"] == "PASS"


@rc1_needed
def test_rc1_column_drops_a_data_failure_that_only_an_unreviewed_flag_raised():
    l = rc1_trade("BBB", LOSER_BARS)                            # its only bar is s1 (2022-10-04)
    flagged = by_symbol(MX.rc1_column([l], {}, {("BBB", S1): ["DUPLICATE_BAR"]}))
    assert flagged.loc["BBB", "rc1_primary"] == "DATA_FAILURE"
    assert flagged.loc["BBB", "rc1_all"] == "DATA_FAILURE;STOP_FAILURE;DIRECTION_FAILURE"
    assert flagged.loc["BBB", "rc1_primary_excl_unreviewed_flags"] == "STOP_FAILURE"   # the flag is not a failure
    assert flagged.loc["BBB", "dq_status"] == "FLAGGED"
    failed = by_symbol(MX.rc1_column([l], {("BBB", S1): True}, {}))
    assert failed.loc["BBB", "rc1_primary"] == "DATA_FAILURE"
    assert failed.loc["BBB", "rc1_primary_excl_unreviewed_flags"] == "DATA_FAILURE"    # a real failure is kept
    assert failed.loc["BBB", "dq_status"] == "FAIL"
    # the decision day counts too, not only the sessions the position was held (audit_rows uses the same window)
    on_d = by_symbol(MX.rc1_column([l], {("BBB", DEC_DAY): True}, {}))
    assert on_d.loc["BBB", "rc1_primary"] == "DATA_FAILURE"
    elsewhere = by_symbol(MX.rc1_column([l], {("BBB", pd.Timestamp("2022-10-08")): True},
                                        {("ZZZ", S1): ["DUPLICATE_BAR"]}))
    assert elsewhere.loc["BBB", "rc1_primary"] == "STOP_FAILURE" and elsewhere.loc["BBB", "dq_status"] == "PASS"


@rc1_needed
def test_rc1_column_treats_a_partial_lock_as_an_unexplained_simulation():
    p = rc1_trade("CCC", PARTIAL_LOCK_BARS)
    c = by_symbol(MX.rc1_column([p], {}, {}))
    # nothing else in RC-1 matches this trade; without the LOCKED_LOWER_PARTIAL -> unexplained rule it would be
    # UNCLASSIFIED, and SIMULATION_FAILURE sits second in the frozen order, right after DATA_FAILURE
    assert c.loc["CCC", "rc1_primary"] == "SIMULATION_FAILURE"
    assert c.loc["CCC", "rc1_all"] == "SIMULATION_FAILURE"
    assert c.loc["CCC", "rc1_primary_excl_unreviewed_flags"] == "SIMULATION_FAILURE"
    # the plain loser carries no such flag and must not be called a simulation failure
    plain = by_symbol(MX.rc1_column([rc1_trade("BBB", LOSER_BARS)], {}, {}))
    assert "SIMULATION_FAILURE" not in plain.loc["BBB", "rc1_all"]


@rc1_needed
def test_rc1_column_covers_every_closed_trade_and_nothing_else():
    trades = [rc1_trade("AAA", WINNER_BARS), rc1_trade("DDD", [None, QUIET]), rc1_trade("BBB", LOSER_BARS)]
    c = MX.rc1_column(trades, {}, {})
    assert list(c.symbol) == ["AAA", "BBB"]                    # the rejected candidate has no trade to explain
    assert list(c.decision_date) == [DEC_DAY, DEC_DAY]
    assert MX.rc1_column([rc1_trade("DDD", [None, QUIET])], {}, {}).empty


def test_each_run_states_which_basis_its_gross_and_cost_drag_are_on():
    """A fixed-notional run measures gross BEFORE slippage; the engine's fills already carry it. The two cost drags
    are therefore not on a common basis, and each run says so rather than leaving the reader to assume."""
    equity = pd.DataFrame({"date": CAL[:5], "equity": [500000.0, 502000.0, 494000.0, 496000.0, 499000.0],
                           "positions": [1, 2, 2, 1, 0]})
    iso = MX.metrics("A", five_trades(), {}, CAL, INDUSTRY)
    pf = MX.metrics("F", five_trades(), {}, CAL, INDUSTRY, portfolio=True, equity=equity, capital=500000.0)
    assert "before slippage" in iso["cost_basis"] and "slippage plus statutory charges" in iso["cost_basis"]
    assert "after slippage" in pf["cost_basis"] and "statutory charges only" in pf["cost_basis"]


# ============================== §9: the extreme-trade audit ==============================

def extreme_fixture():
    rows = []
    for i in range(25):
        net = (i - 12) * 100.0 + 50.0                           # -1150 .. +1250, all distinct, none zero
        symbol = {0: "GOLDBEES", 24: "NIFTYETF"}.get(i, f"SYM{i:02d}")
        rows.append({"symbol": symbol, "decision_date": pd.Timestamp("2022-01-03") + pd.Timedelta(days=i),
                     "entry_date": pd.Timestamp("2022-01-04") + pd.Timedelta(days=i),
                     "exit_date": pd.Timestamp("2022-01-07") + pd.Timedelta(days=i), "exit_reason": "TIME_EXIT",
                     "qty": 500, "buy_value": 50000.0, "gross_inr": net + 120.0, "charges_inr": 120.0,
                     "net_inr": net, "net_ret": net / 50000.0, "flags": ""})
    names = {"GOLDBEES": "Nippon India ETF Gold BeES", "SYM12": "Plain Industries", "NIFTYETF": "Nifty Index Fund"}
    return pd.DataFrame(rows), names


def test_extremes_picks_the_largest_gains_and_the_largest_losses():
    tr, names = extreme_fixture()
    x = MX.extremes(tr, names)
    assert [r["net_inr"] for r in x["largest_gains"]] == [1250.0, 1150.0, 1050.0, 950.0, 850.0, 750.0, 650.0, 550.0,
                                                          450.0, 350.0]
    assert [r["net_inr"] for r in x["largest_losses"]] == [-1150.0, -1050.0, -950.0, -850.0, -750.0, -650.0, -550.0,
                                                           -450.0, -350.0, -250.0]
    assert x["largest_gains"][0]["symbol"] == "NIFTYETF" and x["largest_losses"][0]["symbol"] == "GOLDBEES"
    assert x["largest_gains"][0]["decision_date"] == "2022-01-27"      # formatted, not a Timestamp
    assert x["largest_gains"][0]["entry_date"] == "2022-01-28" and x["largest_gains"][0]["exit_date"] == "2022-01-31"
    # |top 10| = 8,000 and |bottom 10| = 7,000 out of 15,650 of absolute net over all 25
    assert x["share_of_absolute_pnl_in_extremes"] == pytest.approx(15000.0 / 15650.0)
    small = MX.extremes(tr, names, n=2)
    assert len(small["largest_gains"]) == 2 and len(small["largest_losses"]) == 2
    assert small["share_of_absolute_pnl_in_extremes"] == pytest.approx((1250 + 1150 + 1150 + 1050) / 15650.0)


def test_extremes_flags_an_etf_by_symbol_or_by_company_name():
    tr, names = extreme_fixture()
    x = MX.extremes(tr, names)
    by_symbol = x["largest_gains"][0]                                  # NIFTYETF, whose company name has no "ETF"
    by_name = x["largest_losses"][0]                                   # GOLDBEES, "Nippon India ETF Gold BeES"
    assert by_symbol["company"] == "Nifty Index Fund" and bool(by_symbol["etf_like"]) is True
    assert by_name["company"] == "Nippon India ETF Gold BeES" and bool(by_name["etf_like"]) is True
    plain = [r for r in x["largest_gains"] + x["largest_losses"] if r["symbol"] == "SYM12"]
    assert all(bool(r["etf_like"]) is False for r in plain)
    unnamed = [r for r in x["largest_gains"] if r["symbol"] == "SYM20"]
    assert unnamed and all(bool(r["etf_like"]) is False for r in unnamed)   # a missing company name is not a crash
    # the count matches the per-row flag: symbol OR company name. A fund that is an ETF only by name (every ...BEES)
    # must not be invisible here - an ETF artefact is exactly what the 2026-09-19 extreme-trade audit was added for
    assert x["etf_like_trades"] == 2


# ============================== §4b: signals into the risk engine ==============================

def test_signals_carry_the_decision_close_a_2pct_stop_and_the_atr_in_rupees():
    picks = pd.DataFrame({"date": [pd.Timestamp("2022-10-03")] * 2, "symbol": ["AAA", "BBB"], "score": [0.9, 0.8]},
                         index=[4, 9])
    ds = pd.DataFrame({"close": [100.0, 250.0], "atr_pct": [3.0, 1.2]}, index=[4, 9])
    s = MX.signals(picks, ds)
    assert len(s) == 2                                                  # one row per pick
    assert list(s.signal_id) == ["20221003-AAA", "20221003-BBB"]
    assert list(s.order_type) == ["MOO", "MOO"] and list(s.arm) == ["M8", "M8"]
    assert list(s.valid_sessions) == [1, 1] and s.trigger.isna().all()
    assert list(s.model_version) == ["M8|tbs_5_2"] * 2
    assert s.reference_price.tolist() == [100.0, 250.0]                 # the decision close
    assert s.stop.tolist() == [pytest.approx(98.0), pytest.approx(245.0)]    # close x (1 - 2/100)
    assert s.atr.tolist() == [pytest.approx(3.0), pytest.approx(3.0)]        # atr_pct / 100 x close, in rupees
    assert s["rank"].tolist() == [0.9, 0.8]
    assert s.stop_pct.tolist() == [2.0, 2.0] and s.target_pct.tolist() == [5.0, 5.0]
    wide = MX.signals(picks, ds, stop_pct=4.0, target_pct=6.0)
    assert wide.stop.tolist() == [pytest.approx(96.0), pytest.approx(240.0)]
    assert wide.stop_pct.tolist() == [4.0, 4.0] and wide.target_pct.tolist() == [6.0, 6.0]
    assert wide.reference_price.tolist() == [100.0, 250.0]              # the reference price does not move


# ============================== §4b: the engine's trades and rejections ==============================

class FakeResult:
    def __init__(self, trades=None, decisions=None):
        self.trades = pd.DataFrame(trades if trades is not None else [])
        self.decisions = decisions or []


def engine_trade(symbol, reason, qty=100, entry="100", exit_="98", gross="-200", costs="50", net="-250",
                 stop="98", realised=True):
    return {"symbol": symbol, "signal_id": f"20221003-{symbol}", "entry_date": dt.date(2022, 10, 4),
            "exit_date": dt.date(2022, 10, 6), "exit_reason": reason, "qty": qty, "entry_price": D(entry),
            "exit_price": D(exit_), "gross_pnl": D(gross), "costs": D(costs), "net_pnl": D(net),
            "initial_stop": D(stop), "r_multiple": -1.25, "realised": realised}


def test_engine_frame_maps_every_engine_exit_reason_onto_the_matrix_vocabulary():
    pairs = [("STOP", "STOP_HIT"), ("STOP_SAME_DAY", "STOP_HIT"), ("GAP_THROUGH", "GAP_THROUGH_STOP"),
             ("TARGET", "TARGET_HIT"), ("TARGET_SAME_DAY", "TARGET_HIT"), ("GAP_OVER_TARGET", "TARGET_HIT"),
             ("TIME", "TIME_EXIT"), ("OPEN_AT_END", "OPEN_AT_END")]
    res = FakeResult([engine_trade(f"S{i}", raw, realised=(raw != "OPEN_AT_END")) for i, (raw, _) in enumerate(pairs)])
    f = MX.engine_frame(res, "F", {f"S{i}": "Auto" for i in range(len(pairs))})
    assert list(f.exit_reason) == [mapped for _, mapped in pairs]
    assert list(f.exit_detail) == [raw for raw, _ in pairs]             # the engine's own word is kept alongside
    assert set(f.config) == {"F"} and set(f.sector) == {"Auto"}
    assert list(f.realised) == [True] * 7 + [False]


def test_engine_frame_values_are_measured_from_the_buy_value():
    res = FakeResult([engine_trade("AAA", "STOP")])
    f = MX.engine_frame(res, "F", {"AAA": "Banks"})
    assert f.buy_value.iloc[0] == pytest.approx(10000.0)                # 100 shares x 100.00 entry
    assert f.sell_value.iloc[0] == pytest.approx(9800.0)
    assert f.net_ret.iloc[0] == pytest.approx(-0.025)                   # -250 / 10,000 (the BUY value)
    assert f.net_ret.iloc[0] != pytest.approx(-250.0 / 9800.0)
    assert f.gross_ret.iloc[0] == pytest.approx(-0.02)                  # 98 / 100 - 1
    assert f.initial_risk_inr.iloc[0] == pytest.approx(200.0)           # 100 x (100.00 entry - 98.00 stop)
    assert f.gross_inr.iloc[0] == pytest.approx(-200.0) and f.charges_inr.iloc[0] == pytest.approx(50.0)
    assert f.decision_date.iloc[0] == pd.Timestamp("2022-10-03")        # from the signal_id, not the entry date
    assert f.entry_date.iloc[0] == pd.Timestamp("2022-10-04")
    assert np.isnan(f.slippage_inr.iloc[0])                             # the engine hides slippage inside the fill
    assert MX.engine_frame(FakeResult([]), "F", {}).empty


def test_engine_rejections_counts_the_first_reason_of_each_refused_candidate():
    res = FakeResult(decisions=[
        {"decision_status": "REJECTED", "rejection_reasons": ["MAX_POSITIONS"]},
        {"decision_status": "REJECTED", "rejection_reasons": ["MAX_POSITIONS"]},
        {"decision_status": "REJECTED", "rejection_reasons": ["STOCK_CAP", "also ran"]},
        {"decision_status": "REJECTED", "rejection_reasons": []},
        {"decision_status": "APPROVED", "rejection_reasons": ["MAX_POSITIONS"]},
        {"decision_status": "REDUCED", "rejection_reasons": ["SECTOR_CAP"]},
    ])
    assert MX.engine_rejections(res) == {"MAX_POSITIONS": 2, "STOCK_CAP": 1, "UNKNOWN": 1}
    assert MX.engine_rejections(FakeResult()) == {}


# ============================== end to end: runs D and F through the risk engine ==============================

SESSIONS = ["2022-10-03", "2022-10-04", "2022-10-05", "2022-10-06", "2022-10-07",
            "2022-10-10", "2022-10-11", "2022-10-12", "2022-10-13", "2022-10-14", "2022-10-17", "2022-10-18"]
SECTORS = {"AAA": "Auto", "BBB": "Auto", "CCC": "Auto"}          # one sector, so F's 40% sector cap has to bite


def e2e_bars() -> pd.DataFrame:
    """Three symbols, 12 sessions. Decision day closes at 100; the next session opens at 108 (an 8% gap, so a stop
    set on the decision close would be nowhere near the one set on the fill)."""
    rows = []
    for sym in ("AAA", "BBB", "CCC"):
        for i, d in enumerate(SESSIONS):
            if i == 0:
                o, h, l, c = 99, 101, 98, 100
            elif i == 2 and sym == "AAA":
                o, h, l, c = 110, 114, 109, 113                  # reaches the 113.40 target
            elif i == 2 and sym == "BBB":
                o, h, l, c = 107, 108, 105, 106                  # reaches the 105.84 stop
            else:
                o, h, l, c = 108, 110, 107, 109                  # quiet: inside both levels
            rows.append({"symbol": sym, "date": d, "open": float(o), "high": float(h), "low": float(l),
                         "close": float(c), "volume": 5_000_000, "value20": 5e8})
    return pd.DataFrame(rows)


def e2e_signals() -> pd.DataFrame:
    picks = pd.DataFrame({"date": [pd.Timestamp("2022-10-03")] * 3, "symbol": ["AAA", "BBB", "CCC"],
                          "score": [0.9, 0.8, 0.7]}, index=[0, 1, 2])
    ds = pd.DataFrame({"close": [100.0, 100.0, 100.0], "atr_pct": [3.0, 3.0, 3.0]}, index=[0, 1, 2])
    return MX.signals(picks, ds)


def test_end_to_end_f_and_d_levels_come_from_the_fill_and_the_caps_change_who_gets_in():
    sig = e2e_signals()
    assert sig.stop.tolist() == [pytest.approx(98.0)] * 3        # what the SIGNAL carried: 2% off the decision close
    prepared = EN.prepare_bars(e2e_bars())

    res_f, tr_f, meta_f = MX.run_portfolio("F", "SIM-MATRIX-F", sig, prepared, CM, SECTORS, SECTORS)
    res_d, tr_d, meta_d = MX.run_portfolio("D", "SIM-MATRIX-D", sig, prepared, CM, SECTORS, SECTORS)

    assert meta_f["config_id"] == "SIM-MATRIX-F" and meta_f["max_open_positions"] == 8
    assert meta_d["config_id"] == "SIM-MATRIX-D" and meta_d["max_open_positions"] == 50
    assert meta_f["risk_per_trade_pct"] == meta_d["risk_per_trade_pct"] == "0.5"
    assert meta_f["ambiguous_bars"] == 0 and meta_f["exit_blocked_events"] == 0
    assert meta_f["unrealised_at_end"] == 0 and meta_d["unrealised_at_end"] == 0

    # ---- the levels are re-derived from the FILL's raw base (the 108.00 open), never from the 100.00 close ----
    f_trades = res_f.trades.set_index("symbol")
    aaa = f_trades.loc["AAA"]
    assert aaa.entry_price == D("108.11")                        # 108.00 x 1.001 (the 0.10% slippage bucket)
    assert aaa.initial_stop == D("105.84") == D("108") * D("0.98")
    assert aaa.target == D("113.4") == D("108") * D("1.05")
    assert aaa.initial_stop != D("98")                           # the signal's own stop is not the position's stop
    assert aaa.initial_stop != D("108.11") * D("0.98")           # measured from the raw base, not the slipped fill
    assert aaa.exit_reason == "TARGET" and aaa.exit_price == D("113.29")     # 113.40 x 0.999
    assert aaa.exit_date == dt.date(2022, 10, 5) and aaa.qty == 1000

    bbb = f_trades.loc["BBB"]
    assert bbb.exit_reason == "STOP" and bbb.exit_price == D("105.73")       # 105.84 x 0.999
    assert bbb.qty == 995                                        # F's 40% sector cap already shaved the second entry

    # ---- F refuses the third candidate; D, with no allocation caps, takes it ----
    assert sorted(res_f.trades.symbol) == ["AAA", "BBB"]
    assert MX.engine_rejections(res_f) == {"SECTOR_CAP": 1}
    assert sorted(res_d.trades.symbol) == ["AAA", "BBB", "CCC"]
    assert MX.engine_rejections(res_d) == {}
    assert res_d.trades.set_index("symbol").qty.tolist() == [1000, 1000, 1000]   # risk sizing binds, no cap does
    ccc = res_d.trades.set_index("symbol").loc["CCC"]
    assert ccc.exit_reason == "TIME" and ccc.exit_date == dt.date(2022, 10, 10)  # the 5th session after entry

    # ---- and the frames the matrix reports come out with the mapped vocabulary ----
    assert dict(zip(tr_f.symbol, tr_f.exit_reason)) == {"AAA": "TARGET_HIT", "BBB": "STOP_HIT"}
    assert dict(zip(tr_d.symbol, tr_d.exit_reason)) == {"AAA": "TARGET_HIT", "BBB": "STOP_HIT", "CCC": "TIME_EXIT"}
    tr_f = tr_f.set_index("symbol")
    assert tr_f.loc["AAA", "buy_value"] == pytest.approx(108110.0)
    assert tr_f.loc["AAA", "initial_risk_inr"] == pytest.approx(2270.0)       # 1000 x (108.11 - 105.84)
    assert tr_f.loc["AAA", "net_ret"] == pytest.approx(float(res_f.trades.set_index("symbol").loc["AAA"].net_pnl)
                                                       / 108110.0)
    assert tr_f.loc["AAA", "decision_date"] == pd.Timestamp("2022-10-03")


def test_end_to_end_the_position_limit_override_is_applied_to_the_loaded_config():
    sig = e2e_signals()
    prepared = EN.prepare_bars(e2e_bars())
    res, tr, meta = MX.run_portfolio("F", "SIM-MATRIX-F", sig, prepared, CM, SECTORS, SECTORS,
                                     risk_pct=D("1.0"), positions=1)
    assert meta["risk_per_trade_pct"] == "1.0" and meta["max_open_positions"] == 1
    assert sorted(res.trades.symbol) == ["AAA"]                  # one position allowed; the other two are refused
    assert MX.engine_rejections(res) == {"MAX_POSITIONS": 2}
    assert res.trades.set_index("symbol").loc["AAA"].qty == 1000  # 1% risk would buy 2,000; the 20% stock cap binds
    assert len(tr) == 1
