"""Target exits, the same-bar ambiguity flag and the new entry fills — tests written BEFORE the implementation
(Consecutive-Session Simulation PRD v1.0 §5 rows 5-6, §10, §16; deliverable D2). Every expected price is worked by hand.

Interface pinned here (additions to risk.execution; nothing existing changes):
  check_target(bar, target, slippage_pct) -> Fill | None
      open >= target -> GAP_OVER_TARGET at the open; else high >= target -> TARGET at the target; else None.
  exit_on_bar(bar, stop, target, slippage_pct, policy="STOP_FIRST") -> BarExit(fill, level, ambiguous)
      Per bar, in order: open <= stop -> the stop rule (GAP_THROUGH, or NO_FILL when locked at the lower circuit);
      open >= target -> GAP_OVER_TARGET; low <= stop and high >= target -> ambiguous, resolved by `policy`
      (STOP_FIRST | TARGET_FIRST); low <= stop -> STOP; high >= target -> TARGET. `level` is the raw price the exit
      keyed on (the open, the stop or the target) before slippage and rounding. stop or target may be None.
  fill_entry("LIMIT", bar, ..., limit=L): fills at min(open, L) when low <= L, never above L; NOT_REACHED otherwise.
  fill_entry("TYPICAL", bar, ...): (high + low + close) / 3 + slippage (the VWAP proxy); no fill on a locked-upper open.
"""
from __future__ import annotations

from decimal import Decimal as D

import pytest

from nidp.services.tpd_model.risk import execution as EX


def bar(o, h, l, c, v=100000, pc=100):
    return EX.Bar(open=D(str(o)), high=D(str(h)), low=D(str(l)), close=D(str(c)), volume=v, prev_close=D(str(pc)))


# ---------------- check_target ----------------
def test_target_fills_at_the_target_less_slippage():
    f = EX.check_target(bar(101, 106, 100, 104), D("105"), D("0.10"))
    assert f.status == "FILLED" and f.reason == "TARGET" and f.price == D("104.90")      # 105 x 0.999 = 104.895


def test_gap_over_the_target_fills_at_the_open_not_the_target():
    f = EX.check_target(bar(107, 108, 106, 107.5, pc=103), D("105"), D("0.10"))
    assert f.reason == "GAP_OVER_TARGET" and f.price == D("106.89")                      # 107 x 0.999 = 106.893


def test_target_not_reached_and_an_exact_touch():
    assert EX.check_target(bar(101, 104.99, 100, 104), D("105"), D("0")) is None
    f = EX.check_target(bar(101, 105, 100, 104), D("105"), D("0"))
    assert f.reason == "TARGET" and f.price == D("105.00")


# ---------------- exit_on_bar: order and the ambiguity flag ----------------
STOP, TGT = D("98"), D("105")


def test_open_at_or_below_the_stop_is_a_gap_through_even_if_the_bar_later_reaches_the_target():
    x = EX.exit_on_bar(bar(97, 110, 96, 100), STOP, TGT, D("0"))
    assert x.fill.reason == "GAP_THROUGH" and x.level == D("97") and not x.ambiguous
    x = EX.exit_on_bar(bar(98, 110, 96, 100), STOP, TGT, D("0"))                       # open exactly at the stop
    assert x.fill.reason == "GAP_THROUGH" and x.level == D("98")


def test_open_at_or_above_the_target_exits_at_the_open_even_if_the_bar_later_reaches_the_stop():
    x = EX.exit_on_bar(bar(106, 107, 90, 100, pc=103), STOP, TGT, D("0"))
    assert x.fill.reason == "GAP_OVER_TARGET" and x.level == D("106") and not x.ambiguous
    x = EX.exit_on_bar(bar(105, 107, 90, 100, pc=103), STOP, TGT, D("0"))
    assert x.fill.reason == "GAP_OVER_TARGET" and x.level == D("105")


def test_a_bar_touching_both_levels_is_flagged_and_resolved_by_the_policy():
    b = bar(100, 106, 97, 101)
    x = EX.exit_on_bar(b, STOP, TGT, D("0.10"))
    assert x.ambiguous and x.fill.reason == "STOP" and x.level == STOP and x.fill.price == D("97.90")   # 98 x 0.999
    x = EX.exit_on_bar(b, STOP, TGT, D("0.10"), policy="TARGET_FIRST")
    assert x.ambiguous and x.fill.reason == "TARGET" and x.level == TGT and x.fill.price == D("104.90")
    with pytest.raises(ValueError):
        EX.exit_on_bar(b, STOP, TGT, D("0"), policy="CLOSEST_FIRST")


def test_single_level_touches_and_exact_touches():
    x = EX.exit_on_bar(bar(100, 104, 97.5, 99), STOP, TGT, D("0"))
    assert x.fill.reason == "STOP" and x.level == STOP and not x.ambiguous
    x = EX.exit_on_bar(bar(100, 104, 98, 99), STOP, TGT, D("0"))                      # low exactly at the stop
    assert x.fill.reason == "STOP"
    x = EX.exit_on_bar(bar(100, 105, 99, 104), STOP, TGT, D("0"))                     # high exactly at the target
    assert x.fill.reason == "TARGET" and x.level == TGT and not x.ambiguous
    x = EX.exit_on_bar(bar(100, 104.99, 98.01, 104), STOP, TGT, D("0"))
    assert x.fill is None and x.level is None and not x.ambiguous


def test_locked_lower_circuit_at_the_stop_cannot_sell_and_stays_open():
    x = EX.exit_on_bar(bar(80, 80, 80, 80, pc=100), STOP, TGT, D("0"))
    assert x.fill.status == "NO_FILL" and x.fill.reason == "LOCKED_LOWER" and x.level is None


def test_missing_stop_or_target_checks_only_the_other_level():
    x = EX.exit_on_bar(bar(100, 106, 97, 101), None, TGT, D("0"))
    assert x.fill.reason == "TARGET" and not x.ambiguous
    x = EX.exit_on_bar(bar(100, 106, 97, 101), STOP, None, D("0"))
    assert x.fill.reason == "STOP" and not x.ambiguous
    assert EX.exit_on_bar(bar(100, 106, 97, 101), None, None, D("0")).fill is None


# ---------------- new entry fills ----------------
def test_limit_buy_fills_at_the_limit_or_a_lower_open_and_never_above_the_limit():
    f = EX.fill_entry("LIMIT", bar(100, 101, 98, 99), qty=10, slippage_pct=D("0.10"), participation_pct=D("100"),
                      limit=D("99.5"))
    assert f.status == "FILLED" and f.price == D("99.50")                 # 99.5 x 1.001 would exceed the limit
    f = EX.fill_entry("LIMIT", bar(97, 99, 96, 98), qty=10, slippage_pct=D("0.10"), participation_pct=D("100"),
                      limit=D("99.5"))
    assert f.price == D("97.10")                                          # gapped below: 97 x 1.001 = 97.097
    f = EX.fill_entry("LIMIT", bar(100, 101, 99.6, 100.5), qty=10, slippage_pct=D("0"), participation_pct=D("100"),
                      limit=D("99.5"))
    assert f.status == "NO_FILL" and f.reason == "NOT_REACHED"
    f = EX.fill_entry("LIMIT", bar(100, 101, 99.5, 100.5), qty=10, slippage_pct=D("0"), participation_pct=D("100"),
                      limit=D("99.5"))
    assert f.status == "FILLED" and f.price == D("99.50")                 # a low exactly at the limit fills
    with pytest.raises(ValueError):
        EX.fill_entry("LIMIT", bar(100, 101, 98, 99), qty=10, slippage_pct=D("0"), participation_pct=D("100"))


def test_typical_price_entry_is_the_vwap_proxy():
    f = EX.fill_entry("TYPICAL", bar(100, 103, 99, 102), qty=10, slippage_pct=D("0.10"), participation_pct=D("100"))
    assert f.status == "FILLED" and f.price == D("101.43")                # (103 + 99 + 102) / 3 x 1.001 = 101.4346...
    f = EX.fill_entry("TYPICAL", bar(120, 120, 118, 119, pc=100), qty=10, slippage_pct=D("0"), participation_pct=D("100"))
    assert f.status == "NO_FILL" and f.reason == "LOCKED_UPPER"
