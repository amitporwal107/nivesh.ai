"""Small statistics helpers: no numpy, deterministic."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

MIN_SERIES = 8          # fewer sessions than this gives no standard error


def mean(xs: Sequence[float]) -> Optional[float]:
    return sum(xs) / len(xs) if xs else None


def nw_se(series: Sequence[float], lag: int) -> Optional[float]:
    """Newey-West standard error of the mean (Bartlett weights, `lag` autocovariances): forward windows that overlap make
    neighbouring sessions' outcomes dependent, so a plain standard error would overstate the evidence."""
    n = len(series)
    if n < MIN_SERIES:
        return None
    m = sum(series) / n
    d = [x - m for x in series]
    var = sum(x * x for x in d) / n
    for l in range(1, min(lag, n - 1) + 1):
        cov = sum(d[i] * d[i - l] for i in range(l, n)) / n
        var += 2.0 * (1.0 - l / (lag + 1.0)) * cov
    return math.sqrt(max(var, 0.0) / n)


def summarize(series: Sequence[float], lag: int) -> Dict[str, Any]:
    """{n, mean, se, t}: se and t are None when the series is too short or has no spread."""
    n = len(series)
    m = mean(series)
    se = nw_se(series, lag)
    t = None if (m is None or se is None or se <= 0) else m / se
    return {"n": n, "mean": None if m is None else round(m, 4), "se": None if se is None else round(se, 4), "t": None if t is None else round(t, 2)}


def _ranks(xs: Sequence[float]) -> List[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def spearman(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    """Rank correlation with average ranks for ties; None below 4 pairs or when either side has no spread."""
    if len(x) != len(y) or len(x) < 4:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / math.sqrt(sxx * syy)


def canonical_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
