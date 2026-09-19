"""Mode B trade-isolated simulator — synthetic trades with every price and charge worked by hand (PRD §6, §10, §11)."""
from __future__ import annotations

import datetime as dt
import os
import sys
from decimal import Decimal as D

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tradesim as TS  # noqa: E402

CM = TS.CC.load_cost_model("zerodha-equity-v1")
DAY0 = dt.date(2022, 10, 3)


def b(o, h, l, c, v=100000, pc=None):
    return TS.EX.Bar(D(str(o)), D(str(h)), D(str(l)), D(str(c)), v, D(str(pc)) if pc is not None else D(str(o)))


def win(bars, d_close=100, d_high=101, d_low=99, value20=3e8, atr_pct=3.0, **kw):
    dates = [DAY0 + dt.timedelta(days=i + 1) for i in range(len(bars))]
    return TS.Window("X", DAY0, D(str(d_close)), D(str(d_high)), D(str(d_low)), value20, atr_pct, dates=dates, bars=bars,
                     **kw)


QUIET = b(100, 101, 99, 100)


def test_config_a_target_trade_prices_quantity_and_charges_by_hand():
    t = TS.simulate(TS.CONFIG_A, win([b(100, 104, 99, 103), b(103, 106, 102, 105), QUIET, QUIET, QUIET]), CM)
    assert t["status"] == "CLOSED" and t["exit_reason"] == "TARGET_HIT" and t["exit_session"] == 2
    assert t["intended_entry"] == D("100") and t["actual_entry"] == D("100.10")          # 0.10% bucket (value20 ₹30 cr)
    assert t["fill_quantity"] == 499                                                      # floor(50,000 / 100.10)
    assert t["initial_stop"] == D("98.00") and t["initial_target"] == D("105.00")
    assert t["exit_level"] == D("105.00") and t["exit_price"] == D("104.90")              # 105 x 0.999 = 104.895
    assert t["gross_inr"] == D("2495.00")                                                 # (105 - 100) x 499
    assert t["slippage_inr"] == D("99.80")                                                # 0.10 x 499 twice
    # buy 49,949.90: STT 49.95, txn 1.53, SEBI 0.05, stamp 7.49, GST 0.29 = 59.31
    # sell 52,345.10: STT 52.35, txn 1.61, SEBI 0.05, GST 0.30, DP 15.34 = 69.65
    assert t["charges_inr"] == D("128.96")
    assert t["net_inr"] == D("2266.24")                                                   # 52,345.10 - 49,949.90 - 128.96
    assert t["net_ret"] == pytest.approx(2266.24 / 49949.90, abs=1e-12)
    assert t["gross_inr"] - t["slippage_inr"] - t["charges_inr"] == t["net_inr"]
    assert t["costs_retroactive"] is True
    assert t["r_multiple"] == pytest.approx(2266.24 / ((100.10 - 98.00) * 499), abs=1e-9)


def test_a_bar_touching_both_levels_stops_first_and_is_flagged():
    t = TS.simulate(TS.CONFIG_A, win([b(100, 106, 97, 101), QUIET, QUIET, QUIET, QUIET]), CM)
    assert t["exit_reason"] == "STOP_HIT" and t["exit_level"] == D("98.00") and t["intrabar_ambiguous"] is True
    assert t["exit_session"] == 1


def test_gap_through_stop_exits_at_the_open():
    t = TS.simulate(TS.CONFIG_A, win([QUIET, b(96, 97, 95, 96), QUIET, QUIET, QUIET]), CM)
    assert t["exit_reason"] == "GAP_THROUGH_STOP" and t["exit_level"] == D("96") and t["exit_price"] == D("95.90")


def test_time_exit_at_s5_close_and_missing_bars_are_skipped():
    t = TS.simulate(TS.CONFIG_A, win([QUIET, QUIET, None, QUIET, b(100, 102, 99, 101.5)]), CM)
    assert t["exit_reason"] == "TIME_EXIT" and t["exit_session"] == 5 and t["exit_level"] == D("101.5")
    assert "NO_BAR_S3" in t["flags"]
    t = TS.simulate(TS.CONFIG_A, win([QUIET, QUIET, QUIET, b(100, 102, 99, 100.7), None]), CM)
    assert t["exit_reason"] == "TIME_EXIT" and t["exit_session"] == 4 and t["exit_level"] == D("100.7")


def test_no_entry_reasons():
    assert TS.simulate(TS.CONFIG_A, win([None, QUIET]), CM)["entry_rejection_reason"] == "NO_BAR_S1"
    locked = b(110, 110, 110, 110, pc=100)                                   # locked at +10% all day: unbuyable
    assert TS.simulate(TS.CONFIG_A, win([locked, QUIET]), CM)["entry_rejection_reason"] == "LOCKED_UPPER"
    opened_at_band = b(110, 110, 108, 109, pc=100)                            # opened at +10%, then traded: buyable
    assert TS.simulate(TS.CONFIG_A, win([opened_at_band] + [QUIET] * 4), CM)["status"] == "CLOSED"
    chase = TS.Spec("chase", max_chase_pct=D("3"))
    assert TS.simulate(chase, win([b(103.5, 104, 103, 104), QUIET]), CM)["entry_rejection_reason"] == "MAX_CHASE"
    assert TS.simulate(chase, win([b(102.9, 104, 102, 104)] + [QUIET] * 4), CM)["status"] == "CLOSED"


def test_locked_lower_stop_cannot_sell_and_exits_at_the_next_open():
    locked = b(80, 80, 80, 80, pc=100)
    t = TS.simulate(TS.CONFIG_A, win([QUIET, locked, b(78, 79, 77, 78, pc=80), QUIET, QUIET]), CM)
    assert "LOCKED_LOWER_FULLDAY_S2" in t["flags"] and t["exit_session"] == 3 and t["exit_level"] == D("78")
    assert "RECOVERED" not in t["flags"]                                                   # sold at the next open
    t = TS.simulate(TS.CONFIG_A, win([QUIET] * 4 + [locked, b(79, 80, 78, 79.5, pc=80)]), CM)
    assert t["exit_session"] == 6 and t["exit_reason"] == "LIQUIDITY_EXIT" and t["exit_level"] == D("79")  # the open


def test_open_confirmation_entry_and_its_entry_bar_is_evaluated_stop_first():
    spec = TS.PROPOSED["C"]
    t = TS.simulate(spec, win([b(100, 103, 98, 102)] + [QUIET] * 4), CM)        # trigger 101 x 1.001 = 101.101 -> 101.10
    assert t["intended_entry"] == D("101.10") and "ENTRY_BAR_ORDER_UNKNOWN" in t["flags"]
    assert t["initial_stop"] == D("101.10") * D("0.98") and t["exit_reason"] == "STOP_HIT" and t["exit_session"] == 1
    t = TS.simulate(spec, win([b(102, 103, 101.5, 102.5)] + [QUIET] * 4), CM)    # gapped over the trigger: at the open
    assert t["intended_entry"] == D("102") and "ENTRY_BAR_ORDER_UNKNOWN" not in t["flags"]
    assert TS.simulate(spec, win([b(100, 101, 99, 100)] + [QUIET] * 4), CM)["entry_rejection_reason"] == "NOT_TRIGGERED"
    # the bar opened below the stop, but the position only exists from the trigger: a stop at the level, not a gap-through
    t = TS.simulate(spec, win([b(99, 103, 98, 102)] + [QUIET] * 4), CM)
    assert t["exit_reason"] == "STOP_HIT" and t["exit_level"] == D("101.10") * D("0.98")


def test_limit_and_typical_price_entries():
    t = TS.simulate(TS.PROPOSED["LIMIT"], win([b(100.5, 101, 99, 100)] + [QUIET] * 4), CM)
    assert t["intended_entry"] == D("99.50") and t["actual_entry"] == D("99.50")           # never above the limit
    t = TS.simulate(TS.PROPOSED["VWAP"], win([b(100, 103, 99, 102)] + [QUIET] * 4), CM)
    assert t["intended_entry"] == (D("103") + D("99") + D("102")) / 3 and t["actual_entry"] == D("101.43")


def test_atr_structure_and_volatility_stops():
    w = win([QUIET] * 5, atr_pct=3.0)
    assert TS.levels(TS.PROPOSED["B"], w, D("100")) == (D("95.5"), D("109.0"))           # 1.5 x ₹3 ATR; 2R = +9
    w = win([QUIET] * 5, low10=D("90"))
    assert TS.levels(TS.PROPOSED["STRUCTURE"], w, D("100"))[0] == D("92.00")              # 89.91 bounded to 8% below
    w = win([QUIET] * 5, low10=D("99.5"))
    assert TS.levels(TS.PROPOSED["STRUCTURE"], w, D("100"))[0] == D("99.00")              # 99.4005 bounded to 1% below
    w = win([QUIET] * 5, sigma20=0.02)
    stop, target = TS.levels(TS.PROPOSED["VOL_ADJ"], w, D("100"))
    assert stop == D("97.000") and target == D("107.5000")                                # 1.5 x 2% = 3%; 2.5R
    with pytest.raises(ValueError):
        TS.levels(TS.Spec("bad", stop="NONE", target="R_MULTIPLE"), w, D("100"))


def test_costs_off_run_has_no_slippage_or_charges():
    t = TS.simulate(TS.PROPOSED["E"], win([b(100, 104, 99, 103), b(103, 106, 102, 105)] + [QUIET] * 3), CM)
    assert t["actual_entry"] == D("100.00") and t["charges_inr"] == 0 and t["net_inr"] == t["gross_inr"] == D("2500.00")


def test_slippage_basis_decision_day_vs_fill_day():
    w = win([b(100, 104, 99, 103), b(103, 106, 102, 105)] + [QUIET] * 3, value20=3e8)
    w.value20_by_date = {d: 2e9 for d in w.dates}                                        # ₹200 cr on fill days -> 0.05%
    assert TS.simulate(TS.CONFIG_A, w, CM)["actual_entry"] == D("100.10")
    fill = TS.Spec("fill", slippage_basis="FILL")
    assert TS.simulate(fill, w, CM)["actual_entry"] == D("100.05")


def test_exact_path_keeps_unrounded_fills_for_the_reconciliation():
    flat = b(123.8, 124, 123, 123.9, pc=123.8)
    t = TS.simulate(TS.CONFIG_A, win([b(123.45, 124, 123, 123.8)] + [flat] * 4, d_close=123), CM)
    assert t["actual_entry"] == D("123.57") and t["entry_exact"] == D("123.45") * D("1.001")      # 123.57345
    assert t["qty_exact"] == 404 and t["fill_quantity"] == 404
    assert t["net_ret"] != t["net_ret_exact"]
    assert t["exit_exact"] == D("123.9") * D("0.999")


def test_no_target_no_stop_holds_to_the_time_exit():
    t = TS.simulate(TS.PROPOSED["H"], win([b(100, 120, 80, 100)] * 4 + [b(100, 101, 99, 100.5)]), CM)
    assert t["exit_reason"] == "TIME_EXIT" and t["exit_session"] == 5 and t["initial_stop"] is None


def test_path_statistics():
    t = TS.simulate(TS.CONFIG_A, win([b(100, 101, 97.5, 99), b(99, 106, 98.5, 105), QUIET, QUIET, QUIET]), CM)
    assert t["exit_session"] == 1 and t["exit_reason"] == "STOP_HIT"
    assert t["mfe_pct"] == pytest.approx(0.01) and t["mae_pct"] == pytest.approx(-0.025)
    assert t["high_after_exit_pct"] == pytest.approx(0.06) and t["path_max_high_pct"] == pytest.approx(0.06)
    assert t["close_last_pct"] == pytest.approx(0.0)


def test_a_position_locked_for_many_sessions_is_held_until_sellable():
    px = [round(100 * 0.95 ** k, 2) for k in range(12)]                    # eleven sessions locked at -5%
    locked = [b(px[k], px[k], px[k], px[k], pc=px[k - 1]) for k in range(1, 12)]
    t = TS.simulate(TS.CONFIG_A, win([QUIET] + locked + [b(57, 60, 56, 59, pc=px[11])]), CM)
    assert t["status"] == "CLOSED" and t["exit_session"] == 13 and t["exit_level"] == D("57")
    assert t["exit_reason"] == "LIQUIDITY_EXIT" and t["flags"].count("LOCKED_LOWER_FULLDAY") == 11


def test_a_bar_that_opens_at_a_band_and_trades_is_sold_into(d7=True):
    """D7 (owner approved 2026-09-20). This bar opens at the -20% circuit and then trades up to 90: the old lock test
    refused the sale and the position escaped its stop. It is now sold at the open, which is where the stop had
    already been gapped through."""
    opened_at_band = b(80, 90, 80, 88, pc=100)
    t = TS.simulate(TS.CONFIG_A, win([QUIET, opened_at_band, b(99, 100, 98.5, 99.5, pc=88), QUIET, QUIET]), CM)
    assert "LOCKED_LOWER" not in t["flags"] and "RECOVERED" not in t["flags"]
    assert t["exit_reason"] == "GAP_THROUGH_STOP" and t["exit_session"] == 2 and t["exit_level"] == D("80")


def test_a_stop_blocked_by_a_full_day_lock_sells_at_the_next_open_not_at_the_old_stop():
    locked = b(80, 80, 80, 80, pc=100)                           # -20%, never left the band: no sale possible
    t = TS.simulate(TS.CONFIG_A, win([QUIET, locked, b(99, 106, 98.5, 105, pc=80), QUIET, QUIET]), CM)
    assert "LOCKED_LOWER_FULLDAY_S2" in t["flags"]
    # the old rule kept the stop and let this trade reach the target at 105; it now leaves at the next open
    assert t["exit_reason"] == "LIQUIDITY_EXIT" and t["exit_session"] == 3 and t["exit_level"] == D("99")
