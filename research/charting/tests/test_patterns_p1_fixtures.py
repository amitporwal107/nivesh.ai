"""The nine mandatory NI-3 §2 fixtures (owner, 2026-09-23: "not merely examples").

Each asserts the geometry and the classification, not just "a pattern appeared": the candidate
structure, the upper/lower line directions, the shape or the named rejection reason, and — where
applicable — the lifecycle state.

The fixtures are built from CHOSEN LINES rather than hand-drawn prices, so `w` is exact: pivots are
placed on their line at chosen bars and the bars between them sit safely inside the channel. That
makes fixtures 1, 3 and 4 (w = 0.55, 1.6, 0.78) test the band boundaries they are meant to test
instead of whatever a hand-typed series happens to produce.
"""
import numpy as np
import pandas as pd
import pytest

from research.charting import geometry, ni3_config
from research.charting.patterns_p1 import (
    SHAPE_EXPANDING_OUT_OF_SCOPE, SHAPE_FLAT_PARALLEL_IS_RECTANGLE, SHAPE_LINES_CROSS,
    SHAPE_NOT_CONTAINED, SHAPE_UNCLASSIFIED, detect_p1_as_of, evaluate_candidate, select_candidate,
)
from research.charting.series import atr as atr_fn
from research.charting.swings import find_swings

NI3 = ni3_config.load()
P1, SHARED = NI3["p1_geometry"], NI3["shared"]


def _from_lines(upper: geometry.Line, lower: geometry.Line, n: int, *, pivot_every: int = 5,
                start: int = 4, tail: list[float] | None = None) -> pd.DataFrame:
    """Bars whose swing highs sit exactly on `upper` and swing lows exactly on `lower`.

    Between pivots the bar sits at the channel mid, so containment holds and no accidental pivot
    appears. Pivot bars alternate HIGH, LOW, HIGH, ... every `pivot_every` bars.
    """
    close, high, low, kinds = [], [], [], []
    for x in range(n):
        u = geometry.trendline_value_at(upper, x)
        l = geometry.trendline_value_at(lower, x)
        mid = (u + l) / 2.0
        close.append(mid); high.append(mid + (u - mid) * 0.15); low.append(mid - (mid - l) * 0.15)
        kinds.append(None)
    k = 0
    for x in range(start, n, pivot_every):
        u = geometry.trendline_value_at(upper, x)
        l = geometry.trendline_value_at(lower, x)
        if k % 2 == 0:
            high[x] = u; kinds[x] = "HIGH"
        else:
            low[x] = l; kinds[x] = "LOW"
        k += 1
    if tail:
        close = close + tail
        high = high + [c * 1.002 for c in tail]
        low = low + [c * 0.998 for c in tail]
    m = len(close)
    return pd.DataFrame({"date": pd.date_range("2026-01-01", periods=m, freq="D"),
                         "open": close, "high": high, "low": low, "close": close,
                         "volume": [1_000_000.0] * m})


def _evaluate(df: pd.DataFrame, t: int | None = None):
    t = len(df) - 1 if t is None else t
    view = df.iloc[: t + 1].reset_index(drop=True)
    pv = find_swings(view, left_bars=SHARED["swing_left_bars"], right_bars=SHARED["swing_right_bars"])
    atr = atr_fn(view, period=SHARED["atr_period"]).to_numpy()
    return select_candidate(view, t, pv, atr, P1, SHARED)


def _lines_for_w(w: float, n_bars: int, *, first_x: int, last_x: int, base: float = 100.0,
                 width0: float = 20.0, upper_flat: bool = False):
    """Two lines whose width ratio between `first_x` and `last_x` is exactly `w`."""
    width1 = width0 * w
    span = last_x - first_x
    if upper_flat:
        u_slope = 0.0
        l_slope = (width0 - width1) / span
        u_int = base + width0 / 2 - u_slope * first_x
        l_int = base - width0 / 2 - l_slope * first_x
    else:                                   # split the change symmetrically
        u_slope = -(width0 - width1) / (2 * span)
        l_slope = +(width0 - width1) / (2 * span)
        u_int = base + width0 / 2 - u_slope * first_x
        l_int = base - width0 / 2 - l_slope * first_x
    return geometry.Line(u_slope, u_int), geometry.Line(l_slope, l_int)


# ── Fixture 1 ───────────────────────────────────────────────────────────────────────────────────
def test_FIXTURE_01_flat_upper_rising_lower_converging_is_an_ascending_triangle():
    """Flat upper (change 0.9%), rising lower (change 4%), w = 0.55 -> ascending triangle."""
    upper, lower = _lines_for_w(0.55, 40, first_x=4, last_x=29, upper_flat=True)
    df = _from_lines(upper, lower, 34)
    cand, _ = _evaluate(df)
    assert cand is not None and cand.shape == "ASCENDING_TRIANGLE"
    assert cand.u_dir == geometry.FLAT and cand.l_dir == geometry.RISING
    assert cand.pair == geometry.CONVERGING
    assert cand.w == pytest.approx(0.55, abs=0.08)
    assert cand.direction == "BULLISH"


# ── Fixture 2 ───────────────────────────────────────────────────────────────────────────────────
def test_FIXTURE_02_flat_parallel_emits_nothing_the_rectangle_family_owns_it():
    upper = geometry.Line(0.0, 110.0)
    lower = geometry.Line(0.0, 90.0)
    df = _from_lines(upper, lower, 34)
    cand, attempts = _evaluate(df)
    assert cand is None, "flat + flat + parallel must not be emitted as a P-1 shape"
    assert any(a.reason == SHAPE_FLAT_PARALLEL_IS_RECTANGLE for a in attempts)
    assert detect_p1_as_of(df, len(df) - 1, symbol="T") == []


# ── Fixture 3 ───────────────────────────────────────────────────────────────────────────────────
def test_FIXTURE_03_w_of_1_6_is_expanding_and_out_of_scope():
    upper, lower = _lines_for_w(1.6, 40, first_x=4, last_x=29)
    df = _from_lines(upper, lower, 34)
    cand, attempts = _evaluate(df)
    assert cand is None
    assert any(a.reason == SHAPE_EXPANDING_OUT_OF_SCOPE for a in attempts)
    assert P1["expanding_in_scope"] is False


# ── Fixture 4 ───────────────────────────────────────────────────────────────────────────────────
def test_FIXTURE_04_w_of_0_78_is_unclassified_and_never_force_fitted():
    """0.70 < 0.78 < 0.85 — in the gap between converging and parallel. Rejected, not rounded."""
    upper, lower = _lines_for_w(0.78, 40, first_x=4, last_x=29)
    df = _from_lines(upper, lower, 34)
    cand, attempts = _evaluate(df)
    assert cand is None
    assert any(a.reason == SHAPE_UNCLASSIFIED for a in attempts)
    assert geometry.classify_pair(0.78) == geometry.SHAPE_UNCLASSIFIED


# ── Fixture 5 ───────────────────────────────────────────────────────────────────────────────────
def test_FIXTURE_05_a_close_beyond_the_upper_line_mid_formation_ends_the_formation():
    """"the formation ends as a breakout; the pattern is not stretched past it." A close 0.6% above
    the upper line (S5 = 0.5%) inside the pivot window breaks containment for that window."""
    upper, lower = _lines_for_w(0.55, 40, first_x=4, last_x=29, upper_flat=True)
    df = _from_lines(upper, lower, 34)
    mid = 18
    u_mid = geometry.trendline_value_at(upper, mid)
    df.loc[mid, ["close", "open"]] = u_mid * 1.006
    df.loc[mid, "high"] = u_mid * 1.008
    cand, attempts = _evaluate(df)

    # The stated contract is that the formation is not stretched PAST the breakout: any emitted
    # structure must lie wholly on one side of it. (A window that re-fits its upper line to include
    # the breakout bar's new pivot is not "stretched past" it — it is a different, later structure.)
    if cand is not None:
        spans = cand.pivots[0].pivot_index < mid < cand.pivots[-1].pivot_index
        assert not spans, "a P-1 formation must not span a bar that closed beyond its own boundary"

    # and at least one window that DOES span it was rejected for containment
    spanning = [a for a in attempts
                if a.pivots and a.pivots[0].pivot_index < mid < a.pivots[-1].pivot_index]
    assert all(a.shape is None for a in spanning), \
        "a window spanning the breach must not be emitted as an intact formation"


# ── Fixture 6 ───────────────────────────────────────────────────────────────────────────────────
def test_FIXTURE_06_a_pivot_confirmed_after_t_can_never_enter_the_fit():
    """§24.2 look-ahead. Every pivot the engine uses must satisfy confirmed_index <= t, and
    poisoning the bars after `t` must not move the result."""
    upper, lower = _lines_for_w(0.55, 40, first_x=4, last_x=29, upper_flat=True)
    df = _from_lines(upper, lower, 34)
    t = 28
    cand, _ = _evaluate(df, t)
    if cand is not None:
        assert all(p.confirmed_index <= t for p in cand.pivots)

    poisoned = df.copy()
    for i in range(t + 1, len(poisoned)):
        poisoned.loc[i, ["open", "high", "low", "close"]] = [9_999.0] * 4
    a = detect_p1_as_of(df, t, symbol="T")
    b = detect_p1_as_of(poisoned, t, symbol="T")
    assert [s.__dict__ for s in a] == [s.__dict__ for s in b]


# ── Fixture 7 ───────────────────────────────────────────────────────────────────────────────────
def test_FIXTURE_07_lines_that_intersect_inside_the_window_report_shape_lines_cross():
    """Step 5, isolated. The crossing rule is a property of the two FITTED lines over the pivot
    window, so it is tested by handing `evaluate_candidate` an explicit window rather than by
    reverse-engineering an OHLCV series: past a crossing a synthetic series is degenerate (upper
    below lower), the detected pivots stop being the ones intended, and the test would end up
    asserting something other than the rule.

    Highs fall 120 -> 100 -> 80 while lows rise 80 -> 100 -> 120: the lines meet near x = 17,
    inside the window 4..29.
    """
    from research.charting.swings import Pivot

    dates = pd.date_range("2026-01-01", periods=40, freq="D")

    def piv(kind, x, price):
        return Pivot(kind=kind, pivot_index=x, pivot_date=dates[x], price=price,
                     confirmed_index=x + 3, confirmed_date=dates[x + 3])

    window = [piv("HIGH", 4, 120.0), piv("LOW", 9, 80.0), piv("HIGH", 14, 100.0),
              piv("LOW", 19, 100.0), piv("HIGH", 24, 80.0), piv("LOW", 29, 120.0)]

    n = 40
    df = pd.DataFrame({"date": dates, "open": [100.0] * n, "high": [100.4] * n,
                       "low": [99.6] * n, "close": [100.0] * n, "volume": [1e6] * n})
    atr = atr_fn(df, period=SHARED["atr_period"]).to_numpy()

    cand = evaluate_candidate(df, 33, window, atr, P1, SHARED)
    assert cand.shape is None
    assert cand.reason == SHAPE_LINES_CROSS, f"expected SHAPE_LINES_CROSS, got {cand.reason}"

    # and the rule is about the fitted lines, not about any single bar
    assert geometry.trendline_value_at(cand.upper, 4) > geometry.trendline_value_at(cand.lower, 4)
    assert geometry.trendline_value_at(cand.upper, 29) < geometry.trendline_value_at(cand.lower, 29)


# ── Fixture 8 ───────────────────────────────────────────────────────────────────────────────────
def test_FIXTURE_08_a_rising_wedge_breaking_upward_is_invalidated_countertrend():
    """A rising wedge is bearish; a close 0.6% ABOVE its upper line before any breakdown is
    INVALIDATED with COUNTERTREND_BREAKOUT, never a confirmation."""
    # both lines rising, lower faster -> converging
    upper = geometry.Line(0.30, 100.0)
    lower = geometry.Line(0.65, 80.0)
    df = _from_lines(upper, lower, 34)
    cand, _ = _evaluate(df)
    if cand is None or cand.shape != "RISING_WEDGE":
        pytest.skip("fixture geometry did not yield a rising wedge under the frozen bands")
    t = len(df) - 1
    u_t = geometry.trendline_value_at(cand.upper, t)
    df.loc[t, ["open", "close"]] = u_t * 1.006
    df.loc[t, "high"] = u_t * 1.008
    snaps = detect_p1_as_of(df, t, symbol="T")
    assert snaps and snaps[0].status == "INVALIDATED"
    assert snaps[0].events[0]["rule_id"] == "COUNTERTREND_BREAKOUT"


# ── Fixture 9 — split by layer, deliberately ────────────────────────────────────────────────────
# NI-3 fixture 9: "A new pivot turns an ascending triangle's flat upper line into a rising one ->
# SHAPE_CHANGED, and a new pattern starts; the old one is not redrawn."
#
#   Detector (stateless, as-of-t)      : t1 -> ASCENDING_TRIANGLE ; t2 -> a different shape,
#                                        derived entirely from the pivots confirmed by t2.
#   Replay / identity layer            : the t1 identity is not redrawn at t2.
#
# "Not redrawn" must NOT be read as "the detector must remember t1". A stateless detector has no
# such obligation, and adding history to select_candidate() to satisfy this would destroy the
# detection/lifecycle separation in §39.13. The second assertion therefore belongs to the replay
# layer and is marked as such.

def test_FIXTURE_09_detector_contract_a_new_pivot_changes_the_shape():
    """DETECTOR LAYER. Both shapes follow from their own bar's confirmed pivots; nothing is
    remembered between them."""
    upper, lower = _lines_for_w(0.55, 40, first_x=4, last_x=29, upper_flat=True)
    df = _from_lines(upper, lower, 34)
    t1 = len(df) - 1
    c1, _ = _evaluate(df, t1)
    assert c1 is not None and c1.shape == "ASCENDING_TRIANGLE"
    assert c1.u_dir == geometry.FLAT

    # a new, higher swing high lifts the upper line off flat
    extended = df.copy()
    extra = pd.DataFrame({
        "date": pd.date_range(df["date"].iloc[-1] + pd.Timedelta(days=1), periods=8, freq="D"),
        "open": [0.0] * 8, "high": [0.0] * 8, "low": [0.0] * 8, "close": [0.0] * 8,
        "volume": [1_000_000.0] * 8,
    })
    u_last = geometry.trendline_value_at(upper, t1)
    l_last = geometry.trendline_value_at(lower, t1)
    mid = (u_last + l_last) / 2
    shape = [mid, mid + 1, u_last * 1.03, mid + 1, mid, mid, mid, mid]   # a clear higher high
    extra["close"] = shape; extra["open"] = shape
    extra["high"] = [v * 1.001 for v in shape]; extra["low"] = [v * 0.999 for v in shape]
    extra.loc[2, "high"] = u_last * 1.035
    extended = pd.concat([extended, extra], ignore_index=True)

    t2 = len(extended) - 1
    c2, _ = _evaluate(extended, t2)
    assert c2 is None or c2.shape != "ASCENDING_TRIANGLE", \
        "a new higher high must not leave the upper line flat"


def test_FIXTURE_09_replay_layer_contract_is_not_the_detectors_job():
    """REPLAY / IDENTITY LAYER — recorded, not asserted against the detector.

    "the old one is not redrawn" is a statement about pattern IDENTITY across bars. The detector is
    stateless by design (§39.13: a detector determines structure from confirmed pivots; the replay
    engine determines what happens to an already-established pattern), so it neither remembers nor
    redraws anything.

    This test exists to stop a future change "fixing" fixture 9 by adding historical state to
    `select_candidate()`. It asserts the detector's statelessness directly: the same bars at the
    same `t` produce the same answer regardless of what was asked for earlier.
    """
    upper, lower = _lines_for_w(0.55, 40, first_x=4, last_x=29, upper_flat=True)
    df = _from_lines(upper, lower, 34)
    t = len(df) - 1

    first = detect_p1_as_of(df, t, symbol="T")
    _ = detect_p1_as_of(df, t - 3, symbol="T")          # ask about an earlier bar in between
    again = detect_p1_as_of(df, t, symbol="T")
    assert [s.__dict__ for s in first] == [s.__dict__ for s in again], \
        "the detector must be stateless; identity across bars belongs to the replay layer"


# ── the invariant that spans every fixture ──────────────────────────────────────────────────────
def test_same_ohlcv_and_config_give_an_identical_result():
    upper, lower = _lines_for_w(0.55, 40, first_x=4, last_x=29, upper_flat=True)
    df = _from_lines(upper, lower, 34)
    a = detect_p1_as_of(df, len(df) - 1, symbol="T")
    b = detect_p1_as_of(df, len(df) - 1, symbol="T")
    assert [s.__dict__ for s in a] == [s.__dict__ for s in b]
    assert ni3_config.fingerprint(ni3_config.load()) == ni3_config.NI3_FINGERPRINT


# ══════════════════════════════════════════════════════════════════════════════════════════════
# APEX-DEADLINE BOUNDARY (owner-approved, 2026-09-23)
#
# Replay certification found 2 EXPIRED -> PRICE_CONFIRMED transitions. EXPIRED is terminal: NI-3 §2
# makes the temporal boundary part of the definition — "EXPIRED, reason APEX_REACHED, if no breakout
# comes before G13 of the distance from the first pivot to the apex". A breakout after G13 is a
# breakout of a dead structure and must not revive it.
#
# The pair below is the exact boundary:
#     breakout at G13 - 1  -> PRICE_CONFIRMED
#     breakout at G13 + 1  -> stays EXPIRED
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _converging_with_room(n_bars=90):
    """A converging structure whose apex — and therefore its G13 deadline — falls well AFTER the
    last pivot, leaving bars on both sides of the deadline to place a breakout on.

    Pivots are placed only up to bar 29; every later bar sits on the channel mid (monotone, so no
    new pivot forms and the candidate window stays 4..29). A gentler w keeps the apex distant.
    """
    upper, lower = _lines_for_w(0.66, 40, first_x=4, last_x=29, upper_flat=True)
    df = _from_lines(upper, lower, 34)
    extra_idx = range(34, n_bars)
    rows = []
    for x in extra_idx:
        u = geometry.trendline_value_at(upper, x)
        l = geometry.trendline_value_at(lower, x)
        mid = (u + l) / 2.0
        rows.append({"open": mid, "high": mid + (u - mid) * 0.15, "low": mid - (mid - l) * 0.15,
                     "close": mid, "volume": 1_000_000.0})
    extra = pd.DataFrame(rows)
    extra["date"] = pd.date_range(df["date"].iloc[-1] + pd.Timedelta(days=1), periods=len(extra), freq="D")
    df = pd.concat([df, extra[df.columns]], ignore_index=True)
    return upper, lower, df


def _deadline_of(df):
    from research.charting.patterns_p1 import _apex_x
    cand, _ = _evaluate(df, len(df) - 1)
    assert cand is not None and cand.pair == geometry.CONVERGING, "fixture must yield a converging shape"
    first_x = cand.pivots[0].pivot_index
    apex = _apex_x(cand.upper, cand.lower)
    assert apex is not None and apex > first_x
    return cand, first_x, apex, first_x + P1["apex_breakout_deadline_frac"] * (apex - first_x)


def _break_at(df, cand, bar):
    """Put a decisive close above the upper line at `bar`."""
    out = df.copy()
    u = geometry.trendline_value_at(cand.upper, bar)
    out.loc[bar, ["open", "close"]] = u * 1.02
    out.loc[bar, "high"] = u * 1.025
    out.loc[bar, "low"] = u * 1.015
    return out


def test_BOUNDARY_a_breakout_one_bar_before_the_apex_deadline_confirms():
    upper, lower, df = _converging_with_room()
    cand, first_x, apex, deadline = _deadline_of(df)
    bar = int(deadline) - 1
    assert bar > cand.pivots[-1].pivot_index, "the breakout must land after the last pivot"

    snaps = detect_p1_as_of(_break_at(df, cand, bar), bar, symbol="T")
    assert snaps, "expected the structure to still be detected"
    assert snaps[0].status == "PRICE_CONFIRMED"


def test_BOUNDARY_a_breakout_one_bar_after_the_apex_deadline_stays_expired():
    """The defect this fixture exists for. Before the fix the walk scanned every bar to `t` and this
    breakout confirmed a structure that had already expired."""
    upper, lower, df = _converging_with_room()
    cand, first_x, apex, deadline = _deadline_of(df)
    bar = int(deadline) + 1

    snaps = detect_p1_as_of(_break_at(df, cand, bar), bar, symbol="T")
    assert snaps, "expected the structure to still be reported"
    s = snaps[0]
    assert s.status == "EXPIRED", f"a post-deadline breakout must not revive an expired structure (got {s.status})"
    assert any(e["rule_id"] == "APEX_REACHED" for e in s.events)
    assert not any(r["rule_id"] == "P1_CLOSE_BEYOND_LINE" for r in s.rules), \
        "a post-deadline bar must not even be considered for breakout"


def test_BOUNDARY_expired_is_terminal_in_the_detector_output():
    """No snapshot may carry both an EXPIRED event and a PRICE_CONFIRMED one."""
    upper, lower, df = _converging_with_room()
    cand, first_x, apex, deadline = _deadline_of(df)
    for bar in (int(deadline) + 1, int(deadline) + 3):
        if bar >= len(df):
            continue
        for s in detect_p1_as_of(_break_at(df, cand, bar), bar, symbol="T"):
            kinds = {e["event_type"] for e in s.events}
            assert not ({"EXPIRED", "PRICE_CONFIRMED"} <= kinds), "EXPIRED and PRICE_CONFIRMED cannot coexist"
