"""Selection metrics: how good are the TOP-RANKED rows, not how good is the ranking overall.

AUC answers "does the model order the whole population correctly". That is not the use case. The
use case picks a handful of stocks, so what matters is whether the rows it ranks highest actually
contain more winners than chance. A model can carry a respectable AUC and still have a flat top
decile, and that model is worthless for picking.

REBUILT 2026-09-30. The original was lost before it was ever committed. This is a reimplementation
from its call sites, not the same file, so `validate()` below re-establishes the sanity checks
rather than assuming them: a strong ranker must land near 2x on the top decile and pure noise must
land near 1.0.
"""

from __future__ import annotations

import math
from typing import Sequence


def decile_lift(scores: Sequence[float], y: Sequence[int], top: float = 0.10) -> dict:
    """Positive rate among the top `top` fraction by score, divided by the overall positive rate.

    lift 1.0 means the top slice is no better than picking at random; 2.0 means twice the base rate.

    Returns `lift: None` rather than a number whenever the quantity is undefined — no rows, no
    positives anywhere (nothing to concentrate), or a slice too small to mean anything. A caller
    that prints 0.0 for those is saying "no edge" when the truth is "not measurable", and those are
    different claims.
    """
    n = len(scores)
    if n != len(y):
        raise ValueError(f"scores/y length mismatch: {n} vs {len(y)}")
    if not 0.0 < top <= 1.0:
        raise ValueError(f"top must be in (0, 1]: {top}")

    out: dict = {"n": n, "top": top, "lift": None, "n_top": 0, "hits_top": 0,
                 "rate_top": None, "base_rate": None, "tied_at_cutoff": False}
    if n == 0:
        return out

    pos = sum(1 for v in y if v)
    base = pos / n
    out["base_rate"] = base
    if pos == 0 or pos == n:
        return out                      # nothing to concentrate, or everything is a hit

    k = max(1, math.ceil(n * top))
    if k >= n:
        return out                      # "top 100%" is the base rate by construction

    order = sorted(range(n), key=lambda i: (-scores[i], i))
    sel = order[:k]
    # A cutoff sitting inside a run of equal scores means the membership of the slice is decided by
    # the tie-break, not by the model. Flag it: with a coarse score this silently drives the number.
    cut = scores[order[k - 1]]
    out["tied_at_cutoff"] = scores[order[k]] == cut

    hits = sum(1 for i in sel if y[i])
    out["n_top"], out["hits_top"] = k, hits
    out["rate_top"] = hits / k
    out["lift"] = (hits / k) / base
    return out


def validate(seed: int = 7, n: int = 20_000) -> list[str]:
    """Re-establish the two sanity anchors. Returns failures; empty means the metric behaves."""
    import random
    rng = random.Random(seed)
    fails: list[str] = []

    # 1. pure noise: score independent of outcome -> top decile is the base rate
    y = [1 if rng.random() < 0.30 else 0 for _ in range(n)]
    s = [rng.random() for _ in range(n)]
    noise = decile_lift(s, y, top=0.10)["lift"]
    if noise is None or not 0.90 <= noise <= 1.10:
        fails.append(f"noise lift {noise} outside 0.90-1.10 (should be ~1.0)")

    # 2. a strong ranker: score correlated with the outcome -> top decile well above base
    y2, s2 = [], []
    for _ in range(n):
        hit = rng.random() < 0.30
        y2.append(1 if hit else 0)
        s2.append(rng.gauss(1.0 if hit else 0.0, 1.0))
    strong = decile_lift(s2, y2, top=0.10)["lift"]
    if strong is None or strong < 1.8:
        fails.append(f"strong-model lift {strong} below 1.8 (a real signal must concentrate)")

    # 3. a perfect ranker at top=base_rate must be exactly 1/base
    y3 = [1] * 300 + [0] * 700
    s3 = [1.0] * 300 + [0.0] * 700
    perfect = decile_lift(s3, y3, top=0.30)
    if perfect["lift"] is None or abs(perfect["lift"] - (1 / 0.30)) > 1e-6:
        fails.append(f"perfect ranker gave {perfect['lift']}, expected {1/0.30:.4f}")
    if perfect["tied_at_cutoff"]:
        fails.append("a cutoff falling exactly between two score blocks is NOT a tie")

    # 3b. a tie that genuinely STRADDLES the cutoff must be flagged: here the slice boundary lands
    # inside a run of equal scores, so which rows are selected is decided by the tie-break and not
    # by the model.
    y4 = [1, 0] * 50
    s4 = [5.0] * 10 + [1.0] * 80 + [0.0] * 10        # top=0.20 -> k=20, cutoff inside the 1.0 run
    straddle = decile_lift(s4, y4, top=0.20)
    if not straddle["tied_at_cutoff"]:
        fails.append("a tie spanning the cutoff must set tied_at_cutoff")

    # 4. undefined cases must be None, never 0.0
    for bad, why in ((([1.0, 2.0], [0, 0]), "no positives"),
                     (([1.0, 2.0], [1, 1]), "all positives"),
                     ((([], [])), "empty")):
        if decile_lift(bad[0], bad[1], top=0.5)["lift"] is not None:
            fails.append(f"{why}: lift must be None, not a number")
    return fails


if __name__ == "__main__":
    import sys
    problems = validate()
    for p in problems:
        print("FAIL:", p)
    if problems:
        sys.exit(1)
    print("validate(): all sanity anchors pass")
    for t in (0.01, 0.05, 0.10):
        print(f"  reference, strong ranker top {t:.0%}: ", end="")
        import random
        rng = random.Random(7); ys, ss = [], []
        for _ in range(20_000):
            h = rng.random() < 0.30
            ys.append(1 if h else 0); ss.append(rng.gauss(1.0 if h else 0.0, 1.0))
        r = decile_lift(ss, ys, top=t)
        print(f"lift {r['lift']:.2f}  (top {r['n_top']:,} rows, {r['hits_top']:,} hits, base {r['base_rate']:.1%})")
