"""Frozen research configuration — PRD §10.2, §30 and §30.1 (NI-2, approved 2026-09-21).

Single source of truth for every module in research/charting. Do not copy these numbers into other
files; import them. Changing a value changes the configuration hash and invalidates prior runs.
"""
from __future__ import annotations

import hashlib
import json

PROFILE_NAME = "PATTERN_CONFIRMATION_V1_RESEARCH"
ENGINE_VERSION = "0.1.0"

# Canonical single-symbol bar frame: one row per completed daily session, ascending by date, unique dates.
BARS_COLUMNS = ("date", "open", "high", "low", "close", "volume")

CONFIG: dict = {
    # PRD §10.2 / §30
    "timeframe": "1D",
    "swing_left_bars": 3,
    "swing_right_bars": 3,
    "atr_period": 14,
    "volume_baseline_bars": 20,
    "minimum_pattern_length": 15,
    "maximum_pattern_length": 120,
    "breakout_buffer_atr": 0.25,
    "relative_volume_supporting": 1.20,
    "relative_volume_strong": 1.50,
    "confirmation_window_bars": 3,
    "retest_window_bars": 5,
    "require_close_confirmation": True,
    "require_volume_confirmation": False,
    "require_market_alignment": False,
    "require_sector_alignment": False,
    "allow_intrabar_confirmation": False,
    "point_in_time_validation_required": True,
    # PRD §30.1 — NI-2 geometry predicates
    "flat_boundary_max_drift_atr": 0.50,
    "sloped_boundary_min_drift_atr": 0.75,
    "convergence_max_ratio": 0.70,
    "level_cluster_width_atr": 0.35,
    "level_min_touches": 3,
    "pattern_boundary_min_touches": 2,
    "touch_min_separation_bars": 3,
    "strength_touch_saturation": 5,
    "strength_recency_halflife_bars": 60,
    "strength_time_fraction": 0.25,
    "strength_weights": [0.30, 0.20, 0.20, 0.15, 0.15],
    "rectangle_min_range_atr": 1.50,
    "rectangle_max_range_atr": 8.00,
    "failure_buffer_atr": 0.25,
    "failure_window_bars": 5,
    "followthrough_max_atr_expansion": 2.00,
    "followthrough_min_rel_volume": 1.00,
    "followthrough_max_rel_volume": 4.00,
    "stability_refit_fraction": 0.70,
    "boundary_stability_max_shift_atr": 0.30,
    "boundary_max_residual_atr": 0.25,
    "relative_volume_band_convention": "half_open_lower_inclusive",
    # Relative-volume band edges (PRD §12.4, half-open [lower, upper))
    "relative_volume_weak_below": 0.80,
    "relative_volume_normal_below": 1.20,
    # PRD §34.5 early-formation score weights — illustrative starting weights, frozen here so they are covered
    # by config_hash; they must be pre-registered and never tuned after results are seen. Four scores are
    # reported separately (formation / readiness / confirmation / failure_risk) — never summed into one.
    "early_score_weights": {
        "structural_quality": 0.25,
        "volatility_compression": 0.20,
        "distance_to_trigger": 0.15,
        "volume_behaviour": 0.15,
        "momentum_relative_strength": 0.15,
        "market_sector_context": 0.10,
    },
    # PRD §34.7.1 offline maturity checkpoints (fractions of a COMPLETED pattern; t_end picks the bar, never the value)
    "early_maturity_checkpoints": [0.2, 0.4, 0.6, 0.8],
}


def config_hash(cfg: dict | None = None) -> str:
    """SHA-256 of the canonical JSON of a configuration (PRD §21 configuration_hash)."""
    payload = json.dumps(cfg if cfg is not None else CONFIG, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def relative_volume_band(rel_volume: float) -> str:
    """PRD §12.4 with the §30.1 half-open convention: Weak < 0.80 <= Normal < 1.20 <= Supporting < 1.50 <= Strong."""
    if rel_volume < CONFIG["relative_volume_weak_below"]:
        return "WEAK"
    if rel_volume < CONFIG["relative_volume_normal_below"]:
        return "NORMAL"
    if rel_volume < CONFIG["relative_volume_strong"]:
        return "SUPPORTING"
    return "STRONG"
