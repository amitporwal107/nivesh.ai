"""§34.5 "Early Pattern Score" — four independent scores, plus the six illustrative
components that feed `formation_score`.

docs/charting.md §34.5 requires the system to "display four separate values and must not
combine them into one opaque score": `formation_score`, `readiness_score`,
`confirmation_score`, `failure_risk`. This module computes all four from genuinely
different raw inputs — no one of them is derived from another's already-computed number —
and reserves `CONFIG["early_score_weights"]` for the one place §34.5 itself calls for a
weighted combination: the six-component table ("Structural quality 25% / Volatility
compression 20% / Distance to trigger 15% / Volume behaviour 15% / Momentum and relative
strength 15% / Market and sector context 10%") that §34.5's opening line calls "The
[Early Pattern] Score" — implemented here as `formation_score`, since its components
("how well the structure is developing") match `formation_score`'s own definition
("How well the structure is developing") most directly of the four. `readiness_score`,
`confirmation_score` and `failure_risk` are computed by their own independent formulas
below, not by re-weighting the same six components.

Component 6, "Market and sector context", needed a benchmark/sector-index feed that did
not exist in this repo when this module was first written; it always reported
`ScoreValue(None, "UNAVAILABLE")`. `research/charting/context.py` (CHART-S29/S30/T09) now
exists, and `_market_sector_context` below wires to its public `get_context()` query —
see that function's own docstring for the market-only scope (this package has no
per-symbol universe to build a sector index from) and the sign convention. The component
is STILL honestly `ScoreValue(None, "UNAVAILABLE")` whenever `context.py` itself reports
unavailable for either date it needs — most notably the sealed 2023-01-01..2024-07-31
out-of-sample block, which must propagate through here exactly as it does in `context.py`,
never silently substituted with a neutral value. `formation_score`'s weighted aggregate
renormalises over whichever components ARE available (see `_aggregate_formation_score`)
rather than silently treating an unavailable component's weight as zero.

Point-in-time contract: `compute_early_scores(bars, t, ...)` truncates to
`bars.iloc[:t+1]` FIRST (mirroring `swings.swings_as_of`'s own documented contract) and
every downstream computation — swings, ATR, relative volume, momentum, range compression —
runs on that physically-truncated view alone, never on `bars` itself. This is what makes
the poisoned-future probe in `tests/test_early_lookahead.py` meaningful: nothing computed
here can depend on a bar after `t` regardless of any subtlety in how a helper is
implemented, because that bar is not present in the frame at all by the time any helper is
called.

v1 indicator scale note: §34's own worked context is a pattern with
`minimum_pattern_length = 15` bars (CONFIG). The standard institutional indicator periods
used elsewhere in this repo (RSI-14, MACD 12/26/9, a 90-bar long-run volatility baseline)
would never finish warming up inside a typical early-formation window. This module
therefore uses its own, smaller, explicitly local periods for the early-stage momentum and
compression reads below (`_SHORT_RANGE_PERIOD` etc.) — a documented v1 choice distinct from
(and not a redefinition of) any frozen `CONFIG` value.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from research.charting import context
from research.charting.config import CONFIG, config_hash
from research.charting.geometry import cluster_pivots_into_levels, level_strength, ols_slope
from research.charting.series import atr, momentum_slope, range_compression, relative_volume
from research.charting.swings import find_swings

from .indicators import (
    bb_width_compression_as_of,
    failed_breakout_attempts_as_of,
    sr_stability_as_of,
    structure_direction_as_of,
    volume_accumulation_as_of,
)

Direction = Literal["BULLISH", "BEARISH"]
ScoreStatus = Literal["OK", "UNAVAILABLE", "INSUFFICIENT_DATA", "NOT_YET_TRIGGERED"]

EARLY_SCORE_CALC_VERSION = "0.1.0"

# v1 early-stage indicator periods — see module docstring. Deliberately NOT the CONFIG
# defaults (atr_period=14, MACD 12/26/9, volume_baseline_bars=20): those are tuned for
# confirmed-pattern-scale windows, not for scoring a structure that may be as young as
# `minimum_pattern_length` (15) bars.
_EP = CONFIG["early_params"]  # every value below is frozen in config.py and covered by config_hash
_SHORT_RANGE_PERIOD = _EP["short_range_period"]
_LONG_RANGE_PERIOD = _EP["long_range_period"]
_VOLUME_BASELINE_BARS = _EP["volume_baseline_bars"]
_MOMENTUM_K = _EP["momentum_k"]
_MOMENTUM_RSI_PERIOD = _EP["momentum_rsi_period"]
_MOMENTUM_MACD_FAST = _EP["momentum_macd_fast"]
_MOMENTUM_MACD_SLOW = _EP["momentum_macd_slow"]
_MOMENTUM_MACD_SIGNAL = _EP["momentum_macd_signal"]
_READINESS_TREND_BARS = _EP["readiness_trend_bars"]
_READINESS_SLOPE_SCALE = _EP["readiness_slope_scale"]

# v1 local window/scale for `_market_sector_context` (mirrors `_LONG_RANGE_PERIOD`'s 15-bar
# scale and `_DISTANCE_SCALE_ATR`'s "documented v1 constant, not PRD-frozen" convention): the
# market index's own return is read over this many bars, ending at the pattern's as-of bar.
_MARKET_CONTEXT_LOOKBACK_BARS = _EP["market_context_lookback_bars"]
# A market move of this magnitude (5%) over that window maps to the full +-1.0 alignment
# swing before the 0..1 rescale -- ordinary index volatility over ~15 sessions is a
# fraction of this, an outsized move saturates the score rather than exploding past [0, 1].
_MARKET_CONTEXT_RETURN_SCALE = _EP["market_context_return_scale"]

# v1 sub-weights blending `_structural_quality`'s four §34.4 inputs (level_strength,
# structure_direction/higher-lows-lower-highs, boundary_stability, failed_breakout_attempts)
# into that one §34.5 component. Not PRD-frozen — an internal composition choice within the
# "Structural quality" component analogous to how CONFIG["strength_weights"] blends
# `level_strength`'s own five sub-components; renormalised over whichever of the four are
# actually available (see `_structural_quality`), exactly like `_aggregate_formation_score`
# renormalises across the six §34.5 components themselves.
_STRUCTURAL_SUBWEIGHTS = dict(_EP["structural_subweights"])

# Distance-to-trigger / invalidation are mapped to [0, 1] over this many ATRs. A
# documented v1 scale constant, not a PRD-frozen value: at 0 ATR away the score is 1.0,
# at >= this many ATRs away (or beyond) it is 0.0.
_DISTANCE_SCALE_ATR = _EP["distance_scale_atr"]
# The 60/40 blend used by three components (range vs BB width, contraction vs accumulation, distance vs tightening).
_BLEND_PRIMARY, _BLEND_SECONDARY = _EP["component_blend"]
_FAILURE_PROXIMITY_WEIGHT, _FAILURE_EXPANSION_WEIGHT = _EP["failure_risk_blend"]

@dataclass(frozen=True)
class ScoreValue:
    """One score or component, always paired with an honest status. `status="UNAVAILABLE"`
    (market/sector context) and `status="INSUFFICIENT_DATA"` (not enough warmup yet) are
    real, displayed states — never silently rendered as a fabricated 0.0 or 0.5. `value` is
    `None` whenever `status != "OK"`."""

    value: float | None
    status: ScoreStatus

    def to_dict(self) -> dict:
        return {"value": self.value, "status": self.status}


_UNAVAILABLE = ScoreValue(None, "UNAVAILABLE")
_INSUFFICIENT = ScoreValue(None, "INSUFFICIENT_DATA")


def _clip01(x: float) -> float:
    return float(np.clip(x, 0.0, 1.0))


# ── the six §34.5 components ─────────────────────────────────────────────────


def _structural_quality(view: pd.DataFrame, atr_now: float | None, direction: Direction, cfg: dict) -> ScoreValue:
    """§34.5 "Structural quality". Blends four §34.4 inputs, all describing "how well the
    structure is developing" per §34.3's own grouping ("emerging support/resistance ...
    higher lows, lower highs and improving structure"):

    - `level_strength` (NI-2, already a 5-component [0,1] descriptive score) for whichever
      resistance/support level currently has the most confirmed touches, averaged across
      both sides — "how many good touches does this level have".
    - `structure_direction` (§34.4 "Higher lows / lower highs", `early.indicators`) — is the
      opposite-side pivot sequence (support pivots for a BULLISH candidate, resistance
      pivots for BEARISH) actually trending the way the pattern's direction needs.
    - `sr_stability` (§34.4 "Support/resistance stability", `early.indicators`, wrapping the
      previously-unused NI-2 #7 `geometry.boundary_stability`) — has the level's own PRICE
      held still under a refit, a different question from touch count.
    - `failed_breakout_attempts` (§34.4 "Failed breakout attempts", `early.indicators`) —
      count of intrabar piercings of either boundary that closed back inside.

    Requires at least one confirmed pivot to say anything at all; a genuinely one-sided
    structure (a level on only one side) is a real 0.0 reading, not a missing one. The four
    sub-signals are renormalised over whichever are actually available (`_STRUCTURAL_SUBWEIGHTS`),
    exactly like `_aggregate_formation_score` renormalises across the six §34.5 components."""
    if atr_now is None or not np.isfinite(atr_now) or atr_now <= 0:
        return _INSUFFICIENT
    pivots = find_swings(view)
    if not pivots:
        return _INSUFFICIENT
    highs = cluster_pivots_into_levels(pivots, view, atr_now, cfg, kind="HIGH")
    lows = cluster_pivots_into_levels(pivots, view, atr_now, cfg, kind="LOW")
    if not highs or not lows:
        return ScoreValue(0.0, "OK")

    t = len(view) - 1
    rel_vol = relative_volume(view, n=_VOLUME_BASELINE_BARS)
    best_high = max(highs, key=lambda l: len(l.touches))
    best_low = max(lows, key=lambda l: len(l.touches))
    window_start = min(
        min(tt.pivot_index for tt in best_high.touches),
        min(tt.pivot_index for tt in best_low.touches),
    )
    strengths = [
        level_strength(
            lvl, as_of_index=t, window_start=window_start, window_end=t,
            bars=view, relative_volume=rel_vol, atr=atr_now, cfg=cfg,
        ).level_strength
        for lvl in (best_high, best_low)
    ]
    sub_values = {"level_strength": _clip01(float(np.mean(strengths)))}

    structure = structure_direction_as_of(view, t, direction, atr_now, cfg)
    if structure.score is not None:
        sub_values["structure_direction"] = structure.score

    stability = sr_stability_as_of(view, t, atr_now, cfg)
    if stability.score is not None:
        sub_values["boundary_stability"] = stability.score

    failed_high = failed_breakout_attempts_as_of(view, t, best_high.price, "HIGH", atr_now, window_start, cfg)
    failed_low = failed_breakout_attempts_as_of(view, t, best_low.price, "LOW", atr_now, window_start, cfg)
    failed_scores = [f.score for f in (failed_high, failed_low) if f.score is not None]
    if failed_scores:
        sub_values["failed_breakouts"] = float(np.mean(failed_scores))

    weight_mass = sum(_STRUCTURAL_SUBWEIGHTS[k] for k in sub_values)
    value = sum(_STRUCTURAL_SUBWEIGHTS[k] * v for k, v in sub_values.items()) / weight_mass
    return ScoreValue(_clip01(value), "OK")


def _volatility_compression(view: pd.DataFrame, cfg: dict) -> ScoreValue:
    """§34.5 "Volatility compression" / §34.4 "Range compression" + "Bollinger Band Width".
    `atr_ratio`/`range_ratio` < 1 means the recent range is quieter than the stock's own
    longer history (compression); mapped so quieter -> higher score. Blended (60/40) with
    `early.indicators.bb_width_compression_as_of`'s own trailing-percentile read of
    `series.bb_width_percentile` whenever that indicator has enough warmup (v1 local periods
    need 24 bars — see `indicators.py`); falls back to the range/ATR-only reading alone
    otherwise, so a young pattern is never penalised for BB's longer warmup."""
    rc = range_compression(view, short_period=_SHORT_RANGE_PERIOD, long_period=_LONG_RANGE_PERIOD)
    atr_ratio = float(rc["atr_ratio"].iloc[-1])
    range_ratio = float(rc["range_ratio"].iloc[-1])
    candidates = [v for v in (atr_ratio, range_ratio) if np.isfinite(v)]
    if not candidates:
        return _INSUFFICIENT
    range_atr_score = _clip01(1.0 - float(np.mean(candidates)))

    bb = bb_width_compression_as_of(view, len(view) - 1)
    if bb.score is not None:
        return ScoreValue(_clip01(_BLEND_PRIMARY * range_atr_score + _BLEND_SECONDARY * bb.score), "OK")
    return ScoreValue(range_atr_score, "OK")


def _distance_to_trigger(view: pd.DataFrame, atr_now: float | None, trigger_level: float | None) -> ScoreValue:
    """§34.5 "Distance to trigger" / §34.4 "Distance to breakout level": normalised ATR
    distance from the LATEST close (bar `t` of the truncated view — never any later bar) to
    the trigger. Closer -> higher score."""
    if atr_now is None or not np.isfinite(atr_now) or atr_now <= 0 or trigger_level is None:
        return _INSUFFICIENT
    close_now = float(view["close"].iloc[-1])
    dist_atr = abs(trigger_level - close_now) / atr_now
    return ScoreValue(_clip01(1.0 - dist_atr / _DISTANCE_SCALE_ATR), "OK")


def _volume_behaviour(view: pd.DataFrame) -> ScoreValue:
    """§34.5 "Volume behaviour" / §34.4 "Volume contraction" + "Volume accumulation":
    below-baseline participation at the latest bar scores higher (quiet consolidation is the
    sought signal), blended (60/40) with `early.indicators.volume_accumulation_as_of`'s
    trailing OLS slope of relative volume — a *gradual increase* heading into `t`, a
    different time-scale from the latest-bar snapshot ratio and not contradictory with it
    (the textbook shape is an overall-quiet baseline with a gentle recent uptick)."""
    rv = relative_volume(view, n=_VOLUME_BASELINE_BARS)
    latest = float(rv.iloc[-1])
    if not np.isfinite(latest):
        return _INSUFFICIENT
    contraction_score = _clip01(1.0 - latest)

    accumulation = volume_accumulation_as_of(view, len(view) - 1, n=_VOLUME_BASELINE_BARS)
    if accumulation.score is not None:
        return ScoreValue(_clip01(_BLEND_PRIMARY * contraction_score + _BLEND_SECONDARY * accumulation.score), "OK")
    return ScoreValue(contraction_score, "OK")


def _momentum_relative_strength(view: pd.DataFrame, direction: Direction) -> ScoreValue:
    """§34.5 "Momentum and relative strength". Self-referential only (RSI slope, MACD
    histogram slope, both from §34.4) — NOT stock-vs-benchmark relative strength, which
    needs the same index/sector feed as component 6 and is therefore folded into
    `market_sector_context` (UNAVAILABLE) instead of fabricated here. 0.5 = neutral;
    > 0.5 favours the pattern's stated `direction`, < 0.5 opposes it."""
    ms = momentum_slope(
        view, k=_MOMENTUM_K, rsi_period=_MOMENTUM_RSI_PERIOD,
        macd_fast=_MOMENTUM_MACD_FAST, macd_slow=_MOMENTUM_MACD_SLOW, macd_signal=_MOMENTUM_MACD_SIGNAL,
    )
    rsi_slope = float(ms["rsi_slope"].iloc[-1])
    macd_hist_slope = float(ms["macd_hist_slope"].iloc[-1])
    if not np.isfinite(rsi_slope):
        return _INSUFFICIENT

    sign = 1.0 if direction == "BULLISH" else -1.0
    rsi_component = float(np.clip((sign * rsi_slope) / 40.0, -1.0, 1.0))
    if np.isfinite(macd_hist_slope) and macd_hist_slope != 0.0:
        macd_agree = 1.0 if (sign * macd_hist_slope) > 0 else -1.0
        raw = 0.7 * rsi_component + 0.3 * macd_agree
    else:
        raw = rsi_component
    return ScoreValue(_clip01((raw + 1.0) / 2.0), "OK")


def _market_sector_context(view: pd.DataFrame, direction: Direction) -> ScoreValue:
    """§34.5 "Market and sector context" / §34.4 #8 "Relative strength" + #12 "Market/sector
    alignment". Reads `context.get_context()` (CHART-S29/S30/T09) for the pattern's own
    as-of bar — `view["date"].iloc[-1]`, the LAST row of the already-truncated `view` (never
    `pandas.Timestamp.now()`/wall-clock "today", and never a date from the untruncated
    `bars` beyond `t` — the point-in-time contract this whole module documents) — and again
    `_MARKET_CONTEXT_LOOKBACK_BARS` bars earlier in that SAME view, to read the NIFTY 500
    market index's own short-term return over that window. A market move in the pattern's
    stated `direction` scores above 0.5 (tailwind), a move against it scores below
    (headwind), 0.5 = flat — the same direction-alignment convention as
    `_momentum_relative_strength`, just applied to the index instead of the stock itself.

    No `symbol`/`sector` is passed to `context.get_context()`: this package has no
    per-symbol universe of bars to build a sector index from (`context.py`'s own "Universe
    boundary" note — that assembly needs a specific pattern's full universe, which this call
    site does not have). The sector half of `get_context()`'s result is therefore always
    unresolved here; this component is a MARKET-only reading of §34.4 #8/#12 for now — an
    honestly narrower scope than the PRD's full sector-relative-strength ask, not a
    fabricated sector number. Wiring the sector half in is a separate ticket's job once a
    universe of per-symbol bars is available at this call site.

    Two independent `context.get_context()` calls, each with `market_df=None` (its own
    default): NOT pre-loaded once and shared, so that a sealed-gap date is short-circuited
    by `context.py` itself before any real file is touched (see `context.py`'s own
    "defense in depth" contract on `market_value_at`) — this function never loads the market
    index file directly.

    UNAVAILABLE (not INSUFFICIENT_DATA) whenever `context.py` itself reports unavailable for
    EITHER date — most notably the sealed 2023-01-01..2024-07-31 out-of-sample block, which
    must propagate through unchanged, never silently substituted with a neutral 0.5.
    INSUFFICIENT_DATA only for the genuinely different, local reason that `view` itself does
    not yet have `_MARKET_CONTEXT_LOOKBACK_BARS + 1` bars to look back over.
    """
    if len(view) <= _MARKET_CONTEXT_LOOKBACK_BARS:
        return _INSUFFICIENT

    now_date = view["date"].iloc[-1]
    lookback_date = view["date"].iloc[-1 - _MARKET_CONTEXT_LOOKBACK_BARS]

    now_ctx = context.get_context(now_date)
    lookback_ctx = context.get_context(lookback_date)

    if now_ctx.market.status != context.STATUS_OK or lookback_ctx.market.status != context.STATUS_OK:
        return _UNAVAILABLE

    close_now = now_ctx.market.close
    close_before = lookback_ctx.market.close
    if close_before in (None, 0) or not np.isfinite(close_before) or not np.isfinite(close_now):
        return _UNAVAILABLE

    market_return = (close_now - close_before) / close_before
    sign = 1.0 if direction == "BULLISH" else -1.0
    aligned = float(np.clip((sign * market_return) / _MARKET_CONTEXT_RETURN_SCALE, -1.0, 1.0))
    return ScoreValue(_clip01(0.5 + 0.5 * aligned), "OK")


def _components(view: pd.DataFrame, atr_now: float | None, trigger_level: float | None, direction: Direction, cfg: dict) -> dict[str, ScoreValue]:
    return {
        "structural_quality": _structural_quality(view, atr_now, direction, cfg),
        "volatility_compression": _volatility_compression(view, cfg),
        "distance_to_trigger": _distance_to_trigger(view, atr_now, trigger_level),
        "volume_behaviour": _volume_behaviour(view),
        "momentum_relative_strength": _momentum_relative_strength(view, direction),
        "market_sector_context": _market_sector_context(view, direction),
    }


def _aggregate_formation_score(components: dict[str, ScoreValue], cfg: dict) -> tuple[ScoreValue, dict[str, float]]:
    """§34.5's weighted composite, using `CONFIG["early_score_weights"]` verbatim
    (imported, never redefined). Renormalises over whichever components have
    `status == "OK"` so an unavailable/insufficient component reduces the weight mass
    actually used instead of being silently treated as a zero contribution."""
    raw_weights = cfg["early_score_weights"]
    available = {k: v for k, v in components.items() if v.status == "OK" and v.value is not None}
    if not available:
        return _INSUFFICIENT, {}
    weight_mass = sum(raw_weights[k] for k in available)
    if weight_mass <= 0:
        return _INSUFFICIENT, {}
    weights_used = {k: raw_weights[k] / weight_mass for k in available}
    value = sum(weights_used[k] * available[k].value for k in available)
    return ScoreValue(_clip01(value), "OK"), weights_used


def _readiness_score(view: pd.DataFrame, distance_component: ScoreValue, cfg: dict) -> ScoreValue:
    """§34.5 "readiness_score — how close the pattern is to a possible resolution".
    Independent formula (not formation_score's weighted composite): distance-to-trigger
    plus whether the range is still actively tightening (OLS slope of the trailing
    `atr_ratio` — reusing `geometry.ols_slope`, a generic drift-fit helper, not a
    pattern-specific one) over the last `_READINESS_TREND_BARS` valid bars."""
    if distance_component.status != "OK" or distance_component.value is None:
        return _INSUFFICIENT

    rc = range_compression(view, short_period=_SHORT_RANGE_PERIOD, long_period=_LONG_RANGE_PERIOD)
    trail = rc["atr_ratio"].tail(_READINESS_TREND_BARS).dropna()
    if len(trail) < 2:
        return ScoreValue(distance_component.value, "OK")

    slope = ols_slope(list(range(len(trail))), trail.tolist())
    tightening = float(np.clip(-slope * _READINESS_SLOPE_SCALE, -1.0, 1.0))  # shrinking ratio (slope<0) -> tightening>0
    tightening_score = (tightening + 1.0) / 2.0
    return ScoreValue(_clip01(_BLEND_PRIMARY * distance_component.value + _BLEND_SECONDARY * tightening_score), "OK")


def _confirmation_score(view: pd.DataFrame, trigger_level: float | None, direction: Direction, cfg: dict) -> ScoreValue:
    """§34.5 "confirmation_score — strength of evidence after the boundary is crossed".
    Stage 1-3 records are, by definition, mostly pre-trigger: `0.0` with the honest
    `NOT_YET_TRIGGERED` status (not a fabricated "no evidence yet" number indistinguishable
    from a genuinely weak post-cross score) until the latest close has actually crossed
    `trigger_level` in the pattern's stated `direction`. Once crossed, scored from
    follow-through evidence available at `t` alone: relative volume and ATR expansion."""
    if trigger_level is None:
        return _INSUFFICIENT
    close_now = float(view["close"].iloc[-1])
    crossed = close_now >= trigger_level if direction == "BULLISH" else close_now <= trigger_level
    if not crossed:
        return ScoreValue(0.0, "NOT_YET_TRIGGERED")

    rv = float(relative_volume(view, n=_VOLUME_BASELINE_BARS).iloc[-1])
    rc = float(range_compression(view, short_period=_SHORT_RANGE_PERIOD, long_period=_LONG_RANGE_PERIOD)["atr_ratio"].iloc[-1])
    parts = []
    if np.isfinite(rv):
        parts.append(_clip01(rv / cfg["relative_volume_strong"]))
    if np.isfinite(rc):
        parts.append(_clip01(rc))  # expansion right after a breakout is expected follow-through evidence
    if not parts:
        return _INSUFFICIENT
    return ScoreValue(_clip01(float(np.mean(parts))), "OK")


def _failure_risk(view: pd.DataFrame, atr_now: float | None, invalidation_level: float | None, cfg: dict) -> ScoreValue:
    """§34.5 "failure_risk — evidence of invalidation, rejection or structural
    deterioration". Independent formula: proximity to the invalidation level (ATR-normalised,
    same scale as distance_to_trigger but the OPPOSITE boundary) plus premature ATR expansion
    (§34.4 "ATR expansion risk — whether volatility is beginning to expand prematurely")."""
    if atr_now is None or not np.isfinite(atr_now) or atr_now <= 0 or invalidation_level is None:
        return _INSUFFICIENT
    close_now = float(view["close"].iloc[-1])
    dist_atr = abs(close_now - invalidation_level) / atr_now
    proximity_risk = _clip01(1.0 - dist_atr / _DISTANCE_SCALE_ATR)

    rc = float(range_compression(view, short_period=_SHORT_RANGE_PERIOD, long_period=_LONG_RANGE_PERIOD)["atr_ratio"].iloc[-1])
    expansion_risk = _clip01(rc - 1.0) if np.isfinite(rc) else 0.0

    return ScoreValue(_clip01(_FAILURE_PROXIMITY_WEIGHT * proximity_risk + _FAILURE_EXPANSION_WEIGHT * expansion_risk), "OK")


@dataclass(frozen=True)
class EarlyScores:
    """§34.5's four independently-stored, independently-displayed values, plus the
    six-component breakdown and weights behind `formation_score` (PRD §16: "the weights,
    thresholds, component values and calculation version must all be stored with any
    score"). No field here is a fifth "combined"/"composite" score across the four —
    that is exactly what §34.9 AC3 forbids."""

    as_of_index: int
    as_of_date: pd.Timestamp
    formation_score: ScoreValue
    readiness_score: ScoreValue
    confirmation_score: ScoreValue
    failure_risk: ScoreValue
    components: dict[str, ScoreValue]
    weights_used: dict[str, float]
    raw_weights: dict[str, float]
    calculation_version: str
    config_hash: str

    def to_dict(self) -> dict:
        return {
            "as_of_index": self.as_of_index,
            "as_of_date": self.as_of_date.isoformat(),
            "formation_score": self.formation_score.to_dict(),
            "readiness_score": self.readiness_score.to_dict(),
            "confirmation_score": self.confirmation_score.to_dict(),
            "failure_risk": self.failure_risk.to_dict(),
            "components": {k: v.to_dict() for k, v in self.components.items()},
            "weights_used": dict(self.weights_used),
            "raw_weights": dict(self.raw_weights),
            "calculation_version": self.calculation_version,
            "config_hash": self.config_hash,
        }


def compute_early_scores(
    bars: pd.DataFrame,
    t: int,
    *,
    trigger_level: float,
    invalidation_level: float,
    direction: Direction,
    cfg: dict = CONFIG,
) -> EarlyScores:
    """§34.5 entry point. Truncates `bars` to `bars.iloc[:t+1]` FIRST (PIT contract — see
    module docstring) and computes every score/component from that slice alone.
    `trigger_level`/`invalidation_level` are caller-supplied (mirroring `geometry.py`'s own
    convention of taking levels/window bounds as parameters rather than rediscovering them
    internally) — this function scores a candidate, it does not detect one; see
    `records.find_range_candidate_as_of` for detection.
    """
    if t < 0 or t >= len(bars):
        raise ValueError(f"t={t} out of range for bars of length {len(bars)}")
    if direction not in ("BULLISH", "BEARISH"):
        raise ValueError(f"direction must be 'BULLISH' or 'BEARISH', got {direction!r}")

    view = bars.iloc[: t + 1].reset_index(drop=True)
    atr_series = atr(view, period=cfg["atr_period"])
    atr_last = float(atr_series.iloc[-1])
    atr_now = atr_last if np.isfinite(atr_last) else None

    components = _components(view, atr_now, trigger_level, direction, cfg)
    formation_score, weights_used = _aggregate_formation_score(components, cfg)
    readiness_score = _readiness_score(view, components["distance_to_trigger"], cfg)
    confirmation_score = _confirmation_score(view, trigger_level, direction, cfg)
    failure_risk = _failure_risk(view, atr_now, invalidation_level, cfg)

    return EarlyScores(
        as_of_index=t,
        as_of_date=pd.Timestamp(view["date"].iloc[-1]),
        formation_score=formation_score,
        readiness_score=readiness_score,
        confirmation_score=confirmation_score,
        failure_risk=failure_risk,
        components=components,
        weights_used=weights_used,
        raw_weights=dict(cfg["early_score_weights"]),
        calculation_version=EARLY_SCORE_CALC_VERSION,
        config_hash=config_hash(cfg),
    )
