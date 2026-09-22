"""Frozen configuration for research/corporate_actions -- PRD §37.5.

Single source of truth: do not copy these numbers into other modules; import them.
Changing a value changes CONFIG_HASH (mirrors research.charting.config's config_hash()
pattern) so a downstream research run can tell whether it used the same corporate-action
rules as a prior run.
"""
from __future__ import annotations

import hashlib
import json

PROFILE_NAME = "CORPORATE_ACTIONS_V1"

CONFIG: dict = {
    # PRD §37.5: "Sessions T-5..T+5 are excluded from ordinary validation." Symmetric
    # window, measured in the symbol's own trading sessions (not calendar days).
    "regime_break_sessions_before": 5,
    "regime_break_sessions_after": 5,
    # Safety-net large-gap detector (task §1.c): flag |open / prev_close - 1| beyond this
    # threshold as a REVIEW candidate. 20% comfortably catches both known demergers
    # (SIEMENS -34.74%, ABFRL -51.85%) while staying above ordinary circuit-band moves
    # (5/10/20%) for most NSE series -- chosen as a reasonable safety-net default, not a
    # statistically fit value. A flag is never a confirmed demerger by itself.
    "large_gap_threshold_pct": 20.0,
    # A single-bar symbol has no "previous close" to gap from; nothing to flag.
    "gap_detector_min_bars": 2,
}


def config_hash(cfg: dict | None = None) -> str:
    """SHA-256 of the canonical JSON of a configuration (mirrors PRD §21 configuration_hash
    / research.charting.config.config_hash)."""
    payload = json.dumps(cfg if cfg is not None else CONFIG, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


CONFIG_HASH = config_hash()
