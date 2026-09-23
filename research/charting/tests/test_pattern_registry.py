"""Pattern Registry (owner decision 2026-09-23).

The registry exists to stop two lists drifting, so the load-bearing tests here are the ones that
check it against reality -- the detector source and the volume-rule split -- not the ones that
check it against itself.
"""
import pathlib
import re

import pytest

from research.charting import pattern_registry as r
from research.charting import signal_contract as c

PATTERNS_SRC = pathlib.Path(__file__).resolve().parents[1] / "patterns.py"


def test_the_taxonomy_is_complete():
    """3 frozen families + NI-3's 16 = 19. A missing family is how the old drift started."""
    assert len(r.FAMILIES) == 19
    assert len(r.enabled_families()) == 3
    assert len(r.disabled_families()) == 16


def test_enabled_families_really_have_a_detector_in_patterns_py():
    """The invariant's teeth: 'enabled' must mean a detector exists, not that a spec exists.
    Cross-checked against the detector source rather than against another list in this repo."""
    src = PATTERNS_SRC.read_text()
    emitted = set(re.findall(r'pattern_type="([A-Z_]+)"', src))
    for f in r.enabled_families():
        assert f.pattern_type in emitted, f"{f.pattern_type} is ENABLED but patterns.py never emits it"


def test_disabled_families_have_no_detector_in_patterns_py():
    src = PATTERNS_SRC.read_text()
    emitted = set(re.findall(r'pattern_type="([A-Z_]+)"', src))
    for f in r.disabled_families():
        assert f.pattern_type not in emitted, f"{f.pattern_type} is DISABLED but patterns.py emits it"


def test_every_disabled_family_says_why():
    for f in r.disabled_families():
        assert f.disabled_reason, f"{f.pattern_type} is disabled with no reason"
        assert f.spec, f"{f.pattern_type} has no spec reference"


def test_enabled_families_carry_no_disabled_reason():
    for f in r.enabled_families():
        assert f.disabled_reason is None


# ── the volume split (#109/#110) ────────────────────────────────────────────────────────────────
def test_frozen_families_keep_the_follow_through_rule():
    """Applying the new >=1.5x breakout threshold to a frozen family would silently change frozen
    v1 behaviour. The registry is what prevents it."""
    for f in r.enabled_families():
        assert f.volume_rule == r.VOLUME_FOLLOW_THROUGH, f"{f.pattern_type} must stay on the frozen rule"


def test_every_new_family_uses_the_breakout_bar_rule():
    for f in r.disabled_families():
        assert f.volume_rule == r.VOLUME_BREAKOUT_BAR


def test_volume_rule_is_read_from_the_registry():
    assert r.volume_rule("RECTANGLE") == r.VOLUME_FOLLOW_THROUGH
    assert r.volume_rule("ASCENDING_TRIANGLE") == r.VOLUME_BREAKOUT_BAR


# ── NI-3 grouping ───────────────────────────────────────────────────────────────────────────────
def test_ni3_groups_have_their_stated_sizes():
    new = r.disabled_families()
    assert len([f for f in new if f.geometry == r.GEOMETRY_P1]) == 7    # NI-3 §2
    assert len([f for f in new if f.geometry == r.GEOMETRY_P2]) == 4    # NI-3 §3
    assert len([f for f in new if f.geometry == r.GEOMETRY_OWN]) == 5   # NI-3 §4-§7


def test_detector_ids_are_unique():
    ids = [f.detector_id for f in r.FAMILIES]
    assert len(ids) == len(set(ids))


def test_pattern_types_are_unique():
    types = [f.pattern_type for f in r.FAMILIES]
    assert len(types) == len(set(types))


# ── the guard ───────────────────────────────────────────────────────────────────────────────────
def test_an_enabled_family_is_alertable():
    assert r.is_alertable("RECTANGLE")
    assert r.assert_alertable("RECTANGLE").detector_id == "RECT-v1"


def test_a_disabled_family_raises_with_the_reason_and_the_spec():
    assert not r.is_alertable("ASCENDING_TRIANGLE")
    with pytest.raises(r.PatternNotAlertable) as e:
        r.assert_alertable("ASCENDING_TRIANGLE")
    assert "TRI-ASC-v1" in str(e.value) and "NI-3 §2" in str(e.value)


def test_an_unregistered_family_raises_a_distinct_error():
    assert not r.is_alertable("TEACUP")
    with pytest.raises(r.PatternNotRegistered):
        r.get("TEACUP")


def test_registry_hash_is_deterministic():
    assert r.registry_hash() == r.registry_hash()
    assert len(r.registry_hash()) == 64


# ── the wiring into the signal contract ─────────────────────────────────────────────────────────
def test_an_alert_key_cannot_be_minted_for_a_disabled_family():
    """The end-to-end invariant: a disabled family cannot get an alert identity."""
    import datetime as dt
    with pytest.raises(r.PatternNotAlertable):
        c.dedupe_key("RELIANCE", "15minute", "ASCENDING_TRIANGLE", c.CONFIRMED_BREAKOUT, dt.datetime(2026, 9, 23))


def test_an_alert_key_is_minted_for_an_enabled_family():
    import datetime as dt
    key = c.dedupe_key("RELIANCE", "15minute", "RECTANGLE", c.CONFIRMED_BREAKOUT, dt.datetime(2026, 9, 23, 14, 45))
    assert key.startswith("RELIANCE|15minute|RECTANGLE|")


def test_the_contract_publishes_which_families_may_alert():
    s = c.serialisable()
    assert s["alertable_families"] == [f.pattern_type for f in r.enabled_families()]
    assert s["pattern_registry_hash"] == r.registry_hash()
