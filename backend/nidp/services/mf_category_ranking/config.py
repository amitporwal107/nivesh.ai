"""Weight configuration loader for mf_category_ranking.

Loads and validates the per-family weight + direction + threshold config
from weights.yaml (or an injected string for testing).

AC-14: raises ConfigurationError at load time if any family's weights
do not sum to 1.0 (±0.001).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import yaml

_DEFAULT_YAML = Path(__file__).parent / "weights.yaml"

# Tolerance for weight-sum validation (AC-14)
_WEIGHT_SUM_TOLERANCE = 0.001


class ConfigurationError(ValueError):
    """Raised when the weight config is structurally invalid."""


@dataclass
class FamilyConfig:
    """Resolved weight + direction config for one category family."""
    name: str
    weights: Dict[str, float]       # metric_name → weight (sum == 1.0)
    directions: Dict[str, str]      # metric_name → 'higher' | 'lower'

    def lower_is_better(self, metric: str) -> bool:
        return self.directions.get(metric, "higher") == "lower"


@dataclass
class RankingConfig:
    """Full resolved config used by the ranking engine."""
    families: Dict[str, FamilyConfig]   # family_name → FamilyConfig
    min_history_bars: int = 252
    min_peers: int = 8
    w_min: float = 0.60


def load_config(yaml_str: Optional[str] = None) -> RankingConfig:
    """Load and validate ranking config.

    Args:
        yaml_str: YAML text to parse.  If None, reads weights.yaml next to this file.

    Raises:
        ConfigurationError: if weights don't sum to 1.0 or required keys are missing.
    """
    if yaml_str is None:
        with open(_DEFAULT_YAML) as fh:
            yaml_str = fh.read()

    raw = yaml.safe_load(yaml_str)
    if not isinstance(raw, dict):
        raise ConfigurationError("Config must be a YAML mapping")

    thresholds = raw.get("thresholds", {})
    min_history_bars = int(thresholds.get("min_history_bars", 252))
    min_peers = int(thresholds.get("min_peers", 8))
    w_min = float(thresholds.get("w_min", 0.60))

    families_raw = raw.get("families") or {}
    families: Dict[str, FamilyConfig] = {}

    for family_name, fdata in families_raw.items():
        if not fdata:
            # Commented-out / null family — skip
            continue
        weights_raw = fdata.get("weights")
        if not weights_raw:
            raise ConfigurationError(f"Family '{family_name}' has no weights")
        directions_raw = fdata.get("directions", {})

        weights = {k: float(v) for k, v in weights_raw.items()}
        # Round to 6 decimal places to avoid floating-point accumulation noise
        # (e.g. 0.30 + 0.70 = 0.9999... in IEEE 754).
        total = round(sum(weights.values()), 6)
        if abs(total - 1.0) >= _WEIGHT_SUM_TOLERANCE:
            raise ConfigurationError(
                f"Family '{family_name}' weights sum to {total:.6f}, "
                f"expected 1.0 (±{_WEIGHT_SUM_TOLERANCE})"
            )

        directions = {k: str(v) for k, v in directions_raw.items()}
        # Validate direction values
        for metric, direction in directions.items():
            if direction not in ("higher", "lower"):
                raise ConfigurationError(
                    f"Family '{family_name}' metric '{metric}' "
                    f"has invalid direction '{direction}' — must be 'higher' or 'lower'"
                )

        families[family_name] = FamilyConfig(
            name=family_name,
            weights=weights,
            directions=directions,
        )

    return RankingConfig(
        families=families,
        min_history_bars=min_history_bars,
        min_peers=min_peers,
        w_min=w_min,
    )


def family_for_category(raw_category: str, config: RankingConfig) -> Optional[FamilyConfig]:
    """Derive the weight-config family from the raw AMFI scheme_category string.

    Maps prefix → family name:
      'Equity Scheme - ...'              → 'Equity'
      'Debt Scheme - ...'                → 'Debt'
      'Hybrid Scheme - ...'              → 'Hybrid'
      'Solution Oriented Scheme - ...'   → 'Solution'
      'Other Scheme - ...'               → 'Other'
      anything else                      → 'Other'

    Returns None if the derived family has no entry in config.families
    (meaning: emit insufficient_coverage for all funds in this category).
    """
    cat = (raw_category or "").strip()
    if cat.startswith("Equity"):
        family_name = "Equity"
    elif cat.startswith("Debt"):
        family_name = "Debt"
    elif cat.startswith("Hybrid"):
        family_name = "Hybrid"
    elif cat.startswith("Solution"):
        family_name = "Solution"
    else:
        family_name = "Other"

    return config.families.get(family_name)
