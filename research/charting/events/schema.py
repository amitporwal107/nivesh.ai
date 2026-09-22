"""Constants, version stamps and small pure helpers shared by every module in
`research.charting.events` -- the historical pattern event dataset (docs/charting.md §35.2
"Historical event dataset" / "Versioning", §36 Amendment B, cost PRD
`.claude/workspace/charting-pattern-engine/prd-transaction-cost-tax-v1.md` §18/§21/§22/§26-§30).

Single source of truth for this package's own schema/dataset version and every default this
package chooses on the caller's behalf (notional, exchange, segment, brokerage/statutory/tax
rule ids, the sealed-segment date boundaries) -- nothing here is duplicated in another module.
"""
from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Any, Optional

import pandas as pd

from research.charting.research_window import SEALED_GAP_END, SEALED_GAP_START
from research.costs.rule_loader import load_rule_file

# -- This package's own dataset schema version (PRD S30 dataset_version) --
# Bumped 1 -> 2 (docs/charting.md S37, Amendment C, 2026-09-22): the old bare hit_high_N /
# hit_close_N labels are REMOVED from the row (replaced by the S37.2/S37.3 target/stop/R
# framework in `stops.py`); every row also gains `stop`, `targets`, `tradability` and `action`.
EVENTS_SCHEMA_VERSION = 2

# -- S35.2 forward horizons (sessions) and S18.2/S35.2 bars-to-target percentages --
HORIZONS: tuple[int, ...] = (1, 3, 5, 10, 20)
BARS_TO_TARGET_PCTS: tuple[float, ...] = (0.02, 0.05, 0.10, 0.15)

# -- S37.2 owner decision baseline: research targets ("+2%, +3%, +5%, +10% from entry, plus
# R-multiple targets 1R, 1.5R, 2R, 3R") -- see `stops.py` for how these are turned into prices
# and walked against the S37.3 stop. Kept here alongside this package's other frozen constants
# (HORIZONS/BARS_TO_TARGET_PCTS above), for the same reason: one place, imported everywhere.
TARGET_PCTS: tuple[float, ...] = (0.02, 0.03, 0.05, 0.10)
R_MULTIPLES: tuple[float, ...] = (1.0, 1.5, 2.0, 3.0)

# -- S37.3 Layer 2 minimum stop distance ("at least 0.75 x ATR(14) below entry"). NOT a CONFIG
# key: this package never edits `config.py` (owned by other agents right now), and the owner's
# 2026-09-22 chat decision was never folded into the frozen S30 CONFIG dict in the first place --
# so it lives here, the same way HORIZONS/BARS_TO_TARGET_PCTS above are this package's OWN
# frozen constants rather than CONFIG entries.
LAYER2_MIN_STOP_DISTANCE_ATR = 0.75

# -- S37.4 bearish-pattern tradability/action labels (cash-only long portfolio) --
TRADABILITY_LONG_ACTIONABLE = "LONG_ACTIONABLE"
TRADABILITY_INFORMATIONAL = "INFORMATIONAL"
ACTION_CONSIDER_LONG = "CONSIDER_LONG"
ACTION_AVOID_NEW_LONG = "AVOID_NEW_LONG"


def tradability_and_action(direction: str) -> tuple[str, str]:
    """(tradability, action) for a row's own `direction` -- S37.4: "Detected, displayed and
    validated, but tradability = INFORMATIONAL and action = AVOID_NEW_LONG for the cash-only
    long portfolio" for anything that is not BULLISH. BULLISH is the only long-actionable
    case; a pattern family never actually confirms NEUTRAL (see `stops.py` module docstring),
    but this stays a safe, explicit fallback rather than assuming BULLISH-shaped behaviour for
    an unrecognised direction."""
    if direction == "BULLISH":
        return TRADABILITY_LONG_ACTIONABLE, ACTION_CONSIDER_LONG
    return TRADABILITY_INFORMATIONAL, ACTION_AVOID_NEW_LONG

# -- S36 / cost PRD S21-S22 defaults ("statutory path", "default Zerodha delivery = 0") --
DEFAULT_NOTIONAL_INR = Decimal("100000")
DEFAULT_EXCHANGE = "NSE"
DEFAULT_SEGMENT = "delivery"
DEFAULT_STATUTORY_RULE_ID = "nse-equity-statutory-v1"
DEFAULT_TAX_RULE_ID = "tax-equity-v1"
# "Zerodha delivery = 0": zerodha-equity-v1.json's own delivery profile has brokerage_pct "0"
# with no cap -- reproduced here as a research.costs.brokerage "percentage" spec (0%, no cap)
# so the *statutory* cost path is exercised (independently versioned rates), not the bundled
# legacy snapshot. Configurable: pass a different spec to CostConfig.brokerage_spec.
DEFAULT_BROKERAGE_SPEC: dict = {"type": "percentage", "pct": "0", "cap_inr": None}
DEFAULT_DP_BROKER = "zerodha"

# -- S35 / task brief: two development segments, never straddling the sealed block --
SEGMENT_PRE_SEALED = "pre_sealed"
SEGMENT_POST_SEALED = "post_sealed"
SEGMENTS = (SEGMENT_PRE_SEALED, SEGMENT_POST_SEALED)
# pre_sealed: bars <= 2022-12-31.  post_sealed: bars >= 2024-08-01 (fresh history; the sealed
# block itself, 2023-01-01..2024-07-31, is never a valid bound for either segment).
SEGMENT_MAX_DATE = {SEGMENT_PRE_SEALED: SEALED_GAP_START - pd.Timedelta(days=1)}
SEGMENT_MIN_DATE = {SEGMENT_POST_SEALED: SEALED_GAP_END + pd.Timedelta(days=1)}


def iso_date(d: Any) -> str:
    return pd.Timestamp(d).date().isoformat()


@lru_cache(maxsize=4)
def default_liquidity_buckets() -> tuple:
    """The liquidity-bucket slippage table this codebase already ships
    (`zerodha-equity-v1.json`'s `slippage_per_side_pct.buckets`) -- the one liquidity-bucket
    model already established in `research/costs/slippage.py`'s own docstring, loaded once and
    cached rather than hand-copied so a future edit to that file is picked up automatically.
    Returns a tuple of (min_value20_inr, pct) Decimal pairs, the shape
    `research.costs.slippage.liquidity_bucket_pct` expects.
    """
    rs = load_rule_file("zerodha-equity-v1")
    buckets = rs["slippage_per_side_pct"]["buckets"]
    return tuple((Decimal(b["min_value20_inr"]), Decimal(b["pct"])) for b in buckets)


# -- "The level broken" (task item 1) -- NOT a uniform key across pattern families --
#
# Verified against patterns.py directly (2026-09-22):
#   RECTANGLE            levels = {"support", "resistance", "breakout_level", "invalidation_level"}
#                         -- "breakout_level" already holds the actually-broken level for BOTH
#                         directions (`_walk_rectangle_lifecycle`: confirm_breakout_level is set
#                         to the resistance-side trigger on a BULLISH confirm and to the
#                         support-side trigger on a BEARISH confirm).
#   SUPPORT_RESISTANCE   levels = {"level", "kind", "breakout_level" XOR "breakdown_level"}
#                         -- the confirmed trigger is keyed "breakout_level" for BULLISH
#                         (resistance broken) and "breakdown_level" for BEARISH (support broken).
#   HH_HL                levels = {"prior_high", "prior_low"} -- no breakout_level/breakdown_level
#                         key at all; the broken level is "prior_high" for BULLISH,
#                         "prior_low" for BEARISH.
#
# `level_broken()` below is the one place this mapping is encoded, so a future pattern family
# just adds one more explicit branch -- it is never guessed for an unrecognised family (returns
# (None, None) instead, so the event row is never silently wrong).
_LEVEL_FIELD_BY_FAMILY = {
    "RECTANGLE": {"BULLISH": "breakout_level", "BEARISH": "breakout_level"},
    "SUPPORT_RESISTANCE": {"BULLISH": "breakout_level", "BEARISH": "breakdown_level"},
    "HH_HL": {"BULLISH": "prior_high", "BEARISH": "prior_low"},
}


def level_broken(pattern_type: str, direction: str, levels: dict) -> tuple[Optional[float], Optional[str]]:
    """(level_value, level_field_name) for the level a PRICE_CONFIRMED snapshot broke, per the
    per-family mapping above. `(None, None)` for an unrecognised family/direction combination or
    a missing key -- never a guessed number."""
    field_by_dir = _LEVEL_FIELD_BY_FAMILY.get(pattern_type)
    if field_by_dir is None:
        return None, None
    field = field_by_dir.get(direction)
    if field is None:
        return None, None
    value = levels.get(field)
    if value is None:
        return None, None
    return float(value), field
