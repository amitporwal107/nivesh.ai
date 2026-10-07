"""Market sensitivity: WHERE does the model work? (PATTERN_VALIDATION_PRD_V1 §33)

THE QUESTION THIS ANSWERS
-------------------------
The race-label ladder reached AUC 0.740 on a symmetric direction question whose raw base rate is a
coin flip (48.6%). That would be a significant result -- and it is measured on 2021-01..2022-12,
which contained an enormous Indian small-cap bull run. In a rising market, JUMPY STOCKS GO UP, so
"how volatile is it" can look like it predicts direction when it is really detecting "the market
went up". Volatility alone scoring 0.629 on a question it should be blind to is the tell.

So: one model, evaluated WITHIN each market condition. If the edge is real it survives across
regimes. If it is the bull run, it concentrates in the rising segments and collapses elsewhere.

ONE MODEL, NOT ONE PER SEGMENT. Fitting separately per regime would be a different experiment on a
fraction of the n, and the differences between segments would partly be fitting noise. These are
the SAME out-of-fold predictions, partitioned.

THRESHOLDS ARE CONVENTIONAL AND FIXED IN ADVANCE. §33 requires predefined rules, not categories
invented after seeing results. In-sample terciles would be exactly that mistake: the cut points
would be chosen by the data being tested.
"""
from __future__ import annotations

from typing import Mapping, Optional, Sequence

from research.charting.baselines import ladder as L


#: India VIX bands. Conventional levels, not fitted: <15 calm, 15-20 normal, >20 stressed.
VIX_BANDS = ((None, 15.0, "VIX_LOW"), (15.0, 20.0, "VIX_MID"), (20.0, None, "VIX_HIGH"))

#: Breadth: share of the universe above its 200-day average. The classic "is the whole market
#: participating" measure, and the most direct proxy for the confound this module exists to test.
#: <30% weak, 30-60% mixed, >60% strong -- the conventional reading, fixed before looking.
BREADTH_BANDS = ((None, 0.30, "BREADTH_WEAK"), (0.30, 0.60, "BREADTH_MIXED"),
                 (0.60, None, "BREADTH_STRONG"))

#: Advance/decline ratio: <0.8 declining, 0.8-1.2 balanced, >1.2 advancing.
AD_BANDS = ((None, 0.8, "AD_DECLINING"), (0.8, 1.2, "AD_BALANCED"), (1.2, None, "AD_ADVANCING"))


def _band(value: Optional[float], bands) -> str:
    if value is None:
        return "UNKNOWN"
    for lo, hi, name in bands:
        if (lo is None or value >= lo) and (hi is None or value < hi):
            return name
    return "UNKNOWN"


def _get(row: Mapping, *path):
    cur = row
    for k in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(k)
        if cur is None:
            return None
    return cur


def segment_labels(row: Mapping) -> dict:
    """Every predefined market condition for one row. `UNKNOWN` is a real bucket, reported rather
    than dropped -- a segment that silently excludes its missing rows overstates its own coverage.
    """
    ctx = row.get("context") or {}
    date = (row.get("signal_date") or "")[:7]
    half = f"{date[:4]}H{1 if date[5:7] and int(date[5:7]) <= 6 else 2}" if len(date) >= 7 else "UNKNOWN"
    return {
        "regime": ctx.get("regime_regime") or "UNKNOWN",
        "breadth_sma200": _band(ctx.get("breadth_pct_above_sma200"), BREADTH_BANDS),
        "breadth_ad": _band(ctx.get("breadth_advance_decline_ratio"), AD_BANDS),
        "vix": _band(ctx.get("india_vix_close"), VIX_BANDS),
        "half_year": half,
        "market_trend": ctx.get("market_trend_class_class") or "UNKNOWN",
    }


DIMENSIONS = ("regime", "breadth_sma200", "breadth_ad", "vix", "half_year", "market_trend")


def by_segment(oof: Mapping[int, float], labels: Sequence[int], segs: Sequence[Mapping],
               dimension: str, *, min_n: int = 200) -> list:
    """AUC of the SAME model within each bucket of one dimension.

    `min_n` is a floor, not a filter: a bucket below it is reported with its n and an
    INSUFFICIENT_N marker instead of a number, never omitted. An omitted bucket reads as "we
    checked and found nothing", which is the failure the PRD's §10a rule exists to prevent.
    """
    buckets: dict = {}
    for i, p in oof.items():
        buckets.setdefault(segs[i][dimension], []).append((p, labels[i]))
    out = []
    for name, pairs in sorted(buckets.items()):
        n = len(pairs)
        pos = sum(y for _p, y in pairs)
        if n < min_n or pos == 0 or pos == n:
            out.append({"segment": name, "n": n, "auc": None, "base_rate": pos / n if n else None,
                        "note": "INSUFFICIENT_N"})
            continue
        out.append({"segment": name, "n": n, "base_rate": pos / n,
                    "auc": L.auc([p for p, _y in pairs], [y for _p, y in pairs]), "note": None})
    return out


def increment_by_segment(oof_base: Mapping[int, float], oof_full: Mapping[int, float],
                         labels: Sequence[int], segs: Sequence[Mapping], dimension: str,
                         *, min_n: int = 200) -> list:
    """The PATTERN INCREMENT within each bucket -- the number that matters.

    A pattern that only adds information when the market is already rising is not a pattern signal;
    it is a market signal wearing one. This is the test that distinguishes them, and it is why the
    increment is segmented rather than only the absolute AUC.
    """
    base = {d["segment"]: d for d in by_segment(oof_base, labels, segs, dimension, min_n=min_n)}
    full = {d["segment"]: d for d in by_segment(oof_full, labels, segs, dimension, min_n=min_n)}
    out = []
    for name in sorted(set(base) | set(full)):
        b, f = base.get(name, {}), full.get(name, {})
        inc = (f.get("auc") - b.get("auc")) if (f.get("auc") is not None and b.get("auc") is not None) else None
        out.append({"segment": name, "n": b.get("n") or f.get("n"), "base_auc": b.get("auc"),
                    "full_auc": f.get("auc"), "increment": inc,
                    "note": b.get("note") or f.get("note")})
    return out
