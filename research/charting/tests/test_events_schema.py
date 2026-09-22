"""schema.py: version constants, the "level broken" per-family mapping, and the liquidity
bucket table loader."""
from __future__ import annotations

from decimal import Decimal

from research.charting.events import schema


def test_level_broken_rectangle_both_directions_use_breakout_level_key():
    levels = {"support": 100.0, "resistance": 110.0, "breakout_level": 110.5, "invalidation_level": 99.5}
    assert schema.level_broken("RECTANGLE", "BULLISH", levels) == (110.5, "breakout_level")
    # RECTANGLE's own construction (patterns.py) sets "breakout_level" to the BROKEN level for
    # a BEARISH confirm too (the opposite-side threshold goes to "invalidation_level") -- see
    # schema.py's module docstring for the verified mapping.
    levels_bearish = {"support": 100.0, "resistance": 110.0, "breakout_level": 99.5, "invalidation_level": 110.5}
    assert schema.level_broken("RECTANGLE", "BEARISH", levels_bearish) == (99.5, "breakout_level")


def test_level_broken_support_resistance_keys_differ_by_direction():
    bullish_levels = {"level": 110.0, "kind": "RESISTANCE", "breakout_level": 110.4}
    bearish_levels = {"level": 100.0, "kind": "SUPPORT", "breakdown_level": 99.6}
    assert schema.level_broken("SUPPORT_RESISTANCE", "BULLISH", bullish_levels) == (110.4, "breakout_level")
    assert schema.level_broken("SUPPORT_RESISTANCE", "BEARISH", bearish_levels) == (99.6, "breakdown_level")


def test_level_broken_hh_hl_uses_prior_high_or_prior_low():
    levels = {"prior_high": 120.0, "prior_low": 90.0}
    assert schema.level_broken("HH_HL", "BULLISH", levels) == (120.0, "prior_high")
    assert schema.level_broken("HH_HL", "BEARISH", levels) == (90.0, "prior_low")


def test_level_broken_unknown_family_or_direction_returns_none_never_a_guess():
    assert schema.level_broken("TRIANGLE", "BULLISH", {"breakout_level": 5.0}) == (None, None)
    assert schema.level_broken("RECTANGLE", "NEUTRAL", {"breakout_level": 5.0}) == (None, None)
    assert schema.level_broken("HH_HL", "BULLISH", {}) == (None, None)


def test_default_liquidity_buckets_matches_zerodha_rule_file():
    buckets = schema.default_liquidity_buckets()
    assert buckets == (
        (Decimal("1000000000"), Decimal("0.05")),
        (Decimal("250000000"), Decimal("0.10")),
        (Decimal("0"), Decimal("0.20")),
    )
    # cached -- same object shape on a second call, not re-read/re-parsed differently
    assert schema.default_liquidity_buckets() == buckets


def test_segment_bounds_never_include_the_sealed_block():
    from research.charting.research_window import SEALED_GAP_END, SEALED_GAP_START

    assert schema.SEGMENT_MAX_DATE[schema.SEGMENT_PRE_SEALED] < SEALED_GAP_START
    assert schema.SEGMENT_MIN_DATE[schema.SEGMENT_POST_SEALED] > SEALED_GAP_END
