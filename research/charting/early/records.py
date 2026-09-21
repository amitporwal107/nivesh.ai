"""Stage 1-3 early-formation records — §34.2/§34.3.

§34.2: "Stage 1-3 detections are not eligible for §11's RESEARCH_ELIGIBLE state and must
never be reported as confirmed patterns. They are a separate population with a separate
base rate." SNAPSHOT_SCHEMA.md's pattern object already reserves the field for this split:
`"population": "CONFIRMED | EARLY"`. Every record built here carries `population=POPULATION`
("EARLY") and nothing in this module ever writes or reads `research.charting.patterns`'
`PatternSnapshot` ("CONFIRMED") — the two populations are produced by entirely separate code
paths, on purpose, so neither can accidentally merge into the other's storage or reporting.

Detection scope (documented v1 decision — see `research/charting/early/__init__.py`): this
module detects a single shape, a rectangle/range-bound consolidation, using the same NI-2
primitives (`research.charting.swings`, `research.charting.geometry`) `patterns.py` uses for
its CONFIRMED rectangles, but with a much lower evidence bar — Stage 1 is explicitly about
*emerging* structure (§34.3: "Detect emerging support/resistance ... higher lows, lower
highs and improving structure"), so a single confirmed touch per side is enough to
instantiate a candidate here, where `patterns.py` requires `pattern_boundary_min_touches`
(2) before it will even attempt a CONFIRMED lifecycle. Touch count still feeds
`structural_quality` (via `geometry.level_strength`'s own `touch_c` component), so a
one-touch candidate simply scores low on structure rather than being hidden entirely —
"early" means less evidence, not zero evidence.

Point-in-time contract: `find_range_candidate_as_of` truncates to `bars.iloc[:t+1]` FIRST,
exactly like `swings.swings_as_of` and `scoring.compute_early_scores`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from research.charting.config import CONFIG
from research.charting.geometry import cluster_pivots_into_levels, rectangle_range_ok
from research.charting.series import atr
from research.charting.swings import find_swings

from .maturity import LiveMaturity, OfflineCheckpoint, live_maturity, offline_checkpoint_index
from .scoring import EarlyScores, ScoreValue, compute_early_scores

Direction = Literal["BULLISH", "BEARISH"]
FormationStage = Literal["EARLY_FORMATION", "PATTERN_DEVELOPING", "BREAKOUT_READINESS"]

# §34.2: the population tag that keeps every record in this module out of patterns.py's
# "CONFIRMED" population, for good, by construction.
POPULATION = "EARLY"


@dataclass(frozen=True)
class RangeCandidate:
    support: float
    resistance: float
    trigger_level: float
    invalidation_level: float
    formation_start: int
    atr_at_t: float


def find_range_candidate_as_of(bars: pd.DataFrame, t: int, cfg: dict = CONFIG) -> RangeCandidate | None:
    """The Stage 1-3 candidate visible using only `bars[0..t]`, or `None` if there is not
    yet at least one confirmed swing high AND one confirmed swing low forming a valid
    (§30.1 #4 range-checked) support/resistance pair. Truncates to `bars.iloc[:t+1]` before
    computing anything — see module docstring.
    """
    if t < 0 or t >= len(bars):
        raise ValueError(f"t={t} out of range for bars of length {len(bars)}")
    view = bars.iloc[: t + 1].reset_index(drop=True)

    atr_series = atr(view, period=cfg["atr_period"])
    atr_now = float(atr_series.iloc[-1])
    if not np.isfinite(atr_now) or atr_now <= 0:
        return None

    pivots = find_swings(view)
    if not pivots:
        return None
    highs = cluster_pivots_into_levels(pivots, view, atr_now, cfg, kind="HIGH")
    lows = cluster_pivots_into_levels(pivots, view, atr_now, cfg, kind="LOW")
    if not highs or not lows:
        return None

    best_high = max(highs, key=lambda l: len(l.touches))
    best_low = max(lows, key=lambda l: len(l.touches))
    if best_low.price >= best_high.price:
        return None
    range_check = rectangle_range_ok(best_high.price, best_low.price, atr_now, cfg)
    if not range_check.valid:
        return None

    formation_start = min(
        min(tt.pivot_index for tt in best_high.touches),
        min(tt.pivot_index for tt in best_low.touches),
    )
    buffer = cfg["breakout_buffer_atr"] * atr_now
    return RangeCandidate(
        support=best_low.price,
        resistance=best_high.price,
        trigger_level=best_high.price + buffer,
        invalidation_level=best_low.price - buffer,
        formation_start=formation_start,
        atr_at_t=atr_now,
    )


def first_detection_index_for(
    bars: pd.DataFrame, t: int, cfg: dict = CONFIG, *, price_tolerance: float = 1e-6
) -> int | None:
    """The earliest bar index `i` (`>= candidate.formation_start`, `<= t`) at which
    `find_range_candidate_as_of` first returns a candidate matching (within
    `price_tolerance`) the one visible at `t`. Each probed `i` is itself computed
    PIT-safely (`find_range_candidate_as_of` truncates first), so this forward scan never
    looks ahead of whichever index it is currently testing — it only ever asks "was this
    same structure already visible earlier?", never "will it still be there later?".
    Returns `None` if no candidate exists at `t` at all.
    """
    candidate_at_t = find_range_candidate_as_of(bars, t, cfg)
    if candidate_at_t is None:
        return None
    for i in range(candidate_at_t.formation_start, t + 1):
        c = find_range_candidate_as_of(bars, i, cfg)
        if (
            c is not None
            and abs(c.support - candidate_at_t.support) <= price_tolerance
            and abs(c.resistance - candidate_at_t.resistance) <= price_tolerance
        ):
            return i
    return t  # defensive fallback; unreachable in practice since t itself always matches


def classify_stage(*, live_mat: LiveMaturity, readiness: ScoreValue, formation: ScoreValue) -> FormationStage:
    """§34.3 Stage 1/2/3 label from the live maturity + the two most relevant §34.5 scores.
    Illustrative v1 thresholds, documented and not PRD-frozen — §34.5 itself calls its own
    component weights "illustrative starting weights ... must be validated through a
    pre-registered historical test", and the same caveat applies to these cut points.
    `EARLY_FORMATION` is the honest default whenever there isn't yet enough evidence to say
    more, per §34.3 ("A pattern may exit at any stage ... incomplete ... first-class
    outcomes, not missing data").
    """
    if readiness.status == "OK" and readiness.value is not None and readiness.value >= 0.66 and live_mat.maturity >= 0.5:
        return "BREAKOUT_READINESS"
    if live_mat.maturity >= 0.33 or (formation.status == "OK" and formation.value is not None and formation.value >= 0.4):
        return "PATTERN_DEVELOPING"
    return "EARLY_FORMATION"


@dataclass(frozen=True)
class EarlyFormationRecord:
    """§34.7's early-signal record, restricted to the fields this package can honestly fill
    (symbol/pattern_type/timestamps/levels/maturity/scores). `population` is always
    `POPULATION` ("EARLY"). Deliberately has NO `final_length` / `bars_to_breakout` /
    `t_end` field — §34.7.1's required test is that a checkpoint record built via
    `checkpoint_record()` cannot leak `t_end` into a stored value, and there being no field
    to put such a value in is the strongest form of that guarantee.
    """

    symbol: str
    pattern_type: str
    direction: Direction
    population: str
    formation_stage: FormationStage
    detection_timestamp: pd.Timestamp
    first_detection_index: int
    as_of_index: int
    as_of_date: pd.Timestamp
    formation_start: int
    trigger_level: float
    invalidation_level: float
    live_maturity: LiveMaturity
    scores: EarlyScores
    features_available_at_detection: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "pattern_type": self.pattern_type,
            "direction": self.direction,
            "population": self.population,
            "formation_stage": self.formation_stage,
            "detection_timestamp": self.detection_timestamp.isoformat(),
            "first_detection_index": self.first_detection_index,
            "as_of_index": self.as_of_index,
            "as_of_date": self.as_of_date.isoformat(),
            "formation_start": self.formation_start,
            "trigger_level": self.trigger_level,
            "invalidation_level": self.invalidation_level,
            "live_maturity": {
                "bars_since_first_detection": self.live_maturity.bars_since_first_detection,
                "minimum_pattern_length": self.live_maturity.minimum_pattern_length,
                "maturity": self.live_maturity.maturity,
            },
            "scores": self.scores.to_dict(),
            "features_available_at_detection": list(self.features_available_at_detection),
        }


def build_record_as_of(
    bars: pd.DataFrame,
    t: int,
    *,
    symbol: str,
    direction: Direction = "BULLISH",
    pattern_type: str = "RECTANGLE",
    cfg: dict = CONFIG,
    first_detection_index: int | None = None,
) -> EarlyFormationRecord | None:
    """Build the Stage 1-3 record visible using only `bars[0..t]`. Returns `None` if no
    candidate exists yet at `t` (§34.3: "incomplete ... first-class outcomes" — a caller
    walking bar-by-bar simply sees no record until one forms, rather than a fabricated
    placeholder).

    `first_detection_index`, when given, is trusted as-is (the §34.7.1 offline study's own
    use: it is `t_start`, chosen once from indices alone — see `checkpoint_record`). When
    omitted, it is discovered PIT-safely via `first_detection_index_for`.
    """
    candidate = find_range_candidate_as_of(bars, t, cfg)
    if candidate is None:
        return None

    fdi = first_detection_index if first_detection_index is not None else first_detection_index_for(bars, t, cfg)
    assert fdi is not None  # candidate is not None, so a match at >= formation_start always exists
    bars_since = t - fdi
    live_mat = live_maturity(bars_since, cfg)

    scores = compute_early_scores(
        bars, t,
        trigger_level=candidate.trigger_level,
        invalidation_level=candidate.invalidation_level,
        direction=direction,
        cfg=cfg,
    )
    stage = classify_stage(live_mat=live_mat, readiness=scores.readiness_score, formation=scores.formation_score)

    return EarlyFormationRecord(
        symbol=symbol,
        pattern_type=pattern_type,
        direction=direction,
        population=POPULATION,
        formation_stage=stage,
        detection_timestamp=pd.Timestamp(bars["date"].iloc[fdi]),
        first_detection_index=fdi,
        as_of_index=t,
        as_of_date=pd.Timestamp(bars["date"].iloc[t]),
        formation_start=candidate.formation_start,
        trigger_level=candidate.trigger_level,
        invalidation_level=candidate.invalidation_level,
        live_maturity=live_mat,
        scores=scores,
        features_available_at_detection=tuple(
            sorted(k for k, v in scores.components.items() if v.status == "OK")
        ),
    )


def checkpoint_record(
    bars: pd.DataFrame,
    *,
    t_start: int,
    t_end: int,
    fraction: float,
    symbol: str,
    direction: Direction = "BULLISH",
    pattern_type: str = "RECTANGLE",
    cfg: dict = CONFIG,
    first_detection_index: int | None = None,
) -> tuple[OfflineCheckpoint, EarlyFormationRecord]:
    """§34.7.1 definition 2. `t_end` is used ONLY by `offline_checkpoint_index`, to compute
    `t_ck` from two plain integer bar positions. From that point on `t_end` is never touched
    again: `build_record_as_of` is called with `t_ck`, which truncates to `bars[:t_ck+1]`
    before it computes a single value, and the returned `EarlyFormationRecord` has no field
    `t_end` could have populated. `t_start` doubles as `first_detection_index` unless the
    caller overrides it, so `live_maturity` is measured from the same fixed origin the
    checkpoint fraction itself is defined against.

    Raises if no candidate is detectable at `t_ck` — an offline study is expected to only
    call this once it already knows (from a completed live/CONFIRMED run) that a candidate
    existed there.
    """
    ck = offline_checkpoint_index(t_start, t_end, fraction)
    record = build_record_as_of(
        bars, ck.t_ck,
        symbol=symbol, direction=direction, pattern_type=pattern_type, cfg=cfg,
        first_detection_index=first_detection_index if first_detection_index is not None else t_start,
    )
    if record is None:
        raise ValueError(f"no range candidate found at offline checkpoint t_ck={ck.t_ck} (t_start={t_start}, t_end={t_end}, fraction={fraction})")
    return ck, record
