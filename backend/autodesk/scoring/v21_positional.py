"""v21-positional — v2 with the two changes the shadow check (SIGNAL_TIER_HIERARCHY.md §12) supports (SHADOW; registry.py).

Evidence (2.6 years of daily data, §12): setup A (accumulation) and the bearish-warning −10 added nothing to how well the
bands sorted 20-session excess returns. So v2.1 is v2 with exactly two differences:
  1. SETUP_A_ACCUMULATION is context only: it is listed, and earns the supporting-evidence context point, but no
     signal-quality points. (Setup A needs a prior-20-session breakout on 1.5× volume, so the volume-breakout signal fires on
     the same bar and still supplies the quality points.)
  2. Bearish warnings are still listed, but cost no points.
Everything else — features, signals, tiers, weights, bands — is v2's code, so the two versions cannot drift apart.
"""
from __future__ import annotations

from typing import Optional, Sequence

from ..contracts import ShadowScore
from ..market.view import Bar
from . import v2_positional as _v2
from .v2_positional import Features, features

VERSION = "v21-positional"
RULES = "v21-positional-2026-11-07"


def score_at(F: Features, t: int) -> ShadowScore:
    return _v2.score_at(F, t, version=VERSION, setup_a_context=True, bearish_penalty=0)


def score_last(bars: Sequence[Bar], bench: Sequence[Bar], sector: Optional[Sequence[Bar]] = None,
               sector_name: Optional[str] = None) -> ShadowScore:
    if not bars:
        return ShadowScore(version=VERSION, horizon="POSITIONAL", status="SHADOW", reasons=["no bars"])
    F = features(bars, bench, sector, sector_name)
    return score_at(F, len(F) - 1)
