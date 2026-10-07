"""Pattern Registry -- the single authoritative list of pattern families and whether each one may
produce a production alert (owner decision, 2026-09-23).

THE INVARIANT
-------------
    A specification may describe future detector families, but production alerts and validated
    paper results may only reference detector families that are implemented, versioned and
    independently validated.

Before this module there were two independent lists: the alerts PRD §7 named 14 families and NI-3
names 16, while `patterns.py` implements 3. Two lists drift; one registry cannot. Everything
downstream -- the signal evaluator, the alert aggregator, the paper kernel -- asks this module
whether a family may fire, and `assert_alertable()` raises rather than returning a soft answer, so a
family can never be alerted on by omission.

WHAT "ENABLED" MEANS HERE
-------------------------
`enabled=True` requires all three: a detector exists in `research/charting/patterns.py`, it is
frozen under the v1 config, and it has historical validation behind it. It is deliberately NOT
"someone wrote a spec for it". As of 2026-09-23 exactly three families qualify -- the three that
appear in the committed snapshot (SUPPORT_RESISTANCE 388, RECTANGLE 114, HH_HL 11 across 50
symbols). The other sixteen are registered so the taxonomy is complete and reviewable, and disabled
so they cannot fire.

VOLUME RULE IS A REGISTRY FACT, NOT A GLOBAL
--------------------------------------------
The two rules are per-family and must not be merged (#109/#110, NI-3 §1 table):
  - today's three frozen families: FOLLOW_THROUGH, 1.0x-4.0x the 20-session average;
  - the sixteen new families:      BREAKOUT_BAR, >= 1.5x.
Keeping this on the family removes the standing risk of applying the new threshold to a frozen
family, which would silently change frozen v1 behaviour.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from typing import Optional

REGISTRY_VERSION = "1.0.0"

#: Volume confirmation rules. Which one applies is a property of the family (#109/#110).
VOLUME_FOLLOW_THROUGH = "FOLLOW_THROUGH_1.0x_4.0x"
VOLUME_BREAKOUT_BAR = "BREAKOUT_BAR_MIN_1.5x"

#: Geometry engine a family is built on.
GEOMETRY_OWN = "OWN"          # the family's own rules
GEOMETRY_P1 = "P-1"           # the shared fitted-line engine (NI-3 §2)
GEOMETRY_P2 = "P-2"           # pole + P-1 shape (NI-3 §3)


@dataclass(frozen=True)
class PatternFamily:
    #: Canonical pattern_type, as written into the snapshot by patterns.py.
    pattern_type: str
    #: Stable detector id, versioned independently of the family name.
    detector_id: str
    #: Human label for UI.
    label: str
    #: OWN / P-1 / P-2 -- which geometry engine the family needs.
    geometry: str
    #: Which volume confirmation rule applies.
    volume_rule: str
    #: True only when a frozen, validated detector exists. See module docstring.
    enabled: bool
    #: Where the family is specified.
    spec: str
    #: Why it is disabled, or None when enabled. Shown to the user instead of silence.
    disabled_reason: Optional[str] = None


_NO_DETECTOR = "no detector implemented; specification only"

#: Every family, enabled or not. Order is: the frozen three, then NI-3's three groups.
FAMILIES: tuple[PatternFamily, ...] = (
    # ── frozen v1: implemented, validated, alertable ────────────────────────────────────────────
    PatternFamily("SUPPORT_RESISTANCE", "SR-v1", "Support / resistance", GEOMETRY_OWN,
                  VOLUME_FOLLOW_THROUGH, True, "docs/charting.md §13.2"),
    PatternFamily("RECTANGLE", "RECT-v1", "Rectangle", GEOMETRY_OWN,
                  VOLUME_FOLLOW_THROUGH, True, "docs/charting.md §11"),
    PatternFamily("HH_HL", "STRUCTURE-v1", "Higher highs / higher lows", GEOMETRY_OWN,
                  VOLUME_FOLLOW_THROUGH, True, "docs/charting.md §11"),

    # ── NI-3 P-1 shapes (§2): one shared fitted-line engine ─────────────────────────────────────
    PatternFamily("ASCENDING_TRIANGLE", "TRI-ASC-v1", "Ascending triangle", GEOMETRY_P1,
                  VOLUME_BREAKOUT_BAR, False, "NI-3 §2", _NO_DETECTOR),
    PatternFamily("DESCENDING_TRIANGLE", "TRI-DESC-v1", "Descending triangle", GEOMETRY_P1,
                  VOLUME_BREAKOUT_BAR, False, "NI-3 §2", _NO_DETECTOR),
    PatternFamily("SYMMETRICAL_TRIANGLE", "TRI-SYM-v1", "Symmetrical triangle", GEOMETRY_P1,
                  VOLUME_BREAKOUT_BAR, False, "NI-3 §2", _NO_DETECTOR),
    PatternFamily("RISING_WEDGE", "WEDGE-R-v1", "Rising wedge", GEOMETRY_P1,
                  VOLUME_BREAKOUT_BAR, False, "NI-3 §2", _NO_DETECTOR),
    PatternFamily("FALLING_WEDGE", "WEDGE-F-v1", "Falling wedge", GEOMETRY_P1,
                  VOLUME_BREAKOUT_BAR, False, "NI-3 §2", _NO_DETECTOR),
    PatternFamily("ASCENDING_CHANNEL", "CHANNEL-ASC-v1", "Ascending channel", GEOMETRY_P1,
                  VOLUME_BREAKOUT_BAR, False, "NI-3 §2", _NO_DETECTOR),
    PatternFamily("DESCENDING_CHANNEL", "CHANNEL-DESC-v1", "Descending channel", GEOMETRY_P1,
                  VOLUME_BREAKOUT_BAR, False, "NI-3 §2", _NO_DETECTOR),

    # ── NI-3 P-2 (§3): pole + P-1 shape, so gated behind P-1 ────────────────────────────────────
    PatternFamily("BULL_FLAG", "FLAG-BULL-v1", "Bull flag", GEOMETRY_P2,
                  VOLUME_BREAKOUT_BAR, False, "NI-3 §3", _NO_DETECTOR),
    PatternFamily("BEAR_FLAG", "FLAG-BEAR-v1", "Bear flag", GEOMETRY_P2,
                  VOLUME_BREAKOUT_BAR, False, "NI-3 §3", _NO_DETECTOR),
    PatternFamily("BULL_PENNANT", "PENNANT-BULL-v1", "Bull pennant", GEOMETRY_P2,
                  VOLUME_BREAKOUT_BAR, False, "NI-3 §3", _NO_DETECTOR),
    PatternFamily("BEAR_PENNANT", "PENNANT-BEAR-v1", "Bear pennant", GEOMETRY_P2,
                  VOLUME_BREAKOUT_BAR, False, "NI-3 §3", _NO_DETECTOR),

    # ── NI-3 own rules (§4-§7) ──────────────────────────────────────────────────────────────────
    PatternFamily("DOUBLE_BOTTOM", "DB-v1", "Double bottom", GEOMETRY_OWN,
                  VOLUME_BREAKOUT_BAR, False, "NI-3 §4", _NO_DETECTOR),
    PatternFamily("DOUBLE_TOP", "DT-v1", "Double top", GEOMETRY_OWN,
                  VOLUME_BREAKOUT_BAR, False, "NI-3 §5", _NO_DETECTOR),
    PatternFamily("HEAD_AND_SHOULDERS", "HS-v1", "Head & shoulders", GEOMETRY_OWN,
                  VOLUME_BREAKOUT_BAR, False, "NI-3 §6", _NO_DETECTOR),
    PatternFamily("INVERSE_HEAD_AND_SHOULDERS", "IHS-v1", "Inverse head & shoulders", GEOMETRY_OWN,
                  VOLUME_BREAKOUT_BAR, False, "NI-3 §6b", _NO_DETECTOR),
    PatternFamily("CUP_AND_HANDLE", "CAH-v1", "Cup & handle", GEOMETRY_OWN,
                  VOLUME_BREAKOUT_BAR, False, "NI-3 §7", _NO_DETECTOR),
)

_BY_TYPE: dict[str, PatternFamily] = {f.pattern_type: f for f in FAMILIES}


class PatternNotRegistered(KeyError):
    """A pattern_type nothing in the registry knows about."""


class PatternNotAlertable(ValueError):
    """A registered family that may not produce a production alert yet."""


def get(pattern_type: str) -> PatternFamily:
    try:
        return _BY_TYPE[pattern_type]
    except KeyError:
        raise PatternNotRegistered(
            f"{pattern_type!r} is not in the pattern registry; registered: {sorted(_BY_TYPE)}"
        ) from None


def is_registered(pattern_type: str) -> bool:
    return pattern_type in _BY_TYPE


def is_alertable(pattern_type: str) -> bool:
    """True only for a registered AND enabled family. Unknown families are False, never an error --
    use `assert_alertable` when the caller needs the reason."""
    f = _BY_TYPE.get(pattern_type)
    return bool(f and f.enabled)


def assert_alertable(pattern_type: str) -> PatternFamily:
    """Raise unless this family may produce a production alert. This is the enforcement point for
    the module invariant: an alert pipeline calls this and cannot proceed on a disabled family."""
    f = get(pattern_type)
    if not f.enabled:
        raise PatternNotAlertable(
            f"{pattern_type} ({f.detector_id}) is registered but not alertable: "
            f"{f.disabled_reason}. Specified in {f.spec}."
        )
    return f


def enabled_families() -> tuple[PatternFamily, ...]:
    return tuple(f for f in FAMILIES if f.enabled)


def disabled_families() -> tuple[PatternFamily, ...]:
    return tuple(f for f in FAMILIES if not f.enabled)


def volume_rule(pattern_type: str) -> str:
    """The volume confirmation rule for this family. Read from the registry so a frozen family can
    never be evaluated under the new-family threshold."""
    return get(pattern_type).volume_rule


def serialisable() -> dict:
    return {
        "version": REGISTRY_VERSION,
        "families": [asdict(f) for f in FAMILIES],
        "enabled": [f.pattern_type for f in enabled_families()],
        "disabled": [f.pattern_type for f in disabled_families()],
    }


def registry_hash() -> str:
    """Stable sha256. Changes the moment a family is added or its enabled flag flips, so a stored
    signal can be checked against the registry it was produced under."""
    return hashlib.sha256(json.dumps(serialisable(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
