"""Calibration (PRD F6): does stated confidence match what happened? Reliability bins and the Brier score."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

BIN_EDGES = (0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)   # the first bin is "below 0.5"; the last includes 1.0


class CalibrationError(ValueError):
    pass


def _bin_index(c: float) -> int:
    for i in range(len(BIN_EDGES) - 1):
        hi = BIN_EDGES[i + 1]
        if c < hi or (i == len(BIN_EDGES) - 2 and c <= hi):
            return i
    raise CalibrationError(f"confidence {c!r} outside [0, 1]")


def calibration_report(predictions: Iterable[Tuple[float, bool]]) -> Dict[str, Any]:
    """`predictions` = (stated confidence in [0, 1], whether the call came true). Returns the reliability bins, the
    Brier score (mean squared error of confidence against 0/1) and the calibration error (n-weighted mean of
    |observed - stated| over the bins). An empty input gives n = 0 and no scores, never zeros."""
    rows: List[Tuple[float, int]] = []
    for c, hit in predictions:
        if isinstance(c, bool) or not isinstance(c, (int, float)) or not 0.0 <= float(c) <= 1.0:
            raise CalibrationError(f"confidence {c!r} outside [0, 1]")
        rows.append((float(c), 1 if hit else 0))

    bins = [{"low": BIN_EDGES[i], "high": BIN_EDGES[i + 1], "n": 0, "_c": 0.0, "_h": 0} for i in range(len(BIN_EDGES) - 1)]
    for c, h in rows:
        b = bins[_bin_index(c)]
        b["n"] += 1
        b["_c"] += c
        b["_h"] += h

    out_bins, weighted_gap = [], 0.0
    for b in bins:
        n = b["n"]
        mean_conf = b["_c"] / n if n else None
        observed = b["_h"] / n if n else None
        if n:
            weighted_gap += n * abs(observed - mean_conf)
        out_bins.append({"low": b["low"], "high": b["high"], "n": n,
                         "mean_confidence": mean_conf, "observed_rate": observed})

    n = len(rows)
    return {
        "n": n,
        "bins": out_bins,
        "brier": (sum((c - h) ** 2 for c, h in rows) / n) if n else None,
        "calibration_error": (weighted_gap / n) if n else None,
    }
