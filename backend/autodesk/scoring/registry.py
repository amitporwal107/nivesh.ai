"""Scoring versions of the desk's AI Trader — which one selects, which ones only shadow (owner, 5 Nov 2026).

v1 is the production scoring (agents/ai_trader.py, ait-rules-v1) and the only version that may select signals. Other versions
run in SHADOW: their scores are stored beside each signal (Signal.shadow_scores) and in the scan report (ScanReport.shadow) for
comparison and walk-forward validation, and change nothing the desk does. Promoting a version is a code change made after its
validation report (docs/signal_intelligence/SIGNAL_TIER_HIERARCHY.md §8, §11) — never a runtime switch.

Environment: AUTODESK_SCORING_SHADOW = comma list of versions to run in shadow (default "v2-positional,v21-positional"; "" turns shadow
scoring off). AUTODESK_V2_BARS = daily bars read for v2 (default 500: the relative-strength breakout needs 251, the
multi-year breakout 481).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

ACTIVE = "v1"
DEFAULT_SHADOW = ["v2-positional", "v21-positional"]


@dataclass(frozen=True)
class Version:
    key: str
    horizon: str                       # POSITIONAL / SWING / INTRADAY
    status: str                        # ACTIVE / SHADOW / DISABLED (default; the environment can only switch shadows off)
    description: str
    weights: dict[str, Decimal] = field(default_factory=dict)
    validation: str = ""


V2_WEIGHTS = {"signal_quality": Decimal("45"), "trend_confirmation": Decimal("30"), "relative_strength": Decimal("15"),
              "supporting_evidence": Decimal("10")}

VERSIONS: dict[str, Version] = {
    "v1": Version("v1", "POSITIONAL", "ACTIVE",
                  "Production scoring ait-rules-v1: eight weighted dimensions over the previous session's end-of-day data.",
                  {"trend": Decimal("15"), "momentum": Decimal("15"), "volume_delivery": Decimal("15"),
                   "relative_strength": Decimal("10"), "structure": Decimal("15"), "derivatives": Decimal("15"),
                   "regime": Decimal("5"), "liquidity": Decimal("10")},
                  "5 Nov 2026 replay study: rank IC vs 5-session excess return −0.028 (May–Nov 2026)."),
    "v2-positional": Version("v2-positional", "POSITIONAL", "SHADOW",
                             "Revised signal hierarchy for 10–20-session positional trades: signal quality 45 + trend "
                             "confirmation 30 + relative strength 15 + supporting evidence 10; bearish signals are warnings only.",
                             dict(V2_WEIGHTS),
                             "Calibrated on daily data Apr 2024 – Sep 2025, judged Oct 2025 – Nov 2026 (study 5 Nov 2026); "
                             "shadow validation pending before any promotion."),
    "v21-positional": Version("v21-positional", "POSITIONAL", "SHADOW",
                              "v2-positional with two changes the shadow check supports: setup A (accumulation) is context "
                              "only and earns no signal-quality points, and bearish warnings are listed but cost no points.",
                              dict(V2_WEIGHTS),
                              "Changes follow the 2.6-year shadow check of v2 (SIGNAL_TIER_HIERARCHY.md §12: setup A and the "
                              "−10 added nothing); shadow validation pending before any promotion."),
    "v3-intraday": Version("v3-intraday", "INTRADAY", "DISABLED",
                           "Intraday hierarchy (first-5-minute volume, opening-range breakout, VWAP reclaim): off until its "
                           "study is complete.", {}, "Study running (Kite minute data)."),
}


def active_version() -> str:
    return ACTIVE


def require_active(version: str) -> None:
    """Only v1 may select signals; anything else is refused (promotion is a code change after validation)."""
    if version != ACTIVE:
        raise ValueError(f"{version} is not the active scoring version ({ACTIVE}); promotion needs a validated code change")


def shadow_versions() -> list[str]:
    raw = os.environ.get("AUTODESK_SCORING_SHADOW")
    wanted = DEFAULT_SHADOW if raw is None else [x.strip() for x in raw.split(",") if x.strip()]
    return [v for v in wanted if v in VERSIONS and VERSIONS[v].status == "SHADOW"]


def v2_bars() -> int:
    try:
        n = int(os.environ.get("AUTODESK_V2_BARS", "500"))
    except ValueError:
        n = 500
    return max(60, min(n, 1000))


def describe() -> list[dict]:
    shadows = set(shadow_versions())
    out = []
    for v in VERSIONS.values():
        status = v.status
        if v.status == "SHADOW" and v.key not in shadows:
            status = "OFF"
        out.append({"version": v.key, "horizon": v.horizon, "status": status, "selects_signals": v.key == ACTIVE,
                    "description": v.description, "weights": {k: str(w) for k, w in v.weights.items()},
                    "validation": v.validation})
    return out


def get(version: str) -> Optional[Version]:
    return VERSIONS.get(version)
