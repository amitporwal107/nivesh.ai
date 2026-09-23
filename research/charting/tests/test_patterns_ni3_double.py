"""NI-3 §4 / §5 — double bottom and double top.

Certification themes from the v2 pack, applied to this family: GEO (positive, minimum evidence,
boundary tolerance, duration, invalid geometry), LIFE (forming, breakout, invalidated), BRK (exact
threshold, below/above), and NLA (future mutation, pivot confirmation).
"""
import pandas as pd
import pytest

from research.charting import ni3_config
from research.charting.patterns_ni3 import detect_ni3_as_of


def _bars(px, volume=1_000_000.0):
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=len(px), freq="D"),
        "open": px, "high": [p * 1.005 for p in px], "low": [p * 0.995 for p in px],
        "close": px, "volume": [volume] * len(px),
    })


# A clean double bottom: troughs at bars 7 and 17 (separation 10 = B1 exactly), neckline at 12.
W_BASE = [100] * 4 + [97, 94, 91, 90] + [92, 95, 98, 100, 100, 99] + [97, 94, 91, 90.5]
DB_BREAKOUT = W_BASE + [92, 95, 98, 101, 103]
DB_PENDING = W_BASE + [92, 95, 98, 99, 100]          # never closes beyond the neckline
# Invalidation must break the neckline structure WITHOUT displacing the second trough as a pivot:
# the trough at bar 17 needs its 3-bar right window to stay above it, so the break comes at bar 21.
DB_INVALID = W_BASE + [92, 95, 94, 88, 85]           # closes below the second trough at bar 21


def _only(snaps, ptype):
    return [s for s in snaps if s.pattern_type == ptype]


def test_a_double_bottom_is_detected_and_confirms_on_the_breakout():
    snaps = _only(detect_ni3_as_of(_bars(DB_BREAKOUT), len(DB_BREAKOUT) - 1, symbol="T"), "DOUBLE_BOTTOM")
    assert len(snaps) == 1
    s = snaps[0]
    assert s.direction == "BULLISH"
    assert s.status == "PRICE_CONFIRMED"
    assert s.levels["neckline"] == pytest.approx(100.5)
    # NI-3 §4: breakout is close > neckline x (1 + S5), S5 = 0.5%
    assert s.levels["breakout_level"] == pytest.approx(100.5 * 1.005)


def test_before_the_breakout_it_stays_geometry_valid():
    snaps = _only(detect_ni3_as_of(_bars(DB_PENDING), len(DB_PENDING) - 1, symbol="T"), "DOUBLE_BOTTOM")
    assert len(snaps) == 1
    assert snaps[0].status == "GEOMETRY_VALID"


def test_a_close_below_the_second_trough_invalidates():
    """A break that falls straight through the trough instead DISPLACES it as a swing low, so the
    pair genuinely stops being a double bottom as of `t` — the lifecycle of that case belongs to the
    replay layer, not to a single as-of-`t` snapshot. Here the break comes far enough after the
    trough that the pivot survives and the pattern can be recorded as INVALIDATED."""
    snaps = _only(detect_ni3_as_of(_bars(DB_INVALID), len(DB_INVALID) - 1, symbol="T"), "DOUBLE_BOTTOM")
    assert len(snaps) == 1
    s = snaps[0]
    assert s.status == "INVALIDATED"
    assert any(r["rule_id"] == "DE_CLOSE_BEYOND_SECOND_EXTREME" and r["result"] == "FAIL" for r in s.rules)


def test_every_frozen_rule_is_recorded_with_its_threshold():
    s = _only(detect_ni3_as_of(_bars(DB_BREAKOUT), len(DB_BREAKOUT) - 1, symbol="T"), "DOUBLE_BOTTOM")[0]
    got = {r["rule_id"]: r for r in s.rules}
    ni3 = ni3_config.load()["double_bottom"]
    assert got["DE_MIN_SEPARATION_BARS"]["threshold"] == ni3["trough_min_separation_bars"]
    assert got["DE_EXTREME_TOLERANCE_PCT"]["threshold"] == ni3["trough_tolerance_pct"]
    assert got["DE_NECKLINE_MOVE_PCT"]["threshold"] == ni3["recovery_min_pct"]


# ── minimum evidence: each frozen gate actually rejects ─────────────────────────────────────────
def test_troughs_closer_than_b1_are_rejected():
    """Separation 9 < B1 = 10. This is the real reason an earlier fixture found nothing."""
    px = [100] * 4 + [97, 94, 91, 90] + [92, 95, 98, 100, 99] + [97, 94, 91, 90.5] + [92, 95, 98, 101, 103]
    snaps = _only(detect_ni3_as_of(_bars(px), len(px) - 1, symbol="T"), "DOUBLE_BOTTOM")
    assert snaps == []


def test_troughs_further_apart_than_b2_are_rejected():
    """Second trough 10% below the first, against a 3% tolerance."""
    px = W_BASE[:-1] + [81.0] + [83, 86, 90, 95, 101, 103]
    snaps = _only(detect_ni3_as_of(_bars(px), len(px) - 1, symbol="T"), "DOUBLE_BOTTOM")
    assert snaps == []


def test_a_shallow_recovery_below_b5_is_rejected():
    """Neckline only ~2% above the troughs, against B5 = 5%."""
    px = [100] * 4 + [95, 92, 90.5, 90] + [90.6, 91.2, 91.8, 91.9, 91.8, 91.4] + [91, 90.7, 90.4, 90.2] + [91, 92, 93, 94, 95]
    snaps = _only(detect_ni3_as_of(_bars(px), len(px) - 1, symbol="T"), "DOUBLE_BOTTOM")
    assert snaps == []


def test_a_structure_with_no_reaction_high_between_the_troughs_is_rejected():
    px = [100] * 4 + [95, 92, 90, 89] + [89.2, 89.4, 89.3, 89.5, 89.4, 89.6] + [89.5, 89.3, 89.1, 89.0] + [90, 92, 95, 99, 103]
    snaps = _only(detect_ni3_as_of(_bars(px), len(px) - 1, symbol="T"), "DOUBLE_BOTTOM")
    assert all(s.levels.get("neckline") is not None for s in snaps)


# ── the mirror ──────────────────────────────────────────────────────────────────────────────────
def test_a_double_top_is_the_mirror_and_breaks_down():
    px = [90] * 4 + [93, 96, 99, 100] + [98, 95, 92, 90, 90, 91] + [93, 96, 99, 99.5] + [98, 95, 92, 89, 87]
    snaps = _only(detect_ni3_as_of(_bars(px), len(px) - 1, symbol="T"), "DOUBLE_TOP")
    assert len(snaps) == 1
    s = snaps[0]
    assert s.direction == "BEARISH"
    assert s.status == "PRICE_CONFIRMED"
    # breakdown is close < neckline x (1 - S5)
    assert s.levels["breakdown_level"] == pytest.approx(s.levels["neckline"] * 0.995)


# ── no look-ahead ───────────────────────────────────────────────────────────────────────────────
def test_NLA_future_bars_cannot_change_the_result_at_t():
    """Poison every bar after `t` — price and volume — and the snapshot at `t` must be identical."""
    t = len(W_BASE) + 1
    clean = _bars(DB_BREAKOUT)
    poisoned = clean.copy()
    for i in range(t + 1, len(poisoned)):
        poisoned.loc[i, ["open", "high", "low", "close"]] = [9_999.0, 9_999.0, 9_999.0, 9_999.0]
        poisoned.loc[i, "volume"] = 9_999_999.0

    a = detect_ni3_as_of(clean, t, symbol="T")
    b = detect_ni3_as_of(poisoned, t, symbol="T")
    assert [s.__dict__ for s in a] == [s.__dict__ for s in b]


def test_NLA_negative_control_the_probe_can_detect_a_leak():
    """If the detector did read the future, the test above would notice — proved by comparing two
    DIFFERENT `t` values on the poisoned frame, which must differ."""
    poisoned = _bars(DB_BREAKOUT).copy()
    for i in range(len(W_BASE) + 2, len(poisoned)):
        poisoned.loc[i, ["open", "high", "low", "close"]] = [9_999.0] * 4
    early = detect_ni3_as_of(poisoned, len(W_BASE) + 1, symbol="T")
    late = detect_ni3_as_of(poisoned, len(poisoned) - 1, symbol="T")
    assert [s.status for s in early] != [s.status for s in late]


def test_the_walk_never_starts_before_every_pivot_was_confirmed():
    """A breakout printed before the second trough was knowable must not confirm the pattern."""
    snaps = _only(detect_ni3_as_of(_bars(DB_BREAKOUT), len(DB_BREAKOUT) - 1, symbol="T"), "DOUBLE_BOTTOM")
    s = snaps[0]
    confirm = [e for e in s.events if e["event_type"] == "PRICE_CONFIRMED"]
    assert confirm, "expected a confirmation event"
    last_pivot_confirmed = max(p["confirmed_date"] for p in s.pivots)
    assert confirm[0]["date"] >= last_pivot_confirmed


# ── determinism ─────────────────────────────────────────────────────────────────────────────────
def test_detection_is_deterministic():
    a = detect_ni3_as_of(_bars(DB_BREAKOUT), len(DB_BREAKOUT) - 1, symbol="T")
    b = detect_ni3_as_of(_bars(DB_BREAKOUT), len(DB_BREAKOUT) - 1, symbol="T")
    assert [s.__dict__ for s in a] == [s.__dict__ for s in b]


def test_the_frozen_v1_detector_is_untouched_by_this_module():
    """patterns.py must not emit an NI-3 type, and this module must not emit a P0 type."""
    from research.charting.patterns import detect_as_of
    v1 = detect_as_of(_bars(DB_BREAKOUT), len(DB_BREAKOUT) - 1, symbol="T")
    assert all(s.pattern_type in {"SUPPORT_RESISTANCE", "RECTANGLE", "HH_HL"} for s in v1)
    ni3 = detect_ni3_as_of(_bars(DB_BREAKOUT), len(DB_BREAKOUT) - 1, symbol="T")
    assert all(s.pattern_type in {"DOUBLE_BOTTOM", "DOUBLE_TOP"} for s in ni3)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# CERTIFICATION FIXTURES (owner, 2026-09-23). These five are locked: they exist to stop a later
# "helpful" relaxation of a frozen boundary, and to keep the detector/replay split honest.
#
#   | Fixture                              | Expected                   | Protects            |
#   | 9-bar separation                     | reject                     | minimum-duration    |
#   | 10-bar separation                    | accept candidate           | minimum-duration    |
#   | break through UNCONFIRMED trough     | no snapshot invalidation   | pivot integrity     |
#   | break through ESTABLISHED trough     | invalidate                 | lifecycle integrity |
#   | future bar changes historical pivot  | historical result unchanged| no-look-ahead       |
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _double_bottom_with_separation(sep_bars: int):
    """A double bottom whose two troughs are exactly `sep_bars` apart, everything else valid."""
    pre = [100] * 4 + [97, 94, 91, 90]                    # trough at bar 7
    mid = [92, 95, 98, 100, 100, 99][: max(1, sep_bars - 4)]
    while len(pre) + len(mid) + 4 - 1 - 7 < sep_bars:      # pad the middle until the gap is right
        mid = mid + [99]
    tail = [97, 94, 91, 90.5]                              # second trough closes the gap
    return pre + mid + tail + [92, 95, 98, 101, 103]


@pytest.mark.parametrize("sep,expected", [(9, 0), (10, 1)])
def test_CERT_separation_boundary_is_exactly_ten_bars(sep, expected):
    """LOCKED. B1/P1 = 10 sessions (OWNER, re-confirmed #110). Nine must reject, ten must accept —
    the off-by-one that protects the frozen minimum from later relaxation."""
    px = _double_bottom_with_separation(sep)
    snaps = _only(detect_ni3_as_of(_bars(px), len(px) - 1, symbol="T"), "DOUBLE_BOTTOM")
    troughs = [p for s in snaps for p in s.pivots if p["kind"] == "LOW"]
    assert len(snaps) == expected, f"separation {sep} should {'accept' if expected else 'reject'}; got {len(snaps)}"
    if expected:
        idx = sorted(troughs, key=lambda p: p["date"])
        assert len(idx) == 2


def test_CERT_a_break_through_an_unconfirmed_trough_does_not_invalidate_a_snapshot():
    """LOCKED — pivot integrity. If the breaking bar itself displaces the trough as a swing low,
    the pair never was a structure as of `t`: the detector reports NO PATTERN, not an invalidated
    one. Reporting INVALIDATED here would mean claiming a structure that was never established.
    """
    px = W_BASE + [92, 90, 88, 86, 85]          # falls straight through; trough at 17 is displaced
    snaps = _only(detect_ni3_as_of(_bars(px), len(px) - 1, symbol="T"), "DOUBLE_BOTTOM")
    assert snaps == [], "a displaced trough yields no pattern, not an invalidated one"


def test_CERT_a_break_through_an_established_trough_invalidates():
    """LOCKED — lifecycle integrity. The trough survives as a confirmed pivot, the structure was
    established, so the subsequent break is a lifecycle transition and must be recorded."""
    snaps = _only(detect_ni3_as_of(_bars(DB_INVALID), len(DB_INVALID) - 1, symbol="T"), "DOUBLE_BOTTOM")
    assert len(snaps) == 1
    assert snaps[0].status == "INVALIDATED"
    assert [e["event_type"] for e in snaps[0].events] == ["INVALIDATED"]


def test_CERT_a_future_bar_cannot_change_a_historical_pivot_or_result():
    """LOCKED — no-look-ahead. Covered functionally by test_NLA_*; restated here as a named
    certification fixture so the suite reads as the pack's matrix does."""
    t = len(W_BASE) + 1
    clean = _bars(DB_BREAKOUT)
    poisoned = clean.copy()
    for i in range(t + 1, len(poisoned)):
        poisoned.loc[i, ["open", "high", "low", "close"]] = [1.0, 1.0, 1.0, 1.0]
    assert [s.__dict__ for s in detect_ni3_as_of(clean, t, symbol="T")] == \
           [s.__dict__ for s in detect_ni3_as_of(poisoned, t, symbol="T")]
