"""Movement-vs-direction measurement — CHART-S35, package D of the charting / pattern-
detection / historical-validation project (docs/charting.md; plan:
.claude/workspace/charting-pattern-engine/plan.md).

Pure measurement/reporting module — NO cost model, NO slippage, NO position sizing, NO
trading logic anywhere here (package-D scope). For every pattern *family*
(`PatternSnapshot.pattern_type`, e.g. "RECTANGLE" / "SUPPORT_RESISTANCE" / "HH_HL" — see
`patterns.py`; this module does not hardcode that set, it groups by whatever `pattern_type`
strings actually appear in its input, so a future fourth detector needs no change here) and
for each of three forward horizons (1, 3, 5 bars/sessions after a *confirmed* pattern
event), this module answers two separate, honest questions:

  1. Movement AUC  — does a signal measured AT the confirmation bar discriminate "a big
     move followed over the horizon" from "it didn't" — regardless of direction?
  2. Direction AUC — same population, same horizons; does the pattern's own BULLISH/
     BEARISH call predict the SIGN of the forward return instead?

── "Confirmed pattern event" ────────────────────────────────────────────────────────────
A `PatternSnapshot` (from `patterns.py`, typically gathered by running `detect_as_of` /
`replay.replay` over one or more symbols) counts as a *confirmed* pattern event iff its
`.events` list contains an entry with `event_type == "PRICE_CONFIRMED"` — the one §11
lifecycle event every family (RECTANGLE via `_walk_rectangle_lifecycle`,
SUPPORT_RESISTANCE via `_sr_level_patterns`, HH_HL via `_hh_hl_patterns`) emits, verbatim,
at the exact bar it first confirms. That event's own `date` field is the entry date used
for every forward calculation below. A pattern that only ever reached GEOMETRY_VALID /
BREAKOUT_ATTEMPT, or that went straight to INVALIDATED without ever confirming, never
produced a PRICE_CONFIRMED event and is therefore excluded — it never became a "confirmed
pattern event" to begin with (see `_confirmation_date`). What happens AFTER confirmation
(a later RETEST_SUCCESSFUL / FAILED / EXPIRED status) does not matter here: only the
(unique, first) PRICE_CONFIRMED date is used as the entry point, and "forward return" is
measured strictly after it.

`patterns_or_events` accepts, per item, either:
  - a bare `PatternSnapshot` (or an equivalent object/dict exposing `.pattern_id`,
    `.pattern_type`, `.direction`, `.events`, e.g. `PatternSnapshot.to_dict()`'s output) —
    the symbol is then recovered from the `pattern_id` convention
    `f"{symbol}:{pattern_type}:..."` used identically by every detector in `patterns.py`
    (verified against the module: RECTANGLE/SUPPORT_RESISTANCE/HH_HL all build
    `pattern_id` this way). This assumes a symbol never itself contains ":" — true of
    every symbol used in this codebase.
  - or an explicit `(symbol, snapshot)` 2-tuple, to sidestep that parsing entirely.

`bars_by_symbol` is `{symbol: bars_df}` with `bars_df` shaped like `config.BARS_COLUMNS`
(ascending, unique dates, one row per completed session) — exactly what `series.py` and
`patterns.py` already expect. Forward returns are read from these bars directly; this
module never re-derives anything `patterns.py`/`series.py` already computed, and never
looks at any symbol's bars other than the event's own `bars_by_symbol[symbol]` (no
cross-symbol leakage by construction — see `_series_for`).

── Forward return (requirement 2 — pure, no costs) ──────────────────────────────────────
    forward_log_return(entry, h) = ln(close[entry_index + h] / close[entry_index])
The LOG return from the confirmation bar's close to the close `h` bars later. Log (not
simple) return is used so "+10%" and "-10%" are symmetric in magnitude, which matters for
the movement side below. No transaction costs, no slippage, no position sizing — a pure
price ratio and nothing else.

── Movement definition (requirement 1) ──────────────────────────────────────────────────
    atr_pct_entry   = ATR(entry_index) / close(entry_index)     (Wilder ATR, `series.atr`,
                                                                  `config.CONFIG["atr_period"]`
                                                                  by default, re-expressed as
                                                                  a FRACTION of price so it is
                                                                  directly comparable to a log
                                                                  return)
    movement_score  = |forward_log_return| / atr_pct_entry
i.e. "how many ATR-implied-volatility units did price move over the horizon" — this is
exactly "|forward return| / ATR" from the task brief, with ATR expressed in matching
(dimensionless) units. The explicit, documented "big move" criterion (none is prescribed,
so this is this module's own choice):
    move_label = 1  if movement_score >= big_move_atr_multiple   (default 1.0)
                 0  otherwise
i.e. a "big move" is a forward move at least one entry-day ATR (in percentage terms) —
a fixed, absolute, population-independent threshold, matching the ATR-multiple convention
already used everywhere else in this engine (`breakout_buffer_atr`, `failure_buffer_atr`,
... in `config.py`).

The AUC's *predictor* is deliberately NOT `movement_score` (or anything built from the same
`atr_pct_entry` denominator): thresholding a ratio and then using that same ratio (or its
denominator) to "predict" the threshold is circular — for a fixed numerator, a bigger
denominator mechanically produces a smaller ratio, which would manufacture a spurious
negative relationship between "volatility" and "big move" purely from the algebra, not from
any real effect. Instead, the movement AUC ranks by a different, independent, generically
available signal measured at the SAME confirmation bar:
    move_score (AUC predictor) = relative_volume(entry_index)
                                = volume[entry] / mean(volume[entry-20 .. entry-1])
                                  (`series.relative_volume`, `config.CONFIG["volume_baseline_bars"]`)
i.e. "does elevated volume at the moment a pattern confirms predict a bigger subsequent
move" — the same volume-confirmation intuition `patterns.py`'s own RECTANGLE
`FOLLOWTHROUGH_VOLUME_*` rules already encode, generalised here to every family via a
fresh, independent computation from `bars_by_symbol` (no coupling to any family-specific
`levels`/`rules` field naming, so SUPPORT_RESISTANCE and HH_HL get it for free).

── Direction definition ─────────────────────────────────────────────────────────────────
Same population, same horizons (this is the task brief's own wording) — only the label and
predictor change:
    direction_label = 1 if forward_log_return > 0 else 0   (forward_log_return == 0 is
                                                              dropped, see below)
    direction_score = 1 if snapshot.direction == "BULLISH" else 0 (if "BEARISH")
NEUTRAL-direction snapshots assert no direction and are excluded from the direction AUC
only — see population note. Direction AUC therefore answers, literally: "does the
pattern's own BULLISH/BEARISH call predict the sign of the subsequent return."

── Population note ──────────────────────────────────────────────────────────────────────
Both AUCs start from the identical filtered set of confirmed events for a (family,
horizon): entry date resolvable in `bars_by_symbol[symbol]`, an exit bar
`entry_index + horizon` inside that symbol's bars, a finite positive `atr_pct_entry`, a
finite `relative_volume`, and a non-zero forward return. The direction AUC then further
restricts to the subset with a BULLISH/BEARISH call (never a differently-sampled
population). `move_n` and `direction_n` are reported separately per (family, horizon)
precisely because they can legitimately differ for this one reason — see
`FamilyHorizonReport`.

── AUC implementation (requirement 3) ───────────────────────────────────────────────────
scikit-learn is not a dependency of this repo (grepped `research/` and `backend/`: no hit),
so AUC is implemented directly via the Mann-Whitney U / rank-sum equivalence:
    AUC = P(score of a random positive > score of a random negative) + 0.5 * P(tie)
computed from average mid-ranks (`_rank_average`), the same construction
`scipy.stats.mannwhitneyu` uses internally for its U statistic. This is well-defined even
for a binary (0/1) predictor such as the direction score — see `test_movement.py`'s AUC
math tests (perfect / anti-correlated / tied-random cases).

── Honest edge cases (requirement 4) ────────────────────────────────────────────────────
AUC is mathematically UNDEFINED when only one class is present in the label (no negatives,
or no positives, to rank against) — this module never silently substitutes 0.5 or 1.0 for
that. `AucResult.auc` is `None` with `reason="single_class"` in that case, and
`reason="insufficient_n"` when both classes are present but the total is smaller than
`min_n` (default 10) — mathematically defined but not a size anyone should trust. `n` is
always reported, even when `auc is None`, so a tiny/degenerate family+horizon is never
mistaken for "no data" (it is reported, honestly, as unreliable).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from research.charting.config import CONFIG
from research.charting.research_window import assert_no_sealed_rows, research_bars
from research.charting.series import atr as atr_series_fn
from research.charting.series import relative_volume as relative_volume_series_fn

DEFAULT_HORIZONS: tuple[int, ...] = (1, 3, 5)
DEFAULT_BIG_MOVE_ATR_MULTIPLE = 1.0
DEFAULT_MIN_N = 10

_CONFIRMED_EVENT_TYPE = "PRICE_CONFIRMED"


@dataclass(frozen=True)
class AucResult:
    """One AUC estimate. `auc` is `None` (never a placeholder number) whenever it is not
    meaningfully defined — see `reason` ("single_class" | "insufficient_n")."""

    auc: Optional[float]
    n: int
    reason: Optional[str] = None  # always None when auc is not None, always set when it is

    def to_dict(self) -> dict:
        return {"auc": self.auc, "n": self.n, "reason": self.reason}


@dataclass(frozen=True)
class FamilyHorizonReport:
    """Everything requirement 4 asks for, for one (family, horizon) cell."""

    family: str
    horizon: int
    move: AucResult
    direction: AucResult

    def to_dict(self) -> dict:
        return {
            "family": self.family,
            "horizon": self.horizon,
            "move_auc": self.move.auc,
            "move_n": self.move.n,
            "move_reason": self.move.reason,
            "direction_auc": self.direction.auc,
            "direction_n": self.direction.n,
            "direction_reason": self.direction.reason,
        }


# ── AUC math (requirement 3: Mann-Whitney U / rank-sum, no external ML dependency) ───────


def _rank_average(values: np.ndarray) -> np.ndarray:
    """1-indexed average (mid-)ranks, ties sharing the mean of the ranks they span — the
    same convention as `scipy.stats.rankdata(..., method="average")`, reimplemented
    directly since this is the only thing this module would otherwise need scipy for."""
    order = np.argsort(values, kind="mergesort")
    sorted_vals = values[order]
    n = len(values)
    ranks = np.empty(n, dtype=float)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        ranks[order[i : j + 1]] = avg_rank
        i = j + 1
    return ranks


def auc_from_scores_and_labels(
    scores: Sequence[float], labels: Sequence[int], *, min_n: int = DEFAULT_MIN_N
) -> AucResult:
    """Mann-Whitney U / rank-sum AUC: `P(score of random label==1 > score of random
    label==0) + 0.5 * P(tie)`. `labels` must be binary (0/1); `scores` is any real-valued
    ranking signal — ties are allowed and handled via average mid-ranks.

    Honest edge cases (requirement 4):
      - fewer than one example of either class -> AUC is mathematically UNDEFINED ->
        `AucResult(None, n, reason="single_class")`, never a guessed 0.5 or 1.0.
      - `n < min_n` (default 10) -> `AucResult(None, n, reason="insufficient_n")` — the
        math is well-defined here, just not trustworthy at that sample size.
    """
    scores_arr = np.asarray(scores, dtype=float)
    labels_arr = np.asarray(labels, dtype=int)
    n = len(scores_arr)
    if n != len(labels_arr):
        raise ValueError("scores and labels must be the same length")

    n_pos = int(np.sum(labels_arr == 1))
    n_neg = int(np.sum(labels_arr == 0))
    if n_pos == 0 or n_neg == 0:
        return AucResult(auc=None, n=n, reason="single_class")
    if n < min_n:
        return AucResult(auc=None, n=n, reason="insufficient_n")

    ranks = _rank_average(scores_arr)
    sum_ranks_pos = float(np.sum(ranks[labels_arr == 1]))
    u_pos = sum_ranks_pos - n_pos * (n_pos + 1) / 2.0
    auc = u_pos / (n_pos * n_neg)
    return AucResult(auc=auc, n=n, reason=None)


# ── Extracting confirmed pattern events from patterns_or_events ─────────────────────────


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _confirmation_date(events: Optional[list]) -> Optional[str]:
    """The date of the (unique, first) PRICE_CONFIRMED event in a snapshot's `events`
    list, or `None` if the pattern never confirmed — see module docstring."""
    if not events:
        return None
    confirmed = [e for e in events if e.get("event_type") == _CONFIRMED_EVENT_TYPE]
    if not confirmed:
        return None
    return confirmed[0]["date"]


@dataclass(frozen=True)
class _ConfirmedEvent:
    symbol: str
    family: str
    direction: str
    entry_date: str


def _normalize_item(item: Any) -> Optional[_ConfirmedEvent]:
    """One item of `patterns_or_events` -> a `_ConfirmedEvent`, or `None` if it never
    reached PRICE_CONFIRMED (excluded — it is not a "confirmed pattern event")."""
    if isinstance(item, tuple) and len(item) == 2:
        symbol, snapshot = item
    else:
        snapshot = item
        pattern_id = _get(snapshot, "pattern_id")
        if not pattern_id or ":" not in pattern_id:
            return None
        symbol = pattern_id.split(":", 1)[0]

    entry_date = _confirmation_date(_get(snapshot, "events"))
    if entry_date is None:
        return None
    family = _get(snapshot, "pattern_type")
    direction = _get(snapshot, "direction")
    if not family or not direction:
        return None
    return _ConfirmedEvent(symbol=str(symbol), family=str(family), direction=str(direction), entry_date=str(entry_date))


# ── Per-symbol precomputation (never mixes one symbol's bars into another's lookup) ──────


@dataclass(frozen=True)
class _SymbolSeries:
    close: np.ndarray
    atr_pct: np.ndarray  # ATR / close, aligned to bars.index
    rel_volume: np.ndarray
    date_index: dict  # pd.Timestamp -> int, this symbol's own bars only


def _build_symbol_series(bars: pd.DataFrame, atr_period: int, volume_baseline_bars: int) -> _SymbolSeries:
    close = bars["close"].to_numpy(dtype=float)
    atr_vals = atr_series_fn(bars, period=atr_period).to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        atr_pct = np.where(close != 0, atr_vals / close, np.nan)
    rel_vol = relative_volume_series_fn(bars, n=volume_baseline_bars).to_numpy(dtype=float)
    date_index = {pd.Timestamp(d): i for i, d in enumerate(bars["date"])}
    return _SymbolSeries(close=close, atr_pct=atr_pct, rel_volume=rel_vol, date_index=date_index)


# ── Main entry point ─────────────────────────────────────────────────────────────────────


def movement_vs_direction_report(
    patterns_or_events: Iterable[Any],
    bars_by_symbol: Mapping[str, pd.DataFrame],
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    *,
    atr_period: int = CONFIG["atr_period"],
    volume_baseline_bars: int = CONFIG["volume_baseline_bars"],
    big_move_atr_multiple: float = DEFAULT_BIG_MOVE_ATR_MULTIPLE,
    min_n: int = DEFAULT_MIN_N,
) -> dict[tuple[str, int], FamilyHorizonReport]:
    """Movement-vs-direction AUC report, grouped by (pattern family, forward horizon).

    See the module docstring for the exact movement / direction / AUC definitions. Returns
    a dict keyed by `(family, horizon)` -> `FamilyHorizonReport`. Every pattern family that
    contributed at least one confirmed event gets an entry for every horizon in `horizons`
    — even a horizon where zero of its events happen to resolve still gets an explicit
    `AucResult(None, n=0, reason="single_class")` rather than silently vanishing from the
    report. A `patterns_or_events` with no confirmed events at all yields `{}`.

    Sealed-window guard (review 2026-09-22, defect #1): this is a RESEARCH evaluation path,
    so before any AUC computation happens, every confirmed event's own entry (confirmation)
    date is checked against the project-wide sealed 2023-01-01..2024-07-31 out-of-sample
    block, and so is every symbol's bars frame as a whole: the ATR / relative-volume lookback
    and the forward exit bar both read from it, so a frame whose dates span the sealed block
    (an entry in Dec 2022 whose 5-bar exit lands in Jan 2023, or a 2024-08 entry whose ATR
    warms up on sealed bars) raises `research_window.SealedWindowError`. Pass pre- and
    post-sealed bars as separate runs -- no research evaluation may touch this window.
    """
    events = [e for e in (_normalize_item(item) for item in patterns_or_events) if e is not None]
    assert_no_sealed_rows(e.entry_date for e in events)

    series_cache: dict[str, Optional[_SymbolSeries]] = {}

    def _series_for(symbol: str) -> Optional[_SymbolSeries]:
        if symbol not in series_cache:
            bars = bars_by_symbol.get(symbol)
            if bars is not None:
                research_bars(bars)  # lookback and forward bars both come from this frame
            series_cache[symbol] = None if bars is None else _build_symbol_series(bars, atr_period, volume_baseline_bars)
        return series_cache[symbol]

    families = sorted({e.family for e in events})
    report: dict[tuple[str, int], FamilyHorizonReport] = {}

    for family in families:
        family_events = [e for e in events if e.family == family]
        for h in horizons:
            move_scores: list[float] = []
            move_labels: list[int] = []
            dir_scores: list[float] = []
            dir_labels: list[int] = []

            for ev in family_events:
                s = _series_for(ev.symbol)
                if s is None:
                    continue  # symbol not supplied — excluded, never borrows another symbol's bars
                entry_idx = s.date_index.get(pd.Timestamp(ev.entry_date))
                if entry_idx is None:
                    continue  # confirmation date not found in THIS symbol's own bars
                exit_idx = entry_idx + h
                if exit_idx >= len(s.close):
                    continue  # not enough forward data for this horizon
                entry_close = s.close[entry_idx]
                exit_close = s.close[exit_idx]
                if not (np.isfinite(entry_close) and entry_close > 0 and np.isfinite(exit_close) and exit_close > 0):
                    continue
                atr_pct_entry = s.atr_pct[entry_idx]
                rel_vol_entry = s.rel_volume[entry_idx]
                if not (np.isfinite(atr_pct_entry) and atr_pct_entry > 0 and np.isfinite(rel_vol_entry)):
                    continue  # ATR/relative-volume still in warmup at this entry bar

                forward_log_return = float(np.log(exit_close / entry_close))
                if forward_log_return == 0.0:
                    continue  # sign undefined — see module docstring

                movement_score = abs(forward_log_return) / atr_pct_entry
                move_scores.append(rel_vol_entry)
                move_labels.append(1 if movement_score >= big_move_atr_multiple else 0)

                if ev.direction in ("BULLISH", "BEARISH"):
                    dir_scores.append(1.0 if ev.direction == "BULLISH" else 0.0)
                    dir_labels.append(1 if forward_log_return > 0 else 0)

            move_result = auc_from_scores_and_labels(move_scores, move_labels, min_n=min_n)
            dir_result = auc_from_scores_and_labels(dir_scores, dir_labels, min_n=min_n)
            report[(family, h)] = FamilyHorizonReport(family=family, horizon=h, move=move_result, direction=dir_result)

    return report


def report_to_rows(report: Mapping[tuple[str, int], FamilyHorizonReport]) -> list[dict]:
    """`report` as a flat list of plain dicts, sorted by (family, horizon) — convenient for
    printing / asserting in tests / serialising."""
    return [report[key].to_dict() for key in sorted(report.keys())]
